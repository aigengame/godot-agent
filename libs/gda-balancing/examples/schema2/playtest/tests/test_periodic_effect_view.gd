extends "res://tests/playtest_test_case.gd"

const PeriodicEffectController = preload(
	"res://content/periodic_effect/periodic_effect_controller.gd"
)
const PeriodicEffectView = preload(
	"res://ui/periodic_effect/periodic_effect_view.gd"
)

class RecordingController extends PeriodicEffectController:
	var primary_actions := 0
	var target_resets := 0

	func primary_action() -> void:
		primary_actions += 1

	func target_reset_completed() -> void:
		target_resets += 1


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
			"trial_kind": "dynamic",
			"damage_threshold": 85,
			"initial_health": 100,
		}
	)
	await process_frame
	var action := view.find_child("PrimaryAction", true, false) as Button
	_expect(action != null and not action.disabled, "player can apply the curse")
	var rule := view.find_child("EffectRule", true, false) as Label
	_expect(
		rule != null and not rule.text.is_empty() and rule.text.contains("85"),
		"the Dynamic Curse explains its player-facing damage rule",
	)
	var threshold := view.find_child("EffectDamageThreshold", true, false) as Label
	_expect(
		threshold != null and threshold.text.contains("85"),
		"the health bar names the Dynamic Curse damage threshold",
	)
	var marker := view.find_child("EffectDamageThresholdMarker", true, false) as ColorRect
	_expect(
		marker != null and marker.visible and is_equal_approx(marker.anchor_left, 0.85),
		"the health bar marks the damage threshold at the maintained value",
	)
	controller.view_state_changed.emit(
		{
			"phase": "timeline_step",
			"trial_count": 2,
			"trial_index": 0,
			"trial_kind": "dynamic",
			"damage_threshold": 85,
			"initial_health": 100,
			"lifecycle_phase": "pulse",
			"damage": 0,
			"health": 75,
			"health_before": 75,
			"effect_active": true,
			"step": 3,
			"step_count": 5,
		}
	)
	await process_frame
	var step := view.find_child("EffectStep", true, false) as Label
	_expect(
		step != null and step.text.contains("0") and step.text.contains("85"),
		"a zero-damage pulse explains the threshold instead of looking broken",
	)
	controller.view_state_changed.emit(
		{
			"phase": "trial_complete",
			"trial_count": 2,
			"trial_index": 0,
			"trial_kind": "dynamic",
			"damage_threshold": 85,
			"initial_health": 100,
			"health": 75,
		}
	)
	await process_frame
	controller.view_state_changed.emit(
		{
			"phase": "resetting_target",
			"trial_count": 2,
			"trial_index": 1,
			"trial_kind": "snapshot",
			"damage_threshold": 85,
			"fresh_target": true,
			"initial_health": 100,
			"previous_health": 75,
		}
	)
	await process_frame
	var health := view.find_child("EffectTargetHealth", true, false) as ProgressBar
	_expect(
		action != null and action.disabled and health != null and health.value < 100,
		"the fixed trial waits while a fresh target visibly replaces the previous one",
	)
	await create_timer(0.7).timeout
	_expect(
		controller.target_resets == 1 and health != null and health.value == 100,
		"the reset animation completes before Content can present the fixed trial",
	)
	controller.view_state_changed.emit(
		{
			"phase": "ready",
			"trial_count": 2,
			"trial_index": 1,
			"trial_kind": "snapshot",
			"damage_threshold": 85,
			"fresh_target": true,
			"initial_health": 100,
			"previous_health": 75,
		}
	)
	await process_frame
	_expect(
		action != null and not action.disabled and health != null and health.value == 100,
		"the fixed curse can be cast only after the fresh target is ready",
	)
	_expect(
		rule.text.contains("fresh target") and rule.text.contains("100"),
		"the fixed rule states that this is a new 100-Health trial",
	)
	controller.view_state_changed.emit(
		{
			"phase": "timeline_step",
			"trial_count": 2,
			"trial_index": 1,
			"trial_kind": "snapshot",
			"cast_damage": 15,
			"damage_threshold": 85,
			"initial_health": 100,
			"lifecycle_phase": "apply",
			"damage": 0,
			"health": 100,
			"health_before": 100,
			"effect_active": true,
			"step": 0,
			"step_count": 5,
		}
	)
	await process_frame
	_expect(
		step.text.contains("fixed at 15") and step.text.contains("both pulses"),
		"the cast confirms the concrete fixed damage before either pulse",
	)
	if action != null:
		action.pressed.emit()
	_expect(controller.primary_actions == 1, "Effect UI submits the player action")
	_expect(health != null, "health is visible")
	_expect(view.find_child("EffectTargetBlock", true, false) != null, "target is visible")
	view.queue_free()
	controller.queue_free()
	_finish()
