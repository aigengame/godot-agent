extends SceneTree

## Logic seam (a) for S1: exercise PlayerController.compute_velocity — the PURE
## movement decision (velocity in -> velocity out, no node/physics access) —
## headless.
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_player_logic.gd
## or directly:
##   godot --headless --path <project> --script res://tests/gdscript/test_player_logic.gd
##
## preload() the scripts (a headless runtime has no editor-generated
## global_script_class_cache, so bare class_name types would not resolve),
## construct an in-memory PlayerConfig with KNOWN values, and assert each movement
## behavior. Prints "LOGIC_SEAM: PASS" + quit(0) on success, else push_error +
## quit(1).

const PlayerConfigScript := preload("res://src/resources/player_config.gd")
const PlayerControllerScript := preload("res://src/controllers/player_controller.gd")

# A fixed config so every expectation is exact (Godot +Y-down: jump is negative).
const MOVE_SPEED := 300.0
const JUMP_VELOCITY := -650.0
const GRAVITY := 1400.0
const MAX_FALL_SPEED := 1200.0


func _make_config() -> PlayerConfigScript:
	var c := PlayerConfigScript.new()
	c.move_speed = MOVE_SPEED
	c.jump_velocity = JUMP_VELOCITY
	c.gravity = GRAVITY
	c.max_fall_speed = MAX_FALL_SPEED
	return c


func _fail(msg: String) -> void:
	push_error("LOGIC_SEAM: " + msg)
	quit(1)


func _init() -> void:
	var config := _make_config()

	# Behavior 1 — horizontal: velocity.x is input_dir * move_speed, both directions.
	var right := PlayerControllerScript.compute_velocity(
		Vector2.ZERO, 1.0, false, true, config, 0.1
	)
	if not is_equal_approx(right.x, MOVE_SPEED):
		_fail("move right: expected x=%s, got %s" % [MOVE_SPEED, right.x])
		return
	var left := PlayerControllerScript.compute_velocity(
		Vector2.ZERO, -1.0, false, true, config, 0.1
	)
	if not is_equal_approx(left.x, -MOVE_SPEED):
		_fail("move left: expected x=%s, got %s" % [-MOVE_SPEED, left.x])
		return
	var idle := PlayerControllerScript.compute_velocity(
		Vector2(MOVE_SPEED, 0.0), 0.0, false, true, config, 0.1
	)
	if not is_equal_approx(idle.x, 0.0):
		_fail("no input: expected x=0, got %s" % idle.x)
		return

	# Behavior 2 — jump: on the floor with jump pressed sets velocity.y upward.
	var jump := PlayerControllerScript.compute_velocity(
		Vector2.ZERO, 0.0, true, true, config, 0.1
	)
	if not is_equal_approx(jump.y, JUMP_VELOCITY):
		_fail("jump on floor: expected y=%s, got %s" % [JUMP_VELOCITY, jump.y])
		return

	# Behavior 3 — gravity: airborne accumulates downward velocity by gravity*delta.
	var falling := PlayerControllerScript.compute_velocity(
		Vector2.ZERO, 0.0, false, false, config, 0.1
	)
	if not is_equal_approx(falling.y, GRAVITY * 0.1):
		_fail("gravity: expected y=%s, got %s" % [GRAVITY * 0.1, falling.y])
		return
	# ...and is capped at max_fall_speed (terminal velocity).
	var terminal := PlayerControllerScript.compute_velocity(
		Vector2(0.0, MAX_FALL_SPEED - 10.0), 0.0, false, false, config, 0.1
	)
	if not is_equal_approx(terminal.y, MAX_FALL_SPEED):
		_fail("terminal velocity: expected y=%s, got %s" % [MAX_FALL_SPEED, terminal.y])
		return

	# Behavior 4 — landing: touching the floor while falling zeroes downward velocity.
	var landed := PlayerControllerScript.compute_velocity(
		Vector2(0.0, 500.0), 0.0, false, true, config, 0.1
	)
	if not is_equal_approx(landed.y, 0.0):
		_fail("landing: expected y=0, got %s" % landed.y)
		return

	# Behavior 5 — no double-jump: pressing jump while airborne does NOT jump; the
	# frame just falls under gravity.
	var air_jump := PlayerControllerScript.compute_velocity(
		Vector2.ZERO, 0.0, true, false, config, 0.1
	)
	if is_equal_approx(air_jump.y, JUMP_VELOCITY):
		_fail("double-jump: airborne jump should be ignored, got y=%s" % air_jump.y)
		return
	if not is_equal_approx(air_jump.y, GRAVITY * 0.1):
		_fail("airborne jump: expected gravity y=%s, got %s" % [GRAVITY * 0.1, air_jump.y])
		return

	print("LOGIC_SEAM: PASS")
	quit(0)
