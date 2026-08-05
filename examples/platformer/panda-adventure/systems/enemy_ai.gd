class_name EnemyAI
extends RefCounted

## The pure Archetype-AI decisions for S4 (gADR-0003): steering and attack
## gating.
##
## Every function is static, deterministic, and node/physics/clock-free — a pure
## mapping from positions, caller-supplied rule parameters, and time
## time to a decision (the same shape as CombatSystem, gADR-0001), so the logic
## seam exercises them headless and the offline balancing sim can reuse them
## with a simulated clock. Controllers orchestrate (read the real clock,
## integrate velocity, spawn bolts, tween, log); decisions live only here.
##
## Steering is ONE band rule parametrized by data: close in while the Player is
## beyond the Steering Band, back off inside it, hold within it. Melee
## (keep_range_min = 0) and Ranged (a standoff band) are the same rule with
## different config — and since S8 (gADR-0009) so is Tank: its gADR-0003
## deferral is lifted with NO Tank-specific branch, the slow heavy hammer
## emerging purely from its data (move_speed, band, attack stats). The Boss's
## Warp kit is a separate presence-gated ability (WarpSystem), not an
## archetype behavior.

## The horizontal steering decision: -1 (left) / 0 (hold) / 1 (right). Dormant
## beyond the Aggro Range; otherwise steer toward the Player while farther than
## keep_range_max, away while closer than keep_range_min, hold inside the band.
## Distance is the full 2D distance; the returned direction is horizontal (the
## enemy is a grounded platformer body). A Player directly above (dx == 0)
## yields 0 — there is nowhere to steer horizontally.
static func compute_move_dir(
	self_pos: Vector2,
	player_pos: Vector2,
	aggro_range: float,
	keep_range_min: float,
	keep_range_max: float,
) -> float:
	var distance := self_pos.distance_to(player_pos)
	if distance > aggro_range:
		return 0.0
	var toward := signf(player_pos.x - self_pos.x)
	if distance > keep_range_max:
		return toward
	if distance < keep_range_min:
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
## bolt), which the controller owns; Tank hits by contact, the Melee delivery
## (un-deferred by S8, gADR-0009).
static func can_attack(
	self_pos: Vector2,
	player_pos: Vector2,
	aggro_range: float,
	attack_range: float,
	attack_cooldown: float,
	last_attack_time: float,
	now: float,
) -> bool:
	var distance := self_pos.distance_to(player_pos)
	if distance > aggro_range or distance > attack_range:
		return false
	return is_attack_ready(last_attack_time, now, attack_cooldown)
