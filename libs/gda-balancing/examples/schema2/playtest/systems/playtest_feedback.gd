extends RefCounted

var _path: String


func _init(path: String) -> void:
	_path = path


func save(answers: Dictionary, trial_references: Array[Dictionary]) -> Dictionary:
	var payload := answers.duplicate(true)
	payload["created_at"] = Time.get_datetime_string_from_system(true)
	payload["schema_version"] = 1
	payload["trials"] = trial_references.duplicate(true)
	var file := FileAccess.open(_path, FileAccess.WRITE)
	if file == null:
		return {}
	file.store_string(JSON.stringify(payload, "\t") + "\n")
	return {"path": _path, "payload": payload}
