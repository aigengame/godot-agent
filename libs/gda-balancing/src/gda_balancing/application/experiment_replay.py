"""Authenticate, execute, compare, and publish one exact Experiment Replay."""

from dataclasses import dataclass
from typing import Any, cast

from gda_balancing.application.experiment_inputs import check_experiment_inputs
from gda_balancing.application.experiment_execution import (
    ExperimentExecutionRefusal,
    PreparedExperimentExecution,
    execute_prepared_experiment,
    prepare_checked_experiment,
)
from gda_balancing.domain.artifacts import artifacts_by_protocol_role
from gda_balancing.domain.artifact_set import ArtifactSetPlan, resolve_artifact_set, label_artifacts
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.comparison import (
    compare_exact_replay,
    select_exact_replay_contract,
    exact_replay_input_identity,
    exact_replay_original_refusal,
    exact_replay_runtime_profile_refusal,
    validate_published_exact_replay_comparison,
)
from gda_balancing.domain.diagnostics import (
    Schema2Diagnostic,
    Schema2RefusalReport,
    ingress_refusal,
)
from gda_balancing.domain.experiment_artifacts import (
    validate_experiment_artifact_set,
    validate_experiment_member,
)
from gda_balancing.domain.experiment import CheckedExperiment
from gda_balancing.domain.publication import (
    publication_authentication_key,
    select_publication_contracts,
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


def replay_experiment(
    specification: str,
    original_receipt: str,
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    original_artifact_sets: tuple[ArtifactSetPlan, ...],
    success_artifact_set: ArtifactSetPlan,
    verdict_artifact_set: ArtifactSetPlan,
    runtime_refusal_artifact_set: ArtifactSetPlan,
    *,
    rir: str,
    publication_fault: str | None = None,
) -> (
    ExperimentReplayPublication
    | ExperimentReplayVerdictPublication
    | Schema2RefusalReport
):
    """Authenticate one original run and publish an exact Replay comparison."""
    authority_context = packaged_authority_context()
    success_artifact_set = resolve_artifact_set(
        authority_context.language_bundle, success_artifact_set
    )
    verdict_artifact_set = resolve_artifact_set(
        authority_context.language_bundle, verdict_artifact_set
    )
    runtime_refusal_artifact_set = resolve_artifact_set(
        authority_context.language_bundle, runtime_refusal_artifact_set
    )
    try:
        original = read_authenticated_declared_artifact_set(
            original_receipt,
            original_artifact_sets,
            authority_context=authority_context,
        )
    except PublicationAdmissionError as error:
        return ingress_refusal(error.code, error.subject, error.message)
    checked = check_experiment_inputs(
        specification,
        rir,
        authority_context=original.authority_context,
    )
    if isinstance(checked, Schema2RefusalReport):
        return checked
    assert isinstance(checked, CheckedExperiment)
    authority_context = checked.authority_context
    assert authority_context is not None
    original_artifacts = artifacts_by_protocol_role(checked.language_bundle, original.artifacts)
    original_members = _publication_members(original_artifacts)
    original_receipt_identity = cast(str, original.receipt["content_identity"])
    input_identity = exact_replay_input_identity(
        checked.content_identity,
        original_receipt_identity,
    )
    authentication_key = publication_authentication_key()
    publication_contracts = select_publication_contracts(checked.language_bundle)
    replay_contract = select_exact_replay_contract(authority_context)

    def validate_member(logical_name: str, value: dict[str, Any]) -> bool:
        if value.get("artifact_kind") == replay_contract.artifact.definition["artifact_kind"]:
            return replay_contract.artifact.verify(value)
        return validate_experiment_member(checked, logical_name, value)

    def validate_set(artifacts: dict[str, dict[str, Any]]) -> bool:
        try:
            artifacts = artifacts_by_protocol_role(checked.language_bundle, artifacts)
        except (KeyError, TypeError, ValueError):
            return False
        if "runtime-terminal-audit" in artifacts:
            return validate_experiment_artifact_set(checked, artifacts)
        comparison = artifacts.get("replay-comparison")
        if not isinstance(comparison, dict):
            return False
        return validate_published_exact_replay_comparison(
            comparison,
            replay_contract=replay_contract,
            output_contracts=checked.output_contracts,
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
        publication_contracts,
        (success_artifact_set, verdict_artifact_set, runtime_refusal_artifact_set),
        validate_member,
        artifact_set_validator=validate_set,
        authentication_key=authentication_key,
    )
    if recovered is not None:
        recovered_artifacts = artifacts_by_protocol_role(checked.language_bundle, recovered.artifacts)
        if recovered.artifact_set == success_artifact_set:
            return ExperimentReplayPublication(receipt=recovered.receipt)
        if recovered.artifact_set == verdict_artifact_set:
            comparison = recovered_artifacts["replay-comparison"]
            return ExperimentReplayVerdictPublication(
                mismatches=tuple(
                    cast(str, row["key"])
                    for row in cast(list[dict[str, Any]], comparison["checks"])
                    if row["match"] is False
                ),
                receipt=recovered.receipt,
            )
        audit = recovered_artifacts["runtime-terminal-audit"]
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

    original_refusal = exact_replay_original_refusal(
        checked, original_artifacts, replay_contract
    )
    if original_refusal is not None:
        return original_refusal
    prepared = prepare_checked_experiment(checked)
    if isinstance(prepared, ExperimentExecutionRefusal):
        return prepared.report
    assert isinstance(prepared, PreparedExperimentExecution)
    runtime_refusal = exact_replay_runtime_profile_refusal(
        checked,
        original_artifacts["resolved-runtime-profile"],
        prepared.resolved_runtime.value,
        replay_contract,
    )
    if runtime_refusal is not None:
        return runtime_refusal
    execution = execute_prepared_experiment(prepared)
    if isinstance(execution, ExperimentExecutionRefusal):
        if not execution.members:
            return execution.report
        receipt = publish_artifact_set(
            label_artifacts(execution.members, runtime_refusal_artifact_set, lambda member: member.artifact_kind),
            out,
            invocation_key,
            descriptor_identity,
            input_identity,
            publication_contracts,
            runtime_refusal_artifact_set,
            validate_member,
            publication_fault,
            artifact_set_validator=validate_set,
            authentication_key=authentication_key,
        )
        return execution.report.model_copy(update={"terminal_audit": receipt})

    comparison = compare_exact_replay(
        replay_contract=replay_contract,
        output_contracts=checked.output_contracts,
        original_artifact_set_receipt_identity=original_receipt_identity,
        original_members=original_members,
        replay_members=execution.members,
    )
    matched = comparison.value["result"] == "matched"
    omitted_outcomes = (
        {"experiment-verdict"} if matched else {"evaluation-run", "experiment-verdict"}
    )
    publication_members = {
        "replay-comparison": comparison,
        **{
            name: member
            for name, member in execution.members.items()
            if name not in omitted_outcomes
        },
    }
    artifact_set = success_artifact_set if matched else verdict_artifact_set
    receipt = publish_artifact_set(
        label_artifacts(publication_members, artifact_set, lambda member: member.artifact_kind),
        out,
        invocation_key,
        descriptor_identity,
        input_identity,
        publication_contracts,
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
