extends RefCounted

## The Panda Adventure Editor's in-memory authority model (gADR-0012).
##
## Loads Level 1's JSON authorities FOR EDITING — the level authority
## (`level_config.json`: platform segments, the Arena interval, the backdrop) and
## the enemies authority (`enemies_config.json`: the Wave schedule's Spawn Roster
## positions) — and exposes their editable SPATIAL content as typed accessors over
## the raw documents. A `save()` writes ONLY the JSON authority back (gADR-0000:
## JSON is the single source of truth; the derived `.tres` are never hand-written).
## Re-derivation is NOT done here — it belongs to the one Python builder, invoked
## through `editor_builder.gd` (gADR-0012 rejects a second, GDScript derivation
## path).
##
## The raw parsed Dictionaries are kept WHOLE and mutated in place, so a save is a
## minimal JSON-authority diff: only the edited spatial values change, and every
## other field — colors, End-screen numbers, enemy stats, Tier tables — round-trips
## untouched. The PLAY side keeps consuming the derived Resources through the
## existing chain (GeneratedConfig); this model never loads a `.tres`.

const LEVEL_JSON_PATH := "res://data/json/level_config.json"
const ENEMIES_JSON_PATH := "res://data/json/enemies_config.json"

# The whole parsed authority documents. Kept intact so unedited fields survive a
# save byte-for-value; the editable spatial slices are mutated in place.
var _level: Dictionary = {}
var _enemies: Dictionary = {}
# Set on any mutation, cleared on load/save — drives the "unsaved edits" marker
# and the save-before-play guard.
var dirty := false


## Load both JSON authorities from `res://data/json`. Returns false (after a loud
## push_error) if either file is missing or malformed, so the controller can show
## a fault rather than crash. res:// is writable here because the Editor is a
## dev-machine tool run from source (gADR-0012), never a shipped/exported build.
func load_authorities() -> bool:
	_level = _read_json(LEVEL_JSON_PATH)
	_enemies = _read_json(ENEMIES_JSON_PATH)
	dirty = false
	if _level.is_empty() or _enemies.is_empty():
		return false
	return _level.has("platforms") and _enemies.has("waves")


func _read_json(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("EditorLevelModel: cannot open %s (error %d)" % [path, FileAccess.get_open_error()])
		return {}
	var text := file.get_as_text()
	file.close()
	var parsed: Variant = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error("EditorLevelModel: %s is not a JSON object" % path)
		return {}
	return parsed


# --- Backdrop + segment color (level authority) --------------------------------

func get_background_color() -> Color:
	return _to_color(_level.get("background_color", [0.0, 0.0, 0.0, 1.0]))


func set_background_color(color: Color) -> void:
	_level["background_color"] = [color.r, color.g, color.b, color.a]
	dirty = true


func get_platform_color() -> Color:
	return _to_color(_level.get("platform_color", [0.5, 0.5, 0.5, 1.0]))


# --- Platform segments (level authority) ---------------------------------------
# Each entry is {"name": String, "position": [x, y], "size": [w, h]} — position
# is the segment CENTER (the LevelController instancing contract, gADR-0010).

func platform_count() -> int:
	return (_level.get("platforms", []) as Array).size()


func get_platform_name(index: int) -> String:
	return String(_level["platforms"][index]["name"])


func get_platform_center(index: int) -> Vector2:
	return _to_vec2(_level["platforms"][index]["position"])


func get_platform_size(index: int) -> Vector2:
	return _to_vec2(_level["platforms"][index]["size"])


func set_platform_center(index: int, center: Vector2) -> void:
	_level["platforms"][index]["position"] = [center.x, center.y]
	dirty = true


func set_platform_size(index: int, size: Vector2) -> void:
	_level["platforms"][index]["size"] = [size.x, size.y]
	dirty = true


# --- Arena interval (level authority) ------------------------------------------

func get_arena_min_x() -> float:
	return float(_level.get("arena_min_x", 0.0))


func get_arena_max_x() -> float:
	return float(_level.get("arena_max_x", 0.0))


func set_arena_min_x(value: float) -> void:
	_level["arena_min_x"] = value
	dirty = true


func set_arena_max_x(value: float) -> void:
	_level["arena_max_x"] = value
	dirty = true


# --- Wave / Spawn roster positions (enemies authority) -------------------------
# The Wave schedule is `waves: [ {spawns: [ {kind, name, position}, ... ]}, ... ]`.

func wave_count() -> int:
	return (_enemies.get("waves", []) as Array).size()


func spawn_count(wave: int) -> int:
	return (_enemies["waves"][wave]["spawns"] as Array).size()


func get_spawn_position(wave: int, spawn: int) -> Vector2:
	return _to_vec2(_enemies["waves"][wave]["spawns"][spawn]["position"])


func set_spawn_position(wave: int, spawn: int, position: Vector2) -> void:
	_enemies["waves"][wave]["spawns"][spawn]["position"] = [position.x, position.y]
	dirty = true


func get_spawn_label(wave: int, spawn: int) -> String:
	return String(_enemies["waves"][wave]["spawns"][spawn]["name"])


# --- Save (JSON authority only) ------------------------------------------------

## Write both authorities back as pretty JSON. Only the mutated spatial values
## differ from the loaded documents (the whole doc is re-serialized, but every
## unedited field keeps its value). Returns false after a loud push_error on any
## write failure; clears `dirty` on success.
func save() -> bool:
	var wrote_level := _write_json(LEVEL_JSON_PATH, _level)
	var wrote_enemies := _write_json(ENEMIES_JSON_PATH, _enemies)
	if wrote_level and wrote_enemies:
		dirty = false
		return true
	return false


func _write_json(path: String, document: Dictionary) -> bool:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("EditorLevelModel: cannot write %s (error %d)" % [path, FileAccess.get_open_error()])
		return false
	file.store_string(JSON.stringify(document, "  ") + "\n")
	file.close()
	return true


# --- Conversions ---------------------------------------------------------------

func _to_vec2(pair: Variant) -> Vector2:
	var array := pair as Array
	return Vector2(float(array[0]), float(array[1]))


func _to_color(components: Variant) -> Color:
	var array := components as Array
	var alpha := float(array[3]) if array.size() > 3 else 1.0
	return Color(float(array[0]), float(array[1]), float(array[2]), alpha)
