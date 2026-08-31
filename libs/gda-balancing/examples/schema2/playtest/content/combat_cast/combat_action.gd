class_name CombatAction
extends RefCounted

const PlaytestRunProvenance = preload(
	"res://content/playtest_run_provenance.gd"
)
const ACTOR_CONTRACTS := {
	"player": {
		"cost_fact": "player_action_cost",
		"damage_fact": "player_damage_dealt",
		"entrypoint": "combat.player-attacks-enemy",
		"resource": "player_mana",
		"resource_metric": "player_resource_remaining",
		"state": ["enemy_health", "player_health", "player_mana"],
		"target": "enemy_health",
		"target_metric": "enemy_health_remaining",
	},
	"enemy": {
		"cost_fact": "enemy_action_cost",
		"damage_fact": "enemy_damage_dealt",
		"entrypoint": "combat.enemy-attacks-player",
		"resource": "enemy_mana",
		"resource_metric": "enemy_resource_remaining",
		"state": ["enemy_health", "enemy_mana", "player_health"],
		"target": "player_health",
		"target_metric": "player_health_remaining",
	},
}
const COMBAT_STATE_NAMES: Array[String] = [
	"enemy_health", "enemy_mana", "player_health", "player_mana"
]
const ADMITTED_OUTCOMES := {
	"cast-resolved": {"id": "cast-resolved", "kind": "success"},
	"target-defeated": {"id": "target-defeated", "kind": "success"},
}

var _actor := ""
var _damage := 0
var _initial: Dictionary = {}
var _mana_cost := 0
var _outcome := ""
var _provenance: Dictionary = {}
var _revision := ""
var _terminal: Dictionary = {}


func admit_run_result(
	run_result: Dictionary,
	expected_initial: Dictionary,
	actor: String,
	revision: String,
	defeat_threshold: int,
) -> Dictionary:
	if not ACTOR_CONTRACTS.has(actor) or revision.is_empty():
		return _failure("missing_action_binding")
	if not _has_exact_combat_state(expected_initial):
		return _failure("invalid_initial_state")
	var artifacts: Dictionary = run_result.get("artifacts", {})
	var trace: Dictionary = artifacts.get("event-trace", {})
	var snapshots: Dictionary = artifacts.get("snapshot-series", {})
	var metrics: Dictionary = artifacts.get("metric-dataset", {})
	if trace.get("artifact_kind") != "event-trace":
		return _failure("missing_event_trace")
	if snapshots.get("artifact_kind") != "snapshot-series":
		return _failure("missing_snapshot_series")
	if metrics.get("artifact_kind") != "metric-dataset":
		return _failure("missing_metric_dataset")
	var provenance := PlaytestRunProvenance.project(run_result)
	if provenance.is_empty():
		return _failure("incomplete_artifact_provenance")

	var transitions: Array[Dictionary] = []
	for event in trace.get("events", []):
		if event.get("ordering_key", {}).get("phase") == "transition":
			transitions.append(event)
	if transitions.size() != 1:
		return _failure("unexpected_action_order")
	var event := transitions[0]
	var contract: Dictionary = ACTOR_CONTRACTS[actor]
	if _entrypoint_id(event) != contract["entrypoint"]:
		return _failure("unexpected_action_order")
	var outcome: Dictionary = event.get("outcome", {})
	var outcome_id := str(outcome.get("id", ""))
	if not ADMITTED_OUTCOMES.has(outcome_id) or outcome != ADMITTED_OUTCOMES[outcome_id]:
		return _failure("unexpected_cast_outcome")

	var before := _integer_state(event.get("state_before", []))
	var after := _integer_state(event.get("state_after", []))
	var expected_before := _selected_state(expected_initial, contract["state"])
	if before != expected_before or after.size() != expected_before.size():
		return _failure("combat_state_discontinuity")
	for name in expected_before:
		if not after.has(name):
			return _failure("combat_state_discontinuity")
	var committed: Array = snapshots.get("snapshots", [])
	if committed.is_empty():
		return _failure("missing_terminal_snapshot")
	var committed_state := _integer_state(committed[-1].get("values", []))
	if committed_state != after:
		return _failure("terminal_snapshot_mismatch")

	var damage = _integer_fact(event, contract["damage_fact"])
	var cost = _integer_fact(event, contract["cost_fact"])
	if damage == null or cost == null:
		return _failure("missing_action_facts")
	var target: String = contract["target"]
	var resource: String = contract["resource"]
	if (
		int(before[target]) - int(after[target]) != int(damage)
		or int(before[resource]) - int(after[resource]) != int(cost)
	):
		return _failure("action_state_mismatch")
	for name in before:
		if name != target and name != resource and before[name] != after[name]:
			return _failure("action_state_mismatch")
	if (int(after[target]) <= defeat_threshold) != (outcome_id == "target-defeated"):
		return _failure("outcome_state_mismatch")
	if not _metrics_match(metrics, after, contract):
		return _failure("metric_state_mismatch")

	var terminal := expected_initial.duplicate(true)
	for name in after:
		terminal[name] = after[name]
	_actor = actor
	_damage = int(damage)
	_initial = expected_initial.duplicate(true)
	_mana_cost = int(cost)
	_outcome = outcome_id
	_provenance = provenance
	_revision = revision
	_terminal = terminal
	return {"ok": true}


func terminal_state() -> Dictionary:
	return _terminal.duplicate(true)


func target_defeated() -> bool:
	return _outcome == "target-defeated"


func gameplay_values() -> Dictionary:
	return {
		"actor": _actor,
		"damage": _damage,
		"mana_cost": _mana_cost,
		"target_defeated": target_defeated(),
		"terminal": _terminal.duplicate(true),
	}


func feedback_record() -> Dictionary:
	return {
		"actor": _actor,
		"damage": _damage,
		"initial": _initial.duplicate(true),
		"mana_cost": _mana_cost,
		"outcome": _outcome,
		"provenance": _provenance.duplicate(true),
		"revision": _revision,
		"terminal": _terminal.duplicate(true),
	}


func _metrics_match(metrics: Dictionary, after: Dictionary, contract: Dictionary) -> bool:
	var samples: Dictionary = {}
	for sample in metrics.get("samples", []):
		samples[sample.get("metric", "")] = sample.get("value")
	return (
		samples.size() == 2
		and samples.get(contract["target_metric"]) == after[contract["target"]]
		and samples.get(contract["resource_metric"]) == after[contract["resource"]]
	)


func _selected_state(state: Dictionary, names: Array) -> Dictionary:
	var selected: Dictionary = {}
	for name in names:
		if not state.get(name) is int:
			return {}
		selected[name] = state[name]
	return selected


func _has_exact_combat_state(state: Dictionary) -> bool:
	if state.size() != COMBAT_STATE_NAMES.size():
		return false
	for name in COMBAT_STATE_NAMES:
		if not state.get(name) is int:
			return false
	return true


func _entrypoint_id(event: Dictionary) -> String:
	var entrypoint = event.get("entrypoint", {})
	return str(entrypoint.get("id", "")) if entrypoint is Dictionary else ""


func _integer_state(rows: Array) -> Dictionary:
	var state: Dictionary = {}
	for row in rows:
		if not row is Dictionary or not _is_integer_number(row.get("value")):
			return {}
		state[str(row.get("name", ""))] = int(row["value"])
	return state


func _integer_fact(event: Dictionary, name: String):
	var found: Array = []
	for fact in event.get("facts", []):
		if fact.get("name") == name:
			found.append(fact)
	if found.size() != 1 or found[0].get("kind") != "integer":
		return null
	var value = found[0].get("integer")
	return int(value) if _is_integer_number(value) else null


func _is_integer_number(value) -> bool:
	return value is int or (value is float and is_finite(value) and float(int(value)) == value)


func _failure(detail: String) -> Dictionary:
	return {"ok": false, "kind": "invalid_combat_artifacts", "detail": detail}
