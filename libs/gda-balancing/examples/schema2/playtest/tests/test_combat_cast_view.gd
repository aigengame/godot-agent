extends "res://tests/playtest_test_case.gd"

const CombatCastController = preload(
	"res://content/combat_cast/combat_cast_controller.gd"
)
const CombatCastView = preload("res://ui/combat_cast/combat_cast_view.gd")

class RecordingController extends CombatCastController:
	var primary_actions := 0
	var feedback_actions := 0
	var selected_options: Dictionary = {}

	func primary_action() -> void:
		primary_actions += 1

	func open_feedback() -> void:
		feedback_actions += 1

	func set_playtest_options(spell_style: String, rival_strength: String) -> Dictionary:
		selected_options = {
			"rival_strength": rival_strength,
			"spell_style": spell_style,
		}
		return {"ok": true}


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var controller := RecordingController.new()
	get_root().add_child(controller)
	var view := CombatCastView.new()
	get_root().add_child(view)
	await process_frame
	view.bind(controller)
	controller.view_state_changed.emit({"phase": "preparing"})
	await process_frame
	var early_action := InputEventKey.new()
	early_action.pressed = true
	early_action.keycode = KEY_SPACE
	Input.parse_input_event(early_action)
	await process_frame
	_expect(controller.primary_actions == 0, "hidden Combat action ignores keyboard input")
	controller.view_state_changed.emit(
		{
			"combatants": {
				"enemy_health": 100,
				"enemy_mana": 30,
				"player_health": 100,
				"player_mana": 35,
			},
			"action_index": 0,
			"phase": "ready",
			"round": 1,
		}
	)
	await process_frame
	var spell_style := view.find_child("SpellStyle", true, false) as OptionButton
	var rival_strength := view.find_child("RivalStrength", true, false) as OptionButton
	_expect(spell_style != null and rival_strength != null, "Combat options are visible")
	if spell_style != null:
		spell_style.select(0)
		spell_style.item_selected.emit(0)
	_expect(
		controller.selected_options
		== {"rival_strength": "normal", "spell_style": "efficient"},
		"spell and rival options reach Content",
	)
	var action := view.find_child("PrimaryAction", true, false) as Button
	_expect(action != null and not action.disabled, "player can cast")
	if action != null:
		action.pressed.emit()
	_expect(controller.primary_actions == 1, "Combat UI submits the player action")
	var player_health := view.find_child("PlayerHealth", true, false) as ProgressBar
	var player_mana := view.find_child("PlayerMana", true, false) as ProgressBar
	var enemy_health := view.find_child("EnemyHealth", true, false) as ProgressBar
	var enemy_mana := view.find_child("EnemyMana", true, false) as ProgressBar
	_expect(player_health != null and enemy_health != null, "health bars are visible")
	_expect(player_mana != null and enemy_mana != null, "mana bars are visible")
	_expect(
		_bar_color(player_health) == Color("d64545")
		and _bar_color(enemy_health) == Color("d64545"),
		"health bars use the red gameplay color",
	)
	_expect(
		_bar_color(player_mana) == Color("3478d4")
		and _bar_color(enemy_mana) == Color("3478d4"),
		"mana bars use the blue gameplay color",
	)
	var health_label := view.find_child("PlayerHealthLabel", true, false) as Label
	var mana_label := view.find_child("PlayerManaLabel", true, false) as Label
	_expect(health_label != null and health_label.text == "HP", "health bar has a text label")
	_expect(mana_label != null and mana_label.text == "MP", "mana bar has a text label")
	controller.view_state_changed.emit(
		{
			"combatants": {
				"enemy_health": 63,
				"enemy_mana": 30,
				"player_health": 100,
				"player_mana": 26,
			},
			"action_index": 1,
			"damage": 37,
			"mana_cost": 9,
			"phase": "player_resolved",
			"round": 1,
		}
	)
	await process_frame
	var action_result := view.find_child("ActionResult", true, false) as Label
	_expect(
		action_result != null
		and action_result.text == "Your spell deals 37 damage and costs 9 MP.",
		"player action shows damage and mana cost",
	)
	controller.view_state_changed.emit(
		{
			"combatants": {
				"enemy_health": 63,
				"enemy_mana": 23,
				"player_health": 86,
				"player_mana": 26,
			},
			"action_index": 2,
			"damage": 14,
			"mana_cost": 7,
			"phase": "enemy_resolved",
			"round": 2,
		}
	)
	await process_frame
	_expect(
		action_result != null
		and action_result.text == "The counterattack deals 14 damage and costs 7 MP.",
		"enemy action shows damage and mana cost",
	)
	controller.view_state_changed.emit(
		{
			"action_index": 5,
			"combatants": {
				"enemy_health": 0,
				"enemy_mana": 16,
				"player_health": 72,
				"player_mana": 8,
			},
			"damage": 26,
			"mana_cost": 9,
			"phase": "victory",
			"round": 3,
		}
	)
	await process_frame
	var feedback := view.find_child("OpenCombatFeedback", true, false) as Button
	_expect(feedback != null and feedback.visible, "terminal state offers feedback")
	if feedback != null:
		feedback.pressed.emit()
	_expect(controller.feedback_actions == 1, "feedback is a distinct terminal choice")
	if action != null:
		action.pressed.emit()
	_expect(controller.primary_actions == 2, "terminal primary action offers restart")
	view.queue_free()
	controller.queue_free()
	_finish()


func _bar_color(bar: ProgressBar) -> Color:
	if bar == null:
		return Color.TRANSPARENT
	var fill := bar.get_theme_stylebox("fill") as StyleBoxFlat
	return fill.bg_color if fill != null else Color.TRANSPARENT
