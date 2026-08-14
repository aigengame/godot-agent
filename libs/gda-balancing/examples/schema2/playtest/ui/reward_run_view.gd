extends Control

const RewardRunController = preload("res://content/reward_run/reward_run_controller.gd")

var _controller: RewardRunController
var _last_phase := ""

var _title_label: Label
var _subtitle_label: Label
var _progress_label: Label
var _arena: HBoxContainer
var _power_label: Label
var _target_label: Label
var _target_health: ProgressBar
var _target_block: ColorRect
var _player_block: ColorRect
var _reward_panel: PanelContainer
var _reward_name: Label
var _reward_detail: Label
var _instruction: Label
var _primary_button: Button
var _feedback_panel: PanelContainer
var _preference: OptionButton
var _stronger: OptionButton
var _clarity: OptionButton
var _notes: TextEdit
var _save_feedback_button: Button
var _feedback_status: Label
var _input_hint: Label


func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_build_interface()


func bind(controller: RewardRunController) -> void:
	_controller = controller
	_controller.view_state_changed.connect(_render)
	_controller.feedback_saved.connect(_on_feedback_saved)


func show_error(message: String) -> void:
	_instruction.text = message
	_instruction.modulate = Color("ff8a8a")
	_primary_button.disabled = true


func _unhandled_key_input(event: InputEvent) -> void:
	if not event.pressed or event.echo:
		return
	if (
		_feedback_panel.visible
		and event.ctrl_pressed
		and event.keycode in [KEY_ENTER, KEY_KP_ENTER]
	):
		get_viewport().set_input_as_handled()
		_on_save_feedback()
	elif (
		_feedback_panel.visible == false
		and event.keycode in [KEY_SPACE, KEY_ENTER, KEY_KP_ENTER]
	):
		get_viewport().set_input_as_handled()
		_on_primary_action()


func _input(event: InputEvent) -> void:
	if (
		event is InputEventMouseButton
		and event.button_index == MOUSE_BUTTON_LEFT
		and event.pressed
	):
		if (
			_primary_button.visible
			and _primary_button.get_global_rect().has_point(event.position)
		):
			get_viewport().set_input_as_handled()
			_on_primary_action()
		elif (
			_feedback_panel.visible
			and _save_feedback_button.get_global_rect().has_point(event.position)
		):
			get_viewport().set_input_as_handled()
			_on_save_feedback()


func _build_interface() -> void:
	var background := ColorRect.new()
	background.color = Color("09111f")
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(background)

	var margin := MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	margin.add_theme_constant_override("margin_left", 48)
	margin.add_theme_constant_override("margin_right", 48)
	margin.add_theme_constant_override("margin_top", 32)
	margin.add_theme_constant_override("margin_bottom", 32)
	add_child(margin)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 14)
	margin.add_child(column)

	_title_label = _make_label("REWARD RUN", 34, Color("e9f2ff"))
	column.add_child(_title_label)
	_subtitle_label = _make_label(
		"Defeat the target, equip what you find, and feel the difference.",
		18,
		Color("91a6c7"),
	)
	column.add_child(_subtitle_label)

	_progress_label = _make_label("Trial", 17, Color("59d7c6"))
	column.add_child(_progress_label)

	_arena = HBoxContainer.new()
	_arena.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_arena.add_theme_constant_override("separation", 18)
	column.add_child(_arena)

	var player_panel := _make_panel(Color("132942"))
	player_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_arena.add_child(player_panel)
	var player_column := _panel_column(player_panel)
	player_column.add_child(_make_label("YOU", 17, Color("87d9ff")))
	_player_block = ColorRect.new()
	_player_block.name = "PlayerBlock"
	_player_block.color = Color("2998d6")
	_player_block.custom_minimum_size = Vector2(180, 128)
	_player_block.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	player_column.add_child(_player_block)
	_power_label = _make_label("Power 10", 24, Color("ffffff"))
	_power_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	player_column.add_child(_power_label)

	var target_panel := _make_panel(Color("321d2b"))
	target_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_arena.add_child(target_panel)
	var target_column := _panel_column(target_panel)
	_target_label = _make_label("TRAINING TARGET", 17, Color("ffb4c8"))
	_target_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	target_column.add_child(_target_label)
	_target_block = ColorRect.new()
	_target_block.name = "TargetBlock"
	_target_block.color = Color("d95378")
	_target_block.custom_minimum_size = Vector2(180, 128)
	_target_block.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	target_column.add_child(_target_block)
	_target_health = ProgressBar.new()
	_target_health.name = "TargetHealth"
	_target_health.custom_minimum_size = Vector2(280, 24)
	_target_health.show_percentage = false
	target_column.add_child(_target_health)

	_reward_panel = _make_panel(Color("342b16"))
	_reward_panel.name = "RewardCard"
	_reward_panel.visible = false
	column.add_child(_reward_panel)
	var reward_column := _panel_column(_reward_panel)
	_reward_name = _make_label("Reward", 26, Color("ffd166"))
	_reward_name.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	reward_column.add_child(_reward_name)
	_reward_detail = _make_label("", 17, Color("f7e7ad"))
	_reward_detail.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	reward_column.add_child(_reward_detail)

	_instruction = _make_label("", 18, Color("c6d2e5"))
	_instruction.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_instruction)

	_primary_button = Button.new()
	_primary_button.name = "PrimaryAction"
	_primary_button.custom_minimum_size = Vector2(320, 58)
	_primary_button.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_primary_button.add_theme_font_size_override("font_size", 20)
	_primary_button.pressed.connect(_on_primary_action)
	column.add_child(_primary_button)

	_feedback_panel = _build_feedback_panel()
	_feedback_panel.visible = false
	column.add_child(_feedback_panel)

	_feedback_status = _make_label("", 15, Color("59d7c6"))
	_feedback_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_feedback_status)

	_input_hint = _make_label(
		"Mouse: click the action button    Keyboard: Space or Enter",
		14,
		Color("7287a8"),
	)
	_input_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_input_hint)


func _build_feedback_panel() -> PanelContainer:
	var panel := _make_panel(Color("16243a"))
	panel.name = "FeedbackPanel"
	var column := _panel_column(panel)
	var heading := _make_label("How did the two trials feel?", 24, Color("ffffff"))
	heading.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(heading)

	_preference = _add_question(column, "Which trial did you prefer?")
	_stronger = _add_question(column, "Which reward felt stronger?")
	_clarity = _add_question(
		column,
		"Was the equipment change clear?",
		["Very clear", "Mostly clear", "Unclear"],
	)
	column.add_child(_make_label("Optional notes", 15, Color("9fb0ca")))
	_notes = TextEdit.new()
	_notes.name = "Notes"
	_notes.custom_minimum_size = Vector2(640, 74)
	_notes.placeholder_text = "What surprised you? What would you change?"
	column.add_child(_notes)
	_save_feedback_button = Button.new()
	_save_feedback_button.name = "SaveFeedback"
	_save_feedback_button.text = "Save & Copy Feedback"
	_save_feedback_button.custom_minimum_size = Vector2(280, 48)
	_save_feedback_button.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_save_feedback_button.pressed.connect(_on_save_feedback)
	column.add_child(_save_feedback_button)
	return panel


func _add_question(
	column: VBoxContainer,
	question: String,
	answers: Array[String] = ["Trial 1", "Trial 2", "No difference"],
) -> OptionButton:
	column.add_child(_make_label(question, 15, Color("9fb0ca")))
	var options := OptionButton.new()
	for answer in answers:
		options.add_item(answer)
	options.selected = answers.size() - 1
	column.add_child(options)
	return options


func _render(state: Dictionary) -> void:
	var next_phase := str(state["phase"])
	if next_phase == "feedback":
		_show_feedback()
		_last_phase = next_phase
		return

	_feedback_panel.visible = false
	_input_hint.text = "Mouse: click the action button    Keyboard: Space or Enter"
	_title_label.visible = true
	_subtitle_label.visible = true
	_progress_label.visible = true
	_arena.visible = true
	_primary_button.visible = true
	_progress_label.text = "TRIAL %d OF %d" % [
		int(state["trial_index"]) + 1,
		int(state["trial_count"]),
	]
	_power_label.text = "Power %d" % int(state["power"])
	_target_health.max_value = float(state["target_max_health"])
	_target_health.value = float(state["target_health"])
	_target_label.text = "TARGET  %d / %d" % [
		int(state["target_health"]),
		int(state["target_max_health"]),
	]

	var reward: Dictionary = state["reward"]
	var build: Dictionary = state["build"]
	_reward_name.text = str(reward["name"])
	_reward_detail.text = "%s reward · Power %d → %d" % [
		str(reward["rarity"]).capitalize(),
		int(build["power_before"]),
		int(build["power_after"]),
	]
	_reward_panel.visible = next_phase in [
		"reward_ready", "after_fight", "run_complete"
	]

	match next_phase:
		"before_fight":
			_instruction.text = "Break the first target with your Training Blade."
			_primary_button.text = "STRIKE"
		"reward_ready":
			_instruction.text = "Target cleared. Equip your new reward."
			_primary_button.text = "EQUIP %s" % str(reward["name"]).to_upper()
		"after_fight":
			_instruction.text = "Now test the new build on a tougher target."
			_primary_button.text = "STRIKE WITH %s" % str(reward["name"]).to_upper()
		"run_complete":
			_instruction.text = "Trial complete. Continue when you are ready."
			_primary_button.text = (
				"COMPARE TRIALS"
				if int(state["trial_index"]) + 1 == int(state["trial_count"])
				else "START NEXT TRIAL"
			)

	if _last_phase == next_phase and next_phase in ["before_fight", "after_fight"]:
		_pulse_target()
	elif next_phase == "reward_ready":
		_reveal_reward()
	elif _last_phase == "reward_ready" and next_phase == "after_fight":
		_pulse_player()
	_last_phase = next_phase


func _show_feedback() -> void:
	_title_label.visible = false
	_subtitle_label.visible = false
	_progress_label.visible = false
	_arena.visible = false
	_instruction.text = "Your experience is the result."
	_primary_button.visible = false
	_reward_panel.visible = false
	_feedback_panel.visible = true
	_input_hint.text = "Mouse: choose and save    Keyboard: Ctrl+Enter saves the defaults"


func _on_primary_action() -> void:
	if _controller != null:
		_controller.primary_action()


func _on_save_feedback() -> void:
	if _controller == null:
		return
	_controller.submit_feedback(
		_preference.get_item_text(_preference.selected),
		_stronger.get_item_text(_stronger.selected),
		_clarity.get_item_text(_clarity.selected),
		_notes.text,
	)


func _on_feedback_saved(payload: Dictionary, path: String) -> void:
	DisplayServer.clipboard_set(JSON.stringify(payload, "\t"))
	_feedback_status.text = "Feedback saved and copied · %s" % path


func _pulse_target() -> void:
	var tween := create_tween()
	_target_block.modulate = Color("ffffff")
	tween.tween_property(_target_block, "modulate", Color("ffffff66"), 0.08)
	tween.tween_property(_target_block, "modulate", Color.WHITE, 0.16)


func _reveal_reward() -> void:
	_reward_panel.modulate = Color(1, 1, 1, 0)
	_reward_panel.scale = Vector2(0.92, 0.92)
	_reward_panel.pivot_offset = _reward_panel.size * 0.5
	var tween := create_tween().set_parallel(true)
	tween.tween_property(_reward_panel, "modulate", Color.WHITE, 0.25)
	tween.tween_property(_reward_panel, "scale", Vector2.ONE, 0.25).set_trans(
		Tween.TRANS_BACK
	)


func _pulse_player() -> void:
	_player_block.pivot_offset = _player_block.size * 0.5
	var tween := create_tween()
	tween.tween_property(_player_block, "scale", Vector2(1.12, 1.12), 0.12)
	tween.tween_property(_player_block, "scale", Vector2.ONE, 0.18)


func _make_label(text: String, size: int, color: Color) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", size)
	label.modulate = color
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	return label


func _make_panel(color: Color) -> PanelContainer:
	var panel := PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.corner_radius_top_left = 10
	style.corner_radius_top_right = 10
	style.corner_radius_bottom_left = 10
	style.corner_radius_bottom_right = 10
	style.content_margin_left = 22
	style.content_margin_right = 22
	style.content_margin_top = 18
	style.content_margin_bottom = 18
	panel.add_theme_stylebox_override("panel", style)
	return panel


func _panel_column(panel: PanelContainer) -> VBoxContainer:
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 10)
	panel.add_child(column)
	return column
