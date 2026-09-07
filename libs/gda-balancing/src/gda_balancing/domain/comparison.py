"""Domain Comparison semantics for exact Experiment Replay."""

from collections.abc import Mapping
from typing import Any, cast

from gda_balancing.domain.artifacts import identified_artifact, verify_artifact
from gda_balancing.domain.authority.context import AdmittedAuthorityContext
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
_REPRODUCTION_BINDINGS = (
    "experiment_identity",
    "kernel_identity",
    "language_bundle_identity",
    "package_lock_identity",
    "resolved_model_identity",
    "rir_identity",
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
    reason_id: str,
    pointer: str,
    message: str,
) -> Schema2RefusalReport:
    reason = reason_by_id(checked.language_bundle, reason_id)
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
) -> Schema2RefusalReport | None:
    """Apply the LDB-owned eligibility and binding rules to an original run."""
    if "evaluation-run" not in original_artifacts:
        return _exact_replay_refusal(
            checked,
            "evaluation.reason.replay-ineligible-outcome",
            "/original_experiment_run_artifact_set_receipt",
            "The original publication is not a successful Evaluation run",
        )
    if not validate_experiment_artifact_set(checked, original_artifacts):
        return _exact_replay_refusal(
            checked,
            "evaluation.reason.replay-reproduction-mismatch",
            "/original_experiment_run_artifact_set_receipt",
            "The original publication does not bind this Experiment",
        )
    return None


def exact_replay_reproduction_refusal(
    checked: CheckedExperiment,
    original_reproduction: dict[str, Any],
    prepared_reproduction: dict[str, Any],
) -> Schema2RefusalReport | None:
    """Require exact complete reproduction equality before Replay dispatch."""
    if canonical_bytes(cast(JsonValue, original_reproduction)) == canonical_bytes(
        cast(JsonValue, prepared_reproduction)
    ):
        return None
    return _exact_replay_refusal(
        checked,
        "evaluation.reason.replay-reproduction-mismatch",
        "/original_experiment_run_artifact_set_receipt/reproduction-receipt",
        "The prepared Runtime does not match the original reproduction identity",
    )


def _policy_binding(
    policy_index: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    binding = policy_index.get(_EXACT_REPLAY_POLICY)
    if binding is None:
        raise ValueError("the exact Replay policy is not admitted")
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
    language_bundle: dict[str, Any],
) -> dict[str, Any]:
    member = members.get(logical_name)
    if (
        member is None
        or member.artifact_kind != logical_name
        or member.value.get("artifact_kind") != logical_name
        or member.value.get("content_identity") != member.content_identity
        or not verify_artifact(member.value, language_bundle)
    ):
        raise ValueError(f"invalid Replay observation member: {logical_name}")
    return member.value


def _reproduction_members(
    members: dict[str, PublicationMember],
    language_bundle: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    reproduction = _member_value(members, "reproduction-receipt", language_bundle)
    resolved_runtime = _member_value(
        members, "resolved-runtime-profile", language_bundle
    )
    evaluator = _member_value(members, "evaluator-capability-manifest", language_bundle)
    if any(
        reproduction.get(name) != resolved_runtime.get(name)
        for name in _REPRODUCTION_BINDINGS
    ):
        raise ValueError("Replay reproduction does not bind the Resolved Runtime")
    if (
        reproduction.get("resolved_runtime_profile_identity")
        != resolved_runtime["content_identity"]
        or reproduction.get("evaluator_manifest_identity")
        != evaluator["content_identity"]
        or resolved_runtime.get("evaluator_manifest_identity")
        != evaluator["content_identity"]
        or evaluator.get("kernel_identity") != reproduction.get("kernel_identity")
        or evaluator.get("language_bundle_identity")
        != reproduction.get("language_bundle_identity")
        or reproduction.get("language_bundle_identity")
        != language_bundle["content_identity"]
    ):
        raise ValueError("Replay reproduction support is inconsistent")
    return reproduction, resolved_runtime, evaluator


def _producing_outcome(
    members: dict[str, PublicationMember],
    language_bundle: dict[str, Any],
    *,
    require_primary: bool,
) -> tuple[dict[str, str], str, str, dict[str, Any]]:
    reproduction, resolved_runtime, evaluator = _reproduction_members(
        members, language_bundle
    )
    trace = _member_value(members, "event-trace", language_bundle)
    snapshots = _member_value(members, "snapshot-series", language_bundle)
    metrics = _member_value(members, "metric-dataset", language_bundle)
    experiment_identity = reproduction["experiment_identity"]
    runtime_identity = resolved_runtime["content_identity"]
    if any(
        artifact.get("experiment_identity") != experiment_identity
        or artifact.get("resolved_runtime_profile_identity") != runtime_identity
        for artifact in (trace, snapshots, metrics)
    ):
        raise ValueError("Replay observations do not bind the reproduction")
    provenance = metrics.get("source_provenance")
    if (
        snapshots.get("event_trace_identity") != trace["content_identity"]
        or snapshots.get("root_event_map") != trace.get("root_event_map")
        or not isinstance(provenance, dict)
        or provenance.get("resolved_model_identity")
        != reproduction.get("resolved_model_identity")
        or provenance.get("resolved_runtime_profile_identity") != runtime_identity
        or provenance.get("evaluator_manifest_identity")
        != evaluator["content_identity"]
    ):
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
        "reproduction_receipt_identity": cast(str, reproduction["content_identity"]),
        "root_event_map": cast(JsonValue, trace["root_event_map"]),
        "terminal_statuses": cast(JsonValue, trace["terminal_statuses"]),
        "outcome": outcome_status,
    }
    if failed_metrics:
        payload["failed_metrics"] = cast(JsonValue, failed_metrics)
    else:
        payload["evaluator_manifest_identity"] = cast(
            str, evaluator["content_identity"]
        )
    expected_outcome = identified_artifact(language_bundle, outcome_kind, payload)
    present_primary_names = [
        name for name in ("evaluation-run", "experiment-verdict") if name in members
    ]
    if require_primary and present_primary_names != [outcome_kind]:
        raise ValueError("Replay observation has an ineligible producing outcome")
    if present_primary_names:
        if present_primary_names != [outcome_kind]:
            raise ValueError("Replay producing outcome kind is inconsistent")
        primary = _member_value(members, outcome_kind, language_bundle)
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
        reproduction,
    )


def _observation(
    members: dict[str, PublicationMember],
    language_bundle: dict[str, Any],
    *,
    original: bool,
) -> tuple[dict[str, str], str, str]:
    observation, primary_name, primary_identity, _reproduction = _producing_outcome(
        members, language_bundle, require_primary=True
    )
    if original and primary_name != "evaluation-run":
        raise ValueError("the original producing outcome is not an Evaluation run")
    return observation, primary_name, primary_identity


def _comparison_value(
    *,
    authority_context: AdmittedAuthorityContext,
    original_artifact_set_receipt_identity: str,
    original_members: dict[str, PublicationMember],
    replay_members: dict[str, PublicationMember],
) -> dict[str, JsonValue]:
    if not original_artifact_set_receipt_identity:
        raise ValueError("the original Artifact-set receipt identity is empty")
    language_bundle = authority_context.language_bundle
    policy, policy_checks = _policy_binding(
        authority_context.replay_comparison_policy_index
    )
    original, original_kind, original_identity = _observation(
        original_members, language_bundle, original=True
    )
    replay, replay_kind, replay_identity = _observation(
        replay_members, language_bundle, original=False
    )
    original_reproduction = _member_value(
        original_members, "reproduction-receipt", language_bundle
    )
    replay_reproduction = _member_value(
        replay_members, "reproduction-receipt", language_bundle
    )
    if canonical_bytes(cast(JsonValue, original_reproduction)) != canonical_bytes(
        cast(JsonValue, replay_reproduction)
    ):
        raise ValueError("Replay inputs do not share one complete reproduction")
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
        identified_artifact(
            language_bundle,
            "replay-comparison",
            {
                "comparison_implementation_identity": (
                    EXACT_REPLAY_COMPARISON_IMPLEMENTATION
                ),
                "language_bundle_identity": language_bundle["content_identity"],
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
    authority_context: AdmittedAuthorityContext,
    original_artifact_set_receipt_identity: str,
    original_members: dict[str, PublicationMember],
    replay_members: dict[str, PublicationMember],
) -> PublicationMember:
    """Apply the admitted exact Replay policy to explicit observations."""
    value = _comparison_value(
        authority_context=authority_context,
        original_artifact_set_receipt_identity=(original_artifact_set_receipt_identity),
        original_members=original_members,
        replay_members=replay_members,
    )
    if not validate_exact_replay_comparison(
        value,
        authority_context=authority_context,
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
    authority_context: AdmittedAuthorityContext,
    original_artifact_set_receipt_identity: str,
    original_members: dict[str, PublicationMember],
    replay_members: dict[str, PublicationMember],
) -> bool:
    """Independently reconstruct and validate every Replay comparison binding."""
    try:
        expected = _comparison_value(
            authority_context=authority_context,
            original_artifact_set_receipt_identity=(
                original_artifact_set_receipt_identity
            ),
            original_members=original_members,
            replay_members=replay_members,
        )
    except (KeyError, TypeError, ValueError):
        return False
    language_bundle = authority_context.language_bundle
    return verify_artifact(value, language_bundle) and canonical_bytes(
        cast(JsonValue, value)
    ) == canonical_bytes(cast(JsonValue, expected))


def validate_published_exact_replay_comparison(
    value: dict[str, Any],
    *,
    authority_context: AdmittedAuthorityContext,
    original_artifact_set_receipt_identity: str,
    original_members: dict[str, PublicationMember],
    replay_members: dict[str, PublicationMember],
) -> bool:
    """Validate a published comparison from its retained supporting members."""
    try:
        language_bundle = authority_context.language_bundle
        policy, policy_checks = _policy_binding(
            authority_context.replay_comparison_policy_index
        )
        original, original_kind, original_identity = _observation(
            original_members, language_bundle, original=True
        )
        replay, replay_kind, replay_identity, replay_reproduction = _producing_outcome(
            replay_members,
            language_bundle,
            require_primary=False,
        )
        original_reproduction = _member_value(
            original_members, "reproduction-receipt", language_bundle
        )
        if canonical_bytes(cast(JsonValue, original_reproduction)) != canonical_bytes(
            cast(JsonValue, replay_reproduction)
        ):
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
            and verify_artifact(value, language_bundle)
            and value.get("comparison_implementation_identity")
            == EXACT_REPLAY_COMPARISON_IMPLEMENTATION
            and value.get("language_bundle_identity")
            == language_bundle["content_identity"]
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
