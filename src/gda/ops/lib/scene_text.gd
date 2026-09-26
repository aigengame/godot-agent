extends RefCounted

# gda headless operations payload: the .tscn/.tres text format (ADR-0043 §2) —
# headers and ext_resource entries, the resolution of the paths they carry, and
# the rewrite that keeps existing ext_resource ids stable on a re-save. Static.


# Whether one trimmed line OPENS the section named `tag_name` — the SINGLE owner
# of section recognition for every reader of scene text (#720 recheck ×2, #775).
#
# The section NAME must be exactly `tag_name`: after the tag comes the closing
# bracket or the whitespace before attributes, or a longer name passes a bare
# prefix test. That is not hypothetical — `[gd_scenery]` reads as a scene header
# and `[ext_resource_group …]` reads as a declaration, while the ENGINE refuses
# both outright ("Unknown tag 'ext_resource_group' in file",
# resource_format_text.cpp, measured on 4.6.3). Three askers used to spell the
# rule three different ways — closed, bare prefix, and space-only — so the rule
# is stated here once instead of respelled per section.
#
# `]`, " " and "\t" are the accepting characters because that is where the
# engine's own tokenizer ends the tag name — VariantParser reads it as an
# identifier, so any non-identifier character closes it.
static func _is_section_header_line(stripped: String, tag_name: String) -> bool:
	var tag := "[" + tag_name
	if not stripped.begins_with(tag) or stripped.length() <= tag.length():
		return false
	var next := stripped[tag.length()]
	return next == "]" or next == " " or next == "\t"


# node_path -> the ext_resource ids it references, inverted: id -> node paths
# (#664). Attribution is by TEXT because that is where the binding is still
# visible — the engine drops an unresolvable reference from the loaded scene.
#
# A [node ...] header opens a block and any other [section] closes it, so property
# lines are attributed to the node above them. The header line itself is scanned
# too: an instanced sub-scene carries its reference there (instance=ExtResource(…)).
# Every ExtResource(...) occurrence in a line counts, so a reference inside an
# array or dictionary value is attributed like a plain one.
#
# Best-effort, and the one known gap is worth naming: a MULTI-LINE property value
# whose continuation line starts with `[` (an array literal broken across lines)
# closes the block early, so later references in that node lose their attribution.
# Attribution only — the dependency itself is still found and reported, because the
# problems are read from the [ext_resource] lines, not from here.
static func _scene_ext_resource_nodes_by_id(text: String) -> Dictionary:
	var by_id := {}
	var node_path := ""
	for line in text.split("\n"):
		var stripped := line.strip_edges()
		if stripped.begins_with("["):
			node_path = _scene_node_path_from_header(stripped) if _is_node_header_line(stripped) else ""
		if node_path.is_empty():
			continue
		for id in _ext_resource_ids_in_line(stripped):
			if not by_id.has(id):
				by_id[id] = []
			var nodes: Array = by_id[id]
			if not nodes.has(node_path):
				nodes.append(node_path)
	return by_id


# Every ext_resource id an ExtResource("...") call in one line names, in order.
static func _ext_resource_ids_in_line(line: String) -> Array:
	var ids: Array = []
	var needle := "ExtResource("
	var at := line.find(needle)
	while at != -1:
		var id := _first_quoted_after(line, at + needle.length())
		if not id.is_empty():
			ids.append(id)
		at = line.find(needle, at + needle.length())
	return ids


# The ONE CANONICAL IDENTITY of a declared reference: the path every consumer
# keys a referenced file by, whichever kind of declaration named it — an
# [ext_resource] line, or a preload/load/extends argument. #774 left the two as
# twins under two names, identical but for a parameter name; #775 merged them, so
# the rule has one place to be read and one place to be corrected.
#
# A relative address is joined onto the DECLARING file's base directory first,
# because that is how the engine resolves it — `preload("../shared/util.gd")` in
# res://a/b.gd loads res://shared/util.gd, and an [ext_resource] line spelling the
# same way resolves the same way (measured on 4.6.3; the graph-identity note in
# the static-analysis section carries that measurement).
# An ALREADY-prefixed address is canonicalized too, and that half is the #774
# fix: it used to be returned verbatim, so preload("res://sub/../util.gd") and
# preload("res://util.gd") — and `res://leaf.tscn` and `res://./leaf.tscn` — were
# TWO graph nodes for ONE file. Everything downstream keys on this string: the
# dependency walk's "a path declared twice is checked once and reported once"
# rule, the sub-scene walk's own `answered`/`reached_depth`/`chain` sets, and the
# id-restoring re-save — so a lexical alias defeated all of them at once.
#
# simplify_path() is the ENGINE'S own normalization, not gda's invention: Godot
# reports `res://..\outside.gd` back as `res://../outside.gd` (measured on 4.6.3),
# and it leaves a scheme it does not own alone — `uid://abc` and `user://x.tscn`
# pass through unchanged (a uid:// reference round-trips through Godot's UID
# system, not the path graph). It collapses `.`, `..` and doubled separators
# without touching the scheme, which is exactly the identity question and nothing
# more.
static func _resolve_ref_path(ref: String, base_dir: String) -> String:
	if ref.begins_with("res://") or ref.begins_with("uid://") or ref.begins_with("user://"):
		return _canonical_resource_path(ref)
	return _canonical_resource_path(base_dir.path_join(ref))


# The value of the quoted attribute `attr_name` in a section-header line —
# path="res://x" in an [ext_resource] line, name="Root" in a [node] header — or
# "" when the line carries no such attribute.
#
# The name is matched WHOLE, never as a substring, and that rule is the reason
# this helper exists: `uid="uid://…"` also contains the substring `id=`, so a
# substring match reads an [ext_resource] line's uid as its id. The trap is open
# on every attribute a longer name can end with — a `…_path="…"` attribute ahead
# of the real `path="…"` hands back the wrong reference — so the rule is applied
# ONCE, here, for every header attribute gda reads (#775) rather than relearned
# per scan. A match is accepted only where the name starts a token: at the line
# start, after a space or a tab, or right after a `[`.
static func _quoted_named_attr(line: String, attr_name: String) -> String:
	var needle := attr_name + "="
	var from := 0
	while true:
		var idx := line.find(needle, from)
		if idx == -1:
			return ""
		var left_ok := (
				idx == 0
				or line[idx - 1] == " "
				or line[idx - 1] == "\t"
				or line[idx - 1] == "["
		)
		if left_ok:
			return _first_quoted_after(line, idx + needle.length())
		from = idx + 1
	return ""


# The contents of the first quoted string (single or double quotes) at/after
# `from` in `text`, or "" when there is none. Used to pull the literal-string
# argument out of preload("...") / load("...") / path="..." without compiling.
static func _first_quoted_after(text: String, from: int) -> String:
	var dq := text.find("\"", from)
	var sq := text.find("'", from)
	var open := -1
	var quote := "\""
	if dq != -1 and (sq == -1 or dq < sq):
		open = dq
		quote = "\""
	elif sq != -1:
		open = sq
		quote = "'"
	if open == -1:
		return ""
	var close := text.find(quote, open + 1)
	if close == -1:
		return ""
	return text.substr(open + 1, close - open - 1)


# The source scene's file-backed script bindings as {root-relative NodePath ->
# script res:// path}. This catches scripts that Godot failed to materialize
# because a preload target was missing: the node may still exist with no script,
# so walking the instantiated tree alone cannot see the dependency.
static func _scene_attached_external_scripts(scene_path: String) -> Dictionary:
	var text := FileAccess.get_file_as_string(scene_path)
	if text.is_empty():
		return {}
	var script_resources := _scene_script_ext_resources(text, scene_path.get_base_dir())
	var attached := {}
	var current_node_path := ""
	for line in text.split("\n"):
		var stripped := line.strip_edges()
		if _is_node_header_line(stripped):
			current_node_path = _scene_node_path_from_header(stripped)
			continue
		if current_node_path.is_empty():
			continue
		if stripped.find("ExtResource(") == -1:
			continue
		# The assigned property must BE `script`, not merely start with it: a
		# `script_owner = ExtResource("…")` property read as a script binding made
		# a mutating op refuse over a script no node actually carries (#775).
		var assign := stripped.find("=")
		if assign == -1 or stripped.substr(0, assign).strip_edges() != "script":
			continue
		var resource_id := _first_quoted_after(stripped, stripped.find("ExtResource("))
		if script_resources.has(resource_id):
			attached[NodePath(current_node_path)] = script_resources[resource_id]
	return attached


# The scene's Script-typed [ext_resource] declarations as {id -> res:// path},
# read through the ONE scene-text reader and folded through the ONE identity
# owner (#775).
#
# The value therefore compares equal to the resource_path the ENGINE reports for
# the same file however the declaration spelled it — relative or aliased —
# which is exactly the comparison _validate_scene_script_preload_dependencies
# makes. A declaration that resolves outside res:// (a uid:// reference) is left
# out: it names no path the engine would report back.
static func _scene_script_ext_resources(text: String, base_dir: String) -> Dictionary:
	var resources := {}
	for entry in _raw_ext_resource_entries_from_text(text):
		if String(entry["type"]) != "Script":
			continue
		var resource_id := String(entry["id"])
		var ref_path := _resolve_ref_path(String(entry["path"]), base_dir)
		if not resource_id.is_empty() and ref_path.begins_with("res://"):
			resources[resource_id] = ref_path
	return resources


# Whether one trimmed line OPENS a node block (#775). Three scans ask it: the
# node-to-ext_resource attribution, the attached-script binding read, and the
# instance-path recovery — each used to spell `[node ` for itself, so a header
# rule learned in one was learned in none of the others. Section recognition
# itself is _is_section_header_line's.
static func _is_node_header_line(stripped: String) -> bool:
	return _is_section_header_line(stripped, "node")


# The root-relative NodePath a [node …] header declares, or "" when the header
# names no node. Both attributes are read WHOLE-NAME (_quoted_named_attr), the
# same rule the [ext_resource] reader applies: a longer attribute ending in
# `name` or `parent` ahead of the real one would otherwise hand back its value.
static func _scene_node_path_from_header(header: String) -> String:
	var name := _quoted_named_attr(header, "name")
	if name.is_empty():
		return ""
	var parent := _quoted_named_attr(header, "parent")
	if parent.is_empty():
		return "."
	if parent == ".":
		return name
	return parent + "/" + name


# SceneState exposes whether a node is an instance and can resolve the root type,
# but the public PackedScene object it returns does not reliably carry the
# original ext_resource path. Recover that marker from the .tscn header text and
# merge it into the SceneState projection.
static func _scene_instance_paths_by_node_path(path: String) -> Dictionary:
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		return {}
	var ext_resources_by_id := {}
	for entry in _ext_resource_entries_from_text(text, path.get_base_dir()):
		ext_resources_by_id[String(entry["id"])] = String(entry["normalized_path"])

	var instance_paths := {}
	for line in text.split("\n"):
		var stripped := line.strip_edges()
		if not _is_node_header_line(stripped):
			continue
		# `instance` is a header ATTRIBUTE, so it is read by NAME like every other
		# one (#775): a substring scan for `instance=ExtResource(` answered a decoy
		# `fallback_instance=ExtResource("…")` ahead of it, and `scene get` then
		# reported the wrong instanced scene for the node.
		var id := _quoted_named_attr(stripped, "instance")
		if id.is_empty() or not ext_resources_by_id.has(id):
			continue
		var node_path := _scene_node_path_from_header(stripped)
		if not node_path.is_empty():
			instance_paths[node_path] = ext_resources_by_id[id]
	return instance_paths


# Restore ext_resource ids that already existed in the target .tscn before
# ResourceSaver re-serialized it. Scope is deliberately narrow: match resources by
# their normalized ext_resource path, rewrite only id="..." attributes and
# ExtResource("...") references, and leave all other saver canonicalization alone
# (issue #393). If ResourceSaver collapses duplicate entries for the same path, keep
# the first old id for that canonical path rather than accepting a freshly generated
# id.
static func _restore_existing_ext_resource_ids(
		scene_path: String,
		original_text: String,
		saved_text: String) -> String:
	if original_text.is_empty() or saved_text.is_empty():
		return saved_text
	var base_dir := scene_path.get_base_dir()
	var original_ids := _ext_resource_ids_by_path(original_text, base_dir)
	if original_ids.is_empty():
		return saved_text
	var saved_entries := _ext_resource_entries_from_text(saved_text, base_dir)
	if saved_entries.is_empty():
		return saved_text

	var reserved_ids := {}
	for entry in saved_entries:
		var ref_path := String(entry["normalized_path"])
		if original_ids.has(ref_path):
			for old_id in original_ids[ref_path]:
				reserved_ids[String(old_id)] = true
	if reserved_ids.is_empty():
		return saved_text

	var used_ids := {}
	var id_remap := {}
	var path_positions := {}
	for entry in saved_entries:
		var saved_id := String(entry["id"])
		var ref_path := String(entry["normalized_path"])
		var final_id := saved_id
		if original_ids.has(ref_path):
			var position := int(path_positions.get(ref_path, 0))
			var old_ids: Array = original_ids[ref_path]
			if position < old_ids.size():
				final_id = String(old_ids[position])
			path_positions[ref_path] = position + 1
		elif reserved_ids.has(final_id):
			final_id = _fresh_ext_resource_id(saved_id, used_ids, reserved_ids)
		if used_ids.has(final_id):
			final_id = _fresh_ext_resource_id(saved_id, used_ids, reserved_ids)
		used_ids[final_id] = true
		if final_id != saved_id:
			id_remap[saved_id] = final_id

	if id_remap.is_empty():
		return saved_text
	return _replace_ext_resource_ids(saved_text, id_remap)


# Whether one trimmed line DECLARES an external resource (#775). The entries
# reader below and the save-side id substitution are its two askers; the
# substitution rewrites lines in place and so cannot go through the reader, but it
# must agree with it on WHICH lines it may touch. Section recognition itself is
# _is_section_header_line's, not respelled here.
static func _is_ext_resource_line(stripped: String) -> bool:
	return _is_section_header_line(stripped, "ext_resource")


# Every [ext_resource] declaration in one scene/resource text, as written — the
# ONE reader of scene text (#775). Four more scans over these same lines lived
# beside this one, and three of them still pulled the path out with a SUBSTRING
# match: this reader was BORN whole-name (#394 landed it together with
# _quoted_named_attr), and the older scans it grew up beside never learned the
# rule. Adapting them onto this reader ends the class for [ext_resource]
# attributes; the ExtResource("…") CALL-SITE scan over property values
# (_ext_resource_ids_in_line) is a separate read and is still a substring match.
#
# The entry is the line's own content, unresolved: `path` is the spelling the
# declaration used, and anchoring it to a base directory is the caller's step
# (_resolve_ref_path, or the id-keyed view below). A line naming no path declares
# no reference and is dropped.
static func _raw_ext_resource_entries_from_text(text: String) -> Array:
	var entries: Array = []
	for line in text.split("\n"):
		var stripped := line.strip_edges()
		if not _is_ext_resource_line(stripped):
			continue
		var ref_path := _quoted_named_attr(stripped, "path")
		if ref_path.is_empty():
			continue
		# `type` is the class the line DECLARES for the reference ("Script",
		# "Texture2D", …); "" when the line names none. Carried so scene-validate can
		# report what was expected at a path that did not resolve (#664) — the
		# id/path consumers ignore it.
		#
		# `line` is the declaration as WRITTEN (trimmed): find-references reports it
		# as the match context, so an agent sees the spelling it has to edit.
		entries.append({
			"path": ref_path,
			"id": _quoted_named_attr(stripped, "id"),
			"type": _quoted_named_attr(stripped, "type"),
			"line": stripped,
		})
	return entries


# The ID-KEYED view of the same declarations, each resolved to its canonical
# graph identity against the declaring file's directory. A declaration with no
# `id` is left out because the ENGINE refuses the whole file over it — "Parse
# Error: Missing 'id' in external resource tag" (resource_format_text.cpp,
# measured on 4.6.3), and `scene validate` answers not_a_scene. That is what
# separates an id-less line from an unknown ATTRIBUTE, which Godot accepts and
# this reader therefore must read correctly.
static func _ext_resource_entries_from_text(text: String, base_dir: String) -> Array:
	var entries: Array = []
	for entry in _raw_ext_resource_entries_from_text(text):
		var id := String(entry["id"])
		if id.is_empty():
			continue
		var ref_path := String(entry["path"])
		entries.append({
			"path": ref_path,
			"normalized_path": _resolve_ref_path(ref_path, base_dir),
			"id": id,
			"type": String(entry.get("type", "")),
		})
	return entries


# The canonical spelling of one already-absolute path — the identity half of
# _resolve_ref_path, split out so a caller that has no base directory to resolve
# against can key by the SAME identity (#721 review round 3).
#
# The composed scene walk is that caller: its root arrives from the command line
# rather than from an [ext_resource] line, and seeding the walk with the caller's
# raw spelling put the root behind a different identity from every one of its
# children — `res://./main.tscn` and the `res://main.tscn` a child references back
# were two files, so the root was answered for twice.
static func _canonical_resource_path(path: String) -> String:
	return path.simplify_path()


static func _ext_resource_ids_by_path(text: String, base_dir: String) -> Dictionary:
	var by_path := {}
	for entry in _ext_resource_entries_from_text(text, base_dir):
		var ref_path := String(entry["normalized_path"])
		if not by_path.has(ref_path):
			by_path[ref_path] = []
		(by_path[ref_path] as Array).append(String(entry["id"]))
	return by_path


static func _fresh_ext_resource_id(seed: String, used_ids: Dictionary, reserved_ids: Dictionary) -> String:
	var base := seed if not seed.is_empty() else "resource"
	var index := 2
	var candidate := base + "_gda" + str(index)
	while used_ids.has(candidate) or reserved_ids.has(candidate):
		index += 1
		candidate = base + "_gda" + str(index)
	return candidate


static func _replace_ext_resource_ids(text: String, id_remap: Dictionary) -> String:
	var updated := text
	var placeholders := {}
	var index := 0
	for saved_id in id_remap:
		var placeholder := "__GDA_EXT_RESOURCE_ID_" + str(index) + "__"
		while updated.find(placeholder) != -1:
			index += 1
			placeholder = "__GDA_EXT_RESOURCE_ID_" + str(index) + "__"
		placeholders[placeholder] = String(id_remap[saved_id])
		updated = _replace_ext_resource_id_attr(
				updated,
				String(saved_id),
				placeholder)
		updated = updated.replace(
				'ExtResource("' + String(saved_id) + '")',
				'ExtResource("' + placeholder + '")')
		index += 1
	for placeholder in placeholders:
		updated = _replace_ext_resource_id_attr(
				updated,
				String(placeholder),
				String(placeholders[placeholder]))
		updated = updated.replace(
				'ExtResource("' + String(placeholder) + '")',
				'ExtResource("' + String(placeholders[placeholder]) + '")')
	return updated


static func _replace_ext_resource_id_attr(text: String, old_id: String, new_id: String) -> String:
	var old_attr := 'id="' + old_id + '"'
	var new_attr := 'id="' + new_id + '"'
	var lines := text.split("\n")
	for index in lines.size():
		var line := String(lines[index])
		if _is_ext_resource_line(line.strip_edges()):
			lines[index] = line.replace(old_attr, new_attr)
	return "\n".join(lines)
