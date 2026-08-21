extends "res://tests/playtest_test_case.gd"

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const RewardRunController = preload(
	"res://content/reward_run/reward_run_controller.gd"
)
const RewardRun = preload("res://systems/reward_run.gd")

func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var executable := OS.get_environment("GDA_BALANCING_EXECUTABLE")
	var client := GdaExecutionClient.new()
	get_root().add_child(client)
	var controller := RewardRunController.new()
	get_root().add_child(controller)
	controller.configure(
		client,
		executable,
		RewardRun.new(),
	)
	var started: Dictionary = await controller.start()
	_expect(started.get("ok", false), "live Reward Run prepares")
	_expect(
		controller.current_state().get("phase") == "choose_frequency",
		"player first chooses the reward frequency",
	)
	_expect(
		controller.current_state().get("reward_frequency")
		== {"minimum": 0, "maximum": 90, "value": 5},
		"the player control uses maintained bounds and default",
	)

	var baseline: Dictionary = await controller.start_trial(5)
	_expect(baseline.get("ok", false), "baseline trial starts from live artifacts")
	_play_trial(controller, 1)
	controller.primary_action()
	_expect(
		controller.current_state().get("phase") == "choose_frequency",
		"first completion returns to the player control",
	)

	var tuned: Dictionary = await controller.start_trial(2)
	_expect(tuned.get("ok", false), "later revision starts without a restart")
	_play_trial(controller, 3)
	controller.primary_action()
	_expect(
		controller.current_state().get("phase") == "feedback",
		"two live trials reach player feedback",
	)

	await controller.shutdown()
	controller.queue_free()
	client.queue_free()
	_finish()


func _play_trial(controller, second_target_hits: int) -> void:
	for unused in 3:
		controller.primary_action()
	_expect(
		controller.current_state().get("phase") == "reward_ready",
		"first target reveals the reward",
	)
	controller.primary_action()
	_expect(
		controller.current_state().get("phase") == "after_fight",
		"reward equips before the second target",
	)
	for unused in second_target_hits:
		controller.primary_action()
	_expect(
		controller.current_state().get("phase") == "run_complete",
		"reward power completes the trial",
	)
