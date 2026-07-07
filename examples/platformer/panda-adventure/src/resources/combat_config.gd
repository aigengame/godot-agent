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
## PlayerConfig). Fields group into three concerns: the damage-formula params
## (consumed by CombatSystem.compute_damage), the i-frame window, and the
## Projectile blockout + motion + hit-flash juice. The projectile_size box is
## AUTHORED in scale_spec.json (gADR-0013) and composed in by the builder; the
## legacy S2 static-enemy block (superseded by wave spawning since S4) was
## deleted with that migration.

# Damage-formula params — pure inputs to CombatSystem.compute_damage:
# maxf(min_damage, attack * attack_scale - defense * defense_scale).
@export var attack_scale: float
@export var defense_scale: float
@export var min_damage: float

# Seconds of invulnerability a defender gets after a landed hit (i-frames), so a
# single overlap cannot chain hits across consecutive frames.
@export var iframe_duration: float

# Projectile block — the Laser Gun bolt (blockout + manual straight-line motion).
# projectile_asset is the optional view asset reference (P2-S2, #436): the
# ViewBuilder resolves a non-empty reference to the (future) sprite, an empty
# one to the colored-block fallback. Authored empty until an asset slice fills
# it (asset references are data, gADR-0000).
@export var projectile_color: Color
@export var projectile_size: Vector2
@export var projectile_asset: String
@export var projectile_speed: float
@export var projectile_lifetime: float
# Spawn offset from the Player origin; x is scaled by the Player's facing.
@export var projectile_spawn_offset: Vector2

# Hit "juice": the modulate flash applied on a landed hit and the seconds the
# tween takes to recover it (the S2 sibling of S1's landing squash).
@export var hit_flash_color: Color
@export var hit_flash_duration: float
