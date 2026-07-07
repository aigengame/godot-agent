extends SceneTree

## Round-trip seam for the Panda Adventure Editor (gADR-0012, #438): drive the
## editor's real SAVE + DERIVE path headless and assert on the JSON authority.
##
##   edit (mutate the in-memory model) -> save (write ONLY JSON) -> derive
##   (invoke the ONE Python builder via OS.execute) -> reload -> assert the JSON
##   authority AND the freshly derived .tres both carry the edit.
##
## This exercises the exact code the interactive controller wires input into
## (EditorLevelModel + EditorBuilder); it proves the editor never re-implements
## the JSON->Resource derivation in GDScript (gADR-0012's rejection).
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_editor_roundtrip.gd
## MUST run against a THROWAWAY PROJECT COPY — it writes data/json and rebuilds
## data/generated IN PLACE. Prints "EDITOR_ROUNDTRIP: PASS" + quit(0) on success,
## else push_error + quit(1). The builder needs a Python toolchain with the build
## deps; the seam test points PANDA_EDITOR_PYTHON at a suitable interpreter.

const ModelScript := preload("res://src/editor/editor_level_model.gd")
const BuilderScript := preload("res://src/editor/editor_builder.gd")

const LEVEL_TRES := "res://data/generated/level_config.tres"
const SCHEDULE_TRES := "res://data/generated/wave_schedule.tres"


func _fail(msg: String) -> void:
	push_error("EDITOR_ROUNDTRIP: " + msg)
	quit(1)


func _init() -> void:
	var model := ModelScript.new()
	if not model.load_authorities():
		_fail("could not load Level 1 JSON authorities")
		return

	# --- edit: move segment 0 up one tile and widen it (size stays a tile
	# multiple — validate_scale_semantics gates segment SIZE, not position, so
	# +32 keeps 1760->1792 grid-aligned), nudge arena_min in, and move the first
	# spawn. Positions carry no grid gate.
	var seg_center: Vector2 = model.get_platform_center(0) + Vector2(0.0, -16.0)
	var seg_size: Vector2 = model.get_platform_size(0) + Vector2(32.0, 0.0)
	var arena_min: float = model.get_arena_min_x() + 16.0
	var spawn_pos: Vector2 = model.get_spawn_position(0, 0) + Vector2(48.0, -16.0)
	# The backdrop edit (the picker channel). Power-of-two components represent
	# exactly in float32 AND JSON, so it round-trips with plain equality.
	var backdrop := Color(0.25, 0.5, 0.75, 1.0)
	model.set_platform_center(0, seg_center)
	model.set_platform_size(0, seg_size)
	model.set_arena_min_x(arena_min)
	model.set_spawn_position(0, 0, spawn_pos)
	model.set_background_color(backdrop)
	if not model.dirty:
		_fail("model must be dirty after edits")
		return

	# --- save: JSON authority only.
	if not model.save():
		_fail("save failed")
		return
	if model.dirty:
		_fail("dirty must clear after save")
		return

	# --- derive: the ONE Python builder (never a GDScript re-derivation).
	var result: Dictionary = BuilderScript.run()
	if not result["ok"]:
		_fail("derive failed (exit %d via %s): %s" % [result["exit_code"], result["python"], result["output"]])
		return

	# --- reload the JSON authority: a fresh model reads the saved edits back.
	var reloaded := ModelScript.new()
	reloaded.load_authorities()
	if reloaded.get_platform_center(0) != seg_center:
		_fail("JSON segment center not persisted: %s != %s" % [reloaded.get_platform_center(0), seg_center])
		return
	if reloaded.get_platform_size(0) != seg_size:
		_fail("JSON segment size not persisted")
		return
	if reloaded.get_arena_min_x() != arena_min:
		_fail("JSON arena_min not persisted")
		return
	if reloaded.get_spawn_position(0, 0) != spawn_pos:
		_fail("JSON spawn position not persisted")
		return
	if reloaded.get_background_color() != backdrop:
		_fail("JSON backdrop color not persisted: %s" % [reloaded.get_background_color()])
		return

	# --- the DERIVED Resources carry the edit (proof the builder actually ran).
	var level: Resource = load(LEVEL_TRES)
	if level == null:
		_fail("derived level_config.tres missing")
		return
	if level.platforms[0]["position"] != seg_center:
		_fail("derived .tres segment position stale: %s" % [level.platforms[0]["position"]])
		return
	if level.platforms[0]["size"] != seg_size:
		_fail("derived .tres segment size stale")
		return
	if level.arena_min_x != arena_min:
		_fail("derived .tres arena_min stale")
		return
	if level.background_color != backdrop:
		_fail("derived .tres backdrop stale: %s" % [level.background_color])
		return
	var schedule: Resource = load(SCHEDULE_TRES)
	if schedule == null:
		_fail("derived wave_schedule.tres missing")
		return
	if schedule.waves[0]["spawns"][0]["position"] != spawn_pos:
		_fail("derived .tres spawn position stale: %s" % [schedule.waves[0]["spawns"][0]["position"]])
		return

	print("EDITOR_ROUNDTRIP: PASS")
	quit(0)
