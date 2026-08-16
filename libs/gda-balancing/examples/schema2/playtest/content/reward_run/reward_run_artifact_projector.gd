class_name RewardRunArtifactProjector
extends RefCounted

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


func project(run_result: Dictionary, expected_rare_weight: int) -> Dictionary:
	var artifacts: Dictionary = run_result.get("artifacts", {})
	var trace: Dictionary = artifacts.get("event-trace", {})
	if trace.get("artifact_kind") != "event-trace":
		return _failure("missing_event_trace")

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
	if rare_weight == null or int(rare_weight) != expected_rare_weight:
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

	return {
		"ok": true,
		"value": {
			"rare_weight": expected_rare_weight,
			"reward": {
				"key": reward_key,
				"rarity": str(reward.get("rarity", "")),
			},
			"build": {
				"previous_item": previous_key,
				"equipped_item": selected_key,
				"power_before": int(build["power_before"]),
				"power_after": int(build["power_after"]),
			},
			"provenance": _provenance(artifacts, trace),
		},
	}


func _operation_event(trace: Dictionary, operation: String) -> Dictionary:
	var found: Array = []
	for event in trace.get("events", []):
		if event.get("operation") == operation:
			found.append(event)
	return found[0] if found.size() == 1 else {}


func _structured_fact(
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


func _integer_fact(event: Dictionary, name: String):
	var found: Array = []
	for fact in event.get("facts", []):
		if fact.get("name") == name:
			found.append(fact)
	if found.size() != 1 or found[0].get("kind") != "integer":
		return null
	return found[0].get("integer")


func _provenance(artifacts: Dictionary, trace: Dictionary) -> Dictionary:
	return {
		"experiment_identity": str(trace.get("experiment_identity", "")),
		"event_trace_identity": str(trace.get("content_identity", "")),
		"evaluation_run_identity": str(
			artifacts.get("evaluation-run", {}).get("content_identity", "")
		),
		"reproduction_receipt_identity": str(
			artifacts.get("reproduction-receipt", {}).get("content_identity", "")
		),
	}


func _failure(detail: String) -> Dictionary:
	return {"ok": false, "kind": "invalid_reward_artifacts", "detail": detail}
