"""CLI adapter for checking a Standard Schema Model Source Package."""

from pydantic import BaseModel, ConfigDict

from gda_balancing.application.model_check import check_model
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.interfaces.cli.model_fixtures import VALID_MODEL_SOURCE
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.model.semantics import MODEL_REFUSAL_CATALOG


class ModelCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str


class ModelCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checked: bool
    kernel_identity: str
    language_bundle_identity: str


def run_model_check(
    inp: ModelCheckInput,
) -> ModelCheckResult | Schema2RefusalReport:
    result = check_model(inp.source)
    if isinstance(result, Schema2RefusalReport):
        return result
    return ModelCheckResult(
        checked=True,
        kernel_identity=result.kernel_identity,
        language_bundle_identity=result.language_bundle_identity,
    )


MODEL_CHECK = CommandDescriptor(
    group="model",
    command="check",
    description="Check a Standard Schema 2.0 Model Source Package.",
    input_model=ModelCheckInput,
    output_model=ModelCheckResult,
    handler=run_model_check,
    fixtures=ConformanceFixtures(valid_document=VALID_MODEL_SOURCE),
    positional_field="source",
    schema_major=2,
    structured_params=True,
    refusal_catalog=MODEL_REFUSAL_CATALOG,
    usage_codes=(
        "argument_conflict",
        "invalid_argument",
        "unknown_argument",
        "unreadable_input",
    ),
)
