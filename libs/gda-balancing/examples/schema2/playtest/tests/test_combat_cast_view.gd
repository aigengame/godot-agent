extends "res://tests/playtest_test_case.gd"

const CombatCastController = preload(
	"res://content/combat_cast/combat_cast_controller.gd"
)
const CombatCastView = preload("res://ui/combat_cast/combat_cast_view.gd")

class RecordingController extends CombatCastController:
	var primary_actions := 0

	func primary_action() -> void:
		primary_actions += 1


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
	controller.view_state_changed.emit({"phase": "preparing", "exchange_count": 2, "exchange_index": 0})
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
			"exchange_count": 2,
			"exchange_index": 0,
			"phase": "ready",
		}
	)
	await process_frame
	var action := view.find_child("PrimaryAction", true, false) as Button
	_expect(action != null and not action.disabled, "player can cast")
	if action != null:
		action.pressed.emit()
	_expect(controller.primary_actions == 1, "Combat UI submits the player action")
	_expect(view.find_child("PlayerHealth", true, false) != null, "player health is visible")
	_expect(view.find_child("EnemyMana", true, false) != null, "enemy mana is visible")
	view.queue_free()
	controller.queue_free()
	_finish()
