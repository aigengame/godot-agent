"""The boundary funnel — the one validation boundary every document crosses.

Every Design document crosses this single boundary before any use; downstream
code never re-validates and never defends (bADR-0004). This package is the
funnel's public face. It runs Phase 0 (preflight), Phase 1 (structural), then
Phase 2 (semantic), each gating the next, and returns the **typed Design
document** on success. The semantic phase's rule codes union into
:func:`refusal_code_namespace`.
"""

from typing import Any, cast

from pydantic import ValidationError

from gda_balancing.envelope import RefusalReport, UnreadableInputError
from gda_balancing.schema.funnel import report, semantic
from gda_balancing.schema.funnel.preflight import (
    MAX_DOCUMENT_BYTES,
    PREFLIGHT_CODES,
    preflight,
)
from gda_balancing.schema.funnel.structural import STRUCTURAL_VIOLATION, structural
from gda_balancing.schema.model.document import DesignDocument

__all__ = ["load", "validate", "refusal_code_namespace"]


def load(path: str) -> bytes:
    """Read the input document's bytes, or raise :class:`UnreadableInputError`.

    Any ``OSError`` — the path missing (``FileNotFoundError``), being a
    directory (``IsADirectoryError``), or permission-denied
    (``PermissionError``) — becomes an :class:`UnreadableInputError` naming the
    path, which dispatch maps to the usage boundary (bADR-0008). At most
    ``MAX_DOCUMENT_BYTES + 1`` bytes are read: one past the cap is enough for
    preflight to refuse an oversized document without slurping a huge file.
    """
    try:
        with open(path, "rb") as handle:
            return handle.read(MAX_DOCUMENT_BYTES + 1)
    except OSError as err:
        raise UnreadableInputError(f"cannot read input document: {path}") from err


def validate(data: bytes) -> DesignDocument | RefusalReport:
    """Run the funnel over the document bytes, phase by phase.

    Preflight (Phase 0) then structural (Phase 1), each gating the next: the
    first phase to produce refusals returns them as an assembled
    :class:`RefusalReport` (the dispatch tail maps it onto the `refusal`
    envelope / exit 2). A document clearing both phases is constructed into its
    typed :class:`DesignDocument` and returned.

    Construction **must** succeed after a structural pass — the generated
    structural schema is hardened so structural-pass ⇒ model-construction-success
    (bADR-0005; :mod:`gda_balancing.schema.artifacts`). A ``ValidationError``
    here is therefore an *engine-parity bug*, not a user error: it is re-raised
    as a :class:`RuntimeError` so it takes the internal path (exit 4), never a
    silent refusal. The engine-parity tests exist to keep this unreachable.

    The semantic phase (Phase 2) runs last, on the *typed* document plus the raw
    parsed root (bADR-0004: it runs only when the structural phase produced no
    refusals). Its refusals are assembled and returned; a document clearing all
    three phases is returned as its typed :class:`DesignDocument`.
    """
    pre_refusals, root = preflight(data)
    preflight_report = report.assemble(pre_refusals)
    if preflight_report is not None:
        return preflight_report

    structural_report = report.assemble(structural(root))
    if structural_report is not None:
        return structural_report

    try:
        document = DesignDocument.model_validate(root)
    except ValidationError as exc:
        raise RuntimeError(
            "structural schema passed but model construction failed — "
            f"engine-parity bug: {exc}"
        ) from exc

    # `root` is a parsed object; the semantic rules that read raw top-level keys
    # (`$schema`, reserved sections) need a dict. Preflight already refused a
    # non-object root as `malformed_schema_version`, and the structural phase
    # re-validates the closed object envelope — so by here `root` is a dict. The
    # cast records that invariant without an input-boundary assert.
    raw = cast(dict[str, Any], root)
    semantic_report = report.assemble(semantic.run(document, raw))
    if semantic_report is not None:
        return semantic_report

    return document


def refusal_code_namespace() -> frozenset[str]:
    """Every stable refusal code the funnel can emit.

    The preflight family, the single structural code, and every semantic rule's
    code (the rule id *is* its refusal code, bADR-0004/0005). The conformance
    harness asserts every emitted refusal code resolves against this namespace,
    so the CLI can never grow a second refusal-code registry (bADR-0011).
    """
    return (
        PREFLIGHT_CODES
        | {STRUCTURAL_VIOLATION}
        | {rule.code for rule in semantic.SEMANTIC_RULES}
    )
