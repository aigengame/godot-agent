extends "res://tests/playtest_test_case.gd"

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const CombatCastController = preload(
	"res://content/combat_cast/combat_cast_controller.gd"
)
const WAIT_TIMEOUT_MSEC := 60000


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var client := GdaExecutionClient.new()
	get_root().add_child(client)
	var controller := CombatCastController.new()
	get_root().add_child(controller)
	controller.configure(client, OS.get_environment("GDA_BALANCING_EXECUTABLE"))
	var started: Dictionary = await controller.start()
	_expect(started.get("ok", false), "Combat playtest prepares")
	_expect(controller.current_state().get("phase") == "ready", "first exchange is ready")
	controller.primary_action()
	_expect(await _wait_for_phase(controller, "before_exchange"), "first revision runs")
	_complete_exchange(controller)
	controller.primary_action()
	_expect(controller.current_state().get("phase") == "ready", "second exchange is ready")
	_expect(
		controller.current_state().get("combatants", {}).get("player_health") == 86,
		"later exchange starts from the prior validated health",
	)
	controller.primary_action()
	_expect(await _wait_for_phase(controller, "before_exchange"), "later revision runs")
	_complete_exchange(controller)
	controller.primary_action()
	_expect(controller.current_state().get("phase") == "feedback", "duel reaches feedback")
	var payload := controller.submit_feedback(
		"Exchange 1", "Very clear", "Fair", "Readable"
	)
	_expect(not payload.is_empty(), "Combat feedback saves")
	_expect(payload.get("exchanges", []).size() == 2, "feedback retains both exchanges")
	_expect(
		payload.get("exchanges", [])[1].get("terminal", {}).get("enemy_health") == 26,
		"feedback retains the continued duel result",
	)
	await controller.shutdown()
	controller.queue_free()
	client.queue_free()
	_finish()


func _complete_exchange(controller: Node) -> void:
	controller.primary_action()
	_expect(controller.current_state().get("phase") == "player_resolved", "player cast is shown")
	controller.primary_action()
	_expect(controller.current_state().get("phase") == "enemy_resolved", "counterattack is shown")
	controller.primary_action()
	_expect(controller.current_state().get("phase") == "exchange_complete", "exchange completes")


func _wait_for_phase(controller: Node, expected: String) -> bool:
	var deadline := Time.get_ticks_msec() + WAIT_TIMEOUT_MSEC
	while Time.get_ticks_msec() < deadline:
		if controller.current_state().get("phase") == expected:
			return true
		await process_frame
	return false
