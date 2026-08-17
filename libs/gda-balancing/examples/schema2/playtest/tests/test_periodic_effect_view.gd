extends "res://tests/playtest_test_case.gd"

const PeriodicEffectController = preload(
	"res://content/periodic_effect/periodic_effect_controller.gd"
)
const PeriodicEffectView = preload(
	"res://ui/periodic_effect/periodic_effect_view.gd"
)

class RecordingController extends PeriodicEffectController:
	var primary_actions := 0

	func primary_action() -> void:
		primary_actions += 1


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var controller := RecordingController.new()
	get_root().add_child(controller)
	var view := PeriodicEffectView.new()
	get_root().add_child(view)
	await process_frame
	view.bind(controller)
	controller.view_state_changed.emit({"phase": "preparing", "trial_count": 2})
	await process_frame
	var early_action := InputEventKey.new()
	early_action.pressed = true
	early_action.keycode = KEY_SPACE
	Input.parse_input_event(early_action)
	await process_frame
	_expect(controller.primary_actions == 0, "hidden Effect action ignores keyboard input")
	controller.view_state_changed.emit(
		{
			"phase": "ready",
			"trial_count": 2,
			"trial_index": 0,
			"trial_kind": "reactive",
		}
	)
	await process_frame
	var action := view.find_child("PrimaryAction", true, false) as Button
	_expect(action != null and not action.disabled, "player can apply the curse")
	if action != null:
		action.pressed.emit()
	_expect(controller.primary_actions == 1, "Effect UI submits the player action")
	_expect(view.find_child("EffectTargetHealth", true, false) != null, "health is visible")
	_expect(view.find_child("EffectTargetBlock", true, false) != null, "target is visible")
	view.queue_free()
	controller.queue_free()
	_finish()
