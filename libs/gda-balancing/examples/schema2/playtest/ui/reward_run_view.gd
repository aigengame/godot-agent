extends Control

const PlaytestShell = preload("res://ui/playtest_shell.gd")
const RewardRunController = preload("res://content/reward_run/reward_run_controller.gd")

var _controller: RewardRunController
var _last_phase := ""
var _last_state: Dictionary = {}
var _shell: PlaytestShell
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


func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_shell = PlaytestShell.new()
	_shell.name = "PlaytestShell"
	add_child(_shell)
	_shell.setup(
		"APP_TITLE",
		"APP_SUBTITLE",
		"FEEDBACK_STRONGER",
		"FEEDBACK_CLARITY",
	)
	_shell.primary_action_requested.connect(_on_primary_action)
	_shell.feedback_submitted.connect(_on_feedback_submitted)
	_shell.locale_changed.connect(_on_locale_changed)
	_build_reward_presentation(_shell.feature_content())


func bind(controller: RewardRunController) -> void:
	_controller = controller
	_controller.view_state_changed.connect(_render)
	_controller.feedback_saved.connect(_on_feedback_saved)


func show_error(message: String) -> void:
	_shell.show_error(message)


func _build_reward_presentation(content: VBoxContainer) -> void:
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


func _render(state: Dictionary) -> void:
	_last_state = state.duplicate(true)
	var next_phase := str(state["phase"])
	if next_phase == "feedback":
		_shell.show_feedback()
		_last_phase = next_phase
		return

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
	if _controller != null:
		_controller.primary_action()


func _on_feedback_submitted(
	preference: String,
	stronger_reward: String,
	change_clarity: String,
	notes: String,
) -> void:
	if _controller != null:
		_controller.submit_feedback(
			preference,
			stronger_reward,
			change_clarity,
			notes,
		)


func _on_feedback_saved(payload: Dictionary, path: String) -> void:
	_shell.show_feedback_saved(payload, path)


func _on_locale_changed(_locale_id: String) -> void:
	_player_label.text = tr("PLAYER_LABEL")
	if not _last_state.is_empty():
		_render(_last_state)


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
