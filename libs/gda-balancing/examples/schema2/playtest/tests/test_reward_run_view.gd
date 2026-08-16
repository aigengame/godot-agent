extends SceneTree

const RewardRunController = preload(
	"res://content/reward_run/reward_run_controller.gd"
)
const RewardRunView = preload("res://ui/reward_run_view.gd")

var _failures: Array[String] = []


class RecordingController extends RewardRunController:
	var requested_weights: Array[int] = []

	func start_trial(rare_weight: int) -> Dictionary:
		requested_weights.append(rare_weight)
		return {"ok": true}


func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var controller := RecordingController.new()
	get_root().add_child(controller)
	var view := RewardRunView.new()
	get_root().add_child(view)
	await process_frame
	view.bind(controller)
	controller.view_state_changed.emit(
		{
			"phase": "choose_frequency",
			"rare_weight": {"minimum": 0, "maximum": 90, "value": 5},
			"trial_count": 2,
			"trial_index": 0,
		}
	)
	await process_frame

	var frequency := view.find_child("RareWeight", true, false) as Range
	_expect(frequency != null, "Rare reward frequency is visible")
	if frequency != null:
		_expect(frequency.min_value == 0.0, "control uses the Model minimum")
		_expect(frequency.max_value == 90.0, "control uses the Model maximum")
		_expect(frequency.value == 5.0, "control uses the Experiment default")
	var action := view.find_child("PrimaryAction", true, false) as Button
	_expect(action != null and not action.disabled, "player can start the trial")
	if action != null:
		action.pressed.emit()
	_expect(controller.requested_weights == [5], "UI submits the player value")

	view.queue_free()
	controller.queue_free()
	_finish()


func _expect(condition: bool, message: String) -> void:
	if not condition:
		_failures.append(message)


func _finish() -> void:
	if _failures.is_empty():
		print(JSON.stringify({"passed": 6, "status": "passed"}))
		quit(0)
		return
	for failure in _failures:
		push_error(failure)
	quit(1)
