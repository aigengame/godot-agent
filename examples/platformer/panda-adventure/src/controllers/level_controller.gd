class_name LevelController
extends Node2D

## Scene-level director for S1+S2: applies the data-driven Platform blockout,
## spawns the S2 Enemy, and emits the boot log. The Player self-configures
## (PlayerController); this owns the rest of the level so config application
## stays out of the physics body.
##
## Visuals and geometry are data (gADR-0000): the derived PlayerConfig /
## CombatConfig Resources, never hardcoded. Loaded here and in the actor
## controllers — load() is cached, so all observe the same instance.
##
## The Enemy is runtime-instanced from enemy.tscn rather than baked into
## main.tscn: its placement is config (enemy_position), and S4's wave spawner
## inherits this exact pattern.
##
## preload() over the global class_name registry: this project has no
## editor-generated global_script_class_cache, so a bare PlayerConfig / GameLog
## type name would not resolve in a headless runtime.

const PlayerConfigScript := preload("res://src/resources/player_config.gd")
const CombatConfigScript := preload("res://src/resources/combat_config.gd")
const GameLogScript := preload("res://src/util/game_log.gd")
const EnemyScene := preload("res://scenes/enemy.tscn")

const CONFIG_PATH := "res://data/generated/player_config.tres"
const COMBAT_CONFIG_PATH := "res://data/generated/combat_config.tres"


func _ready() -> void:
	var config: PlayerConfigScript = load(CONFIG_PATH)
	var combat: CombatConfigScript = load(COMBAT_CONFIG_PATH)
	if config == null or combat == null:
		push_error(
			"LevelController: could not load %s / %s — run scripts/build_config.py."
			% [CONFIG_PATH, COMBAT_CONFIG_PATH]
		)
		return
	_apply_platform(config)
	_spawn_enemy(combat)

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


## Spawn the S2 static Enemy at its config position. The instance self-applies
## its blockout and stats (EnemyController._ready).
func _spawn_enemy(combat: CombatConfigScript) -> void:
	var enemy := EnemyScene.instantiate()
	enemy.name = "Enemy"
	enemy.position = combat.enemy_position
	add_child(enemy)
