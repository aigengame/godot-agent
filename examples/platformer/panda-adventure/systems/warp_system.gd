class_name WarpSystem
extends RefCounted

## The pure Warp-kit decisions for S8 (gADR-0009): the warp gate, the blink
## landing point, and the Time Dilation Field membership check.
##
## Every function is static, deterministic, and node/physics/clock-free — a
## pure mapping from positions, caller-supplied rule parameters, and
## caller-supplied time to a decision (the CombatSystem/EnemyAI shape,
## gADR-0001/gADR-0003), so the logic seam exercises them headless. The
## controller orchestrates (clock, the tell/recovery phases, tween, log,
## spawning the field); decisions live only here.

## Whether this kind carries the Warp kit at all: the presence-gated block
## (gADR-0009) floors warp_cooldown strictly above 0 at the data seam, so a
## kind without the block reads the type default 0.0 — the has-Warp predicate.
static func has_warp(warp_cooldown: float) -> bool:
	return warp_cooldown > 0.0


## The warp gate: cast only when the kind HAS the kit, the Player is inside
## the Aggro Range (dormant enemies stay dormant — the gADR-0003 contract)
## but FARTHER than the trigger range (the Blink is an anti-kite engage tool:
## the Boss never warps inside a brawl), and the cooldown has elapsed. An
## enemy that never warped uses the -INF sentinel (the is_attack_ready
## contract), so its first warp is gated by distance alone.
static func should_warp(
	self_pos: Vector2,
	player_pos: Vector2,
	aggro_range: float,
	warp_trigger_range: float,
	warp_cooldown: float,
	last_warp_time: float,
	now: float,
) -> bool:
	if not has_warp(warp_cooldown):
		return false
	var distance := self_pos.distance_to(player_pos)
	if distance > aggro_range:
		return false
	if distance <= warp_trigger_range:
		return false
	return (now - last_warp_time) >= warp_cooldown


## The deterministic blink landing (gADR-0009): x lands the configured offset
## on the Player's FAR side from the caster (cutting off the retreat — the
## Boss appears ahead of the fleeing Player), clamped to the arena's x range;
## y is the Player's y plus the offset's y. A Player exactly overhead
## (dx == 0) resolves to the +x side, so the same inputs always land the same
## spot (never random).
static func warp_landing(
	self_pos: Vector2,
	player_pos: Vector2,
	warp_offset: Vector2,
	arena_min_x: float,
	arena_max_x: float,
) -> Vector2:
	var side := signf(player_pos.x - self_pos.x)
	if side == 0.0:
		side = 1.0
	var x := clampf(
		player_pos.x + side * warp_offset.x, arena_min_x, arena_max_x
	)
	return Vector2(x, player_pos.y + warp_offset.y)


## Time Dilation Field membership: inside the zone at (or within) its radius.
## The field controller's per-frame overlap is the physics mirror of this
## rule; the logic seam and the offline sim use the pure form.
static func is_inside_field(
	pos: Vector2, field_center: Vector2, radius: float
) -> bool:
	return pos.distance_to(field_center) <= radius
