class_name ProgressionConfig
extends Resource

## The S6b progression loop's typed config (gADR-0006): the data-driven
## leveling curve the Player levels up along, and the Drop/Pickup blockout.
##
## `level_curve` is the ordered cumulative EXP thresholds — entry k is the
## total EXP at which the Player reaches level k+2 (level 1 is the start), so
## the MAX level is level_curve.size() + 1: config, never code (the gADR-0005
## waves.size() idiom). `drop_items` maps every droppable item name (gold, and
## the S7 Consumables bun/wine) to its pickup blockout
## {"color": Color, "size": Vector2}; the schema requires all three, so a drop
## table can never reference an unstyled item.
##
## This Resource is a DERIVED artifact: it is regenerated from the
## authoritative data/json/progression_config.json by scripts/build_config.py
## and emitted to data/generated/progression_config.tres. Never hand-edit the
## generated .tres or hardcode these values — change the JSON (gADR-0000).
##
## The @export fields carry NO default literals on purpose (see PlayerConfig).

# The leveling curve: strictly increasing cumulative EXP thresholds
# (build_config.validate_progression_semantics enforces the monotonicity).
@export var level_curve: Array

# The level-up "juice": flash color + tween-back duration.
# SUPERSEDED by the Player sprite animations (P2-S5, #443, gADR-0016): a level rise
# now plays the AnimatedSprite2D "level_up" one-shot, so no runtime reads these.
# Retained (not deleted) — the editor schema forms (#441/#481) map them, and
# physical removal is a separate gated cleanup.
@export var level_up_flash_color: Color
@export var level_up_flash_duration: float

# Pickup blockout per droppable item name: item -> {"color": Color,
# "size": Vector2, "asset": String}. `asset` is the item's optional view asset
# reference (P2-S2, #436): the ViewBuilder resolves a non-empty reference to
# the (future) sprite, an empty one to the colored-block fallback.
@export var drop_items: Dictionary

# The deterministic drop scatter: horizontal spacing between one death's
# Pickups, centered on the death position (EconomySystem.drop_offset).
@export var pickup_spacing: float

# Pickup juice: the spawn-telegraph squash (the gADR-0005 idiom) and the
# collected block's shrink-to-nothing tween.
@export var pickup_spawn_squash: Vector2
@export var pickup_spawn_tween_duration: float
@export var pickup_collect_tween_duration: float
