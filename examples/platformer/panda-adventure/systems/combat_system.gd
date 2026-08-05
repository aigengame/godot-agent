class_name CombatSystem
extends RefCounted

## The pure combat decisions for S2 (gADR-0001): damage, i-frames, death.
##
## Every function here is static, deterministic, and node/physics/clock-free —
## a pure mapping from stat data and caller-supplied rule parameters and
## caller-supplied time to a decision. That purity is load-bearing: the offline
## Monte-Carlo balancing pipeline (gADR-0000) reuses these functions unchanged,
## supplying its own simulated clock. Controllers orchestrate (read the real
## clock, mutate StatsSystem, tween, log); decisions live only here.

const StatsConfigScript := preload("res://systems/stats_config.gd")


## The data-driven damage formula (issue #331): the attacker's scaled attack
## minus the defender's scaled mitigation, floored at min_damage. SYMMETRIC by
## construction — S4's enemy->Player damage is this same call with the roles
## swapped. The defense term contributes 0 until the Spacesuit exists.
static func compute_damage(
	attacker: StatsConfigScript,
	defender: StatsConfigScript,
	attack_scale: float,
	defense_scale: float,
	min_damage: float,
) -> float:
	return maxf(
		min_damage,
		attacker.attack * attack_scale - defender.defense * defense_scale,
	)


## True while the defender is inside its post-hit i-frame window, so a single
## overlap cannot chain hits across consecutive frames. Pure in (last_hit_time,
## now): the runtime passes its clock, the balancing sim passes a simulated one.
## A defender that was never hit uses the -INF sentinel (elapsed = INF -> false).
static func is_invulnerable(
	last_hit_time: float, now: float, iframe_duration: float
) -> bool:
	return (now - last_hit_time) < iframe_duration


## The death rule: an actor dies at exactly 0 HP (StatsSystem clamps there).
static func is_dead(hp: float) -> bool:
	return hp <= 0.0
