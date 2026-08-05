class_name PlayerController
extends CharacterBody2D

## Drives the Player block: applies its data-driven blockout in _ready, reads the
## InputMap each physics frame, feeds it to PlayerMovementSystem's pure velocity
## decision,
## and applies the result with move_and_slide. A landing squash-stretch tween is
## the blockout "animation" (property interpolation, gADR/GDD).
##
## S2 adds the Laser Gun: the `fire` action spawns a Projectile bolt aimed by
## the facing (the movement System's pure facing decision over the same axis), carrying the
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
## S7 adds the Consumable use verbs + the Spacesuit (gADR-0008): `eat_bun` and
## `drink_wine` consume the S6b item-count hook (supply-gated, capped restore,
## consume flash), and the worn Spacesuit composes the effective defender
## (base defense + config bonus) that take_hit feeds the damage formula's
## mitigation term. See the S7 block at the end of this file.
##
## Movement params and visuals are data (gADR-0000): a derived PlayerConfig
## Resource, never hardcoded. PlayerMovementSystem is static and node-free so
## the logic seam can exercise it headless.
##
## Cross-script references use preload() rather than the global class_name
## registry: this project has no editor-generated global_script_class_cache, so a
## bare PlayerConfig type name would not resolve in a headless runtime.

const PlayerConfigScript := preload("res://content/config/player_config.gd")
const StatsConfigScript := preload("res://systems/stats_config.gd")
const CombatConfigScript := preload("res://content/config/combat_config.gd")
const StatsSystemScript := preload("res://systems/stats_system.gd")
const CombatSystemScript := preload("res://systems/combat_system.gd")
const PlayerMovementSystemScript := preload("res://systems/player_movement_system.gd")
const GameLogScript := preload("res://addons/game_log/game_log.gd")
const GeneratedConfigScript := preload("res://content/config/generated_config.gd")
const ViewBuilderScript := preload("res://content/presentation/view_builder.gd")
const PlayerAnimatorScript := preload("res://content/presentation/player_animator.gd")
const ProjectileScene := preload("res://content/scenes/projectile.tscn")

const CONFIG_PATH := "res://content/data/generated/player_config.tres"
const STATS_PATH := "res://content/data/generated/stats_player.tres"
const COMBAT_CONFIG_PATH := "res://content/data/generated/combat_config.tres"

## The Player's death edge (S9, gADR-0010): emitted exactly once, on the S4
## death latch — the EnemyController `died` precedent. The LevelController
## folds it into the End state and publishes the result upward to UI.
signal died

# --- View-integration hooks (P2-S5, #443) -------------------------------------
# The phase-wide "one hook home": the Player's presentation-relevant moments,
# emitted by the controller and consumed by view PRESENTERS via signal connect —
# the PlayerAnimator (this slice), the SFX players (#444), and the VFX (#448).
# The controller holds NO reference to any presenter and decides nothing about
# look/sound; it only emits. So animation/audio/VFX stay OUT of the controller and
# the pure Systems (gADR-0000 layering; the Phase-2 closed logic-change list is
# view-integration hooks + numeric config only — never a Systems behavioral diff).
# These REPLACE the S1–S7 inline property-tween placeholders (landing squash, the
# hit / level-up / consume flashes), which are now the PlayerAnimator's animations.

## Locomotion base state changed — one of &"idle" / &"run" / &"jump" / &"fall".
## The continuous animation the sprite loops; emitted only on the CHANGE edge
## (never per physics frame — the gda-logger no-spam convention).
signal locomotion_changed(state: StringName)

## Touchdown edge (was airborne, now on the floor) — the discrete landing moment
## (SFX #444 a landing thud, VFX #448 a dust puff). The locomotion animation is
## already handled by `locomotion_changed`; this is the discrete-event hook.
signal landed

## A weapon fired — `weapon` is &"laser_gun" or &"gravity_gun" (the WEAPON_*
## identifiers). Emitted after the bolt / field actually spawns.
signal fired(weapon: StringName)

## The Player took a hit — the presentation edge of `take_hit` (i-frames already
## gated it upstream), so a hurt animation / hit SFX / spark VFX fires once.
signal hurt

## A Consumable was used — `item` is &"bun" or &"wine" (the ITEM_* identifiers).
## Emitted after the supply gate consumed one.
signal consumed(item: StringName)

## The Player leveled up — the positive presentation edge, on a level rise.
signal leveled_up

## The Player's death PRESENTATION edge — distinct from `died` (the gameplay latch
## the LevelController folds into the End state): emitted once, in the same latch,
## so the death animation / sting / explosion plays without coupling a presenter to
## the gameplay signal.
signal death_started

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
# Debug god-mode (#476 review): when set — only by the Editor's debug palette, a
# dev-machine tool — take_hit skips the whole hit so the Player cannot die while a
# playtest finding is reproduced. A DEBUG SEAM, not a gameplay-logic change: the
# editor scene that drives it is export-stripped (gADR-0012), and take_hit gates
# the effect on NOT a template (exported) build, so a shipped build ignores it
# even if the flag were somehow set.
var _debug_invulnerable := false
# The time scale a Time Dilation Field imposes (S8, gADR-0009): 1.0 = full
# speed. Set by the field via the time_dilatable contract each overlap frame,
# reset to 1.0 the frame the Player leaves (or the field expires).
var _time_dilation := 1.0
# The Player's animation state machine (P2-S5, #443): the view driver that turns
# the view-integration hook signals into AnimatedSprite2D state. Null when the
# Player has no SpriteFrames asset (the colored-block fallback — nothing to drive).
var _animator: PlayerAnimatorScript
# The last locomotion state emitted, so `locomotion_changed` fires on the edge only.
var _locomotion: StringName = &"idle"


func _ready() -> void:
	_config = GeneratedConfigScript.load_config(CONFIG_PATH)
	_stats_config = GeneratedConfigScript.load_config(STATS_PATH)
	_combat = GeneratedConfigScript.load_config(COMBAT_CONFIG_PATH)
	if _config == null or _stats_config == null or _combat == null:
		return
	# Time-dilation response contract (S8, gADR-0009): the Time Dilation Field
	# acts on this group via set_time_dilation — the Player is the design
	# target of the Boss's zone (and is NEVER gravity_affectable, gADR-0002).
	add_to_group("time_dilatable")
	_stats = StatsSystemScript.new()
	_stats.init_from(_stats_config)
	_apply_blockout(_config)
	GameLogScript.emit("info", "player_ready", {
		"move_speed": _config.move_speed,
		"jump_velocity": _config.jump_velocity,
		"max_hp": _stats_config.max_hp,
	})
	_equip_spacesuit()


## Apply the data-driven blockout, spawn position, and follow-camera smoothing.
## The Player block (visual + collision centered on the body origin, center pivot
## for the landing squash) routes through the shared view seam (ViewBuilder, #436),
## with the config's asset reference feeding the seam's resolution (authored empty
## today, so the block); the spawn position and camera are Player-specific
## placement, kept here. All from config — nothing hardcoded.
func _apply_blockout(config: PlayerConfigScript) -> void:
	ViewBuilderScript.apply_box(
		self, config.player_color, config.player_size, true, config.player_asset
	)
	# Drive the animation state machine off the view-integration hooks when the
	# resolved asset gave the Visual an AnimatedSprite2D (a SpriteFrames reference,
	# P2-S5 #443); the colored-block fallback has no sprite, so no driver.
	var sprite := $Visual.get_node_or_null("AnimatedSprite") as AnimatedSprite2D
	if sprite != null:
		_animator = PlayerAnimatorScript.new(self, sprite)

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

	_facing = PlayerMovementSystemScript.compute_facing(_facing, input_dir)
	velocity = PlayerMovementSystemScript.compute_velocity(
		velocity,
		input_dir,
		jump_pressed,
		was_on_floor,
		_config.move_speed,
		_config.jump_velocity,
		_config.gravity,
		_config.max_fall_speed,
		delta,
		_time_dilation,
	)
	move_and_slide()

	# Landing this frame (airborne last frame, on the floor now) → the landing hook.
	if is_on_floor() and not was_on_floor:
		_emit_landed()
	# The locomotion base state the animator loops (idle/run/jump/fall), emitted on
	# the change edge only — a view-integration hook, no gameplay effect.
	_update_locomotion()

	if Input.is_action_just_pressed("switch_weapon"):
		_switch_weapon()
	if Input.is_action_just_pressed("drink_wine"):
		_drink_wine()
	if Input.is_action_just_pressed("eat_bun"):
		_eat_bun()
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
	# The PLAYER's bolts opt into the Time Dilation Field's contract (S8,
	# gADR-0009) — the enemy-bolt variant never joins, so only the Player's
	# side slows inside the Boss's zone.
	bolt.add_to_group("time_dilatable")
	var offset := _combat.projectile_spawn_offset
	bolt.position = position + Vector2(_facing * offset.x, offset.y)
	get_parent().add_child(bolt)
	GameLogScript.emit("info", "laser_fired", {
		"facing": _facing,
		"spawn_x": bolt.position.x,
		"spawn_y": bolt.position.y,
	})
	fired.emit(WEAPON_LASER)


## Time-dilation response contract (S8, gADR-0009): a Time Dilation Field
## feeds the factor here each overlap frame and resets it to 1.0 on exit or
## expiry; compute_velocity integrates it as full slow motion. Logged on the
## CHANGE edge only (enter/exit — never per-frame spam), the durable
## observable of being slowed for gda logger tail.
func set_time_dilation(factor: float) -> void:
	if is_equal_approx(factor, _time_dilation):
		return
	_time_dilation = factor
	GameLogScript.emit("info", "player_time_dilated", {"factor": factor})


## S4 damage-receiving path: resolve one incoming hit from an attacker's stat
## block — the SAME symmetric pipeline as the Enemy's (CombatSystem.compute_damage
## with the roles swapped, gADR-0001), i-frame gated so a single overlap cannot
## chain hits. On death: log player_died once and emit the `died` edge — the
## Content owns the consequences (S9, gADR-0010: game_lost, World freeze, and
## the explicit Retry entry point); UI observes the result.
## Debug god-mode toggle (#476 review): the Editor's debug palette drives this to
## make the Player invulnerable while reproducing a finding. Dev-machine only — the
## effect is gated in take_hit on NOT a template build, so it is a debug seam.
func set_debug_invulnerable(on: bool) -> void:
	_debug_invulnerable = on


func take_hit(attacker: StatsConfigScript) -> void:
	if _stats == null or _dead:
		return
	# Debug god-mode: skip the whole hit (no damage, no i-frame, no death latch) so
	# the Player never dies. Gated on NOT a template build — a shipped build always
	# takes hits; only a dev-machine editor run can enable it (#476 review).
	if _debug_invulnerable and not OS.has_feature("template"):
		return
	var now := _now()
	if CombatSystemScript.is_invulnerable(_last_hit_time, now, _combat.iframe_duration):
		return
	_last_hit_time = now
	# The defender is the SPACESUIT-composed stat block (S7, gADR-0008): base
	# defense + the worn Equipment's bonus, feeding the formula's mitigation
	# term with the formula itself untouched.
	var damage := CombatSystemScript.compute_damage(
		attacker,
		_defender_stats(),
		_combat.attack_scale,
		_combat.defense_scale,
		_combat.min_damage,
	)
	_stats.apply_damage(damage)
	GameLogScript.emit("info", "player_hit", {"damage": damage, "hp_left": _stats.hp})
	_emit_hurt()
	if CombatSystemScript.is_dead(_stats.hp):
		_dead = true
		GameLogScript.emit("info", "player_died", {"x": position.x, "y": position.y})
		died.emit()
		# The death PRESENTATION edge (view-integration hook): the death animation /
		# sting / explosion, separate from the gameplay `died` latch above.
		death_started.emit()


## The runtime clock feeding the pure i-frame decision; the Monte-Carlo sim
## supplies its own simulated time instead.
func _now() -> float:
	return Time.get_ticks_msec() / 1000.0


## The hit presentation edge (P2-S5, #443): emit the `hurt` view-integration hook
## (the PlayerAnimator plays the hurt animation; SFX/VFX attach here too). Replaces
## the S4 hit-flash property-tween placeholder. Config `hit_flash_*` stays authored
## (data-seam) — the presentation is now an animation, not a ColorRect tween.
func _emit_hurt() -> void:
	hurt.emit()


## The landing edge (P2-S5, #443): emit the `landed` view-integration hook and log
## the touchdown (the durable `player_land` observable for gda logger tail). Replaces
## the S1 landing squash-stretch property-tween placeholder; the landing ANIMATION
## follows from the locomotion change. Config `landing_*` stays authored (data-seam).
func _emit_landed() -> void:
	landed.emit()
	GameLogScript.emit("info", "player_land", {"floor_y": position.y})


## The locomotion base state the animator loops, as a pure decision (view-only, not a
## Systems rule): airborne rising is jump, airborne falling is fall, on the floor with
## horizontal input is run, else idle. Godot is +Y-down (rising is v.y < 0).
static func _compute_locomotion(vel: Vector2, on_floor: bool) -> StringName:
	if not on_floor:
		return &"jump" if vel.y < 0.0 else &"fall"
	return &"run" if absf(vel.x) > 1.0 else &"idle"


## Emit `locomotion_changed` when the locomotion base state changes (the edge only —
## never per physics frame; the gda-logger no-spam convention applied to a hook).
func _update_locomotion() -> void:
	var state := _compute_locomotion(velocity, is_on_floor())
	if state != _locomotion:
		_locomotion = state
		locomotion_changed.emit(state)


# --- S3 Gravity Gun + weapon switch + MP economy (gADR-0002) ------------------
# Kept as ONE self-contained block: S4 adds take_hit/i-frames to this file in
# parallel, so the S3 additions stay append-only (GDScript accepts class-level
# declarations after methods).

const GravityConfigScript := preload("res://content/config/gravity_config.gd")
const GravityFieldScene := preload("res://content/scenes/gravity_field.tscn")
const GRAVITY_CONFIG_PATH := "res://content/data/generated/gravity_config.tres"

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
	fired.emit(WEAPON_GRAVITY)


## Drink Wine — restore MP capped at the stat block's max_mp. Since S7 the S3
## hook is supply-gated (gADR-0008): one Wine is consumed from the item-count
## hook (or the use is refused, consumable_blocked) and the restore amount
## reads from the one items authority (ItemsConfig — migrated out of
## GravityConfig). The use juice + count land in the log record.
func _drink_wine() -> void:
	var cfg := _items_config()
	if cfg == null or _stats == null or _stats_config == null:
		return
	if not _try_consume(ITEM_WINE):
		return
	var mp_before := _stats.mp
	_stats.restore_mp(cfg.wine_mp_restore, _stats_config.max_mp)
	consumed.emit(ITEM_WINE)
	GameLogScript.emit("info", "wine_drunk", {
		"mp_before": mp_before,
		"mp_after": _stats.mp,
		"count": _items[ITEM_WINE],
	})


## The derived GravityConfig with the standard loud guard, lazily loaded so the
## S2 _ready block stays untouched.
func _gravity_config() -> GravityConfigScript:
	if _gravity_cfg == null:
		_gravity_cfg = GeneratedConfigScript.load_config(GRAVITY_CONFIG_PATH)
	return _gravity_cfg


# --- S6a Kill reward + HUD read surface (gADR-0004) ---------------------------
# Kept as ONE self-contained append-only block (the S3/S4 parallel-merge
# pattern): the reward RECEIVER (the spawner-side wiring lives in
# LevelController) and the one public snapshot the HUD reads.


## Receive one Kill reward: accumulate the defeated kind's Tier-derived
## EXP/Gold onto this Player's own StatsSystem (the only mutation — pure
## addition, StatsSystem.gain_reward) and log the accumulation trace, then
## re-resolve the level the new EXP total implies (S6b, gADR-0006). The
## amounts and tier come from the defeated kind's derived config, read by the
## caller (LevelController) — this method decides nothing.
func gain_reward(exp_reward: float, gold_reward: float, tier: String) -> void:
	if _stats == null:
		return
	_stats.gain_reward(exp_reward, gold_reward)
	GameLogScript.emit("info", "reward_gained", {
		"exp": exp_reward,
		"gold": gold_reward,
		"exp_total": _stats.exp_points,
		"gold_total": _stats.gold,
		"tier": tier,
	})
	_check_level_up()


## The minimal public read surface the HUD pulls each frame (gADR-0004): one
## snapshot Dictionary of the live stats (+ their config caps), the current
## Level (S6b), and the Current weapon, so the HUD never reaches into
## privates. Empty ({}) until _ready has initialized the stats — a puller
## skips that frame.
func hud_state() -> Dictionary:
	if _stats == null or _stats_config == null:
		return {}
	return {
		"hp": _stats.hp,
		"max_hp": _stats_config.max_hp,
		"mp": _stats.mp,
		"max_mp": _stats_config.max_mp,
		"level": _level,
		"exp": _stats.exp_points,
		"gold": _stats.gold,
		"weapon": _weapon,
		# S7 (gADR-0008): the Consumable supply, so the HUD can surface what
		# the use verbs can spend.
		"bun": int(_items.get(ITEM_BUN, 0)),
		"wine": int(_items.get(ITEM_WINE, 0)),
	}


# --- S6b Leveling curve + drop collection (gADR-0006) -------------------------
# Kept as ONE self-contained append-only block (the S3/S4 parallel-merge
# pattern): the level the accumulated EXP implies (a pure GrowthSystem
# re-resolution after each reward) and the receiving end of a Pickup's drop.

const ProgressionConfigScript := preload("res://content/config/progression_config.gd")
const GrowthSystemScript := preload("res://systems/growth_system.gd")
const PROGRESSION_CONFIG_PATH := "res://content/data/generated/progression_config.tres"

# The Player's current Level — DERIVED runtime state (gADR-0006): always the
# pure GrowthSystem.resolve_level of the live EXP total, cached only so the
# old->new edge is detectable for the level_up log + flash. Starts at level 1.
var _level := 1
# The S6b item-count hook (item name -> count): where dropped Consumables
# land until S7's inventory/use story consumes them (the S3 Wine-hook
# pattern: the supply side exists, the use side is the later slice). Runtime
# state, never persisted (gADR-0001).
var _items := {}
# The derived ProgressionConfig, lazily loaded (load() is cached) so _ready's
# S2 load block stays untouched (the S3 GravityConfig pattern).
var _progression_cfg: ProgressionConfigScript


## Re-resolve the Level implied by the live EXP total against the data-driven
## leveling curve (pure GrowthSystem decision; the curve comes from the
## derived config — max level is curve length + 1, config never code). On a
## rise: log level_up (from/to covers a multi-threshold jump in one record)
## and play the flash. EXP only ever grows, so the level never goes down.
func _check_level_up() -> void:
	var cfg := _progression_config()
	if cfg == null or _stats == null:
		return
	var resolved := GrowthSystemScript.resolve_level(_stats.exp_points, cfg.level_curve)
	if resolved <= _level:
		return
	var from := _level
	_level = resolved
	GameLogScript.emit("info", "level_up", {
		"from": from,
		"to": _level,
		"exp_total": _stats.exp_points,
	})
	leveled_up.emit()


## Receive one collected Pickup's drop (called by PickupController on
## contact): gold accumulates onto this Player's own StatsSystem
## (StatsSystem.gain_gold — Gold's second source next to the Kill reward),
## any other item lands in the S6b item-count hook. Each path logs its
## accumulation trace. The item/amount come from the Pickup's injected drop
## (resolved from the defeated kind's derived Drop table) — this method
## decides nothing.
func collect_drop(item: String, amount: int) -> void:
	if _stats == null:
		return
	if item == "gold":
		_stats.gain_gold(float(amount))
		GameLogScript.emit("info", "gold_collected", {
			"amount": amount,
			"gold_total": _stats.gold,
		})
		return
	_items[item] = int(_items.get(item, 0)) + amount
	GameLogScript.emit("info", "item_collected", {
		"item": item,
		"amount": amount,
		"count": _items[item],
	})


## The derived ProgressionConfig with the standard loud guard, lazily loaded
## so the S2 _ready block stays untouched (the S3 GravityConfig pattern).
func _progression_config() -> ProgressionConfigScript:
	if _progression_cfg == null:
		_progression_cfg = GeneratedConfigScript.load_config(PROGRESSION_CONFIG_PATH)
	return _progression_cfg


# --- S7 Consumable use + Spacesuit Equipment (gADR-0008) ----------------------
# Kept as ONE self-contained append-only block (the S3/S4 parallel-merge
# pattern): the use verbs that CONSUME the S6b item-count hook (supply-gated,
# capped restore, consume flash — pure gating in ItemSystem) and the worn
# Spacesuit's composed defender feeding take_hit's mitigation term.

const ItemsConfigScript := preload("res://content/config/items_config.gd")
const ItemSystemScript := preload("res://systems/item_system.gd")
const ITEMS_CONFIG_PATH := "res://content/data/generated/items_config.tres"

# The two Consumables' item names — the CLOSED Phase-1 drop vocabulary's
# non-gold entries (gADR-0006). Structural identifiers (they name _items keys
# and log values, not tunable numbers — the WEAPON_* pattern).
const ITEM_BUN := "bun"
const ITEM_WINE := "wine"

# The Spacesuit-composed effective defender (base stat block + config defense
# bonus), built once at ready — the Spacesuit is worn from spawn (persistent
# Equipment, GDD). Null until _equip_spacesuit (or when config failed to
# load); _defender_stats falls back to the bare stat block.
var _defender: StatsConfigScript
# The derived ItemsConfig, lazily loaded (load() is cached) so _ready's S2
# load block stays untouched (the S3 GravityConfig pattern).
var _items_cfg: ItemsConfigScript


## Wear the Spacesuit: compose the effective defender (pure ItemSystem
## decision — the base .tres is load()-aliased immutable config and is never
## mutated, gADR-0001) and log the module entry with the config bonus.
func _equip_spacesuit() -> void:
	var cfg := _items_config()
	if cfg == null or _stats_config == null:
		return
	_defender = ItemSystemScript.effective_defender(_stats_config, cfg.spacesuit_defense)
	GameLogScript.emit("info", "spacesuit_equipped", {
		"defense_bonus": cfg.spacesuit_defense,
		"defense_total": _defender.defense,
	})


## The defender stat block take_hit feeds the damage formula: the
## Spacesuit-composed block, or the bare base block until/unless the suit
## initialized (the formula contract is unchanged either way).
func _defender_stats() -> StatsConfigScript:
	return _defender if _defender != null else _stats_config


## Eat a Bun — restore HP capped at the stat block's max_hp, consuming one
## from the item-count hook (or refusing, consumable_blocked). Supply is the
## ONLY gate (gADR-0008): the S4 death latch stops the damage/death records,
## not verbs — like moving and firing, item use stays live after player_died
## until a later slice owns game-over/respawn.
func _eat_bun() -> void:
	var cfg := _items_config()
	if cfg == null or _stats == null or _stats_config == null:
		return
	if not _try_consume(ITEM_BUN):
		return
	var hp_before := _stats.hp
	_stats.restore_hp(cfg.bun_hp_restore, _stats_config.max_hp)
	consumed.emit(ITEM_BUN)
	GameLogScript.emit("info", "bun_eaten", {
		"hp_before": hp_before,
		"hp_after": _stats.hp,
		"count": _items[ITEM_BUN],
	})


## The shared Consumable supply gate (gADR-0008): consume one `item` from the
## S6b item-count hook and report true, or refuse (nothing consumed, one
## consumable_blocked record — the gravity_blocked pattern) when none is
## held. Supply is the only input; the restore caps bound the effect.
func _try_consume(item: String) -> bool:
	var count := int(_items.get(item, 0))
	if not ItemSystemScript.can_consume(count):
		GameLogScript.emit("info", "consumable_blocked", {"item": item, "count": count})
		return false
	_items[item] = ItemSystemScript.consumed(count)
	return true


## The derived ItemsConfig with the standard loud guard, lazily loaded so the
## S2 _ready block stays untouched (the S3 GravityConfig pattern).
func _items_config() -> ItemsConfigScript:
	if _items_cfg == null:
		_items_cfg = GeneratedConfigScript.load_config(ITEMS_CONFIG_PATH)
	return _items_cfg
