class_name CombatCastDocuments
extends RefCounted

const MAINTAINED_SOURCE_DIRECTORY := "res://../rpg-combat-cast"
const MODEL_SOURCE_FILE := "model-source.json"
const EXPERIMENT_FILE := "experiment.json"
const COMBAT_STATE_NAMES: Array[String] = [
	"enemy_health",
	"enemy_mana",
	"player_health",
	"player_mana",
]

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
	var experiment: Dictionary = experiment_result["value"]
	var initial := _combat_state(experiment)
	if not initial.get("ok", false):
		return initial
	_experiment = experiment.duplicate(true)
	return {
		"ok": true,
		"model_source": model_result["value"].duplicate(true),
		"experiment": _experiment.duplicate(true),
		"combat_state": initial["value"],
	}


func experiment_from_terminal(terminal: Dictionary) -> Dictionary:
	if _experiment.is_empty():
		return _failure("documents_not_loaded", "load documents first")
	for name in COMBAT_STATE_NAMES:
		if not terminal.get(name) is int:
			return _failure("invalid_terminal_state", name)
	var revised := _experiment.duplicate(true)
	for name in COMBAT_STATE_NAMES:
		var assignment := _assignment(revised, name)
		if assignment.is_empty():
			return _failure("missing_combat_assignment", name)
		assignment["value"] = terminal[name]
	return {"ok": true, "value": revised}


func _combat_state(experiment: Dictionary) -> Dictionary:
	var value: Dictionary = {}
	for name in COMBAT_STATE_NAMES:
		var assignment := _assignment(experiment, name)
		if assignment.is_empty() or not _is_integer_number(assignment.get("value")):
			return _failure("missing_combat_assignment", name)
		value[name] = int(assignment["value"])
	return {"ok": true, "value": value}


func _assignment(experiment: Dictionary, name: String) -> Dictionary:
	for scenario in experiment.get("scenarios", []):
		for assignment in scenario.get("assignments", []):
			if assignment.get("target", {}).get("name") == name:
				return assignment
	return {}


func _is_integer_number(value) -> bool:
	return (
		value is int
		or (value is float and is_finite(value) and float(int(value)) == value)
	)


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
