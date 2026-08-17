extends "res://tests/playtest_test_case.gd"

const RewardRunController = preload(
	"res://content/reward_run/reward_run_controller.gd"
)
const RewardRunView = preload("res://ui/reward_run_view.gd")

class RecordingController extends RewardRunController:
	var requested_weights: Array[int] = []
	var primary_actions := 0

	func start_trial(reward_frequency: int) -> Dictionary:
		requested_weights.append(reward_frequency)
		return {"ok": true}

	func primary_action() -> void:
		primary_actions += 1


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var controller := RecordingController.new()
	get_root().add_child(controller)
	var view := RewardRunView.new()
	get_root().add_child(view)
	await process_frame
	view.bind(controller)
	controller.view_state_changed.emit(
		{"phase": "preparing", "trial_count": 2, "trial_index": 0}
	)
	await process_frame
	var early_action := InputEventKey.new()
	early_action.pressed = true
	early_action.keycode = KEY_SPACE
	Input.parse_input_event(early_action)
	await process_frame
	_expect(controller.primary_actions == 0, "hidden action ignores keyboard input")
	controller.view_state_changed.emit(
		{
			"phase": "choose_frequency",
			"reward_frequency": {"minimum": 0, "maximum": 90, "value": 5},
			"trial_count": 2,
			"trial_index": 0,
		}
	)
	await process_frame

	var frequency := view.find_child("RewardFrequency", true, false) as Range
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

	controller.view_state_changed.emit(
		{
			"phase": "before_fight",
			"reward_frequency_value": 5,
			"power": 10,
			"target_health": 30,
			"target_max_health": 30,
			"reward": {"key": "volatile_crown", "rarity": "rare"},
			"build": {"power_before": 10, "power_after": 90},
			"trial_count": 2,
			"trial_index": 0,
		}
	)
	await process_frame
	var frequency_panel := view.find_child("FrequencyPanel", true, false) as Control
	_expect(
		frequency_panel != null and not frequency_panel.visible,
		"locked setup control is hidden during play",
	)

	view.queue_free()
	controller.queue_free()
	_finish()
