extends RefCounted

var last_error: String = ""
var _path: String


func _init(path: String) -> void:
	_path = path


func outcome_for(request: Dictionary) -> Dictionary:
	var trial_id := str(request.get("trial_id", ""))
	if trial_id.is_empty():
		last_error = "The reward request is incomplete."
		return {}
	for outcome in _load_outcomes():
		if outcome["id"] == trial_id:
			return outcome.duplicate(true)
	if last_error.is_empty():
		last_error = "The requested reward outcome is not available."
	return {}


func _load_outcomes() -> Array:
	last_error = ""
	var file := FileAccess.open(_path, FileAccess.READ)
	if file == null:
		last_error = "The playtest data could not be opened."
		return []
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		last_error = "The playtest data is not valid."
		return []
	if parsed.get("schema_version") != 1:
		last_error = "The playtest data version is not supported."
		return []
	var trials: Variant = parsed.get("trials")
	if not trials is Array or trials.size() != 2:
		last_error = "The playtest needs exactly two trials."
		return []
	for trial in trials:
		if not _valid_trial(trial):
			last_error = "A playtest trial is incomplete."
			return []
	return trials.duplicate(true)


func _valid_trial(trial: Variant) -> bool:
	if not trial is Dictionary:
		return false
	var reward: Variant = trial.get("reward")
	var build: Variant = trial.get("build")
	return (
		not str(trial.get("id", "")).is_empty()
		and not str(trial.get("title", "")).is_empty()
		and not str(trial.get("playtest_provenance_reference", "")).is_empty()
		and reward is Dictionary
		and not str(reward.get("name", "")).is_empty()
		and build is Dictionary
		and int(build.get("power_before", 0)) > 0
		and int(build.get("power_after", 0)) > 0
	)
