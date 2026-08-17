class_name RewardRunDocuments
extends RefCounted

const MODULE_ID := "reward-build"
const PARAMETER_NAME := "rare_weight"
const MAINTAINED_SOURCE_DIRECTORY := "res://../roguelike-reward-build"
const MODEL_SOURCE_FILE := "model-source.json"
const EXPERIMENT_FILE := "experiment.json"

var _experiment: Dictionary = {}
var _model_id := ""
var _minimum := 0
var _maximum := 0


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
	var model_id := str(model_source.get("manifest", {}).get("id", ""))
	var parameter := _rare_weight_parameter(model_source)
	if parameter.is_empty():
		return _failure("missing_rare_weight", model_source_path)
	var domain: Dictionary = parameter.get("domain", {})
	if (
		parameter.get("representation") != "Int"
		or parameter.get("domain_kind") != "closed-interval"
		or not domain.has("minimum")
		or not domain.has("maximum")
	):
		return _failure("invalid_rare_weight_domain", model_source_path)

	var assignment := _rare_weight_assignment(experiment, model_id)
	if assignment.is_empty():
		return _failure("missing_rare_weight_assignment", experiment_path)
	_minimum = int(domain["minimum"])
	_maximum = int(domain["maximum"])
	_model_id = model_id
	var value := int(assignment["value"])
	if value < _minimum or value > _maximum:
		return _failure("rare_weight_out_of_range", str(value))
	_experiment = experiment.duplicate(true)
	return {
		"ok": true,
		"model_source": model_source.duplicate(true),
		"experiment": _experiment.duplicate(true),
		"reward_frequency": {
			"minimum": _minimum,
			"maximum": _maximum,
			"value": value,
		},
	}


func experiment_with_reward_frequency(value: int) -> Dictionary:
	if _experiment.is_empty():
		return _failure("documents_not_loaded", "load documents first")
	if value < _minimum or value > _maximum:
		return _failure("rare_weight_out_of_range", str(value))
	var revised := _experiment.duplicate(true)
	var assignment := _rare_weight_assignment(revised, _model_id)
	if assignment.is_empty():
		return _failure("missing_rare_weight_assignment", PARAMETER_NAME)
	assignment["value"] = value
	return {"ok": true, "value": revised}


func _read_object(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return _failure("document_not_found", path)
	var parsed = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		return _failure("invalid_document", path)
	return {"ok": true, "value": parsed}


func _rare_weight_parameter(model_source: Dictionary) -> Dictionary:
	for module in model_source.get("modules", []):
		if module.get("id") != MODULE_ID:
			continue
		for symbol in module.get("symbols", []):
			if symbol.get("symbol") == PARAMETER_NAME:
				return symbol
	return {}


func _rare_weight_assignment(experiment: Dictionary, model_id: String) -> Dictionary:
	for scenario in experiment.get("scenarios", []):
		for assignment in scenario.get("assignments", []):
			var target: Dictionary = assignment.get("target", {})
			if (
				target.get("model") == model_id
				and target.get("module") == MODULE_ID
				and target.get("name") == PARAMETER_NAME
			):
				return assignment
	return {}


func _failure(kind: String, detail: String) -> Dictionary:
	return {"ok": false, "kind": kind, "detail": detail}
