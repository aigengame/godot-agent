extends SceneTree

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)

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
	var started: Dictionary = await client.start(executable)
	_expect(started.get("ok", false), "client starts a compatible local service")
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
		print(JSON.stringify({"passed": 7, "status": "passed"}))
		quit(0)
		return
	for failure in _failures:
		push_error(failure)
	quit(1)
