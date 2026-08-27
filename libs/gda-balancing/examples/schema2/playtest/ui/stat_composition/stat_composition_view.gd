class_name StatCompositionView
extends Control

const PlaytestShell = preload("res://ui/playtest_shell.gd")
const StatCompositionController = preload(
	"res://content/stat_composition/stat_composition_controller.gd"
)
const ENGLISH_TRANSLATION = preload(
	"res://ui/stat_composition/localization/stat_composition.en.tres"
)
const CHINESE_TRANSLATION = preload(
	"res://ui/stat_composition/localization/stat_composition.zh_CN.tres"
)
const CLARITY_KEYS: Array[String] = [
	"STAT_CLARITY_5", "STAT_CLARITY_4", "STAT_CLARITY_3", "STAT_CLARITY_2", "STAT_CLARITY_1"
]
const CLARITY_VALUES: Array[String] = ["5", "4", "3", "2", "1"]
const MAXIMUM_KEYS: Array[String] = [
	"STAT_MAXIMUM_YES", "STAT_MAXIMUM_UNSURE", "STAT_MAXIMUM_NO"
]
const MAXIMUM_VALUES: Array[String] = ["Yes", "Not sure", "No"]
const LEAST_CLEAR_KEYS: Array[String] = [
	"STAT_PART_LEVEL",
	"STAT_PART_WEAPON",
	"STAT_PART_BUFF",
	"STAT_PART_MAXIMUM",
	"STAT_PART_NOTHING",
]
const LEAST_CLEAR_VALUES: Array[String] = [
	"Level", "Weapon", "Damage Buff", "Maximum", "Nothing"
]
const HEALTH_COLOR := Color("d64545")
const RESOURCE_BACKGROUND_COLOR := Color("111d2d")

var _controller: StatCompositionController
var _shell: PlaytestShell
var _current_phase := ""
var _last_state: Dictionary = {}
var _rendering := false
var _shown_attack_count := 0
var _settings_panel: PanelContainer
var _level: HSlider
var _level_label: Label
var _level_value: Label
var _weapon: HSlider
var _weapon_label: Label
var _weapon_value: Label
var _buff: CheckButton
var _rules_label: Label
var _dummy_block: ColorRect
var _dummy_health: ProgressBar
var _dummy_health_label: Label
var _damage_float: Label
var _base_value: Label
var _progression_value: Label
var _build_value: Label
var _effect_value: Label
var _attack_value: Label
var _cap_label: Label
var _result_label: Label
var _feedback_action: Button
var _clarity_label: Label
var _maximum_label: Label
var _least_clear_label: Label
var _clarity: OptionButton
var _maximum: OptionButton
var _least_clear: OptionButton


func _ready() -> void:
	TranslationServer.add_translation(ENGLISH_TRANSLATION)
	TranslationServer.add_translation(CHINESE_TRANSLATION)
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_shell = PlaytestShell.new()
	_shell.name = "PlaytestShell"
	add_child(_shell)
	_shell.setup("STAT_APP_TITLE", "STAT_APP_SUBTITLE")
	_shell.primary_action_requested.connect(_on_primary_action)
	_shell.feedback_save_requested.connect(_on_feedback_save_requested)
	_shell.locale_changed.connect(_on_locale_changed)
	_build_training(_shell.feature_content())
	_build_feedback(_shell.feedback_content())


func bind(controller: StatCompositionController) -> void:
	_controller = controller
	_controller.view_state_changed.connect(_render)
	_controller.feedback_saved.connect(_on_feedback_saved)


func _build_training(content: VBoxContainer) -> void:
	var body := HBoxContainer.new()
	body.name = "TrainingLayout"
	body.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 20)
	content.add_child(body)
	_build_settings(body)
	_build_dummy(body)
	_result_label = _make_label("", 18, Color("ffd166"))
	_result_label.name = "AttackResult"
	_result_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	content.add_child(_result_label)
	_feedback_action = Button.new()
	_feedback_action.name = "OpenStatFeedback"
	_feedback_action.visible = false
	_feedback_action.pressed.connect(_on_open_feedback)
	content.add_child(_feedback_action)


func _build_settings(parent: HBoxContainer) -> void:
	_settings_panel = _make_panel(Color("16243a"))
	_settings_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(_settings_panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 12)
	_settings_panel.add_child(column)
	var heading := _make_label(tr("STAT_BUILD_HEADING"), 20, Color("87d9ff"))
	heading.name = "BuildHeading"
	column.add_child(heading)
	_level_label = _make_label("", 15, Color("dce7f7"))
	column.add_child(_level_label)
	var level_row := HBoxContainer.new()
	column.add_child(level_row)
	_level = HSlider.new()
	_level.name = "StatLevel"
	_level.step = 1
	_level.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_level.value_changed.connect(_on_setting_changed)
	level_row.add_child(_level)
	_level_value = _make_value_label()
	level_row.add_child(_level_value)
	_weapon_label = _make_label("", 15, Color("dce7f7"))
	column.add_child(_weapon_label)
	var weapon_row := HBoxContainer.new()
	column.add_child(weapon_row)
	_weapon = HSlider.new()
	_weapon.name = "WeaponDamageBonus"
	_weapon.step = 1
	_weapon.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_weapon.value_changed.connect(_on_setting_changed)
	weapon_row.add_child(_weapon)
	_weapon_value = _make_value_label()
	weapon_row.add_child(_weapon_value)
	_buff = CheckButton.new()
	_buff.name = "DamageBuff"
	_buff.toggled.connect(_on_buff_toggled)
	column.add_child(_buff)
	_rules_label = _make_label("", 15, Color("91a6c7"))
	_rules_label.name = "VisibleRules"
	column.add_child(_rules_label)
	var separator := HSeparator.new()
	column.add_child(separator)
	_add_breakdown_row(column, "STAT_BASE_DAMAGE", "BaseValue")
	_add_breakdown_row(column, "STAT_LEVEL_BONUS", "ProgressionValue")
	_add_breakdown_row(column, "STAT_WEAPON_BONUS", "BuildValue")
	_add_breakdown_row(column, "STAT_BUFF_DAMAGE", "EffectValue")
	_add_breakdown_row(column, "STAT_ATTACK_DAMAGE", "AttackValue", true)


func _add_breakdown_row(
	parent: VBoxContainer, key: String, value_name: String, emphasized: bool = false
) -> void:
	var row := HBoxContainer.new()
	parent.add_child(row)
	var label := _make_label(tr(key), 16 if not emphasized else 19, Color("dce7f7"))
	label.name = value_name + "Label"
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(label)
	var value := _make_label("—", 16 if not emphasized else 22, Color("59d7c6"))
	value.name = value_name
	row.add_child(value)
	match value_name:
		"BaseValue":
			_base_value = value
		"ProgressionValue":
			_progression_value = value
		"BuildValue":
			_build_value = value
		"EffectValue":
			_effect_value = value
		"AttackValue":
			_attack_value = value
			_cap_label = _make_label("", 14, Color("ffd166"))
			_cap_label.name = "MaximumBadge"
			parent.add_child(_cap_label)


func _build_dummy(parent: HBoxContainer) -> void:
	var panel := _make_panel(Color("321d2b"))
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 12)
	panel.add_child(column)
	var title := _make_label(tr("STAT_DUMMY"), 20, Color("ffb4c8"))
	title.name = "DummyHeading"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(title)
	_dummy_block = ColorRect.new()
	_dummy_block.name = "TrainingDummy"
	_dummy_block.color = Color("b74362")
	_dummy_block.custom_minimum_size = Vector2(220, 190)
	_dummy_block.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	column.add_child(_dummy_block)
	_damage_float = _make_label("", 28, Color("ffd166"))
	_damage_float.name = "FloatingDamage"
	_damage_float.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_damage_float.modulate.a = 0
	column.add_child(_damage_float)
	_dummy_health = ProgressBar.new()
	_dummy_health.name = "DummyHealth"
	_dummy_health.max_value = 120
	_dummy_health.value = 120
	_dummy_health.show_percentage = false
	_dummy_health.custom_minimum_size = Vector2(360, 24)
	_dummy_health.add_theme_stylebox_override(
		"background", _bar_style(RESOURCE_BACKGROUND_COLOR)
	)
	_dummy_health.add_theme_stylebox_override("fill", _bar_style(HEALTH_COLOR))
	column.add_child(_dummy_health)
	_dummy_health_label = _make_label("", 18, Color("ffffff"))
	_dummy_health_label.name = "DummyHealthLabel"
	_dummy_health_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_dummy_health_label)


func _build_feedback(content: VBoxContainer) -> void:
	_clarity_label = _make_label("", 15, Color("9fb0ca"))
	content.add_child(_clarity_label)
	_clarity = _make_options(CLARITY_KEYS, CLARITY_VALUES)
	content.add_child(_clarity)
	_maximum_label = _make_label("", 15, Color("9fb0ca"))
	content.add_child(_maximum_label)
	_maximum = _make_options(MAXIMUM_KEYS, MAXIMUM_VALUES)
	content.add_child(_maximum)
	_least_clear_label = _make_label("", 15, Color("9fb0ca"))
	content.add_child(_least_clear_label)
	_least_clear = _make_options(LEAST_CLEAR_KEYS, LEAST_CLEAR_VALUES)
	content.add_child(_least_clear)
	_refresh_translations()


func _render(state: Dictionary) -> void:
	_last_state = state.duplicate(true)
	_current_phase = str(state.get("phase", ""))
	if _current_phase == "feedback":
		_shell.show_feedback()
		return
	var settings: Dictionary = state.get("settings", {})
	var contracts: Dictionary = state.get("setting_contracts", {})
	_rendering = true
	if not contracts.is_empty():
		_level.min_value = float(contracts["level"]["minimum"])
		_level.max_value = float(contracts["level"]["maximum"])
		_weapon.min_value = float(contracts["weapon_damage_bonus"]["minimum"])
		_weapon.max_value = float(contracts["weapon_damage_bonus"]["maximum"])
	if not settings.is_empty():
		_level.value = float(settings["level"])
		_weapon.value = float(settings["weapon_damage_bonus"])
		_buff.button_pressed = bool(settings["buff_enabled"])
		_level_value.text = str(int(settings["level"]))
		_weapon_value.text = "+%d" % int(settings["weapon_damage_bonus"])
	_rendering = false
	var rules: Dictionary = state.get("rules", {})
	if not rules.is_empty():
		_rules_label.text = tr("STAT_VISIBLE_RULES") % [
			int(rules["base_damage"]),
			int(rules["damage_per_level"]),
			int(rules["buff_percent"]),
			int(rules["maximum_damage"]),
		]
	_dummy_health.max_value = float(state.get("target_max_health", 120))
	_dummy_health_label.text = tr("STAT_HEALTH") % [
		int(state.get("target_health", 120)), int(state.get("target_max_health", 120))
	]
	var editable := _current_phase == "ready"
	_level.editable = editable
	_weapon.editable = editable
	_buff.disabled = not editable
	_feedback_action.visible = _current_phase == "defeated"
	var progress := tr("STAT_ATTACK_COUNT") % int(state.get("attack_count", 0))
	match _current_phase:
		"preparing":
			_shell.show_play("", tr("STAT_PREPARING"), "")
		"ready":
			_shell.show_play(progress, tr("STAT_READY"), tr("STAT_ACTION_ATTACK"))
		"attacking":
			_shell.show_play(progress, tr("STAT_ATTACKING"), tr("STAT_ACTION_WAIT"), false)
		"retry":
			_shell.show_play(progress, tr("STAT_RETRY"), tr("STAT_ACTION_RETRY"))
		"defeated":
			_shell.show_play(progress, tr("STAT_DEFEATED"), tr("STAT_ACTION_RESTART"))
	_render_last_attack(state)


func _render_last_attack(state: Dictionary) -> void:
	var attack: Dictionary = state.get("last_attack", {})
	if attack.is_empty():
		return
	var metrics: Dictionary = attack["metrics"]
	var rules: Dictionary = state["rules"]
	_base_value.text = str(int(rules["base_damage"]))
	_progression_value.text = "+%d" % int(metrics["progression_damage"])
	_build_value.text = "+%d" % int(metrics["build_damage"])
	_effect_value.text = "+%d" % int(metrics["effect_damage"])
	_attack_value.text = str(int(metrics["attack_damage"]))
	_cap_label.text = (
		tr("STAT_MAXIMUM_REACHED") % int(rules["maximum_damage"])
		if attack["capped"]
		else ""
	)
	_result_label.text = tr("STAT_ATTACK_RESULT") % [
		int(metrics["attack_damage"]),
		int(metrics["damage_dealt"]),
		int(metrics["target_health"]),
	]
	var attack_count := int(state.get("attack_count", 0))
	if attack_count > _shown_attack_count:
		_shown_attack_count = attack_count
		_animate_hit(int(metrics["damage_dealt"]), int(metrics["target_health"]))


func _animate_hit(damage: int, target_health: int) -> void:
	var health_tween := create_tween()
	health_tween.tween_property(_dummy_health, "value", float(target_health), 0.25)
	_dummy_block.pivot_offset = _dummy_block.size * 0.5
	var hit_tween := create_tween()
	hit_tween.tween_property(_dummy_block, "position:x", _dummy_block.position.x + 12, 0.05)
	hit_tween.tween_property(_dummy_block, "position:x", _dummy_block.position.x - 12, 0.05)
	hit_tween.tween_property(_dummy_block, "position:x", _dummy_block.position.x, 0.08)
	_damage_float.text = "-%d" % damage
	_damage_float.modulate.a = 1
	_damage_float.position.y += 8
	var float_tween := create_tween()
	float_tween.tween_property(_damage_float, "position:y", _damage_float.position.y - 20, 0.3)
	float_tween.parallel().tween_property(_damage_float, "modulate:a", 0.0, 0.3)


func _on_primary_action() -> void:
	if _controller != null:
		_controller.primary_action()


func _on_open_feedback() -> void:
	if _controller != null:
		_controller.open_feedback()


func _on_setting_changed(_value: float) -> void:
	_submit_settings()


func _on_buff_toggled(_enabled: bool) -> void:
	_submit_settings()


func _submit_settings() -> void:
	if _rendering or _controller == null:
		return
	_controller.set_playtest_options(
		int(_level.value), int(_weapon.value), _buff.button_pressed
	)


func _on_feedback_save_requested(notes: String) -> void:
	if _controller != null:
		_controller.submit_feedback(
			_selected_value(_clarity),
			_selected_value(_maximum),
			_selected_value(_least_clear),
			notes,
		)


func _on_feedback_saved(payload: Dictionary, path: String) -> void:
	_shell.show_feedback_saved(payload, path)


func _on_locale_changed(_locale_id: String) -> void:
	_refresh_translations()
	if not _last_state.is_empty():
		_render(_last_state)


func _refresh_translations() -> void:
	if _level_label == null:
		return
	_level_label.text = tr("STAT_LEVEL")
	_weapon_label.text = tr("STAT_WEAPON_DAMAGE")
	_buff.text = tr("STAT_DAMAGE_BUFF")
	_feedback_action.text = tr("STAT_ACTION_FEEDBACK")
	_clarity_label.text = tr("STAT_FEEDBACK_CLARITY")
	_maximum_label.text = tr("STAT_FEEDBACK_MAXIMUM")
	_least_clear_label.text = tr("STAT_FEEDBACK_LEAST_CLEAR")
	_populate_options(_clarity, CLARITY_KEYS, CLARITY_VALUES)
	_populate_options(_maximum, MAXIMUM_KEYS, MAXIMUM_VALUES)
	_populate_options(_least_clear, LEAST_CLEAR_KEYS, LEAST_CLEAR_VALUES)


func _make_options(keys: Array[String], values: Array[String]) -> OptionButton:
	var options := OptionButton.new()
	_populate_options(options, keys, values)
	return options


func _populate_options(
	options: OptionButton, keys: Array[String], values: Array[String]
) -> void:
	var selected_value := _selected_value(options)
	options.clear()
	for index in range(keys.size()):
		options.add_item(tr(keys[index]))
		options.set_item_metadata(index, values[index])
		if values[index] == selected_value:
			options.selected = index
	if selected_value.is_empty():
		options.selected = 0


func _selected_value(options: OptionButton) -> String:
	if options != null and options.item_count > 0 and options.selected >= 0:
		return str(options.get_item_metadata(options.selected))
	return ""


func _make_value_label() -> Label:
	var label := _make_label("", 18, Color("59d7c6"))
	label.custom_minimum_size.x = 54
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	return label


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


func _bar_style(color: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.corner_radius_top_left = 4
	style.corner_radius_top_right = 4
	style.corner_radius_bottom_left = 4
	style.corner_radius_bottom_right = 4
	return style
