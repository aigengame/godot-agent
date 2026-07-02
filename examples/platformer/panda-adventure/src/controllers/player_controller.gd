class_name PlayerController
extends CharacterBody2D

## Drives the Player block: applies its data-driven blockout in _ready, reads the
## InputMap each physics frame, feeds it to the PURE compute_velocity decision,
## and applies the result with move_and_slide. A landing squash-stretch tween is
## the blockout "animation" (property interpolation, gADR/GDD).
##
## S2 adds the Laser Gun: the `fire` action spawns a Projectile bolt aimed by
## the facing (pure compute_facing over the same input axis), carrying the
## Player's StatsConfig stat block as the attacker for the damage formula. The
## Player owns its live StatsSystem (all four stats; HP untouched until S4's
## enemy->Player damage).
##
## Movement params and visuals are data (gADR-0000): a derived PlayerConfig
## Resource, never hardcoded. compute_velocity is static and node-free so the
## logic seam can exercise it headless (tests/gdscript/test_player_logic.gd via
## `gda script run`).
##
## Cross-script references use preload() rather than the global class_name
## registry: this project has no editor-generated global_script_class_cache, so a
## bare PlayerConfig type name would not resolve in a headless runtime.

const PlayerConfigScript := preload("res://src/resources/player_config.gd")
const StatsConfigScript := preload("res://src/resources/stats_config.gd")
const CombatConfigScript := preload("res://src/resources/combat_config.gd")
const StatsSystemScript := preload("res://src/systems/stats_system.gd")
const GameLogScript := preload("res://src/util/game_log.gd")
const ProjectileScene := preload("res://scenes/projectile.tscn")

const CONFIG_PATH := "res://data/generated/player_config.tres"
const STATS_PATH := "res://data/generated/stats_player.tres"
const COMBAT_CONFIG_PATH := "res://data/generated/combat_config.tres"

var _config: PlayerConfigScript
var _stats_config: StatsConfigScript
var _combat: CombatConfigScript
var _stats: StatsSystemScript
# Current aim (-1 left / 1 right); spawn faces right (structural, not config).
var _facing := 1.0


## Pure movement decision (no node/physics access): given the current velocity,
## the horizontal input axis (-1..1), whether jump fired this frame, whether the
## body is on the floor, the config, and the physics delta, return the next
## velocity. Godot is +Y-down: jump_velocity is negative (up), gravity positive.
static func compute_velocity(
	velocity: Vector2,
	input_dir: float,
	jump_pressed: bool,
	on_floor: bool,
	config: PlayerConfigScript,
	delta: float
) -> Vector2:
	var v := velocity
	# Horizontal is driven straight from input — instantaneous for the blockout.
	v.x = input_dir * config.move_speed
	# Vertical: jump only from the floor (no double-jump in this slice); when
	# airborne, accumulate gravity, capped at terminal velocity.
	if on_floor:
		# Just landed: shed the downward velocity so it does not accumulate.
		if v.y > 0.0:
			v.y = 0.0
		if jump_pressed:
			v.y = config.jump_velocity
	else:
		v.y += config.gravity * delta
		if v.y > config.max_fall_speed:
			v.y = config.max_fall_speed
	return v


## Pure facing decision: a nonzero horizontal input re-aims the Player
## (sign-normalized to -1/1), zero input preserves the current facing. Drives
## the Laser Gun's projectile direction; the spawn facing (1.0, rightward) is
## structural, not config.
static func compute_facing(facing: float, input_dir: float) -> float:
	return signf(input_dir) if input_dir != 0.0 else facing


func _ready() -> void:
	_config = load(CONFIG_PATH)
	_stats_config = load(STATS_PATH)
	_combat = load(COMBAT_CONFIG_PATH)
	if _config == null or _stats_config == null or _combat == null:
		# The derived .tres are committed; guard loudly rather than crash on a
		# half-checkout, pointing at the pipeline that regenerates them from JSON.
		push_error(
			"PlayerController: could not load %s / %s / %s — run scripts/build_config.py."
			% [CONFIG_PATH, STATS_PATH, COMBAT_CONFIG_PATH]
		)
		return
	_stats = StatsSystemScript.new()
	_stats.init_from(_stats_config)
	_apply_blockout(_config)
	GameLogScript.emit("info", "player_ready", {
		"move_speed": _config.move_speed,
		"jump_velocity": _config.jump_velocity,
		"max_hp": _stats_config.max_hp,
	})


## Apply the data-driven blockout: the Player block (visual + collision centered
## on the body origin), spawn position, and follow-camera smoothing. All from
## config — nothing hardcoded.
func _apply_blockout(config: PlayerConfigScript) -> void:
	var half := config.player_size / 2.0

	var visual := $Visual as ColorRect
	visual.color = config.player_color
	visual.size = config.player_size
	visual.position = -half
	visual.pivot_offset = half  # scale/tween about the block center

	var shape := ($Collision as CollisionShape2D).shape as RectangleShape2D
	shape.size = config.player_size

	position = config.player_start

	var cam := $Camera2D as Camera2D
	cam.position_smoothing_enabled = true
	cam.position_smoothing_speed = config.camera_smoothing_speed


func _physics_process(delta: float) -> void:
	if _config == null:
		return
	var input_dir := Input.get_axis("move_left", "move_right")
	var jump_pressed := Input.is_action_just_pressed("jump")
	var was_on_floor := is_on_floor()

	_facing = compute_facing(_facing, input_dir)
	velocity = compute_velocity(velocity, input_dir, jump_pressed, was_on_floor, _config, delta)
	move_and_slide()

	# Landing this frame (airborne last frame, on the floor now) → play the squash.
	if is_on_floor() and not was_on_floor:
		_play_landing_tween()

	if Input.is_action_just_pressed("fire"):
		_fire()


## Fire the Laser Gun: spawn one Projectile bolt aimed by the facing, offset
## from the Player origin, carrying the Player's stat block as the attacker.
## The bolt is a child of the Player's PARENT (the level), so it flies in world
## space instead of inheriting the Player's movement. One press = one bolt.
func _fire() -> void:
	if _stats_config == null or _combat == null:
		return
	var bolt := ProjectileScene.instantiate()
	bolt.setup(Vector2(_facing, 0.0), _stats_config)
	var offset := _combat.projectile_spawn_offset
	bolt.position = position + Vector2(_facing * offset.x, offset.y)
	get_parent().add_child(bolt)
	GameLogScript.emit("info", "laser_fired", {
		"facing": _facing,
		"spawn_x": bolt.position.x,
		"spawn_y": bolt.position.y,
	})


## The blockout "animation": a brief squash-stretch of the Player block on landing
## (a property-tween, per the GDD — no authored sprite frames).
func _play_landing_tween() -> void:
	var visual := $Visual as ColorRect
	visual.scale = _config.landing_squash
	var tween := create_tween()
	var recover := tween.tween_property(visual, "scale", Vector2.ONE, _config.landing_tween_duration)
	recover.set_trans(Tween.TRANS_SINE)
	GameLogScript.emit("info", "player_land", {"floor_y": position.y})
