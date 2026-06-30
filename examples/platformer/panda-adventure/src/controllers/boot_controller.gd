class_name BootController
extends Node2D

## Drives the S0 walking skeleton: load the derived GameConfig Resource and apply
## it to the one visible Block (color, size, start position), then tween the Block
## to its target. All visuals come from data (gADR-0000) — nothing is hardcoded.
##
## Cross-script references use preload() rather than the global `class_name`
## registry: this project has no editor-generated global_script_class_cache, so a
## bare `GameConfig` / `GameLog` type name would not resolve in a headless runtime.

const GameConfigScript := preload("res://src/resources/game_config.gd")
const GameLogScript := preload("res://src/util/game_log.gd")

const CONFIG_PATH := "res://data/generated/boot_config.tres"


## Pure logic seam (no node access): derive the block plan straight from config.
## Kept static and headless-testable — this is the seam the Monte-Carlo balancing
## sim will later reuse.
static func plan_from_config(config: GameConfigScript) -> Dictionary:
	return {
		"color": config.block_color,
		"size": config.block_size,
		"start": config.start_position,
		"target": config.target_position,
		"duration": config.tween_duration,
	}


func _ready() -> void:
	var config: GameConfigScript = load(CONFIG_PATH)
	if config == null:
		# The derived .tres is committed, but guard the boot loudly rather than
		# null-dereferencing if it is missing (e.g. a half-checkout): point at the
		# pipeline that regenerates it from the authoritative JSON.
		push_error(
			"BootController: could not load %s — run scripts/build_config.py to regenerate the derived config." % CONFIG_PATH
		)
		return
	var plan := plan_from_config(config)

	var block := $Block as ColorRect
	block.color = plan["color"]
	block.size = plan["size"]
	block.position = plan["start"]

	var tween := create_tween()
	tween.tween_property(block, "position", plan["target"], plan["duration"])

	# Keep fields JSON-scalar so the print() fallback's JSON.stringify is clean
	# (Vector2 is not a JSON type); structured positions can come later if needed.
	GameLogScript.emit("info", "boot", {
		"scene": "main",
		"tween_duration": plan["duration"],
	})
