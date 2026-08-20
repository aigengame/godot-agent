"""Authored one-action revisions shared by public RPG combat tracers."""

from copy import deepcopy
from typing import Any


_ACTION_SLICES = {
    "player-attacks-enemy": {
        "assignments": frozenset(
            {
                "enemy_defense",
                "enemy_health",
                "defeat_threshold",
                "player_accuracy",
                "player_action_cost",
                "player_base_damage",
                "player_critical_threshold",
                "player_health",
                "player_mana",
            }
        ),
        "metrics": frozenset(
            {
                "enemy_health_remaining",
                "player_damage_dealt",
                "player_resource_remaining",
            }
        ),
        "damage_metric": "player_damage_dealt",
    },
    "enemy-attacks-player": {
        "assignments": frozenset(
            {
                "defeat_threshold",
                "enemy_accuracy",
                "enemy_action_cost",
                "enemy_base_damage",
                "enemy_critical_threshold",
                "enemy_health",
                "enemy_mana",
                "player_defense",
                "player_health",
            }
        ),
        "metrics": frozenset(
            {
                "enemy_damage_dealt",
                "enemy_resource_remaining",
                "player_health_remaining",
            }
        ),
        "damage_metric": "enemy_damage_dealt",
    },
}


def combat_action_assignment_names(root_event_ref: str) -> frozenset[str]:
    """Return the complete assignment surface for one maintained action."""
    return _ACTION_SLICES[root_event_ref]["assignments"]


def one_action_experiment(
    baseline: dict[str, Any],
    identifier: str,
    *,
    root_event_ref: str,
    include_damage_metric: bool = True,
) -> dict[str, Any]:
    """Project one complete Experiment revision from the maintained duel."""
    action = _ACTION_SLICES[root_event_ref]
    revision = deepcopy(baseline)
    revision["id"] = identifier
    scenario = revision["scenarios"][0]
    scenario["event_plan"] = [
        event
        for event in scenario["event_plan"]
        if event["root_event_ref"] == root_event_ref
    ]
    scenario["assignments"] = [
        row
        for row in scenario["assignments"]
        if row["target"]["name"] in action["assignments"]
    ]
    metric_ids = action["metrics"]
    if not include_damage_metric:
        metric_ids = metric_ids - {action["damage_metric"]}
    revision["metrics"] = [
        metric for metric in revision["metrics"] if metric["id"] in metric_ids
    ]
    return revision
