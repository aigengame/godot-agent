extends RefCounted

signal trial_changed(index: int, trial: Dictionary)
signal all_trials_completed

var _trials: Array = []
var _current_index: int = -1


func configure(trials: Array) -> bool:
	if trials.is_empty():
		return false
	var known_ids: Dictionary = {}
	for trial in trials:
		if not trial is Dictionary:
			return false
		var trial_id := str(trial.get("id", ""))
		if trial_id.is_empty() or known_ids.has(trial_id):
			return false
		known_ids[trial_id] = true
	_trials = trials.duplicate(true)
	_current_index = -1
	return true


func begin() -> Dictionary:
	_current_index = 0
	var trial := current_trial()
	trial_changed.emit(_current_index, trial)
	return trial


func advance() -> Dictionary:
	if _current_index < 0:
		return begin()
	_current_index += 1
	if _current_index >= _trials.size():
		all_trials_completed.emit()
		return {}
	var trial := current_trial()
	trial_changed.emit(_current_index, trial)
	return trial


func current_trial() -> Dictionary:
	if _current_index < 0 or _current_index >= _trials.size():
		return {}
	return _trials[_current_index].duplicate(true)


func current_index() -> int:
	return _current_index


func trial_count() -> int:
	return _trials.size()


func trial_references() -> Array[Dictionary]:
	var references: Array[Dictionary] = []
	for trial in _trials:
		references.append(
			{
				"id": trial["id"],
				"playtest_provenance_reference": trial[
					"playtest_provenance_reference"
				],
			}
		)
	return references
