extends "res://tests/playtest_test_case.gd"

const WAIT_TIMEOUT_MSEC := 60000


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var scene: PackedScene = load("res://apps/periodic_effect/main.tscn")
	var main := scene.instantiate()
	get_root().add_child(main)
	var view: Control = main.get_node("PeriodicEffectView")
	var controller: Node = main.get_node("PeriodicEffectController")
	var action := view.find_child("PrimaryAction", true, false) as Button
	_expect(action != null, "Periodic Effect main exposes the player action")
	_expect(await _wait_for_phase(view, "ready"), "Periodic Effect main reaches first trial")
	await _play_trial(view, action)
	action.pressed.emit()
	_expect(await _wait_for_phase(view, "ready"), "Periodic Effect main reaches later trial")
	await _play_trial(view, action)
	action.pressed.emit()
	_expect(await _wait_for_phase(view, "feedback"), "Periodic Effect main reaches feedback")
	var save := view.find_child("SaveFeedback", true, false) as Button
	_expect(save != null, "Periodic Effect feedback action is available")
	if save != null:
		save.pressed.emit()
		await process_frame
	_expect(not controller.last_feedback_path.is_empty(), "Effect feedback saves through main")
	var absolute_path := ProjectSettings.globalize_path(
		"user://rpg_periodic_effect_feedback.json"
	)
	_expect(_view_contains_text(view, absolute_path), "Effect shows the absolute feedback path")
	await controller.shutdown()
	main.queue_free()
	_finish()


func _play_trial(view: Control, action: Button) -> void:
	action.pressed.emit()
	_expect(await _wait_for_phase(view, "timeline_step"), "complete revision starts trial")
	for expected in ["pulse", "attack", "pulse", "expire"]:
		action.pressed.emit()
		_expect(await _wait_for_lifecycle_phase(view, expected), "Effect presents %s" % expected)
	action.pressed.emit()
	_expect(await _wait_for_phase(view, "trial_complete"), "Effect trial completes")


func _wait_for_phase(view: Control, expected: String) -> bool:
	var deadline := Time.get_ticks_msec() + WAIT_TIMEOUT_MSEC
	while Time.get_ticks_msec() < deadline:
		if view._current_phase == expected:
			return true
		await process_frame
	return false


func _wait_for_lifecycle_phase(view: Control, expected: String) -> bool:
	var deadline := Time.get_ticks_msec() + WAIT_TIMEOUT_MSEC
	while Time.get_ticks_msec() < deadline:
		if view._last_state.get("lifecycle_phase") == expected:
			return true
		await process_frame
	return false


func _view_contains_text(view: Control, expected: String) -> bool:
	for node in view.find_children("*", "Label", true, false):
		var label := node as Label
		if label != null and label.text.contains(expected):
			return true
	return false
