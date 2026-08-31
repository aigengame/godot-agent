extends "res://tests/playtest_test_case.gd"

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const PeriodicEffectController = preload(
	"res://content/periodic_effect/periodic_effect_controller.gd"
)
const PlaytestExecutionCoordinator = preload(
	"res://content/playtest_execution_coordinator.gd"
)
const PeriodicEffectTimeline = preload(
	"res://systems/periodic_effect_timeline.gd"
)
const WAIT_TIMEOUT_MSEC := 60000


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var client := GdaExecutionClient.new()
	get_root().add_child(client)
	var execution := PlaytestExecutionCoordinator.new()
	execution.configure(client, OS.get_environment("GDA_BALANCING_EXECUTABLE"))
	var controller := PeriodicEffectController.new()
	get_root().add_child(controller)
	controller.configure(
		execution,
		PeriodicEffectTimeline.new(),
	)
	var started: Dictionary = await controller.start()
	_expect(started.get("ok", false), "Periodic Effect playtest prepares")
	_expect(controller.current_state().get("phase") == "ready", "first curse is ready")
	_expect(controller.current_state().get("trial_kind") == "dynamic", "dynamic trial is first")
	_expect(
		controller.current_state().get("damage_threshold") == 85,
		"player-facing damage cutoff comes from the maintained Experiment",
	)
	controller.primary_action()
	_expect(await _wait_for_phase(controller, "timeline_step"), "dynamic revision runs")
	_expect(controller.current_state().get("lifecycle_phase") == "apply", "apply is visible")
	_complete_trial(controller)
	controller.primary_action()
	_expect(
		controller.current_state().get("phase") == "resetting_target",
		"the controller separates the two independent trials",
	)
	_expect(
		controller.current_state().get("fresh_target") == true
		and controller.current_state().get("previous_health") == 75
		and controller.current_state().get("initial_health") == 100,
		"the second trial explicitly resets the target instead of implying continuity",
	)
	controller.primary_action()
	_expect(
		controller.current_state().get("phase") == "resetting_target",
		"gameplay cannot skip the visible target reset",
	)
	controller.target_reset_completed()
	_expect(controller.current_state().get("phase") == "ready", "fixed curse is ready")
	controller.primary_action()
	_expect(await _wait_for_phase(controller, "timeline_step"), "fixed revision runs")
	_complete_trial(controller)
	controller.primary_action()
	_expect(controller.current_state().get("phase") == "feedback", "trials reach feedback")
	var payload := controller.submit_feedback(
		"Dynamic Curse", "Very clear", "Mostly clear", "Readable"
	)
	_expect(not payload.is_empty(), "Periodic Effect feedback saves")
	_expect(payload.get("trials", []).size() == 2, "feedback retains both trials")
	_expect(
		payload.get("trials", [])[1].get("timeline", [])[-1].get("health") == 60,
		"feedback retains the fixed trial terminal health",
	)
	await controller.shutdown()
	controller.queue_free()
	client.queue_free()
	_finish()


func _complete_trial(controller: Node) -> void:
	for unused in 5:
		controller.primary_action()
	_expect(controller.current_state().get("phase") == "trial_complete", "trial completes")


func _wait_for_phase(controller: Node, expected: String) -> bool:
	var deadline := Time.get_ticks_msec() + WAIT_TIMEOUT_MSEC
	while Time.get_ticks_msec() < deadline:
		if controller.current_state().get("phase") == expected:
			return true
		await process_frame
	return false
