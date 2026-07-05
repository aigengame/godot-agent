class_name ItemSystem
extends RefCounted

## The pure Items & Equipment decisions for S7 (gADR-0008): Consumable supply
## gating and worn-Equipment defense composition.
##
## Every function here is static, deterministic, and node/physics/clock-free —
## the CombatSystem purity contract (gADR-0001), so the offline Monte-Carlo
## balancing pipeline can consume counts and compose defenders with the real
## rules. Controllers orchestrate (own the _items Dictionary, mutate their
## StatsSystem, tween, log); decisions live only here.

const StatsConfigScript := preload("res://src/resources/stats_config.gd")


## The Consumable supply gate: a use verb may fire iff at least one is held.
## Supply is the ONLY input — using at full HP/MP is legal (the restore cap
## bounds the effect; gADR-0008's one-input gate).
static func can_consume(count: int) -> bool:
	return count > 0


## The count after one Consumable is used up. Callers gate on can_consume
## first; the floor at 0 keeps a miscounted hook from ever going negative.
static func consumed(count: int) -> int:
	return maxi(count - 1, 0)


## Compose the effective defender for the damage formula's mitigation term:
## a FRESH stat block copying `base` with `defense` raised by the worn
## Equipment's bonus (the Spacesuit). The base Resource is load()-aliased
## immutable config (gADR-0001) and is NEVER mutated — CombatSystem.
## compute_damage keeps its symmetric stat-block contract untouched.
static func effective_defender(
	base: StatsConfigScript, defense_bonus: float
) -> StatsConfigScript:
	var composed := StatsConfigScript.new()
	composed.max_hp = base.max_hp
	composed.max_mp = base.max_mp
	composed.attack = base.attack
	composed.defense = base.defense + defense_bonus
	return composed
