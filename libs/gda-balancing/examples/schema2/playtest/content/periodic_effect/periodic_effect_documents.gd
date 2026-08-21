class_name PeriodicEffectDocuments
extends RefCounted

const MAINTAINED_SOURCE_DIRECTORY := "res://../rpg-periodic-effect"
const MODEL_SOURCE_FILE := "model-source.json"
const EXPERIMENT_FILE := "same-time-experiment.json"
const POLICY_ENTRYPOINTS := {
	"dynamic": "effect.apply-live-periodic",
	"snapshot": "effect.apply-snapshot-periodic",
}

var _experiment: Dictionary = {}


func load_maintained() -> Dictionary:
	var source_directory := ProjectSettings.globalize_path(
		MAINTAINED_SOURCE_DIRECTORY
	).simplify_path()
	return self.load(
		source_directory.path_join(MODEL_SOURCE_FILE),
		source_directory.path_join(EXPERIMENT_FILE),
	)


func load(model_source_path: String, experiment_path: String) -> Dictionary:
	var model_result := _read_object(model_source_path)
	if not model_result.get("ok", false):
		return model_result
	var experiment_result := _read_object(experiment_path)
	if not experiment_result.get("ok", false):
		return experiment_result
	_experiment = experiment_result["value"].duplicate(true)
	var initial_health = _assignment_value(_experiment, "target_health")
	var damage_threshold = _assignment_value(_experiment, "magnitude_threshold")
	if initial_health == null or damage_threshold == null:
		return _failure("missing_periodic_assignments", experiment_path)
	var dynamic := experiment_for_policy("dynamic")
	var snapshot := experiment_for_policy("snapshot")
	if not dynamic.get("ok", false) or not snapshot.get("ok", false):
		return _failure("invalid_periodic_experiment", experiment_path)
	return {
		"damage_threshold": int(damage_threshold),
		"dynamic_experiment": dynamic["value"],
		"initial_health": int(initial_health),
		"ok": true,
		"model_source": model_result["value"].duplicate(true),
		"snapshot_experiment": snapshot["value"],
	}


func experiment_for_policy(policy: String) -> Dictionary:
	if _experiment.is_empty():
		return _failure("documents_not_loaded", "load documents first")
	if not POLICY_ENTRYPOINTS.has(policy):
		return _failure("unknown_policy", policy)
	var revised := _experiment.duplicate(true)
	var scenarios: Array = revised.get("scenarios", [])
	if scenarios.size() != 1 or not scenarios[0] is Dictionary:
		return _failure("invalid_scenarios", str(scenarios.size()))
	var event_plan: Array = scenarios[0].get("event_plan", [])
	if event_plan.size() != 2:
		return _failure("invalid_event_plan", str(event_plan.size()))
	if event_plan[0].get("root_event_ref") != "apply-periodic-effect":
		return _failure("missing_apply_event", policy)
	if event_plan[1].get("root_event_ref") != "ordinary-combat-damage":
		return _failure("missing_attack_event", policy)
	event_plan[0]["entrypoint"] = POLICY_ENTRYPOINTS[policy]
	# Both playtest trials use the same pulse-before-attack ordering. The policy
	# entrypoint is the only value that differs between them.
	event_plan[1]["priority"] = -1
	return {"ok": true, "value": revised}


func _read_object(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return _failure("document_not_found", path)
	var parsed = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		return _failure("invalid_document", path)
	return {"ok": true, "value": parsed}


func _assignment_value(experiment: Dictionary, name: String):
	var found: Array = []
	for scenario in experiment.get("scenarios", []):
		for assignment in scenario.get("assignments", []):
			if assignment.get("target", {}).get("name") == name:
				found.append(assignment.get("value"))
	if found.size() != 1 or not _is_integer_number(found[0]):
		return null
	return found[0]


func _is_integer_number(value) -> bool:
	return (
		value is int
		or (value is float and is_finite(value) and float(int(value)) == value)
	)


func _failure(kind: String, detail: String) -> Dictionary:
	return {"ok": false, "kind": kind, "detail": detail}
