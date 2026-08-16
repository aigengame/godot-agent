extends Control

signal primary_action_requested
signal locale_changed(locale_id: String)
signal feedback_submitted(
	preference: String,
	stronger_choice: String,
	change_clarity: String,
	notes: String,
)

const PlaytestPreferences = preload("res://ui/playtest_preferences.gd")
const TRIAL_OPTION_KEYS: Array[String] = ["TRIAL_1", "TRIAL_2", "NO_DIFFERENCE"]
const TRIAL_OPTION_VALUES: Array[String] = ["Trial 1", "Trial 2", "No difference"]
const CLARITY_OPTION_KEYS: Array[String] = ["VERY_CLEAR", "MOSTLY_CLEAR", "UNCLEAR"]
const CLARITY_OPTION_VALUES: Array[String] = ["Very clear", "Mostly clear", "Unclear"]

var _built := false
var _preferences := PlaytestPreferences.new()
var _feature_content: VBoxContainer
var _resolution_label: Label
var _language_label: Label
var _resolution_picker: OptionButton
var _language_picker: OptionButton
var _title_label: Label
var _subtitle_label: Label
var _progress_label: Label
var _instruction: Label
var _primary_button: Button
var _feedback_panel: PanelContainer
var _feedback_heading: Label
var _preference_label: Label
var _stronger_label: Label
var _clarity_label: Label
var _preference: OptionButton
var _stronger: OptionButton
var _clarity: OptionButton
var _notes_label: Label
var _notes: TextEdit
var _save_feedback_button: Button
var _feedback_status: Label
var _input_hint: Label
var _title_key := ""
var _subtitle_key := ""
var _stronger_question_key := ""
var _clarity_question_key := ""
var _mode := "play"
var _feedback_path := ""


func _ready() -> void:
	_preferences.install_translations()
	_preferences.apply_locale(_preferences.default_locale())
	_ensure_built()
	_preferences.apply_resolution(get_window(), _preferences.default_resolution_id())
	_refresh_translations()


func setup(
	title_key: String,
	subtitle_key: String,
	stronger_question_key: String,
	clarity_question_key: String,
) -> void:
	_ensure_built()
	_title_key = title_key
	_subtitle_key = subtitle_key
	_stronger_question_key = stronger_question_key
	_clarity_question_key = clarity_question_key
	_build_feedback_panel()
	_refresh_translations()


func feature_content() -> VBoxContainer:
	_ensure_built()
	return _feature_content


func show_play(
	progress: String,
	instruction: String,
	action: String,
	action_enabled: bool = true,
) -> void:
	_mode = "play"
	_title_label.visible = true
	_subtitle_label.visible = true
	_progress_label.visible = true
	_progress_label.text = progress
	_feature_content.visible = true
	_instruction.text = instruction
	_instruction.modulate = Color("c6d2e5")
	_primary_button.visible = not action.is_empty()
	_primary_button.disabled = not action_enabled
	_primary_button.text = action
	_feedback_panel.visible = false
	_feedback_status.text = ""
	_input_hint.text = tr("MOUSE_PLAY_HINT")


func show_feedback() -> void:
	_mode = "feedback"
	_title_label.visible = false
	_subtitle_label.visible = false
	_progress_label.visible = false
	_feature_content.visible = false
	_instruction.text = tr("FEEDBACK_RESULT")
	_primary_button.visible = false
	_feedback_panel.visible = true
	_feedback_status.text = ""
	_input_hint.text = tr("MOUSE_FEEDBACK_HINT")


func show_error(message: String) -> void:
	_mode = "error"
	_instruction.text = message
	_instruction.modulate = Color("ff8a8a")
	_primary_button.disabled = true


func show_feedback_saved(payload: Dictionary, path: String) -> void:
	DisplayServer.clipboard_set(JSON.stringify(payload, "\t"))
	_feedback_path = path
	_feedback_status.text = tr("FEEDBACK_SAVED") % path


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
	_build_settings_row(column)

	_title_label = _make_label("", 34, Color("e9f2ff"))
	column.add_child(_title_label)
	_subtitle_label = _make_label("", 18, Color("91a6c7"))
	column.add_child(_subtitle_label)
	_progress_label = _make_label("", 17, Color("59d7c6"))
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
	_refresh_translations()


func _build_settings_row(column: VBoxContainer) -> void:
	var row := HBoxContainer.new()
	row.name = "PlayerSettings"
	row.add_theme_constant_override("separation", 10)
	column.add_child(row)

	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(spacer)

	_resolution_label = _make_label("", 14, Color("91a6c7"))
	_resolution_label.autowrap_mode = TextServer.AUTOWRAP_OFF
	_resolution_label.custom_minimum_size = Vector2(84, 36)
	_resolution_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	row.add_child(_resolution_label)
	_resolution_picker = OptionButton.new()
	_resolution_picker.name = "Resolution"
	_resolution_picker.custom_minimum_size = Vector2(132, 36)
	_resolution_picker.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	for option in _preferences.resolution_options():
		var index := _resolution_picker.item_count
		_resolution_picker.add_item(str(option["label"]))
		_resolution_picker.set_item_metadata(index, option["id"])
		if option["id"] == _preferences.default_resolution_id():
			_resolution_picker.selected = index
	_resolution_picker.item_selected.connect(_on_resolution_selected)
	row.add_child(_resolution_picker)

	_language_label = _make_label("", 14, Color("91a6c7"))
	_language_label.autowrap_mode = TextServer.AUTOWRAP_OFF
	_language_label.custom_minimum_size = Vector2(72, 36)
	_language_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	row.add_child(_language_label)
	_language_picker = OptionButton.new()
	_language_picker.name = "Language"
	_language_picker.custom_minimum_size = Vector2(132, 36)
	_language_picker.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	for option in _preferences.locale_options():
		var index := _language_picker.item_count
		_language_picker.add_item(str(option["label"]))
		_language_picker.set_item_metadata(index, option["id"])
		if option["id"] == _preferences.default_locale():
			_language_picker.selected = index
	_language_picker.item_selected.connect(_on_language_selected)
	row.add_child(_language_picker)


func _build_feedback_panel() -> void:
	var column := _panel_column(_feedback_panel)
	_feedback_heading = _make_label("", 24, Color("ffffff"))
	_feedback_heading.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_feedback_heading)
	_preference_label = _make_label("", 15, Color("9fb0ca"))
	column.add_child(_preference_label)
	_preference = _make_options(TRIAL_OPTION_KEYS, TRIAL_OPTION_VALUES)
	column.add_child(_preference)
	_stronger_label = _make_label("", 15, Color("9fb0ca"))
	column.add_child(_stronger_label)
	_stronger = _make_options(TRIAL_OPTION_KEYS, TRIAL_OPTION_VALUES)
	column.add_child(_stronger)
	_clarity_label = _make_label("", 15, Color("9fb0ca"))
	column.add_child(_clarity_label)
	_clarity = _make_options(CLARITY_OPTION_KEYS, CLARITY_OPTION_VALUES)
	column.add_child(_clarity)
	_notes_label = _make_label("", 15, Color("9fb0ca"))
	column.add_child(_notes_label)
	_notes = TextEdit.new()
	_notes.name = "Notes"
	_notes.custom_minimum_size = Vector2(640, 74)
	column.add_child(_notes)
	_save_feedback_button = Button.new()
	_save_feedback_button.name = "SaveFeedback"
	_save_feedback_button.custom_minimum_size = Vector2(280, 48)
	_save_feedback_button.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_save_feedback_button.pressed.connect(_submit_feedback)
	column.add_child(_save_feedback_button)
	_refresh_translations()


func _submit_feedback() -> void:
	feedback_submitted.emit(
		str(_preference.get_item_metadata(_preference.selected)),
		str(_stronger.get_item_metadata(_stronger.selected)),
		str(_clarity.get_item_metadata(_clarity.selected)),
		_notes.text,
	)


func _make_options(keys: Array[String], values: Array[String]) -> OptionButton:
	var options := OptionButton.new()
	_populate_options(options, keys, values, values.size() - 1)
	return options


func _populate_options(
	options: OptionButton,
	keys: Array[String],
	values: Array[String],
	default_index: int,
) -> void:
	var selected_value := ""
	if options.item_count > 0 and options.selected >= 0:
		selected_value = str(options.get_item_metadata(options.selected))
	options.clear()
	for index in range(keys.size()):
		options.add_item(tr(keys[index]))
		options.set_item_metadata(index, values[index])
		if values[index] == selected_value:
			options.selected = index
	if selected_value.is_empty():
		options.selected = default_index


func _on_resolution_selected(index: int) -> void:
	var resolution_id := str(_resolution_picker.get_item_metadata(index))
	_preferences.apply_resolution(get_window(), resolution_id)


func _on_language_selected(index: int) -> void:
	var locale_id := str(_language_picker.get_item_metadata(index))
	if _preferences.apply_locale(locale_id):
		_refresh_translations()
		locale_changed.emit(locale_id)


func _notification(what: int) -> void:
	if what == NOTIFICATION_TRANSLATION_CHANGED and _built:
		_refresh_translations()


func _refresh_translations() -> void:
	if not _built:
		return
	_resolution_label.text = tr("SETTINGS_RESOLUTION")
	_language_label.text = tr("SETTINGS_LANGUAGE")
	_title_label.text = tr(_title_key) if not _title_key.is_empty() else tr("PLAYTEST_LABEL")
	_subtitle_label.text = tr(_subtitle_key) if not _subtitle_key.is_empty() else ""
	if _progress_label.text.is_empty():
		_progress_label.text = tr("TRIAL_LABEL")
	if _feedback_heading != null:
		_feedback_heading.text = tr("FEEDBACK_HEADING")
		_preference_label.text = tr("FEEDBACK_PREFERENCE")
		_stronger_label.text = tr(_stronger_question_key)
		_clarity_label.text = tr(_clarity_question_key)
		_notes_label.text = tr("OPTIONAL_NOTES")
		_notes.placeholder_text = tr("NOTES_PLACEHOLDER")
		_save_feedback_button.text = tr("SAVE_COPY_FEEDBACK")
		_populate_options(_preference, TRIAL_OPTION_KEYS, TRIAL_OPTION_VALUES, 2)
		_populate_options(_stronger, TRIAL_OPTION_KEYS, TRIAL_OPTION_VALUES, 2)
		_populate_options(_clarity, CLARITY_OPTION_KEYS, CLARITY_OPTION_VALUES, 2)
	if _mode == "play":
		_input_hint.text = tr("MOUSE_PLAY_HINT")
	elif _mode == "feedback":
		_instruction.text = tr("FEEDBACK_RESULT")
		_input_hint.text = tr("MOUSE_FEEDBACK_HINT")
	if not _feedback_path.is_empty():
		_feedback_status.text = tr("FEEDBACK_SAVED") % _feedback_path


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
