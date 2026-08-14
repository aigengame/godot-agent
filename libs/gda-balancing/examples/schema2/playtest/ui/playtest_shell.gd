extends Control

signal primary_action_requested
signal feedback_submitted(
	preference: String,
	stronger_choice: String,
	change_clarity: String,
	notes: String,
)

var _built := false
var _feature_content: VBoxContainer
var _title_label: Label
var _subtitle_label: Label
var _progress_label: Label
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
	_ensure_built()


func setup(
	title: String,
	subtitle: String,
	stronger_question: String,
	clarity_question: String,
) -> void:
	_ensure_built()
	_title_label.text = title
	_subtitle_label.text = subtitle
	_build_feedback_panel(stronger_question, clarity_question)


func feature_content() -> VBoxContainer:
	_ensure_built()
	return _feature_content


func show_play(progress: String, instruction: String, action: String) -> void:
	_title_label.visible = true
	_subtitle_label.visible = true
	_progress_label.visible = true
	_progress_label.text = progress
	_feature_content.visible = true
	_instruction.text = instruction
	_instruction.modulate = Color("c6d2e5")
	_primary_button.visible = true
	_primary_button.disabled = false
	_primary_button.text = action
	_feedback_panel.visible = false
	_feedback_status.text = ""
	_input_hint.text = "Mouse: click the action button    Keyboard: Space or Enter"


func show_feedback() -> void:
	_title_label.visible = false
	_subtitle_label.visible = false
	_progress_label.visible = false
	_feature_content.visible = false
	_instruction.text = "Your experience is the result."
	_primary_button.visible = false
	_feedback_panel.visible = true
	_feedback_status.text = ""
	_input_hint.text = "Mouse: choose and save    Keyboard: Ctrl+Enter saves the defaults"


func show_error(message: String) -> void:
	_instruction.text = message
	_instruction.modulate = Color("ff8a8a")
	_primary_button.disabled = true


func show_feedback_saved(payload: Dictionary, path: String) -> void:
	DisplayServer.clipboard_set(JSON.stringify(payload, "\t"))
	_feedback_status.text = "Feedback saved and copied · %s" % path


func _unhandled_key_input(event: InputEvent) -> void:
	if not event.pressed or event.echo:
		return
	if (
		_feedback_panel.visible
		and event.ctrl_pressed
		and event.keycode in [KEY_ENTER, KEY_KP_ENTER]
	):
		get_viewport().set_input_as_handled()
		_submit_feedback()
	elif (
		_feedback_panel.visible == false
		and event.keycode in [KEY_SPACE, KEY_ENTER, KEY_KP_ENTER]
	):
		get_viewport().set_input_as_handled()
		primary_action_requested.emit()


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
			primary_action_requested.emit()
		elif (
			_feedback_panel.visible
			and _save_feedback_button.get_global_rect().has_point(event.position)
		):
			get_viewport().set_input_as_handled()
			_submit_feedback()


func _ensure_built() -> void:
	if _built:
		return
	_built = true
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

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

	_title_label = _make_label("PLAYTEST", 34, Color("e9f2ff"))
	column.add_child(_title_label)
	_subtitle_label = _make_label("", 18, Color("91a6c7"))
	column.add_child(_subtitle_label)
	_progress_label = _make_label("Trial", 17, Color("59d7c6"))
	column.add_child(_progress_label)

	_feature_content = VBoxContainer.new()
	_feature_content.name = "FeatureContent"
	_feature_content.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_feature_content.add_theme_constant_override("separation", 14)
	column.add_child(_feature_content)

	_instruction = _make_label("", 18, Color("c6d2e5"))
	_instruction.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_instruction)

	_primary_button = Button.new()
	_primary_button.name = "PrimaryAction"
	_primary_button.custom_minimum_size = Vector2(320, 58)
	_primary_button.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_primary_button.add_theme_font_size_override("font_size", 20)
	_primary_button.pressed.connect(primary_action_requested.emit)
	column.add_child(_primary_button)

	_feedback_panel = _make_panel(Color("16243a"))
	_feedback_panel.name = "FeedbackPanel"
	_feedback_panel.visible = false
	column.add_child(_feedback_panel)

	_feedback_status = _make_label("", 15, Color("59d7c6"))
	_feedback_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_feedback_status)

	_input_hint = _make_label("", 14, Color("7287a8"))
	_input_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_input_hint)


func _build_feedback_panel(stronger_question: String, clarity_question: String) -> void:
	var column := _panel_column(_feedback_panel)
	var heading := _make_label("How did the two trials feel?", 24, Color("ffffff"))
	heading.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(heading)
	_preference = _add_question(column, "Which trial did you prefer?")
	_stronger = _add_question(column, stronger_question)
	_clarity = _add_question(
		column,
		clarity_question,
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
	_save_feedback_button.pressed.connect(_submit_feedback)
	column.add_child(_save_feedback_button)


func _submit_feedback() -> void:
	feedback_submitted.emit(
		_preference.get_item_text(_preference.selected),
		_stronger.get_item_text(_stronger.selected),
		_clarity.get_item_text(_clarity.selected),
		_notes.text,
	)


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
