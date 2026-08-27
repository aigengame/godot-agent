extends "res://tests/playtest_test_case.gd"

const StatCompositionController = preload(
	"res://content/stat_composition/stat_composition_controller.gd"
)
const StatCompositionView = preload(
	"res://ui/stat_composition/stat_composition_view.gd"
)

class RecordingController extends StatCompositionController:
	var feedback_actions := 0
	var primary_actions := 0
	var selected_options: Dictionary = {}

	func primary_action() -> void:
		primary_actions += 1

	func open_feedback() -> void:
		feedback_actions += 1

	func set_playtest_options(
		level: int, weapon_damage_bonus: int, buff_enabled: bool
	) -> Dictionary:
		selected_options = {
			"buff_enabled": 1 if buff_enabled else 0,
			"level": level,
			"weapon_damage_bonus": weapon_damage_bonus,
		}
		return {"ok": true}


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var controller := RecordingController.new()
	get_root().add_child(controller)
	var view := StatCompositionView.new()
	get_root().add_child(view)
	await process_frame
	view.bind(controller)
	controller.view_state_changed.emit(_state("ready"))
	await process_frame
	var level := view.find_child("StatLevel", true, false) as HSlider
	var weapon := view.find_child("WeaponDamageBonus", true, false) as HSlider
	var buff := view.find_child("DamageBuff", true, false) as CheckButton
	_expect(level != null and weapon != null and buff != null, "player settings are visible")
	if weapon != null:
		weapon.value = 18
	await process_frame
	_expect(
		controller.selected_options
		== {"buff_enabled": 1, "level": 3, "weapon_damage_bonus": 18},
		"setting edits reach Content",
	)
	var action := view.find_child("PrimaryAction", true, false) as Button
	_expect(action != null and not action.disabled, "Attack is available")
	if action != null:
		action.pressed.emit()
	_expect(controller.primary_actions == 1, "the UI submits Attack")
	var resolved := _state("ready")
	resolved["attack_count"] = 1
	resolved["target_health"] = 60
	resolved["last_attack"] = {
		"capped": true,
		"metrics": {
			"attack_damage": 60,
			"build_damage": 18,
			"damage_dealt": 60,
			"effect_damage": 12,
			"pre_buff_damage": 50,
			"progression_damage": 12,
			"target_health": 60,
		},
	}
	controller.view_state_changed.emit(resolved)
	await process_frame
	var result := view.find_child("AttackResult", true, false) as Label
	var badge := view.find_child("MaximumBadge", true, false) as Label
	_expect(
		result != null and result.text == "Attack Damage 60. Dealt 60 damage. Dummy HP: 60.",
		"the result uses direct player wording",
	)
	_expect(badge != null and badge.text == "MAX 60 REACHED", "the cap is explicit")
	var health := view.find_child("DummyHealth", true, false) as ProgressBar
	_expect(_bar_color(health) == Color("d64545"), "the HP bar uses the red gameplay color")
	var defeated := resolved.duplicate(true)
	defeated["phase"] = "defeated"
	defeated["target_health"] = 0
	controller.view_state_changed.emit(defeated)
	await process_frame
	var feedback := view.find_child("OpenStatFeedback", true, false) as Button
	_expect(feedback != null and feedback.visible, "defeat offers a separate feedback action")
	if feedback != null:
		feedback.pressed.emit()
	_expect(controller.feedback_actions == 1, "the UI opens feedback separately")
	if action != null:
		action.pressed.emit()
	_expect(controller.primary_actions == 2, "the terminal primary action offers Restart")
	view.queue_free()
	controller.queue_free()
	_finish()


func _state(phase_name: String) -> Dictionary:
	return {
		"attack_count": 0,
		"phase": phase_name,
		"rules": {
			"base_damage": 20,
			"buff_percent": 25,
			"damage_per_level": 4,
			"maximum_damage": 60,
		},
		"setting_contracts": {
			"buff_enabled": {"minimum": 0, "maximum": 1, "value": 1},
			"level": {"minimum": 1, "maximum": 10, "value": 3},
			"weapon_damage_bonus": {"minimum": 0, "maximum": 20, "value": 8},
		},
		"settings": {"buff_enabled": 1, "level": 3, "weapon_damage_bonus": 8},
		"target_health": 120,
		"target_max_health": 120,
	}


func _bar_color(bar: ProgressBar) -> Color:
	if bar == null:
		return Color.TRANSPARENT
	var fill := bar.get_theme_stylebox("fill") as StyleBoxFlat
	return fill.bg_color if fill != null else Color.TRANSPARENT
