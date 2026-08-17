extends "res://tests/playtest_test_case.gd"

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const PeriodicEffectController = preload(
	"res://content/periodic_effect/periodic_effect_controller.gd"
)
const WAIT_TIMEOUT_MSEC := 60000


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var client := GdaExecutionClient.new()
	get_root().add_child(client)
	var controller := PeriodicEffectController.new()
	get_root().add_child(controller)
	controller.configure(client, OS.get_environment("GDA_BALANCING_EXECUTABLE"))
	var started: Dictionary = await controller.start()
	_expect(started.get("ok", false), "Periodic Effect playtest prepares")
	_expect(controller.current_state().get("phase") == "ready", "first curse is ready")
	_expect(controller.current_state().get("trial_kind") == "reactive", "reactive trial is first")
	controller.primary_action()
	_expect(await _wait_for_phase(controller, "timeline_step"), "reactive revision runs")
	_expect(controller.current_state().get("lifecycle_phase") == "apply", "apply is visible")
	_complete_trial(controller)
	controller.primary_action()
	_expect(controller.current_state().get("phase") == "ready", "locked curse is ready")
	controller.primary_action()
	_expect(await _wait_for_phase(controller, "timeline_step"), "locked revision runs")
	_complete_trial(controller)
	controller.primary_action()
	_expect(controller.current_state().get("phase") == "feedback", "trials reach feedback")
	var payload := controller.submit_feedback(
		"Reactive Hex", "Very clear", "Mostly clear", "Readable"
	)
	_expect(not payload.is_empty(), "Periodic Effect feedback saves")
	_expect(payload.get("trials", []).size() == 2, "feedback retains both trials")
	_expect(
		payload.get("trials", [])[1].get("timeline", [])[-1].get("health") == 60,
		"feedback retains the locked trial terminal health",
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
