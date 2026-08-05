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
## MUST run against a THROWAWAY PROJECT COPY — it writes content/data/json and rebuilds
## content/data/generated IN PLACE. Prints "EDITOR_ROUNDTRIP: PASS" + quit(0) on success,
## else push_error + quit(1). The builder needs a Python toolchain with the build
## deps; the seam test points PANDA_EDITOR_PYTHON at a suitable interpreter.

const ModelScript := preload("res://tools/editor/editor_level_model.gd")
const BuilderScript := preload("res://tools/editor/editor_builder.gd")
const FormSpecScript := preload("res://tools/editor/editor_form_spec.gd")

const LEVEL_TRES := "res://content/data/generated/level_config.tres"
const SCHEDULE_TRES := "res://content/data/generated/wave_schedule.tres"
const PLAYER_TRES := "res://content/data/generated/player_config.tres"
const PLAYER_SCHEMA := "res://content/data/schema/player_config.schema.json"


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

	# --- form edit (#441): a schema-driven NUMERIC hand-tune of a Player feel
	# number. The field set comes from the SCHEMA (EditorFormSpec), proving the
	# form maps from content/data/schema, and the write goes through the model's generic
	# set_number exactly as a SpinBox row does. 320.0 is exact in float32 + JSON.
	var fields := FormSpecScript.numeric_fields(model.read_schema(PLAYER_SCHEMA))
	if not _has_field(fields, "move_speed"):
		_fail("schema-derived numeric fields missing move_speed")
		return
	var new_move_speed := 320.0  # was 300.0
	model.set_number(ModelScript.AUTHORITY_PLAYER, "move_speed", new_move_speed)
	# Multi-config coverage (#476 review): hand-tune a Combat and a Gravity number
	# too, proving the numeric round-trip spans EVERY tuning config, not just
	# player/level. 0.5 / 8.0 are exact in float32 + JSON.
	var new_iframe := 0.5  # combat.iframe_duration, was 0.6
	var new_mp_cost := 8.0  # gravity.mp_cost, was 10.0
	model.set_number(ModelScript.AUTHORITY_COMBAT, "iframe_duration", new_iframe)
	model.set_number(ModelScript.AUTHORITY_GRAVITY, "mp_cost", new_mp_cost)

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
	if reloaded.get_number(ModelScript.AUTHORITY_PLAYER, "move_speed") != new_move_speed:
		_fail("JSON move_speed not persisted: %s" % [reloaded.get_number(ModelScript.AUTHORITY_PLAYER, "move_speed")])
		return
	if reloaded.get_number(ModelScript.AUTHORITY_COMBAT, "iframe_duration") != new_iframe:
		_fail("JSON combat iframe_duration not persisted")
		return
	if reloaded.get_number(ModelScript.AUTHORITY_GRAVITY, "mp_cost") != new_mp_cost:
		_fail("JSON gravity mp_cost not persisted")
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
	# The form edit propagated through the builder into the derived PlayerConfig
	# (#441): forms -> JSON -> builder -> reload closed the numeric loop.
	var player: Resource = load(PLAYER_TRES)
	if player == null:
		_fail("derived player_config.tres missing")
		return
	if player.move_speed != new_move_speed:
		_fail("derived .tres move_speed stale: %s" % [player.move_speed])
		return
	var combat: Resource = load("res://content/data/generated/combat_config.tres")
	if combat == null or combat.iframe_duration != new_iframe:
		_fail("derived combat_config.tres iframe_duration stale")
		return
	var gravity: Resource = load("res://content/data/generated/gravity_config.tres")
	if gravity == null or gravity.mp_cost != new_mp_cost:
		_fail("derived gravity_config.tres mp_cost stale")
		return

	print("EDITOR_ROUNDTRIP: PASS")
	quit(0)


## Whether a schema-derived field list carries `key` — the forms map from schema.
func _has_field(fields: Array, key: String) -> bool:
	for field: Dictionary in fields:
		if String(field["key"]) == key:
			return true
	return false
