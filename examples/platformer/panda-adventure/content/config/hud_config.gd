class_name HudConfig
extends Resource

## The HUD blockout's typed config (S6a, gADR-0004): overlay placement and the
## value-change pulse tween. The HUD's CONTENT (live HP/MP/EXP/Gold + Current
## weapon) is fixed by the GDD's "HUD & UI" section; concrete layout/styling
## beyond these numbers is a later asset concern.
##
## This Resource is a DERIVED artifact: it is regenerated from the
## authoritative content/data/json/hud_config.json by scripts/build_config.py and
## emitted to content/data/generated/hud_config.tres. Never hand-edit the generated
## .tres or hardcode these values — change the JSON (gADR-0000).
##
## The @export fields carry NO default literals on purpose (see PlayerConfig).

# Offset of the HUD stat column from the viewport's top-left corner. AUTHORED
# in scale_spec.json (gADR-0013), composed in by the builder.
@export var margin: Vector2
# HUD label font size in design-space pixels — the Scale spec's hud_font_size
# (gADR-0013), made explicit where the blockout leaned on the engine default.
@export var font_size: float
# The value-change "juice": a scale punch tweened back to 1.0 (the landing-
# squash idiom applied to a Label the moment its value changes).
@export var value_punch_scale: Vector2
@export var value_tween_duration: float
# Resolved res:// path of the HUD's bitmap font (P2-S9, #445): an Asset manifest
# reference (gADR-0014) the builder resolves from its id; empty when no font is
# wired (the HUD then keeps the engine default). The HudController load()s it and
# applies it via add_theme_font_override at the Scale spec's font_size.
@export var hud_font: String
