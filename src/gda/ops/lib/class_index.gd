extends RefCounted

# gda headless operations payload: the class_name → script index and its
# resolver (ADR-0032, ADR-0043 §2), and script instancing. Static, with the
# per-process index cache in a static var (ADR-0043 §4).

const GDSCRIPT_SCAN := preload("gdscript_scan.gd")
const PROJECT_WALK := preload("project_walk.gd")


# The gda-owned static class_name → declaring-.gd-paths index (ADR-0032), the
# cache-independent fallback tier of the unified resolver. Built lazily once per
# process run (a headless op is one-shot, so this is per-op) and reused across
# the node-add / resource-create / find-references call sites. `_built` guards
# the lazy build so an empty project (no class_name declared) is distinguished
# from an unbuilt index rather than rescanning res:// on every miss.
static var _project_class_index: Dictionary = {}
static var _project_class_index_built := false


# The single unified project-local class_name resolver (ADR-0032), shared by node
# add, resource create, and find-references so the three sites agree on whether a
# class_name resolves in an editor-never-opened project. Resolves ONLY the
# class_name → script-path step; the built-in-engine-class tier and the
# Node-vs-Resource base-class check stay in each caller. The chain is cache-first:
#   tier 2 — the editor global class list (get_global_class_list), populated only
#            by the Godot editor scan, kept FIRST so an editor-opened project
#            resolves exactly as before (the fallback is unobservable there);
#   tier 3 — a gda-owned static scan of the project's own .gd sources, invoked
#            only when the cache misses, so a headless editor-never-opened project
#            still resolves a valid project-local class_name.
# Returns a status Dictionary the caller matches on:
#   {"status": "resolved", "path": "res://…gd"}
#   {"status": "ambiguous", "paths": [conflicting res:// paths]}
#   {"status": "not_found"}
# A class_name declared in more than one .gd is ambiguous, never first-file-wins
# (ADR-0032): a nondeterministic pick would mask a real project error the editor
# itself reports. The scan runs NO project code — it parses raw source only.
static func _resolve_project_class_script(class_token: String) -> Dictionary:
	if class_token.is_empty():
		return {"status": "not_found"}
	# Tier 2: the editor global class list (cache-first). A populated cache never
	# carries a duplicate — the editor rejects that — so no ambiguity check here.
	for entry in ProjectSettings.get_global_class_list():
		if String(entry.get("class", "")) == class_token:
			return {"status": "resolved", "path": String(entry.get("path", ""))}
	# Tier 3: the gda-owned static scan, built once per process and reused.
	var index := _project_class_name_index()
	if not index.has(class_token):
		return {"status": "not_found"}
	var declaring: Array = index[class_token]
	if declaring.size() > 1:
		return {"status": "ambiguous", "paths": declaring}
	return {"status": "resolved", "path": String(declaring[0])}


# Build (once per process) the class_name → declaring-.gd-paths index for the
# resolver's tier-3 static scan (ADR-0032). Walks the full res:// tree skipping
# the root cache — reusing the extension-filtered collector
# (_collect_resource_paths, which already enumerates .gd among the graph
# resources) — and parses each .gd's
# class_name from raw source with the existing never-compiled parser
# (_script_metadata). A class_name declared in more than one .gd maps to multiple
# paths (sorted, so an ambiguous_class_name error is deterministic regardless of
# traversal order). Runs NO project code.
static func _project_class_name_index() -> Dictionary:
	if _project_class_index_built:
		return _project_class_index
	var paths: Array[String] = []
	PROJECT_WALK._collect_resource_paths("res://", paths)
	for path in paths:
		if not GDSCRIPT_SCAN._is_script_path(path):
			continue
		# get_file_as_string returns "" for an unreadable OR empty .gd; either way
		# it declares no class_name, so it simply contributes nothing to the index.
		var meta := GDSCRIPT_SCAN._script_metadata(FileAccess.get_file_as_string(path))
		var declared: Variant = meta.get("class_name")
		if declared == null:
			continue
		var token := String(declared)
		if not _project_class_index.has(token):
			_project_class_index[token] = []
		(_project_class_index[token] as Array).append(path)
	for token in _project_class_index:
		(_project_class_index[token] as Array).sort()
	_project_class_index_built = true
	return _project_class_index


# The shared ambiguous_class_name failure message (ADR-0032), emitted uniformly by
# all three resolver call sites: it names the class and every conflicting script
# path so an agent can repair the project (declare the class_name in exactly one
# .gd) rather than depend on a nondeterministic first-file-wins pick.
static func _ambiguous_class_name_message(class_token: String, paths: Array) -> String:
	return "class_name " + class_token + " is declared in more than one script, so it cannot be resolved to a single script; declare it in exactly one .gd. Conflicting scripts: " + ", ".join(PackedStringArray(paths))


# Isolated so an engine-raised call error from Script.new() — a constructor
# that needs arguments, or a script broken in a way can_instantiate() does not
# catch — aborts only this helper frame; the caller observes null and reports
# the failure structurally instead of degrading into an unstructured abort.
static func _new_script_instance(script: Script) -> Variant:
	return script.new()


# The class_name of the node's attached script, or null for a plain built-in
# node (or a script with no class_name) — the result field an agent asserts to
# confirm a class_name addition took effect.
static func _script_class_of(node: Node) -> Variant:
	var script := node.get_script() as Script
	if script == null:
		return null
	var global_name := String(script.get_global_name())
	if global_name.is_empty():
		return null
	return global_name
