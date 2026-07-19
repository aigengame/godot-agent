"""The `design` command group — Design-document operations (bADR-0007).

``design validate`` is the first document-taking command: it runs a Design
document through the boundary funnel (bADR-0004) and reports the outcome as the
invocation-result contract's two normative shapes (bADR-0008/0011) — the typed
:class:`ValidationResult` on a document that passes, or the funnel's
:class:`RefusalReport` on one that is refused. The dispatch tail owns emission;
this handler only returns data.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.envelope import RefusalReport
from gda_balancing.schema import funnel


class DesignValidateInput(BaseModel):
    """`design validate` takes exactly the Design document's path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document: str


class ValidationResult(BaseModel):
    """A document that crossed the funnel. ``valid`` is fixed ``True`` — an
    *invalid* document is a `refusal` envelope, never this result with a
    ``False`` field (bADR-0004: refusal is the rejection path, not a verdict
    flag)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: Literal[True] = True


def run_design_validate(inp: DesignValidateInput) -> ValidationResult | RefusalReport:
    """Load the document and run the funnel; a refusal report is the product on
    an invalid document, :class:`ValidationResult` on one that passes.

    The funnel returns the typed :class:`DesignDocument` on success; this
    command reports only *that* it validated (``design format`` consumes the
    typed document in a later stage), so the document is mapped to the fixed
    :class:`ValidationResult`."""
    data = funnel.load(inp.document)
    outcome = funnel.validate(data)
    if isinstance(outcome, RefusalReport):
        return outcome
    return ValidationResult()


DESIGN_VALIDATE = CommandDescriptor(
    group="design",
    command="validate",
    description="Validate a Design document through the boundary funnel (bADR-0004).",
    input_model=DesignValidateInput,
    output_model=ValidationResult,
    handler=run_design_validate,
    positional_field="document",
    fixtures=ConformanceFixtures(
        # A V1 minimal document (bADR-0004a) — the smallest document that
        # clears preflight — and one whose only defect is an unsupported major,
        # a stable preflight refusal (unsupported_schema_version).
        valid_document='{"schema_version": "1.0.0", "meta": {"name": "smallest"}}',
        refusing_document='{"schema_version": "9.0.0", "meta": {"name": "smallest"}}',
    ),
)
