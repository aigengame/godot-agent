extends "res://tests/playtest_test_case.gd"

const WAIT_TIMEOUT_MSEC := 60000


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var scene: PackedScene = load("res://apps/combat_cast/main.tscn")
	var main := scene.instantiate()
	get_root().add_child(main)
	var view: Control = main.get_node("CombatCastView")
	var controller: Node = main.get_node("CombatCastController")
	var action := view.find_child("PrimaryAction", true, false) as Button
	_expect(action != null, "Combat main exposes the player action")
	_expect(await _wait_for_phase(view, "ready"), "Combat main reaches the duel")
	for expected in [
		"player_resolved", "enemy_resolved", "player_resolved", "enemy_resolved", "victory"
	]:
		action.pressed.emit()
		_expect(await _wait_for_phase(view, expected), "Combat presents %s" % expected)
	var open_feedback := view.find_child("OpenCombatFeedback", true, false) as Button
	_expect(open_feedback != null and open_feedback.visible, "terminal duel offers feedback")
	if open_feedback != null:
		open_feedback.pressed.emit()
	_expect(await _wait_for_phase(view, "feedback"), "Combat enters feedback by player choice")
	var save := view.find_child("SaveFeedback", true, false) as Button
	_expect(save != null, "Combat feedback action is available")
	if save != null:
		save.pressed.emit()
		await process_frame
	_expect(not controller.last_feedback_path.is_empty(), "Combat feedback saves through main")
	var absolute_path := ProjectSettings.globalize_path(
		"user://rpg_combat_cast_feedback.json"
	)
	_expect(_view_contains_text(view, absolute_path), "Combat shows the absolute feedback path")
	await controller.shutdown()
	main.queue_free()
	_finish()
func _wait_for_phase(view: Control, expected: String) -> bool:
	var deadline := Time.get_ticks_msec() + WAIT_TIMEOUT_MSEC
	while Time.get_ticks_msec() < deadline:
		if view._current_phase == expected:
			return true
		await process_frame
	return false


func _view_contains_text(view: Control, expected: String) -> bool:
	for node in view.find_children("*", "Label", true, false):
		var label := node as Label
		if label != null and label.text.contains(expected):
			return true
	return false
