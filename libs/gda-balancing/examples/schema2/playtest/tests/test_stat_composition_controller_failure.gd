extends "res://tests/playtest_test_case.gd"

const StatCompositionController = preload(
	"res://content/stat_composition/stat_composition_controller.gd"
)
const FakePlaytestExecutionCoordinator = preload(
	"res://tests/fake_playtest_execution_coordinator.gd"
)


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var execution := FakePlaytestExecutionCoordinator.new()
	var controller := StatCompositionController.new()
	get_root().add_child(controller)
	controller.configure(execution)
	var started: Dictionary = await controller.start()
	_expect(started.get("ok", false), "fake Stat Composition preparation succeeds")
	var before := controller.current_state()
	controller.primary_action()
	await process_frame
	var refused := controller.current_state()
	_expect(refused.get("phase") == "retry", "run refusal presents Retry")
	_expect(refused.get("target_health") == before.get("target_health"), "run refusal applies no damage")
	_expect(refused.get("attack_count") == 0, "run refusal records no successful attack")
	var retried: Dictionary = await controller.retry()
	_expect(retried.get("ok", false), "explicit Retry recreates the session")
	_expect(execution.sessions_created == 2, "Retry creates a new isolated session")
	execution.return_invalid_artifacts = true
	controller.primary_action()
	await process_frame
	_expect(controller.current_state().get("phase") == "retry", "projection failure presents Retry")
	_expect(controller.current_state().get("attack_count") == 0, "projection failure records no attack")
	await controller.shutdown()
	controller.queue_free()
	_finish()
