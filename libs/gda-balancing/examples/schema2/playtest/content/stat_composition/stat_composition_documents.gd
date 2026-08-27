class_name StatCompositionDocuments
extends RefCounted

const MAINTAINED_SOURCE_DIRECTORY := "res://../rpg-stat-composition"
const MODEL_SOURCE_FILE := "model-source.json"
const EXPERIMENT_FILE := "experiment.json"
const MODULE_ID := "stats"
const TARGET_MAX_HEALTH := 120
const EDITABLE_NAMES: Array[String] = [
	"buff_enabled", "level", "weapon_damage_bonus"
]
const RULE_NAMES: Array[String] = [
	"base_damage", "buff_percent", "damage_per_level", "maximum_damage"
]

var _experiment: Dictionary = {}
var _model_id := ""
var _settings: Dictionary = {}
var _rules: Dictionary = {}


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
	var model_source: Dictionary = model_result["value"]
	var experiment: Dictionary = experiment_result["value"]
	_model_id = str(model_source.get("manifest", {}).get("id", ""))
	if _model_id.is_empty():
		return _failure("missing_model_id", model_source_path)

	var settings: Dictionary = {}
	for name in EDITABLE_NAMES:
		var symbol := _symbol(model_source, name)
		var assignment := _assignment(experiment, name)
		if symbol.is_empty() or assignment.is_empty():
			return _failure("missing_player_setting", name)
		var domain: Dictionary = symbol.get("domain", {})
		if (
			symbol.get("representation") != "Int"
			or symbol.get("domain_kind") != "closed-interval"
			or not domain.has("minimum")
			or not domain.has("maximum")
			or not _is_integer_number(assignment.get("value"))
		):
			return _failure("invalid_player_setting", name)
		settings[name] = {
			"minimum": int(domain["minimum"]),
			"maximum": int(domain["maximum"]),
			"value": int(assignment["value"]),
		}

	var rules: Dictionary = {}
	for name in RULE_NAMES:
		var assignment := _assignment(experiment, name)
		if assignment.is_empty() or not _is_integer_number(assignment.get("value")):
			return _failure("missing_visible_rule", name)
		rules[name] = int(assignment["value"])
	var health := _assignment(experiment, "target_health")
	if health.is_empty() or int(health.get("value", -1)) != TARGET_MAX_HEALTH:
		return _failure("invalid_target_health", experiment_path)

	_experiment = experiment.duplicate(true)
	_settings = settings.duplicate(true)
	_rules = rules.duplicate(true)
	return {
		"ok": true,
		"experiment": _experiment.duplicate(true),
		"model_source": model_source.duplicate(true),
		"rules": _rules.duplicate(true),
		"settings": _settings.duplicate(true),
		"target_max_health": TARGET_MAX_HEALTH,
	}


func experiment_for_attack(
	target_health: int,
	level: int,
	weapon_damage_bonus: int,
	buff_enabled: bool,
	action_index: int,
) -> Dictionary:
	if _experiment.is_empty():
		return _failure("documents_not_loaded", "load documents first")
	if target_health <= 0 or target_health > TARGET_MAX_HEALTH:
		return _failure("invalid_target_health", str(target_health))
	if action_index <= 0:
		return _failure("invalid_action_index", str(action_index))
	var selected := {
		"buff_enabled": 1 if buff_enabled else 0,
		"level": level,
		"weapon_damage_bonus": weapon_damage_bonus,
	}
	for name in selected:
		var contract: Dictionary = _settings[name]
		var value := int(selected[name])
		if value < int(contract["minimum"]) or value > int(contract["maximum"]):
			return _failure("setting_out_of_range", name)

	var revised := _experiment.duplicate(true)
	revised["id"] = "%s.playtest-attack-%d" % [_experiment["id"], action_index]
	_set_assignment(revised, "target_health", target_health)
	for name in selected:
		_set_assignment(revised, name, int(selected[name]))
	return {"ok": true, "value": revised}


func _symbol(model_source: Dictionary, name: String) -> Dictionary:
	for module in model_source.get("modules", []):
		if module.get("id") != MODULE_ID:
			continue
		for symbol in module.get("symbols", []):
			if symbol.get("symbol") == name:
				return symbol
	return {}


func _set_assignment(experiment: Dictionary, name: String, value: int) -> void:
	var assignment := _assignment(experiment, name)
	if not assignment.is_empty():
		assignment["value"] = value


func _assignment(experiment: Dictionary, name: String) -> Dictionary:
	for scenario in experiment.get("scenarios", []):
		for assignment in scenario.get("assignments", []):
			var target: Dictionary = assignment.get("target", {})
			if (
				target.get("model") == _model_id
				and target.get("module") == MODULE_ID
				and target.get("name") == name
			):
				return assignment
	return {}


func _read_object(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return _failure("document_not_found", path)
	var parsed = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		return _failure("invalid_document", path)
	return {"ok": true, "value": parsed}


func _is_integer_number(value) -> bool:
	return value is int or (value is float and is_finite(value) and float(int(value)) == value)


func _failure(kind: String, detail: String) -> Dictionary:
	return {"ok": false, "kind": kind, "detail": detail}
