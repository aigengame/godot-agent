extends SceneTree

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const RewardRunController = preload(
	"res://content/reward_run/reward_run_controller.gd"
)

var _failures: Array[String] = []


func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var executable := OS.get_environment("GDA_BALANCING_EXECUTABLE")
	var example_dir := ProjectSettings.globalize_path("res://").path_join(
		"../roguelike-reward-build"
	).simplify_path()
	var client := GdaExecutionClient.new()
	get_root().add_child(client)
	var controller := RewardRunController.new()
	get_root().add_child(controller)
	controller.configure(
		client,
		executable,
		example_dir.path_join("model-source.json"),
		example_dir.path_join("experiment.json"),
	)
	var started: Dictionary = await controller.start()
	_expect(started.get("ok", false), "live Reward Run prepares")
	_expect(
		controller.current_state().get("phase") == "choose_frequency",
		"player first chooses the reward frequency",
	)
	_expect(
		controller.current_state().get("rare_weight")
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


func _expect(condition: bool, message: String) -> void:
	if not condition:
		_failures.append(message)


func _finish() -> void:
	if _failures.is_empty():
		print(JSON.stringify({"passed": 11, "status": "passed"}))
		quit(0)
		return
	for failure in _failures:
		push_error(failure)
	quit(1)
