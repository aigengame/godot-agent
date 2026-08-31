extends "res://tests/playtest_test_case.gd"

const CombatCastController = preload(
	"res://content/combat_cast/combat_cast_controller.gd"
)
const CombatDuel = preload("res://systems/combat_duel.gd")
const FakePlaytestExecutionCoordinator = preload(
	"res://tests/fake_playtest_execution_coordinator.gd"
)


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var execution := FakePlaytestExecutionCoordinator.new()
	var controller := CombatCastController.new()
	get_root().add_child(controller)
	controller.configure(execution, CombatDuel.new())
	var started: Dictionary = await controller.start()
	_expect(started.get("ok", false), "fake Combat preparation succeeds")
	var before: Dictionary = controller.current_state().get(
		"combatants", {}
	).duplicate(true)
	controller.primary_action()
	await process_frame
	var refused := controller.current_state()
	_expect(refused.get("phase") == "retry", "run refusal presents retry")
	_expect(refused.get("combatants") == before, "run refusal commits no gameplay state")
	_expect(not refused.has("damage"), "run refusal publishes no damage")
	var retried: Dictionary = await controller.retry()
	_expect(retried.get("ok", false), "explicit retry recreates the Combat session")
	_expect(execution.sessions_created == 2, "retry creates a new isolated session")
	execution.return_invalid_artifacts = true
	controller.primary_action()
	await process_frame
	_expect(
		controller.current_state().get("phase") == "retry",
		"projection failure also presents retry",
	)
	_expect(
		not controller.current_state().has("damage"),
		"projection failure publishes no Combat result",
	)
	await controller.shutdown()
	controller.queue_free()
	_finish()
