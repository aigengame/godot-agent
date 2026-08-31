extends "res://tests/playtest_test_case.gd"

const CombatCastController = preload(
	"res://content/combat_cast/combat_cast_controller.gd"
)
const CombatAction = preload("res://content/combat_cast/combat_action.gd")
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
	var duel := CombatDuel.new()
	get_root().add_child(controller)
	controller.configure(execution, duel)
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
	var committed_state := before.duplicate(true)
	committed_state["enemy_health"] = int(committed_state["enemy_health"]) - 10
	var committed_action := CombatAction.new()
	committed_action._actor = "player"
	committed_action._terminal = committed_state.duplicate(true)
	controller._actions.append(committed_action)
	controller._combat_state = committed_state.duplicate(true)
	duel.present_action(
		{
			"actor": "player",
			"damage": 10,
			"mana_cost": 1,
			"terminal": committed_state,
		}
	)
	execution.retry_failure = {
		"ok": false,
		"kind": "service_unavailable",
		"detail": "delete failed",
		"stage": "session_deletion",
		"value": {"outcome": "failure"},
	}
	var cleanup_failed: Dictionary = await controller.retry()
	_expect(not cleanup_failed.get("ok", false), "retry reports cleanup failure")
	_expect(
		cleanup_failed.get("stage") == "session_deletion",
		"retry preserves the cleanup failure stage",
	)
	_expect(
		controller.current_state().get("combatants") == committed_state,
		"cleanup failure preserves committed Combat state",
	)
	_expect(
		controller.current_state().get("action_index") == 1,
		"cleanup failure preserves committed Combat history",
	)
	execution.retry_failure = {}
	var recovered: Dictionary = await controller.retry()
	_expect(recovered.get("ok", false), "retry can recover after cleanup failure")
	_expect(
		controller.current_state().get("combatants") == committed_state,
		"successful retry preserves committed Combat state",
	)
	_expect(
		controller.current_state().get("phase") == "player_resolved",
		"successful retry resumes after the last committed actor",
	)
	await controller.shutdown()
	controller.queue_free()
	_finish()
