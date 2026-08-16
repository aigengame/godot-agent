extends SceneTree

const RewardRunController = preload(
	"res://content/reward_run/reward_run_controller.gd"
)

var _failures: Array[String] = []


class RefusingExecutionClient extends Node:
	var sessions_created := 0

	func start(_executable_path: String = "") -> Dictionary:
		return {"ok": true}

	func create_session(_model: Dictionary, _experiment: Dictionary) -> Dictionary:
		sessions_created += 1
		return {
			"ok": true,
			"session": "session-%d" % sessions_created,
			"revision": "baseline",
		}

	func admit_revision(_session: String, _experiment: Dictionary) -> Dictionary:
		return {"ok": true, "revision": "candidate"}

	func run_revision(_session: String, _revision: String) -> Dictionary:
		return {
			"ok": false,
			"kind": "execution_refused",
			"value": {"outcome": "refusal"},
		}

	func delete_session(_session: String) -> Dictionary:
		return {"ok": true}

	func shutdown() -> Dictionary:
		return {"ok": true}


func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var example_dir := ProjectSettings.globalize_path("res://").path_join(
		"../roguelike-reward-build"
	).simplify_path()
	var client := RefusingExecutionClient.new()
	get_root().add_child(client)
	var controller := RewardRunController.new()
	get_root().add_child(controller)
	controller.configure(
		client,
		"unused-by-boundary-test",
		example_dir.path_join("model-source.json"),
		example_dir.path_join("experiment.json"),
	)
	var prepared: Dictionary = await controller.start()
	_expect(prepared.get("ok", false), "controller prepares through its boundary")

	var refused: Dictionary = await controller.start_trial(5)
	_expect(not refused.get("ok", true), "refused run is reported")
	var failed_state := controller.current_state()
	_expect(failed_state.get("phase") == "retry", "failure offers explicit retry")
	_expect(failed_state.get("trial_index") == 0, "failure commits no trial")
	_expect(not failed_state.has("reward"), "failure commits no reward state")

	var retried: Dictionary = await controller.retry()
	_expect(retried.get("ok", false), "explicit retry recreates the live session")
	_expect(client.sessions_created == 2, "retry establishes a new Execution session")
	_expect(
		controller.current_state().get("phase") == "choose_frequency",
		"retry returns to the player control",
	)

	await controller.shutdown()
	controller.queue_free()
	client.queue_free()
	_finish()


func _expect(condition: bool, message: String) -> void:
	if not condition:
		_failures.append(message)


func _finish() -> void:
	if _failures.is_empty():
		print(JSON.stringify({"passed": 8, "status": "passed"}))
		quit(0)
		return
	for failure in _failures:
		push_error(failure)
	quit(1)
