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
# class_name → script-path step; the built-in-class tier and the base-class
# check are the instancing ladder's (_instantiate_class). The chain is cache-first:
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


# The stale-entry predicate (#1073): the ONE check that a class index entry
# still names what its script declares. Only the editor filesystem scan (the
# engine import pass, `gda project scan`) writes the index, so after a
# `class_name` is renamed or removed with no scan the entry keeps the old name
# while the script compiles under the new one (or under none). The predicate
# applies only to a script that COMPILED (`can_instantiate()`): the engine sets
# a script's declared name only when its compile succeeds, so a script that does
# not compile declares no name. Such a script keeps its compile diagnostic and
# is never a stale entry — a scan writes the same entry again. It reads the name
# the engine compiled and runs no extra compile and no project code.
static func _declares_other_class(script: Script, entry_class: String) -> bool:
	return script != null and script.can_instantiate() \
			and String(script.get_global_name()) != entry_class


# One stale entry as both uses report it: the entry's class, its script path and
# the name the script declares now ("" when it declares none).
static func _stale_entry(entry_class: String, path: String, script: Script) -> Dictionary:
	return {"name": entry_class, "path": path, "declared_name": String(script.get_global_name())}


# The write refusal's message (`class_index_stale`): names the entry, what the
# script declares now, and the remedy.
static func _stale_entry_message(stale: Dictionary) -> String:
	var declared := String(stale["declared_name"])
	var now := "declares no class_name" if declared.is_empty() else "declares class_name " + declared
	return "the class index is stale: its entry " + String(stale["name"]) + " names " \
			+ String(stale["path"]) + ", which now " + now \
			+ "; run `gda project scan` and retry (nothing was written)"


# Validate's use of the predicate (#1073): every index entry whose script is
# loaded in this process — the compile's dependencies and the project's
# autoloads, which the engine loads at startup before the op runs. Only scripts
# already in the resource cache are read, so this loads and compiles nothing.
static func _stale_loaded_entries() -> Array:
	var stale: Array = []
	for entry in ProjectSettings.get_global_class_list():
		var path := String(entry.get("path", ""))
		if path.is_empty() or not ResourceLoader.has_cached(path):
			continue
		var script := ResourceLoader.get_cached_ref(path) as Script
		var entry_class := String(entry.get("class", ""))
		if _declares_other_class(script, entry_class):
			stale.append(_stale_entry(entry_class, path, script))
	stale.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return String(a["name"]) < String(b["name"]))
	return stale


# Isolated so an engine-raised call error from Script.new() — a constructor
# that needs arguments, or a script broken in a way can_instantiate() does not
# catch — aborts only this helper frame; the ladder observes null and returns the
# constructor refusal instead of degrading into an unstructured abort.
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


# The steps of the class_name instancing ladder that can refuse, in ladder order.
enum Refusal { UNKNOWN, AMBIGUOUS, LOAD, COMPILE, STALE, CONSTRUCT, WRONG_BASE }


# The class_name instancing ladder (#1192) that node add --type and resource
# create --type share: it makes one instance of a `base`-derived class ("Node" or
# "Resource") from a class token. First a built-in engine class that ClassDB can
# instantiate and that derives from `base`. class_exists gates can_instantiate:
# probing a class ClassDB does not know (a project-local class_name) logs a
# spurious engine ERROR (issue #377). Then a project class_name, through the
# resolver above. Returns {"instance": the new Object}, or {"refusal": Refusal,
# "message": String}. It records no failure (ADR-0043 §4): each caller maps the
# refusal to its own code.
static func _instantiate_class(class_token: String, base: String) -> Dictionary:
	if not class_token.is_empty() and ClassDB.class_exists(class_token) \
			and ClassDB.can_instantiate(class_token) and ClassDB.is_parent_class(class_token, base):
		return {"instance": ClassDB.instantiate(class_token)}
	var resolution := _resolve_project_class_script(class_token)
	match resolution["status"]:
		"resolved":
			return _instantiate_script_class(class_token, String(resolution["path"]), base)
		"ambiguous":
			return _refusal(Refusal.AMBIGUOUS,
					_ambiguous_class_name_message(class_token, resolution["paths"]))
		_:
			return _refusal(Refusal.UNKNOWN, "not an instantiable " + base
					+ " class, and no .gd script declares class_name " + class_token
					+ " (check for a misspelled name, or declare it with `class_name " + class_token + "`)")


# The ladder's steps for a resolved script. Resolution only proves that a .gd
# declares the class_name, not that the script loads, compiles, or constructs (a
# cached entry may be stale, and the static scan parses raw text with no compile;
# issue #65), so each step is checked and a failure is named as the script
# problem it is, never as an unknown type.
static func _instantiate_script_class(class_token: String, script_path: String,
		base: String) -> Dictionary:
	var script := ResourceLoader.load(script_path) as Script
	if script == null:
		return _refusal(Refusal.LOAD, "registered class_name " + class_token
				+ " script failed to load: " + script_path
				+ " — broken or removed since the project scan; see diagnostics")
	if not script.can_instantiate():
		return _refusal(Refusal.COMPILE, "registered class_name " + class_token
				+ " script cannot be instantiated: " + script_path
				+ " — it no longer compiles; see diagnostics")
	# The stale-entry predicate (#1073), after the load and compile checks so a
	# script that does not compile keeps its compile refusal: an entry whose
	# compiled script declares another name would write that name under this one.
	if _declares_other_class(script, class_token):
		return _refusal(Refusal.STALE,
				_stale_entry_message(_stale_entry(class_token, script_path, script)))
	var instance: Variant = _new_script_instance(script)
	if instance == null:
		return _refusal(Refusal.CONSTRUCT, "registered class_name " + class_token
				+ " script constructor failed: " + script_path
				+ " — its _init may require arguments; see diagnostics")
	# The same test as `instance is Node` or `instance is Resource`: GDScript's
	# `is` compares the instance's native class with ClassDB.is_parent_class, and
	# Script.new() makes the instance from the script's native base type. The
	# script supplies that type, not the instance: a project script can override
	# get_class(), and calling it would run project code.
	if ClassDB.is_parent_class(script.get_instance_base_type(), base):
		return {"instance": instance}
	if instance is Object and not (instance is RefCounted):
		instance.free()
	return _refusal(Refusal.WRONG_BASE, "registered class_name " + class_token
			+ " is not a " + base + "-derived script: " + script_path)


# The step is typed int, not Refusal: in a type hint, a project's global
# class_name of the same name resolves before this script's enum, and the payload
# would then not compile in that project.
static func _refusal(step: int, message: String) -> Dictionary:
	return {"refusal": step, "message": message}
