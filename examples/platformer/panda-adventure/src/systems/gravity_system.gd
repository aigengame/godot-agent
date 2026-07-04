class_name GravitySystem
extends RefCounted

## The pure gravity-field decisions for S3 (gADR-0002): the field velocity and
## the clamped-displacement integration.
##
## Every function here is static, deterministic, and node/physics/clock-free —
## the gADR-0001 decision shape. The Gravity Field controller and the
## gravity-affectable bodies orchestrate (overlap scan, position mutation,
## tween, log); decisions live only here, so the logic seam (and any future
## balancing sim) exercises the same rules the runtime uses.


## The field's velocity from its data params: direction, normalized so strength
## stays the single magnitude authority, scaled by strength (px/s). Lift, slam,
## and redirect are DATA — different directions through this one function,
## never separate code paths (gADR-0002). A zero direction yields a null field
## (Vector2.ZERO) rather than a NaN from normalizing a zero vector.
static func compute_field_velocity(direction: Vector2, strength: float) -> Vector2:
	if direction.is_zero_approx():
		return Vector2.ZERO
	return direction.normalized() * strength


## Clamped-displacement integration for a static gravity-affectable body: one
## physics frame advances the accumulated offset by field_velocity * delta, and
## the TOTAL offset length is clamped to max_offset — a field can lift, slam,
## or redirect a static block, but never fling it off-level. The body applies
## the delta between the returned and the stored offset to its position, then
## stores the new offset.
static func compute_clamped_offset(
	offset: Vector2, field_velocity: Vector2, delta: float, max_offset: float
) -> Vector2:
	return (offset + field_velocity * delta).limit_length(max_offset)
