class_name HudConfig
extends Resource

## The HUD blockout's typed config (S6a, gADR-0004): overlay placement and the
## value-change pulse tween. The HUD's CONTENT (live HP/MP/EXP/Gold + Current
## weapon) is fixed by the GDD's "HUD & UI" section; concrete layout/styling
## beyond these numbers is a later asset concern.
##
## This Resource is a DERIVED artifact: it is regenerated from the
## authoritative data/json/hud_config.json by scripts/build_config.py and
## emitted to data/generated/hud_config.tres. Never hand-edit the generated
## .tres or hardcode these values — change the JSON (gADR-0000).
##
## The @export fields carry NO default literals on purpose (see PlayerConfig).

# Offset of the HUD stat column from the viewport's top-left corner.
@export var margin: Vector2
# The value-change "juice": a scale punch tweened back to 1.0 (the landing-
# squash idiom applied to a Label the moment its value changes).
@export var value_punch_scale: Vector2
@export var value_tween_duration: float
