class_name CombatConfig
extends Resource

## Typed combat configuration for S2 (Laser Gun combat).
##
## This Resource is a DERIVED artifact: it is regenerated from the authoritative
## data/json/combat_config.json by scripts/build_config.py (validated against
## data/schema/combat_config.schema.json) and emitted to
## data/generated/combat_config.tres. Never hand-edit the generated .tres or
## hardcode these values — change the JSON (gADR-0000).
##
## The @export fields carry NO default literals on purpose (gADR-0000; see
## PlayerConfig). Fields group into four concerns: the damage-formula params
## (consumed by CombatSystem.compute_damage), the i-frame window, the Projectile
## blockout + motion, and the S2 static Enemy blockout + hit-flash juice.

# Damage-formula params — pure inputs to CombatSystem.compute_damage:
# maxf(min_damage, attack * attack_scale - defense * defense_scale).
@export var attack_scale: float
@export var defense_scale: float
@export var min_damage: float

# Seconds of invulnerability a defender gets after a landed hit (i-frames), so a
# single overlap cannot chain hits across consecutive frames.
@export var iframe_duration: float

# Projectile block — the Laser Gun bolt (blockout + manual straight-line motion).
@export var projectile_color: Color
@export var projectile_size: Vector2
@export var projectile_speed: float
@export var projectile_lifetime: float
# Spawn offset from the Player origin; x is scaled by the Player's facing.
@export var projectile_spawn_offset: Vector2

# Enemy block — the S2 static target (S4 replaces placement with wave spawning).
@export var enemy_color: Color
@export var enemy_size: Vector2
@export var enemy_position: Vector2

# Hit "juice": the modulate flash applied on a landed hit and the seconds the
# tween takes to recover it (the S2 sibling of S1's landing squash).
@export var hit_flash_color: Color
@export var hit_flash_duration: float
