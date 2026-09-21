"""Leaf projections shared by Package and Replay protocol derivation."""

from typing import Any


def _non_empty_string_schema() -> dict[str, object]:
    return {"type": "string", "minLength": 1}


def replay_observation_schemas(
    meta_format: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Project the existing Replay vector's observation, checks and result owners."""
    kinds = [
        row
        for row in meta_format["package_vector"]["kinds"]
        if row.get("id") == "replay-comparison"
    ]
    if len(kinds) != 1:
        raise ValueError("Kernel Replay vector kind is missing or ambiguous")
    kind = kinds[0]
    if (
        kind.get("input_members") != ["original", "replay"]
        or kind.get("observation_members")
        != [
            "evaluation_outcome_status",
            "event_trace_identity",
            "snapshot_series_identity",
            "metric_dataset_identity",
        ]
        or kind.get("expect_members") != ["checks", "result"]
        or kind.get("check_members") != ["key", "match", "original", "replay"]
        or kind.get("results") != ["matched", "mismatched"]
    ):
        raise ValueError("Kernel replay-comparison vector contract is incomplete")
    observation = {
        "type": "object",
        "properties": {
            member: _non_empty_string_schema() for member in kind["observation_members"]
        },
        "required": list(kind["observation_members"]),
        "unevaluatedProperties": False,
    }
    checks = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "key": _non_empty_string_schema(),
                "match": {"type": "boolean"},
                "original": _non_empty_string_schema(),
                "replay": _non_empty_string_schema(),
            },
            "required": list(kind["check_members"]),
            "unevaluatedProperties": False,
        },
    }
    return observation, checks, {"enum": list(kind["results"])}
