extends SceneTree

## Logic seam (a): exercise the controller's PURE config -> plan decision headless.
##
## Run via:
##   godot --headless --path <project> --script res://tests/gdscript/test_boot_logic.gd
##
## preload() the scripts (a headless runtime has no editor-generated
## global_script_class_cache, so bare class_name types would not resolve), load
## the generated config Resource, and assert the plan is DERIVED from it (not
## hardcoded). Prints "LOGIC_SEAM: PASS" + quit(0) on success, else push_error +
## quit(1).

const GameConfigScript := preload("res://src/resources/game_config.gd")
const BootControllerScript := preload("res://src/controllers/boot_controller.gd")

const CONFIG_PATH := "res://data/generated/boot_config.tres"


func _init() -> void:
	var config: GameConfigScript = load(CONFIG_PATH)
	if config == null:
		push_error("LOGIC_SEAM: could not load %s" % CONFIG_PATH)
		quit(1)
		return

	var plan := BootControllerScript.plan_from_config(config)

	var ok: bool = (
		plan["color"] == config.block_color
		and plan["size"] == config.block_size
		and plan["start"] == config.start_position
		and plan["target"] == config.target_position
		and is_equal_approx(float(plan["duration"]), config.tween_duration)
	)
	if ok:
		print("LOGIC_SEAM: PASS")
		quit(0)
	else:
		push_error("LOGIC_SEAM: plan %s did not match config" % [plan])
		quit(1)
