class_name EnemyWarpDriver
extends RefCounted

## Drives one enemy's Warp rotation (S8, gADR-0009): the three-phase
## (tell -> blink -> recovery) orchestration state machine, extracted from
## EnemyController so the Boss animation (P2-S6) and warp VFX (P2-S7) hook ONE
## home with a public phase() read instead of reaching into _physics_process.
##
## Decisions stay PURE in WarpSystem (the gate and the far-side landing formula,
## gADR-0009 — untouched): this driver only ORCHESTRATES node ops through its
## owning EnemyController — reads the real clock, stamps the cooldown, runs the
## tell/recovery phases, tweens, logs, relocates the body, and drops the Time
## Dilation Field. The spawn-telegraph numbers it replays at the landing are
## SHARED with the non-warp spawn telegraph, so they live on the enemy and are
## read back through the owner (play_spawn_tween / the cached squash).
##
## The owner reference is untyped on purpose: typing it as EnemyController would
## preload back into the controller that preloads this driver (a cycle), and the
## driver only needs the enemy's CharacterBody2D surface (position/velocity/
## move_and_slide/is_on_floor/create_tween/get_parent/get_node) plus a few enemy
## members (_kind, _now, _spawn_squash, play_spawn_tween). A kind without the
## Warp kit (WarpSystem.has_warp false) never opens the gate, so the driver stays
## inert — try_begin always returns false and no phase ever runs.

const WarpSystemScript := preload("res://systems/warp_system.gd")
const LevelConfigScript := preload("res://content/config/level_config.gd")
const GeneratedConfigScript := preload("res://content/config/generated_config.gd")
const GameLogScript := preload("res://addons/game_log/game_log.gd")
const TimeFieldScene := preload("res://content/scenes/time_field.tscn")

const LEVEL_CONFIG_PATH := "res://content/data/generated/level_config.tres"

# The owning enemy (an EnemyController / CharacterBody2D); see the header for why
# it is untyped.
var _enemy

# When this enemy last STARTED a warp (-INF = never, the is_attack_ready
# sentinel: the first warp is gated by distance alone); the current phase
# ("" = none, "tell", "recovery") and when it ends. Phases suspend steering and
# attack — the tell is the telegraph, the recovery is the fair-exchange window.
var _last_warp_time := -INF
var _phase := ""
var _phase_until := 0.0

# The derived LevelConfig (the level authority: the authored Arena interval,
# gADR-0010 — was the PlayerConfig platform extent until S9), lazily loaded for
# the landing's arena clamp.
var _level_config: LevelConfigScript


func _init(enemy) -> void:
	_enemy = enemy


## Whether a Warp phase is currently in flight (its steering/attack suspension is
## active). The public read the animation and VFX edges hook.
func is_active() -> bool:
	return _phase != ""


## The current Warp phase: "" (none), "tell", or "recovery".
func phase() -> String:
	return _phase


## Open the Warp gate if the pure decision allows it (WarpSystem.should_warp:
## has-kit, inside Aggro but outside the trigger range, cooldown elapsed). Begins
## the tell and returns true when a new cast starts; false otherwise (no player,
## no kit, or gate closed). Called from the enemy's AI path once no phase is in
## flight.
func try_begin(player: Node2D) -> bool:
	if player == null:
		return false
	if not WarpSystemScript.should_warp(
		_enemy.position,
		player.position,
		_enemy._kind.aggro_range,
		_enemy._kind.warp_trigger_range,
		_enemy._kind.warp_cooldown,
		_last_warp_time,
		_enemy._now(),
	):
		return false
	_begin_tell()
	return true


## Advance the in-flight Warp phase each physics frame: hold (with vertical
## settling only — a blink may land above the platform) until the phase ends,
## then tell -> blink + field drop, recovery -> normal AI resumes next frame.
func tick(delta: float, player: Node2D) -> void:
	var velocity: Vector2 = _enemy.velocity
	velocity.x = 0.0
	if _enemy.is_on_floor():
		if velocity.y > 0.0:
			velocity.y = 0.0
	else:
		velocity.y += _enemy._kind.gravity * delta
		if velocity.y > _enemy._kind.max_fall_speed:
			velocity.y = _enemy._kind.max_fall_speed
	_enemy.velocity = velocity
	_enemy.move_and_slide()
	if _enemy._now() < _phase_until:
		return
	if _phase == "tell":
		_blink(player)
	else:
		_phase = ""


## Start the Warp tell (gADR-0009): stamp the cooldown at the DECISION moment
## (the cooldown spans the whole rotation), telegraph with a charge-shrink tween
## toward the spawn squash, and suspend normal AI until the tell ends.
func _begin_tell() -> void:
	_last_warp_time = _enemy._now()
	_phase = "tell"
	_phase_until = _enemy._now() + _enemy._kind.warp_tell_duration
	_enemy.velocity = Vector2.ZERO
	GameLogScript.emit("info", "warp_tell", {"x": _enemy.position.x, "y": _enemy.position.y})
	var visual := _enemy.get_node("Visual") as ColorRect
	var tween: Tween = _enemy.create_tween()
	tween.tween_property(visual, "scale", _enemy._spawn_squash, _enemy._kind.warp_tell_duration)


## The blink itself: relocate to the pure far-side landing, drop the Time
## Dilation Field there at the SAME instant (the zone is the warp's wake,
## gADR-0009), replay the spawn squash as the rematerialize telegraph, and enter
## the no-attack recovery window. A Player gone from the tree (never in Phase 1 —
## death latches, the node stays) just cancels the cast.
func _blink(player: Node2D) -> void:
	if player == null:
		_phase = ""
		(_enemy.get_node("Visual") as ColorRect).scale = Vector2.ONE
		return
	var bounds := _arena_bounds()
	var landing := WarpSystemScript.warp_landing(
		_enemy.position, player.position, _enemy._kind.warp_offset, bounds.x, bounds.y
	)
	GameLogScript.emit("info", "warp_blink", {
		"from_x": _enemy.position.x,
		"from_y": _enemy.position.y,
		"to_x": landing.x,
		"to_y": landing.y,
	})
	_enemy.position = landing
	_enemy.velocity = Vector2.ZERO
	var field := TimeFieldScene.instantiate()
	field.configure(_enemy._kind)
	field.position = landing
	_enemy.get_parent().add_child(field)
	_enemy.play_spawn_tween(_enemy._spawn_squash, _enemy._spawn_tween_duration)
	_phase = "recovery"
	_phase_until = _enemy._now() + _enemy._kind.warp_recovery_duration


## The landing clamp's x range (min, max): the authored Arena interval — the
## level authority's arena_min_x/arena_max_x (gADR-0010, replacing the S8
## platform-extent derivation: a multi-segment Great Wall has no single extent) —
## inset by half this kind's width so the body lands ON the rampart, never half
## off the Arena's edge.
func _arena_bounds() -> Vector2:
	if _level_config == null:
		_level_config = GeneratedConfigScript.load_config(LEVEL_CONFIG_PATH)
		if _level_config == null:
			return Vector2(_enemy.position.x, _enemy.position.x)  # degenerate: land in place
	var half_body: float = _enemy._kind.size.x / 2.0
	return Vector2(
		_level_config.arena_min_x + half_body,
		_level_config.arena_max_x - half_body
	)
