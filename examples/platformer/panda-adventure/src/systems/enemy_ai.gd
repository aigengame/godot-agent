class_name EnemyAI
extends RefCounted

## The pure Archetype-AI decisions for S4 (gADR-0003): steering and attack
## gating.
##
## Every function is static, deterministic, and node/physics/clock-free — a pure
## mapping from positions, the kind's EnemyConfig params, and caller-supplied
## time to a decision (the same shape as CombatSystem, gADR-0001), so the logic
## seam exercises them headless and the offline balancing sim can reuse them
## with a simulated clock. Controllers orchestrate (read the real clock,
## integrate velocity, spawn bolts, tween, log); decisions live only here.
##
## Steering is ONE band rule parametrized by data: close in while the Player is
## beyond the Steering Band, back off inside it, hold within it. Melee
## (keep_range_min = 0) and Ranged (a standoff band) are the same rule with
## different config. Tank is representable in the data model but its AI behavior
## is DEFERRED (gADR-0003): it neither moves nor attacks in Phase 1.

const EnemyConfigScript := preload("res://src/resources/enemy_config.gd")


## The horizontal steering decision: -1 (left) / 0 (hold) / 1 (right). Dormant
## beyond the Aggro Range; otherwise steer toward the Player while farther than
## keep_range_max, away while closer than keep_range_min, hold inside the band.
## Distance is the full 2D distance; the returned direction is horizontal (the
## enemy is a grounded platformer body). A Player directly above (dx == 0)
## yields 0 — there is nowhere to steer horizontally.
static func compute_move_dir(
	self_pos: Vector2, player_pos: Vector2, config: EnemyConfigScript
) -> float:
	if config.archetype == "tank":
		return 0.0  # Tank AI deferred (gADR-0003) — representable, no behavior.
	var distance := self_pos.distance_to(player_pos)
	if distance > config.aggro_range:
		return 0.0
	var toward := signf(player_pos.x - self_pos.x)
	if distance > config.keep_range_max:
		return toward
	if distance < config.keep_range_min:
		return -toward
	return 0.0


## The attack-cooldown gate: ready once `cooldown` seconds have elapsed since
## the last attack. An enemy that never attacked uses the -INF sentinel
## (elapsed = INF -> always ready), mirroring CombatSystem.is_invulnerable's
## sentinel contract.
static func is_attack_ready(last_attack_time: float, now: float, cooldown: float) -> bool:
	return (now - last_attack_time) >= cooldown


## The full attack decision: the Player must be inside BOTH the Aggro Range and
## the attack range, and the cooldown must have elapsed. Archetype-agnostic by
## design — what differs per archetype is the attack DELIVERY (contact hit vs
## bolt), which the controller owns; Tank never attacks (deferred, gADR-0003).
static func can_attack(
	self_pos: Vector2,
	player_pos: Vector2,
	config: EnemyConfigScript,
	last_attack_time: float,
	now: float,
) -> bool:
	if config.archetype == "tank":
		return false  # Tank AI deferred (gADR-0003).
	var distance := self_pos.distance_to(player_pos)
	if distance > config.aggro_range or distance > config.attack_range:
		return false
	return is_attack_ready(last_attack_time, now, config.attack_cooldown)
