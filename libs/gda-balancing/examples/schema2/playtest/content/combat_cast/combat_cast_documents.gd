class_name CombatCastDocuments
extends RefCounted

const MAINTAINED_SOURCE_DIRECTORY := "res://../rpg-combat-cast"
const MODEL_SOURCE_FILE := "model-source.json"
const EXPERIMENT_FILE := "experiment.json"
const COMBAT_STATE_NAMES: Array[String] = [
	"enemy_health", "enemy_mana", "player_health", "player_mana"
]
const ACTION_CONTRACTS := {
	"player": {
		"assignments": [
			"defeat_threshold", "enemy_defense", "enemy_health", "player_accuracy",
			"player_action_cost", "player_base_damage", "player_critical_threshold",
			"player_health", "player_mana",
		],
		"metrics": ["enemy_health_remaining", "player_resource_remaining"],
		"root_event_ref": "player-attacks-enemy",
	},
	"enemy": {
		"assignments": [
			"defeat_threshold", "enemy_accuracy", "enemy_action_cost",
			"enemy_base_damage", "enemy_critical_threshold", "enemy_health",
			"enemy_mana", "player_defense", "player_health",
		],
		"metrics": ["enemy_resource_remaining", "player_health_remaining"],
		"root_event_ref": "enemy-attacks-player",
	},
}
const SPELL_STYLES := {
	"efficient": {"player_action_cost": 6, "player_base_damage": 34},
	"balanced": {"player_action_cost": 9, "player_base_damage": 45},
	"powerful": {"player_action_cost": 14, "player_base_damage": 65},
}
const RIVAL_STRENGTHS := {
	"normal": {"enemy_base_damage": 20},
	"strong": {"enemy_base_damage": 32},
}

var _experiment: Dictionary = {}
var _initial_state: Dictionary = {}


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
	var experiment: Dictionary = experiment_result["value"]
	var initial := _combat_state(experiment)
	if not initial.get("ok", false):
		return initial
	var threshold := _assignment(experiment, "defeat_threshold")
	if threshold.is_empty() or not _is_integer_number(threshold.get("value")):
		return _failure("missing_combat_assignment", "defeat_threshold")
	_experiment = experiment.duplicate(true)
	_initial_state = initial["value"].duplicate(true)
	return {
		"ok": true,
		"model_source": model_result["value"].duplicate(true),
		"experiment": _experiment.duplicate(true),
		"combat_state": _initial_state.duplicate(true),
		"defeat_threshold": int(threshold["value"]),
	}


func initial_state_for_options(spell_style: String, rival_strength: String) -> Dictionary:
	if _experiment.is_empty():
		return _failure("documents_not_loaded", "load documents first")
	if not SPELL_STYLES.has(spell_style):
		return _failure("unknown_spell_style", spell_style)
	if not RIVAL_STRENGTHS.has(rival_strength):
		return _failure("unknown_rival_strength", rival_strength)
	return {"ok": true, "value": _initial_state.duplicate(true)}


func experiment_for_action(
	combat_state: Dictionary,
	actor: String,
	spell_style: String,
	rival_strength: String,
	action_index: int,
) -> Dictionary:
	if _experiment.is_empty():
		return _failure("documents_not_loaded", "load documents first")
	if not ACTION_CONTRACTS.has(actor):
		return _failure("unknown_combat_actor", actor)
	if not SPELL_STYLES.has(spell_style):
		return _failure("unknown_spell_style", spell_style)
	if not RIVAL_STRENGTHS.has(rival_strength):
		return _failure("unknown_rival_strength", rival_strength)
	for name in COMBAT_STATE_NAMES:
		if not combat_state.get(name) is int:
			return _failure("invalid_combat_state", name)

	var contract: Dictionary = ACTION_CONTRACTS[actor]
	var revised := _experiment.duplicate(true)
	revised["id"] = "%s.playtest-action-%d" % [_experiment["id"], action_index]
	var scenario: Dictionary = revised["scenarios"][0]
	scenario["event_plan"] = scenario["event_plan"].filter(
		func(event: Dictionary) -> bool:
			return event.get("root_event_ref") == contract["root_event_ref"]
	)
	scenario["assignments"] = scenario["assignments"].filter(
		func(assignment: Dictionary) -> bool:
			return assignment.get("target", {}).get("name") in contract["assignments"]
	)
	for assignment in scenario["assignments"]:
		var name := str(assignment.get("target", {}).get("name", ""))
		if combat_state.has(name):
			assignment["value"] = combat_state[name]
	for name in SPELL_STYLES[spell_style]:
		_set_assignment(revised, name, SPELL_STYLES[spell_style][name])
	for name in RIVAL_STRENGTHS[rival_strength]:
		_set_assignment(revised, name, RIVAL_STRENGTHS[rival_strength][name])
	revised["metrics"] = revised["metrics"].filter(
		func(metric: Dictionary) -> bool:
			return metric.get("id") in contract["metrics"]
	)
	return {"ok": true, "value": revised}


func _combat_state(experiment: Dictionary) -> Dictionary:
	var value: Dictionary = {}
	for name in COMBAT_STATE_NAMES:
		var assignment := _assignment(experiment, name)
		if assignment.is_empty() or not _is_integer_number(assignment.get("value")):
			return _failure("missing_combat_assignment", name)
		value[name] = int(assignment["value"])
	return {"ok": true, "value": value}


func _set_assignment(experiment: Dictionary, name: String, value: int) -> void:
	var assignment := _assignment(experiment, name)
	if not assignment.is_empty():
		assignment["value"] = value


func _assignment(experiment: Dictionary, name: String) -> Dictionary:
	for scenario in experiment.get("scenarios", []):
		for assignment in scenario.get("assignments", []):
			if assignment.get("target", {}).get("name") == name:
				return assignment
	return {}


func _is_integer_number(value) -> bool:
	return value is int or (value is float and is_finite(value) and float(int(value)) == value)


func _read_object(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return _failure("document_not_found", path)
	var parsed = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		return _failure("invalid_document", path)
	return {"ok": true, "value": parsed}


func _failure(kind: String, detail: String) -> Dictionary:
	return {"ok": false, "kind": kind, "detail": detail}
