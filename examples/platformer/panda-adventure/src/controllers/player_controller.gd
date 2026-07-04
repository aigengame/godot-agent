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
## S3 adds the Gravity Gun + weapon switch + MP economy (gADR-0002):
## `switch_weapon` toggles which gun `fire` fires (the Laser Gun is the spawn
## default), the Gravity Gun spends MP (StatsSystem.spend_mp — at 0 MP it
## cannot fire) to spawn a Gravity Field, and `drink_wine` restores MP (the
## minimal Wine hook; the full Consumable system is S7). See the S3 block at
## the end of this file.
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
const CombatSystemScript := preload("res://src/systems/combat_system.gd")
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
# S4 damage-receiving state: when the Player last took a hit (-INF = never, so
# the first hit always lands — CombatSystem.is_invulnerable's sentinel), and a
# death latch so player_died is logged exactly once (respawn/game-over is out
# of scope for Phase 1).
var _last_hit_time := -INF
var _dead := false


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
	# S4: enemies find their target by this group (EnemyController._player).
	add_to_group("player")
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

	if Input.is_action_just_pressed("switch_weapon"):
		_switch_weapon()
	if Input.is_action_just_pressed("drink_wine"):
		_drink_wine()
	if Input.is_action_just_pressed("fire"):
		_fire_current_weapon()


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


## S4 damage-receiving path: resolve one incoming hit from an attacker's stat
## block — the SAME symmetric pipeline as the Enemy's (CombatSystem.compute_damage
## with the roles swapped, gADR-0001), i-frame gated so a single overlap cannot
## chain hits. On death: log player_died once; respawn/game-over is out of
## scope for Phase 1 (a later slice owns it).
func take_hit(attacker: StatsConfigScript) -> void:
	if _stats == null or _dead:
		return
	var now := _now()
	if CombatSystemScript.is_invulnerable(_last_hit_time, now, _combat.iframe_duration):
		return
	_last_hit_time = now
	var damage := CombatSystemScript.compute_damage(attacker, _stats_config, _combat)
	_stats.apply_damage(damage)
	GameLogScript.emit("info", "player_hit", {"damage": damage, "hp_left": _stats.hp})
	_play_hit_flash()
	if CombatSystemScript.is_dead(_stats.hp):
		_dead = true
		GameLogScript.emit("info", "player_died", {"x": position.x, "y": position.y})


## The runtime clock feeding the pure i-frame decision; the Monte-Carlo sim
## supplies its own simulated time instead.
func _now() -> float:
	return Time.get_ticks_msec() / 1000.0


## The hit "juice": flash the Player block to the shared hit color and tween
## back to its own color (the same property-tween as the Enemy's, per the GDD).
func _play_hit_flash() -> void:
	var visual := $Visual as ColorRect
	visual.color = _combat.hit_flash_color
	var tween := create_tween()
	var recover := tween.tween_property(
		visual, "color", _config.player_color, _combat.hit_flash_duration
	)
	recover.set_trans(Tween.TRANS_SINE)


## The blockout "animation": a brief squash-stretch of the Player block on landing
## (a property-tween, per the GDD — no authored sprite frames).
func _play_landing_tween() -> void:
	var visual := $Visual as ColorRect
	visual.scale = _config.landing_squash
	var tween := create_tween()
	var recover := tween.tween_property(visual, "scale", Vector2.ONE, _config.landing_tween_duration)
	recover.set_trans(Tween.TRANS_SINE)
	GameLogScript.emit("info", "player_land", {"floor_y": position.y})


# --- S3 Gravity Gun + weapon switch + MP economy (gADR-0002) ------------------
# Kept as ONE self-contained block: S4 adds take_hit/i-frames to this file in
# parallel, so the S3 additions stay append-only (GDScript accepts class-level
# declarations after methods).

const GravityConfigScript := preload("res://src/resources/gravity_config.gd")
const GravityFieldScene := preload("res://scenes/gravity_field.tscn")
const GRAVITY_CONFIG_PATH := "res://data/generated/gravity_config.tres"

# The two Equipment guns `fire` can drive. Structural identifiers (they name
# code paths and log values, not tunable numbers — gADR-0000 governs numbers).
const WEAPON_LASER := "laser_gun"
const WEAPON_GRAVITY := "gravity_gun"

# Current weapon — which gun `fire` fires. The spawn default is the Laser Gun.
var _weapon := WEAPON_LASER
# The derived GravityConfig, lazily loaded (load() is cached) so _ready's S2
# load block stays untouched for the parallel S4 merge.
var _gravity_cfg: GravityConfigScript


## Pure weapon-switch decision: toggle between the two guns. Anything outside
## the two-gun set falls back to the spawn default (Laser Gun), so the state
## can never leave the set.
static func compute_next_weapon(weapon: String) -> String:
	return WEAPON_GRAVITY if weapon == WEAPON_LASER else WEAPON_LASER


## `fire` fires the CURRENT weapon: the Laser Gun spawns a Projectile (_fire,
## S2 unchanged), the Gravity Gun spends MP to spawn a Gravity Field.
func _fire_current_weapon() -> void:
	if _weapon == WEAPON_GRAVITY:
		_fire_gravity_gun()
	else:
		_fire()


func _switch_weapon() -> void:
	_weapon = compute_next_weapon(_weapon)
	GameLogScript.emit("info", "weapon_switched", {"weapon": _weapon})


## Fire the Gravity Gun: spend MP first (StatsSystem.spend_mp is the gate — on
## insufficient MP nothing is spent and no field spawns), then spawn one
## Gravity Field offset from the Player origin by the config offset (x scaled
## by the facing, the Projectile's spawn pattern). The field is a child of the
## Player's PARENT (the level), so it stays fixed in world space.
func _fire_gravity_gun() -> void:
	var cfg := _gravity_config()
	if cfg == null or _stats == null:
		return
	var mp_before := _stats.mp
	if not _stats.spend_mp(cfg.mp_cost):
		GameLogScript.emit("info", "gravity_blocked", {
			"mp": _stats.mp,
			"mp_cost": cfg.mp_cost,
		})
		return
	var field := GravityFieldScene.instantiate()
	var offset := cfg.field_spawn_offset
	field.position = position + Vector2(_facing * offset.x, offset.y)
	get_parent().add_child(field)
	GameLogScript.emit("info", "gravity_fired", {
		"mp_before": mp_before,
		"mp_after": _stats.mp,
		"field_x": field.position.x,
		"field_y": field.position.y,
	})


## Drink Wine — the S3 minimal MP-restore hook (the full Consumable system with
## inventory/counts is S7, so nothing is consumed from anywhere yet): restore
## the config amount, capped at the stat block's max_mp.
func _drink_wine() -> void:
	var cfg := _gravity_config()
	if cfg == null or _stats == null or _stats_config == null:
		return
	var mp_before := _stats.mp
	_stats.restore_mp(cfg.wine_mp_restore, _stats_config.max_mp)
	GameLogScript.emit("info", "wine_drunk", {
		"mp_before": mp_before,
		"mp_after": _stats.mp,
	})


## The derived GravityConfig with the standard loud guard, lazily loaded so the
## S2 _ready block stays untouched.
func _gravity_config() -> GravityConfigScript:
	if _gravity_cfg == null:
		_gravity_cfg = load(GRAVITY_CONFIG_PATH)
		if _gravity_cfg == null:
			push_error(
				"PlayerController: could not load %s — run scripts/build_config.py."
				% GRAVITY_CONFIG_PATH
			)
	return _gravity_cfg
