extends RefCounted

# gda headless operations payload: reference edges between project files
# (ADR-0043 §2). Static.

const GDSCRIPT_SCAN := preload("gdscript_scan.gd")
const SCENE_TEXT := preload("scene_text.gd")


# Whether this file can declare OUTGOING references (so dependencies reports it as
# a source row): a scene/resource (.tscn/.tres, via [ext_resource]) or a script
# (.gd, via preload/load/extends). A leaf asset declares none.
static func _has_outgoing_references(path: String) -> bool:
	var ext := path.get_extension().to_lower()
	return ext == "tscn" or ext == "tres" or ext == "gd"


# The outgoing references of one file as a list of {path, kind} entries, in the
# order they appear, de-duplicated. A .tscn/.tres yields its [ext_resource]
# paths; a .gd yields its preload/load/extends-by-path references. The referenced
# path is always a res:// path (a relative .gd preload is resolved against the
# file's own directory). Reading is pure text — no load/instantiate (issue #30).
static func _outgoing_references_of(path: String) -> Array:
	var ext := path.get_extension().to_lower()
	var seen := {}
	var out: Array = []
	if ext == "tscn" or ext == "tres":
		for ref_path in _ext_resource_paths(path):
			# Dedup the ext_resource form on path+kind, the same key
			# find-references matches by, so the two views of the graph agree
			# exactly (issue #116 consistency criterion).
			var key: String = ref_path + "\next_resource"
			if not seen.has(key):
				seen[key] = true
				out.append({"path": ref_path, "kind": "ext_resource"})
	elif ext == "gd":
		for ref in _script_outgoing_references(path):
			# Dedup on path+KIND, not path alone: the same target reached by both
			# preload() and load() is two distinct references, and find-references
			# reports both — so dependencies must too, or the graphs disagree
			# (issue #116 review). A newline joins the pair into a collision-free
			# key — it can appear in neither a res:// path nor a kind token.
			var key: String = String(ref["path"]) + "\n" + String(ref["kind"])
			if not seen.has(key):
				seen[key] = true
				out.append(ref)
	return out


# The res:// paths an [ext_resource ... path="res://..."] line names in a
# .tscn/.tres file — the file's external dependencies, in line order.
#
# Two owners do the work and neither rule lives here: which lines are
# declarations and how an attribute is pulled out of one belong to the scene-text
# reader (_raw_ext_resource_entries_from_text, #775), and folding each harvested
# path to its one graph identity belongs to _resolve_ref_path (#774).
static func _ext_resource_paths(path: String) -> Array[String]:
	var out: Array[String] = []
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		return out
	var base_dir := path.get_base_dir()
	for entry in SCENE_TEXT._raw_ext_resource_entries_from_text(text):
		out.append(SCENE_TEXT._resolve_ref_path(String(entry["path"]), base_dir))
	return out


# A .gd script's outgoing references as {path, kind} entries: preload("res://…")
# and load("res://…") calls (kind preload / load), and an `extends "res://Base.gd"`
# base-class-by-path (kind class_extends). A relative path argument is resolved
# against the script's own directory so it becomes a res:// path comparable to the
# rest of the graph. Parsed by text — the script is never compiled (issue #30).
static func _script_outgoing_references(path: String) -> Array:
	var out: Array = []
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		return out
	var base_dir := path.get_base_dir()
	for line in text.split("\n"):
		var stripped := line.strip_edges()
		out.append_array(_script_outgoing_references_in_line(stripped, base_dir))
	return out


# Find every reference to the target inside one file, appending {path, kind,
# context} entries to `references`. A .tscn/.tres references the target when an
# [ext_resource] names one of the target's res:// paths; a .gd references it when
# a preload/load/extends names one of those paths, or — when the target is a
# class_name — when the file uses the class token as an identifier. The context is
# the matched line, trimmed, so an agent locates the reference without re-reading.
# Dispatches on extension BEFORE reading (issue #378): only the reference-bearing
# text formats (_has_outgoing_references' .tscn/.tres/.gd set) are ever decoded,
# so a binary artifact in the walked tree (an exported .pck/.app under build/)
# never hits the engine's UTF-8 decode and never spams a per-file "Unicode
# parsing error" to stderr. The graph universe is unchanged — only the decode
# narrows, mirroring the ext-first shape of _outgoing_references_of.
static func _collect_references_from(path: String, target_paths: Dictionary, target_class: String, references: Array) -> void:
	if not _has_outgoing_references(path):
		return
	var ext := path.get_extension().to_lower()
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		return
	if ext == "tscn" or ext == "tres":
		var ext_base_dir := path.get_base_dir()
		# The SAME reader the dependencies harvest uses (#775), so the incoming and
		# outgoing views of the graph cannot recognize a different set of lines or
		# read a different attribute out of one.
		for entry in SCENE_TEXT._raw_ext_resource_entries_from_text(text):
			# One identity on BOTH sides: target_paths is seeded canonical, and the
			# declared spelling is folded here through the SAME owner the harvest
			# side uses (_resolve_ref_path — anchor to the declaring file's
			# directory, then canonicalize), so an aliased OR relative declaration
			# matches a canonical query and the reverse (#774).
			if target_paths.has(SCENE_TEXT._resolve_ref_path(String(entry["path"]), ext_base_dir)):
				# The context is the declaration as WRITTEN, so the agent still sees
				# the spelling it must edit — only the MATCHING is normalized.
				references.append({
					"path": path,
					"kind": "ext_resource",
					"context": String(entry["line"]),
				})
	elif ext == "gd":
		var base_dir := path.get_base_dir()
		for line in text.split("\n"):
			var stripped := line.strip_edges()
			# A preload/load/extends-by-path naming one of the target's paths.
			for ref in _script_outgoing_references_in_line(stripped, base_dir):
				if target_paths.has(ref["path"]):
					references.append({"path": path, "kind": ref["kind"], "context": stripped})
			# A class_name target used as a bare identifier token (extends Name,
			# `var x: Name`, `Name.new()`, …). Best-effort: a whole-word token
			# match, so a substring of a longer identifier is not a false hit.
			# Skip the target's OWN `class_name <target>` declaration line: that is
			# the definition site, not a reference (issue #116 review). Without this
			# guard the class's defining file reports itself as a class_reference.
			if (
				not target_class.is_empty()
				and not _is_class_name_declaration_of(stripped, target_class)
				and _line_uses_token(stripped, target_class)
			):
				references.append({"path": path, "kind": "class_reference", "context": stripped})


# The {path, kind} references in a SINGLE already-stripped .gd line — the
# per-line core _script_outgoing_references loops over, factored out so
# find-references can match a target path AND keep the matched line as context.
# Finds EVERY preload(...)/load(...) call on the line (not just the first), so a
# line with two calls is fully captured; each call's marker is matched on a word
# boundary so `load(` INSIDE `preload(` is not double-counted as its own load
# reference (the markers overlap as substrings, issue #116 review).
static func _script_outgoing_references_in_line(stripped: String, base_dir: String) -> Array:
	var out: Array = []
	var markers: Array[String] = ["preload", "load"]
	for marker in markers:
		var call: String = marker + "("
		var from := 0
		while true:
			var idx := stripped.find(call, from)
			if idx == -1:
				break
			from = idx + call.length()
			# Word boundary on the left: the char before the marker must not be an
			# identifier char, or this is a longer identifier ending in the marker
			# (the `load(` inside `preload(`, or a user `myload(`), not a call to it.
			if idx > 0 and GDSCRIPT_SCAN._is_identifier_char(stripped[idx - 1]):
				continue
			var arg := SCENE_TEXT._first_quoted_after(stripped, idx + call.length())
			if arg.is_empty():
				continue
			out.append({"path": SCENE_TEXT._resolve_ref_path(arg, base_dir), "kind": marker})
	if stripped.begins_with("extends ") and stripped.find("\"") != -1:
		var ext_arg := SCENE_TEXT._first_quoted_after(stripped, "extends ".length())
		if not ext_arg.is_empty():
			out.append({"path": SCENE_TEXT._resolve_ref_path(ext_arg, base_dir), "kind": "class_extends"})
	return out


# Project-level references to the target that live in project.godot rather than a
# scanned file (issue #116): the main scene (run/main_scene) and the autoloads
# (autoload/*). These reference a resource by path the way a file's ext_resource
# does, so find-references must surface them or the target would look less
# referenced than it is.
static func _collect_project_level_references(target_paths: Dictionary, references: Array) -> void:
	var main_scene := _main_scene_path()
	if not main_scene.is_empty() and target_paths.has(main_scene):
		references.append({"path": "project.godot", "kind": "main_scene", "context": "application/run/main_scene=" + main_scene})
	for autoload in _project_autoloads():
		if target_paths.has(autoload["path"]):
			references.append({"path": "project.godot", "kind": "autoload", "context": "autoload/" + autoload["name"] + "=" + autoload["path"]})


# The project entry points — paths that are "reached" without a file reference, so
# find-unused must never flag them: the main scene plus every autoload's path.
static func _project_entry_points() -> Array[String]:
	var out: Array[String] = []
	var main_scene := _main_scene_path()
	if not main_scene.is_empty():
		out.append(main_scene)
	for autoload in _project_autoloads():
		out.append(autoload["path"])
	return out


# The project's main scene res:// path, or "" when none is set. Read from
# ProjectSettings — never run.
static func _main_scene_path() -> String:
	var value: Variant = ProjectSettings.get_setting("application/run/main_scene", "")
	# Canonical like every other path in the graph (#774): an aliased
	# run/main_scene left the project's entry point matching nothing the walk
	# found, so find-unused-resources reported the MAIN SCENE as unused.
	# simplify_path("") is "", so an unset main scene stays the empty "none".
	return SCENE_TEXT._canonical_resource_path(String(value))


# The project's autoload singletons as {name, path} entries, read from
# ProjectSettings's autoload/* keys (never executed). The stored value carries a
# leading "*" enable marker for an enabled singleton; it is stripped so the path
# is the bare res:// path the rest of the graph compares against, then
# canonicalized like every other path in the graph (#774). Order matters: the
# marker must come off FIRST, because simplify_path does not recognize a scheme
# behind it and folds "*res://a/../b.gd" to the broken "*res:/b.gd".
static func _project_autoloads() -> Array:
	var out: Array = []
	for setting in ProjectSettings.get_property_list():
		var key := String(setting.get("name", ""))
		if not key.begins_with("autoload/"):
			continue
		var autoload_name: String = key.substr("autoload/".length())
		var value := String(ProjectSettings.get_setting(key, ""))
		out.append({"name": autoload_name, "path": SCENE_TEXT._canonical_resource_path(value.trim_prefix("*"))})
	return out


# The enabled editor plugins' plugin.cfg res:// paths (issue #116). Read from
# editor_plugins/enabled in ProjectSettings; each entry is already a
# res://addons/<name>/plugin.cfg path. Empty when the project enables none.
static func _project_plugins() -> Array[String]:
	var out: Array[String] = []
	var enabled: Variant = ProjectSettings.get_setting("editor_plugins/enabled", PackedStringArray())
	if enabled is PackedStringArray or enabled is Array:
		for entry in enabled:
			out.append(String(entry))
	return out


# Count the lines of a TEXT file (issue #116): the number of newline-separated
# parts of its content, treating a binary/unreadable file as 0 lines. A trailing
# newline does not add a phantom empty final line, so "a\nb\n" is 2 lines. Only
# called on files statistics counts.
#
# Line-count ONLY known text extensions (issue #116 review): a binary asset (an
# image, a font, audio) must contribute to the file count but NOT the line count
# — statistics' documented contract. Reading every file as text counted a binary
# asset's stray newline bytes as lines, inflating total_lines. An unknown
# extension is treated as binary (0 lines) rather than read as text.
static func _count_lines(path: String) -> int:
	if not _is_text_extension(path.get_extension().to_lower()):
		return 0
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		return 0
	var normalized := text.replace("\r\n", "\n")
	var parts := normalized.split("\n")
	var count := parts.size()
	# A trailing newline yields a final empty part; do not count it as a line.
	if count > 0 and parts[count - 1].is_empty():
		count -= 1
	return count


# The file extensions statistics treats as text for line counting (issue #116
# review). Covers Godot's text formats (.gd/.tscn/.tres scenes & resources, the
# .godot/.cfg/.import config files, .gdshader) plus common plain-text companions
# (docs, data, the C# source). Anything else — images, audio, fonts, .res binary
# resources — is binary: it counts as a file but contributes 0 lines.
static func _is_text_extension(ext: String) -> bool:
	return ext in [
		"gd", "tscn", "tres", "godot", "cfg", "import", "gdshader", "gdshaderinc",
		"cs", "json", "txt", "md", "xml", "csv", "ini", "po", "pot", "gdextension",
	]


# Whether a line uses `token` as a WHOLE-WORD identifier — bounded by a non
# identifier character (or the line edge) on both sides — so a class_name match
# is not a false positive on a substring of a longer name (Hero vs HeroSpawner)
# or inside another word. Best-effort static check for class_name references that
# carry no res:// path (extends Name, type annotations, Name.new()).
static func _line_uses_token(line: String, token: String) -> bool:
	var from := 0
	while true:
		var idx := line.find(token, from)
		if idx == -1:
			return false
		var before_ok := idx == 0 or not GDSCRIPT_SCAN._is_identifier_char(line[idx - 1])
		var after_index := idx + token.length()
		var after_ok := after_index >= line.length() or not GDSCRIPT_SCAN._is_identifier_char(line[after_index])
		if before_ok and after_ok:
			return true
		from = idx + 1
	return false


# Whether an already-stripped .gd line is the `class_name <target>` declaration
# of the find-references target — the definition site, not a reference. Matches
# the same `class_name ` prefix _parse_script_meta keys on, with the first token
# of the remainder equal to the target class (so `class_name HeroSpawner` is not
# treated as Hero's declaration). Lets find-references exclude a class's own
# defining line from its class_reference hits (issue #116 review).
static func _is_class_name_declaration_of(line: String, target_class: String) -> bool:
	if not line.begins_with("class_name "):
		return false
	return GDSCRIPT_SCAN._first_token(line.substr("class_name ".length())) == target_class
