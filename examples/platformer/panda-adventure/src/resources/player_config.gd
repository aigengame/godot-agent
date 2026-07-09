class_name PlayerConfig
extends Resource

## Typed level+player configuration for S1 (player traversal).
##
## This Resource is a DERIVED artifact: it is regenerated from the authoritative
## data/json/player_config.json by scripts/build_config.py (validated against
## data/schema/player_config.schema.json) and emitted to
## data/generated/player_config.tres. Never hand-edit the generated .tres or
## hardcode these values — change the JSON (gADR-0000: JSON is the single
## authoritative config source).
##
## The @export fields carry NO default literals on purpose: a default would read
## as a second config source competing with the authoritative JSON (gADR-0000).
## The committed .tres sets every field, so the runtime value always comes from
## data.
##
## Fields group into three concerns: the Player block (visual + spawn), its
## movement params (consumed by PlayerController.compute_velocity), and the
## follow-Camera smoothing. The Platform blockout migrated OUT to the level
## authority (LevelConfig) in S9 — gADR-0010.

# Player block — the spacesuit-panda blockout (GAME-CONTEXT: Player).
# player_asset is the optional view asset reference (P2-S2, #436): the
# ViewBuilder resolves a non-empty reference to the (future) sprite, an empty
# one to the colored-block fallback. Authored empty until an asset slice fills
# it (asset references are data, gADR-0000).
@export var player_color: Color
@export var player_size: Vector2
@export var player_asset: String
@export var player_start: Vector2

# Movement params — the pure inputs to PlayerController.compute_velocity. Godot's
# +Y-down convention: jump_velocity is negative (upward), gravity is positive.
@export var move_speed: float
@export var jump_velocity: float
@export var gravity: float
@export var max_fall_speed: float

# Follow-camera smoothing (Camera2D.position_smoothing_speed): higher = snappier.
@export var camera_smoothing_speed: float

# Landing "juice": the squash-stretch pose (block scale) and recover-tween seconds.
# SUPERSEDED by the Player sprite animations (P2-S5, #443, gADR-0016): the Player
# landing is now the AnimatedSprite2D's locomotion transition, so no runtime reads
# these. Retained (not deleted) — the editor schema forms (#441/#481) map them, and
# physical removal is a separate gated cleanup.
@export var landing_squash: Vector2
@export var landing_tween_duration: float
