extends "../op_base.gd"

# gda headless operations payload: the script command group (ADR-0043). The
# entry, operations.gd, creates one instance per run and dispatches the group's
# operations to it.

const VALUE := preload("../lib/value.gd")
const PROJECT_WALK := preload("../lib/project_walk.gd")
const GDSCRIPT_SCAN := preload("../lib/gdscript_scan.gd")
const CLASS_INDEX := preload("../lib/class_index.gd")
const FILE_WRITE := preload("../lib/file_write.gd")
const TEXT_EDIT := preload("../lib/text_edit.gd")
const SCENE_STORE := preload("../lib/scene_store.gd")

# The instance concept modules this group's operations call, created with the
# group's frame and held for the group's life (ADR-0043 §4).
var _file_write: FILE_WRITE
var _text_edit: TEXT_EDIT
var _scene_store: SCENE_STORE


func _init(frame) -> void:
	super(frame)
	_file_write = FILE_WRITE.new(frame)
	_text_edit = TEXT_EDIT.new(frame)
	_scene_store = SCENE_STORE.new(frame)


# The per-script delimiter script-validate writes before each compile (#663), so
# gda can attribute a batch's advisory stderr diagnostics to individual files.
# The full line is DIAG_PREFIX + this + the script path, and that composition is
# mirrored Python-side by gda.commands.script.VALIDATE_MARKER_PREFIX. A test pins
# these two VALUES against that constant, so the contract survives any change to
# how or where the line is written.
const VALIDATE_MARKER := "validating: "


# script-create: write a new .gd script at the requested path — from verbatim
# content or a minimal built-in template — and report the saved path plus the
# class_name/extends the written source declares (issue #110). The script group
# addresses scripts by FILE PATH, not by class_name.
#
# This writes raw text (FileAccess), never compiling or loading the script:
# creating a script must not run project code, the same trust boundary the read
# ops honor (issue #30). No-clobber: an existing target is refused with
# already_exists, leaving it untouched (mirrors scene-create).
func _op_script_create(params: Dictionary) -> void:
	_diag("running operation: script-create")
	var path := VALUE._string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not GDSCRIPT_SCAN._is_script_path(path):
		_fail(OP_ERROR_INVALID_PATH, "script path must end in .gd: " + path)
		return
	if FileAccess.file_exists(path) or DirAccess.dir_exists_absolute(path):
		_fail(OP_ERROR_ALREADY_EXISTS, "script target already exists: " + path)
		return

	# Verbatim content wins; otherwise write a minimal template extending the
	# requested base class (defaulting to Node).
	var source: String
	var content: Variant = params.get("content", null)
	if content is String:
		source = content
	else:
		var base := VALUE._string_param(params, "extends_type")
		if base.is_empty():
			base = "Node"
		source = "extends " + base + "\n"

	var created_dirs: Variant = _file_write._ensure_parent_dirs(path)
	if created_dirs == null:
		return  # _ensure_parent_dirs already recorded the failure
	if not _write_script_file(path, source):
		return  # _write_script_file already recorded the failure

	var meta := GDSCRIPT_SCAN._script_metadata(source)
	_succeed({
		"path": path,
		"class_name": meta["class_name"],
		"extends": meta["extends"],
		"created_dirs": created_dirs,
	})


# script-get: read a script's source back as RAW TEXT and report it with the
# class_name/extends the source declares — the read half of issue #110, which
# makes a script-create verifiable end-to-end (create → get returns the source).
#
# Reads via FileAccess.get_file_as_string (which resolves res:// against the
# project) and parses the metadata from the text — it never load()s/compiles the
# script, so reading a script can never run or even parse-execute project code
# (issue #30).
func _op_script_get(params: Dictionary) -> void:
	_diag("running operation: script-get")
	var path := VALUE._string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_script(path):
		return  # _require_existing_script already recorded the failure

	var source: Variant = _read_script_source(path)
	if source == null:
		return  # _read_script_source already recorded the failure

	var meta := GDSCRIPT_SCAN._script_metadata(source)
	_succeed({
		"path": path,
		"source": source,
		"class_name": meta["class_name"],
		"extends": meta["extends"],
	})


# script-list: enumerate the project's .gd scripts (issue #117). Walks the
# project's res:// tree, reporting each script's res:// path plus the
# class_name/extends parsed from its raw source (no compilation, exactly like
# script-get, issue #30 — listing must not execute project code). Mirrors
# scene-list (issue #54): a script whose source declares neither is still
# listed, with null metadata, so the listing names every .gd it found.
#
# Enumerating res:// requires a project: a projectless headless process has no
# res:// tree to walk, so script-list refuses with project_not_found rather than
# returning a misleading empty listing.
func _op_script_list(_params: Dictionary) -> void:
	_diag("running operation: script-list")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "script list requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var paths: Array[String] = []
	_collect_script_paths("res://", paths)
	paths.sort()

	var scripts: Array = []
	for path in paths:
		scripts.append(_script_summary(path))

	_succeed({"scripts": scripts})


# script-delete: remove a script file and report what was removed (issue #117).
# Reuses the script group's existing addressing boundary (must be .gd → missing
# file → path_not_found), exactly as script-get does: delete only removes a .gd
# script that exists, so a non-.gd target is refused with invalid_path and a
# stray missing path with path_not_found, never silently deleting an arbitrary
# file. The class_name/extends are parsed from the raw source before deletion so
# the result names the content removed, not just the path (mirrors scene-delete).
func _op_script_delete(params: Dictionary) -> void:
	_diag("running operation: script-delete")
	var path := VALUE._string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_script(path):
		return  # _require_existing_script already recorded the failure

	# Read the metadata before deletion so the result names the content removed.
	# A read error here is non-fatal: the file exists and is about to be deleted,
	# so fall back to null metadata rather than failing the delete.
	var meta := GDSCRIPT_SCAN._script_metadata(FileAccess.get_file_as_string(path))

	var err := DirAccess.remove_absolute(path)
	if err != OK:
		_fail(OP_ERROR_DELETE_FAILED, "failed to delete script " + path + ": " + error_string(err))
		return

	_succeed({
		"path": path,
		"class_name": meta["class_name"],
		"extends": meta["extends"],
	})


# script-set: edit an EXISTING .gd script on disk as RAW TEXT (issue #118) — it
# never compiles or loads the script, so editing it cannot run project code (the
# read trust boundary of issue #30, the same one create/get/delete honor). Three
# mutually-exclusive edit modes; the CLI resolves exactly one and stamps it on the
# explicit `mode` discriminator the op dispatches on (issue #133), never re-inferred
# here from which params are present:
# - search-replace: replace EVERY literal (not regex) occurrence of `search`.
# - line-range: replace the 1-based, inclusive line span [start_line, end_line]
#   with `content`. Lines are the parts of the source split on "\n", so a
#   trailing newline yields a final empty part ("a\nb\n" → ["a","b",""], 3 lines).
# - full: overwrite the whole file with `content`.
# set edits an existing script; it never creates — a missing target is
# path_not_found, not a silent create.
func _op_script_set(params: Dictionary) -> void:
	_diag("running operation: script-set")
	var path := VALUE._string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_script(path):
		return  # _require_existing_script already recorded the failure

	var source: Variant = _read_script_source(path)
	if source == null:
		return  # _read_script_source already recorded the failure
	# Capture the staleness token right after the read (issue #226) — script-set writes
	# raw text directly, not via the shared tail, so it wires capture/recheck itself.
	_file_write._capture_staleness_token(path)

	# Dispatch on the explicit mode discriminator the CLI resolved (issue #133):
	# the edit mode is decided once, at the CLI's mutual-exclusion check, and rides
	# through on `mode` — the op never re-infers it from which params are present,
	# so the op's dispatch can no longer drift from the CLI's exclusivity rule.
	var mode := VALUE._string_param(params, "mode")
	var new_source: Variant
	match mode:
		"search_replace":
			new_source = _text_edit._apply_search_replace(source, params, "script")
		"line_range":
			new_source = _text_edit._apply_line_range(source, params, "script")
		"full":
			# full overwrite: content is guaranteed present by the CLI's mode check.
			new_source = VALUE._string_param(params, "content")
		_:
			# The CLI always supplies one of the three modes; a missing/unknown mode
			# means a malformed direct op invocation, not a reachable CLI path.
			_fail(OP_ERROR_INVALID_PARAMS, "unknown script-set mode: " + mode)
			return
	if new_source == null:
		return  # the apply helper already recorded the failure

	# Recheck before the write (issue #226): refuse if a concurrent editor changed the
	# .gd in the read->write window.
	if not _file_write._check_unchanged():
		return
	if not _write_script_file(path, new_source):
		return  # _write_script_file already recorded the failure

	# Re-parse the written source so set round-trips through script get.
	var meta := GDSCRIPT_SCAN._script_metadata(new_source)
	_succeed({
		"path": path,
		"class_name": meta["class_name"],
		"extends": meta["extends"],
	})


# script-attach: bind a .gd script to a node in a .tscn (issue #118). Load the
# scene → resolve the node by node path (the #53 addressing: '.' = root, 'A/B' =
# descendant) → load the .gd as a Script resource → node.set_script(script) →
# re-pack and save.
#
# As a scene MUTATION it goes through the shared mutate-entry (load → instantiate
# → unmaterialized-node guard, the same as node set), so it honors the
# mutation-integrity boundary (issue #64) and instantiates the scene — running
# the _init of scripts already attached in the scene (the inherent trust
# boundary of ADR-0009). For a script that compiles, set_script constructs an
# instance of the attached .gd, which RUNS that script's _init too — attach's
# project-code execution surface is both already-attached scripts and the
# newly-attached one.
#
# attach requires the script to COMPILE. On the standard headless build,
# set_script silently REJECTS a non-compiling script — the node's script stays
# null and a re-pack saves no script at all — so attach cannot honor a request
# to bind a broken script (verified: ResourceLoader.load returns a non-null
# Script for a .gd with a parse error, but get_script() is null after
# set_script). Rather than report a phantom success over a scene with no script
# attached, attach verifies the bind took effect and refuses a non-compiling
# script with script_compile_failed — fix it (or check with script validate).
#
# attach is a MUTATION verb (it is node.set_script): it OVERWRITES an existing
# binding rather than refusing it (issue #132) — there is no `script detach`, so
# refusing an already-scripted node would strand it. The overwrite is not silent:
# the prior script's resource_path is captured BEFORE set_script and reported as
# replaced_script (null only when the node had no prior script), so an agent can
# detect a clobber from the result.
#
# Error ordering (issue #132, Part 2): the primary subject (the scene loads + the
# addressed node exists) is validated BEFORE the secondary input (the --script
# arg). Both the .gd-shape check and the script-existence check (_require_existing_
# script) run AFTER the scene load and node resolution — one invariant, no
# exceptions. So with both the scene and the script missing, the scene problem is
# reported first. The accepted trade-off: a missing/malformed --script now pays
# the scene load+instantiate on the error path — fine, since ADR-0009 makes the
# project trusted (running _init is not a security concern) and the error path is
# rare.
func _op_script_attach(params: Dictionary) -> void:
	_diag("running operation: script-attach")
	var path := VALUE._string_param(params, "path")

	# Primary subject first: load + instantiate the scene, then resolve the node —
	# validated before the secondary --script input (issue #132, Part 2).
	var root: Node = _scene_store._load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure
	var node_path := VALUE._string_param(params, "node")
	var node := _scene_store._resolve_node(root, node_path)
	if node == null:
		_scene_store._fail_node_not_found(node_path)
		return
	# A node inside an instanced child the root does not hold as editable: the
	# file would record no script on it (#1054). Part of the primary subject, so
	# it is refused before the --script input is read.
	if _scene_store._refuse_foreign_write(root, SCENE_STORE.Write.ATTACH_SCRIPT, node):
		return

	# Secondary input: validate the --script arg only now — its .gd shape
	# (invalid_path) and existence (path_not_found), via the shared #135 helper — so
	# a scene/node problem is always reported ahead of a script problem (issue #132,
	# Part 2). The helper records the failure.
	var script_path := VALUE._string_param(params, "script")
	if not _require_existing_script(script_path):
		return  # _require_existing_script already recorded the failure
	if not _scene_store._validate_script_preload_dependencies(script_path):
		return  # _validate_script_preload_dependencies already recorded the failure

	# load returns a non-null Script even for a .gd that does not compile (compile
	# errors go to stderr; the resource still loads), so a null here is a genuine
	# resource-load failure (e.g. no format loader), not a compile verdict — guard
	# it so set_script is never handed null (which would clear the node's script).
	var script := ResourceLoader.load(script_path) as Script
	if script == null:
		_fail(OP_ERROR_INVALID_PATH, "file could not be loaded as a GDScript resource: " + script_path)
		return

	# Capture what this attach is about to DISPLACE before set_script overwrites it
	# (issue #132). A node that already carries a script yields its prior script's
	# resource_path verbatim — including a built-in/embedded script's sub-resource
	# ref (res://scene.tscn::GDScript_xxx) — so a displacement always reports a
	# non-null signal; a node with no prior script yields null.
	var replaced_script: Variant = _displaced_script_path(node)

	node.set_script(script)
	# set_script silently rejects a script it cannot bind: get_script() stays null
	# and a re-pack would save no script. Verify the bind took effect rather than
	# report a phantom success — and tell the two rejection modes apart so the
	# agent gets the right remediation: a script that does NOT compile is
	# script_compile_failed (fix the syntax), while one that compiles but whose
	# native base is incompatible with the node (e.g. an `extends Node3D` script
	# on a Node2D — the engine refuses the assignment) is incompatible_script_type
	# (attach it to a compatible node, or change the script's extends).
	if node.get_script() == null:
		var node_class := node.get_class()
		var script_base := script.get_instance_base_type()
		var compiles := script.reload() == OK
		if compiles:
			_fail(OP_ERROR_INCOMPATIBLE_SCRIPT_TYPE, "script extends " + script_base
					+ ", which is incompatible with node " + node_path + " of type " + node_class
					+ " — attach it to a " + script_base + " node, or change the script's extends")
		else:
			_fail(OP_ERROR_SCRIPT_COMPILE_FAILED, "script does not compile, so it cannot be attached: "
					+ script_path + " — fix it, or check it with `gda script validate`")
		return

	# Capture the attached class_name off the live node before re-saving frees it.
	var class_name_value: Variant = CLASS_INDEX._script_class_of(node)
	if not _scene_store._repack_and_save(root, path):
		return  # _repack_and_save already recorded the failure (and freed root)

	_succeed({
		"scene_path": path,
		"node": node_path,
		"script": script_path,
		"class_name": class_name_value,
		"replaced_script": replaced_script,
	})


# script-validate: syntax/compile-check a BATCH of .gd scripts (issue #118, #663).
# For each script: read the file text, set it on a fresh GDScript at the script's
# REAL res:// path, and reload() it — err == OK means it compiles. Validating an
# INVALID script is a SUCCESSFUL operation — the op exits 0 with the script's
# valid=false; the op only FAILS (non-zero) for op errors (non-.gd path →
# invalid_path, missing/unreadable file → path_not_found).
#
# ONE call validates N scripts (#663), because a change usually touches four to
# six related scripts and one script per invocation cost one engine launch each.
# The result carries one entry per script plus the aggregate `valid` — false as
# soon as any entry is invalid. Two selectors, exactly one of them given (the CLI
# enforces that on both its input paths): `paths` names the batch, while
# `all_scripts` validates every .gd in the project, enumerated the way script-list
# enumerates them — and so, like script-list, it needs a real res:// tree and
# refuses projectless with project_not_found rather than reporting a vacuously
# valid empty batch.
#
# ADDRESSING IS CHECKED FIRST, for the whole batch, before anything is compiled:
# an unaddressable path refuses the call rather than becoming a verdict (a missing
# file is not an invalid script), and checking up front makes that refusal
# independent of where the bad path sits in the batch.
#
# Unlike the other script-file ops, validate DOES compile each script (reload
# parses and compiles it), but it never INSTANTIATES it, so it does not run the
# script's instance code. The line/message of a compile error are not available
# from any bound API (is_valid() is not even callable from GDScript) — only from
# the engine's stderr — so the op emits just {path, valid, error_string} per script
# and gda parses the advisory line/message diagnostics from stderr. With several
# scripts compiled into ONE stream, gda needs to know where each script's errors
# begin: the `validating: <path>` diagnostic below is that delimiter, so the marker
# and gda's parser are two halves of one contract (a test pins the spelling on both
# sides).
#
# The compile context must match how the engine actually loads the file (issue
# #131). Compiling an ANONYMOUS in-memory GDScript gives it a synthetic
# `gdscript://` resource path, so a relative `preload("sibling.gd")` resolves
# against that synthetic base and fails — a false negative for a script that loads
# fine in-engine. take_over_path claims the script's real res:// path on the fresh
# GDScript BEFORE reload(), so relative preloads and other path-dependent
# resolution resolve against the script's own res:// location exactly as in-engine.
# take_over_path (not `resource_path =`) is used deliberately: in the rare case the
# path is already in the resource cache (an autoload pulled it in at startup), it
# cleanly claims the cache slot, whereas assigning resource_path logs a spurious
# "Another resource is loaded ... cyclic resource inclusion" error. Either way the
# claim is harmless in this one-shot headless process: validate is a leaf op that
# loads nothing at that path afterward, so the swapped cache entry cannot leak.
# reload() stays the verdict, so the stderr still carries the GDScript::reload
# frame the diagnostics parser pairs (the frame now names the real res:// path).
func _op_script_validate(params: Dictionary) -> void:
	_diag("running operation: script-validate")
	var paths: Variant = _validate_target_paths(params)
	if paths == null:
		return  # _validate_target_paths already recorded the failure

	# The whole batch's addressing boundary, checked before any compile.
	for path in paths:
		if not _require_existing_script(path):
			return  # _require_existing_script already recorded the failure

	var scripts: Array = []
	var aggregate := true
	for path in paths:
		# The per-script delimiter gda splits the engine's stderr on, so each
		# script's advisory diagnostics are attributed to it and not to the batch.
		_diag(VALIDATE_MARKER + path)
		var source: Variant = _read_script_source(path)
		if source == null:
			return  # _read_script_source already recorded the failure

		# Compile-check without instantiating: set the source on a fresh GDScript at
		# the script's real res:// path and reload() it. The reload error (and its
		# diagnostics on stderr) is the verdict; the real path makes relative
		# preloads resolve as in-engine (issue #131).
		var script := GDScript.new()
		script.source_code = source
		script.take_over_path(path)
		var err := script.reload()
		if err != OK:
			aggregate = false
		scripts.append({
			"path": path,
			"valid": err == OK,
			"error_string": null if err == OK else error_string(err),
		})

	# The stale-entry predicate over every index entry whose script this process
	# has loaded — the compiles' dependencies and the autoloads (#1073). A stale
	# entry makes the aggregate invalid while each script's own verdict keeps its
	# meaning (it compiles): the next import pass rewrites the index and the
	# project then fails to compile.
	var stale := CLASS_INDEX._stale_loaded_entries()
	_succeed({
		"valid": aggregate and stale.is_empty(),
		"scripts": scripts,
		"stale_class_entries": stale,
	})


# The script paths one script-validate call must compile: the requested batch, or
# every .gd in the project under `all_scripts` (#663). Returns null after recording
# the failure (the caller must stop), so the two selectors' error handling stays
# out of the operation body.
#
# EXACTLY ONE selector, enforced here as well as at the CLI. gda's own CLI refuses
# a contradictory selection before it ever reaches the engine, so this arm is not
# reachable through `gda script validate` — but the op is a contract in its own
# right (ADR-0002), and a contract that documents "both is a contradiction, not a
# precedence question" must not quietly pick a winner when both arrive. Silently
# discarding a caller's explicit `paths` because `all_scripts` was also set would
# report a verdict for a set they did not ask for.
#
# The refusals split by WHAT is wrong, so the codes mean the same thing on both
# sides of the wire: a params SHAPE problem — a non-array `paths`, a non-string
# entry, both selectors, or neither — is invalid_params, the same code the Python
# model reports for the identical selections; a path VALUE problem (an empty
# string, which is a well-typed path naming nothing) is invalid_path, like every
# other unusable path in this file.
func _validate_target_paths(params: Dictionary) -> Variant:
	var requested: Variant = params.get("paths", [])
	if not (requested is Array):
		_fail(OP_ERROR_INVALID_PARAMS, "paths must be a JSON array of .gd script paths")
		return null
	# Type-check the raw Variant before coercing it. `bool(value)` is not total in
	# GDScript: a null, a String or an Array makes it raise, which aborts
	# _initialize BEFORE any sentinel is printed — so a malformed payload came back
	# as the generic operation_failed instead of ADR-0002's structured
	# invalid_params. Same reason the `paths` shape is checked above, and the same
	# hazard issue #31 named for a typed assignment on arbitrary JSON.
	var raw_all: Variant = params.get("all_scripts", false)
	if not (raw_all is bool):
		_fail(OP_ERROR_INVALID_PARAMS, "all_scripts must be a boolean: " + str(raw_all))
		return null
	var all_scripts: bool = raw_all
	if all_scripts and not (requested as Array).is_empty():
		_fail(OP_ERROR_INVALID_PARAMS, "paths and all_scripts are mutually exclusive: all_scripts already covers every script in the project")
		return null
	if all_scripts:
		if not _has_project():
			_fail(OP_ERROR_PROJECT_NOT_FOUND, "script validate --all requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
			return null
		var found: Array[String] = []
		_collect_script_paths("res://", found)
		# Sorted so a project-wide run reports a stable order across invocations,
		# exactly as script-list does — the enumeration order of a directory is not.
		found.sort()
		return found

	var paths: Array[String] = []
	for entry in requested:
		if not (entry is String):
			_fail(OP_ERROR_INVALID_PARAMS, "each entry of paths must be a string: " + str(entry))
			return null
		if String(entry).is_empty():
			_fail(OP_ERROR_INVALID_PATH, "script path must not be empty")
			return null
		paths.append(entry)
	if paths.is_empty():
		_fail(OP_ERROR_INVALID_PARAMS, "give at least one path, or set all_scripts")
		return null
	return paths


# Clear the script group's addressing boundary for an EXISTING script: the path
# must be a .gd (invalid_path otherwise) and the file must exist on disk
# (path_not_found otherwise). Returns true to proceed, or false after recording
# the failure (the caller must stop). Shared by every op that reads or mutates an
# existing script — get / delete / set / validate / attach — so they all refuse a
# non-.gd target and a missing file identically, rather than operating on it.
func _require_existing_script(path: String) -> bool:
	if not GDSCRIPT_SCAN._is_script_path(path):
		_fail(OP_ERROR_INVALID_PATH, "script path must end in .gd: " + path)
		return false
	if not FileAccess.file_exists(path):
		_fail(OP_ERROR_PATH_NOT_FOUND, "script file does not exist: " + path)
		return false
	return true


# Read a .gd script's source back as RAW TEXT, disambiguating an empty file from
# an unreadable one. get_file_as_string returns "" both for an empty file AND on
# an open error; an empty .gd is legal source, so "" alone cannot be trusted as
# the content. When the read returns "" but the open errored, the file is
# unreadable, not empty — report path_not_found and return null (the caller must
# stop). Otherwise return the source as-is ("" for a genuinely empty file).
# Shared by script get / set / validate, which each only need the raw source.
func _read_script_source(path: String) -> Variant:
	var source := FileAccess.get_file_as_string(path)
	if source.is_empty():
		var open_err := FileAccess.get_open_error()
		if open_err != OK:
			_fail(OP_ERROR_PATH_NOT_FOUND, "script file could not be read: " + path
					+ ": " + error_string(open_err))
			return null
	return source


# Recursively collect every .gd script under res:// (issue #117) over the shared
# traversal, which enumerates hidden entries (a .hidden.gd, or a script under a
# dot-prefixed directory) and asks _should_descend about every directory. Paths
# are returned as res:// paths so they round-trip into other script commands. The
# acceptance test is _is_script_path — the same predicate the script group's
# addressing boundary uses, case-insensitive as the engine is.
func _collect_script_paths(dir_path: String, out: Array[String]) -> void:
	PROJECT_WALK._collect_paths(dir_path, GDSCRIPT_SCAN._is_script_path, out)


# Summarize one .gd for the listing: its path plus the class_name/extends parsed
# from its raw source (no compilation, issue #30 — reading a script must never
# run it). A script whose source declares neither (or could not be read) still
# appears, with null metadata, rather than being dropped.
func _script_summary(path: String) -> Dictionary:
	var meta := GDSCRIPT_SCAN._script_metadata(FileAccess.get_file_as_string(path))
	return {
		"path": path,
		"class_name": meta["class_name"],
		"extends": meta["extends"],
	}


# The resource_path of the script CURRENTLY bound to the node — the script that an
# attach is about to DISPLACE (issue #132). Reported verbatim, so a built-in /
# embedded script keeps its sub-resource ref (res://scene.tscn::GDScript_xxx) and
# a displacement always yields a non-null signal. null when the node carries no
# prior script (get_script() == null). The "had a script but resource_path is
# empty" edge (does not occur for .tscn-embedded scripts, which carry an id) is
# accepted as reported-null. Captured BEFORE set_script overwrites the binding.
func _displaced_script_path(node: Node) -> Variant:
	var script := node.get_script() as Script
	if script == null:
		return null
	var resource_path := script.resource_path
	if resource_path.is_empty():
		return null
	return resource_path


# Write `source` to a .gd file as RAW TEXT, reporting both failure modes as
# save_failed. Returns true on a clean write, or false after recording the
# failure (the caller must stop). A successful open does not guarantee a
# successful write: a disk-full/I/O error surfaces at get_error(), not at open,
# so capture it BEFORE close() invalidates the handle — a failed write is
# save_failed, never a phantom success over a partial or empty file. Shared by
# script create and script set, the two ops that write script text. The write
# itself goes through _atomic_write_text so a torn/failed write never tears the
# original .gd (issue #226): a non-OK return leaves the target untouched, and we
# translate it into the same save_failed ladder this op has always reported.
func _write_script_file(path: String, source: String) -> bool:
	var write_err := _file_write._atomic_write_text(path, source)
	if write_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _file_write._save_failure_message("script", path, write_err))
		return false
	return true
