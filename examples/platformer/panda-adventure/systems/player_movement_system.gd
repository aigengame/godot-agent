class_name PlayerMovementSystem
extends RefCounted

## Pure Player movement decisions. Content reads input and applies physics;
## this System owns the reusable velocity and facing rules without loading
## project-specific configuration Resources.
##
## Godot uses +Y down: jump velocity is negative and gravity is positive. Time
## dilation is full slow motion (gADR-0009): speed and jump impulse scale by the
## factor, while gravity scales by its square. This preserves jump height
## (v^2 / 2g) while tracing the same arc at 1/factor pace. Input still takes
## effect immediately, so the Player is slowed rather than stunned.


static func compute_velocity(
	velocity: Vector2,
	input_dir: float,
	jump_pressed: bool,
	on_floor: bool,
	move_speed: float,
	jump_velocity: float,
	gravity: float,
	max_fall_speed: float,
	delta: float,
	time_scale: float = 1.0,
) -> Vector2:
	var next := velocity
	next.x = input_dir * move_speed * time_scale
	if on_floor:
		if next.y > 0.0:
			next.y = 0.0
		if jump_pressed:
			next.y = jump_velocity * time_scale
	else:
		next.y += gravity * time_scale * time_scale * delta
		if next.y > max_fall_speed * time_scale:
			next.y = max_fall_speed * time_scale
	return next


static func compute_facing(facing: float, input_dir: float) -> float:
	return signf(input_dir) if input_dir != 0.0 else facing
