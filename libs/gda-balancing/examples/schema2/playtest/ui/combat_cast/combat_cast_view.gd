class_name CombatCastView
extends Control

const PlaytestShell = preload("res://ui/playtest_shell.gd")
const CombatCastController = preload(
	"res://content/combat_cast/combat_cast_controller.gd"
)
const ENGLISH_TRANSLATION = preload(
	"res://ui/combat_cast/localization/combat_cast.en.tres"
)
const CHINESE_TRANSLATION = preload(
	"res://ui/combat_cast/localization/combat_cast.zh_CN.tres"
)
const FEEL_KEYS: Array[String] = [
	"COMBAT_SPELL_SATISFYING", "COMBAT_SPELL_WEAK", "COMBAT_SPELL_COSTLY"
]
const FEEL_VALUES: Array[String] = ["Satisfying", "Too weak", "Too costly"]
const CLARITY_KEYS: Array[String] = [
	"COMBAT_VERY_CLEAR", "COMBAT_MOSTLY_CLEAR", "COMBAT_UNCLEAR"
]
const CLARITY_VALUES: Array[String] = ["Very clear", "Mostly clear", "Unclear"]
const TIMING_KEYS: Array[String] = [
	"COMBAT_TIMING_FAIR", "COMBAT_TIMING_FAST", "COMBAT_TIMING_UNCLEAR"
]
const TIMING_VALUES: Array[String] = ["Fair", "Too fast", "Unclear"]
const HEALTH_COLOR := Color("d64545")
const MANA_COLOR := Color("3478d4")
const RESOURCE_BACKGROUND_COLOR := Color("111d2d")
const SPELL_STYLE_KEYS: Array[String] = [
	"COMBAT_STYLE_EFFICIENT", "COMBAT_STYLE_BALANCED", "COMBAT_STYLE_POWERFUL"
]
const SPELL_STYLE_VALUES: Array[String] = ["efficient", "balanced", "powerful"]
const RIVAL_KEYS: Array[String] = ["COMBAT_RIVAL_NORMAL", "COMBAT_RIVAL_STRONG"]
const RIVAL_VALUES: Array[String] = ["normal", "strong"]

var _controller: CombatCastController
var _shell: PlaytestShell
var _current_phase := ""
var _last_phase := ""
var _last_state: Dictionary = {}
var _arena: HBoxContainer
var _player_block: ColorRect
var _enemy_block: ColorRect
var _player_health: ProgressBar
var _player_mana: ProgressBar
var _enemy_health: ProgressBar
var _enemy_mana: ProgressBar
var _player_stats: Label
var _enemy_stats: Label
var _damage_result: Label
var _feedback_action: Button
var _settings: HBoxContainer
var _spell_style: OptionButton
var _spell_style_label: Label
var _rival_strength: OptionButton
var _rival_strength_label: Label
var _preference_label: Label
var _readability_label: Label
var _timing_label: Label
var _preference: OptionButton
var _readability: OptionButton
var _timing: OptionButton


func _ready() -> void:
	TranslationServer.add_translation(ENGLISH_TRANSLATION)
	TranslationServer.add_translation(CHINESE_TRANSLATION)
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_shell = PlaytestShell.new()
	_shell.name = "PlaytestShell"
	add_child(_shell)
	_shell.setup("COMBAT_APP_TITLE", "COMBAT_APP_SUBTITLE")
	_shell.primary_action_requested.connect(_on_primary_action)
	_shell.feedback_save_requested.connect(_on_feedback_save_requested)
	_shell.locale_changed.connect(_on_locale_changed)
	_build_arena(_shell.feature_content())
	_build_feedback(_shell.feedback_content())


func bind(controller: CombatCastController) -> void:
	_controller = controller
	_controller.view_state_changed.connect(_render)
	_controller.feedback_saved.connect(_on_feedback_saved)


func _build_arena(content: VBoxContainer) -> void:
	_build_options(content)
	_arena = HBoxContainer.new()
	_arena.name = "CombatArena"
	_arena.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_arena.add_theme_constant_override("separation", 24)
	content.add_child(_arena)
	var player_panel := _combatant_panel(
		_arena, "PlayerBlock", Color("2277aa"), "COMBAT_PLAYER"
	)
	_player_block = player_panel["block"]
	_player_health = player_panel["health"]
	_player_mana = player_panel["mana"]
	_player_stats = player_panel["stats"]
	var enemy_panel := _combatant_panel(
		_arena, "EnemyBlock", Color("b74362"), "COMBAT_ENEMY"
	)
	_enemy_block = enemy_panel["block"]
	_enemy_health = enemy_panel["health"]
	_enemy_mana = enemy_panel["mana"]
	_enemy_stats = enemy_panel["stats"]
	_damage_result = _make_label("", 19, Color("ffd166"))
	_damage_result.name = "ActionResult"
	_damage_result.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	content.add_child(_damage_result)
	_feedback_action = Button.new()
	_feedback_action.name = "OpenCombatFeedback"
	_feedback_action.visible = false
	_feedback_action.pressed.connect(_on_open_feedback)
	content.add_child(_feedback_action)


func _build_options(content: VBoxContainer) -> void:
	_settings = HBoxContainer.new()
	_settings.name = "CombatOptions"
	_settings.add_theme_constant_override("separation", 18)
	content.add_child(_settings)
	var spell_column := VBoxContainer.new()
	spell_column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_settings.add_child(spell_column)
	_spell_style_label = _make_label("", 14, Color("9fb0ca"))
	spell_column.add_child(_spell_style_label)
	_spell_style = _make_options(SPELL_STYLE_KEYS, SPELL_STYLE_VALUES, 1)
	_spell_style.name = "SpellStyle"
	_spell_style.item_selected.connect(_on_options_changed)
	spell_column.add_child(_spell_style)
	var rival_column := VBoxContainer.new()
	rival_column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_settings.add_child(rival_column)
	_rival_strength_label = _make_label("", 14, Color("9fb0ca"))
	rival_column.add_child(_rival_strength_label)
	_rival_strength = _make_options(RIVAL_KEYS, RIVAL_VALUES, 0)
	_rival_strength.name = "RivalStrength"
	_rival_strength.item_selected.connect(_on_options_changed)
	rival_column.add_child(_rival_strength)


func _combatant_panel(
	parent: HBoxContainer,
	block_name: String,
	color: Color,
	label_key: String,
) -> Dictionary:
	var panel := _make_panel(color.darkened(0.68))
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 10)
	panel.add_child(column)
	var title := _make_label(tr(label_key), 20, Color("ffffff"))
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(title)
	var block := ColorRect.new()
	block.name = block_name
	block.color = color
	block.custom_minimum_size = Vector2(180, 150)
	block.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	column.add_child(block)
	var resource_prefix := block_name.trim_suffix("Block")
	var health := _resource_row(column, resource_prefix, "Health", "HP", HEALTH_COLOR)
	var mana := _resource_row(column, resource_prefix, "Mana", "MP", MANA_COLOR)
	var stats := _make_label("", 16, Color("dce7f7"))
	stats.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(stats)
	return {"block": block, "health": health, "mana": mana, "stats": stats}


func _resource_row(
	parent: VBoxContainer,
	name_prefix: String,
	resource_name: String,
	label_text: String,
	fill_color: Color,
) -> ProgressBar:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	parent.add_child(row)
	var label := _make_label(label_text, 14, Color("dce7f7"))
	label.name = name_prefix + resource_name + "Label"
	label.custom_minimum_size.x = 28
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	row.add_child(label)
	var bar := ProgressBar.new()
	bar.name = name_prefix + resource_name
	bar.max_value = 100
	bar.show_percentage = false
	bar.custom_minimum_size.y = 20
	bar.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	bar.add_theme_stylebox_override("background", _bar_style(RESOURCE_BACKGROUND_COLOR))
	bar.add_theme_stylebox_override("fill", _bar_style(fill_color))
	row.add_child(bar)
	return bar


func _bar_style(color: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.corner_radius_top_left = 4
	style.corner_radius_top_right = 4
	style.corner_radius_bottom_left = 4
	style.corner_radius_bottom_right = 4
	return style


func _build_feedback(content: VBoxContainer) -> void:
	_preference_label = _make_label("", 15, Color("9fb0ca"))
	content.add_child(_preference_label)
	_preference = _make_options(FEEL_KEYS, FEEL_VALUES, 0)
	content.add_child(_preference)
	_readability_label = _make_label("", 15, Color("9fb0ca"))
	content.add_child(_readability_label)
	_readability = _make_options(CLARITY_KEYS, CLARITY_VALUES, 2)
	content.add_child(_readability)
	_timing_label = _make_label("", 15, Color("9fb0ca"))
	content.add_child(_timing_label)
	_timing = _make_options(TIMING_KEYS, TIMING_VALUES, 2)
	content.add_child(_timing)
	_refresh_feature_translations()


func _render(state: Dictionary) -> void:
	_last_state = state.duplicate(true)
	_current_phase = str(state.get("phase", ""))
	if _current_phase == "preparing":
		_settings.visible = false
		_arena.visible = false
		_damage_result.visible = false
		_feedback_action.visible = false
		_shell.show_play("", tr("COMBAT_PREPARING"), "")
		_last_phase = _current_phase
		return
	if _current_phase == "feedback":
		_shell.show_feedback()
		_last_phase = _current_phase
		return
	_arena.visible = true
	_damage_result.visible = true
	_feedback_action.visible = _current_phase in ["victory", "defeat"]
	_settings.visible = _current_phase == "ready" and int(state.get("action_index", 0)) == 0
	var combatants: Dictionary = state.get("combatants", {})
	if not combatants.is_empty():
		_update_combatants(combatants)
	var progress := tr("COMBAT_ROUND_PROGRESS") % int(state.get("round", 1))
	match _current_phase:
		"ready":
			_damage_result.text = ""
			_shell.show_play(progress, tr("COMBAT_READY"), tr("COMBAT_ACTION_CAST"))
		"resolving_player", "resolving_enemy":
			_shell.show_play(progress, tr("COMBAT_RESOLVING"), tr("COMBAT_ACTION_WAIT"), false)
		"player_resolved":
			_damage_result.text = tr("COMBAT_PLAYER_HIT") % [
				int(state["damage"]), int(state["mana_cost"])
			]
			_shell.show_play(progress, tr("COMBAT_COUNTER_PROMPT"), tr("COMBAT_ACTION_COUNTER"))
			_pulse(_enemy_block)
		"enemy_resolved":
			_damage_result.text = tr("COMBAT_ENEMY_HIT") % [
				int(state["damage"]), int(state["mana_cost"])
			]
			_shell.show_play(progress, tr("COMBAT_EXCHANGE_RESOLVED"), tr("COMBAT_ACTION_CAST"))
			_pulse(_player_block)
		"victory", "defeat":
			var player_won := _current_phase == "victory"
			_damage_result.text = (
				tr("COMBAT_PLAYER_HIT") if player_won else tr("COMBAT_ENEMY_HIT")
			) % [int(state["damage"]), int(state["mana_cost"])]
			_shell.show_play(
				progress,
				tr("COMBAT_VICTORY") if player_won else tr("COMBAT_DEFEAT"),
				tr("COMBAT_ACTION_RESTART"),
			)
			_pulse(_enemy_block if player_won else _player_block)
		"retry":
			_shell.show_play(progress, tr("COMBAT_RETRY"), tr("COMBAT_ACTION_RETRY"))
	_last_phase = _current_phase


func _update_combatants(combatants: Dictionary) -> void:
	_player_health.value = float(combatants.get("player_health", 0))
	_player_mana.value = float(combatants.get("player_mana", 0))
	_enemy_health.value = float(combatants.get("enemy_health", 0))
	_enemy_mana.value = float(combatants.get("enemy_mana", 0))
	_player_stats.text = tr("COMBAT_STATS") % [
		int(combatants.get("player_health", 0)), int(combatants.get("player_mana", 0))
	]
	_enemy_stats.text = tr("COMBAT_STATS") % [
		int(combatants.get("enemy_health", 0)), int(combatants.get("enemy_mana", 0))
	]


func _on_primary_action() -> void:
	if _controller == null:
		return
	if _current_phase == "retry":
		_controller.retry()
	else:
		_controller.primary_action()


func _on_feedback_save_requested(notes: String) -> void:
	if _controller != null:
		_controller.submit_feedback(
			_selected_value(_preference),
			_selected_value(_readability),
			_selected_value(_timing),
			notes,
		)


func _on_open_feedback() -> void:
	if _controller != null:
		_controller.open_feedback()


func _on_options_changed(_index: int) -> void:
	if _controller != null:
		_controller.set_playtest_options(
			_selected_value(_spell_style),
			_selected_value(_rival_strength),
		)


func _on_feedback_saved(payload: Dictionary, path: String) -> void:
	_shell.show_feedback_saved(payload, path)


func _on_locale_changed(_locale_id: String) -> void:
	_refresh_feature_translations()
	if not _last_state.is_empty():
		_render(_last_state)


func _refresh_feature_translations() -> void:
	if _preference_label == null:
		return
	_preference_label.text = tr("COMBAT_FEEDBACK_PREFERENCE")
	_spell_style_label.text = tr("COMBAT_STYLE_LABEL")
	_rival_strength_label.text = tr("COMBAT_RIVAL_LABEL")
	_feedback_action.text = tr("COMBAT_ACTION_FEEDBACK")
	_readability_label.text = tr("COMBAT_FEEDBACK_READABILITY")
	_timing_label.text = tr("COMBAT_FEEDBACK_TIMING")
	_populate_options(_spell_style, SPELL_STYLE_KEYS, SPELL_STYLE_VALUES, 1)
	_populate_options(_rival_strength, RIVAL_KEYS, RIVAL_VALUES, 0)
	_populate_options(_preference, FEEL_KEYS, FEEL_VALUES, 0)
	_populate_options(_readability, CLARITY_KEYS, CLARITY_VALUES, 2)
	_populate_options(_timing, TIMING_KEYS, TIMING_VALUES, 2)


func _make_options(
	keys: Array[String], values: Array[String], default_index: int
) -> OptionButton:
	var options := OptionButton.new()
	_populate_options(options, keys, values, default_index)
	return options


func _populate_options(
	options: OptionButton,
	keys: Array[String],
	values: Array[String],
	default_index: int,
) -> void:
	var selected_value := _selected_value(options)
	options.clear()
	for index in range(keys.size()):
		options.add_item(tr(keys[index]))
		options.set_item_metadata(index, values[index])
		if values[index] == selected_value:
			options.selected = index
	if selected_value.is_empty():
		options.selected = default_index


func _selected_value(options: OptionButton) -> String:
	if options != null and options.item_count > 0 and options.selected >= 0:
		return str(options.get_item_metadata(options.selected))
	return ""


func _pulse(block: Control) -> void:
	block.pivot_offset = block.size * 0.5
	var tween := create_tween()
	tween.tween_property(block, "scale", Vector2(1.12, 1.12), 0.1)
	tween.tween_property(block, "scale", Vector2.ONE, 0.18)


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
