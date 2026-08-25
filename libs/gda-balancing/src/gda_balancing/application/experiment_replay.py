"""Authenticate, execute, compare, and publish one exact Experiment Replay."""

from dataclasses import dataclass
from typing import Any, cast

from gda_balancing.application.experiment_execution import (
    ExperimentExecutionRefusal,
    PreparedExperimentExecution,
    execute_prepared_experiment,
    prepare_checked_experiment,
)
from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.artifacts import verify_artifact
from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.comparison import (
    compare_exact_replay,
    validate_published_exact_replay_comparison,
)
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
    ingress_refusal,
)
from gda_balancing.domain.evidence import (
    validate_experiment_artifact_set,
    validate_experiment_member,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment
from gda_balancing.domain.publication import (
    publication_authentication_key,
    publish_artifact_set,
    read_authenticated_declared_artifact_set,
    recover_committed_artifact_set,
)
from gda_balancing.domain.publication_types import (
    PublicationAdmissionError,
    PublicationMember,
)


@dataclass(frozen=True)
class ExperimentReplayPublication:
    receipt: dict[str, Any]


@dataclass(frozen=True)
class ExperimentReplayVerdictPublication:
    mismatches: tuple[str, ...]
    receipt: dict[str, Any]


def _publication_members(
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, PublicationMember]:
    return {
        name: PublicationMember(
            value=value,
            artifact_kind=cast(str, value["artifact_kind"]),
            wire_schema_identity=cast(str, value["wire_schema_identity"]),
            content_identity=cast(str, value["content_identity"]),
        )
        for name, value in artifacts.items()
    }


def _evaluation_refusal(
    checked: CheckedExperiment, code: str, pointer: str, message: str
) -> Schema2RefusalReport:
    return Schema2RefusalReport(
        stage="evaluation",
        diagnostics=(
            Schema2Diagnostic(
                code=code,
                message=message,
                primary=ArtifactLocation(
                    content_identity=checked.content_identity,
                    pointer=pointer,
                ),
            ),
        ),
        truncated=False,
    )


def _replay_input_identity(
    checked: CheckedExperiment, original_receipt_identity: str
) -> str:
    return content_identity(
        "experiment-replay-command-input-v1",
        cast(
            JsonValue,
            {
                "experiment_identity": checked.content_identity,
                "original_experiment_run_artifact_set_receipt_identity": (
                    original_receipt_identity
                ),
            },
        ),
    )


def _same_complete_reproduction(
    original: dict[str, Any], prepared: dict[str, Any]
) -> bool:
    return canonical_bytes(cast(JsonValue, original)) == canonical_bytes(
        cast(JsonValue, prepared)
    )


def replay_experiment(
    specification: str,
    original_receipt: str,
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    experiment_run_descriptor_identity: str,
    original_artifact_sets: tuple[tuple[ArtifactSetMemberSpec, ...], ...],
    success_artifact_set: tuple[ArtifactSetMemberSpec, ...],
    verdict_artifact_set: tuple[ArtifactSetMemberSpec, ...],
    runtime_refusal_artifact_set: tuple[ArtifactSetMemberSpec, ...],
    *,
    publication_fault: str | None = None,
) -> (
    ExperimentReplayPublication
    | ExperimentReplayVerdictPublication
    | Schema2RefusalReport
):
    """Authenticate one original run and publish an exact Replay comparison."""
    try:
        original = read_authenticated_declared_artifact_set(
            original_receipt,
            experiment_run_descriptor_identity,
            original_artifact_sets,
        )
    except PublicationAdmissionError as error:
        return ingress_refusal(error.code, error.subject, error.message)
    checked = check_experiment(
        specification,
        authority_context=original.authority_context,
    )
    if isinstance(checked, Schema2RefusalReport):
        return checked
    assert isinstance(checked, CheckedExperiment)
    if "evaluation-run" not in original.artifacts:
        return _evaluation_refusal(
            checked,
            "evaluation.replay_ineligible_outcome",
            "/original_experiment_run_artifact_set_receipt",
            "The original publication is not a successful Evaluation run",
        )
    if not validate_experiment_artifact_set(checked, original.artifacts):
        return _evaluation_refusal(
            checked,
            "evaluation.replay_reproduction_mismatch",
            "/original_experiment_run_artifact_set_receipt",
            "The original publication does not bind this Experiment",
        )
    original_members = _publication_members(original.artifacts)
    original_receipt_identity = cast(str, original.receipt["content_identity"])
    input_identity = _replay_input_identity(checked, original_receipt_identity)
    authentication_key = publication_authentication_key()

    def validate_member(logical_name: str, value: dict[str, Any]) -> bool:
        if logical_name == "replay-comparison":
            return verify_artifact(value, checked.language_bundle)
        return validate_experiment_member(checked, logical_name, value)

    def validate_set(artifacts: dict[str, dict[str, Any]]) -> bool:
        if "runtime-terminal-audit" in artifacts:
            return validate_experiment_artifact_set(checked, artifacts)
        comparison = artifacts.get("replay-comparison")
        if not isinstance(comparison, dict):
            return False
        return validate_published_exact_replay_comparison(
            comparison,
            language_bundle=checked.language_bundle,
            original_artifact_set_receipt_identity=original_receipt_identity,
            original_members=original_members,
            replay_members=_publication_members(
                {
                    name: value
                    for name, value in artifacts.items()
                    if name != "replay-comparison"
                }
            ),
        )

    recovered = recover_committed_artifact_set(
        out,
        invocation_key,
        descriptor_identity,
        input_identity,
        checked.language_bundle,
        (success_artifact_set, verdict_artifact_set, runtime_refusal_artifact_set),
        validate_member,
        artifact_set_validator=validate_set,
        authentication_key=authentication_key,
    )
    if recovered is not None:
        if recovered.artifact_set == success_artifact_set:
            return ExperimentReplayPublication(receipt=recovered.receipt)
        if recovered.artifact_set == verdict_artifact_set:
            comparison = recovered.artifacts["replay-comparison"]
            return ExperimentReplayVerdictPublication(
                mismatches=tuple(
                    cast(str, row["key"])
                    for row in cast(list[dict[str, Any]], comparison["checks"])
                    if row["match"] is False
                ),
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

    prepared = prepare_checked_experiment(checked)
    if isinstance(prepared, ExperimentExecutionRefusal):
        return prepared.report
    assert isinstance(prepared, PreparedExperimentExecution)
    original_reproduction = original.artifacts["reproduction-receipt"]
    if not _same_complete_reproduction(
        original_reproduction, prepared.reproduction.value
    ):
        return _evaluation_refusal(
            checked,
            "evaluation.replay_reproduction_mismatch",
            "/original_experiment_run_artifact_set_receipt/reproduction-receipt",
            "The prepared Runtime does not match the original reproduction identity",
        )
    execution = execute_prepared_experiment(prepared)
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
            validate_member,
            publication_fault,
            artifact_set_validator=validate_set,
            authentication_key=authentication_key,
        )
        return execution.report.model_copy(update={"terminal_audit": receipt})

    comparison = compare_exact_replay(
        language_bundle=checked.language_bundle,
        original_artifact_set_receipt_identity=original_receipt_identity,
        original_members=original_members,
        replay_members=execution.members,
    )
    publication_members = {
        "replay-comparison": comparison,
        **{
            name: member
            for name, member in execution.members.items()
            if name != "experiment-verdict"
        },
    }
    matched = comparison.value["result"] == "matched"
    artifact_set = success_artifact_set if matched else verdict_artifact_set
    receipt = publish_artifact_set(
        publication_members,
        out,
        invocation_key,
        descriptor_identity,
        input_identity,
        checked.language_bundle,
        artifact_set,
        validate_member,
        publication_fault,
        artifact_set_validator=validate_set,
        authentication_key=authentication_key,
    )
    if matched:
        return ExperimentReplayPublication(receipt=receipt)
    return ExperimentReplayVerdictPublication(
        mismatches=tuple(
            cast(str, row["key"])
            for row in cast(list[dict[str, Any]], comparison.value["checks"])
            if row["match"] is False
        ),
        receipt=receipt,
    )
