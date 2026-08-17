"""Execute and publish one admitted Experiment Specification."""

from dataclasses import dataclass
from typing import Any

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.evidence import (
    validate_experiment_artifact_set,
    validate_experiment_member,
)
from gda_balancing.application.experiment_execution import (
    ExperimentExecutionRefusal,
    ExperimentExecutionSuccess,
    ExperimentExecutionVerdict,
    execute_checked_experiment,
)
from gda_balancing.domain.experiment import (
    CheckedExperiment,
    check_experiment,
    experiment_input_identity,
)
from gda_balancing.domain.publication import (
    publication_authentication_key,
    publish_artifact_set,
    recover_committed_artifact_set,
)
from gda_balancing.domain.diagnostics import (
    Schema2Diagnostic,
    Schema2RefusalReport,
)


@dataclass(frozen=True)
class ExperimentRunPublication:
    """One accepted Experiment publication receipt."""

    receipt: dict[str, Any]


@dataclass(frozen=True)
class ExperimentVerdictPublication:
    """One rejected metric verdict and its publication receipt."""

    failed_metrics: tuple[str, ...]
    receipt: dict[str, Any]


def run_experiment(
    specification: str,
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    success_artifact_set: tuple[ArtifactSetMemberSpec, ...],
    verdict_artifact_set: tuple[ArtifactSetMemberSpec, ...],
    runtime_refusal_artifact_set: tuple[ArtifactSetMemberSpec, ...],
    *,
    publication_fault: str | None = None,
) -> ExperimentRunPublication | ExperimentVerdictPublication | Schema2RefusalReport:
    """Admit, execute, recover, or publish one exact Experiment run."""
    checked = check_experiment(specification)
    if isinstance(checked, Schema2RefusalReport):
        return checked
    assert isinstance(checked, CheckedExperiment)
    input_identity = experiment_input_identity(checked.value)
    authentication_key = publication_authentication_key()
    recovered = recover_committed_artifact_set(
        out,
        invocation_key,
        descriptor_identity,
        input_identity,
        checked.language_bundle,
        (
            success_artifact_set,
            verdict_artifact_set,
            runtime_refusal_artifact_set,
        ),
        lambda logical_name, value: validate_experiment_member(
            checked, logical_name, value
        ),
        artifact_set_validator=lambda artifacts: validate_experiment_artifact_set(
            checked, artifacts
        ),
        authentication_key=authentication_key,
    )
    if recovered is not None:
        if recovered.artifact_set == success_artifact_set:
            return ExperimentRunPublication(receipt=recovered.receipt)
        if recovered.artifact_set == verdict_artifact_set:
            verdict = recovered.artifacts["experiment-verdict"]
            return ExperimentVerdictPublication(
                failed_metrics=tuple(verdict["failed_metrics"]),
                receipt=recovered.receipt,
            )
        audit = recovered.artifacts["runtime-terminal-audit"]
        diagnostic = audit["diagnostic"]
        return Schema2RefusalReport(
            stage="runtime",
            variant="post-dispatch",
            diagnostics=(
                Schema2Diagnostic.model_validate(
                    {key: value for key, value in diagnostic.items() if key != "stage"}
                ),
            ),
            truncated=False,
            terminal_audit=recovered.receipt,
        )

    execution = execute_checked_experiment(checked)
    if isinstance(execution, ExperimentExecutionRefusal):
        if not execution.members:
            return execution.report
        receipt = publish_artifact_set(
            execution.members,
            out,
            invocation_key,
            descriptor_identity,
            input_identity,
            checked.language_bundle,
            runtime_refusal_artifact_set,
            lambda logical_name, value: validate_experiment_member(
                checked, logical_name, value
            ),
            publication_fault,
            artifact_set_validator=lambda artifacts: validate_experiment_artifact_set(
                checked, artifacts
            ),
            authentication_key=authentication_key,
        )
        return execution.report.model_copy(update={"terminal_audit": receipt})

    artifact_set = (
        success_artifact_set
        if isinstance(execution, ExperimentExecutionSuccess)
        else verdict_artifact_set
    )
    receipt = publish_artifact_set(
        execution.members,
        out,
        invocation_key,
        descriptor_identity,
        input_identity,
        checked.language_bundle,
        artifact_set,
        lambda logical_name, value: validate_experiment_member(
            checked, logical_name, value
        ),
        publication_fault,
        artifact_set_validator=lambda artifacts: validate_experiment_artifact_set(
            checked, artifacts
        ),
        authentication_key=authentication_key,
    )
    if isinstance(execution, ExperimentExecutionSuccess):
        return ExperimentRunPublication(receipt=receipt)
    assert isinstance(execution, ExperimentExecutionVerdict)
    return ExperimentVerdictPublication(
        failed_metrics=execution.failed_metrics,
        receipt=receipt,
    )
