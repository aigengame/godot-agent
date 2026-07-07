class_name EnemyController
extends CharacterBody2D

## Drives one spawned Enemy of a data-driven Enemy Kind (S4, gADR-0003): applies
## the kind's blockout in _ready, owns its live StatsSystem, runs its Archetype
## AI each physics frame (pure EnemyAI decisions -> velocity integration +
## attack delivery), and resolves incoming hits (i-frame gate, the symmetric
## damage formula, hit-flash tween, death at 0 HP: died signal + removal).
##
## The kind (EnemyConfig) is INJECTED by the spawner via setup() before
## add_child, so one scene serves every kind. Attack delivery branches on the
## Archetype: Melee (and, since S8, Tank — the gADR-0003 deferral lifted by
## gADR-0009 with no Tank-specific branch) lands a contact hit
## (player.take_hit with this kind as the attacker stat block — the SAME
## CombatSystem.compute_damage with roles swapped, gADR-0001); Ranged fires an
## enemy bolt (the shared ProjectileController in the player-masked variant).
##
## A kind carrying the presence-gated Warp block (gADR-0009) additionally runs
## the Warp rotation: when the pure gate opens (WarpSystem.should_warp), the
## tell phase charges (a shrink tween, steering and attack suspended), the
## blink relocates to the pure far-side landing and drops the Time Dilation
## Field there at the SAME instant (the zone is the warp's wake), and the
## recovery phase holds a short no-attack window before normal AI resumes.
##
## Decisions stay PURE (CombatSystem + EnemyAI, gADR-0001/0003): this controller
## only orchestrates — it reads the real clock, integrates velocity, mutates its
## StatsSystem, tweens, and logs. Every number comes from the derived
## EnemyConfig/CombatConfig Resources (gADR-0000). Cross-script references use
## preload() (no editor class cache in this never-imported project).

signal died

const StatsConfigScript := preload("res://src/resources/stats_config.gd")
const EnemyConfigScript := preload("res://src/resources/enemy_config.gd")
const CombatConfigScript := preload("res://src/resources/combat_config.gd")
const StatsSystemScript := preload("res://src/systems/stats_system.gd")
const CombatSystemScript := preload("res://src/systems/combat_system.gd")
const EnemyAIScript := preload("res://src/systems/enemy_ai.gd")
const GravitySystemScript := preload("res://src/systems/gravity_system.gd")
const GravityConfigScript := preload("res://src/resources/gravity_config.gd")
const GameLogScript := preload("res://src/util/game_log.gd")
const GeneratedConfigScript := preload("res://src/util/generated_config.gd")
const ViewBuilderScript := preload("res://src/view/view_builder.gd")
const EnemyWarpDriverScript := preload("res://src/controllers/enemy_warp_driver.gd")
const EnemyProjectileScene := preload("res://scenes/enemy_projectile.tscn")

const COMBAT_CONFIG_PATH := "res://data/generated/combat_config.tres"
const GRAVITY_CONFIG_PATH := "res://data/generated/gravity_config.tres"

var _kind: EnemyConfigScript
var _combat: CombatConfigScript
var _stats: StatsSystemScript
# When this defender last took a hit (seconds). -INF = never hit, so the first
# hit always lands (CombatSystem.is_invulnerable's sentinel contract).
var _last_hit_time := -INF
# When this enemy last attacked. -INF = never, so the first attack is ready
# immediately (EnemyAI.is_attack_ready's sentinel contract).
var _last_attack_time := -INF
# Buffered Gravity Field velocity (gADR-0002, S3): while a field feeds this,
# the next physics frame SUSPENDS steering/gravity and applies the clamped
# field displacement instead — see apply_gravity_field/_physics_process.
var _field_velocity := Vector2.ZERO
# Total displacement Gravity Fields have accumulated on this body, bounded by
# GravityConfig.enemy_max_gravity_offset (a field never flings it off-level);
# shed once the enemy is back on the floor with no field acting.
var _gravity_offset := Vector2.ZERO
# The largest field displacement of the CURRENT suspension episode, reported by
# one `enemy_suspended` record when the episode ends. Suspension itself is
# transient (the enemy falls back the first un-fielded frame), so the log must
# carry the peak — an observer polling positions can miss the whole episode.
var _suspension_peak := Vector2.ZERO
# Whether a field fed this body last physics frame — the episode edge detector.
var _suspended := false
# The derived GravityConfig, lazily loaded (load() is cached) so the gravity
# block stays independent of _ready (the S3 pattern).
var _gravity_config: GravityConfigScript
# The Warp driver (S8, gADR-0009): the enemy-owned three-phase (tell -> blink ->
# recovery) rotation state machine. Constructed for every kind; a kind without
# the Warp kit never opens its gate, so it stays inert. Holds the warp state and
# the four rotation methods that used to interleave this _physics_process.
var _warp: EnemyWarpDriverScript
# The spawn-telegraph numbers, cached from play_spawn_tween so the Warp driver's
# blink can replay the SAME rematerialize squash at its landing (the schedule
# owns them, gADR-0005 — an enemy spawned outside the wave system just skips it).
var _spawn_squash := Vector2.ONE
var _spawn_tween_duration := 0.0


## Hand this enemy its Enemy Kind. Called by the spawner BEFORE add_child, so
## _ready sees the kind (the Projectile setup() pattern).
func setup(kind: EnemyConfigScript) -> void:
	_kind = kind


func _ready() -> void:
	_combat = GeneratedConfigScript.load_config(COMBAT_CONFIG_PATH)
	if _combat == null:
		return
	if _kind == null:
		# The spawner must setup() before add_child; guard loudly rather than
		# crash on an enemy that was never handed its kind (not a pipeline fault).
		push_error("EnemyController: missing kind — setup() must run before add_child.")
		return
	# Gravity-response contract (gADR-0002): the S3 Gravity Field acts on this
	# group via apply_gravity_field.
	add_to_group("gravity_affectable")
	_stats = StatsSystemScript.new()
	_stats.init_from(_kind)
	_warp = EnemyWarpDriverScript.new(self)
	_apply_blockout(_kind)
	GameLogScript.emit("info", "enemy_ready", {
		"max_hp": _kind.max_hp,
		"faction": _kind.faction,
		"tier": _kind.tier,
		"archetype": _kind.archetype,
		"x": position.x,
		"y": position.y,
	})


func _physics_process(delta: float) -> void:
	if _kind == null or _stats == null:
		return
	# Suspended in a Gravity Field (gADR-0002): while a field feeds velocity,
	# the clamped displacement REPLACES steering/gravity integration — the
	# enemy hangs in the field (the GDD's "suspend a cluster of enemies in a
	# Gravity Field, then shoot them") and its own gravity resumes the first
	# un-fielded frame. Same pure decision as the Obstacle's
	# (GravitySystem.compute_clamped_offset).
	if _field_velocity != Vector2.ZERO:
		var next := GravitySystemScript.compute_clamped_offset(
			_gravity_offset, _field_velocity, delta, _gravity_clamp()
		)
		position += next - _gravity_offset
		_gravity_offset = next
		if next.length() > _suspension_peak.length():
			_suspension_peak = next
		_suspended = true
		_field_velocity = Vector2.ZERO
		velocity = Vector2.ZERO
		return
	# The suspension episode just ended (first un-fielded frame): report its
	# peak displacement — the durable observable of a transient state, one
	# record per episode (not per-frame spam).
	if _suspended:
		_suspended = false
		GameLogScript.emit("info", "enemy_suspended", {
			"peak_offset_x": _suspension_peak.x,
			"peak_offset_y": _suspension_peak.y,
		})
		_suspension_peak = Vector2.ZERO
	# Back on the floor with no field acting: the field displacement has been
	# shed by normal gravity, so a future field starts a fresh clamp budget.
	if _gravity_offset != Vector2.ZERO and is_on_floor():
		_gravity_offset = Vector2.ZERO
	var player := _player()
	# The Warp rotation (S8, gADR-0009): an in-flight phase suspends steering
	# and attack (vertical settling only); otherwise the pure gate may open a
	# new cast. Gravity Fields still act above — a suspension mid-tell moves
	# the Boss, never cancels the warp.
	if _warp.is_active():
		_warp.tick(delta, player)
		return
	if _warp.try_begin(player):
		return
	var move_dir := 0.0
	if player != null:
		move_dir = EnemyAIScript.compute_move_dir(position, player.position, _kind)
	velocity.x = move_dir * _kind.move_speed
	# Vertical: accumulate gravity while airborne (capped at terminal velocity);
	# shed leftover downward velocity on the floor.
	if is_on_floor():
		if velocity.y > 0.0:
			velocity.y = 0.0
	else:
		velocity.y += _kind.gravity * delta
		if velocity.y > _kind.max_fall_speed:
			velocity.y = _kind.max_fall_speed
	move_and_slide()
	if player != null and EnemyAIScript.can_attack(
		position, player.position, _kind, _last_attack_time, _now()
	):
		_attack(player)


## Gravity-response contract (gADR-0002, owned and documented by S3): buffer a
## Gravity Field's velocity; the next _physics_process integrates it as clamped
## displacement (suspension) with its own delta, so the steering overwrite
## cannot drop it and the observable lift matches the Obstacle's.
func apply_gravity_field(field_velocity: Vector2, _delta: float) -> void:
	_field_velocity += field_velocity


## The field-displacement clamp from the derived GravityConfig (gADR-0002),
## lazily loaded like the S3 block on the other responders.
func _gravity_clamp() -> float:
	if _gravity_config == null:
		_gravity_config = GeneratedConfigScript.load_config(GRAVITY_CONFIG_PATH)
		if _gravity_config == null:
			return 0.0
	return _gravity_config.enemy_max_gravity_offset


## Resolve one incoming hit from an attacker's stat block. Inside the i-frame
## window the hit is ignored — a single overlap cannot chain hits across frames.
func take_hit(attacker: StatsConfigScript) -> void:
	if _stats == null:
		return
	var now := _now()
	if CombatSystemScript.is_invulnerable(_last_hit_time, now, _combat.iframe_duration):
		return
	_last_hit_time = now
	var damage := CombatSystemScript.compute_damage(attacker, _kind, _combat)
	_stats.apply_damage(damage)
	GameLogScript.emit("info", "enemy_hit", {"damage": damage, "hp_left": _stats.hp})
	_play_hit_flash()
	if CombatSystemScript.is_dead(_stats.hp):
		# The death record precedes the signal: signal handlers run
		# SYNCHRONOUSLY (the spawner awards, levels, and spawns pickups
		# inside died.emit()), so logging first is what keeps the observable
		# kill flow causal — enemy_died -> reward_gained -> level_up ->
		# pickup_spawned -> collections (the gADR-0006 logger contract).
		GameLogScript.emit("info", "enemy_died", {"x": position.x, "y": position.y})
		died.emit()
		queue_free()


## Deliver one attack per the Archetype: Melee lands a contact hit, Ranged
## fires an enemy bolt at the Player. Cooldown stamped here (orchestration);
## the decision to attack was EnemyAI's.
func _attack(player: Node2D) -> void:
	_last_attack_time = _now()
	GameLogScript.emit("info", "enemy_attack", {
		"archetype": _kind.archetype,
		"faction": _kind.faction,
		"tier": _kind.tier,
		"x": position.x,
	})
	_play_attack_tween()
	if _kind.archetype == "ranged":
		_fire_bolt(player)
	elif player.has_method("take_hit"):
		player.take_hit(_kind)


## Fire one enemy bolt aimed at the Player, configured from this kind's
## projectile block. The bolt is the SHARED ProjectileController in the
## enemy_projectile.tscn variant (mask = terrain|player), a child of this
## enemy's PARENT so it flies in world space.
func _fire_bolt(player: Node2D) -> void:
	var aim := (player.position - position).normalized()
	if aim == Vector2.ZERO:
		return
	var bolt := EnemyProjectileScene.instantiate()
	bolt.setup(aim, _kind)
	bolt.configure(
		_kind.projectile_color,
		_kind.projectile_size,
		_kind.projectile_speed,
		_kind.projectile_lifetime,
	)
	var offset := _kind.projectile_spawn_offset
	bolt.position = position + Vector2(signf(aim.x) * offset.x, offset.y)
	get_parent().add_child(bolt)


## The Player, looked up by group each frame (PlayerController joins "player"
## in _ready) — no cached reference to go stale.
func _player() -> Node2D:
	return get_tree().get_first_node_in_group("player") as Node2D


## The runtime clock feeding the pure i-frame/cooldown decisions; the
## Monte-Carlo sim supplies its own simulated time instead.
func _now() -> float:
	return Time.get_ticks_msec() / 1000.0


## Apply the kind's data-driven blockout through the shared view seam
## (ViewBuilder, #436): the Enemy block centered on the body origin (color =
## Faction flavor, size = Tier read at a glance, per the GDD), with a center pivot
## so the spawn/attack/hit scale tweens punch about the middle.
func _apply_blockout(kind: EnemyConfigScript) -> void:
	ViewBuilderScript.apply_box(self, kind.color, kind.size, true)


## The hit "juice": flash the block to the shared hit color and tween back to
## the kind's own color (a property-tween, per the GDD).
func _play_hit_flash() -> void:
	var visual := $Visual as ColorRect
	visual.color = _combat.hit_flash_color
	var tween := create_tween()
	var recover := tween.tween_property(
		visual, "color", _kind.color, _combat.hit_flash_duration
	)
	recover.set_trans(Tween.TRANS_SINE)


## The spawn telegraph (S5, gADR-0005): punch the block's scale from the Wave
## schedule's spawn squash and tween back to normal (the attack-squash shape).
## PUBLIC: the numbers live on the schedule config — they belong to the wave
## system, not to any one kind — so the spawner (LevelController) hands them
## in after add_child (once _ready has applied the blockout).
func play_spawn_tween(squash: Vector2, duration: float) -> void:
	if _kind == null:
		return
	# Cached so the Warp blink can replay the SAME rematerialize telegraph at
	# its landing (gADR-0009) without re-reading the schedule.
	_spawn_squash = squash
	_spawn_tween_duration = duration
	var visual := $Visual as ColorRect
	visual.scale = squash
	var tween := create_tween()
	var recover := tween.tween_property(visual, "scale", Vector2.ONE, duration)
	recover.set_trans(Tween.TRANS_SINE)


## The attack telegraph: punch the block's scale to the kind's attack squash
## and tween back (the S4 sibling of S1's landing squash).
func _play_attack_tween() -> void:
	var visual := $Visual as ColorRect
	visual.scale = _kind.attack_squash
	var tween := create_tween()
	var recover := tween.tween_property(
		visual, "scale", Vector2.ONE, _kind.attack_tween_duration
	)
	recover.set_trans(Tween.TRANS_SINE)
