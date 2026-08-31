class_name RewardTrial
extends RefCounted

const PlaytestRunProvenance = preload(
	"res://content/playtest_run_provenance.gd"
)
const REWARD_OPERATION := "game.generation.select-reward-v1"
const BUILD_OPERATION := "game.build.replace-reward-v1"
const REWARD_SELECTION_TYPE := {
	"package": "game.generation",
	"version": "1.0.0",
	"id": "RewardSelection",
}
const BUILD_DECISION_TYPE := {
	"package": "game.build",
	"version": "1.0.0",
	"id": "BuildDecision",
}
const BUILD_STATE_TYPE := {
	"package": "game.build",
	"version": "1.0.0",
	"id": "BuildState",
}

var _trial_id: String
var _revision: String
var _reward_frequency: int
var _reward: Dictionary
var _build: Dictionary
var _provenance: Dictionary


func admit_run_result(
	run_result: Dictionary,
	expected_reward_frequency: int,
	trial_id: String,
	revision: String,
) -> Dictionary:
	if trial_id.is_empty() or revision.is_empty():
		return _failure("missing_trial_binding")
	var artifacts: Dictionary = run_result.get("artifacts", {})
	var trace: Dictionary = artifacts.get("event-trace", {})
	if trace.get("artifact_kind") != "event-trace":
		return _failure("missing_event_trace")
	var provenance := PlaytestRunProvenance.project(run_result)
	if provenance.is_empty():
		return _failure("incomplete_artifact_provenance")

	var reward_event := _operation_event(trace, REWARD_OPERATION)
	var build_event := _operation_event(trace, BUILD_OPERATION)
	if reward_event.is_empty() or build_event.is_empty():
		return _failure("missing_reward_build_events")
	if reward_event.get("outcome", {}) != {"id": "selected", "kind": "success"}:
		return _failure("unexpected_reward_outcome")
	if build_event.get("outcome", {}) != {"id": "replaced", "kind": "success"}:
		return _failure("unexpected_build_outcome")

	var reward := _structured_fact(
		reward_event,
		"reward_result",
		REWARD_SELECTION_TYPE,
	)
	var build := _structured_fact(build_event, "build_result", BUILD_DECISION_TYPE)
	var build_state := _structured_fact(build_event, "build_state", BUILD_STATE_TYPE)
	if reward.is_empty() or build.is_empty() or build_state.is_empty():
		return _failure("missing_reward_build_values")
	var rare_weight = _integer_fact(reward_event, "rare_weight")
	var build_score = _integer_fact(build_event, "build_score")
	if rare_weight == null or int(rare_weight) != expected_reward_frequency:
		return _failure("rare_weight_mismatch")
	if build_score == null or int(build_score) != int(build.get("power_after", -1)):
		return _failure("build_score_mismatch")

	var reward_key := str(reward.get("selected", {}).get("key", ""))
	var selected_key := str(build.get("selected", {}).get("key", ""))
	var previous_key := str(build.get("previous", {}).get("key", ""))
	if reward_key.is_empty() or reward_key != selected_key or previous_key.is_empty():
		return _failure("selected_reward_mismatch")
	if reward.get("disposition") != "build" or build.get("disposition") != "build":
		return _failure("reward_disposition_mismatch")
	if build.get("kind") != "replaced":
		return _failure("build_replacement_missing")
	if (
		build_state.get("slot", {}).get("key") != selected_key
		or int(build_state.get("power", -1)) != int(build.get("power_after", -1))
	):
		return _failure("build_state_mismatch")

	_trial_id = trial_id
	_revision = revision
	_reward_frequency = expected_reward_frequency
	_reward = {
		"key": reward_key,
		"rarity": str(reward.get("rarity", "")),
	}
	_build = {
		"previous_item": previous_key,
		"equipped_item": selected_key,
		"power_before": int(build["power_before"]),
		"power_after": int(build["power_after"]),
	}
	_provenance = provenance
	return {"ok": true}


func trial_id() -> String:
	return _trial_id


func gameplay_values() -> Dictionary:
	return {
		"reward": _reward.duplicate(true),
		"build": _build.duplicate(true),
	}


func feedback_record() -> Dictionary:
	return {
		"id": _trial_id,
		"reward_frequency": _reward_frequency,
		"reward": _reward.duplicate(true),
		"build": _build.duplicate(true),
		"provenance": _provenance.duplicate(true),
	}


func snapshot() -> Dictionary:
	var value := feedback_record()
	value["revision"] = _revision
	return value


static func _operation_event(trace: Dictionary, operation: String) -> Dictionary:
	var found: Array = []
	for event in trace.get("events", []):
		if event.get("operation") == operation:
			found.append(event)
	return found[0] if found.size() == 1 else {}


static func _structured_fact(
	event: Dictionary,
	name: String,
	expected_type: Dictionary,
) -> Dictionary:
	var found: Array = []
	for fact in event.get("facts", []):
		if fact.get("name") == name:
			found.append(fact)
	if found.size() != 1 or found[0].get("kind") != "structured":
		return {}
	var typed: Dictionary = found[0].get("value", {})
	if typed.get("type", {}) != expected_type or not typed.get("value") is Dictionary:
		return {}
	return typed["value"]


static func _integer_fact(event: Dictionary, name: String):
	var found: Array = []
	for fact in event.get("facts", []):
		if fact.get("name") == name:
			found.append(fact)
	if found.size() != 1 or found[0].get("kind") != "integer":
		return null
	return found[0].get("integer")


static func _failure(detail: String) -> Dictionary:
	return {"ok": false, "kind": "invalid_reward_artifacts", "detail": detail}
