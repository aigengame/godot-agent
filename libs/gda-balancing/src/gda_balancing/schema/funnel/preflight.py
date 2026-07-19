"""Phase 0 — preflight: ingress caps, duplicate-key refusal, version dispatch.

The funnel's first phase (bADR-0004). Its sub-steps are strictly ordered and
each is *terminal on failure*, but *report-all within a sub-step*: sub-steps
1-4 (byte cap, UTF-8, depth pre-scan, parse) short-circuit the rest as soon as
one refuses — nothing downstream can run without a decoded, parsed, pinned
document; sub-steps 5 (the caps walk) and 6 (version dispatch) run together, so
a document with both a cap violation and a bad ``schema_version`` reports both
in one round trip.

The depth pre-scan (sub-step 3) runs *before* ``json.loads`` specifically so a
pathologically deep document becomes a typed ``nesting_too_deep`` refusal
rather than a ``RecursionError`` — a crash (exit 4) would reclassify a resource
bound as a toolkit fault. Preflight resolves the version but does not yet build
the typed document; the structural/semantic phases (later stages) do.

``number_not_finite`` is a preflight-family addition *beyond* bADR-0004's
listed caps (byte size, nesting depth, collection size, expression-tree
limits). Justification: JSON's grammar admits numeric literals with no
finite IEEE-754 double representation (e.g. ``1e999`` parses to ``inf``), and
canonical emission runs ``allow_nan=False`` (bADR-0005) — an ``inf`` slipping
past preflight would surface as a crash-class emission failure downstream. Per
bADR-0004's own spirit ("resource exhaustion is a refusal class, not a crash
class"), an unrepresentable number is refused at ingress, not crashed on later.
"""

import json
import math
from collections.abc import Callable
from typing import Any

from gda_balancing.envelope import Refusal
from gda_balancing.schema import pointer
from gda_balancing.schema.version import line_accepted, parse_line

# v1 normative ingress caps (bADR-0004); raising any is a minor schema bump.
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # 10 MiB
MAX_NESTING_DEPTH = 64
MAX_COLLECTION_ELEMENTS = 10_000

# Every stable refusal code preflight can emit. The funnel's public
# ``refusal_code_namespace`` currently *is* this set; later stages union the
# structural code and the semantic catalog into it. The conformance harness
# asserts every emitted refusal code resolves against that namespace.
PREFLIGHT_CODES: frozenset[str] = frozenset(
    {
        "document_too_large",
        "nesting_too_deep",
        "malformed_json",
        "duplicate_object_key",
        "collection_too_large",
        "number_not_finite",
        "malformed_schema_version",
        "unsupported_schema_version",
    }
)

_VERSION_KEY = "schema_version"
_VERSION_PATH = pointer.build(_VERSION_KEY)


def preflight(data: bytes) -> tuple[list[Refusal], object | None]:
    """Run Phase 0 over the raw document bytes; return ``(refusals, root)``.

    An empty refusal list means preflight passed and ``root`` is the parsed
    document the structural/semantic phases validate. ``root`` is ``None``
    whenever a **terminal** sub-step (1-4, and duplicate keys) refused before a
    usable document existed; sub-steps 5-6 (caps + version dispatch) refuse *with*
    the parsed root in hand, but the funnel returns on any preflight refusal, so
    that root is never consumed. Refusals are raw (dedup/order/truncate is
    :mod:`report`'s job), in discovery order.
    """
    # 1. Byte cap (terminal) — checked on bytes so it never depends on decode.
    if len(data) > MAX_DOCUMENT_BYTES:
        return [
            Refusal(
                code="document_too_large",
                path="",
                detail=f"document exceeds the {MAX_DOCUMENT_BYTES}-byte cap",
            )
        ], None

    # 2. UTF-8 decode (terminal).
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [Refusal(code="malformed_json", path="", detail="not valid UTF-8")], None

    # 3. Depth pre-scan (terminal) — string-aware, before json.loads.
    if _max_nesting_depth(text) > MAX_NESTING_DEPTH:
        return [
            Refusal(
                code="nesting_too_deep",
                path="",
                detail=f"nesting exceeds the depth-{MAX_NESTING_DEPTH} cap",
            )
        ], None

    # 4. Parse with a duplicate-key-detecting hook (terminal). Duplicate object
    # keys are refused: map keys are id authorities (bADR-0002), so a lenient
    # parser silently keeping the last value would void structural uniqueness.
    duplicates: list[str] = []
    try:
        root = json.loads(text, object_pairs_hook=_dedup_hook(duplicates))
    except json.JSONDecodeError as exc:
        return [Refusal(code="malformed_json", path="", detail=str(exc))], None
    if duplicates:
        return [
            Refusal(
                code="duplicate_object_key",
                path="",
                detail=f"duplicate object key: {name!r}",
            )
            for name in duplicates
        ], None

    # 5 + 6 report together (both are non-terminal within preflight).
    refusals: list[Refusal] = []
    _walk_caps(root, (), refusals)
    refusals.extend(_version_dispatch(root))
    return refusals, root


def _dedup_hook(duplicates: list[str]) -> Callable[[list[tuple[str, Any]]], Any]:
    """A ``json.loads`` ``object_pairs_hook`` that records every duplicated key
    name into ``duplicates`` while still collapsing to a last-wins dict — so
    report-all sees every offending key yet the parsed value stays usable."""

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        for key, _ in pairs:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        return dict(pairs)

    return hook


def _max_nesting_depth(text: str) -> int:
    """The maximum ``{``/``[`` nesting depth outside JSON string literals.

    A single O(n) scan tracking in-string and escape state, so structural
    brackets *inside* string values never inflate the count. Runs before the
    parser so a too-deep document is refused, never recursed into.
    """
    depth = 0
    deepest = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
            deepest = max(deepest, depth)
        elif char in "}]":
            depth -= 1
    return deepest


def _walk_caps(
    value: object, tokens: tuple[str | int, ...], refusals: list[Refusal]
) -> None:
    """Path-tracked walk collecting every collection-size and non-finite
    violation (report-all). Recursion is bounded: the depth pre-scan already
    guaranteed depth ``<= MAX_NESTING_DEPTH``."""
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ELEMENTS:
            refusals.append(_too_large(tokens, len(value)))
        for key, item in value.items():
            _walk_caps(item, (*tokens, key), refusals)
    elif isinstance(value, list):
        if len(value) > MAX_COLLECTION_ELEMENTS:
            refusals.append(_too_large(tokens, len(value)))
        for index, item in enumerate(value):
            _walk_caps(item, (*tokens, index), refusals)
    elif isinstance(value, float):
        # A JSON numeric literal with no finite double (e.g. 1e999 -> inf).
        if not math.isfinite(value):
            refusals.append(
                Refusal(
                    code="number_not_finite",
                    path=pointer.build(*tokens),
                    detail="number has no finite IEEE-754 double value",
                )
            )


def _too_large(tokens: tuple[str | int, ...], size: int) -> Refusal:
    return Refusal(
        code="collection_too_large",
        path=pointer.build(*tokens),
        detail=(
            f"collection has {size} entries, over the "
            f"{MAX_COLLECTION_ELEMENTS}-element cap"
        ),
    )


def _version_dispatch(root: object) -> list[Refusal]:
    """Resolve the declared ``schema_version`` to a supported line (bADR-0001).

    The root must be an object carrying a full-semver string the validator
    both understands (``parse_line``) and serves (``line_accepted``). Patch is
    ignored by construction — ``parse_line`` drops it — so ``1.0.999`` on a
    ``1.0`` validator is accepted.
    """
    if not isinstance(root, dict):
        return [
            Refusal(
                code="malformed_schema_version",
                path=_VERSION_PATH,
                detail="document root is not a JSON object",
            )
        ]
    raw = root.get(_VERSION_KEY)
    if not isinstance(raw, str):
        return [
            Refusal(
                code="malformed_schema_version",
                path=_VERSION_PATH,
                detail="schema_version is missing or not a string",
            )
        ]
    line = parse_line(raw)
    if line is None:
        return [
            Refusal(
                code="malformed_schema_version",
                path=_VERSION_PATH,
                detail=f"schema_version {raw!r} is not a full semver string",
            )
        ]
    if not line_accepted(line):
        return [
            Refusal(
                code="unsupported_schema_version",
                path=_VERSION_PATH,
                detail=f"schema line {line} is not supported by this validator",
            )
        ]
    return []
