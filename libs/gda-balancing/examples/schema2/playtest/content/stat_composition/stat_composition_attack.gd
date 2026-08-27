class_name StatCompositionAttack
extends RefCounted

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const METRIC_IDS: Array[String] = [
	"attack_damage",
	"base_damage",
	"build_damage",
	"damage_dealt",
	"effect_damage",
	"pre_buff_damage",
	"progression_damage",
	"target_health",
]

var _attack_index := 0
var _capped := false
var _metrics: Dictionary = {}
var _provenance: Dictionary = {}
var _revision := ""
var _settings: Dictionary = {}


func admit_run_result(
	run_result: Dictionary,
	expected_health: int,
	settings: Dictionary,
	maximum_damage: int,
	attack_index: int,
	revision: String,
) -> Dictionary:
	if expected_health <= 0 or attack_index <= 0 or revision.is_empty():
		return _failure("missing_attack_binding")
	var artifacts: Dictionary = run_result.get("artifacts", {})
	var trace: Dictionary = artifacts.get("event-trace", {})
	var snapshots: Dictionary = artifacts.get("snapshot-series", {})
	var dataset: Dictionary = artifacts.get("metric-dataset", {})
	if trace.get("artifact_kind") != "event-trace":
		return _failure("missing_event_trace")
	if snapshots.get("artifact_kind") != "snapshot-series":
		return _failure("missing_snapshot_series")
	if dataset.get("artifact_kind") != "metric-dataset":
		return _failure("missing_metric_dataset")
	var provenance := GdaExecutionClient.project_run_provenance(run_result)
	if provenance.is_empty():
		return _failure("incomplete_artifact_provenance")

	var transitions: Array[Dictionary] = []
	for event in trace.get("events", []):
		if event.get("ordering_key", {}).get("phase") == "transition":
			transitions.append(event)
	if transitions.size() != 1:
		return _failure("unexpected_attack_order")
	var event := transitions[0]
	if (
		event.get("operation") != "game.combat.damage-v1"
		or event.get("outcome") != {"id": "applied", "kind": "success"}
	):
		return _failure("unexpected_attack_outcome")
	var before := _integer_state(event.get("state_before", []))
	var after := _integer_state(event.get("state_after", []))
	if before != {"target_health": expected_health} or not after.has("target_health"):
		return _failure("target_health_discontinuity")

	var facts := _integer_facts(event.get("facts", []))
	var metrics := _integer_metrics(dataset.get("samples", []))
	if metrics.size() != METRIC_IDS.size():
		return _failure("missing_attack_metrics")
	for metric_id in METRIC_IDS:
		if not metrics.has(metric_id) or facts.get(metric_id) != metrics[metric_id]:
			return _failure("metric_fact_mismatch")
	if (
		int(after["target_health"]) != int(metrics["target_health"])
		or expected_health - int(after["target_health"]) != int(metrics["damage_dealt"])
	):
		return _failure("damage_state_mismatch")
	for setting_name in ["buff_enabled", "level", "weapon_damage_bonus"]:
		if facts.get(setting_name) != settings.get(setting_name):
			return _failure("setting_fact_mismatch")
	if facts.get("maximum_damage") != maximum_damage:
		return _failure("maximum_damage_mismatch")
	var committed: Array = snapshots.get("snapshots", [])
	if committed.is_empty() or _integer_state(committed[-1].get("values", [])) != after:
		return _failure("terminal_snapshot_mismatch")

	_attack_index = attack_index
	_capped = int(metrics["attack_damage"]) == maximum_damage
	_metrics = metrics.duplicate(true)
	_provenance = provenance
	_revision = revision
	_settings = settings.duplicate(true)
	return {"ok": true}


func gameplay_values() -> Dictionary:
	return {
		"attack_index": _attack_index,
		"capped": _capped,
		"metrics": _metrics.duplicate(true),
		"settings": _settings.duplicate(true),
	}


func feedback_record() -> Dictionary:
	return {
		"attack_index": _attack_index,
		"capped": _capped,
		"completion_state": (
			"dummy-defeated" if int(_metrics.get("target_health", -1)) == 0 else "active"
		),
		"metrics": _metrics.duplicate(true),
		"provenance": _provenance.duplicate(true),
		"revision": _revision,
		"settings": _settings.duplicate(true),
	}


func _integer_state(rows: Array) -> Dictionary:
	var state: Dictionary = {}
	for row in rows:
		if row.get("name") is String and _is_integer_number(row.get("value")):
			state[row["name"]] = int(row["value"])
	return state


func _integer_facts(rows: Array) -> Dictionary:
	var facts: Dictionary = {}
	for row in rows:
		if row.get("name") is String and _is_integer_number(row.get("integer")):
			facts[row["name"]] = int(row["integer"])
	return facts


func _integer_metrics(rows: Array) -> Dictionary:
	var metrics: Dictionary = {}
	for row in rows:
		var metric := str(row.get("metric", ""))
		if metric in METRIC_IDS and _is_integer_number(row.get("value")):
			metrics[metric] = int(row["value"])
	return metrics


func _is_integer_number(value) -> bool:
	return value is int or (value is float and is_finite(value) and float(int(value)) == value)


func _failure(kind: String) -> Dictionary:
	return {"ok": false, "kind": kind}
