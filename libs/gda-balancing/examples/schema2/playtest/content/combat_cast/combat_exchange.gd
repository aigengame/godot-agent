class_name CombatExchange
extends RefCounted

const PLAYER_ENTRYPOINT := "combat.player-attacks-enemy"
const ENEMY_ENTRYPOINT := "combat.enemy-attacks-player"
const EXPECTED_OUTCOME := {"id": "cast-resolved", "kind": "success"}
const TERMINAL_METRICS := {
	"enemy_health": "enemy_health_remaining",
	"enemy_mana": "enemy_resource_remaining",
	"player_health": "player_health_remaining",
	"player_mana": "player_resource_remaining",
}

var _exchange_id := ""
var _revision := ""
var _initial: Dictionary = {}
var _after_player: Dictionary = {}
var _terminal: Dictionary = {}
var _damage: Dictionary = {}
var _mana_cost: Dictionary = {}
var _provenance: Dictionary = {}


func admit_run_result(
	run_result: Dictionary,
	expected_initial: Dictionary,
	exchange_id: String,
	revision: String,
) -> Dictionary:
	if exchange_id.is_empty() or revision.is_empty():
		return _failure("missing_exchange_binding")
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

	var transitions: Array[Dictionary] = []
	for event in trace.get("events", []):
		if event.get("ordering_key", {}).get("phase") == "transition":
			transitions.append(event)
	if transitions.size() != 2:
		return _failure("unexpected_exchange_order")
	var player: Dictionary = transitions[0]
	var enemy: Dictionary = transitions[1]
	if (
		_entrypoint_id(player) != PLAYER_ENTRYPOINT
		or _entrypoint_id(enemy) != ENEMY_ENTRYPOINT
	):
		return _failure("unexpected_exchange_order")
	if player.get("outcome") != EXPECTED_OUTCOME or enemy.get("outcome") != EXPECTED_OUTCOME:
		return _failure("unexpected_cast_outcome")

	var player_before := _integer_state(player.get("state_before", []))
	var player_after := _integer_state(player.get("state_after", []))
	var enemy_before := _integer_state(enemy.get("state_before", []))
	var enemy_after := _integer_state(enemy.get("state_after", []))
	if (
		not _has_exact_combat_state(expected_initial)
		or player_before != expected_initial
		or not _has_exact_combat_state(player_after)
		or enemy_before != player_after
		or not _has_exact_combat_state(enemy_after)
	):
		return _failure("combat_state_discontinuity")
	var committed: Array = snapshots.get("snapshots", [])
	if committed.is_empty():
		return _failure("missing_terminal_snapshot")
	var terminal := _integer_state(committed[-1].get("values", []))
	if terminal != enemy_after:
		return _failure("terminal_snapshot_mismatch")

	var player_damage = _integer_fact(player, "player_damage_dealt")
	var enemy_damage = _integer_fact(enemy, "enemy_damage_dealt")
	var player_cost = _integer_fact(player, "player_action_cost")
	var enemy_cost = _integer_fact(enemy, "enemy_action_cost")
	if (
		player_damage == null
		or enemy_damage == null
		or player_cost == null
		or enemy_cost == null
	):
		return _failure("missing_exchange_facts")
	if (
		int(player_before["enemy_health"]) - int(player_after["enemy_health"])
		!= int(player_damage)
		or int(player_before["player_health"]) != int(player_after["player_health"])
		or int(player_before["player_mana"]) - int(player_after["player_mana"])
		!= int(player_cost)
		or int(player_before["enemy_mana"]) != int(player_after["enemy_mana"])
		or int(enemy_before["player_health"]) - int(enemy_after["player_health"])
		!= int(enemy_damage)
		or int(enemy_before["enemy_health"]) != int(enemy_after["enemy_health"])
		or int(enemy_before["enemy_mana"]) - int(enemy_after["enemy_mana"])
		!= int(enemy_cost)
		or int(enemy_before["player_mana"]) != int(enemy_after["player_mana"])
	):
		return _failure("exchange_state_mismatch")
	if not _metrics_match(metrics, terminal, int(player_damage), int(enemy_damage)):
		return _failure("metric_state_mismatch")

	_exchange_id = exchange_id
	_revision = revision
	_initial = expected_initial.duplicate(true)
	_after_player = player_after.duplicate(true)
	_terminal = terminal.duplicate(true)
	_damage = {"enemy": int(enemy_damage), "player": int(player_damage)}
	_mana_cost = {"enemy": int(enemy_cost), "player": int(player_cost)}
	_provenance = _artifact_provenance(artifacts, trace, snapshots)
	return {"ok": true}


func terminal_state() -> Dictionary:
	return _terminal.duplicate(true)


func gameplay_values() -> Dictionary:
	return {
		"after_player": _after_player.duplicate(true),
		"damage": _damage.duplicate(true),
		"initial": _initial.duplicate(true),
		"mana_cost": _mana_cost.duplicate(true),
		"terminal": _terminal.duplicate(true),
	}


func feedback_record() -> Dictionary:
	return {
		"damage": _damage.duplicate(true),
		"id": _exchange_id,
		"initial": _initial.duplicate(true),
		"mana_cost": _mana_cost.duplicate(true),
		"provenance": _provenance.duplicate(true),
		"terminal": _terminal.duplicate(true),
	}


func snapshot() -> Dictionary:
	var value := feedback_record()
	value["revision"] = _revision
	return value


func _metrics_match(
	metrics: Dictionary,
	terminal: Dictionary,
	player_damage: int,
	enemy_damage: int,
) -> bool:
	var samples: Dictionary = {}
	for sample in metrics.get("samples", []):
		samples[sample.get("metric", "")] = sample.get("value")
	for state_name in TERMINAL_METRICS:
		if samples.get(TERMINAL_METRICS[state_name]) != terminal[state_name]:
			return false
	return (
		samples.get("player_damage_dealt") == player_damage
		and samples.get("enemy_damage_dealt") == enemy_damage
	)


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


func _has_exact_combat_state(state: Dictionary) -> bool:
	if state.size() != TERMINAL_METRICS.size():
		return false
	for name in TERMINAL_METRICS:
		if not state.has(name):
			return false
	return true


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
	return (
		value is int
		or (value is float and is_finite(value) and float(int(value)) == value)
	)


func _artifact_provenance(
	artifacts: Dictionary,
	trace: Dictionary,
	snapshots: Dictionary,
) -> Dictionary:
	return {
		"evaluation_run_identity": str(
			artifacts.get("evaluation-run", {}).get("content_identity", "")
		),
		"event_trace_identity": str(trace.get("content_identity", "")),
		"experiment_identity": str(trace.get("experiment_identity", "")),
		"reproduction_receipt_identity": str(
			artifacts.get("reproduction-receipt", {}).get("content_identity", "")
		),
		"snapshot_series_identity": str(snapshots.get("content_identity", "")),
	}


func _failure(detail: String) -> Dictionary:
	return {"ok": false, "kind": "invalid_combat_artifacts", "detail": detail}
