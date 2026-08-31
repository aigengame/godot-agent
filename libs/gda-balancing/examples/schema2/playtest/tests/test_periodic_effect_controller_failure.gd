extends "res://tests/playtest_test_case.gd"

const PeriodicEffectController = preload(
	"res://content/periodic_effect/periodic_effect_controller.gd"
)
const PeriodicEffectTimeline = preload(
	"res://systems/periodic_effect_timeline.gd"
)
const FakePlaytestExecutionCoordinator = preload(
	"res://tests/fake_playtest_execution_coordinator.gd"
)


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var execution := FakePlaytestExecutionCoordinator.new()
	var controller := PeriodicEffectController.new()
	get_root().add_child(controller)
	controller.configure(execution, PeriodicEffectTimeline.new())
	var started: Dictionary = await controller.start()
	_expect(started.get("ok", false), "fake Periodic Effect preparation succeeds")
	controller.primary_action()
	await process_frame
	var refused := controller.current_state()
	_expect(refused.get("phase") == "retry", "run refusal presents retry")
	_expect(not refused.has("health"), "run refusal publishes no gameplay state")
	var retried: Dictionary = await controller.retry()
	_expect(retried.get("ok", false), "explicit retry recreates the Effect session")
	_expect(execution.sessions_created == 2, "retry creates a new isolated session")
	execution.return_invalid_artifacts = true
	controller.primary_action()
	await process_frame
	_expect(
		controller.current_state().get("phase") == "retry",
		"projection failure also presents retry",
	)
	_expect(
		not controller.current_state().has("health"),
		"projection failure publishes no Effect result",
	)
	await controller.shutdown()
	controller.queue_free()
	_finish()
