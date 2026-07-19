"""The boundary funnel — the one validation boundary every document crosses.

Every Design document crosses this single boundary before any use; downstream
code never re-validates and never defends (bADR-0004). This package is the
funnel's public face. Today it implements only Phase 0 (preflight); the
structural and semantic phases arrive in later stages, unioning their codes
into :func:`refusal_code_namespace` and returning the typed document from
:func:`validate` on success.
"""

from gda_balancing.envelope import RefusalReport, UnreadableInputError
from gda_balancing.schema.funnel import report
from gda_balancing.schema.funnel.preflight import (
    MAX_DOCUMENT_BYTES,
    PREFLIGHT_CODES,
    preflight,
)

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


def validate(data: bytes) -> RefusalReport | None:
    """Run the funnel over the document bytes.

    ``None`` means the document passed every executed phase — currently just
    preflight, so a preflight-clean document validates. (Later stages will
    return the *typed Design document* on success instead of ``None``, once the
    structural and semantic phases exist to produce it.) A non-``None``
    :class:`RefusalReport` carries the assembled, report-all refusals the
    dispatch tail maps onto the `refusal` envelope / exit 2.
    """
    return report.assemble(preflight(data))


def refusal_code_namespace() -> frozenset[str]:
    """Every stable refusal code the funnel can emit.

    Currently the preflight family; later stages union the structural code and
    the semantic rule catalog into it. The conformance harness asserts every
    emitted refusal code resolves against this namespace, so the CLI can never
    grow a second refusal-code registry (bADR-0011).
    """
    return PREFLIGHT_CODES
