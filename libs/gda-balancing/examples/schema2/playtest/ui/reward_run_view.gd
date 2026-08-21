extends Control

const PlaytestShell = preload("res://ui/playtest_shell.gd")
const RewardRunController = preload("res://content/reward_run/reward_run_controller.gd")
const ENGLISH_TRANSLATION = preload(
	"res://ui/reward_run/localization/reward_run.en.tres"
)
const CHINESE_TRANSLATION = preload(
	"res://ui/reward_run/localization/reward_run.zh_CN.tres"
)
const TRIAL_OPTION_KEYS: Array[String] = ["TRIAL_1", "TRIAL_2", "NO_DIFFERENCE"]
const TRIAL_OPTION_VALUES: Array[String] = ["Trial 1", "Trial 2", "No difference"]
const CLARITY_OPTION_KEYS: Array[String] = ["VERY_CLEAR", "MOSTLY_CLEAR", "UNCLEAR"]
const CLARITY_OPTION_VALUES: Array[String] = ["Very clear", "Mostly clear", "Unclear"]

var _controller: RewardRunController
var _last_phase := ""
var _current_phase := ""
var _last_state: Dictionary = {}
var _shell: PlaytestShell
var _frequency_panel: PanelContainer
var _frequency_label: Label
var _frequency: HSlider
var _frequency_value: Label
var _arena: HBoxContainer
var _player_label: Label
var _power_label: Label
var _target_label: Label
var _target_health: ProgressBar
var _target_block: ColorRect
var _player_block: ColorRect
var _reward_panel: PanelContainer
var _reward_name: Label
var _reward_detail: Label
var _preference_label: Label
var _stronger_label: Label
var _clarity_label: Label
var _preference: OptionButton
var _stronger: OptionButton
var _clarity: OptionButton


func _ready() -> void:
	TranslationServer.add_translation(ENGLISH_TRANSLATION)
	TranslationServer.add_translation(CHINESE_TRANSLATION)
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_shell = PlaytestShell.new()
	_shell.name = "PlaytestShell"
	add_child(_shell)
	_shell.setup(
		"APP_TITLE",
		"APP_SUBTITLE",
	)
	_shell.primary_action_requested.connect(_on_primary_action)
	_shell.feedback_save_requested.connect(_on_feedback_save_requested)
	_shell.locale_changed.connect(_on_locale_changed)
	_build_reward_presentation(_shell.feature_content())
	_build_reward_feedback(_shell.feedback_content())


func bind(controller: RewardRunController) -> void:
	_controller = controller
	_controller.view_state_changed.connect(_render)
	_controller.feedback_saved.connect(_on_feedback_saved)


func show_error(message: String) -> void:
	_shell.show_error(message)


func _build_reward_presentation(content: VBoxContainer) -> void:
	_build_frequency_control(content)

	_arena = HBoxContainer.new()
	_arena.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_arena.add_theme_constant_override("separation", 18)
	content.add_child(_arena)

	var player_panel := _make_panel(Color("132942"))
	player_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_arena.add_child(player_panel)
	var player_column := _panel_column(player_panel)
	_player_label = _make_label(tr("PLAYER_LABEL"), 17, Color("87d9ff"))
	player_column.add_child(_player_label)
	_player_block = ColorRect.new()
	_player_block.name = "PlayerBlock"
	_player_block.color = Color("2998d6")
	_player_block.custom_minimum_size = Vector2(180, 128)
	_player_block.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	player_column.add_child(_player_block)
	_power_label = _make_label(tr("POWER_VALUE") % 10, 24, Color("ffffff"))
	_power_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	player_column.add_child(_power_label)

	var target_panel := _make_panel(Color("321d2b"))
	target_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_arena.add_child(target_panel)
	var target_column := _panel_column(target_panel)
	_target_label = _make_label(tr("TRAINING_TARGET"), 17, Color("ffb4c8"))
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
	content.add_child(_reward_panel)
	var reward_column := _panel_column(_reward_panel)
	_reward_name = _make_label(tr("REWARD_LABEL"), 26, Color("ffd166"))
	_reward_name.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	reward_column.add_child(_reward_name)
	_reward_detail = _make_label("", 17, Color("f7e7ad"))
	_reward_detail.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	reward_column.add_child(_reward_detail)


func _build_frequency_control(content: VBoxContainer) -> void:
	_frequency_panel = _make_panel(Color("16243a"))
	_frequency_panel.name = "FrequencyPanel"
	content.add_child(_frequency_panel)
	var column := _panel_column(_frequency_panel)
	_frequency_label = _make_label("", 17, Color("91a6c7"))
	_frequency_label.text = tr("FREQUENCY_LABEL")
	column.add_child(_frequency_label)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 16)
	column.add_child(row)
	_frequency = HSlider.new()
	_frequency.name = "RewardFrequency"
	_frequency.step = 1.0
	_frequency.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_frequency.custom_minimum_size = Vector2(560, 36)
	_frequency.value_changed.connect(_on_frequency_changed)
	row.add_child(_frequency)
	_frequency_value = _make_label("", 22, Color("59d7c6"))
	_frequency_value.text = "0"
	_frequency_value.custom_minimum_size = Vector2(72, 36)
	_frequency_value.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	row.add_child(_frequency_value)


func _build_reward_feedback(content: VBoxContainer) -> void:
	_preference_label = _make_label("", 15, Color("9fb0ca"))
	content.add_child(_preference_label)
	_preference = _make_options(TRIAL_OPTION_KEYS, TRIAL_OPTION_VALUES)
	content.add_child(_preference)
	_stronger_label = _make_label("", 15, Color("9fb0ca"))
	content.add_child(_stronger_label)
	_stronger = _make_options(TRIAL_OPTION_KEYS, TRIAL_OPTION_VALUES)
	content.add_child(_stronger)
	_clarity_label = _make_label("", 15, Color("9fb0ca"))
	content.add_child(_clarity_label)
	_clarity = _make_options(CLARITY_OPTION_KEYS, CLARITY_OPTION_VALUES)
	content.add_child(_clarity)
	_refresh_feedback_translations()


func _render(state: Dictionary) -> void:
	_last_state = state.duplicate(true)
	var next_phase := str(state["phase"])
	_current_phase = next_phase
	if next_phase == "preparing":
		_frequency_panel.visible = false
		_arena.visible = false
		_reward_panel.visible = false
		_shell.show_play("", tr("PREPARING_PLAYTEST"), "")
		_last_phase = next_phase
		return
	if next_phase in ["choose_frequency", "preparing_trial", "retry"]:
		var control: Dictionary = state.get("reward_frequency", {})
		if control.has("minimum"):
			_frequency.min_value = float(control["minimum"])
			_frequency.max_value = float(control["maximum"])
			_frequency.value = float(control["value"])
		_frequency.editable = next_phase == "choose_frequency"
		_frequency_panel.visible = true
		_arena.visible = false
		_reward_panel.visible = false
		var progress := tr("TRIAL_PROGRESS") % [
			int(state.get("trial_index", 0)) + 1,
			int(state.get("trial_count", 2)),
		]
		if next_phase == "choose_frequency":
			_shell.show_play(
				progress,
				tr("FREQUENCY_INSTRUCTION"),
				tr("ACTION_START_TRIAL"),
			)
		elif next_phase == "preparing_trial":
			_shell.show_play(
				progress,
				tr("PREPARING_TRIAL_REWARD"),
				tr("ACTION_PREPARING"),
				false,
			)
		else:
			_shell.show_play(
				progress,
				tr("RETRY_INSTRUCTION"),
				tr("ACTION_RETRY"),
			)
		_last_phase = next_phase
		return
	if next_phase == "feedback":
		_shell.show_feedback()
		_last_phase = next_phase
		return

	_frequency_panel.visible = false
	_frequency.editable = false
	_arena.visible = true
	if state.has("reward_frequency_value"):
		_frequency.value = float(state["reward_frequency_value"])
	_power_label.text = tr("POWER_VALUE") % int(state["power"])
	_target_health.max_value = float(state["target_max_health"])
	_target_health.value = float(state["target_health"])
	_target_label.text = tr("TARGET_HEALTH") % [
		int(state["target_health"]),
		int(state["target_max_health"]),
	]

	var reward: Dictionary = state["reward"]
	var build: Dictionary = state["build"]
	var reward_name := _translated_reward_name(reward)
	_reward_name.text = reward_name
	_reward_detail.text = tr("REWARD_DETAIL") % [
		_translated_rarity(str(reward["rarity"])),
		int(build["power_before"]),
		int(build["power_after"]),
	]
	_reward_panel.visible = next_phase in [
		"reward_ready", "after_fight", "run_complete"
	]

	var instruction := ""
	var action := ""
	match next_phase:
		"before_fight":
			instruction = tr("INSTRUCTION_FIRST_TARGET")
			action = tr("ACTION_STRIKE")
		"reward_ready":
			instruction = tr("INSTRUCTION_EQUIP")
			action = tr("ACTION_EQUIP") % reward_name.to_upper()
		"after_fight":
			instruction = tr("INSTRUCTION_SECOND_TARGET")
			action = tr("ACTION_STRIKE_WITH") % reward_name.to_upper()
		"run_complete":
			instruction = tr("INSTRUCTION_TRIAL_COMPLETE")
			action = (
				tr("ACTION_COMPARE_TRIALS")
				if int(state["trial_index"]) + 1 == int(state["trial_count"])
				else tr("ACTION_START_NEXT_TRIAL")
			)

	_shell.show_play(
		tr("TRIAL_PROGRESS") % [
			int(state["trial_index"]) + 1,
			int(state["trial_count"]),
		],
		instruction,
		action,
	)

	if _last_phase == next_phase and next_phase in ["before_fight", "after_fight"]:
		_pulse_target()
	elif next_phase == "reward_ready":
		_reveal_reward()
	elif _last_phase == "reward_ready" and next_phase == "after_fight":
		_pulse_player()
	_last_phase = next_phase


func _on_primary_action() -> void:
	if _controller == null:
		return
	match _current_phase:
		"choose_frequency":
			_controller.start_trial(int(_frequency.value))
		"retry":
			_controller.retry()
		_:
			_controller.primary_action()


func _on_feedback_save_requested(notes: String) -> void:
	if _controller != null:
		_controller.submit_feedback(
			str(_preference.get_item_metadata(_preference.selected)),
			str(_stronger.get_item_metadata(_stronger.selected)),
			str(_clarity.get_item_metadata(_clarity.selected)),
			notes,
		)


func _on_feedback_saved(payload: Dictionary, path: String) -> void:
	_shell.show_feedback_saved(payload, path)


func _on_locale_changed(_locale_id: String) -> void:
	_player_label.text = tr("PLAYER_LABEL")
	_frequency_label.text = tr("FREQUENCY_LABEL")
	_refresh_feedback_translations()
	if not _last_state.is_empty():
		_render(_last_state)


func _refresh_feedback_translations() -> void:
	if _preference_label == null:
		return
	_preference_label.text = tr("FEEDBACK_PREFERENCE")
	_stronger_label.text = tr("FEEDBACK_STRONGER")
	_clarity_label.text = tr("FEEDBACK_CLARITY")
	_populate_options(_preference, TRIAL_OPTION_KEYS, TRIAL_OPTION_VALUES, 2)
	_populate_options(_stronger, TRIAL_OPTION_KEYS, TRIAL_OPTION_VALUES, 2)
	_populate_options(_clarity, CLARITY_OPTION_KEYS, CLARITY_OPTION_VALUES, 2)


func _on_frequency_changed(value: float) -> void:
	if _frequency_value != null:
		_frequency_value.text = str(int(value))


func _translated_reward_name(reward: Dictionary) -> String:
	match str(reward.get("key", "")):
		"volatile_crown":
			return tr("REWARD_STORM_CROWN")
		"steady_guard":
			return tr("REWARD_IRON_GUARD")
	return str(reward.get("name", ""))


func _translated_rarity(rarity: String) -> String:
	match rarity:
		"rare":
			return tr("RARITY_RARE")
		"common":
			return tr("RARITY_COMMON")
	return rarity.capitalize()


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
