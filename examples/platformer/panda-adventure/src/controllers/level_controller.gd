class_name LevelController
extends Node2D

## Scene-level director for S1+S2+S4+S5+S6a: applies the data-driven Platform
## blockout, plays the Wave schedule (gADR-0005) — spawning each Wave's Spawn
## Roster, folding deaths through the pure WaveSystem, and advancing on clear
## — wires each spawn's death to the Kill reward (gADR-0004), and emits the
## boot log. The Player self-configures (PlayerController); this owns the rest
## of the level so config application stays out of the physics body.
##
## Visuals and geometry are data (gADR-0000): the derived PlayerConfig /
## WaveScheduleConfig / EnemyConfig Resources, never hardcoded. Loaded here and
## in the actor controllers — load() is cached, so all observe the same
## instance.
##
## Enemies are runtime-instanced from enemy.tscn rather than baked into
## main.tscn: which kind spawns where, in which Wave, is the data-driven Wave
## schedule (gADR-0003/gADR-0005). The wave COUNT is waves.size() — config,
## never code (#334).
##
## preload() over the global class_name registry: this project has no
## editor-generated global_script_class_cache, so a bare PlayerConfig / GameLog
## type name would not resolve in a headless runtime.

const PlayerConfigScript := preload("res://src/resources/player_config.gd")
const EnemyConfigScript := preload("res://src/resources/enemy_config.gd")
const WaveScheduleConfigScript := preload("res://src/resources/wave_schedule_config.gd")
const WaveSystemScript := preload("res://src/systems/wave_system.gd")
const GameLogScript := preload("res://src/util/game_log.gd")
const EnemyScene := preload("res://scenes/enemy.tscn")

const CONFIG_PATH := "res://data/generated/player_config.tres"
const SCHEDULE_PATH := "res://data/generated/wave_schedule.tres"
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


func _ready() -> void:
	var config: PlayerConfigScript = load(CONFIG_PATH)
	if config == null:
		push_error(
			"LevelController: could not load %s — run scripts/build_config.py."
			% CONFIG_PATH
		)
		return
	_apply_platform(config)
	_schedule = load(SCHEDULE_PATH)
	if _schedule == null or _schedule.waves.is_empty():
		push_error(
			"LevelController: could not load %s (or it has no waves) — run scripts/build_config.py."
			% SCHEDULE_PATH
		)
		return
	_start_wave(0)

	# Keep fields JSON-scalar so the GameLog print() fallback's JSON.stringify is
	# clean (Vector2 is not a JSON type).
	GameLogScript.emit("info", "boot", {
		"scene": "main",
		"move_speed": config.move_speed,
		"gravity": config.gravity,
	})


## Apply the data-driven Platform blockout: the Great-Wall block (visual +
## collision centered on the body origin) and its position. All from config.
func _apply_platform(config: PlayerConfigScript) -> void:
	var half := config.platform_size / 2.0
	var platform := $Platform as StaticBody2D

	var visual := platform.get_node("Visual") as ColorRect
	visual.color = config.platform_color
	visual.size = config.platform_size
	visual.position = -half

	var shape := (platform.get_node("Collision") as CollisionShape2D).shape as RectangleShape2D
	shape.size = config.platform_size

	platform.position = config.platform_position


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
		# died) and the Player only receives. The same died edge feeds the
		# wave fold in _on_enemy_died.
		enemy.died.connect(_on_enemy_died.bind(kind))
		add_child(enemy)
		enemy.play_spawn_tween(_schedule.spawn_squash, _schedule.spawn_tween_duration)
		_alive += 1
	GameLogScript.emit("info", "wave_started", {
		"wave": index + 1,
		"total": _schedule.waves.size(),
		"spawns": _alive,
	})


## One enemy of the current Wave died: award the Kill reward, then fold the
## death through the pure WaveSystem (gADR-0005) — advance to the next Wave on
## clear, or report the whole schedule done after the final one.
func _on_enemy_died(kind: EnemyConfigScript) -> void:
	_award_kill(kind)
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
