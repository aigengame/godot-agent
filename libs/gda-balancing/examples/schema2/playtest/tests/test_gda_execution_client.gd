extends SceneTree

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)


class CompatibilityErrorCapture extends Logger:
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
		_error_type: int,
		_script_backtraces: Array[ScriptBacktrace],
	) -> void:
		_mutex.lock()
		_errors.append(rationale if not rationale.is_empty() else code)
		_mutex.unlock()

	func errors() -> Array[String]:
		_mutex.lock()
		var snapshot := _errors.duplicate()
		_mutex.unlock()
		return snapshot


var _failures: Array[String] = []


func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var executable := OS.get_environment("GDA_BALANCING_EXECUTABLE")
	_expect(not executable.is_empty(), "test executable is provided")
	if executable.is_empty():
		_finish()
		return

	var client := GdaExecutionClient.new()
	get_root().add_child(client)
	_expect_compatibility_gate(client)
	var started: Dictionary = await client.start(executable)
	_expect(started.get("ok", false), "client starts a compatible local service")
	_expect(not started.has("value"), "readiness credential stays inside the Add-on")
	var detail: String = client._compatibility_detail(
		{
			"capability_token": "must-not-cross-the-boundary",
			"protocol": "future",
			"status": "ready",
			"toolkit_version": "future",
		}
	)
	_expect(
		not detail.contains("must-not-cross-the-boundary"),
		"incompatible readiness detail omits the credential",
	)
	if not started.get("ok", false):
		client.queue_free()
		_finish()
		return

	var example_dir := ProjectSettings.globalize_path("res://").path_join(
		"../roguelike-reward-build"
	).simplify_path()
	var model_source := _read_json(example_dir.path_join("model-source.json"))
	var experiment := _read_json(example_dir.path_join("experiment.json"))
	var created: Dictionary = await client.create_session(model_source, experiment)
	_expect(
		created.get("ok", false),
		"client creates an Execution session: %s" % JSON.stringify(created),
	)
	if created.get("ok", false):
		var run: Dictionary = await client.run_revision(
			created["session"],
			created["revision"],
		)
		_expect(run.get("ok", false), "client runs the exact Experiment revision")
		_expect(
			run.get("value", {}).get("artifacts", {}).has("event-trace"),
			"run returns the existing Event Trace artifact",
		)
		var deleted: Dictionary = await client.delete_session(created["session"])
		_expect(deleted.get("ok", false), "client deletes the Execution session")

	var stopped: Dictionary = await client.shutdown()
	_expect(stopped.get("ok", false), "client shuts down its service process")
	client.queue_free()
	_finish()


func _expect_compatibility_gate(client: Node) -> void:
	var error_capture := CompatibilityErrorCapture.new()
	OS.add_logger(error_capture)
	var readiness := {
		"base_url": "http://127.0.0.1:1",
		"capability_token": "token",
		"protocol": "v1",
		"status": "ready",
		"toolkit_version": "future",
	}
	_expect(client._is_compatible_readiness(readiness), "complete readiness is compatible")
	for invalid in [
		readiness.merged({"protocol": "future"}, true),
		readiness.merged({"toolkit_version": ""}, true),
		readiness.merged({"toolkit_version": 1}, true),
	]:
		_expect(not client._is_compatible_readiness(invalid), "invalid readiness is rejected")
	var status := {
		"ok": true,
		"value": {
			"protocol": "v1",
			"status": "ready",
			"toolkit_version": "future",
		},
	}
	_expect(client._is_compatible_status(readiness, status), "matching status is compatible")
	for invalid in [
		status.merged({"value": status["value"].merged({"protocol": "future"}, true)}, true),
		status.merged({"value": status["value"].merged({"status": "starting"}, true)}, true),
		status.merged({"value": status["value"].merged({"toolkit_version": ""}, true)}, true),
		status.merged({"value": status["value"].merged({"toolkit_version": 1}, true)}, true),
	]:
		_expect(not client._is_compatible_status(readiness, invalid), "invalid status is rejected")
	var malformed_values: Array = [1, [], {}, null]
	for field in ["status", "protocol"]:
		for malformed in malformed_values:
			var invalid_readiness := readiness.merged({field: malformed}, true)
			_expect(
				not client._is_compatible_readiness(invalid_readiness),
				"malformed readiness %s is rejected" % field,
			)
			var invalid_status_value: Dictionary = status["value"].merged({field: malformed}, true)
			var invalid_status := status.merged({"value": invalid_status_value}, true)
			_expect(
				not client._is_compatible_status(readiness, invalid_status),
				"malformed status %s is rejected" % field,
			)
	OS.remove_logger(error_capture)
	_expect(
		error_capture.errors().is_empty(),
		"malformed compatibility facts produce no script errors: %s"
		% JSON.stringify(error_capture.errors()),
	)


func _read_json(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		_failures.append("maintained document opens: %s" % path)
		return {}
	var value = JSON.parse_string(file.get_as_text())
	if not value is Dictionary:
		_failures.append("maintained document is JSON: %s" % path)
		return {}
	return value


func _expect(condition: bool, message: String) -> void:
	if not condition:
		_failures.append(message)


func _finish() -> void:
	if _failures.is_empty():
		print(JSON.stringify({"passed": 35, "status": "passed"}))
		quit(0)
		return
	for failure in _failures:
		push_error(failure)
	quit(1)
