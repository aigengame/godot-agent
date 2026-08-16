extends SceneTree

const WAIT_TIMEOUT_MSEC := 60000

var _failures: Array[String] = []


func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var main_scene: PackedScene = load("res://main.tscn")
	var main := main_scene.instantiate()
	get_root().add_child(main)
	var view: Control = main.get_node("RewardRunView")
	var controller: Node = main.get_node("RewardRunController")
	var action := view.find_child("PrimaryAction", true, false) as Button
	var frequency := view.find_child("RewardFrequency", true, false) as Range
	_expect(action != null and frequency != null, "main scene exposes player controls")
	var prepared := await _wait_for_phase(view, "choose_frequency")
	_expect(prepared, "main bootstrap reaches the first live trial")
	if not prepared:
		await controller.shutdown()
		main.queue_free()
		_finish()
		return

	frequency.value = 5
	action.pressed.emit()
	_expect(await _wait_for_phase(view, "before_fight"), "first live trial starts")
	await _complete_trial(view, action, 1)
	action.pressed.emit()
	_expect(
		await _wait_for_phase(view, "choose_frequency"),
		"UI returns to the later revision control",
	)

	frequency.value = 2
	action.pressed.emit()
	_expect(await _wait_for_phase(view, "before_fight"), "later live trial starts")
	await _complete_trial(view, action, 3)
	action.pressed.emit()
	_expect(await _wait_for_phase(view, "feedback"), "two live trials reach feedback")

	var save := view.find_child("SaveFeedback", true, false) as Button
	_expect(save != null, "feedback action is available")
	if save != null:
		save.pressed.emit()
		await process_frame
	_expect(not controller.last_feedback_path.is_empty(), "feedback saves through main")
	var absolute_feedback_path := ProjectSettings.globalize_path(
		"user://reward_run_feedback.json"
	)
	_expect(
		_view_contains_text(view, absolute_feedback_path),
		"feedback status shows the absolute saved file path",
	)
	await controller.shutdown()
	main.queue_free()
	_finish()


func _complete_trial(view: Control, action: Button, second_hits: int) -> void:
	for unused in 3:
		action.pressed.emit()
		await process_frame
	_expect(await _wait_for_phase(view, "reward_ready"), "reward is revealed")
	action.pressed.emit()
	_expect(await _wait_for_phase(view, "after_fight"), "reward is equipped")
	for unused in second_hits:
		action.pressed.emit()
		await process_frame
	_expect(await _wait_for_phase(view, "run_complete"), "trial is complete")


func _wait_for_phase(view: Control, expected: String) -> bool:
	var deadline := Time.get_ticks_msec() + WAIT_TIMEOUT_MSEC
	while Time.get_ticks_msec() < deadline:
		if view._current_phase == expected:
			return true
		await process_frame
	return false


func _expect(condition: bool, message: String) -> void:
	if not condition:
		_failures.append(message)


func _view_contains_text(view: Control, expected: String) -> bool:
	for node in view.find_children("*", "Label", true, false):
		var label := node as Label
		if label != null and label.text.contains(expected):
			return true
	return false


func _finish() -> void:
	if _failures.is_empty():
		print(JSON.stringify({"passed": 15, "status": "passed"}))
		quit(0)
		return
	for failure in _failures:
		push_error(failure)
	quit(1)
