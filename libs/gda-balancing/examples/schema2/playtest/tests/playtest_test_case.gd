extends SceneTree


class RuntimeErrorCapture extends Logger:
	var _errors: Array[String] = []
	var _mutex := Mutex.new()

	func _log_message(_message: String, _error: bool) -> void:
		pass

	func _log_error(
		_function: String,
		_file: String,
		_line: int,
		code: String,
		rationale: String,
		_editor_notify: bool,
		error_type: int,
		_script_backtraces: Array[ScriptBacktrace],
	) -> void:
		if error_type == ERROR_TYPE_WARNING:
			return
		_mutex.lock()
		_errors.append(rationale if not rationale.is_empty() else code)
		_mutex.unlock()

	func errors() -> Array[String]:
		_mutex.lock()
		var snapshot := _errors.duplicate()
		_mutex.unlock()
		return snapshot


var _assertion_count := 0
var _failures: Array[String] = []
var _runtime_errors := RuntimeErrorCapture.new()
var _runtime_errors_registered := false


func _init() -> void:
	OS.add_logger(_runtime_errors)
	_runtime_errors_registered = true


func _expect(condition: bool, message: String) -> void:
	_assertion_count += 1
	if not condition:
		_fail(message)


func _fail(message: String) -> void:
	_failures.append(message)


func _finish() -> void:
	if _runtime_errors_registered:
		OS.remove_logger(_runtime_errors)
		_runtime_errors_registered = false
	for error in _runtime_errors.errors():
		_fail("unexpected Godot runtime error: %s" % error)
	if _failures.is_empty():
		print(JSON.stringify({"passed": _assertion_count, "status": "passed"}))
		quit(0)
		return
	for failure in _failures:
		push_error(failure)
	quit(1)
