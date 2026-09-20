"""CLI adapter for checking a Standard Schema Experiment Specification."""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from gda_balancing.application.authority import admit_command_authority
from gda_balancing.application.experiment_check import check_experiment_specification
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
    authority_context_handler,
)
from gda_balancing.domain.experiment import experiment_check_refusal_reasons
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    AuthorityContextProvider,
    packaged_authority_context,
)
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


def _experiment_check_refusal_catalog(
    context: AdmittedAuthorityContext | None,
) -> tuple[tuple[str, str], ...]:
    return refusal_catalog_for_reasons(
        experiment_check_refusal_reasons(context),
        None if context is None else context.language_bundle,
    )


def experiment_check_handler(
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
) -> Callable[..., ExperimentCheckResult | Schema2RefusalReport]:
    """Bind Experiment admission to one explicit authority source."""

    def _run(
        inp: ExperimentCheckInput,
        authority_context: AdmittedAuthorityContext | None = None,
    ) -> ExperimentCheckResult | Schema2RefusalReport:
        context = authority_context or admit_command_authority(
            authority_context_provider
        )
        if isinstance(context, Schema2RefusalReport):
            return context
        try:
            result = check_experiment_specification(
                inp.specification,
                inp.rir,
                authority_context=context,
            )
        except InputReadError as err:
            raise UnreadableInputError(
                "cannot read an Experiment input document"
            ) from err
        if isinstance(result, Schema2RefusalReport):
            return result
        return ExperimentCheckResult(
            checked=True,
            experiment_identity=result.experiment_identity,
            rir_semantic_identity=result.rir_semantic_identity,
            runtime_profile=result.runtime_profile,
        )

    return authority_context_handler(_run)


def experiment_check_descriptor(
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
) -> CommandDescriptor:
    """Compose Experiment checking and refusal projection over one authority."""
    return CommandDescriptor(
        group="experiment",
        command="check",
        description="Check one exact Standard Schema 2.0 Experiment Specification.",
        input_model=ExperimentCheckInput,
        output_model=ExperimentCheckResult,
        handler=experiment_check_handler(authority_context_provider),
        fixtures=ConformanceFixtures(
            prepare_args=prepare_experiment_args,
        ),
        positional_field="specification",
        schema_major=2,
        structured_params=True,
        authority_context_provider=authority_context_provider,
        refusal_catalog_provider=_experiment_check_refusal_catalog,
        usage_codes=(
            "argument_conflict",
            "invalid_argument",
            "unknown_argument",
            "unreadable_input",
        ),
    )


run_experiment_check = experiment_check_handler()
EXPERIMENT_CHECK = experiment_check_descriptor()
