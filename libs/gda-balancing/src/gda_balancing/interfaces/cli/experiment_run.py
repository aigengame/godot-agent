"""CLI adapter for executing and publishing an Experiment."""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.application.experiment_run import (
    ExperimentRunPublication,
    ExperimentVerdictPublication,
    run_experiment,
)
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
    RefusalArtifactSetSpec,
    RefusalDetailSpec,
    RefusalVariantSpec,
)
from gda_balancing.domain.artifact_set import (
    EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET,
    EXPERIMENT_SUCCESS_ARTIFACT_SET,
    EXPERIMENT_VERDICT_ARTIFACT_SET,
)
from gda_balancing.domain.experiment import EXPERIMENT_CHECK_REFUSAL_REASONS
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.infrastructure.input_bytes import InputReadError
from gda_balancing.interfaces.cli.experiment_fixtures import (
    prepare_valid_experiment,
    prepare_verdict_experiment,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.diagnostics import refusal_catalog_for_reasons
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.interfaces.cli.surface import descriptor_identity


class ExperimentRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    specification: str
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


def _operation_refusal_reasons() -> tuple[str, ...]:
    language = packaged_authority_context().language_bundle["language"]
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


def _experiment_run_refusal_catalog() -> tuple[tuple[str, str], ...]:
    """Resolve the run-only catalog after the CLI has selected this surface."""
    return refusal_catalog_for_reasons(
        EXPERIMENT_CHECK_REFUSAL_REASONS
        + _EXPERIMENT_RUN_NON_OPERATION_REFUSAL_REASONS
        + _operation_refusal_reasons()
    )


def _terminal_audit_receipt_schema() -> dict[str, object]:
    return ExperimentRunResult.model_json_schema()


def experiment_run_handler(
    *, publication_fault: str | None = None
) -> Callable[
    [ExperimentRunInput],
    ExperimentRunResult | ExperimentVerdictResult | Schema2RefusalReport,
]:
    """Create the run handler; publication fault injection is test-only."""

    def _run(
        inp: ExperimentRunInput,
    ) -> ExperimentRunResult | ExperimentVerdictResult | Schema2RefusalReport:
        try:
            result = run_experiment(
                inp.specification,
                inp.out,
                inp.invocation_key,
                descriptor_identity(EXPERIMENT_RUN),
                EXPERIMENT_RUN.artifact_set,
                EXPERIMENT_RUN.verdict_artifact_set,
                EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET,
                publication_fault=publication_fault,
            )
        except InputReadError as err:
            raise UnreadableInputError(
                f"cannot read input document: {inp.specification}"
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

    return _run


run_experiment_run = experiment_run_handler()

EXPERIMENT_RUN = CommandDescriptor(
    group="experiment",
    command="run",
    description="Run and atomically publish one exact Standard Schema 2.0 Experiment.",
    input_model=ExperimentRunInput,
    output_model=ExperimentRunResult,
    verdict_model=ExperimentVerdictResult,
    handler=run_experiment_run,
    fixtures=ConformanceFixtures(
        prepare_valid_document=prepare_valid_experiment,
        prepare_verdict_document=prepare_verdict_experiment,
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
