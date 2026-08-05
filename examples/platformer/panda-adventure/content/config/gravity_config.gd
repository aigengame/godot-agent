class_name GravityConfig
extends Resource

## Typed gravity configuration for S3 (Gravity Gun + Gravity Field + MP economy).
##
## This Resource is a DERIVED artifact: it is regenerated from the authoritative
## content/data/json/gravity_config.json by scripts/build_config.py (validated against
## content/data/schema/gravity_config.schema.json) and emitted to
## content/data/generated/gravity_config.tres. Never hand-edit the generated .tres or
## hardcode these values — change the JSON (gADR-0000).
##
## The field's EFFECT is data (gADR-0002): direction x strength is the field
## velocity, radius/duration bound it in space and time — lift is the shipped
## fire default; slam/redirect are different values of the same fields, never
## separate code paths.
##
## The @export fields carry NO default literals on purpose: a default would read
## as a second config source competing with the authoritative JSON (gADR-0000).

# MP economy — firing the Gravity Gun is the game's only MP sink. The Wine
# restore that refills this budget lives in ItemsConfig since S7 (gADR-0008:
# one items authority; wine_mp_restore migrated out of this source).
@export var mp_cost: float

# Gravity Field params — the data-driven effect (gADR-0002): velocity =
# direction.normalized() * strength (px/s), acting within radius for duration
# seconds. Godot is +Y-down: lift = (0, -1), slam = (0, 1).
@export var field_direction: Vector2
@export var field_strength: float
@export var field_radius: float
@export var field_duration: float

# Field blockout + juice: the translucent block color, the spawn/expiry fade
# tween seconds, and the spawn offset from the Player origin (x scaled by
# facing, like the Projectile). field_asset is the optional view asset
# reference (P2-S2, #436): the ViewBuilder resolves a non-empty reference to
# the (future) sprite, an empty one to the colored-block fallback. Authored
# empty until an asset slice fills it (asset references are data, gADR-0000).
@export var field_color: Color
@export var field_asset: String
@export var field_fade_duration: float
@export var field_spawn_offset: Vector2

# Gravity-response clamp for the static Enemy (gADR-0002): the max total
# displacement fields can accumulate on it (clamped-displacement integration).
@export var enemy_max_gravity_offset: float

# Obstacle block — the gravity-affectable environment prop (terrain layer):
# blockout, placement, and its own displacement clamp. obstacle_asset is the
# optional view asset reference (P2-S2, #436; the field_asset pattern).
@export var obstacle_color: Color
@export var obstacle_size: Vector2
@export var obstacle_asset: String
@export var obstacle_position: Vector2
@export var obstacle_max_gravity_offset: float
