class_name LevelController
extends Node2D

## Scene-level director for S1+S2+S4+S6a: applies the data-driven Platform
## blockout, spawns the Spawn Roster's enemies, wires each spawn's death to
## the Kill reward (gADR-0004), and emits the boot log. The Player
## self-configures (PlayerController); this owns the rest of the level so
## config application stays out of the physics body.
##
## Visuals and geometry are data (gADR-0000): the derived PlayerConfig /
## EnemyRosterConfig / EnemyConfig Resources, never hardcoded. Loaded here and
## in the actor controllers — load() is cached, so all observe the same
## instance.
##
## Enemies are runtime-instanced from enemy.tscn rather than baked into
## main.tscn: which kind spawns where is the data-driven Spawn Roster
## (gADR-0003); the Wave slice will compose roster entries per Wave on top of
## this same mechanism.
##
## preload() over the global class_name registry: this project has no
## editor-generated global_script_class_cache, so a bare PlayerConfig / GameLog
## type name would not resolve in a headless runtime.

const PlayerConfigScript := preload("res://src/resources/player_config.gd")
const EnemyConfigScript := preload("res://src/resources/enemy_config.gd")
const EnemyRosterConfigScript := preload("res://src/resources/enemy_roster_config.gd")
const GameLogScript := preload("res://src/util/game_log.gd")
const EnemyScene := preload("res://scenes/enemy.tscn")

const CONFIG_PATH := "res://data/generated/player_config.tres"
const ROSTER_PATH := "res://data/generated/enemy_roster.tres"
# The per-kind derived EnemyConfig path convention (matches build_config's
# SPECS outputs) — structural wiring, not a config number.
const ENEMY_KIND_TRES := "res://data/generated/enemy_%s.tres"


func _ready() -> void:
	var config: PlayerConfigScript = load(CONFIG_PATH)
	if config == null:
		push_error(
			"LevelController: could not load %s — run scripts/build_config.py."
			% CONFIG_PATH
		)
		return
	_apply_platform(config)
	_spawn_enemies()

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


## Spawn the data-driven Spawn Roster (S4, gADR-0003): each entry instances
## enemy.tscn as its named Enemy Kind at its position; the instance
## self-applies the kind's blockout and stats (EnemyController._ready). A
## roster entry naming an unknown kind is skipped loudly (the data seam guards
## the reference; this guard keeps a bad copy diagnosable, not crashing).
func _spawn_enemies() -> void:
	var roster: EnemyRosterConfigScript = load(ROSTER_PATH)
	if roster == null:
		push_error(
			"LevelController: could not load %s — run scripts/build_config.py."
			% ROSTER_PATH
		)
		return
	for spawn: Dictionary in roster.spawns:
		var kind: EnemyConfigScript = load(ENEMY_KIND_TRES % spawn["kind"])
		if kind == null:
			push_error(
				"LevelController: unknown enemy kind '%s' in the Spawn Roster."
				% spawn["kind"]
			)
			continue
		var enemy := EnemyScene.instantiate()
		enemy.setup(kind)
		enemy.name = spawn["name"]
		enemy.position = spawn["position"]
		# S6a Kill reward (gADR-0004): the spawner owns the death->reward
		# wiring, binding the spawned kind so the award reads its Tier-derived
		# fields — the EnemyController stays reward-agnostic (it only emits
		# died) and the Player only receives.
		enemy.died.connect(_on_enemy_died.bind(kind))
		add_child(enemy)


## Award one Kill reward (S6a, gADR-0004): the dying kind's Tier-derived
## EXP/Gold go to the Player (looked up by group, the S4 pattern — no cached
## reference to go stale), which accumulates them onto its own StatsSystem and
## logs reward_gained. No decision here beyond delivery: the amounts are dumb
## per-kind fields the builder resolved from the per-Tier table.
func _on_enemy_died(kind: EnemyConfigScript) -> void:
	var player := get_tree().get_first_node_in_group("player")
	if player == null or not player.has_method("gain_reward"):
		return
	player.gain_reward(kind.exp_reward, kind.gold_reward, kind.tier)
