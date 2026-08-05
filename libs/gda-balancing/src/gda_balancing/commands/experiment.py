"""Standard Schema 2.0 Experiment checking and execution commands."""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.descriptors import (
    ArtifactSetMemberSpec,
    CommandDescriptor,
    ConformanceFixtures,
    RefusalArtifactSetSpec,
    RefusalDetailSpec,
    RefusalVariantSpec,
)
from gda_balancing.domain.experiment import (
    EXPERIMENT_CHECK_REFUSAL_REASONS,
    CheckedExperiment,
    check_experiment,
    experiment_input_identity,
)
from gda_balancing.domain.evidence import (
    runtime_terminal_audit_members,
    validate_experiment_artifact_set,
    validate_experiment_member,
)
from gda_balancing.domain.runtime.execution import (
    RuntimeRefusalOutcome,
    evaluate_experiment,
)
from gda_balancing.domain.publication import (
    publication_authentication_key,
    publish_artifact_set,
    recover_committed_artifact_set,
)
from gda_balancing.envelope import UnreadableInputError
from gda_balancing.infrastructure.input_bytes import InputReadError
from gda_balancing.interfaces.cli.experiment_fixtures import (
    prepare_valid_experiment,
    prepare_verdict_experiment,
)
from gda_balancing.schema2.diagnostics import (
    Schema2Diagnostic,
    Schema2RefusalReport,
)
from gda_balancing.schema2.model import (
    refusal_catalog_for_reasons,
)
from gda_balancing.schema2.surface import descriptor_identity


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


_EXPERIMENT_RUN_ONLY_REFUSAL_REASONS = (
    "runtime.reason.capability-unsupported",
    "runtime.reason.step-limit",
    "runtime.reason.numeric-overflow",
    "runtime.reason.schedule-backward",
    "runtime.reason.schedule-hidden-input",
    "runtime.reason.schedule-illegal-same-time-priority",
    "runtime.reason.queue-limit",
    "runtime.reason.zero-time-depth-limit",
    "runtime.reason.event-limit",
    "runtime.reason.logical-time-limit",
    "runtime.reason.cancel-active",
    "runtime.reason.cancel-completed",
    "runtime.reason.cancel-unknown",
    "evaluation.reason.observation-unavailable",
)
EXPERIMENT_RUN_REFUSAL_CATALOG = refusal_catalog_for_reasons(
    EXPERIMENT_CHECK_REFUSAL_REASONS + _EXPERIMENT_RUN_ONLY_REFUSAL_REASONS
)

_EXPERIMENT_SUCCESS_ARTIFACT_SET = (
    ArtifactSetMemberSpec("evaluation-run", "evaluation-run", role="primary"),
    ArtifactSetMemberSpec("event-trace", "event-trace"),
    ArtifactSetMemberSpec("snapshot-series", "snapshot-series"),
    ArtifactSetMemberSpec("metric-dataset", "metric-dataset"),
    ArtifactSetMemberSpec("reproduction-receipt", "reproduction-receipt"),
    ArtifactSetMemberSpec("resolved-runtime-profile", "resolved-runtime-profile"),
    ArtifactSetMemberSpec(
        "evaluator-capability-manifest",
        "evaluator-capability-manifest",
    ),
)
_EXPERIMENT_VERDICT_ARTIFACT_SET = (
    ArtifactSetMemberSpec(
        "experiment-verdict",
        "experiment-verdict",
        role="primary",
    ),
    ArtifactSetMemberSpec("event-trace", "event-trace"),
    ArtifactSetMemberSpec("snapshot-series", "snapshot-series"),
    ArtifactSetMemberSpec("metric-dataset", "metric-dataset"),
    ArtifactSetMemberSpec("reproduction-receipt", "reproduction-receipt"),
    ArtifactSetMemberSpec("resolved-runtime-profile", "resolved-runtime-profile"),
    ArtifactSetMemberSpec(
        "evaluator-capability-manifest",
        "evaluator-capability-manifest",
    ),
)
_EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET = (
    ArtifactSetMemberSpec(
        "runtime-terminal-audit",
        "runtime-terminal-audit",
        role="primary",
    ),
    ArtifactSetMemberSpec("reproduction-receipt", "reproduction-receipt"),
    ArtifactSetMemberSpec("resolved-runtime-profile", "resolved-runtime-profile"),
    ArtifactSetMemberSpec(
        "evaluator-capability-manifest",
        "evaluator-capability-manifest",
    ),
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
            checked = check_experiment(inp.specification)
        except InputReadError as err:
            raise UnreadableInputError(
                f"cannot read input document: {inp.specification}"
            ) from err
        if isinstance(checked, Schema2RefusalReport):
            return checked
        assert isinstance(checked, CheckedExperiment)
        recovered = recover_committed_artifact_set(
            inp.out,
            inp.invocation_key,
            descriptor_identity(EXPERIMENT_RUN),
            experiment_input_identity(checked.value),
            checked.language_bundle,
            (
                EXPERIMENT_RUN.artifact_set,
                EXPERIMENT_RUN.verdict_artifact_set,
                *(item.members for item in EXPERIMENT_RUN.refusal_artifact_sets),
            ),
            lambda logical_name, value: validate_experiment_member(
                checked, logical_name, value
            ),
            artifact_set_validator=lambda artifacts: validate_experiment_artifact_set(
                checked, artifacts
            ),
            authentication_key=publication_authentication_key(),
        )
        if recovered is not None:
            validated_receipt = ExperimentRunResult.model_validate(recovered.receipt)
            if recovered.artifact_set == EXPERIMENT_RUN.artifact_set:
                return validated_receipt
            if recovered.artifact_set == EXPERIMENT_RUN.verdict_artifact_set:
                verdict = recovered.artifacts["experiment-verdict"]
                return ExperimentVerdictResult(
                    outcome="rejected",
                    failed_metrics=verdict["failed_metrics"],
                    artifact_set=validated_receipt,
                )
            audit = recovered.artifacts["runtime-terminal-audit"]
            diagnostic = audit["diagnostic"]
            return Schema2RefusalReport(
                stage="runtime",
                variant="post-dispatch",
                diagnostics=(
                    Schema2Diagnostic.model_validate(
                        {
                            key: value
                            for key, value in diagnostic.items()
                            if key != "stage"
                        }
                    ),
                ),
                truncated=False,
                terminal_audit=recovered.receipt,
            )
        evaluation = evaluate_experiment(checked)
        if isinstance(evaluation, RuntimeRefusalOutcome):
            report = evaluation.report
            runtime_set = next(
                item.members
                for item in EXPERIMENT_RUN.refusal_artifact_sets
                if item.stage == "runtime"
            )
            members = runtime_terminal_audit_members(checked, evaluation)
            receipt = publish_artifact_set(
                members,
                inp.out,
                inp.invocation_key,
                descriptor_identity(EXPERIMENT_RUN),
                experiment_input_identity(checked.value),
                checked.language_bundle,
                runtime_set,
                lambda logical_name, value: validate_experiment_member(
                    checked, logical_name, value
                ),
                publication_fault,
                artifact_set_validator=lambda artifacts: (
                    validate_experiment_artifact_set(checked, artifacts)
                ),
                authentication_key=publication_authentication_key(),
            )
            return report.model_copy(update={"terminal_audit": receipt})
        if isinstance(evaluation, Schema2RefusalReport):
            return evaluation
        artifact_set = (
            EXPERIMENT_RUN.artifact_set
            if evaluation.accepted
            else EXPERIMENT_RUN.verdict_artifact_set
        )
        receipt = publish_artifact_set(
            evaluation.members,
            inp.out,
            inp.invocation_key,
            descriptor_identity(EXPERIMENT_RUN),
            experiment_input_identity(checked.value),
            checked.language_bundle,
            artifact_set,
            lambda logical_name, value: validate_experiment_member(
                checked, logical_name, value
            ),
            publication_fault,
            artifact_set_validator=lambda artifacts: validate_experiment_artifact_set(
                checked, artifacts
            ),
            authentication_key=publication_authentication_key(),
        )
        validated_receipt = ExperimentRunResult.model_validate(receipt)
        if evaluation.accepted:
            return validated_receipt
        return ExperimentVerdictResult(
            outcome="rejected",
            failed_metrics=list(evaluation.failed_metrics),
            artifact_set=validated_receipt,
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
    artifact_set=_EXPERIMENT_SUCCESS_ARTIFACT_SET,
    verdict_artifact_set=_EXPERIMENT_VERDICT_ARTIFACT_SET,
    refusal_artifact_sets=(
        RefusalArtifactSetSpec(
            stage="runtime",
            members=_EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET,
            variant="post-dispatch",
        ),
    ),
    schema_major=2,
    structured_params=True,
    stochastic=True,
    refusal_catalog=EXPERIMENT_RUN_REFUSAL_CATALOG,
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
