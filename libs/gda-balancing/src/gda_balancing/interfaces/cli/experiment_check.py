"""CLI adapter for checking a Standard Schema Experiment Specification."""

from pydantic import BaseModel, ConfigDict

from gda_balancing.application.experiment_check import check_experiment_specification
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.domain.experiment import experiment_check_refusal_reasons
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.infrastructure.input_bytes import InputReadError
from gda_balancing.interfaces.cli.experiment_fixtures import prepare_experiment_args
from gda_balancing.domain.diagnostics import (
    Schema2RefusalReport,
    refusal_catalog_for_reasons,
)


class ExperimentCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    specification: str
    rir: str


class ExperimentCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checked: bool
    experiment_identity: str
    rir_semantic_identity: str
    runtime_profile: str


def run_experiment_check(
    inp: ExperimentCheckInput,
) -> ExperimentCheckResult | Schema2RefusalReport:
    try:
        result = check_experiment_specification(inp.specification, inp.rir)
    except InputReadError as err:
        raise UnreadableInputError("cannot read an Experiment input document") from err
    if isinstance(result, Schema2RefusalReport):
        return result
    return ExperimentCheckResult(
        checked=True,
        experiment_identity=result.experiment_identity,
        rir_semantic_identity=result.rir_semantic_identity,
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
        prepare_args=prepare_experiment_args,
    ),
    positional_field="specification",
    schema_major=2,
    structured_params=True,
    refusal_catalog=refusal_catalog_for_reasons(experiment_check_refusal_reasons()),
    usage_codes=(
        "argument_conflict",
        "invalid_argument",
        "unknown_argument",
        "unreadable_input",
    ),
)
