"""Unregistered Standard Schema 1.x source-input regression adapters.

These descriptors are deliberately absent from the production command registry:
Schema 2.0 exposes ``model migrate`` as the only 1.x entrypoint. Tests retain
them as adapters over the exact 1.x funnel so conversion-input behavior remains
covered without making the superseded ``design`` group public.

``design format`` runs the *same* funnel and, on success, emits the **validated**
document in canonical form (bADR-0005; V11): the model dump materializes every
defined default and excludes reserved sections, and canonical emission sorts the
keys — so a valid non-canonical input round-trips to a byte-stable form,
idempotently. It is an artifact-sink command (bADR-0009): with ``--out`` the
canonical document goes to the sink and stdout carries the receipt. The dispatch
tail owns emission; both handlers only return data.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, RootModel

from gda_balancing.descriptors import (
    ArtifactReceipt,
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.envelope import RefusalReport
from gda_balancing.schema import funnel
from gda_balancing.schema.model.document import DesignDocument


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


class DesignFormatInput(BaseModel):
    """`design format` takes exactly the Design document's path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document: str


class DesignFormatOutput(RootModel[DesignDocument | ArtifactReceipt]):
    """The success result: the canonically-emitted document, or — when ``--out``
    was given — the :class:`ArtifactReceipt` the dispatch tail substitutes
    (bADR-0009). The union is the artifact-sink output-model contract; the body
    arm is the bare :class:`DesignDocument` (bADR-0008's no-wrapper law), so the
    document *is* the result, never nested under a key."""


def run_design_format(inp: DesignFormatInput) -> DesignFormatOutput | RefusalReport:
    """Load the document and run the funnel; a refusal report is the product on
    an invalid document, the canonical :class:`DesignDocument` (wrapped in
    :class:`DesignFormatOutput`) on one that passes. Emission does the rest:
    the model dump materializes every defined default (V11) and drops reserved
    sections; canonical emission sorts the keys."""
    data = funnel.load(inp.document)
    outcome = funnel.validate(data)
    if isinstance(outcome, RefusalReport):
        return outcome
    return DesignFormatOutput(root=outcome)


DESIGN_FORMAT = CommandDescriptor(
    group="design",
    command="format",
    description="Emit the validated document in canonical form (bADR-0005).",
    input_model=DesignFormatInput,
    output_model=DesignFormatOutput,
    handler=run_design_format,
    positional_field="document",
    artifact_sink=True,
    fixtures=ConformanceFixtures(
        # The V1 minimal document (bADR-0004a) and the same stable-refusal
        # document `design validate` uses (an unsupported major → a preflight
        # `unsupported_schema_version` refusal).
        valid_document='{"schema_version": "1.0.0", "meta": {"name": "smallest"}}',
        refusing_document='{"schema_version": "9.0.0", "meta": {"name": "smallest"}}',
    ),
)
