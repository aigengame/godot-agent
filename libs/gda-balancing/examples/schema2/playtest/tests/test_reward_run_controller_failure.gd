extends "res://tests/playtest_test_case.gd"

const RewardRunController = preload(
	"res://content/reward_run/reward_run_controller.gd"
)

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
	super()
	call_deferred("_run")


func _run() -> void:
	var client := RefusingExecutionClient.new()
	get_root().add_child(client)
	var controller := RewardRunController.new()
	get_root().add_child(controller)
	controller.configure(
		client,
		"unused-by-boundary-test",
	)
	controller.primary_action()
	_expect(controller.phase == "loading", "input before preparation is ignored")
	_expect(controller.current_state().is_empty(), "early input emits no gameplay state")
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
