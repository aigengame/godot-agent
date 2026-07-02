class_name StatsConfig
extends Resource

## The per-actor-kind stat block for S2 combat (gADR-0001).
##
## This Resource is a DERIVED artifact: it is regenerated from the authoritative
## data/json/combat_config.json (its player_stats / enemy_stats blocks) by
## scripts/build_config.py and emitted to data/generated/stats_player.tres and
## stats_enemy.tres. Never hand-edit the generated .tres or hardcode these
## values — change the JSON (gADR-0000).
##
## Player and Enemy carry the SAME type: this is the symmetric attacker/defender
## shape of the damage formula (CombatSystem.compute_damage), so S4's
## enemy->Player damage reuses the formula unchanged. Immutable at runtime —
## live HP/MP mutate on a per-actor StatsSystem instead (gADR-0001).
##
## The @export fields carry NO default literals on purpose: a default would read
## as a second config source competing with the authoritative JSON (gADR-0000).

@export var max_hp: float
@export var max_mp: float
@export var attack: float
# Defense/mitigation term of the damage formula. 0 until the Spacesuit exists.
@export var defense: float
