class_name LevelConfig
extends Resource

## Typed level configuration for S9 (gADR-0010): the level authority.
##
## This Resource is a DERIVED artifact: it is regenerated from the authoritative
## data/json/level_config.json by scripts/build_config.py (validated against
## data/schema/level_config.schema.json) and emitted to
## data/generated/level_config.tres. Never hand-edit the generated .tres or
## hardcode these values — change the JSON (gADR-0000: JSON is the single
## authoritative config source).
##
## The @export fields carry NO default literals on purpose: a default would read
## as a second config source competing with the authoritative JSON (gADR-0000).
## The committed .tres sets every field, so the runtime value always comes from
## data.
##
## Fields group into four concerns: the backdrop, the Great-Wall blockout
## (consumed by LevelController's segment instancing), the Arena interval
## (consumed by EnemyController's Warp-landing clamp), and the End screen's
## blockout numbers (consumed by EndScreenController).

# Backdrop — the black-hole-edge clear color behind the wall.
@export var background_color: Color

# Great-Wall blockout (GAME-CONTEXT: Great-Wall blockout): one shared segment
# color, and the ordered segments themselves. Each element of `platforms` is a
# Dictionary {"name": String, "position": Vector2, "size": Vector2} — a named
# rampart/tower/parapet block the level runtime-instances (gADR-0010).
@export var platform_color: Color
@export var platforms: Array

# Arena (GAME-CONTEXT: Arena): the authored combat span whose x interval clamps
# the Warp Blink's landing (gADR-0010, replacing the S8 platform-extent
# derivation).
@export var arena_min_x: float
@export var arena_max_x: float

# End screen blockout (GAME-CONTEXT: End screen): the full-screen dim, the two
# verdict title colors, the label font sizes, and the fade-in tween duration.
@export var end_overlay_color: Color
@export var end_win_color: Color
@export var end_lose_color: Color
@export var end_title_font_size: float
@export var end_hint_font_size: float
@export var end_fade_duration: float
