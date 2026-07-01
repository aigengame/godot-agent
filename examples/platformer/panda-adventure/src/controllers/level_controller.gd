class_name LevelController
extends Node2D

## Scene-level director for S1: applies the data-driven Platform blockout and
## emits the boot log. The Player self-configures (PlayerController); this owns
## the rest of the level so config application stays out of the physics body.
##
## Visuals and geometry are data (gADR-0000): the derived PlayerConfig Resource,
## never hardcoded. Loaded here and in PlayerController — load() is cached, so
## both observe the same instance.
##
## preload() over the global class_name registry: this project has no
## editor-generated global_script_class_cache, so a bare PlayerConfig / GameLog
## type name would not resolve in a headless runtime.

const PlayerConfigScript := preload("res://src/resources/player_config.gd")
const GameLogScript := preload("res://src/util/game_log.gd")

const CONFIG_PATH := "res://data/generated/player_config.tres"


func _ready() -> void:
	var config: PlayerConfigScript = load(CONFIG_PATH)
	if config == null:
		push_error(
			"LevelController: could not load %s — run scripts/build_config.py." % CONFIG_PATH
		)
		return
	_apply_platform(config)

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
