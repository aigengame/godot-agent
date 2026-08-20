class_name PeriodicEffectView
extends Control

const PlaytestShell = preload("res://ui/playtest_shell.gd")
const PeriodicEffectController = preload(
	"res://content/periodic_effect/periodic_effect_controller.gd"
)
const ENGLISH_TRANSLATION = preload(
	"res://ui/periodic_effect/localization/periodic_effect.en.tres"
)
const CHINESE_TRANSLATION = preload(
	"res://ui/periodic_effect/localization/periodic_effect.zh_CN.tres"
)
const STYLE_KEYS: Array[String] = [
	"EFFECT_DYNAMIC_NAME", "EFFECT_FIXED_NAME", "EFFECT_NO_DIFFERENCE"
]
const STYLE_VALUES: Array[String] = ["Dynamic Curse", "Fixed Curse", "No difference"]
const CLARITY_KEYS: Array[String] = [
	"EFFECT_VERY_CLEAR", "EFFECT_MOSTLY_CLEAR", "EFFECT_UNCLEAR"
]
const CLARITY_VALUES: Array[String] = ["Very clear", "Mostly clear", "Unclear"]
const TARGET_RESET_DURATION := 0.5

var _controller: PeriodicEffectController
var _shell: PlaytestShell
var _current_phase := ""
var _last_state: Dictionary = {}
var _target_block: ColorRect
var _rule_label: Label
var _health: ProgressBar
var _threshold_marker: ColorRect
var _threshold_label: Label
var _health_label: Label
var _effect_badge: Label
var _step_label: Label
var _preference_label: Label
var _impact_label: Label
var _timing_label: Label
var _preference: OptionButton
var _impact: OptionButton
var _timing: OptionButton
var _target_reset_tween: Tween


func _ready() -> void:
	TranslationServer.add_translation(ENGLISH_TRANSLATION)
	TranslationServer.add_translation(CHINESE_TRANSLATION)
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_shell = PlaytestShell.new()
	_shell.name = "PlaytestShell"
	add_child(_shell)
	_shell.setup("EFFECT_APP_TITLE", "EFFECT_APP_SUBTITLE")
	_shell.primary_action_requested.connect(_on_primary_action)
	_shell.feedback_save_requested.connect(_on_feedback_save_requested)
	_shell.locale_changed.connect(_on_locale_changed)
	_build_stage(_shell.feature_content())
	_build_feedback(_shell.feedback_content())


func bind(controller: PeriodicEffectController) -> void:
	_controller = controller
	_controller.view_state_changed.connect(_render)
	_controller.feedback_saved.connect(_on_feedback_saved)


func _build_stage(content: VBoxContainer) -> void:
	var panel := _make_panel(Color("231d3d"))
	panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	content.add_child(panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 14)
	panel.add_child(column)
	var target_label := _make_label(tr("EFFECT_TARGET"), 20, Color("e5d4ff"))
	target_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(target_label)
	_rule_label = _make_label("", 17, Color("d7e5ff"))
	_rule_label.name = "EffectRule"
	_rule_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_rule_label)
	_target_block = ColorRect.new()
	_target_block.name = "EffectTargetBlock"
	_target_block.color = Color("7856c6")
	_target_block.custom_minimum_size = Vector2(260, 170)
	_target_block.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	column.add_child(_target_block)
	_health = ProgressBar.new()
	_health.name = "EffectTargetHealth"
	_health.max_value = 100
	_health.show_percentage = false
	_health.custom_minimum_size = Vector2(560, 28)
	column.add_child(_health)
	_threshold_marker = ColorRect.new()
	_threshold_marker.name = "EffectDamageThresholdMarker"
	_threshold_marker.color = Color("ffcf70")
	_threshold_marker.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_threshold_marker.anchor_top = 0.0
	_threshold_marker.anchor_bottom = 1.0
	_threshold_marker.offset_left = -2
	_threshold_marker.offset_right = 2
	_threshold_marker.offset_top = 0
	_threshold_marker.offset_bottom = 0
	_health.add_child(_threshold_marker)
	_threshold_label = _make_label("", 15, Color("ffcf70"))
	_threshold_label.name = "EffectDamageThreshold"
	_threshold_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_threshold_label)
	_health_label = _make_label("", 20, Color("ffffff"))
	_health_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_health_label)
	_effect_badge = _make_label("", 18, Color("ffcf70"))
	_effect_badge.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_effect_badge)
	_step_label = _make_label("", 18, Color("9fd5ff"))
	_step_label.name = "EffectStep"
	_step_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_step_label)


func _build_feedback(content: VBoxContainer) -> void:
	_preference_label = _make_label("", 15, Color("9fb0ca"))
	content.add_child(_preference_label)
	_preference = _make_options(STYLE_KEYS, STYLE_VALUES, 2)
	content.add_child(_preference)
	_impact_label = _make_label("", 15, Color("9fb0ca"))
	content.add_child(_impact_label)
	_impact = _make_options(CLARITY_KEYS, CLARITY_VALUES, 2)
	content.add_child(_impact)
	_timing_label = _make_label("", 15, Color("9fb0ca"))
	content.add_child(_timing_label)
	_timing = _make_options(CLARITY_KEYS, CLARITY_VALUES, 2)
	content.add_child(_timing)
	_refresh_feature_translations()


func _render(state: Dictionary) -> void:
	_last_state = state.duplicate(true)
	_current_phase = str(state.get("phase", ""))
	if _current_phase == "preparing":
		_shell.feature_content().visible = false
		_shell.show_play("", tr("EFFECT_PREPARING"), "")
		return
	if _current_phase == "feedback":
		_shell.show_feedback()
		return
	_shell.feature_content().visible = true
	var progress := tr("EFFECT_TRIAL_PROGRESS") % [
		mini(int(state.get("trial_index", 0)) + 1, int(state.get("trial_count", 2))),
		int(state.get("trial_count", 2)),
	]
	if _current_phase == "resetting_target":
		_start_target_reset(state, progress)
		return
	if _current_phase == "ready":
		_cancel_target_reset()
		_reset_stage(state)
		var style_key := (
			"EFFECT_DYNAMIC_NAME"
			if state.get("trial_kind") == "dynamic"
			else "EFFECT_FIXED_NAME"
		)
		var ready_message := (
			tr("EFFECT_READY_FRESH") % [int(state.get("initial_health", 100)), tr(style_key)]
			if state.get("fresh_target", false)
			else tr("EFFECT_READY") % tr(style_key)
		)
		_shell.show_play(
			progress,
			ready_message,
			tr("EFFECT_ACTION_APPLY"),
		)
		return
	_render_rule(state)
	if _current_phase == "preparing_trial":
		_shell.show_play(progress, tr("EFFECT_RESOLVING"), tr("EFFECT_ACTION_WAIT"), false)
		return
	if _current_phase == "retry":
		_shell.show_play(progress, tr("EFFECT_RETRY"), tr("EFFECT_ACTION_RETRY"))
		return
	if state.has("health"):
		_health.value = float(state["health"])
		_health_label.text = tr("EFFECT_HEALTH") % int(state["health"])
		_effect_badge.text = (
			tr("EFFECT_ACTIVE") if state.get("effect_active", false) else tr("EFFECT_EXPIRED")
		)
		_step_label.text = _step_text(state)
	if _current_phase == "timeline_step":
		var next_action := (
			tr("EFFECT_ACTION_FINISH")
			if int(state.get("step", 0)) + 1 == int(state.get("step_count", 0))
			else tr("EFFECT_ACTION_NEXT_STEP")
		)
		_shell.show_play(progress, _step_text(state), next_action)
		if int(state.get("damage", 0)) > 0:
			_pulse_target()
	elif _current_phase == "trial_complete":
		var final_trial := int(state.get("trial_index", 0)) + 1 == int(state.get("trial_count", 2))
		var completion_message := (
			tr("EFFECT_TRIAL_COMPLETE_FIXED") % int(state.get("health", 0))
			if final_trial
			else tr("EFFECT_TRIAL_COMPLETE_DYNAMIC") % int(state.get("health", 0))
		)
		_step_label.text = completion_message
		_shell.show_play(
			progress,
			completion_message,
			tr("EFFECT_ACTION_FEEDBACK") if final_trial else tr("EFFECT_ACTION_NEXT_TRIAL"),
		)


func _step_text(state: Dictionary) -> String:
	var dynamic: bool = state.get("trial_kind") == "dynamic"
	var damage := int(state.get("damage", 0))
	var threshold := int(state.get("damage_threshold", 0))
	match str(state.get("lifecycle_phase", "")):
		"apply":
			if dynamic:
				return tr("EFFECT_STEP_APPLY_DYNAMIC")
			var cast_damage := int(state.get("cast_damage", 0))
			return tr("EFFECT_STEP_APPLY_FIXED") % [cast_damage, cast_damage]
		"pulse":
			if not dynamic:
				return tr("EFFECT_STEP_FIXED_PULSE") % damage
			if damage == 0:
				return tr("EFFECT_STEP_DYNAMIC_THRESHOLD") % [
					int(state.get("health_before", state.get("health", 0))), threshold
				]
			return tr("EFFECT_STEP_DYNAMIC_PULSE") % [
				int(state.get("health_before", state.get("health", 0))), damage
			]
		"attack":
			return (
				tr("EFFECT_STEP_ATTACK_DYNAMIC") % damage
				if dynamic
				else tr("EFFECT_STEP_ATTACK_FIXED") % damage
			)
		"expire":
			return tr("EFFECT_STEP_EXPIRE")
	return ""


func _reset_stage(state: Dictionary) -> void:
	var initial_health := int(state.get("initial_health", 100))
	_health.max_value = initial_health
	_set_displayed_health(float(initial_health))
	_effect_badge.text = tr("EFFECT_INACTIVE")
	_step_label.text = ""
	_render_rule(state)


func _start_target_reset(state: Dictionary, progress: String) -> void:
	_cancel_target_reset()
	var initial_health := maxi(int(state.get("initial_health", 100)), 1)
	var previous_health := clampi(
		int(state.get("previous_health", initial_health)), 0, initial_health
	)
	_health.max_value = initial_health
	_set_displayed_health(float(previous_health))
	_effect_badge.text = tr("EFFECT_INACTIVE")
	_step_label.text = tr("EFFECT_RESETTING_TARGET") % initial_health
	_render_rule(state)
	_shell.show_play(
		progress,
		tr("EFFECT_RESETTING_TARGET") % initial_health,
		"",
		false,
	)
	_target_reset_tween = create_tween()
	_target_reset_tween.set_trans(Tween.TRANS_QUAD)
	_target_reset_tween.set_ease(Tween.EASE_OUT)
	_target_reset_tween.tween_method(
		_set_displayed_health,
		float(previous_health),
		float(initial_health),
		TARGET_RESET_DURATION,
	)
	_target_reset_tween.tween_callback(_finish_target_reset.bind(initial_health))


func _finish_target_reset(initial_health: int) -> void:
	_target_reset_tween = null
	_set_displayed_health(float(initial_health))
	if _controller != null:
		_controller.target_reset_completed()


func _cancel_target_reset() -> void:
	if _target_reset_tween != null and _target_reset_tween.is_valid():
		_target_reset_tween.kill()
	_target_reset_tween = null


func _set_displayed_health(value: float) -> void:
	_health.value = value
	_health_label.text = tr("EFFECT_HEALTH") % int(round(value))


func _render_rule(state: Dictionary) -> void:
	var threshold := int(state.get("damage_threshold", 0))
	var initial_health := maxi(int(state.get("initial_health", 100)), 1)
	var dynamic: bool = state.get("trial_kind") == "dynamic"
	_rule_label.text = (
		tr("EFFECT_DYNAMIC_RULE") % [threshold, threshold]
		if dynamic
		else tr("EFFECT_FIXED_RULE") % initial_health
	)
	_threshold_label.text = (
		tr("EFFECT_DYNAMIC_THRESHOLD") % threshold
		if dynamic
		else tr("EFFECT_FIXED_THRESHOLD") % threshold
	)
	var ratio := clampf(float(threshold) / float(initial_health), 0.0, 1.0)
	_threshold_marker.anchor_left = ratio
	_threshold_marker.anchor_right = ratio
	_threshold_marker.visible = threshold > 0


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
			_selected_value(_impact),
			_selected_value(_timing),
			notes,
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
	_preference_label.text = tr("EFFECT_FEEDBACK_PREFERENCE")
	_impact_label.text = tr("EFFECT_FEEDBACK_IMPACT")
	_timing_label.text = tr("EFFECT_FEEDBACK_TIMING")
	_populate_options(_preference, STYLE_KEYS, STYLE_VALUES, 2)
	_populate_options(_impact, CLARITY_KEYS, CLARITY_VALUES, 2)
	_populate_options(_timing, CLARITY_KEYS, CLARITY_VALUES, 2)


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


func _pulse_target() -> void:
	_target_block.pivot_offset = _target_block.size * 0.5
	var tween := create_tween()
	tween.tween_property(_target_block, "scale", Vector2(0.9, 0.9), 0.08)
	tween.tween_property(_target_block, "scale", Vector2.ONE, 0.16)


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
