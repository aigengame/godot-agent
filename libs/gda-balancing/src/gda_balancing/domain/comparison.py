"""Domain Comparison semantics for exact Experiment Replay."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from gda_balancing.domain.artifacts import ArtifactContract, select_artifact_contract
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    _deep_freeze,
)
from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    RefusalStage,
    Schema2Diagnostic,
    Schema2RefusalReport,
    reason_by_id,
)
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.experiment import CheckedExperiment
from gda_balancing.domain.publication_types import PublicationMember


EXACT_REPLAY_COMPARISON_IMPLEMENTATION = (
    "gda-balancing.python-exact-replay-comparator-v1"
)
EXACT_REPLAY_REFUSAL_REASONS = (
    "evaluation.reason.replay-ineligible-outcome",
    "evaluation.reason.replay-reproduction-mismatch",
)
_EXACT_REPLAY_POLICY = "exact-replay-v1"
_EXACT_REPLAY_INPUT_IDENTITY_DOMAIN = "experiment-replay-command-input-v1"


@dataclass(frozen=True)
class ExactReplayContract:
    """One admitted Replay policy and its immutable result/refusal contracts."""

    policy_binding: Mapping[str, Any]
    reasons: Mapping[str, Mapping[str, Any]]
    artifact: ArtifactContract

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_binding", _deep_freeze(self.policy_binding))
        object.__setattr__(self, "reasons", _deep_freeze(self.reasons))


def select_exact_replay_contract(
    authority_context: AdmittedAuthorityContext,
) -> ExactReplayContract:
    """Select Replay inputs once from their admitted policy and reason owners."""
    binding = authority_context.replay_comparison_policy_index.get(_EXACT_REPLAY_POLICY)
    if binding is None:
        raise ValueError("the exact Replay policy is not admitted")
    _policy_binding(binding)
    reasons = {
        reason_id: reason_by_id(authority_context.language_bundle, reason_id)
        for reason_id in EXACT_REPLAY_REFUSAL_REASONS
    }
    if any(reason["stage"] != "evaluation" for reason in reasons.values()):
        raise ValueError("an exact Replay refusal reason belongs to the wrong stage")
    return ExactReplayContract(
        policy_binding=binding,
        reasons=reasons,
        artifact=select_artifact_contract(
            authority_context.language_bundle, "replay-comparison"
        ),
    )


def exact_replay_input_identity(
    experiment_identity: str,
    original_artifact_set_receipt_identity: str,
) -> str:
    """Bind one Replay retry to its Experiment and authenticated original run."""
    return content_identity(
        _EXACT_REPLAY_INPUT_IDENTITY_DOMAIN,
        cast(
            JsonValue,
            {
                "experiment_identity": experiment_identity,
                "original_experiment_run_artifact_set_receipt_identity": (
                    original_artifact_set_receipt_identity
                ),
            },
        ),
    )


def _exact_replay_refusal(
    checked: CheckedExperiment,
    replay_contract: ExactReplayContract,
    reason_id: str,
    pointer: str,
    message: str,
) -> Schema2RefusalReport:
    reason = replay_contract.reasons[reason_id]
    stage = cast(RefusalStage, reason["stage"])
    if stage != "evaluation":
        raise ValueError("an exact Replay refusal reason belongs to the wrong stage")
    return Schema2RefusalReport(
        stage=stage,
        diagnostics=(
            Schema2Diagnostic(
                code=cast(str, reason["diagnostic"]),
                message=message,
                primary=ArtifactLocation(
                    content_identity=checked.content_identity,
                    pointer=pointer,
                ),
            ),
        ),
        truncated=False,
    )


def exact_replay_original_refusal(
    checked: CheckedExperiment,
    original_artifacts: dict[str, dict[str, Any]],
    replay_contract: ExactReplayContract,
) -> Schema2RefusalReport | None:
    """Apply the LDB-owned eligibility and binding rules to an original run."""
    if "evaluation-run" not in original_artifacts:
        return _exact_replay_refusal(
            checked,
            replay_contract,
            "evaluation.reason.replay-ineligible-outcome",
            "/original_experiment_run_artifact_set_receipt",
            "The original publication is not a successful Evaluation run",
        )
    if not validate_experiment_artifact_set(checked, original_artifacts):
        return _exact_replay_refusal(
            checked,
            replay_contract,
            "evaluation.reason.replay-reproduction-mismatch",
            "/original_experiment_run_artifact_set_receipt",
            "The original publication does not bind this Experiment",
        )
    return None


def exact_replay_runtime_profile_refusal(
    checked: CheckedExperiment,
    original_runtime: dict[str, Any],
    prepared_runtime: dict[str, Any],
    replay_contract: ExactReplayContract,
) -> Schema2RefusalReport | None:
    """Require the same admitted semantic execution identity before dispatch."""
    contract = checked.output_contracts["resolved-runtime-profile"]
    if (
        contract.verify(original_runtime)
        and contract.verify(prepared_runtime)
        and original_runtime["content_identity"] == prepared_runtime["content_identity"]
    ):
        return None
    return _exact_replay_refusal(
        checked,
        replay_contract,
        "evaluation.reason.replay-reproduction-mismatch",
        "/original_experiment_run_artifact_set_receipt/resolved-runtime-profile",
        "The prepared Runtime does not match the original semantic execution identity",
    )


def _policy_binding(
    binding: Mapping[str, Any],
) -> tuple[dict[str, str], list[str]]:
    policy = cast(Mapping[str, Any], binding["policy"])
    owner = cast(Mapping[str, Any], binding["owner"])
    if policy.get("comparator") != "canonical-equal":
        raise ValueError("the exact Replay policy comparator is unsupported")
    checks = policy.get("checks")
    if not isinstance(checks, list) or not checks or len(checks) != len(set(checks)):
        raise ValueError("the exact Replay policy has no closed ordered checks")
    return (
        {
            "id": cast(str, policy["id"]),
            "package": cast(str, owner["package"]),
        },
        cast(list[str], checks),
    )


def _member_value(
    members: dict[str, PublicationMember],
    logical_name: str,
    output_contracts: Mapping[str, ArtifactContract],
) -> dict[str, Any]:
    member = members.get(logical_name)
    contract = output_contracts.get(logical_name)
    if (
        member is None
        or contract is None
        or member.artifact_kind != logical_name
        or member.value.get("artifact_kind") != logical_name
        or member.value.get("content_identity") != member.content_identity
        or not contract.verify(member.value)
    ):
        raise ValueError(f"invalid Replay observation member: {logical_name}")
    return member.value


def _producing_outcome(
    members: dict[str, PublicationMember],
    output_contracts: Mapping[str, ArtifactContract],
    *,
    require_primary: bool,
) -> tuple[dict[str, str], str, str, dict[str, Any]]:
    resolved_runtime = _member_value(
        members, "resolved-runtime-profile", output_contracts
    )
    _member_value(members, "evaluator-capability-manifest", output_contracts)
    trace = _member_value(members, "event-trace", output_contracts)
    snapshots = _member_value(members, "snapshot-series", output_contracts)
    metrics = _member_value(members, "metric-dataset", output_contracts)
    experiment_identity = resolved_runtime["experiment_identity"]
    runtime_identity = resolved_runtime["content_identity"]
    if any(
        artifact.get("experiment_identity") != experiment_identity
        or artifact.get("resolved_runtime_profile_identity") != runtime_identity
        for artifact in (trace, snapshots, metrics)
    ):
        raise ValueError("Replay observations do not bind the semantic execution")
    if snapshots.get("event_trace_identity") != trace[
        "content_identity"
    ] or snapshots.get("root_event_map") != trace.get("root_event_map"):
        raise ValueError("Replay observation support is inconsistent")

    samples = metrics.get("samples")
    if not isinstance(samples, list):
        raise ValueError("Replay Metric dataset has no samples")
    failed_metrics = [
        sample.get("metric")
        for sample in samples
        if isinstance(sample, dict) and sample.get("within_target") is False
    ]
    if not all(isinstance(metric, str) for metric in failed_metrics):
        raise ValueError("Replay Metric failures are invalid")
    outcome_kind = "experiment-verdict" if failed_metrics else "evaluation-run"
    outcome_status = "rejected" if failed_metrics else "accepted"
    payload: dict[str, JsonValue] = {
        "experiment_identity": cast(str, experiment_identity),
        "resolved_runtime_profile_identity": runtime_identity,
        "event_trace_identity": cast(str, trace["content_identity"]),
        "snapshot_series_identity": cast(str, snapshots["content_identity"]),
        "metric_dataset_identity": cast(str, metrics["content_identity"]),
        "root_event_map": cast(JsonValue, trace["root_event_map"]),
        "terminal_statuses": cast(JsonValue, trace["terminal_statuses"]),
        "outcome": outcome_status,
    }
    if failed_metrics:
        payload["failed_metrics"] = cast(JsonValue, failed_metrics)
    expected_outcome = output_contracts[outcome_kind].identify(payload)
    present_primary_names = [
        name for name in ("evaluation-run", "experiment-verdict") if name in members
    ]
    if require_primary and present_primary_names != [outcome_kind]:
        raise ValueError("Replay observation has an ineligible producing outcome")
    if present_primary_names:
        if present_primary_names != [outcome_kind]:
            raise ValueError("Replay producing outcome kind is inconsistent")
        primary = _member_value(members, outcome_kind, output_contracts)
        if canonical_bytes(cast(JsonValue, primary)) != canonical_bytes(
            cast(JsonValue, expected_outcome)
        ):
            raise ValueError("Replay producing outcome is inconsistent")
    observation = {
        "evaluation_outcome_status": outcome_status,
        "event_trace_identity": cast(str, trace["content_identity"]),
        "snapshot_series_identity": cast(str, snapshots["content_identity"]),
        "metric_dataset_identity": cast(str, metrics["content_identity"]),
    }
    return (
        observation,
        outcome_kind,
        cast(str, expected_outcome["content_identity"]),
        resolved_runtime,
    )


def _observation(
    members: dict[str, PublicationMember],
    output_contracts: Mapping[str, ArtifactContract],
    *,
    original: bool,
) -> tuple[dict[str, str], str, str]:
    observation, primary_name, primary_identity, _resolved_runtime = _producing_outcome(
        members, output_contracts, require_primary=True
    )
    if original and primary_name != "evaluation-run":
        raise ValueError("the original producing outcome is not an Evaluation run")
    return observation, primary_name, primary_identity


def _comparison_value(
    *,
    replay_contract: ExactReplayContract,
    output_contracts: Mapping[str, ArtifactContract],
    original_artifact_set_receipt_identity: str,
    original_members: dict[str, PublicationMember],
    replay_members: dict[str, PublicationMember],
) -> dict[str, JsonValue]:
    if not original_artifact_set_receipt_identity:
        raise ValueError("the original Artifact-set receipt identity is empty")
    policy, policy_checks = _policy_binding(replay_contract.policy_binding)
    original, original_kind, original_identity = _observation(
        original_members, output_contracts, original=True
    )
    replay, replay_kind, replay_identity = _observation(
        replay_members, output_contracts, original=False
    )
    original_runtime = _member_value(
        original_members, "resolved-runtime-profile", output_contracts
    )
    replay_runtime = _member_value(
        replay_members, "resolved-runtime-profile", output_contracts
    )
    if original_runtime["content_identity"] != replay_runtime["content_identity"]:
        raise ValueError("Replay inputs do not share one semantic execution identity")

    observations = {
        "evaluation-outcome-status": "evaluation_outcome_status",
        "event-trace-identity": "event_trace_identity",
        "snapshot-series-identity": "snapshot_series_identity",
        "metric-dataset-identity": "metric_dataset_identity",
    }
    if policy_checks != list(observations):
        raise ValueError("the admitted Replay policy has unsupported checks")
    checks = [
        {
            "key": key,
            "match": canonical_bytes(cast(JsonValue, original[member]))
            == canonical_bytes(cast(JsonValue, replay[member])),
            "original": original[member],
            "replay": replay[member],
        }
        for key, member in observations.items()
    ]
    return cast(
        dict[str, JsonValue],
        replay_contract.artifact.identify(
            {
                "comparison_implementation_identity": (
                    EXACT_REPLAY_COMPARISON_IMPLEMENTATION
                ),
                "original_artifact_set_receipt_identity": (
                    original_artifact_set_receipt_identity
                ),
                "original_evaluation_run_identity": original_identity,
                "replay_outcome_kind": replay_kind,
                "replay_outcome_identity": replay_identity,
                "policy": cast(JsonValue, policy),
                "original_observation": cast(JsonValue, original),
                "replay_observation": cast(JsonValue, replay),
                "checks": cast(JsonValue, checks),
                "result": (
                    "matched"
                    if all(cast(bool, check["match"]) for check in checks)
                    else "mismatched"
                ),
            },
        ),
    )


def compare_exact_replay(
    *,
    replay_contract: ExactReplayContract,
    output_contracts: Mapping[str, ArtifactContract],
    original_artifact_set_receipt_identity: str,
    original_members: dict[str, PublicationMember],
    replay_members: dict[str, PublicationMember],
) -> PublicationMember:
    """Apply the admitted exact Replay policy to explicit observations."""
    value = _comparison_value(
        replay_contract=replay_contract,
        output_contracts=output_contracts,
        original_artifact_set_receipt_identity=(original_artifact_set_receipt_identity),
        original_members=original_members,
        replay_members=replay_members,
    )
    if not validate_exact_replay_comparison(
        value,
        replay_contract=replay_contract,
        output_contracts=output_contracts,
        original_artifact_set_receipt_identity=(original_artifact_set_receipt_identity),
        original_members=original_members,
        replay_members=replay_members,
    ):
        raise ValueError("constructed Replay comparison failed independent validation")
    return PublicationMember(
        value=value,
        artifact_kind="replay-comparison",
        wire_schema_identity=cast(str, value["wire_schema_identity"]),
        content_identity=cast(str, value["content_identity"]),
    )


def validate_exact_replay_comparison(
    value: dict[str, Any],
    *,
    replay_contract: ExactReplayContract,
    output_contracts: Mapping[str, ArtifactContract],
    original_artifact_set_receipt_identity: str,
    original_members: dict[str, PublicationMember],
    replay_members: dict[str, PublicationMember],
) -> bool:
    """Independently reconstruct and validate every Replay comparison binding."""
    try:
        expected = _comparison_value(
            replay_contract=replay_contract,
            output_contracts=output_contracts,
            original_artifact_set_receipt_identity=(
                original_artifact_set_receipt_identity
            ),
            original_members=original_members,
            replay_members=replay_members,
        )
    except (KeyError, TypeError, ValueError):
        return False
    return replay_contract.artifact.verify(value) and canonical_bytes(
        cast(JsonValue, value)
    ) == canonical_bytes(cast(JsonValue, expected))


def validate_published_exact_replay_comparison(
    value: dict[str, Any],
    *,
    replay_contract: ExactReplayContract,
    output_contracts: Mapping[str, ArtifactContract],
    original_artifact_set_receipt_identity: str,
    original_members: dict[str, PublicationMember],
    replay_members: dict[str, PublicationMember],
) -> bool:
    """Validate a published comparison from its retained supporting members."""
    try:
        policy, policy_checks = _policy_binding(replay_contract.policy_binding)
        original, original_kind, original_identity = _observation(
            original_members, output_contracts, original=True
        )
        replay, replay_kind, replay_identity, replay_runtime = _producing_outcome(
            replay_members,
            output_contracts,
            require_primary=False,
        )
        original_runtime = _member_value(
            original_members, "resolved-runtime-profile", output_contracts
        )
        if original_runtime["content_identity"] != replay_runtime["content_identity"]:
            return False

        observations = {
            "evaluation-outcome-status": "evaluation_outcome_status",
            "event-trace-identity": "event_trace_identity",
            "snapshot-series-identity": "snapshot_series_identity",
            "metric-dataset-identity": "metric_dataset_identity",
        }
        checks = [
            {
                "key": key,
                "match": canonical_bytes(cast(JsonValue, original[member]))
                == canonical_bytes(cast(JsonValue, replay[member])),
                "original": original[member],
                "replay": replay[member],
            }
            for key, member in observations.items()
        ]
        expected_result = (
            "matched"
            if all(cast(bool, row["match"]) for row in checks)
            else "mismatched"
        )
        return (
            original_kind == "evaluation-run"
            and replay_contract.artifact.verify(value)
            and value.get("comparison_implementation_identity")
            == EXACT_REPLAY_COMPARISON_IMPLEMENTATION
            and value.get("original_artifact_set_receipt_identity")
            == original_artifact_set_receipt_identity
            and value.get("original_evaluation_run_identity") == original_identity
            and value.get("replay_outcome_kind") == replay_kind
            and value.get("replay_outcome_identity") == replay_identity
            and canonical_bytes(cast(JsonValue, value.get("policy")))
            == canonical_bytes(cast(JsonValue, policy))
            and policy_checks == list(observations)
            and canonical_bytes(cast(JsonValue, value.get("original_observation")))
            == canonical_bytes(cast(JsonValue, original))
            and canonical_bytes(cast(JsonValue, value.get("replay_observation")))
            == canonical_bytes(cast(JsonValue, replay))
            and canonical_bytes(cast(JsonValue, value.get("checks")))
            == canonical_bytes(cast(JsonValue, checks))
            and value.get("result") == expected_result
        )
    except (KeyError, TypeError, ValueError):
        return False
