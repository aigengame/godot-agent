extends "res://tests/playtest_test_case.gd"

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const StatCompositionController = preload(
	"res://content/stat_composition/stat_composition_controller.gd"
)
const WAIT_TIMEOUT_MSEC := 60000


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var client := GdaExecutionClient.new()
	get_root().add_child(client)
	var controller := StatCompositionController.new()
	get_root().add_child(controller)
	controller.configure(client, OS.get_environment("GDA_BALANCING_EXECUTABLE"))
	var started: Dictionary = await controller.start()
	_expect(started.get("ok", false), "Attack Damage Training prepares")
	_expect(controller.current_state().get("phase") == "ready", "the first attack is ready")
	controller.primary_action()
	_expect(await _wait_for_attack(controller, 1, "ready"), "the default attack resolves")
	_expect(controller.current_state().get("target_health") == 70, "the default attack deals 50 damage")
	var configured := controller.set_playtest_options(3, 18, true)
	_expect(configured.get("ok", false), "the player edits settings between attacks")
	controller.primary_action()
	_expect(await _wait_for_attack(controller, 2, "ready"), "the capped later revision resolves")
	var capped: Dictionary = controller.current_state()["last_attack"]
	_expect(capped.get("capped") == true, "the later revision reaches the damage maximum")
	_expect(capped.get("metrics", {}).get("attack_damage") == 60, "Attack Damage is 60")
	_expect(controller.current_state().get("target_health") == 10, "the dummy retains 10 HP")
	controller.primary_action()
	_expect(await _wait_for_attack(controller, 3, "defeated"), "a final attack defeats the dummy")
	var terminal: Dictionary = controller.current_state()["last_attack"]
	_expect(terminal.get("metrics", {}).get("attack_damage") == 60, "the final Attack Damage stays 60")
	_expect(terminal.get("metrics", {}).get("damage_dealt") == 10, "only remaining HP is dealt")
	controller.open_feedback()
	_expect(controller.current_state().get("phase") == "feedback", "defeat offers feedback")
	var payload := controller.submit_feedback("5", "Yes", "Nothing", "Clear")
	_expect(payload.get("attacks", []).size() == 3, "feedback retains every attack")
	_expect(payload.get("reached_cap") == true, "feedback records that the player reached the cap")
	for attack in payload.get("attacks", []):
		var provenance: Dictionary = attack.get("provenance", {})
		_expect(
			provenance.get("primary_artifact_kind")
			in ["evaluation-run", "experiment-verdict"],
			"every attack records its actual primary artifact kind",
		)
		for member in [
			"primary_artifact_identity",
			"experiment_identity",
			"event_trace_identity",
			"snapshot_series_identity",
			"metric_dataset_identity",
			"reproduction_receipt_identity",
		]:
			_expect(
				not str(provenance.get(member, "")).is_empty(),
				"every attack records %s" % member,
			)
	controller.restart_training()
	_expect(controller.current_state().get("target_health") == 120, "Restart restores the dummy")
	_expect(
		controller.current_state().get("settings", {}).get("weapon_damage_bonus") == 18,
		"Restart retains the selected settings",
	)
	controller.primary_action()
	_expect(
		await _wait_for_attack(controller, 1, "ready"),
		"the first attack after Restart resolves",
	)
	await controller.shutdown()
	controller.queue_free()
	client.queue_free()
	_finish()


func _wait_for_attack(controller: Node, count: int, expected_phase: String) -> bool:
	var deadline := Time.get_ticks_msec() + WAIT_TIMEOUT_MSEC
	while Time.get_ticks_msec() < deadline:
		var state: Dictionary = controller.current_state()
		if state.get("attack_count") == count and state.get("phase") == expected_phase:
			return true
		if state.get("phase") == "retry":
			return false
		await process_frame
	return false
