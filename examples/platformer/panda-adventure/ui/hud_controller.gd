class_name HudController
extends CanvasLayer

## Drives the HUD blockout (S6a, gADR-0004; +Level since S6b, gADR-0006;
## +Consumable counts since S7, gADR-0008): eight Labels in a screen-space
## column surfacing the Player's live HP, MP, Level, EXP, Gold, Current
## weapon, and the Bun/Wine supply — the GDD's "HUD & UI" contract — so the
## player reads state without leaving the action. A CanvasLayer renders in
## screen space, untouched by the S1 follow-camera.
##
## Read model: the HUD PULLS the Player's public `hud_state()` snapshot each
## process frame (gADR-0004) — at five values a frame that costs nothing and
## needs no signal plumbing across every stat mutation site; the Player stays
## the single owner of its state and the HUD holds none. A Label's text is
## rewritten only when its formatted value CHANGES, and that change plays the
## value pulse (a scale punch tweened back to 1.0 — the landing-squash idiom,
## the GDD's property-tween "animation"), so success feedback (EXP/Gold ticking
## up) reads at a glance.
##
## Placement and pulse numbers are data (gADR-0000): the derived HudConfig
## Resource, never hardcoded. The format decisions are PURE static functions so
## the logic seam can pin them headless (tests/gdscript/test_reward_hud_logic.gd
## via `gda script run`). Cross-script references use preload() (no editor
## class cache in this never-imported project).

const HudConfigScript := preload("res://content/config/hud_config.gd")
const GameLogScript := preload("res://addons/game_log/game_log.gd")
const GeneratedConfigScript := preload("res://content/config/generated_config.gd")

const HUD_CONFIG_PATH := "res://content/data/generated/hud_config.tres"

# The eight surfaced values, in display order: each maps a snapshot to its
# Label node name. Structural wiring (what the HUD shows is the GDD contract),
# not config numbers.
const LINES := ["hp", "mp", "level", "exp", "gold", "weapon", "bun", "wine"]

var _config: HudConfigScript
var _player: Node
# Whether the first snapshot has been rendered (it populates silently and logs
# hud_ready; later changes pulse).
var _primed := false


## Bind the Content state source at the composition point.
func bind(player: Node) -> void:
	_player = player


## Pure format decision for a capped stat (HP/MP): current value against its
## cap. The current value uses ceili so the readout never shows 0 while the
## death rule (hp <= 0) has not fired — legibility over rounding symmetry; the
## cap is a config value, roundi'd for display.
static func format_bar(prefix: String, value: float, max_value: float) -> String:
	return "%s %d/%d" % [prefix, ceili(value), roundi(max_value)]


## Pure format decision for an accumulating amount (EXP/Gold): floori — the
## readout never shows more than has actually been earned.
static func format_amount(prefix: String, value: float) -> String:
	return "%s %d" % [prefix, floori(value)]


## Pure format decision for the Current weapon: the weapon identifier rendered
## as its display name ("laser_gun" -> "LASER GUN").
static func format_weapon(weapon: String) -> String:
	return weapon.replace("_", " ").to_upper()


## Pure mapping from the Player's hud_state() snapshot to the eight display
## strings, keyed like LINES. The single place the snapshot's shape meets the
## format decisions, so the seam can pin the whole readout at once. The Level
## readout (S6b) reuses format_amount (an integer level passes through floori
## unchanged), and so do the S7 Consumable counts (integers by construction).
static func format_lines(state: Dictionary) -> Dictionary:
	return {
		"hp": format_bar("HP", state["hp"], state["max_hp"]),
		"mp": format_bar("MP", state["mp"], state["max_mp"]),
		"level": format_amount("LV", state["level"]),
		"exp": format_amount("EXP", state["exp"]),
		"gold": format_amount("GOLD", state["gold"]),
		"weapon": format_weapon(state["weapon"]),
		"bun": format_amount("BUN", state["bun"]),
		"wine": format_amount("WINE", state["wine"]),
	}


func _ready() -> void:
	_config = GeneratedConfigScript.load_config(HUD_CONFIG_PATH)
	if _config == null:
		return
	($Stats as VBoxContainer).position = _config.margin
	# The styled HUD font (P2-S9, gADR-0014): the derived bitmap Font applied to
	# every line, at the Scale spec's font size (gADR-0013 — the font-scale anchor
	# is data). The font is a resolved asset reference (data, gADR-0000); an
	# empty/failed reference keeps the engine default so a font-less checkout still
	# renders every line. Presentation only — the LINES contract is untouched.
	var font := _hud_font()
	for key: String in LINES:
		var label := _label(key)
		if font != null:
			label.add_theme_font_override("font", font)
		label.add_theme_font_size_override("font_size", roundi(_config.font_size))


func _process(_delta: float) -> void:
	if _config == null:
		return
	if _player == null or not is_instance_valid(_player) or not _player.has_method("hud_state"):
		return
	var state: Dictionary = _player.hud_state()
	if state.is_empty():
		# The Player has not initialized its stats yet — try next frame.
		return
	var lines := format_lines(state)
	for key: String in LINES:
		var label := _label(key)
		if label.text == lines[key]:
			continue
		label.text = lines[key]
		if _primed:
			_play_value_pulse(label)
	if not _primed:
		# First full readout: populate silently (nothing "changed" yet) and
		# log the module entry with the initial values, per the logger
		# feedback convention. Weapon is a string; all fields JSON-scalar.
		_primed = true
		GameLogScript.emit("info", "hud_ready", {
			"hp": state["hp"],
			"mp": state["mp"],
			"level": state["level"],
			"exp": state["exp"],
			"gold": state["gold"],
			"weapon": state["weapon"],
			"bun": state["bun"],
			"wine": state["wine"],
		})


## The value-change "juice": punch the Label's scale and tween back to 1.0
## about its center (the landing-squash idiom on a Control).
func _play_value_pulse(label: Label) -> void:
	label.pivot_offset = label.size / 2.0
	label.scale = _config.value_punch_scale
	var tween := create_tween()
	var recover := tween.tween_property(
		label, "scale", Vector2.ONE, _config.value_tween_duration
	)
	recover.set_trans(Tween.TRANS_SINE)


## Load the HUD's configured bitmap font, or null when none is wired or the load
## fails — the HUD then keeps the engine-default font. A non-empty-but-unloadable
## reference is a not-shipped-font fault: guard loudly (the ViewBuilder sprite
## idiom) but never blank the readout.
func _hud_font() -> Font:
	if _config.hud_font.is_empty():
		return null
	var font := load(_config.hud_font) as Font
	if font == null:
		push_error(
			"HudController: font '%s' failed to load — rendering the default font."
			% _config.hud_font
		)
	return font


## The Label for one LINES key ("hp" -> Stats/HpLabel).
func _label(key: String) -> Label:
	return get_node("Stats/%sLabel" % key.capitalize()) as Label
