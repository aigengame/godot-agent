extends RefCounted

## The Panda Adventure Editor's in-memory authority model (gADR-0012).
##
## Loads Level 1's JSON authorities FOR EDITING and holds them in a single
## authority registry (id -> parsed document). The level authority
## (`level_config.json`: platform segments, the Arena interval, the backdrop) and
## the enemies authority (`enemies_config.json`: the Wave schedule's Spawn Roster
## positions) expose their editable SPATIAL content as typed accessors; EVERY
## tuning config (player, combat, gravity, items, hud, progression, scale, and the
## two above) additionally exposes its scalar NUMBERS through the generic
## get_number/set_number pair the schema-driven forms drive (#476 review). A
## `save()` writes ONLY the changed JSON authorities back (gADR-0000: JSON is the
## single source of truth; the derived `.tres` are never hand-written).
## Re-derivation is NOT done here — it belongs to the one Python builder, invoked
## through `editor_builder.gd` (gADR-0012 rejects a second, GDScript derivation
## path).
##
## The raw parsed Dictionaries are kept WHOLE and mutated in place, so a save is a
## minimal JSON-authority diff: only the edited spatial values change, and every
## other field — colors, End-screen numbers, enemy stats, Tier tables — round-trips
## untouched. The PLAY side keeps consuming the derived Resources through the
## existing chain (GeneratedConfig); this model never loads a `.tres`.

# The authority identifiers the generic numeric accessors key on — the Editor's
# own vocabulary for "which JSON document a form field writes", not a config
# number. Structural (the WEAPON_* / kind-id pattern used across the game). Every
# tuning config is registered so the schema-driven forms span the whole tuning
# surface, not just player + level (#476 review, gADR-0012's "tune numbers").
const AUTHORITY_LEVEL := "level"
const AUTHORITY_ENEMIES := "enemies"
const AUTHORITY_PLAYER := "player"
const AUTHORITY_COMBAT := "combat"
const AUTHORITY_GRAVITY := "gravity"
const AUTHORITY_ITEMS := "items"
const AUTHORITY_HUD := "hud"
const AUTHORITY_PROGRESSION := "progression"
const AUTHORITY_SCALE := "scale"

# authority id -> its JSON authority path. The single registry every operation
# iterates (load / save / dirty / snapshot / rollback), so adding a tuning config
# is one entry, never a new field + branch in five methods.
const AUTHORITY_PATHS := {
	AUTHORITY_LEVEL: "res://data/json/level_config.json",
	AUTHORITY_ENEMIES: "res://data/json/enemies_config.json",
	AUTHORITY_PLAYER: "res://data/json/player_config.json",
	AUTHORITY_COMBAT: "res://data/json/combat_config.json",
	AUTHORITY_GRAVITY: "res://data/json/gravity_config.json",
	AUTHORITY_ITEMS: "res://data/json/items_config.json",
	AUTHORITY_HUD: "res://data/json/hud_config.json",
	AUTHORITY_PROGRESSION: "res://data/json/progression_config.json",
	AUTHORITY_SCALE: "res://data/json/scale_spec.json",
}

# id -> the whole parsed authority Dictionary. Kept intact so unedited fields
# survive a save byte-for-value; the editable slices are mutated in place.
var _docs: Dictionary = {}
# id -> bool: which authorities carry unsaved edits, so a save reserializes ONLY
# the files that changed (a minimal JSON diff; untouched authorities never churn).
var _dirty_ids: Dictionary = {}
# The OR of _dirty_ids — the "unsaved edits" marker and the save-before-play guard.
var dirty := false
# Convenience aliases into _docs for the SPATIAL accessors below (platforms /
# arena / backdrop read `_level`; wave spawns read `_enemies`). Godot Dictionaries
# are reference types, so these alias the SAME objects the registry holds — a
# spatial edit and a numeric-form edit mutate one document.
var _level: Dictionary = {}
var _enemies: Dictionary = {}


## Load every registered JSON authority from `res://data/json`. Returns false
## (after a loud push_error inside _read_json) when the documents the editor's own
## editing needs are missing/malformed, so the controller shows a fault rather than
## crash. res:// is writable here because the Editor is a dev-machine tool run from
## source (gADR-0012), never a shipped/exported build.
func load_authorities() -> bool:
	_docs.clear()
	_dirty_ids.clear()
	dirty = false
	for id: String in AUTHORITY_PATHS:
		_docs[id] = _read_json(AUTHORITY_PATHS[id])
		_dirty_ids[id] = false
	_level = _docs[AUTHORITY_LEVEL]
	_enemies = _docs[AUTHORITY_ENEMIES]
	var player: Dictionary = _docs[AUTHORITY_PLAYER]
	# Guard the shape the editor DIRECTLY manipulates (platforms, waves) + the
	# player feel forms; the other tuning configs are form-only, guarded by their
	# own empty-form fallback rather than a hard load failure.
	if _level.is_empty() or _enemies.is_empty() or player.is_empty():
		return false
	return _level.has("platforms") and _enemies.has("waves") and player.has("move_speed")


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


# The three spatial-edit paths (backdrop/platforms/arena live in the level
# authority; wave spawns in the enemies authority) mark through the registry.
func _mark_level() -> void:
	_mark(AUTHORITY_LEVEL)


func _mark_enemies() -> void:
	_mark(AUTHORITY_ENEMIES)


## Mark one authority dirty (edits pending) and refresh the OR marker.
func _mark(id: String) -> void:
	_dirty_ids[id] = true
	dirty = true


# --- Numeric hand-tune scalars (schema-driven forms, #441) ---------------------
# One generic scalar get/set pair keyed on an authority id + a JSON key, driving
# the schema-derived SpinBox rows (EditorFormSpec + EditorForms) across EVERY
# tuning config. The forms edit scalar NUMBERS only; spatial arrays stay the
# direct-manipulation channel. The level authority's arena_min_x/arena_max_x also
# carry dedicated setters above (the drag/nudge path) — both write the SAME
# `_level[key]`, so a numeric form and a drag are one edit.

func get_number(authority: String, key: String) -> float:
	return float((_docs.get(authority, {}) as Dictionary).get(key, 0.0))


## Write one scalar number into its authority document and mark that authority
## dirty (so save() reserializes only it). Coerced to float — JSON numbers are
## floats, and the derived Resources' fields are floats (gADR-0000). An unknown
## authority is a no-op (the forms only ever pass a registered id).
func set_number(authority: String, key: String, value: float) -> void:
	if not _docs.has(authority):
		return
	(_docs[authority] as Dictionary)[key] = value
	_mark(authority)


## Read a JSON-Schema document (res://data/schema/…) for the forms to derive
## their fields from. Read-only — the Editor never writes a schema (gADR-0000:
## schemas are the config contract, owned by the pipeline). Returns {} on any
## read/parse failure, so a missing schema yields an empty form, not a crash.
func read_schema(path: String) -> Dictionary:
	return _read_json(path)


# --- Backdrop + segment color (level authority) --------------------------------

func get_background_color() -> Color:
	return _to_color(_level.get("background_color", [0.0, 0.0, 0.0, 1.0]))


func set_background_color(color: Color) -> void:
	_level["background_color"] = [color.r, color.g, color.b, color.a]
	_mark_level()


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
	_mark_level()


func set_platform_size(index: int, size: Vector2) -> void:
	_level["platforms"][index]["size"] = [size.x, size.y]
	_mark_level()


# --- Arena interval (level authority) ------------------------------------------

func get_arena_min_x() -> float:
	return float(_level.get("arena_min_x", 0.0))


func get_arena_max_x() -> float:
	return float(_level.get("arena_max_x", 0.0))


func set_arena_min_x(value: float) -> void:
	_level["arena_min_x"] = value
	_mark_level()


func set_arena_max_x(value: float) -> void:
	_level["arena_max_x"] = value
	_mark_level()


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
	_mark_enemies()


func get_spawn_label(wave: int, spawn: int) -> String:
	return String(_enemies["waves"][wave]["spawns"][spawn]["name"])


# --- Save (JSON authority only) ------------------------------------------------

## Write the CHANGED authorities back as pretty JSON — only a file whose spatial
## content was actually edited is reserialized, so an untouched authority never
## churns (a minimal JSON diff). Within a written doc only the mutated values
## differ; every unedited field keeps its value. Returns false after a loud
## push_error on any write failure; clears the dirty flags on success.
func save() -> bool:
	for id: String in _docs:
		if _dirty_ids.get(id, false) and not _write_json(AUTHORITY_PATHS[id], _docs[id]):
			return false
	dirty = false
	for id: String in _dirty_ids:
		_dirty_ids[id] = false
	return true


## Snapshot the CURRENT on-disk text of every dirty authority — its last-derived-
## GOOD content — so a subsequent derive failure can restore it (#476 review:
## integrity — the JSON authority on disk is never left in a written-but-failed-to-
## derive state). Read BEFORE save() overwrites. Returns [{id, path, text}].
func snapshot_dirty() -> Array:
	var snaps: Array = []
	for id: String in _docs:
		if _dirty_ids.get(id, false):
			snaps.append({
				"id": id,
				"path": AUTHORITY_PATHS[id],
				"text": _read_text(AUTHORITY_PATHS[id]),
			})
	return snaps


## Restore each snapshot's on-disk text and RE-MARK those authorities dirty — used
## when a derive fails after save, so the JSON authority returns to its last-good
## content while the in-memory edits stay PENDING (unsaved) for a retry. The
## in-memory _docs keep the edits; only the files revert.
func rollback(snapshots: Array) -> void:
	for snap: Dictionary in snapshots:
		var text: Variant = snap.get("text")
		if typeof(text) == TYPE_STRING:
			var file := FileAccess.open(String(snap["path"]), FileAccess.WRITE)
			if file != null:
				file.store_string(text)
				file.close()
		_mark(String(snap["id"]))


func _read_text(path: String) -> Variant:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return null
	var text := file.get_as_text()
	file.close()
	return text


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
