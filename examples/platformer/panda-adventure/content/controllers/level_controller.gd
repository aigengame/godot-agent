class_name LevelController
extends Node2D

signal run_ended(won: bool)

## Scene-level director for S1+S2+S4+S5+S6a+S6b+S9: applies the data-driven
## Great-Wall blockout (gADR-0010) — the backdrop plus the runtime-instanced
## platform segments — plays the Wave schedule (gADR-0005) — spawning each
## Wave's Spawn Roster, folding deaths through the pure WaveSystem, and
## advancing on clear — wires each spawn's death to the Kill reward
## (gADR-0004) and to its Drop-table roll (gADR-0006: pickups scattered at
## the death position), and emits the boot log. Since S9 the run's End state
## (gADR-0010) is delegated to a level-owned Game-flow director (#453): this
## node forwards the two upstream edges — the schedule's all-cleared decision
## and the Player's death — and the director folds them through the pure
## GameStateSystem into won/lost, freezes the world (never a tree pause —
## that would sever the gda harness's live channel), publishes the result, and
## serves Retry through an explicit application entry point. The UI-owned Game
## Shell observes the result and forwards retry intent. The Player self-configures;
## this owns the rest of the level so config application stays out of the
## physics body.
##
## Visuals and geometry are data (gADR-0000): the derived LevelConfig /
## PlayerConfig / WaveScheduleConfig / EnemyConfig Resources, never
## hardcoded. Loaded here and in the actor controllers — load() is cached,
## so all observe the same instance.
##
## Enemies are runtime-instanced from enemy.tscn rather than baked into the
## Gameplay scene: which kind spawns where, in which Wave, is the data-driven Wave
## schedule (gADR-0003/gADR-0005). The wave COUNT is waves.size() — config,
## never code (#334). The Great-Wall segments follow the same pattern since
## S9: platform.tscn instanced per `platforms` entry, geometry config never
## scene-baked (gADR-0010).
##
## preload() over the global class_name registry: this project has no
## editor-generated global_script_class_cache, so a bare PlayerConfig / GameLog
## type name would not resolve in a headless runtime.

const PlayerConfigScript := preload("res://content/config/player_config.gd")
const LevelConfigScript := preload("res://content/config/level_config.gd")
const EnemyConfigScript := preload("res://content/config/enemy_config.gd")
const WaveScheduleConfigScript := preload("res://content/config/wave_schedule_config.gd")
const ProgressionConfigScript := preload("res://content/config/progression_config.gd")
const WaveSystemScript := preload("res://systems/wave_system.gd")
const EconomySystemScript := preload("res://systems/economy_system.gd")
const GameFlowDirectorScript := preload("res://content/controllers/game_flow_director.gd")
const GameLogScript := preload("res://addons/game_log/game_log.gd")
const GeneratedConfigScript := preload("res://content/config/generated_config.gd")
const ViewBuilderScript := preload("res://content/presentation/view_builder.gd")
const EnemyScene := preload("res://content/scenes/enemy.tscn")
const PickupScene := preload("res://content/scenes/pickup.tscn")
const PlatformScene := preload("res://content/scenes/platform.tscn")

const CONFIG_PATH := "res://content/data/generated/player_config.tres"
const LEVEL_CONFIG_PATH := "res://content/data/generated/level_config.tres"
const SCHEDULE_PATH := "res://content/data/generated/wave_schedule.tres"
const PROGRESSION_CONFIG_PATH := "res://content/data/generated/progression_config.tres"
# The per-kind derived EnemyConfig path convention (matches build_config's
# SPECS outputs) — structural wiring, not a config number.
const ENEMY_KIND_TRES := "res://content/data/generated/enemy_%s.tres"

# The derived Wave schedule and the live progression state it drives: the
# current wave (0-based; logs are 1-based for the GDD's "Wave 1..N" language)
# and how many of its spawns are still alive. Runtime state, never persisted
# (gADR-0001's config/state split).
var _schedule: WaveScheduleConfigScript
var _wave_index := 0
var _alive := 0
# The derived ProgressionConfig (S6b: the pickup scatter spacing), lazily
# loaded (load() is cached) so _ready's load block stays untouched.
var _progression_cfg: ProgressionConfigScript
# The run's game-flow director (S9, gADR-0010): the End state and its
# consequences — the World freeze, verdict log, result signal, and Retry —
# extracted here so the geometry + Wave director stay this node's job (#453).
# Constructed in _ready; a Retry reload rebuilds it by construction.
var _flow: GameFlowDirectorScript
# The derived LevelConfig (S9): the Great-Wall blockout, the Arena, and values
# consumed by the End screen in UI.
var _level_cfg: LevelConfigScript
var _player: Node


func _ready() -> void:
	# The Game-flow director owns the End state; this node forwards the edges
	# (S9, gADR-0010; extracted #453). Constructed BEFORE the config guards —
	# its _init has zero config dependencies, so config guards can return safely.
	_flow = GameFlowDirectorScript.new(self)
	_flow.run_ended.connect(_on_run_ended)
	var config: PlayerConfigScript = GeneratedConfigScript.load_config(CONFIG_PATH)
	if config == null:
		return
	_level_cfg = GeneratedConfigScript.load_config(LEVEL_CONFIG_PATH)
	if _level_cfg == null:
		return
	if _level_cfg.platforms.is_empty():
		# Loaded but empty: the JSON source has no platforms — a data fault the
		# seam's load guard can't see, so guard it here (not a pipeline fault).
		push_error("LevelController: %s has no platforms." % LEVEL_CONFIG_PATH)
		return
	_apply_level(_level_cfg)
	_player = get_node_or_null("Player")
	if _player != null:
		# The lose edge (S9, gADR-0010): the Player's S4 death latch now
		# reports here, folding into the End state exactly once.
		_player.died.connect(_on_player_died)
	_schedule = GeneratedConfigScript.load_config(SCHEDULE_PATH)
	if _schedule == null:
		return
	if _schedule.waves.is_empty():
		# Loaded but empty: the JSON source has no waves — a data fault the seam's
		# load guard can't see, so guard it here (not a pipeline fault).
		push_error("LevelController: %s has no waves." % SCHEDULE_PATH)
		return
	_start_wave(0)

	# Keep fields JSON-scalar so the GameLog print() fallback's JSON.stringify is
	# clean (Vector2 is not a JSON type).
	GameLogScript.emit("info", "boot", {
		"scene": "main",
		"move_speed": config.move_speed,
		"gravity": config.gravity,
	})


## Apply the data-driven Great-Wall blockout (S9, gADR-0010): the backdrop
## clear color and one platform.tscn instance per `platforms` segment (visual
## + collision centered on the body origin — the S1 slab's shape, now per
## segment). Each segment's blockout routes through the shared view seam
## (ViewBuilder, #436) — the same construction every actor uses, applied to the
## instanced segment, with the segment's asset reference feeding the seam's
## resolution (authored empty today, so the block). No pivot — a static platform
## never scale-tweens. All from config.
func _apply_level(config: LevelConfigScript) -> void:
	RenderingServer.set_default_clear_color(config.background_color)
	for entry: Dictionary in config.platforms:
		var segment := PlatformScene.instantiate()
		segment.name = entry["name"]
		segment.position = entry["position"]
		ViewBuilderScript.apply_box(
			segment, config.platform_color, entry["size"], false, entry["asset"]
		)
		add_child(segment)
	GameLogScript.emit("info", "level_ready", {
		"platforms": config.platforms.size(),
		"arena_min_x": config.arena_min_x,
		"arena_max_x": config.arena_max_x,
	})


## Start one Wave (gADR-0005): spawn its Spawn Roster and arm the live count
## the death fold below drains. Each entry instances enemy.tscn as its named
## Enemy Kind at its position; the instance self-applies the kind's blockout
## and stats (EnemyController._ready), then plays the spawn telegraph with the
## schedule's tween numbers. A spawn naming an unknown kind is skipped loudly
## (the data seam guards the reference; this guard keeps a bad copy
## diagnosable, not crashing). The live count only counts real spawns; a wave
## whose EVERY spawn is bad halts progression on that loud error — a corrupted
## copy stays diagnosable rather than silently skipped.
func _start_wave(index: int) -> void:
	_wave_index = index
	_alive = 0
	var wave: Dictionary = _schedule.waves[index]
	var spawns: Array = wave["spawns"]
	for spawn: Dictionary in spawns:
		# Deliberately NOT routed through the Derived-Resource loader: a
		# data-keyed reference-integrity lookup — null means the schedule names
		# an unknown kind (fix the schedule), not a pipeline fault.
		var kind: EnemyConfigScript = load(ENEMY_KIND_TRES % spawn["kind"])
		if kind == null:
			push_error(
				"LevelController: unknown enemy kind '%s' in wave %d of the Wave schedule."
				% [spawn["kind"], index + 1]
			)
			continue
		var enemy := EnemyScene.instantiate()
		enemy.setup(kind, _player)
		enemy.name = spawn["name"]
		enemy.position = spawn["position"]
		# S6a Kill reward (gADR-0004): the spawner owns the death->reward
		# wiring, binding the spawned kind so the award reads its Tier-derived
		# fields — the EnemyController stays reward-agnostic (it only emits
		# died) and the Player only receives. The enemy node itself is bound
		# too (S6b, gADR-0006): at emit time it is still in the tree
		# (queue_free is deferred), so its name/position anchor the drops.
		# The same died edge feeds the wave fold in _on_enemy_died.
		enemy.died.connect(_on_enemy_died.bind(enemy, kind))
		add_child(enemy)
		enemy.play_spawn_tween(_schedule.spawn_squash, _schedule.spawn_tween_duration)
		_alive += 1
	GameLogScript.emit("info", "wave_started", {
		"wave": index + 1,
		"total": _schedule.waves.size(),
		"spawns": _alive,
	})


## One enemy of the current Wave died: award the Kill reward, roll and spawn
## its Drop-table drops (S6b, gADR-0006), then fold the death through the pure
## WaveSystem (gADR-0005) — advance to the next Wave on clear, or report the
## whole schedule done after the final one.
func _on_enemy_died(enemy: Node2D, kind: EnemyConfigScript) -> void:
	_award_kill(kind)
	_spawn_drops(kind, enemy.name, enemy.position)
	var decision: Dictionary = WaveSystemScript.resolve_death(
		_alive, _wave_index, _schedule.waves.size()
	)
	_alive = decision["alive"]
	if decision["cleared"]:
		GameLogScript.emit("info", "wave_cleared", {"wave": _wave_index + 1})
	if decision["advance"]:
		_start_wave(_wave_index + 1)
	elif decision["all_cleared"]:
		GameLogScript.emit("info", "all_waves_cleared", {
			"total": _schedule.waves.size(),
		})
		# The win edge (S9, gADR-0010): the SCHEDULE clearing wins the run —
		# never "the Boss died"; the Boss slot stays demo composition
		# (gADR-0005). Forwarded to the Game-flow director with the wave total
		# (the game_won verdict field).
		_flow.on_all_waves_cleared(_schedule.waves.size())


## Award one Kill reward (S6a, gADR-0004): the dying kind's Tier-derived
## EXP/Gold go to the explicitly cached Player, which accumulates them onto its
## own StatsSystem and
## logs reward_gained. No decision here beyond delivery: the amounts are dumb
## per-kind fields the builder resolved from the per-Tier table.
func _award_kill(kind: EnemyConfigScript) -> void:
	if _player == null or not _player.has_method("gain_reward"):
		return
	_player.gain_reward(kind.exp_reward, kind.gold_reward, kind.tier)


## Roll and spawn one death's drops (S6b, gADR-0006): one randf() per
## Drop-table entry feeds the PURE EconomySystem.resolve_drops (the roll is
## orchestration, like the clock — the decision stays parameter-injected and
## testable), and each resolved drop instances pickup.tscn on the
## deterministic scatter row centered on the death position. Pickup names are
## derived from the schedule-unique spawn name (gADR-0005), so drops stay
## addressable. The Pickup self-applies its blockout and logs pickup_spawned
## (PickupController._ready).
func _spawn_drops(kind: EnemyConfigScript, source_name: String, death_position: Vector2) -> void:
	var cfg := _progression_config()
	if cfg == null:
		return
	var rolls: Array = []
	for _entry in kind.drop_table:
		rolls.append(randf())
	var drops: Array = EconomySystemScript.resolve_drops(kind.drop_table, rolls)
	for i in drops.size():
		var drop: Dictionary = drops[i]
		var pickup := PickupScene.instantiate()
		pickup.setup(drop["item"], drop["amount"])
		pickup.name = "%sDrop%d" % [source_name, i]
		pickup.position = death_position + EconomySystemScript.drop_offset(
			i, drops.size(), cfg.pickup_spacing
		)
		add_child(pickup)


## The derived ProgressionConfig with the standard loud guard, lazily loaded
## (the S3 GravityConfig pattern) so _ready's load block stays untouched.
func _progression_config() -> ProgressionConfigScript:
	if _progression_cfg == null:
		_progression_cfg = GeneratedConfigScript.load_config(PROGRESSION_CONFIG_PATH)
	return _progression_cfg


# --- S9 End state + Retry (gADR-0010) ------------------------------------------
# The Game-flow director owns the Content consequences: World freeze, verdict
# log, result signal, and gated Retry. This node forwards the lose/win edges and
# exposes the small application surface used by the Game Shell.


## The lose edge: the Player's S4 death latch fired (exactly once). Forwarded to
## the Game-flow director with the current wave (the game_lost verdict field).
func _on_player_died() -> void:
	_flow.on_player_died(_wave_index + 1)


## Public application surface used by the UI-owned Game Shell.
func player_node() -> Node:
	return _player


func retry() -> void:
	_flow.retry()


func _on_run_ended(won: bool) -> void:
	run_ended.emit(won)
