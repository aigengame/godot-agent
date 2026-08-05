"""CLI adapter for checking a Standard Schema Experiment Specification."""

from pydantic import BaseModel, ConfigDict

from gda_balancing.application.experiment_check import check_experiment_specification
from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.domain.experiment import EXPERIMENT_CHECK_REFUSAL_REASONS
from gda_balancing.envelope import UnreadableInputError
from gda_balancing.infrastructure.input_bytes import InputReadError
from gda_balancing.interfaces.cli.experiment_fixtures import prepare_valid_experiment
from gda_balancing.schema2.diagnostics import Schema2RefusalReport
from gda_balancing.schema2.model import refusal_catalog_for_reasons


class ExperimentCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    specification: str


class ExperimentCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checked: bool
    experiment_identity: str
    resolved_model_identity: str
    runtime_profile: str


def run_experiment_check(
    inp: ExperimentCheckInput,
) -> ExperimentCheckResult | Schema2RefusalReport:
    try:
        result = check_experiment_specification(inp.specification)
    except InputReadError as err:
        raise UnreadableInputError(
            f"cannot read input document: {inp.specification}"
        ) from err
    if isinstance(result, Schema2RefusalReport):
        return result
    return ExperimentCheckResult(
        checked=True,
        experiment_identity=result.experiment_identity,
        resolved_model_identity=result.resolved_model_identity,
        runtime_profile=result.runtime_profile,
    )


EXPERIMENT_CHECK = CommandDescriptor(
    group="experiment",
    command="check",
    description="Check one exact Standard Schema 2.0 Experiment Specification.",
    input_model=ExperimentCheckInput,
    output_model=ExperimentCheckResult,
    handler=run_experiment_check,
    fixtures=ConformanceFixtures(
        prepare_valid_document=prepare_valid_experiment,
    ),
    positional_field="specification",
    schema_major=2,
    structured_params=True,
    refusal_catalog=refusal_catalog_for_reasons(EXPERIMENT_CHECK_REFUSAL_REASONS),
    usage_codes=(
        "argument_conflict",
        "invalid_argument",
        "unknown_argument",
        "unreadable_input",
    ),
)
