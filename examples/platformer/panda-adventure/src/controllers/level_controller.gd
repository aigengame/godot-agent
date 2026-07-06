class_name LevelController
extends Node2D

## Scene-level director for S1+S2+S4+S5+S6a+S6b+S9: applies the data-driven
## Great-Wall blockout (gADR-0010) — the backdrop plus the runtime-instanced
## platform segments — plays the Wave schedule (gADR-0005) — spawning each
## Wave's Spawn Roster, folding deaths through the pure WaveSystem, and
## advancing on clear — wires each spawn's death to the Kill reward
## (gADR-0004) and to its Drop-table roll (gADR-0006: pickups scattered at
## the death position), and emits the boot log. Since S9 it also owns the
## run's End state (gADR-0010): the schedule's all-cleared decision and the
## Player's death fold through the pure GameStateSystem into won/lost, which
## freezes the world (never a tree pause — that would sever the gda
## harness's live channel), shows the End screen, and arms Retry (the
## `retry` action reloads the scene, so the whole run re-derives from
## config). The Player self-configures (PlayerController); this owns the
## rest of the level so config application stays out of the physics body.
##
## Visuals and geometry are data (gADR-0000): the derived LevelConfig /
## PlayerConfig / WaveScheduleConfig / EnemyConfig Resources, never
## hardcoded. Loaded here and in the actor controllers — load() is cached,
## so all observe the same instance.
##
## Enemies are runtime-instanced from enemy.tscn rather than baked into
## main.tscn: which kind spawns where, in which Wave, is the data-driven Wave
## schedule (gADR-0003/gADR-0005). The wave COUNT is waves.size() — config,
## never code (#334). The Great-Wall segments follow the same pattern since
## S9: platform.tscn instanced per `platforms` entry, geometry config never
## scene-baked (gADR-0010).
##
## preload() over the global class_name registry: this project has no
## editor-generated global_script_class_cache, so a bare PlayerConfig / GameLog
## type name would not resolve in a headless runtime.

const PlayerConfigScript := preload("res://src/resources/player_config.gd")
const LevelConfigScript := preload("res://src/resources/level_config.gd")
const EnemyConfigScript := preload("res://src/resources/enemy_config.gd")
const WaveScheduleConfigScript := preload("res://src/resources/wave_schedule_config.gd")
const ProgressionConfigScript := preload("res://src/resources/progression_config.gd")
const WaveSystemScript := preload("res://src/systems/wave_system.gd")
const GameStateSystemScript := preload("res://src/systems/game_state_system.gd")
const EconomySystemScript := preload("res://src/systems/economy_system.gd")
const GameLogScript := preload("res://src/util/game_log.gd")
const GeneratedConfigScript := preload("res://src/util/generated_config.gd")
const EnemyScene := preload("res://scenes/enemy.tscn")
const PickupScene := preload("res://scenes/pickup.tscn")
const PlatformScene := preload("res://scenes/platform.tscn")

const CONFIG_PATH := "res://data/generated/player_config.tres"
const LEVEL_CONFIG_PATH := "res://data/generated/level_config.tres"
const SCHEDULE_PATH := "res://data/generated/wave_schedule.tres"
const PROGRESSION_CONFIG_PATH := "res://data/generated/progression_config.tres"
# The per-kind derived EnemyConfig path convention (matches build_config's
# SPECS outputs) — structural wiring, not a config number.
const ENEMY_KIND_TRES := "res://data/generated/enemy_%s.tres"

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
# The run's game-flow state (S9, gADR-0010): playing until the schedule
# clears (won) or the Player dies (lost) — the pure GameStateSystem owns the
# transitions, this node owns the consequences (freeze, End screen, Retry).
# Runtime state; a Retry reload resets it by construction.
var _state := GameStateSystemScript.STATE_PLAYING
# The derived LevelConfig (S9): the Great-Wall blockout, the Arena, and the
# End screen numbers.
var _level_cfg: LevelConfigScript


func _ready() -> void:
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
	var player := get_tree().get_first_node_in_group("player")
	if player != null:
		# The lose edge (S9, gADR-0010): the Player's S4 death latch now
		# reports here, folding into the End state exactly once.
		player.died.connect(_on_player_died)
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


func _process(_delta: float) -> void:
	# Retry is live ONLY in an End state (gADR-0010): mid-run, Enter does
	# nothing. This node stays processing through the World freeze (only
	# CHILDREN are disabled), so the retry read survives it.
	if not GameStateSystemScript.can_retry(_state):
		return
	if Input.is_action_just_pressed("retry"):
		_retry()


## Apply the data-driven Great-Wall blockout (S9, gADR-0010): the backdrop
## clear color and one platform.tscn instance per `platforms` segment (visual
## + collision centered on the body origin — the S1 slab's shape, now per
## segment). The collision shape is CREATED here (RectangleShape2D.new sized
## from config): gda cannot author inline sub-resources (#365), so the scene
## ships shape=null (the ObstacleController pattern). All from config.
func _apply_level(config: LevelConfigScript) -> void:
	RenderingServer.set_default_clear_color(config.background_color)
	for entry: Dictionary in config.platforms:
		var segment := PlatformScene.instantiate()
		segment.name = entry["name"]
		segment.position = entry["position"]
		var size: Vector2 = entry["size"]
		var half := size / 2.0

		var visual := segment.get_node("Visual") as ColorRect
		visual.color = config.platform_color
		visual.size = size
		visual.position = -half

		var shape := RectangleShape2D.new()
		shape.size = size
		(segment.get_node("Collision") as CollisionShape2D).shape = shape

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
		var kind: EnemyConfigScript = load(ENEMY_KIND_TRES % spawn["kind"])
		if kind == null:
			push_error(
				"LevelController: unknown enemy kind '%s' in wave %d of the Wave schedule."
				% [spawn["kind"], index + 1]
			)
			continue
		var enemy := EnemyScene.instantiate()
		enemy.setup(kind)
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
		# (gADR-0005).
		_enter_end_state(GameStateSystemScript.EVENT_ALL_WAVES_CLEARED)


## Award one Kill reward (S6a, gADR-0004): the dying kind's Tier-derived
## EXP/Gold go to the Player (looked up by group, the S4 pattern — no cached
## reference to go stale), which accumulates them onto its own StatsSystem and
## logs reward_gained. No decision here beyond delivery: the amounts are dumb
## per-kind fields the builder resolved from the per-Tier table.
func _award_kill(kind: EnemyConfigScript) -> void:
	var player := get_tree().get_first_node_in_group("player")
	if player == null or not player.has_method("gain_reward"):
		return
	player.gain_reward(kind.exp_reward, kind.gold_reward, kind.tier)


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
# Kept as ONE self-contained append-only block (the S3/S4 parallel-merge
# pattern): the two upstream edges fold through the pure GameStateSystem; the
# consequences — the World freeze, the End screen, the verdict log, Retry —
# live here.


## The lose edge: the Player's S4 death latch fired (exactly once).
func _on_player_died() -> void:
	_enter_end_state(GameStateSystemScript.EVENT_PLAYER_DIED)


## Fold one game-flow event through the pure GameStateSystem (gADR-0010). On
## the FIRST transition into an End state: log the verdict (the durable
## observable for gda logger tail), then apply the consequences at the frame
## boundary — both edges arrive from physics callbacks (an enemy's attack, the
## last death's wave fold), so the freeze is deferred rather than flipping
## process modes mid-callback. The latch lives in the pure decision: a second
## event never re-enters.
func _enter_end_state(event: String) -> void:
	var decision: Dictionary = GameStateSystemScript.resolve_event(_state, event)
	if not decision["changed"]:
		return
	_state = decision["state"]
	if _state == GameStateSystemScript.STATE_WON:
		GameLogScript.emit("info", "game_won", {"waves": _schedule.waves.size()})
	else:
		GameLogScript.emit("info", "game_lost", {"wave": _wave_index + 1})
	_apply_end_state.call_deferred()


## The End state's consequences, applied at the frame boundary: freeze the
## world, then show the End screen (its fade tween runs on the un-frozen
## CanvasLayer). Split from _enter_end_state so the deferral covers both.
func _apply_end_state() -> void:
	_freeze_world()
	var end_screen := get_node_or_null("EndScreen")
	if end_screen != null and end_screen.has_method("show_end"):
		end_screen.show_end(_state == GameStateSystemScript.STATE_WON)


## The World freeze (gADR-0010): disable processing on every non-CanvasLayer
## child — actors, bolts, fields, pickups halt where they are (the finale's
## time-stopped tableau) while the HUD keeps its final readout and the End
## screen runs its fade. NEVER get_tree().paused: the gda harness autoload
## serves the live IPC channel from _process under the default pause mode, so
## a tree pause would sever gda's live channel exactly when an e2e wants to
## observe the End state and press retry. This node itself stays processing —
## only children are disabled — so the Retry read in _process survives.
func _freeze_world() -> void:
	for child in get_children():
		if child is CanvasLayer:
			continue
		child.process_mode = Node.PROCESS_MODE_DISABLED


## Retry (gADR-0010): log the restart (before the scene dies), then reload the
## level scene — the whole run re-derives from config, with zero reset code to
## drift. The gda session survives the reload (same process), so the fresh
## boot records land in the same session log.
func _retry() -> void:
	GameLogScript.emit("info", "game_retried", {"from_state": _state})
	get_tree().reload_current_scene()
