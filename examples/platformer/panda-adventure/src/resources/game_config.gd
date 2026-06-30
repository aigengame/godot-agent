class_name GameConfig
extends Resource

## Typed boot configuration for the walking skeleton.
##
## This Resource is a DERIVED artifact: it is regenerated from the authoritative
## data/json/boot_config.json by scripts/build_config.py (validated against
## data/schema/boot_config.schema.json) and emitted to
## data/generated/boot_config.tres. Never hand-edit the generated .tres or
## hardcode these values — change the JSON (gADR-0000: JSON is the single
## authoritative config source).
##
## The @export fields carry NO default literals on purpose: a default would read
## as a second config source competing with the authoritative JSON (gADR-0000).
## The committed .tres sets every field, so the runtime value always comes from
## data.

@export var block_color: Color
@export var block_size: Vector2
@export var start_position: Vector2
@export var target_position: Vector2
@export var tween_duration: float
