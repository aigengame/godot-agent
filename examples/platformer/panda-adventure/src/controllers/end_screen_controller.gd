class_name EndScreenController
extends CanvasLayer

## Drives the End screen blockout (S9, gADR-0010): the level-owned overlay
## announcing the End state — a full-screen dim, the verdict title, and the
## retry hint — shown once per run by the LevelController and faded in by
## tween (the GDD's property-tween "animation"). A CanvasLayer above the HUD
## (screen space, untouched by the S1 follow-camera); NOT part of the HUD —
## gADR-0004's LINES contract is untouched.
##
## Colors, font sizes, and the fade duration are data (gADR-0000): the derived
## LevelConfig Resource, never hardcoded. The copy ("VICTORY!", "GAME OVER",
## the retry hint) is structural, like the weapon identifiers. Layout is
## proportioned to the config font sizes — no separate layout numbers.
##
## The World freeze skips CanvasLayers (gADR-0010), so this node keeps
## processing while the world stands still: the fade plays, and the
## LevelController (also un-frozen) serves the retry action.
##
## Cross-script references use preload() (no editor class cache in this
## never-imported project).

const LevelConfigScript := preload("res://src/resources/level_config.gd")
const GameLogScript := preload("res://src/util/game_log.gd")
const GeneratedConfigScript := preload("res://src/util/generated_config.gd")

const LEVEL_CONFIG_PATH := "res://data/generated/level_config.tres"

# The verdict copy — structural identifiers of the two End states (the
# WEAPON_* pattern: they name states and log values, not tunable numbers).
const TITLE_WON := "VICTORY!"
const TITLE_LOST := "GAME OVER"
const HINT_RETRY := "Press Enter to retry"

var _config: LevelConfigScript


func _ready() -> void:
	_config = GeneratedConfigScript.load_config(LEVEL_CONFIG_PATH)
	if _config == null:
		return
	# Above the HUD's default layer (structural: the closure overlay outranks
	# the readout), hidden until an End state shows it.
	layer = 2
	visible = false
	var overlay := $Overlay as ColorRect
	overlay.color = _config.end_overlay_color
	overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)


## Announce one End state (called by the LevelController exactly once per
## run): style the verdict title and the retry hint from config, center them
## (proportioned to the config font sizes), and fade the whole overlay in —
## the labels ride the Overlay's modulate. Logs end_screen_shown, the surface's
## durable observable for gda logger tail.
func show_end(win: bool) -> void:
	if _config == null:
		return
	var title := $Overlay/TitleLabel as Label
	title.text = TITLE_WON if win else TITLE_LOST
	title.add_theme_font_size_override("font_size", int(_config.end_title_font_size))
	title.add_theme_color_override(
		"font_color", _config.end_win_color if win else _config.end_lose_color
	)
	_center(title, -_config.end_title_font_size)

	var hint := $Overlay/HintLabel as Label
	hint.text = HINT_RETRY
	hint.add_theme_font_size_override("font_size", int(_config.end_hint_font_size))
	_center(hint, _config.end_hint_font_size)

	visible = true
	var overlay := $Overlay as ColorRect
	overlay.modulate.a = 0.0
	var tween := create_tween()
	var fade := tween.tween_property(overlay, "modulate:a", 1.0, _config.end_fade_duration)
	fade.set_trans(Tween.TRANS_SINE)
	GameLogScript.emit("info", "end_screen_shown", {
		"result": "won" if win else "lost",
	})


## Center one label on the screen, shifted vertically by `y_shift` pixels —
## the title sits one title-height above center, the hint one hint-height
## below (spacing proportioned to the config font sizes, no layout numbers).
## reset_size() first so the preset centers the label's FRESH minimum size
## (the text and font size were just set).
func _center(label: Label, y_shift: float) -> void:
	label.reset_size()
	label.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	label.position.y += y_shift
