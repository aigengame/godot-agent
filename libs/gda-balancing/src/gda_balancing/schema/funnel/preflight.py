"""Phase 0 — preflight: ingress caps, duplicate-key refusal, version dispatch.

The funnel's first phase (bADR-0004). Its early sub-steps are strictly ordered
and *terminal on failure*: sub-steps 1-4 (byte cap, UTF-8, depth pre-scan,
parse) short-circuit the rest as soon as one refuses — nothing downstream can
run without a decoded, parsed, pinned document. Sub-steps 5 (the caps walk —
duplicate keys, collection sizes, non-finite numbers, non-Unicode strings) and
6 (version dispatch) run *together, report-all*, so a document with several
distinct violations reports them all in one round trip. Duplicate object keys
are recovered *in* the walk (not terminally at parse) so each is located at its
own element pointer rather than collapsing under the enclosing collection.

The depth pre-scan (sub-step 3) runs *before* ``json.loads`` specifically so a
pathologically deep document becomes a typed ``nesting_too_deep`` refusal
rather than a ``RecursionError`` — a crash (exit 4) would reclassify a resource
bound as a toolkit fault. Preflight resolves the version but does not yet build
the typed document; the structural/semantic phases (later stages) do.

``number_not_finite`` and ``string_not_unicode`` are preflight-family additions
*beyond* bADR-0004's listed caps (byte size, nesting depth, collection size,
expression-tree limits). Both are crash-class guards under bADR-0004's own
spirit ("resource exhaustion is a refusal class, not a crash class"):

* ``number_not_finite`` — JSON's grammar admits numeric literals with no finite
  IEEE-754 double (``1e999`` parses to ``inf``; a ~400-digit integer overflows
  ``float()``), and canonical emission runs ``allow_nan=False`` (bADR-0005), so
  an ``inf`` slipping past preflight would surface as a crash-class emission
  failure downstream.
* ``string_not_unicode`` — ``json.loads`` accepts an escaped lone surrogate
  (``"\\ud800"``) that is a valid Python ``str`` but not encodable text, and
  canonical emission is UTF-8 (``ensure_ascii=False``, bADR-0005), so such a
  string reaching emission is an equivalent crash-class failure (a
  ``UnicodeEncodeError`` at output). It is refused at ingress for the same
  reason: canonical emission must be encodable.
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
# The nesting cap must *compose* with bADR-0003's expression-tree depth limit
# (32): every op node contributes 2 JSON nesting levels (its object + its `args`
# array), so a legal depth-32 tree already reaches ~64 levels of raw nesting, and
# its deepest legal declaration site adds more — `/effects/items/<id>/modifiers/
# <i>/magnitude` (or `/attributes/items/<id>/base/formula`) is itself ~7 levels
# deep, plus collection-nesting headroom. At 64 those failed to compose: a
# depth-31/32 formula was unreachable (refused `nesting_too_deep` before its
# `expression_tree_too_deep` rule could speak). 96 clears the deepest legal
# formula at every site while still bounding recursion (#527 review; bADR-0004
# amendment 2026-07-20). The raise was gated on linearizing structural validation
# (:mod:`gda_balancing.schema.artifacts`) — under the previous exponential
# validator the lower cap was a load-bearing shadow, not slack.
MAX_NESTING_DEPTH = 96
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
        "string_not_unicode",
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
    whenever a **terminal** sub-step (1-4) refused before a usable document
    existed; sub-steps 5-6 (the caps/duplicate/unicode walk + version dispatch)
    refuse *with* the parsed root in hand, but the funnel returns on any
    preflight refusal, so that root is never consumed. Refusals are raw
    (dedup/order/truncate is :mod:`report`'s job), in discovery order.
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

    # 4. Parse with a duplicate-key-recording hook. Map keys are id authorities
    # (bADR-0002), so a lenient parser silently keeping the last value would void
    # structural uniqueness; the hook records each built dict's duplicated keys
    # (keyed by the dict's id) so the sub-step-5 walk can point at each
    # duplicate's own element (bADR-0004), never just the enclosing collection.
    duplicates: dict[int, list[str]] = {}
    try:
        root = json.loads(text, object_pairs_hook=_dedup_hook(duplicates))
    except ValueError as exc:
        # `ValueError` (not just `JSONDecodeError`, which subclasses it) — so a
        # pathological integer literal that trips CPython's integer-string digit
        # limit *inside* the parser (a bare `ValueError`) is a malformed document
        # too, never an uncaught crash (exit 4).
        return [Refusal(code="malformed_json", path="", detail=str(exc))], None

    # 5 + 6 report together (all non-terminal within preflight). Duplicate keys
    # are reported here too — with their recovered element pointers — so several
    # duplicates at distinct locations yield several located refusals rather than
    # collapsing under one enclosing-collection path.
    refusals: list[Refusal] = []
    _walk_caps(root, (), duplicates, refusals)
    refusals.extend(_version_dispatch(root))
    return refusals, root


def _dedup_hook(
    duplicates: dict[int, list[str]],
) -> Callable[[list[tuple[str, Any]]], dict[str, Any]]:
    """A ``json.loads`` ``object_pairs_hook`` that records, per built dict, the
    names of any keys duplicated in its source pairs — keyed by the dict's
    ``id`` — while still collapsing to a last-wins dict so the parsed value stays
    usable. The walk holds the whole tree alive, so every recorded ``id`` stays
    valid and distinct until the walk recovers each duplicate's location."""

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        duped: list[str] = []
        for key, _ in pairs:
            if key in seen:
                if key not in duped:
                    duped.append(key)
            else:
                seen.add(key)
        built = dict(pairs)
        if duped:
            duplicates[id(built)] = duped
        return built

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
    value: object,
    tokens: tuple[str | int, ...],
    duplicates: dict[int, list[str]],
    refusals: list[Refusal],
) -> None:
    """Path-tracked walk collecting every duplicate-key, collection-size,
    non-finite-number and non-Unicode-string violation (report-all). Recursion
    is bounded: the depth pre-scan already guaranteed depth
    ``<= MAX_NESTING_DEPTH``."""
    if isinstance(value, dict):
        for key in duplicates.get(id(value), ()):
            refusals.append(
                Refusal(
                    code="duplicate_object_key",
                    path=pointer.build(*tokens, key),
                    detail=f"duplicate object key: {key!r}",
                )
            )
        if len(value) > MAX_COLLECTION_ELEMENTS:
            refusals.append(_too_large(tokens, len(value)))
        for key, item in value.items():
            if not _is_unicode_text(key):
                # A surrogate-bearing key cannot itself be a safely encodable
                # pointer token, so the refusal names the offending member's
                # enclosing element (the deepest encodable pointer).
                refusals.append(_not_unicode(tokens, "object key"))
            _walk_caps(item, (*tokens, key), duplicates, refusals)
    elif isinstance(value, list):
        if len(value) > MAX_COLLECTION_ELEMENTS:
            refusals.append(_too_large(tokens, len(value)))
        for index, item in enumerate(value):
            _walk_caps(item, (*tokens, index), duplicates, refusals)
    elif isinstance(value, bool):
        # JSON booleans are `int` subclasses but not numbers — never the int arm.
        pass
    elif isinstance(value, int):
        # A JSON integer literal too large for any finite double: `float()`
        # raises OverflowError (or, defensively, yields inf). Mere precision loss
        # is fine — JSON numbers are doubles (bADR-0005).
        if not _has_finite_double(value):
            refusals.append(_not_finite(tokens))
    elif isinstance(value, float):
        # A JSON numeric literal with no finite double (e.g. 1e999 -> inf).
        if not math.isfinite(value):
            refusals.append(_not_finite(tokens))
    elif isinstance(value, str):
        # A JSON string carrying an escaped lone surrogate (json.loads accepts
        # it) is not encodable as UTF-8 — refused at the value's own path.
        if not _is_unicode_text(value):
            refusals.append(_not_unicode(tokens, "string"))


def _has_finite_double(value: int) -> bool:
    """Whether a JSON integer literal has a finite IEEE-754 double value. A huge
    magnitude raises ``OverflowError`` on ``float()`` (or, defensively, converts
    to ``inf``); either means no finite double."""
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _not_finite(tokens: tuple[str | int, ...]) -> Refusal:
    return Refusal(
        code="number_not_finite",
        path=pointer.build(*tokens),
        detail="number has no finite IEEE-754 double value",
    )


def _is_unicode_text(text: str) -> bool:
    """Whether a string is emittable as UTF-8. ``json.loads`` accepts escaped
    lone surrogates (``"\\ud800"``), which canonical emission (ensure_ascii=
    False, bADR-0005) cannot encode. The ASCII fast path pays only a single
    C-level scan; only a non-ASCII string runs the authoritative encode — which
    tests the exact property emission needs rather than re-deriving the
    surrogate range."""
    if text.isascii():
        return True
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _not_unicode(tokens: tuple[str | int, ...], subject: str) -> Refusal:
    # The detail names the subject but never echoes the offending text, so the
    # refusal itself stays UTF-8 encodable.
    return Refusal(
        code="string_not_unicode",
        path=pointer.build(*tokens),
        detail=f"{subject} is not valid UTF-8 text (contains an unpaired surrogate)",
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
