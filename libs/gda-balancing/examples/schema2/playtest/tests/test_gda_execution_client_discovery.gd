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

	var separator := ";" if OS.get_name() == "Windows" else ":"
	var original_path := OS.get_environment("PATH")
	OS.set_environment(
		"PATH",
		executable.get_base_dir() + separator + original_path,
	)
	var client := GdaExecutionClient.new()
	get_root().add_child(client)
	var started: Dictionary = await client.start()
	_expect(started.get("ok", false), "client finds gda-balancing on PATH")
	if started.get("ok", false):
		var stopped: Dictionary = await client.shutdown()
		_expect(stopped.get("ok", false), "PATH-started service shuts down")
	client.queue_free()

	var invalid := GdaExecutionClient.new()
	get_root().add_child(invalid)
	var refused: Dictionary = await invalid.start(
		ProjectSettings.globalize_path("res://missing-gda-balancing")
	)
	_expect(not refused.get("ok", true), "invalid explicit path is refused")
	_expect(
		refused.get("kind") == "executable_not_found",
		"invalid explicit path does not fall back to PATH",
	)
	invalid.queue_free()
	OS.set_environment("PATH", original_path)
	_finish()


func _expect(condition: bool, message: String) -> void:
	if not condition:
		_failures.append(message)


func _finish() -> void:
	if _failures.is_empty():
		print(JSON.stringify({"passed": 4, "status": "passed"}))
		quit(0)
		return
	for failure in _failures:
		push_error(failure)
	quit(1)
