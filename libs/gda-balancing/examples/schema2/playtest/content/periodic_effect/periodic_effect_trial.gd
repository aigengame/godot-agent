class_name PeriodicEffectTrial
extends RefCounted

const POLICY_OPERATIONS := {
	"reactive": {
		"apply": "game.effect.apply-live-periodic-v1",
		"tick": "game.effect.tick-live-periodic-v1",
	},
	"locked": {
		"apply": "game.effect.apply-snapshot-periodic-v1",
		"tick": "game.effect.tick-snapshot-periodic-v1",
	},
}
const EXPECTED_TIMELINE_PHASES: Array[String] = [
	"apply", "pulse", "attack", "pulse", "expire"
]

var _trial_id := ""
var _revision := ""
var _policy := ""
var _timeline: Array[Dictionary] = []
var _provenance: Dictionary = {}


func admit_run_result(
	run_result: Dictionary,
	policy: String,
	trial_id: String,
	revision: String,
) -> Dictionary:
	if not POLICY_OPERATIONS.has(policy) or trial_id.is_empty() or revision.is_empty():
		return _failure("missing_trial_binding")
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
	if transitions.size() != EXPECTED_TIMELINE_PHASES.size():
		return _failure("unexpected_lifecycle_length")
	var operations: Dictionary = POLICY_OPERATIONS[policy]
	var expected_operations: Array[String] = [
		operations["apply"],
		operations["tick"],
		"game.combat.cast-v1",
		operations["tick"],
		"game.effect.expire-periodic-v1",
	]
	var expected_times: Array[int] = [0, 1, 1, 2, 3]
	for index in range(transitions.size()):
		var event: Dictionary = transitions[index]
		if event.get("operation") != expected_operations[index]:
			return _failure("unexpected_lifecycle_order")
		if int(event.get("ordering_key", {}).get("logical_time", -1)) != expected_times[index]:
			return _failure("unexpected_lifecycle_time")
		if index > 0 and event.get("state_before") != transitions[index - 1].get("state_after"):
			return _failure("lifecycle_state_discontinuity")

	var committed: Array = snapshots.get("snapshots", [])
	if committed.is_empty():
		return _failure("missing_terminal_snapshot")
	var terminal := _integer_state(committed[-1].get("values", []))
	var final_state := _integer_state(transitions[-1].get("state_after", []))
	if terminal != final_state:
		return _failure("terminal_snapshot_mismatch")
	var timeline: Array[Dictionary] = []
	for index in range(transitions.size()):
		var event: Dictionary = transitions[index]
		var before := _integer_state(event.get("state_before", []))
		var after := _integer_state(event.get("state_after", []))
		if before.is_empty() or after.is_empty():
			return _failure("invalid_lifecycle_state")
		timeline.append(
			{
				"damage": int(before.get("target_health", 0)) - int(after.get("target_health", 0)),
				"effect_active": int(after.get("effect_active", 0)) == 1,
				"health": int(after.get("target_health", 0)),
				"phase": EXPECTED_TIMELINE_PHASES[index],
			}
		)
	var pulse_damage := _pulse_damage_evidence(transitions, policy)
	var attack_damage = _integer_fact(transitions[2], "combat_damage")
	if (
		pulse_damage.size() != 2
		or attack_damage == null
		or int(timeline[0]["damage"]) != 0
		or int(timeline[1]["damage"]) != int(pulse_damage[0])
		or int(timeline[1]["damage"]) <= 0
		or int(timeline[2]["damage"]) != int(attack_damage)
		or int(timeline[3]["damage"]) != int(pulse_damage[1])
		or int(timeline[3]["damage"]) < 0
		or int(timeline[4]["damage"]) != 0
		or bool(timeline[4]["effect_active"])
	):
		return _failure("invalid_lifecycle_relationships")
	if not _metrics_match(metrics, terminal, int(attack_damage)):
		return _failure("metric_state_mismatch")

	_trial_id = trial_id
	_revision = revision
	_policy = policy
	_timeline = timeline
	_provenance = _artifact_provenance(artifacts, trace, snapshots)
	return {"ok": true}


func gameplay_values() -> Dictionary:
	return {"timeline": _timeline.duplicate(true), "trial_kind": _policy}


func feedback_record() -> Dictionary:
	return {
		"id": _trial_id,
		"provenance": _provenance.duplicate(true),
		"timeline": _timeline.duplicate(true),
		"trial_kind": _policy,
	}


func snapshot() -> Dictionary:
	var value := feedback_record()
	value["revision"] = _revision
	return value


func _metrics_match(
	metrics: Dictionary,
	terminal: Dictionary,
	attack_damage: int,
) -> bool:
	var samples: Dictionary = {}
	for sample in metrics.get("samples", []):
		samples[sample.get("metric", "")] = sample.get("value")
	for required in [
		"target_health_remaining",
		"effect_active_terminal",
		"effect_instance_id_terminal",
		"combat_damage",
	]:
		if not samples.has(required):
			return false
	return (
		terminal.has("target_health")
		and terminal.has("effect_active")
		and terminal.has("effect_instance_id")
		and int(samples["target_health_remaining"]) == int(terminal["target_health"])
		and int(samples["effect_active_terminal"]) == int(terminal["effect_active"])
		and int(samples["effect_instance_id_terminal"])
		== int(terminal["effect_instance_id"])
		and int(samples["combat_damage"]) == attack_damage
	)


func _pulse_damage_evidence(
	transitions: Array[Dictionary],
	policy: String,
) -> Array:
	var operations: Dictionary = POLICY_OPERATIONS[policy]
	var damage: Array[int] = []
	if policy == "reactive":
		for index in [1, 3]:
			var result = _formula_result(transitions[index], operations["tick"])
			if result == null:
				return []
			damage.append(int(result))
		return damage

	var apply: Dictionary = transitions[0]
	var captured = _formula_result(apply, operations["apply"])
	if captured == null:
		return []
	var scheduled_damage: Dictionary = {}
	for schedule in apply.get("schedules", []):
		if schedule.get("operation", {}).get("id") != operations["tick"]:
			continue
		var event_id := str(schedule.get("event_id", ""))
		var magnitude = _named_integer(schedule.get("arguments", []), "magnitude")
		if (
			event_id.is_empty()
			or scheduled_damage.has(event_id)
			or magnitude == null
			or int(magnitude) != int(captured)
		):
			return []
		scheduled_damage[event_id] = int(magnitude)
	if scheduled_damage.size() != 2:
		return []
	for index in [1, 3]:
		var event_id := str(transitions[index].get("event_id", ""))
		if not scheduled_damage.has(event_id):
			return []
		damage.append(int(scheduled_damage[event_id]))
	return damage


func _formula_result(event: Dictionary, operation_id: String):
	var matches: Array = []
	for evaluation in event.get("formula_evaluations", []):
		if (
			evaluation.get("operation", {}).get("id") == operation_id
			and evaluation.get("formula", {}).get("id") == "periodic-magnitude"
			and evaluation.get("slot") == "magnitude-policy"
			and _is_integer_number(evaluation.get("result"))
		):
			matches.append(evaluation["result"])
	return int(matches[0]) if matches.size() == 1 else null


func _integer_fact(event: Dictionary, name: String):
	var found: Array = []
	for fact in event.get("facts", []):
		if fact.get("name") == name:
			found.append(fact)
	if found.size() != 1 or found[0].get("kind") != "integer":
		return null
	var value = found[0].get("integer")
	return int(value) if _is_integer_number(value) else null


func _named_integer(rows: Array, name: String):
	var found: Array = []
	for row in rows:
		if row.get("name") == name and _is_integer_number(row.get("value")):
			found.append(row["value"])
	return int(found[0]) if found.size() == 1 else null


func _integer_state(rows: Array) -> Dictionary:
	var state: Dictionary = {}
	for row in rows:
		if not row is Dictionary or not _is_integer_number(row.get("value")):
			return {}
		state[str(row.get("name", ""))] = int(row["value"])
	return state


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
	return {"ok": false, "kind": "invalid_periodic_artifacts", "detail": detail}
