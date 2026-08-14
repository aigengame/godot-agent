extends RefCounted

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


func start() -> Dictionary:
	_current_index = 0
	return _session_state()


func finish_current_trial() -> Dictionary:
	if _current_index < 0:
		return start()
	_current_index += 1
	return _session_state()


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


func _session_state() -> Dictionary:
	var complete := _current_index >= _trials.size()
	return {
		"complete": complete,
		"trial": {} if complete else _trials[_current_index].duplicate(true),
		"trial_count": _trials.size(),
		"trial_index": _trials.size() if complete else _current_index,
	}
