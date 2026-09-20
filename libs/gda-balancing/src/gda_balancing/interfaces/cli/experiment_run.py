"""CLI adapter for executing and publishing an Experiment."""

from collections.abc import Callable
from dataclasses import replace

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.application.experiment_run import (
    ExperimentRunPublication,
    ExperimentVerdictPublication,
    run_experiment,
)
from gda_balancing.application.authority import admit_command_authority
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
    RefusalArtifactSetSpec,
    RefusalDetailSpec,
    RefusalVariantSpec,
    authority_context_handler,
)
from gda_balancing.domain.artifact_set import (
    EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET,
    EXPERIMENT_SUCCESS_ARTIFACT_SET,
    EXPERIMENT_VERDICT_ARTIFACT_SET,
)
from gda_balancing.domain.experiment import experiment_check_refusal_reasons
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.infrastructure.input_bytes import InputReadError
from gda_balancing.interfaces.cli.experiment_fixtures import (
    prepare_experiment_args,
    prepare_experiment_verdict_args,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.diagnostics import refusal_catalog_for_reasons
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    AuthorityContextProvider,
    packaged_authority_context,
)
from gda_balancing.interfaces.cli.surface import descriptor_identity


class ExperimentRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    specification: str
    rir: str
    out: str = Field(min_length=1)
    invocation_key: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExperimentArtifactSetMemberLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_name: str
    locator: str


class ExperimentRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_kind: str
    artifact_version: str
    wire_schema_identity: str
    descriptor_identity: str
    invocation_key: str
    manifest_identity: str
    manifest_locator: str
    member_locators: list[ExperimentArtifactSetMemberLocator]
    content_identity: str


class ExperimentVerdictResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: str
    failed_metrics: list[str]
    artifact_set: ExperimentRunResult


def _operation_refusal_reasons(
    context: AdmittedAuthorityContext,
) -> tuple[str, ...]:
    language = context.language_bundle["language"]
    return tuple(
        sorted(
            {
                reason
                for operation in language["operations"]
                for reason in operation.get("refusals", [])
            },
            key=lambda value: value.encode("utf-8"),
        )
    )


_EXPERIMENT_RUN_NON_OPERATION_REFUSAL_REASONS = (
    "runtime.reason.capability-unsupported",
    "evaluation.reason.observation-unavailable",
)


def _experiment_run_refusal_catalog(
    context: AdmittedAuthorityContext | None,
) -> tuple[tuple[str, str], ...]:
    """Resolve the run-only catalog after the CLI has selected this surface."""
    context = context or packaged_authority_context()
    return refusal_catalog_for_reasons(
        experiment_check_refusal_reasons(context)
        + _EXPERIMENT_RUN_NON_OPERATION_REFUSAL_REASONS
        + _operation_refusal_reasons(context),
        context.language_bundle,
    )


def _terminal_audit_receipt_schema() -> dict[str, object]:
    return ExperimentRunResult.model_json_schema()


def experiment_run_handler(
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
    *,
    publication_fault: str | None = None,
    _descriptor: CommandDescriptor | None = None,
) -> Callable[
    ...,
    ExperimentRunResult | ExperimentVerdictResult | Schema2RefusalReport,
]:
    """Create the run handler; publication fault injection is test-only."""

    def _run(
        inp: ExperimentRunInput,
        authority_context: AdmittedAuthorityContext | None = None,
    ) -> ExperimentRunResult | ExperimentVerdictResult | Schema2RefusalReport:
        context = authority_context or admit_command_authority(
            authority_context_provider
        )
        if isinstance(context, Schema2RefusalReport):
            return context
        descriptor = _descriptor or EXPERIMENT_RUN
        try:
            result = run_experiment(
                inp.specification,
                inp.out,
                inp.invocation_key,
                descriptor_identity(descriptor, authority_context=context),
                descriptor.artifact_set,
                descriptor.verdict_artifact_set,
                descriptor.refusal_artifact_sets[0].members,
                rir=inp.rir,
                publication_fault=publication_fault,
                authority_context=context,
            )
        except InputReadError as err:
            raise UnreadableInputError(
                "cannot read an Experiment input document"
            ) from err
        if isinstance(result, Schema2RefusalReport):
            return result
        receipt = ExperimentRunResult.model_validate(result.receipt)
        if isinstance(result, ExperimentRunPublication):
            return receipt
        assert isinstance(result, ExperimentVerdictPublication)
        return ExperimentVerdictResult(
            outcome="rejected",
            failed_metrics=list(result.failed_metrics),
            artifact_set=receipt,
        )

    return authority_context_handler(_run)


def experiment_run_descriptor(
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
    *,
    publication_fault: str | None = None,
) -> CommandDescriptor:
    """Compose Experiment execution and projections over one authority source."""

    def _unbound(_inp: ExperimentRunInput) -> ExperimentRunResult:
        raise RuntimeError("Experiment run descriptor handler is not bound")

    descriptor = CommandDescriptor(
        group="experiment",
        command="run",
        description=(
            "Run and atomically publish one exact Standard Schema 2.0 Experiment."
        ),
        input_model=ExperimentRunInput,
        output_model=ExperimentRunResult,
        verdict_model=ExperimentVerdictResult,
        handler=_unbound,
        fixtures=ConformanceFixtures(
            prepare_args=prepare_experiment_args,
            prepare_verdict_args=prepare_experiment_verdict_args,
        ),
        positional_field="specification",
        artifact_set=EXPERIMENT_SUCCESS_ARTIFACT_SET,
        verdict_artifact_set=EXPERIMENT_VERDICT_ARTIFACT_SET,
        refusal_artifact_sets=(
            RefusalArtifactSetSpec(
                stage="runtime",
                members=EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET,
                variant="post-dispatch",
            ),
        ),
        schema_major=2,
        structured_params=True,
        stochastic=True,
        authority_context_provider=authority_context_provider,
        refusal_catalog_provider=_experiment_run_refusal_catalog,
        refusal_details=(
            RefusalDetailSpec(
                stage="runtime",
                field_name="terminal_audit",
                schema=_terminal_audit_receipt_schema,
                required=False,
            ),
        ),
        refusal_variants=(
            RefusalVariantSpec(
                stage="runtime",
                id="pre-event",
                forbidden_details=("terminal_audit",),
            ),
            RefusalVariantSpec(
                stage="runtime",
                id="post-dispatch",
                required_details=("terminal_audit",),
            ),
        ),
        usage_codes=(
            "argument_conflict",
            "invalid_argument",
            "invocation_key_conflict",
            "unknown_argument",
            "unreadable_input",
            "unwritable_output",
        ),
    )
    return replace(
        descriptor,
        handler=experiment_run_handler(
            authority_context_provider,
            publication_fault=publication_fault,
            _descriptor=descriptor,
        ),
    )


EXPERIMENT_RUN = experiment_run_descriptor()
run_experiment_run = experiment_run_handler()
