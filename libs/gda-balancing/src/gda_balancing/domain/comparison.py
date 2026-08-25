"""Domain Comparison semantics for exact Experiment Replay."""

from typing import Any, cast

from gda_balancing.domain.artifacts import identified_artifact, verify_artifact
from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from gda_balancing.domain.publication_types import PublicationMember


EXACT_REPLAY_COMPARISON_IMPLEMENTATION = (
    "gda-balancing.python-exact-replay-comparator-v1"
)
_EXACT_REPLAY_POLICY = "exact-replay-v1"
_OBSERVATION_MEMBERS = {
    "event_trace_identity": "event-trace",
    "snapshot_series_identity": "snapshot-series",
    "metric_dataset_identity": "metric-dataset",
}


def _policy_binding(
    language_bundle: dict[str, Any],
) -> tuple[dict[str, str], list[str]]:
    language = cast(dict[str, Any], language_bundle["language"])
    matches = [
        policy
        for policy in cast(list[dict[str, Any]], language["replay_comparison_policies"])
        if policy.get("id") == _EXACT_REPLAY_POLICY
    ]
    if len(matches) != 1 or matches[0].get("comparator") != "canonical-equal":
        raise ValueError("the exact Replay policy is not uniquely admitted")
    policy = matches[0]
    checks = policy.get("checks")
    if not isinstance(checks, list) or not checks or len(checks) != len(set(checks)):
        raise ValueError("the exact Replay policy has no closed ordered checks")
    owners = [
        release
        for release in cast(list[dict[str, Any]], language["packages"])
        if _EXACT_REPLAY_POLICY
        in cast(
            list[str], release.get("exports", {}).get("replay_comparison_policies", [])
        )
    ]
    if len(owners) != 1:
        raise ValueError("the exact Replay policy has no unique Package owner")
    owner = owners[0]
    return (
        {
            "id": cast(str, policy["id"]),
            "package": cast(str, owner["id"]),
            "package_version": cast(str, owner["version"]),
            "version": cast(str, policy["version"]),
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


def _observation(
    members: dict[str, PublicationMember],
    language_bundle: dict[str, Any],
    *,
    original: bool,
) -> tuple[dict[str, str], str, str]:
    primary_names = [
        name for name in ("evaluation-run", "experiment-verdict") if name in members
    ]
    eligible = (
        primary_names == ["evaluation-run"] if original else len(primary_names) == 1
    )
    if not eligible:
        raise ValueError("Replay observation has an ineligible producing outcome")
    primary_name = primary_names[0]
    primary = _member_value(members, primary_name, language_bundle)
    expected_outcome = "accepted" if primary_name == "evaluation-run" else "rejected"
    observation = {"evaluation_outcome_status": expected_outcome}
    for identity_member, logical_name in _OBSERVATION_MEMBERS.items():
        member = _member_value(members, logical_name, language_bundle)
        if primary.get(identity_member) != member["content_identity"]:
            raise ValueError(f"Replay outcome does not bind {logical_name}")
        observation[identity_member] = cast(str, member["content_identity"])
    if primary.get("outcome") != expected_outcome:
        raise ValueError("Replay outcome status is inconsistent")
    return (
        observation,
        primary_name,
        cast(str, primary["content_identity"]),
    )


def _comparison_value(
    *,
    language_bundle: dict[str, Any],
    original_artifact_set_receipt_identity: str,
    original_members: dict[str, PublicationMember],
    replay_members: dict[str, PublicationMember],
) -> dict[str, JsonValue]:
    if not original_artifact_set_receipt_identity:
        raise ValueError("the original Artifact-set receipt identity is empty")
    policy, policy_checks = _policy_binding(language_bundle)
    original, original_kind, original_identity = _observation(
        original_members, language_bundle, original=True
    )
    replay, replay_kind, replay_identity = _observation(
        replay_members, language_bundle, original=False
    )
    if original_kind != "evaluation-run":
        raise ValueError("the original producing outcome is not an Evaluation run")
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
    language_bundle: dict[str, Any],
    original_artifact_set_receipt_identity: str,
    original_members: dict[str, PublicationMember],
    replay_members: dict[str, PublicationMember],
) -> PublicationMember:
    """Apply the admitted exact Replay policy to explicit observations."""
    value = _comparison_value(
        language_bundle=language_bundle,
        original_artifact_set_receipt_identity=(original_artifact_set_receipt_identity),
        original_members=original_members,
        replay_members=replay_members,
    )
    if not validate_exact_replay_comparison(
        value,
        language_bundle=language_bundle,
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
    language_bundle: dict[str, Any],
    original_artifact_set_receipt_identity: str,
    original_members: dict[str, PublicationMember],
    replay_members: dict[str, PublicationMember],
) -> bool:
    """Independently reconstruct and validate every Replay comparison binding."""
    try:
        expected = _comparison_value(
            language_bundle=language_bundle,
            original_artifact_set_receipt_identity=(
                original_artifact_set_receipt_identity
            ),
            original_members=original_members,
            replay_members=replay_members,
        )
    except (KeyError, TypeError, ValueError):
        return False
    return verify_artifact(value, language_bundle) and canonical_bytes(
        cast(JsonValue, value)
    ) == canonical_bytes(cast(JsonValue, expected))


def validate_published_exact_replay_comparison(
    value: dict[str, Any],
    *,
    language_bundle: dict[str, Any],
    original_artifact_set_receipt_identity: str,
    original_members: dict[str, PublicationMember],
    replay_members: dict[str, PublicationMember],
) -> bool:
    """Validate a published comparison from its retained supporting members."""
    try:
        policy, policy_checks = _policy_binding(language_bundle)
        original, original_kind, original_identity = _observation(
            original_members, language_bundle, original=True
        )
        replay = cast(dict[str, str], value["replay_observation"])
        if set(replay) != {
            "evaluation_outcome_status",
            *_OBSERVATION_MEMBERS,
        }:
            return False
        for identity_member, logical_name in _OBSERVATION_MEMBERS.items():
            member = _member_value(replay_members, logical_name, language_bundle)
            if replay[identity_member] != member["content_identity"]:
                return False
        replay_kind = value.get("replay_outcome_kind")
        if replay_kind not in {"evaluation-run", "experiment-verdict"}:
            return False
        if replay_kind == "evaluation-run":
            replay_primary = _member_value(
                replay_members, "evaluation-run", language_bundle
            )
            if value.get("replay_outcome_identity") != replay_primary.get(
                "content_identity"
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
            and canonical_bytes(cast(JsonValue, value.get("policy")))
            == canonical_bytes(cast(JsonValue, policy))
            and policy_checks == list(observations)
            and canonical_bytes(cast(JsonValue, value.get("original_observation")))
            == canonical_bytes(cast(JsonValue, original))
            and canonical_bytes(cast(JsonValue, value.get("checks")))
            == canonical_bytes(cast(JsonValue, checks))
            and value.get("result") == expected_result
        )
    except (KeyError, TypeError, ValueError):
        return False
