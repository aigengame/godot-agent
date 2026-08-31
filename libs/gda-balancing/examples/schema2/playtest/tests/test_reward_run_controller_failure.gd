extends "res://tests/playtest_test_case.gd"

const RewardRunController = preload(
	"res://content/reward_run/reward_run_controller.gd"
)
const RewardRun = preload("res://systems/reward_run.gd")
const FakePlaytestExecutionCoordinator = preload(
	"res://tests/fake_playtest_execution_coordinator.gd"
)


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var execution := FakePlaytestExecutionCoordinator.new()
	var controller := RewardRunController.new()
	get_root().add_child(controller)
	controller.configure(
		execution,
		RewardRun.new(),
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
	_expect(execution.sessions_created == 2, "retry establishes a new Execution session")
	_expect(
		controller.current_state().get("phase") == "choose_frequency",
		"retry returns to the player control",
	)

	await controller.shutdown()
	controller.queue_free()
	_finish()
