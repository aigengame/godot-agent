class_name PlayerMovementSystem
extends RefCounted

## Pure Player movement decisions. Content reads input and applies physics;
## this System owns the reusable velocity and facing rules without loading
## project-specific configuration Resources.


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
