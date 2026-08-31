extends "res://tests/playtest_test_case.gd"

const WAIT_TIMEOUT_MSEC := 60000


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var main_scene: PackedScene = load("res://apps/stat_composition/main.tscn")
	var main := main_scene.instantiate()
	get_root().add_child(main)
	var view: Control = main.get_node("StatCompositionView")
	var controller: Node = main.get_node("StatCompositionController")
	var action := view.find_child("PrimaryAction", true, false) as Button
	var weapon := view.find_child("WeaponDamageBonus", true, false) as HSlider
	_expect(action != null and weapon != null, "main scene exposes Attack and settings")
	var prepared := await _wait_for_state(controller, 0, "ready")
	_expect(prepared, "main bootstrap reaches the first attack")
	if not prepared:
		await controller.shutdown()
		main.queue_free()
		_finish()
		return

	action.pressed.emit()
	_expect(await _wait_for_state(controller, 1, "ready"), "the default revision resolves")
	weapon.value = 18
	await process_frame
	action.pressed.emit()
	_expect(await _wait_for_state(controller, 2, "ready"), "the edited capped revision resolves")
	action.pressed.emit()
	_expect(await _wait_for_state(controller, 3, "defeated"), "the dummy is defeated")
	_expect(controller.current_state()["last_attack"]["capped"] == true, "the played path reaches the cap")
	var feedback := view.find_child("OpenStatFeedback", true, false) as Button
	_expect(feedback != null, "feedback action is available")
	if feedback != null:
		feedback.pressed.emit()
	await process_frame
	var save := view.find_child("SaveFeedback", true, false) as Button
	_expect(save != null, "feedback can be saved")
	if save != null:
		save.pressed.emit()
		await process_frame
	_expect(not controller.last_feedback_path.is_empty(), "feedback saves through main")
	var absolute_feedback_path := ProjectSettings.globalize_path(
		"user://rpg_stat_composition_feedback.json"
	)
	_expect(
		_view_contains_text(view, absolute_feedback_path),
		"feedback status shows the absolute saved file path",
	)
	await controller.shutdown()
	main.queue_free()
	_finish()


func _wait_for_state(controller: Node, count: int, phase_name: String) -> bool:
	var deadline := Time.get_ticks_msec() + WAIT_TIMEOUT_MSEC
	while Time.get_ticks_msec() < deadline:
		var state: Dictionary = controller.current_state()
		if state.get("attack_count") == count and state.get("phase") == phase_name:
			return true
		if state.get("phase") == "retry":
			return false
		await process_frame
	return false


func _view_contains_text(view: Control, expected: String) -> bool:
	for node in view.find_children("*", "Label", true, false):
		var label := node as Label
		if label != null and label.text.contains(expected):
			return true
	return false
