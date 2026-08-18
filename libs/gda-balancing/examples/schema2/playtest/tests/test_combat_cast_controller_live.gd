extends "res://tests/playtest_test_case.gd"

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const CombatCastController = preload(
	"res://content/combat_cast/combat_cast_controller.gd"
)
const CombatDuel = preload("res://systems/combat_duel.gd")
const WAIT_TIMEOUT_MSEC := 60000


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var client := GdaExecutionClient.new()
	get_root().add_child(client)
	var controller := CombatCastController.new()
	get_root().add_child(controller)
	controller.configure(
		client,
		OS.get_environment("GDA_BALANCING_EXECUTABLE"),
		CombatDuel.new(),
	)
	var started: Dictionary = await controller.start()
	_expect(started.get("ok", false), "Combat playtest prepares")
	_expect(controller.current_state().get("phase") == "ready", "duel is ready")
	var configured := controller.set_playtest_options("efficient", "strong")
	_expect(configured.get("ok", false), "player can select duel options")

	for expected in [
		["player_resolved", 26, 6],
		["enemy_resolved", 26, 7],
		["player_resolved", 26, 6],
		["enemy_resolved", 26, 7],
		["player_resolved", 26, 6],
		["enemy_resolved", 26, 7],
		["victory", 22, 6],
	]:
		controller.primary_action()
		_expect(
			await _wait_for_phase(controller, expected[0]),
			"action reaches %s" % expected[0],
		)
		_expect(controller.current_state().get("damage") == expected[1], "damage is visible")
		_expect(controller.current_state().get("mana_cost") == expected[2], "MP cost is visible")

	var terminal := controller.current_state()
	_expect(
		terminal.get("combatants", {}).get("enemy_health") == 0,
		"duel ends only after the explicit target-defeated action",
	)
	_expect(terminal.get("action_index") == 7, "no counterattack follows terminal defeat")
	controller.open_feedback()
	_expect(controller.current_state().get("phase") == "feedback", "terminal duel offers feedback")
	var payload := controller.submit_feedback(
		"Satisfying", "Very clear", "Fair", "Readable"
	)
	_expect(not payload.is_empty(), "Combat feedback saves")
	_expect(payload.get("actions", []).size() == 7, "feedback retains every played action")
	_expect(
		payload.get("playtest_options")
		== {"rival_strength": "strong", "spell_style": "efficient"},
		"feedback retains the selected duel options",
	)
	_expect(payload.get("outcome") == "victory", "feedback retains the explicit outcome")
	controller.restart_battle()
	_expect(controller.current_state().get("phase") == "ready", "player can restart the duel")
	_expect(
		controller.current_state().get("combatants", {}).get("enemy_health") == 100,
		"restart restores the selected duel's initial state",
	)
	await controller.shutdown()
	controller.queue_free()
	client.queue_free()
	_finish()


func _wait_for_phase(controller: Node, expected: String) -> bool:
	var deadline := Time.get_ticks_msec() + WAIT_TIMEOUT_MSEC
	while Time.get_ticks_msec() < deadline:
		if controller.current_state().get("phase") == expected:
			return true
		if controller.current_state().get("phase") == "retry":
			return false
		await process_frame
	return false
