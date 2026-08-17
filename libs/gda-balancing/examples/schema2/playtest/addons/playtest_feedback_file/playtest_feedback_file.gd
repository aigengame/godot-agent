class_name PlaytestFeedbackFile
extends RefCounted


func save(path: String, payload: Dictionary) -> Dictionary:
	var detached := payload.duplicate(true)
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return {}
	file.store_string(JSON.stringify(detached, "\t") + "\n")
	return {"path": path, "payload": detached}
