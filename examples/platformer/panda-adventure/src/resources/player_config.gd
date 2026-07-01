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
## Fields group into four concerns: the Player block (visual + spawn), its
## movement params (consumed by PlayerController.compute_velocity), the Platform
## block it lands on, and the follow-Camera smoothing.

# Player block — the spacesuit-panda blockout (GAME-CONTEXT: Player).
@export var player_color: Color
@export var player_size: Vector2
@export var player_start: Vector2

# Movement params — the pure inputs to PlayerController.compute_velocity. Godot's
# +Y-down convention: jump_velocity is negative (upward), gravity is positive.
@export var move_speed: float
@export var jump_velocity: float
@export var gravity: float
@export var max_fall_speed: float

# Platform block — the Great-Wall rampart the Player collides with and lands on.
@export var platform_color: Color
@export var platform_size: Vector2
@export var platform_position: Vector2

# Follow-camera smoothing (Camera2D.position_smoothing_speed): higher = snappier.
@export var camera_smoothing_speed: float
