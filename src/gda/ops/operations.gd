#!/usr/bin/env -S godot --headless --script
extends SceneTree

# gda headless operations payload (ADR-0001, ADR-0002).
#
# Invoked as: godot --headless --script operations.gd <operation> [params_json]
#
# Each operation emits EXACTLY ONE result to stdout, wrapped in the GDA
# sentinels, and routes all of its own diagnostics to stderr. stdout carries
# nothing but the sentinel-delimited result; everything else is engine noise.
#
# An operation that fails reports it structurally through the same stdout
# sentinels as success, using a minimal error envelope. gda's shared classifier
# surfaces the registered code as the stable GdaError.code (ADR-0002).
#
# Control flow (issue #31): all work happens in _initialize, but the process is
# quit from _process — which runs on the first idle frame regardless of whether
# _initialize completed. So even an uncaught runtime error mid-operation, which
# aborts _initialize, still exits promptly and non-zero (the default _exit_code)
# instead of leaving the headless main loop spinning forever. An operation never
# calls quit() itself: it records its outcome via _succeed / _fail, and the
# single quit() lives in _process — no path can quit twice or clobber the code.

const RESULT_BEGIN := "<<<GDA:RESULT>>>"
const RESULT_END := "<<<GDA:END>>>"
# Preflight readiness as INDEPENDENT evidence, not part of the result sentinel
# (#709 review): printed the moment the scene reports ready, so the fact that it
# came up survives a project that ends the run (get_tree().quit() in _ready)
# before the pending tick can emit the result. Mirrored in gda.commands.scene,
# which reads it only off a clean exit that carried no result.
const PREFLIGHT_READY_EVIDENCE := "<<<GDA:PREFLIGHT-READY>>>"

const OP_ERROR_USAGE := "usage_error"
const OP_ERROR_UNKNOWN_OPERATION := "unknown_operation"
const OP_ERROR_INVALID_PARAMS := "invalid_params"
const OP_ERROR_INVALID_PATH := "invalid_path"
const OP_ERROR_INVALID_ROOT_TYPE := "invalid_root_type"
const OP_ERROR_INVALID_ROOT_NAME := "invalid_root_name"
const OP_ERROR_ALREADY_EXISTS := "already_exists"
const OP_ERROR_SAVE_FAILED := "save_failed"
const OP_ERROR_DELETE_FAILED := "delete_failed"
const OP_ERROR_FILE_CHANGED_EXTERNALLY := "file_changed_externally"
const OP_ERROR_PROJECT_NOT_FOUND := "project_not_found"
const OP_ERROR_PATH_NOT_FOUND := "path_not_found"
const OP_ERROR_NOT_A_SCENE := "not_a_scene"
const OP_ERROR_PARENT_NOT_FOUND := "parent_not_found"
const OP_ERROR_INVALID_NODE_TYPE := "invalid_node_type"
const OP_ERROR_INVALID_NODE_NAME := "invalid_node_name"
const OP_ERROR_DUPLICATE_NODE_NAME := "duplicate_node_name"
const OP_ERROR_INVALID_CHILD_INDEX := "invalid_child_index"
const OP_ERROR_MISSING_DEPENDENCY := "missing_dependency"
const OP_ERROR_UNINSTANTIABLE_SCRIPT := "uninstantiable_script"
const OP_ERROR_AMBIGUOUS_CLASS_NAME := "ambiguous_class_name"
const OP_ERROR_NODE_NOT_FOUND := "node_not_found"
const OP_ERROR_CANNOT_TARGET_ROOT := "cannot_target_root"
const OP_ERROR_CYCLIC_TARGET := "cyclic_target"
const OP_ERROR_UNKNOWN_PROPERTY := "unknown_property"
const OP_ERROR_UNCOERCIBLE_VALUE := "uncoercible_value"
# Object-typed property assignment via a res:// resource reference (ADR-0033, #363).
const OP_ERROR_EXPECTED_RESOURCE_PATH := "expected_resource_path"
const OP_ERROR_NOT_A_RESOURCE := "not_a_resource"
const OP_ERROR_RESOURCE_TYPE_MISMATCH := "resource_type_mismatch"
const OP_ERROR_USE_SCRIPT_ATTACH := "use_script_attach"
const OP_ERROR_UNSUPPORTED_PROPERTY_TYPE := "unsupported_property_type"
const OP_ERROR_NO_SEARCH_MATCH := "no_search_match"
const OP_ERROR_INVALID_LINE_RANGE := "invalid_line_range"
const OP_ERROR_SCRIPT_COMPILE_FAILED := "script_compile_failed"
const OP_ERROR_INCOMPATIBLE_SCRIPT_TYPE := "incompatible_script_type"
const OP_ERROR_SIGNAL_NOT_FOUND := "signal_not_found"
const OP_ERROR_ALREADY_CONNECTED := "already_connected"
const OP_ERROR_CONNECTION_NOT_FOUND := "connection_not_found"
const OP_ERROR_INVALID_RESOURCE_TYPE := "invalid_resource_type"
const OP_ERROR_EXPORT_PRESETS_NOT_FOUND := "export_presets_not_found"
const OP_ERROR_EXPORT_PRESET_NOT_FOUND := "export_preset_not_found"
const OP_ERROR_INVALID_UID := "invalid_uid"
const OP_ERROR_UNKNOWN_UID := "unknown_uid"
const OP_ERROR_NO_UID_ASSIGNED := "no_uid_assigned"
const OP_ERROR_UNKNOWN_SETTING := "unknown_setting"
const OP_ERROR_INVALID_TARGET := "invalid_target"
const OP_ERROR_INVALID_KEY := "invalid_key"

const NODE_NAME_INVALID_CHARS := [".", ":", "@", "/", "\"", "%"]

# The prefix every gda diagnostic line carries on stderr (see _diag), so a reader
# can tell gda's own lines from the engine's. A const rather than an inline
# literal because one diagnostic — VALIDATE_MARKER below — is PARSED by gda, not
# merely displayed, which makes this prefix half of a cross-language contract.
const DIAG_PREFIX := "gda: "

# The per-script delimiter script-validate writes before each compile (#663), so
# gda can attribute a batch's advisory stderr diagnostics to individual files.
# The full line is DIAG_PREFIX + this + the script path, and that composition is
# mirrored Python-side by gda.commands.script.VALIDATE_MARKER_PREFIX. A test pins
# these two VALUES against that constant, so the contract survives any change to
# how or where the line is written.
const VALIDATE_MARKER := "validating: "

# The problem kinds scene-validate reports, one per unresolvable dependency of a
# scene (#664). Values, not free prose: gda projects them into a closed enum on
# the published result, so an agent branches on the kind instead of matching a
# message. SCENE_PROBLEM_SCRIPT_COMPILE_FAILED deliberately spells the same string
# as the script_compile_failed error code — it is the same condition, reported as
# a verdict here rather than as a refusal.
const SCENE_PROBLEM_MISSING_RESOURCE := "missing_resource"
const SCENE_PROBLEM_UNLOADABLE_RESOURCE := "unloadable_resource"
const SCENE_PROBLEM_SCRIPT_COMPILE_FAILED := "script_compile_failed"
# Deliberately the same word OP_ERROR_INCOMPATIBLE_SCRIPT_TYPE's remedy speaks:
# the script compiles but its native base cannot bind the node that carries it.
const SCENE_PROBLEM_INCOMPATIBLE_SCRIPT := "incompatible_script"
# The three problems the SUB-SCENE walk can raise that a single file never does
# (#721). The first is a real defect: a scene references one that already
# references it, and Godot refuses the closing reference. The other two are LIMITS
# gda declares about ITSELF — the walk stopped or could not read the target, so
# what lies below is unchecked rather than sound. Both are reported for the same
# reason the depth one was: a gate must not answer "sound" about a subtree it never
# opened (GDA-DF-030).
const SCENE_PROBLEM_CYCLIC_INSTANCE := "cyclic_instance"
const SCENE_PROBLEM_INSTANCE_DEPTH_EXCEEDED := "instance_depth_exceeded"
# A referenced scene in the BINARY .scn form (#721 review). It loads perfectly
# well; what it does not carry is the [gd_scene] TEXT the walk reads its
# dependency set out of — the same reason the top-level op refuses a .scn
# outright. Measured on Godot 4.6.3: a .tscn parent instancing a .scn child whose
# script has a syntax error, or whose script cannot bind its node, answered
# `valid: true, problems: []` while the engine's own load of that parent reported
# the child's break. Silence there reproduces exactly the defect this command
# exists to prevent.
const SCENE_PROBLEM_UNREADABLE_SUB_SCENE := "unreadable_sub_scene"

# How many levels of referenced sub-scenes below the validated scene the walk
# descends before it stops and says so (#721 review). The bound is on the
# SHORTEST route to each file, not on the first route walked — see `reached_depth` in
# _new_scene_walk for why that distinction is the contract and not an internal.
#
# It bounds GDA'S OWN work, and nothing else. Measured on Godot 4.6.3 against a
# straight chain of N scenes each instancing the next (two runs each, quiet
# machine): the pre-#721 command is FLAT at ~2s for both N=100 and N=300, because
# it does ONE load and the engine walks the chain internally. The unbounded
# composed walk added a per-file pass on top of that load and went 5-7s at N=100
# and 38-47s at N=300 — superlinear, and close enough to the 60s launch ceiling
# that it CROSSES it into launch_timeout when the machine is under load, which is
# how the regression was first seen. Bounded, the same chains take 3-4s and 5-6s.
#
# It does NOT make deep chains safe, and must not be described as if it did: at
# N=1200 the engine's own loader overflows its stack and the run dies with signal
# 11 — on the PRE-#721 code too, where no gda recursion exists. That failure is the
# engine's, it is reached through the single top-level load this bound does not
# touch, and no cap here can prevent it.
#
# 16 is the number _packed_scene_root_type already refuses past, on the very same
# axis (it walks the instancing chain of a scene's root), and the number
# JSONIFY_MAX_DEPTH uses for value recursion. Real compositions nest a handful of
# levels deep; 16 leaves large headroom while keeping the walk's cost bounded.
const SCENE_INSTANCE_MAX_DEPTH := 16

# The startup verdicts scene-preflight reports (#664). The third one an agent can
# read, `timeout`, is gda's own: only the CLI knows the launch outran its bound,
# because an engine stuck inside a scene's `_ready` never reaches the frame loop
# below to report anything at all.
const SCENE_STARTUP_READY := "ready"
const SCENE_STARTUP_NOT_READY := "not_ready"

# The ONE directory a res:// walk excludes: the engine's own import/cache tree at
# the project root. The VALUE only — the decision that uses it lives in exactly one
# place, _should_descend, which every walk calls.
const ENGINE_CACHE_DIR := "res://.godot"

# The project-info settings (issue #111), read with a default so a project that
# never wrote them still reports a sensible value rather than failing: a new
# Godot 4 project has no explicit main_scene and inherits viewport defaults.
const PROJECT_NAME_SETTING := "application/config/name"
const PROJECT_MAIN_SCENE_SETTING := "application/run/main_scene"
const PROJECT_VIEWPORT_WIDTH_SETTING := "display/window/size/viewport_width"
const PROJECT_VIEWPORT_HEIGHT_SETTING := "display/window/size/viewport_height"

# Autoload singletons live under the "autoload/<name>" section of project.godot
# (issue #119). The value is the res:// path optionally prefixed with "*" to mean
# "enabled as a singleton" — the normal, accessible form gda writes.
const AUTOLOAD_SETTING_PREFIX := "autoload/"
const AUTOLOAD_ENABLED_PREFIX := "*"

# InputMap actions live under the "input/<name>" section of project.godot
# (issue #380). The value is a Dictionary of {deadzone, events} where the events
# are real InputEventKey Objects, persisted via ProjectSettings.save() so the
# serialization is exactly the engine's own var_to_str form.
const INPUT_SETTING_PREFIX := "input/"

# The exit code the process will use. Defaults to failure, so an operation that
# aborts before recording an outcome (e.g. an uncaught runtime error) still
# exits non-zero rather than reporting a phantom success.
var _exit_code := 1

# The gda-owned static class_name → declaring-.gd-paths index (ADR-0032), the
# cache-independent fallback tier of the unified resolver. Built lazily once per
# process run (a headless op is one-shot, so this is per-op) and reused across
# the node-add / resource-create / find-references call sites. `_built` guards
# the lazy build so an empty project (no class_name declared) is distinguished
# from an unbuilt index rather than rescanning res:// on every miss.
var _project_class_index: Dictionary = {}
var _project_class_index_built := false

# The multi-frame tail of an operation that cannot answer inside _initialize
# (#664). Every other operation finishes in one call and quits on the first idle
# frame; scene-preflight has to keep the main loop running so the scene it booted
# actually gets frames. `_pending_tick` is called once per idle frame with the
# 1-based frame number and returns true when it has recorded its outcome.
var _pending_tick := Callable()
var _pending_frames := 0
var _pending_frame_limit := 0

# scene-preflight's own state across those frames: the scene it booted, the path
# it reports, and whether the booted root was EVER observed ready. Latched rather
# than sampled at the end, so a scene that frees itself after starting is still
# reported as having started.
var _preflight_instance: Node = null
var _preflight_path := ""
var _preflight_ready := false


func _initialize() -> void:
	# Everything after `--` on the Godot command line — i.e. <operation>
	# [params_json] — arrives here, independent of engine argument ordering.
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		_fail(OP_ERROR_USAGE, "usage: godot --headless --script operations.gd -- <operation> [params_json]")
		return

	var operation: String = args[0]
	var params: Variant = _parse_params(args)
	if params == null:
		return  # _parse_params already recorded the failure

	match operation:
		"info":
			_op_info()
		"scene-create":
			_op_scene_create(params)
		"scene-get":
			_op_scene_get(params)
		"scene-get-exports":
			_op_scene_get_exports(params)
		"scene-list":
			_op_scene_list(params)
		"scene-delete":
			_op_scene_delete(params)
		"scene-validate":
			_op_scene_validate(params)
		"scene-preflight":
			_op_scene_preflight(params)
		"node-add":
			_op_node_add(params)
		"node-list":
			_op_node_list(params)
		"node-get":
			_op_node_get(params)
		"node-set":
			_op_node_set(params)
		"node-remove":
			_op_node_remove(params)
		"node-duplicate":
			_op_node_duplicate(params)
		"node-move":
			_op_node_move(params)
		"node-connect-signal":
			_op_node_connect_signal(params)
		"node-disconnect-signal":
			_op_node_disconnect_signal(params)
		"script-create":
			_op_script_create(params)
		"script-get":
			_op_script_get(params)
		"script-list":
			_op_script_list(params)
		"script-delete":
			_op_script_delete(params)
		"script-set":
			_op_script_set(params)
		"script-attach":
			_op_script_attach(params)
		"script-validate":
			_op_script_validate(params)
		"resource-create":
			_op_resource_create(params)
		"resource-get":
			_op_resource_get(params)
		"resource-set":
			_op_resource_set(params)
		"resource-delete":
			_op_resource_delete(params)
		"export-list":
			_op_export_list(params)
		"export-get":
			_op_export_get(params)
		"resource-uid":
			_op_resource_uid(params)
		"project-info":
			_op_project_info(params)
		"project-get":
			_op_project_get(params)
		"project-list":
			_op_project_list(params)
		"project-set":
			_op_project_set(params)
		"project-add-autoload":
			_op_project_add_autoload(params)
		"project-remove-autoload":
			_op_project_remove_autoload(params)
		"project-add-input-action":
			_op_project_add_input_action(params)
		"project-remove-input-action":
			_op_project_remove_input_action(params)
		"shader-create":
			_op_shader_create(params)
		"shader-get":
			_op_shader_get(params)
		"shader-set":
			_op_shader_set(params)
		"theme-create":
			_op_theme_create(params)
		"project-find-references":
			_op_project_find_references(params)
		"project-dependencies":
			_op_project_dependencies(params)
		"project-find-unused-resources":
			_op_project_find_unused_resources(params)
		"project-statistics":
			_op_project_statistics(params)
		_:
			_fail(OP_ERROR_UNKNOWN_OPERATION, "unknown operation: " + operation)


# Quit on the first idle frame, whatever happened during _initialize — this is
# the single exit point and the watchdog against a hung main loop (issue #31).
#
# An operation that declared a pending tail (_begin_pending, #664) keeps the loop
# running until its tick says it is done. The watchdog survives that: the frame is
# COUNTED and CAPPED before the tick runs, so a tick aborted by an uncaught runtime
# error — which makes this function return its default `false` and be called again
# next frame — still ends the run at the cap instead of erroring forever. The op's
# own budget is the cap, so a tick that never records an outcome quits non-zero
# (the generic operation_failed) rather than spinning.
func _process(_delta: float) -> bool:
	if _pending_tick.is_valid():
		_pending_frames += 1
		if _pending_frames <= _pending_frame_limit and not _pending_tick.call(_pending_frames):
			return false
	quit(_exit_code)
	return true


# Keep the main loop running for up to `frames` idle frames, calling `tick` on
# each with the 1-based frame number until it returns true (#664).
func _begin_pending(tick: Callable, frames: int) -> void:
	_pending_tick = tick
	_pending_frame_limit = frames


# Parse the optional params JSON into a Dictionary; null signals a recorded
# failure (the caller must stop). A missing payload is an empty Dictionary.
func _parse_params(args: PackedStringArray) -> Variant:
	if args.size() <= 1:
		return {}
	var parsed: Variant = JSON.parse_string(args[1])
	if not (parsed is Dictionary):
		_fail(OP_ERROR_INVALID_PARAMS, "params is not a JSON object: " + args[1])
		return null
	return parsed


# info: emit Engine.get_version_info() through the structured-output contract.
func _op_info() -> void:
	_diag("running operation: info")
	_succeed(Engine.get_version_info())


# scene-create: instantiate a root node of the requested type, pack it, save
# it as a .tscn at the requested path (issue #18).
func _op_scene_create(params: Dictionary) -> void:
	_diag("running operation: scene-create")
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	var root_type := _string_param(params, "root_type")
	# class_exists gates can_instantiate: probing a name ClassDB does not know
	# logs a spurious engine ERROR (issue #377); the miss still fails as
	# invalid_root_type through the same else path.
	if root_type.is_empty() or not ClassDB.class_exists(root_type) \
			or not ClassDB.can_instantiate(root_type) \
			or not ClassDB.is_parent_class(root_type, "Node"):
		_fail(OP_ERROR_INVALID_ROOT_TYPE, "not an instantiable Node class: " + root_type)
		return
	var root_name := _string_param(params, "root_name")
	if not _is_valid_node_name(root_name):
		_fail(OP_ERROR_INVALID_ROOT_NAME, "invalid root_name: " + root_name)
		return
	if FileAccess.file_exists(path) or DirAccess.dir_exists_absolute(path):
		_fail(OP_ERROR_ALREADY_EXISTS, "scene target already exists: " + path)
		return

	var root: Node = ClassDB.instantiate(root_type)
	root.name = root_name
	var actual_root_name := String(root.name)
	if actual_root_name != root_name:
		root.free()
		_fail(OP_ERROR_INVALID_ROOT_NAME, "Godot rewrote root_name from " + root_name + " to " + actual_root_name)
		return

	# Create any missing parent dirs BEFORE packing-and-saving. pack() works purely
	# in memory on root and writes nothing, so making the directories first (rather
	# than between pack and save) is behavior-equivalent and lets scene-create reuse
	# the one shared pack-and-save tail (_repack_and_save) the node ops use (#135).
	# _ensure_parent_dirs does not free root on failure, so free it here on that path.
	var created_dirs: Variant = _ensure_parent_dirs(path)
	if created_dirs == null:
		root.free()
		return  # _ensure_parent_dirs already recorded the failure
	if not _repack_and_save(root, path):
		return  # _repack_and_save already recorded the failure (and freed root)

	_succeed({
		"path": path,
		"root_name": actual_root_name,
		"root_type": root_type,
		"created_dirs": created_dirs,
	})


# scene-get: load a .tscn from disk and emit its structured node tree.
#
# Reads the packed scene's STORED STATE (SceneState) rather than instantiating
# it. Instantiating would run the _init of any attached script — executing
# arbitrary project code merely to read a scene, and letting that code print a
# forged result onto stdout (issue #30). SceneState exposes the declared tree
# without constructing a single node.
func _op_scene_get(params: Dictionary) -> void:
	_diag("running operation: scene-get")
	var packed: PackedScene = _load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var path := _string_param(params, "path")

	_succeed({
		"path": path,
		"root": _tree_from_state(packed.get_state(), false, _scene_instance_paths_by_node_path(path)),
	})


# scene-get-exports: load a .tscn, instantiate it, and emit — per node (by node
# path) — the @export properties the node's attached script declares (issue #58).
#
# Unlike scene-get (which reads SceneState without instantiating, issue #30),
# reporting an export's TYPE/HINT and current/default VALUE requires the real
# script and the real node: a script's @export surface is read from
# Script.get_script_property_list(), and the value off the live node — exactly
# the introspection node-get reuses (_type_name, _jsonify). Instantiating runs
# the _init of any attached script (the same trust boundary as node-get,
# ADR-0009), but get-exports does not re-save, so it skips the unmaterialized-
# node guard (that boundary protects a re-save from silently dropping data,
# issue #64 — there is no save here). It reuses _load_scene's failure ladder, so
# a missing file is path_not_found and a non-scene file not_a_scene.
#
# An @export property is a SCRIPT VARIABLE the script exposes to the editor: in
# the property's usage flags both PROPERTY_USAGE_SCRIPT_VARIABLE (declared in
# the script, not inherited from the engine class) and PROPERTY_USAGE_EDITOR
# (exported) are set. Reading the script's own get_script_property_list() — not
# the node's whole get_property_list() — keeps the listing to the script's
# declared surface, so an inherited engine property never leaks in.
func _op_scene_get_exports(params: Dictionary) -> void:
	_diag("running operation: scene-get-exports")
	var packed: PackedScene = _load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var root: Node = packed.instantiate()
	if root == null:
		_fail(OP_ERROR_MISSING_DEPENDENCY, "scene failed to instantiate: "
				+ _string_param(params, "path")
				+ " — an instanced sub-scene is unresolvable or empty; check the scene's dependencies and --project")
		return

	var nodes: Array = []
	_collect_node_exports(root, root, nodes)
	# Capture the path before freeing the tree (reading off a freed node errors).
	var scene_path := _string_param(params, "path")
	root.free()

	_succeed({
		"path": scene_path,
		"nodes": nodes,
	})


# Walk the instantiated subtree rooted at `node`, appending one entry per node
# whose attached script declares at least one @export property (issue #58). A
# node with no script, or a script declaring no exports, is omitted — the
# listing names only nodes that actually export. The node path is the canonical
# root-relative form node get / node set address by ('.' for the root), so an
# agent can read or set any reported export afterwards.
func _collect_node_exports(node: Node, root: Node, out: Array) -> void:
	var exports := _script_exports_of(node)
	if not exports.is_empty():
		var node_path := "." if node == root else String(root.get_path_to(node))
		out.append({
			"path": node_path,
			"name": String(node.name),
			"type": node.get_class(),
			"script": _script_resource_path_of(node),
			"exports": exports,
		})
	for child in node.get_children():
		_collect_node_exports(child, root, out)


# The @export properties a node's attached script declares, in declaration
# order (issue #58). Empty for a scriptless node or a script that exports
# nothing. Each export reuses node get's introspection: _type_name for the
# declared Godot type, _jsonify for the value projection (its default on a
# freshly-instantiated node). hint is the PropertyHint enum value the @export
# annotation produced, hint_string its companion string.
func _script_exports_of(node: Node) -> Array:
	var script := node.get_script() as Script
	if script == null:
		return []
	var exports: Array = []
	for prop in script.get_script_property_list():
		if not _is_export_property(prop):
			continue
		var prop_name := String(prop.get("name", ""))
		exports.append({
			"name": prop_name,
			"type": _type_name(int(prop.get("type", TYPE_NIL))),
			"hint": int(prop.get("hint", 0)),
			"hint_string": String(prop.get("hint_string", "")),
			"value": _jsonify(node.get(prop_name)),
		})
	return exports


# Whether a script property-list entry is an @export: a script-declared variable
# (PROPERTY_USAGE_SCRIPT_VARIABLE) exposed to the editor (PROPERTY_USAGE_EDITOR).
# Both flags together are exactly what the @export annotation sets — the engine's
# category/group separators and non-exported script vars (a plain `var`, which
# carries SCRIPT_VARIABLE but not EDITOR) are excluded.
func _is_export_property(prop: Dictionary) -> bool:
	var usage := int(prop.get("usage", 0))
	return (usage & PROPERTY_USAGE_SCRIPT_VARIABLE) != 0 \
			and (usage & PROPERTY_USAGE_EDITOR) != 0


# The res:// path of the script attached to `node`, naming where its exports
# came from, or null for a scriptless node or a script with no resource path
# (an embedded/built-in script). Mirrors _displaced_script_path's null handling.
func _script_resource_path_of(node: Node) -> Variant:
	var script := node.get_script() as Script
	if script == null:
		return null
	var resource_path := script.resource_path
	if resource_path.is_empty():
		return null
	return resource_path


# scene-list: enumerate the project's .tscn scenes (issue #54). Walks the
# project's res:// tree, reporting each scene's res:// path plus its root
# name/type read from stored state (no instantiation, exactly like scene-get,
# issue #30 — listing must not execute project code). A .tscn that cannot be
# loaded as a scene is still listed, with null root info, so the listing names
# every .tscn it found rather than dropping it.
#
# Enumerating res:// requires a project: a projectless headless process has no
# res:// tree to walk, so scene-list refuses with project_not_found rather than
# returning a misleading empty listing.
func _op_scene_list(_params: Dictionary) -> void:
	_diag("running operation: scene-list")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "scene list requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var paths: Array[String] = []
	_collect_scene_paths("res://", paths)
	paths.sort()

	var scenes: Array = []
	for path in paths:
		scenes.append(_scene_summary(path))

	_succeed({"scenes": scenes})


# scene-delete: remove a scene file and report what was removed (issue #54).
# Reuses the shared load-failure ladder (missing → path_not_found, not loadable
# → not_a_scene): delete only removes a file that loads as a PackedScene, so a
# stray non-scene file is refused rather than silently deleted. The root
# name/type are read from stored state before deletion so the result names the
# content removed, not just the path.
func _op_scene_delete(params: Dictionary) -> void:
	_diag("running operation: scene-delete")
	var packed: PackedScene = _load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var path := _string_param(params, "path")

	var state := packed.get_state()
	var root_name := String(state.get_node_name(0))
	var root_type := String(state.get_node_type(0))

	var err := DirAccess.remove_absolute(path)
	if err != OK:
		_fail(OP_ERROR_DELETE_FAILED, "failed to delete scene " + path + ": " + error_string(err))
		return

	_succeed({
		"path": path,
		"root_name": root_name,
		"root_type": root_type,
	})


# scene-validate: report whether a scene's external dependencies resolve and its
# attached scripts compile (#664, dogfooding GDA-DF-040).
#
# STATIC, like scene-get and for the same reason (issue #30): the scene is loaded
# but never INSTANTIATED, so none of the scene's own node scripts run — no _init, no
# _ready, no frames. (The project's autoloads still start, as they do for every
# --project op; and compiling a script executes its static initializers, which is
# why the compile check below asks the loaded script first.) That is the boundary
# against scene-preflight below, which boots the scene on purpose.
#
# It exists because loading a scene SUCCEEDS whatever is broken inside it: the
# engine substitutes null for an ext_resource it cannot resolve, prints an error to
# stderr, and hands back a perfectly usable PackedScene — so scene-get reports a
# healthy-looking tree for a scene whose script and texture are both gone. This op
# is the verdict scene-get does not give.
#
# An INVALID scene is a SUCCESSFUL operation (valid=false + problems), exactly as
# script-validate reports a script that does not compile. Only the shared
# addressing ladder refuses: a missing file is path_not_found and a file that does
# not load as a scene at all is not_a_scene — the same failures every other scene
# op reports for them, so the group's ladder does not fork here.
#
# The verdict is COMPOSED (#721): the scenes this one instances are validated with
# it, because a parent whose child is broken is broken too — and its own walk can
# never see that, since res://child.tscn resolves and loads whatever is missing
# inside it. Each problem is stamped with the FILE it was found in, so a child's
# missing script is never read as the parent's.
func _op_scene_validate(params: Dictionary) -> void:
	_diag("running operation: scene-validate")
	var raw_path := _string_param(params, "path")
	if raw_path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	# The scene is addressed by its CANONICAL spelling from here on — everything
	# the result echoes (`path`, and every problem's `scene`) is that spelling, not
	# the caller's. It is one identity for the whole walk: a root given as
	# `res://./main.tscn` used to seed a key no child's reference back to
	# `res://main.tscn` could match, so the file was answered for twice under two
	# spellings (#721 review round 3). Answering under a spelling the caller did
	# not type is the smaller surprise, and the one the problem `path` field
	# already chose.
	var path := _canonical_resource_path(raw_path)
	# The addressing boundary this op does NOT share with the rest of the group, and
	# the reason is not tidiness: the dependency set is read from the scene's TEXT,
	# and a binary .scn carries none — so the walk would find nothing and report a
	# vacuously VALID verdict for a scene with definitively broken dependencies. A
	# validation gate that answers "yes" to a file it could not read is the worst
	# failure mode it has, so the target is refused instead (the same shape
	# _require_existing_script gives a non-.gd script).
	if not _is_scene_path(path):
		_fail(OP_ERROR_INVALID_PATH, "scene path must end in .tscn: " + path
				+ " — validate reads the scene's own text to find its dependencies, which a binary .scn does not carry")
		return
	if not FileAccess.file_exists(path):
		_fail(OP_ERROR_PATH_NOT_FOUND, "scene file does not exist: " + path)
		return
	# Scene-identity admission, decided from the file's own text BEFORE any
	# diagnosis (#720 review): a .tscn that is not a scene document at all must be
	# refused as not_a_scene, not diagnosed — a dependency finding inside garbage
	# text would otherwise skip the load below and convert the garbage into a
	# scene VERDICT. The header is the text format's own discriminator, so this
	# admission needs no load. A COMPLETE header, not a prefix: the section name
	# must BE "gd_scene" — `[gd_scene]` or `[gd_scene <attrs>…]` — or a
	# `[gd_scenery]` would pass a bare prefix test (#720 recheck).
	var text := FileAccess.get_file_as_string(path)
	if not _has_scene_header(text):
		_fail(OP_ERROR_NOT_A_SCENE, "not a scene document (no [gd_scene] header): " + path)
		return

	# The dependency scan runs BEFORE the load, and its answer OUTRANKS a load
	# failure. Godot tolerates an unresolvable [ext_resource] referenced from a NODE
	# (it substitutes null and the scene still loads) but hard-fails the whole load
	# when the same reference sits in a [sub_resource] — an AtlasTexture's atlas, a
	# script-backed custom Resource (verified against Godot 4.6.3). Gating on the load
	# would answer `not_a_scene` for exactly the broken dependency this command exists
	# to report, and about a file that IS a scene.
	var own: Variant = _scene_own_problems(path)
	if own == null:
		# Nothing found and nothing loadable is the group's ordinary not-a-scene,
		# reported in its words. The ROOT's contract only: a SUB-scene that does not
		# load is a finding about the composition, never a refusal of the whole call
		# (#721) — the caller asked about THIS file, and it is a scene.
		_fail(OP_ERROR_NOT_A_SCENE, "failed to load as a scene: " + path)
		return
	var problems := _attributed_problems(own as Array, path)
	# The COMPOSED verdict (#721): a scene that references a broken one is broken,
	# and its own walk cannot see it — Godot resolves res://child.tscn perfectly
	# well while everything inside the child is gone. The walk therefore descends
	# into each referenced .tscn and adds its findings, each stamped with the file
	# it was found in. The depth-bound findings are settled only once every route
	# has been walked, so they come last.
	var walk := _new_scene_walk(path, problems)
	_collect_sub_scene_problems(path, walk)
	_flush_pending_depth_problems(walk)

	_succeed({
		"path": path,
		"valid": problems.is_empty(),
		"problems": problems,
	})


# One scene file's OWN verdict — the two-stage check, without any sub-scene: the
# dependency walk, and, only when it found nothing, the binding scan of the loaded
# scene. Returns the problems, or null when the file did not load as a scene at
# all. Shared by the root and by every sub-scene the walk descends into (#721), so
# a composed verdict is the same question asked of each file rather than a second
# implementation.
#
# The load is only ASKED when the scan found nothing: a scene already known broken
# needs no second opinion, and loading it would only add the engine's own cascade
# to stderr. The BINDING scan (#720 review) then answers what the dependency walk
# cannot — the walk proves each referenced file loads, but not that a script can
# bind the node that carries it, and it never sees an EMBEDDED [sub_resource
# type="GDScript"] at all. Both are read off the loaded scene's state, so that
# stage runs only when the load did.
#
# The null return is a fact, not a verdict: what the CALLER does with it differs
# (the root refuses, the walk skips), which is why this reports the condition
# instead of deciding it.
func _scene_own_problems(path: String) -> Variant:
	var problems := _scene_dependency_problems(path)
	if not problems.is_empty():
		return problems
	var packed := ResourceLoader.load(path, "PackedScene") as PackedScene
	if not _is_loaded_scene(packed):
		return null
	return _scene_binding_problems(packed)


# Stamp every problem with the scene file it was found in, and hand the array back
# (#721). ATTRIBUTION is what makes a composed verdict readable: without it a
# missing script inside child.tscn reads as a problem of parent.tscn, and each
# problem's `nodes` — which are relative to the scene that owns them — would be
# resolved against the wrong tree. Present on EVERY problem, the root's included,
# so a reader never has to infer it.
func _attributed_problems(problems: Array, scene_path: String) -> Array:
	for problem in problems:
		(problem as Dictionary)["scene"] = scene_path
	return problems


# The OUTCOME an edge of the scene graph has been settled with, and the rule that
# promotes one into the other (#721 review round 4). An edge — one declaring file,
# one target — carries at most ONE problem, and these say which and whether it
# still stands:
#
# - SCENE_EDGE_DEPTH_PENDING is PROVISIONAL. The edge was declined because its
#   target lay past the depth bound ON THIS ROUTE, and the finding it holds is
#   published only at the end, and only if no route ever reached that target
#   inside the bound (_flush_pending_depth_problems);
# - SCENE_EDGE_REPORTED is TERMINAL. A problem about this edge is already in the
#   result, and nothing later can add a second one or take it back.
#
# PROMOTION: provisional -> terminal is allowed, and WITHDRAWS the pending
# finding; every other transition is refused. That rule is the whole reason an
# edge has an outcome instead of an "already reported" flag. With one flag for
# both states, a deep route's depth deferral SUPPRESSED the cyclic_instance a
# later, shorter route proved on the same edge, and the deferral was then dropped
# because its target had been reached — so a cyclic composition answered
# `valid: true`. Measured on Godot 4.6.3 over `root -> d1 ... d15 -> s -> t` plus
# `root -> t -> s`: valid deep-first, one cyclic_instance direct-first (#721
# review round 4).
#
# Promotion never loses a finding: a cycle target is by definition an ancestor of
# the current descent, and the walk records a file's depth before it descends into
# it, so that target was reached inside the bound — which is exactly the condition
# under which the flush drops a pending finding anyway.
const SCENE_EDGE_DEPTH_PENDING := "depth_pending"
const SCENE_EDGE_REPORTED := "reported"


# The traversal state of ONE composed verdict, in one bag (#721). Five fields that
# only ever move together, so they are passed as one rather than as five
# positionals that a later addition has to thread through every call site.
#
# Each answers exactly ONE question, and the comment says which — and, where it
# has been misread, which question it does NOT answer. Three rounds of review
# found the same defect three times, each time a single record standing for two
# states (seen/answered, answered/expanded, provisional/terminal), so the fields
# are documented as the questions they answer (#721 review round 4):
#
# - `problems` is the caller's own array, appended to in place;
#
# - `answered`: "has this file's OWN verdict been produced?" — validated, or
#   reported as one the walk cannot read. It is what makes a file's own problems
#   appear once however many sites reference it, and what keeps the one expensive
#   step (the load and the script compiles behind _scene_own_problems) to once per
#   file. It says NOTHING about the file's references: a file is answered for
#   before its subtree is walked, and stays answered when a later route walks that
#   subtree again;
#
# - `reached_depth`: "what is the SMALLEST depth at which the walk reached this
#   file INSIDE the bound?" — and, by carrying a key at all, "was this file
#   reached inside the bound?", which is the question every pending depth finding
#   is settled against. A file reached again at a strictly smaller depth is
#   expanded again from there, which is what makes the reachable SET a property of
#   the graph rather than of the order two [ext_resource] lines appear in. A file
#   with nothing below it to reach — missing, unreadable, or not a scene document
#   — is recorded at 0, the minimum, so no shorter route can improve on it. It
#   does NOT answer whether the file's own problems were produced (`answered`
#   does), and it is not a record of the routes taken, only of the best one;
#
# - `chain`: "which files are ancestors of the descent currently under way?" —
#   which is how a cycle is recognized, and whose SIZE is the depth of the edge
#   being examined (the same fact counted, not a second one). It is not a record
#   of what the walk has seen: it shrinks again on the way back up;
#
# - `edges`: "what OUTCOME has this edge — declaring file, then target — been
#   settled with, and what finding is still pending for it?" One record per edge;
#   see SCENE_EDGE_DEPTH_PENDING for the outcomes and the promotion rule between
#   them. Kept on the WALK rather than on one descent because a file can be
#   expanded more than once, and the same edge must not be reported once per
#   expansion.
#
# Every key is a CANONICAL path (_canonical_resource_path) — the root's included,
# which the caller must canonicalize before it seeds this. A root spelled
# `res://./main.tscn` seeded a key its own children's references could never match,
# so the file was answered for twice (#721 review round 3).
func _new_scene_walk(root_path: String, problems: Array) -> Dictionary:
	return {
		"problems": problems,
		"answered": {root_path: true},
		"reached_depth": {root_path: 0},
		"chain": {root_path: true},
		"edges": {},
	}


# Descend into the scenes `scene_path` references, appending each one's own
# problems to the walk (#721). Depth-first in DECLARATION order, so the composed
# list reads parent-then-child, and each entry already carries the file it belongs
# to.
#
# Five decisions, none of them free:
#
# - WHAT is descended into is decided by _is_sub_scene_edge, the one projection
#   that owns "this reference is a sub-scene". Read it for the rule.
#
# - TERMINATION: `answered` holds every file the walk has produced a verdict
#   about, so it stops on its own — it is bounded by the number of DISTINCT scene
#   files reachable from the root, a finite set. A sub-scene is therefore reported
#   ONCE PER FILE, not once per referencing site: a broken child instanced at five
#   places is one broken file, which is the same rule the dependency walk already
#   applies to a path declared twice. Every key is the canonical path
#   (_normalize_ext_resource_path), so an alias spelling is the same file.
#
# - DEPTH is bounded SEPARATELY, because terminating is not the same as finishing
#   in time (#721 review). Stopping was never the problem; COST was. Each level
#   adds a per-file pass on top of the single load the engine already walks the
#   chain for, and measured on a straight N-scene chain that term is superlinear:
#   the pre-#721 command is flat at ~2s for N=100 and N=300 while the unbounded
#   composed walk went 5-7s then 38-47s, near enough the 60s launch ceiling to
#   cross it under load. SCENE_INSTANCE_MAX_DEPTH
#   removes that term, and reaching it is REPORTED (instance_depth_exceeded) rather
#   than silently accepted, so an unchecked subtree never reads as a sound one. Read
#   that constant for what the bound does and does not do — in particular it does
#   not, and cannot, prevent the engine-side stack overflow that kills a 1200-deep
#   chain with or without any of this.
#
# - The bound is on the SHORTEST route, not on the first one walked.
#   `reached_depth` holds the smallest depth each file was reached at, and a file
#   reached again nearer the root is walked again from there — which is what makes
#   the published verdict independent of the order two [ext_resource] lines happen
#   to appear in. The cheap half of the walk (read the text, parse the lines) is
#   what repeats; the expensive half (`_scene_own_problems`: the load and the
#   script compiles) sits behind `answered` and runs once per file whatever the
#   shape of the graph. A file's recorded depth strictly decreases each time, and
#   depth is bounded by SCENE_INSTANCE_MAX_DEPTH, so the repetition is bounded too.
#
# - A CYCLE is reported, not merely survived: `chain` holds the ancestors of the
#   current descent, and a reference back into it becomes a cyclic_instance
#   problem attributed to the file that declares it. `answered` alone would stop
#   the walk silently, which would hide a composition the engine mutilates.
#   Checked BEFORE `answered` — every ancestor is also answered for, so the
#   cheaper test would swallow the diagnostic — and its outcome is TERMINAL, so it
#   also outranks whatever a deeper route left on the same edge
#   (see _report_cycle_edge).
func _collect_sub_scene_problems(scene_path: String, walk: Dictionary) -> void:
	var text := FileAccess.get_file_as_string(scene_path)
	if text.is_empty():
		return
	var out: Array = walk["problems"]
	var answered: Dictionary = walk["answered"]
	var reached_depth: Dictionary = walk["reached_depth"]
	var chain: Dictionary = walk["chain"]
	for entry in _ext_resource_entries_from_text(text, scene_path.get_base_dir()):
		if not _is_sub_scene_edge(entry):
			continue
		var ref_path := String(entry["normalized_path"])
		# Nothing is relaxed on this branch, and nothing needs to be: an ancestor
		# was reached at a smaller depth than the edge that points back at it, so
		# this route could not improve on its recorded depth.
		if chain.has(ref_path):
			_report_cycle_edge(walk, scene_path, text, entry)
			continue
		# `chain` holds the ancestors of this edge's target, so its size IS the
		# target's depth below the validated scene. DEFERRED rather than reported:
		# a shorter route to the same target may still reach it, and whether this
		# deep route or that short one is walked FIRST is nothing but declaration
		# order — see _flush_pending_depth_problems.
		var depth := chain.size()
		if depth > SCENE_INSTANCE_MAX_DEPTH:
			_defer_depth_edge(walk, scene_path, text, entry)
			continue
		# Already reached from here or from nearer the root: nothing this route can
		# add. Only a STRICTLY shorter route falls through, and then only to expand
		# the subtree again — never to repeat the file's own problems.
		if reached_depth.has(ref_path) and int(reached_depth[ref_path]) <= depth:
			continue
		if not answered.has(ref_path):
			answered[ref_path] = true
			# A referenced scene the walk cannot READ. Three cases, told apart
			# because the reader needs different things from them:
			#
			# - the file is not there, or is there but no loader opens it: the
			#   referencing file's own dependency walk has ALREADY named it
			#   (missing_resource / unloadable_resource) with the node that
			#   references it, so a second problem here would be one finding
			#   reported twice;
			# - the file LOADS as a PackedScene, but its bytes are not the
			#   [gd_scene] text the walk reads — a binary .scn, or a PackedScene
			#   saved into a .res resource file. Nothing has been said about it,
			#   and staying silent would let a composed verdict answer "sound"
			#   about a subtree it never opened;
			# - the file loads as something else entirely (a line that declares
			#   type="PackedScene" over a resource that is not one). The engine
			#   ignores that declaration and loads what is actually there, so there
			#   is no sub-scene here and nothing to report.
			#
			# All three are recorded at depth 0: there is nothing below them for a
			# shorter route to reach.
			if not FileAccess.file_exists(ref_path):
				reached_depth[ref_path] = 0
				continue
			if not _has_scene_header(FileAccess.get_file_as_string(ref_path)):
				if ResourceLoader.load(ref_path) is PackedScene:
					out.append(_sub_scene_edge_problem(SCENE_PROBLEM_UNREADABLE_SUB_SCENE, entry,
							scene_path, text,
							"this scene loads, but not as the [gd_scene] text gda reads a "
							+ "dependency set out of — a binary .scn, or a PackedScene saved "
							+ "into a resource file, carries none, which is why the command "
							+ "refuses such a file as its target too. This scene and "
							+ "everything it references are UNCHECKED, not judged sound. "
							+ "Re-save it as .tscn for a composed verdict that covers it"))
				reached_depth[ref_path] = 0
				continue
			var own: Variant = _scene_own_problems(ref_path)
			if own != null:
				out.append_array(_attributed_problems(own as Array, ref_path))
		# Descended into even when it did not load: its text is still readable, and
		# the scenes IT references can be broken for reasons of their own.
		reached_depth[ref_path] = depth
		chain[ref_path] = true
		_collect_sub_scene_problems(ref_path, walk)
		chain.erase(ref_path)


# Whether an [ext_resource] entry is an edge into a SUB-SCENE — the one projection
# that owns that question for the composed walk (#721 review round 3).
#
# A UNION of two triggers, because neither alone covers the scenes Godot writes:
#
# - the resolved PATH names a scene file: a .tscn, which the walk reads, or a
#   .scn, which it cannot and reports (unreadable_sub_scene). Extension is the
#   engine's own test for picking a format handler
#   (ResourceFormatLoader::recognize_path), and it is the only trigger that works
#   for a line whose declared type is wrong or absent;
# - the line DECLARES type="PackedScene". ResourceSaver will write a PackedScene
#   into a plain .res (ResourceFormatSaverBinary accepts "res" for any resource;
#   the text saver refuses, so .tres is not a form a PackedScene can be saved in),
#   and such a child was silently skipped by the extension test alone — a parent
#   instancing a .res scene with a broken script answered `valid: true` while the
#   engine's own load of that parent reported the break (measured on Godot 4.6.3).
#
# The declared type is an extra TRIGGER, never a FILTER. Selecting on it would
# MISS real edges, which is a separate measurement: Godot's text loader starts a
# load for EVERY [ext_resource] line before it parses a single node and passes
# `type` only as a HINT (ResourceLoaderText::load, ResourceFormatLoaderText::
# handles_type accepts every type), so a `.tscn` declared type="Resource" and
# never instanced breaks its referencing scene exactly as an instanced one does.
# Both facts point the same way: widen the trigger, never narrow it.
#
# What is still outside: a PackedScene stored under a non-scene extension AND
# declared as some other type. Nothing gda writes takes that form, and it is
# stated on the public surfaces rather than left implicit. Extending the union to
# "load every reference and ask what it is" is deliberately NOT done — it would
# load every texture and audio file a scene names to answer a question that has
# no known instance.
func _is_sub_scene_edge(entry: Dictionary) -> bool:
	if _is_scene_reference_path(String(entry["normalized_path"])):
		return true
	return String(entry.get("type", "")) == "PackedScene"

# The per-declaring-file map of edge outcomes, created on the first edge that file
# settles (#721 review round 4). A Dictionary is a reference, so the caller writes
# through what it gets back.
func _scene_edge_outcomes(walk: Dictionary, scene_path: String) -> Dictionary:
	var edges: Dictionary = walk["edges"]
	if not edges.has(scene_path):
		edges[scene_path] = {}
	return edges[scene_path]


# Publish the cyclic_instance this edge closes, and settle the edge TERMINALLY
# (#721).
#
# One edge problem per target per declaring file: a scene that references the same
# ancestor under two ids still closes ONE cycle, so a second call about the same
# edge publishes nothing. What it does do is PROMOTE — a provisional depth record
# left on this edge by a deeper route is replaced and its pending finding
# withdrawn. A cycle is a fact about the graph; a depth deferral is a statement
# about one route, so the cycle stands whichever order the two are met in, and the
# edge still carries exactly one problem. Read SCENE_EDGE_DEPTH_PENDING for the
# order-dependent false-clean verdict that came of not making that distinction.
func _report_cycle_edge(walk: Dictionary, scene_path: String, scene_text: String,
		entry: Dictionary) -> void:
	var outcomes := _scene_edge_outcomes(walk, scene_path)
	var ref_path := String(entry["normalized_path"])
	var record: Dictionary = outcomes.get(ref_path, {})
	if String(record.get("outcome", "")) == SCENE_EDGE_REPORTED:
		return
	outcomes[ref_path] = {"outcome": SCENE_EDGE_REPORTED}
	(walk["problems"] as Array).append(
			_sub_scene_edge_problem(SCENE_PROBLEM_CYCLIC_INSTANCE, entry, scene_path, scene_text,
			"the scene at this path is an ancestor in this scene's reference chain, "
			+ "so referencing it here closes a cycle. Measured on Godot 4.6.3, the "
			+ "engine refuses the closing reference ([ext_resource] referenced "
			+ "non-existent resource), drops it, and the nodes it would have "
			+ "contributed vanish from the composition it loads. gda stopped the "
			+ "walk at this edge; break the cycle to get a verdict for what lies "
			+ "beyond it"))


# Hold this edge's depth finding PROVISIONALLY: the target lies past the bound on
# the route currently being walked, and a shorter route may still reach it (#721
# review).
#
# Recorded only on an edge nothing has settled yet — neither a pending finding of
# its own (one unchecked subtree, not one per route that declines it) nor a
# published problem, which already says what became of this edge. The finding
# itself is published, or dropped, by _flush_pending_depth_problems once every
# route has been walked.
func _defer_depth_edge(walk: Dictionary, scene_path: String, scene_text: String,
		entry: Dictionary) -> void:
	var outcomes := _scene_edge_outcomes(walk, scene_path)
	var ref_path := String(entry["normalized_path"])
	if outcomes.has(ref_path):
		return
	outcomes[ref_path] = {
		"outcome": SCENE_EDGE_DEPTH_PENDING,
		"problem": _sub_scene_edge_problem(SCENE_PROBLEM_INSTANCE_DEPTH_EXCEEDED, entry,
				scene_path, scene_text,
				"gda validates " + str(SCENE_INSTANCE_MAX_DEPTH) + " levels of "
				+ "sub-scenes below the scene it was given, and no route to this one is "
				+ "inside that bound — this scene and everything it references are "
				+ "UNCHECKED, not judged sound. The bound is on gda's own walk: the "
				+ "engine still loads the whole chain itself, and at extreme depth its "
				+ "loader overflows and the run dies with no verdict at all, which this "
				+ "bound does not change. Validate this scene directly to get a verdict "
				+ "for it"),
	}


# Publish the depth findings the finished walk still stands behind (#721 review).
#
# A depth finding is a statement about a TARGET — "no verdict was established for
# this scene" — but the walk can only see one ROUTE at a time. In a diamond where a
# leaf sits both past the bound and one edge below the root, whichever route is
# declared first decided the verdict: deep-first reported the bound and then
# validated the leaf anyway (valid: false, with a stale finding), while
# direct-first validated the leaf and let the visited record swallow the deep edge
# in silence (valid: true). One graph, two published verdicts, chosen by the order
# two lines happen to appear in — which is not a contract.
#
# Deferring settles it in BOTH directions with the walk's own record: a pending
# finding survives only when nothing ever reached its target inside the bound.
# Order cannot change that, because it is read after every route has been walked.
# The other two halves of the same guarantee are `reached_depth` in
# _collect_sub_scene_problems, which is what makes a shorter route to an ANCESTOR
# of the deep target reach the target at all, and the promotion rule in
# _report_cycle_edge, which turns a pending record into the cycle a later route
# proves rather than letting it suppress one.
func _flush_pending_depth_problems(walk: Dictionary) -> void:
	var reached_depth: Dictionary = walk["reached_depth"]
	var out: Array = walk["problems"]
	for scene_path in walk["edges"]:
		var outcomes: Dictionary = walk["edges"][scene_path]
		for ref_path in outcomes:
			var record: Dictionary = outcomes[ref_path]
			if String(record["outcome"]) != SCENE_EDGE_DEPTH_PENDING:
				continue
			if reached_depth.has(ref_path):
				continue
			out.append(record["problem"])


# One problem about an EDGE of the scene graph rather than about a file's
# contents (#721 review): the walk reached this reference and did not follow it.
# All three such kinds carry the same three facts — the target the edge points at,
# the file that declares it, and the nodes that reference it — so they are built in
# one place instead of three times.
#
# The nodes come from a per-TARGET map, not from this entry's id: one file can
# declare the same target under several [ext_resource] ids, and reading only the
# id that happened to settle the edge dropped the sites the others reference
# (#721 review round 3). It is the per-file merge _scene_dependency_problems
# already does for an ordinary dependency, applied to the edge kinds too.
#
# The map is built HERE, from the declaring file's text, rather than once per
# descent: an edge problem is the rare case, and the walk now expands a file again
# whenever a shorter route reaches it, so a map built eagerly would be rebuilt for
# every expansion of every file to serve the few that report one.
func _sub_scene_edge_problem(kind: String, entry: Dictionary, scene_path: String,
		scene_text: String, message: String) -> Dictionary:
	var ref_path := String(entry["normalized_path"])
	var problem := _scene_problem(kind, ref_path, String(entry.get("type", "")), message)
	var nodes_by_path := _scene_ext_resource_nodes_by_path(scene_text, scene_path.get_base_dir())
	problem["nodes"] = (nodes_by_path.get(ref_path, []) as Array).duplicate()
	problem["scene"] = scene_path
	return problem


# Every node that references each [ext_resource] TARGET of one scene's text,
# merged across the ids that name it (#721 review round 3).
#
# _scene_ext_resource_nodes_by_id answers per id, which is the wrong grain for a
# report keyed by the file the reference points AT: two ids for one path — an
# alias spelling, or simply a hand-written duplicate — are one target with two
# sets of referencing nodes. In declaration order, deduplicated, which is the
# order and the rule _scene_dependency_problems merges by.
func _scene_ext_resource_nodes_by_path(text: String, base_dir: String) -> Dictionary:
	var nodes_by_id := _scene_ext_resource_nodes_by_id(text)
	var by_path := {}
	for entry in _ext_resource_entries_from_text(text, base_dir):
		var ref_path := String(entry["normalized_path"])
		if not by_path.has(ref_path):
			by_path[ref_path] = []
		var nodes: Array = by_path[ref_path]
		for node_path in nodes_by_id.get(String(entry["id"]), []):
			if not nodes.has(node_path):
				nodes.append(node_path)
	return by_path


# Whether the text OPENS with a complete, CLOSED `[gd_scene …]` section header
# (#720 recheck ×2). Two requirements, each defeating a real bypass:
#
# - the section NAME must be exactly "gd_scene" — after the tag comes the
#   closing bracket or the whitespace before attributes, or "[gd_scenery]"
#   would pass a bare prefix test;
# - the header LINE must close with "]" — an unclosed "[gd_scene load_steps=2"
#   is not a header, and the load cannot be relied on to catch it: when the
#   dependency walk finds problems the load is deliberately skipped, so
#   admission must be decided here, completely.
#
# Leading whitespace and a UTF-8 BOM are tolerated. The question is identity,
# not well-formedness — a closed header over a broken body is still admitted,
# and the load has the final word only on that admitted case.
func _has_scene_header(text: String) -> bool:
	var stripped := text.lstrip(" \t\r\n" + String.chr(0xFEFF))
	const TAG := "[gd_scene"
	if not stripped.begins_with(TAG):
		return false
	var line_end := stripped.find("\n")
	var line := stripped if line_end == -1 else stripped.substr(0, line_end)
	line = line.strip_edges()
	# The shortest admitted header is "[gd_scene]", so a line that closes always
	# has a character after the tag.
	if not line.ends_with("]") or line.length() <= TAG.length():
		return false
	var next := line[TAG.length()]
	return next == "]" or next == " " or next == "\t"


# Whether a load produced a scene with a root — the two conditions _load_scene
# refuses separately, asked as one question by the validate path, which only needs
# to know whether the file is a scene at all.
func _is_loaded_scene(packed: PackedScene) -> bool:
	if packed == null:
		return false
	var state := packed.get_state()
	return state != null and state.get_node_count() > 0


# One entry per SCRIPT the loaded scene binds that cannot actually serve its node
# (#720 review). The dependency walk above proves each referenced FILE loads; this
# walk asks the questions only the loaded state can answer:
#
# - an EMBEDDED [sub_resource type="GDScript"] never appears as an [ext_resource],
#   so a syntax error inside one is invisible to the text walk — here it shows up
#   as a script that cannot instantiate, named by its ::id sub-resource path;
# - a script that compiles can still be REFUSED by the engine at bind time when
#   the node's native class is outside the script's base (an `extends Resource`
#   script on a Node2D boots silently script-less). The compatibility rule is the
#   one _op_script_attach enforces at attach time, asked statically: the node's
#   type must be the script's base or inherit from it;
# - a `script` slot can hold a value that is not a Script at all — an embedded
#   [sub_resource] of another type (#709 review). The engine refuses that at
#   bind time too ("Cannot set object script") and the node boots script-less.
#
# Reported per SCRIPT with the referencing nodes merged, the dependency walk's own
# shape. A node without a type of its own (an instanced/inherited child) is
# skipped honestly: its real class lives in another scene, and guessing it would
# turn this into the false positive it exists to remove.
func _scene_binding_problems(packed: PackedScene) -> Array:
	var state := packed.get_state()
	var problems: Array = []
	var by_script := {}
	for i in state.get_node_count():
		var node_type := String(state.get_node_type(i))
		for j in state.get_node_property_count(i):
			if String(state.get_node_property_name(i, j)) != "script":
				continue
			var value: Variant = state.get_node_property_value(i, j)
			if value == null:
				continue
			var problem: Variant
			if value is Script:
				problem = _script_binding_problem(value as Script, node_type)
			else:
				# A NON-Script value in the script slot — an embedded
				# [sub_resource] that is not a script, or anything the dependency
				# walk could not see. Discarding it silently (#709 review) turned
				# the engine's deterministic bind-time refusal into a clean
				# verdict.
				problem = _non_script_binding_problem(value)
			if problem == null:
				continue
			var key := String((problem as Dictionary)["path"]) + "|" + String((problem as Dictionary)["kind"])
			if not by_script.has(key):
				(problem as Dictionary)["nodes"] = []
				by_script[key] = problems.size()
				problems.append(problem)
			var nodes: Array = (problems[int(by_script[key])] as Dictionary)["nodes"]
			var node_path := String(state.get_node_path(i))
			if not nodes.has(node_path):
				nodes.append(node_path)
	return problems


# One bound script's verdict against one node type: a problem Dictionary (without
# its `nodes`, the caller owns attribution), or null when the binding is sound.
func _script_binding_problem(script: Script, node_type: String) -> Variant:
	if not script.can_instantiate():
		# The scene loaded with the script attached, but the script itself never
		# compiled — the embedded-GDScript case (an external one is caught by the
		# dependency walk before the load is even asked). reload() on a script
		# that never compiled retries the compile and runs no project code.
		var err := script.reload()
		if err == OK and script.can_instantiate():
			return null
		return _scene_problem(SCENE_PROBLEM_SCRIPT_COMPILE_FAILED,
				script.resource_path, "Script",
				"the script does not compile: " + error_string(err))
	var base := script.get_instance_base_type()
	if String(base).is_empty() or node_type.is_empty():
		return null
	if not ClassDB.class_exists(node_type):
		return null
	if node_type == String(base) or ClassDB.is_parent_class(node_type, base):
		return null
	return _scene_problem(SCENE_PROBLEM_INCOMPATIBLE_SCRIPT,
			script.resource_path, "Script",
			"the script extends " + String(base) + ", which cannot bind a node of type "
			+ node_type + " — the engine would refuse the assignment and the node "
			+ "would run script-less. Bind it to a " + String(base)
			+ "-compatible target, or change the script's extends")


# The verdict for a `script` property whose value is not a Script at all (#709
# review): the engine refuses the assignment at instantiate time ("Cannot set
# object script. Parameter should be null or a reference to a valid script.",
# object.cpp set_script) and the node boots script-less — the same consequence as
# an incompatible base, so it is the same problem kind. The path names the bound
# resource where it has one (a res:// file, or the ::id sub-resource form for an
# embedded one); a non-resource value can only name its Variant type.
func _non_script_binding_problem(value: Variant) -> Dictionary:
	var shown := type_string(typeof(value))
	var bound_path := ""
	if value is Resource:
		shown = (value as Resource).get_class()
		bound_path = (value as Resource).resource_path
	return _scene_problem(SCENE_PROBLEM_INCOMPATIBLE_SCRIPT, bound_path, "Script",
			"the node's script property binds a " + shown + ", not a Script — the "
			+ "engine would refuse the assignment (Cannot set object script) and "
			+ "the node would run script-less")


# One entry per DEPENDENCY the scene declares and gda could not resolve, in the
# order the .tscn declares them (#664).
#
# The dependency set is read from the file's [ext_resource] lines as text, not
# from the loaded PackedScene: the engine drops a reference it could not resolve,
# so the loaded object no longer knows the path that was asked for — which is the
# one thing a report has to name. Reading the text is also what attributes each
# dependency to the nodes that use it.
#
# A path declared twice (two ids for one file) is checked ONCE and reported once,
# with the referencing nodes merged: it is one broken file, not two problems.
func _scene_dependency_problems(path: String) -> Array:
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		return []
	var nodes_by_id := _scene_ext_resource_nodes_by_id(text)
	var problems: Array = []
	# ref_path -> the index of its problem, or -1 when the dependency is fine. The
	# -1 rows matter as much as the others: they are what keeps a healthy path
	# declared twice from being re-checked (and re-loaded) on its second id.
	var checked := {}
	for entry in _ext_resource_entries_from_text(text, path.get_base_dir()):
		var ref_path := String(entry["normalized_path"])
		if not checked.has(ref_path):
			var problem: Variant = _scene_dependency_problem(ref_path, String(entry.get("type", "")))
			if problem == null:
				checked[ref_path] = -1
			else:
				(problem as Dictionary)["nodes"] = []
				checked[ref_path] = problems.size()
				problems.append(problem)
		var at: int = int(checked[ref_path])
		if at >= 0:
			var nodes: Array = (problems[at] as Dictionary)["nodes"]
			for node_path in nodes_by_id.get(String(entry["id"]), []):
				if not nodes.has(node_path):
					nodes.append(node_path)
	return problems


# One dependency's verdict: a problem Dictionary, or null when it resolves (#664).
# `declared_type` is the type= the [ext_resource] line names ("Script",
# "Texture2D", …), reported back so a reader can tell WHAT was expected there.
#
# The three kinds answer three different questions, and the split is not cosmetic:
# a missing file needs the file, an unimported asset needs an import, and a broken
# script needs an edit.
func _scene_dependency_problem(ref_path: String, declared_type: String) -> Variant:
	if not ResourceLoader.exists(ref_path):
		# ResourceLoader.exists() is the loadability question, not the file
		# question: an asset that was never imported (a .png with no import
		# artifacts) is present on disk yet has no loader in a non-editor run, and
		# the game would lose it at runtime exactly as this scene does. So the two
		# are told apart rather than both called missing.
		if FileAccess.file_exists(ref_path):
			return _scene_problem(SCENE_PROBLEM_UNLOADABLE_RESOURCE, ref_path, declared_type,
					"the file exists but no ResourceLoader can open it — typically an asset that was never imported")
		return _scene_problem(SCENE_PROBLEM_MISSING_RESOURCE, ref_path, declared_type,
				"the referenced file does not exist")
	if _is_script_path(ref_path):
		# Ask the ALREADY-loaded script first (the scene's own load brought it in, so
		# this costs nothing and runs nothing): a script that compiled can be
		# instantiated, and one that did not reports an empty base type. Only when
		# that first answer is negative is a fresh compile run, which both confirms
		# the verdict and yields the Error the message quotes. Order matters for a
		# reason beyond speed: GDScript.reload() executes a script's STATIC
		# INITIALIZERS, so compiling every healthy script a second time would run
		# project code twice per validate.
		var loaded := ResourceLoader.load(ref_path) as GDScript
		if loaded == null:
			return _scene_problem(SCENE_PROBLEM_UNLOADABLE_RESOURCE, ref_path, declared_type,
					"the script file could not be loaded")
		if loaded.can_instantiate():
			return null
		var err := _script_compile_error(ref_path)
		if err != OK:
			return _scene_problem(SCENE_PROBLEM_SCRIPT_COMPILE_FAILED, ref_path, declared_type,
					"the script does not compile: " + error_string(err)
					+ " — run 'gda script validate " + ref_path + "' for the line and message")
		return null
	var resource := ResourceLoader.load(ref_path)
	if resource == null:
		return _scene_problem(SCENE_PROBLEM_UNLOADABLE_RESOURCE, ref_path, declared_type,
				"the resource could not be loaded")
	if declared_type == "Script" and not (resource is Script):
		# Declared as a script but the file is not one — a plain .tres in an
		# `[ext_resource type="Script"]` line (#709 review). The load alone cannot
		# answer this: the loader returns the Resource it found, and the engine
		# only refuses at bind time ("Cannot set object script"), when the node
		# has already booted script-less.
		return _scene_problem(SCENE_PROBLEM_INCOMPATIBLE_SCRIPT, ref_path, declared_type,
				"the file loads as " + resource.get_class() + ", not a Script — the engine "
				+ "would refuse the assignment (Cannot set object script) and the node "
				+ "would run script-less")
	return null


func _scene_problem(kind: String, ref_path: String, declared_type: String, message: String) -> Dictionary:
	return {
		"kind": kind,
		"path": ref_path,
		"type": null if declared_type.is_empty() else declared_type,
		"message": message,
	}


# Whether a .gd compiles, as an Error — the SAME check script-validate makes, so
# "does not compile" means one thing across the two commands (#664).
#
# Loading a script that does not compile still hands back a GDScript object
# (verified against Godot 4.6.3), so the loaded object cannot produce the ERROR; a
# fresh compile can, which is why the caller falls back to this once the cheap check
# has already said something is wrong. take_over_path is what makes the script's own
# relative preloads resolve as in-engine (issue #131); it displaces the cached copy
# for the rest of this one-shot process, which nothing after this reads.
func _script_compile_error(ref_path: String) -> int:
	var script := GDScript.new()
	script.source_code = FileAccess.get_file_as_string(ref_path)
	script.take_over_path(ref_path)
	return script.reload()


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
func _scene_ext_resource_nodes_by_id(text: String) -> Dictionary:
	var by_id := {}
	var node_path := ""
	for line in text.split("\n"):
		var stripped := line.strip_edges()
		if stripped.begins_with("["):
			node_path = _scene_node_path_from_header(stripped) if stripped.begins_with("[node ") else ""
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
func _ext_resource_ids_in_line(line: String) -> Array:
	var ids: Array = []
	var needle := "ExtResource("
	var at := line.find(needle)
	while at != -1:
		var id := _first_quoted_after(line, at + needle.length())
		if not id.is_empty():
			ids.append(id)
		at = line.find(needle, at + needle.length())
	return ids


# scene-preflight: boot the scene and report how far it got (#664, dogfooding
# GDA-DF-030).
#
# The dynamic twin of scene-validate, and the reason both exist: a scene whose
# dependencies all resolve and whose scripts all compile can still fail the moment
# it runs. This op instantiates the scene, adds it under the tree root — which is
# what runs its _ready — and keeps the loop alive for `frames` idle frames so
# startup work that lands AFTER _ready (a deferred call, a _process, an awaited
# signal) gets to run and to print its errors. The verdict is the engine's own
# readiness; the errors themselves are read off stderr by gda, which owns that
# parser (#651).
#
# It runs the scene's code by construction — every script in it, plus the project's
# autoloads — which stays inside the Trusted project assumption (ADR-0009) and is
# the widest project-code surface of any scene op. That is the point of a preflight,
# and it is why scene-validate stays static.
func _op_scene_preflight(params: Dictionary) -> void:
	_diag("running operation: scene-preflight")
	var frames: Variant = _preflight_frames(params)
	if frames == null:
		return  # _preflight_frames already recorded the failure
	var packed: PackedScene = _load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var path := _string_param(params, "path")

	var instance: Node = packed.instantiate()
	if instance == null:
		# The same refusal scene-get-exports reports for the same condition, in the
		# same words: a scene that cannot be built at all is an addressing/dependency
		# failure, not a startup verdict, and the group already has a code for it.
		_fail(OP_ERROR_MISSING_DEPENDENCY, "scene failed to instantiate: " + path
				+ " — an instanced sub-scene is unresolvable or empty; check the scene's dependencies and --project")
		return

	_preflight_path = path
	_preflight_instance = instance
	# add_child does NOT run _ready here. An op runs inside MainLoop::initialize,
	# which SceneTree calls BEFORE it puts its own root into the tree, so the scene
	# is not in a tree yet and nothing propagates readiness (verified against Godot
	# 4.6.3: is_node_ready() is false on the next line). Propagation happens as the
	# tree finishes initializing — after this function returns, and still before the
	# first idle frame.
	root.add_child(instance)
	# So the verdict is LATCHED from the signal rather than sampled later. Sampling
	# it on the first frame was wrong for a scene that hands off in its own _ready
	# (a splash or bootstrap scene calling queue_free): by then the node is gone,
	# the poll below cannot read it, and a scene that plainly started was reported
	# as not_ready. The connection is made after add_child and still lands before
	# the signal, because the propagation above has not happened yet.
	instance.ready.connect(_on_preflight_ready)
	# A _ready that never returns blocks the engine before any of that — no frame
	# ever runs, nothing more is printed, and only gda's own launch bound ends it.
	_begin_pending(_preflight_tick, int(frames))


# The scene reported ready. Latched, never un-latched: what happens to the node
# afterwards (it frees itself, it leaves the tree) does not unmake the fact that it
# started. The fact is also PRINTED immediately as its own evidence line: a _ready
# that calls get_tree().quit() ends the run before the pending tick can emit the
# result sentinel, and without this line the readiness it plainly reached would
# leave the process with it (#709 review).
func _on_preflight_ready() -> void:
	_preflight_ready = true
	print(PREFLIGHT_READY_EVIDENCE)


# The frame budget of one preflight: a positive whole number of idle frames. Null
# after recording the failure (the caller must stop). Checked as a raw Variant
# before coercion for the reason _validate_target_paths states: int() on arbitrary
# JSON raises, which would abort _initialize before any sentinel is printed.
#
# REQUIRED, with no default of its own. The window's default belongs to gda's params
# model, which every CLI invocation goes through; inventing a second one here would
# be a second authority for one fact — and an unreachable one, so it could disagree
# with the real default indefinitely without anyone noticing. A caller driving the
# payload directly states its own window.
func _preflight_frames(params: Dictionary) -> Variant:
	if not params.has("frames"):
		_fail(OP_ERROR_INVALID_PARAMS, "frames is required: the observation window, in idle frames")
		return null
	var raw: Variant = params.get("frames")
	if not (raw is float or raw is int):
		_fail(OP_ERROR_INVALID_PARAMS, "frames must be a number: " + str(raw))
		return null
	# JSON numbers arrive as floats; only a mathematically integral one names a
	# frame count. int(raw) would silently truncate 1.5 to a one-frame window
	# (#720 review), and a silent shrink of an observation window is a verdict
	# changer, not a rounding detail.
	if raw is float and raw != floorf(raw):
		_fail(OP_ERROR_INVALID_PARAMS, "frames must be a whole number: " + str(raw))
		return null
	var frames := int(raw)
	if frames < 1:
		_fail(OP_ERROR_INVALID_PARAMS, "frames must be at least 1: " + str(frames))
		return null
	return frames


# One idle frame of a running preflight; true once the verdict is recorded (#664).
#
# The readiness signal above is what normally latches the verdict; this poll is the
# backstop for a node that became ready without emitting to this connection, and it
# costs one call per frame. is_instance_valid guards the node the signal case cares
# about: reading a property off a freed node would abort this tick, and a
# verdict-reporting path must not throw.
func _preflight_tick(frame: int) -> bool:
	if is_instance_valid(_preflight_instance) and _preflight_instance.is_node_ready():
		_preflight_ready = true
	if frame < _pending_frame_limit:
		return false
	_succeed({
		"path": _preflight_path,
		"status": SCENE_STARTUP_READY if _preflight_ready else SCENE_STARTUP_NOT_READY,
	})
	return true


# node-add: load a .tscn, add a child node under a parent node path, pack and
# save it back — the node-group mutate tracer (issue #53). The parent is
# addressed by node path relative to the scene root ('.' is the root itself).
#
# Unlike the read operations, mutation REQUIRES instantiating the scene — only
# a real node tree can be edited and re-packed. Instantiating runs the _init
# of any script attached in the scene, so node-add executes project code where
# scene-get (issue #30) deliberately does not; likewise creating a class_name
# node runs that script's constructor. Inherent to headless file mutation.
func _op_node_add(params: Dictionary) -> void:
	_diag("running operation: node-add")
	var path := _string_param(params, "path")

	var node_name := _string_param(params, "name")
	if not _is_valid_node_name(node_name):
		_fail(OP_ERROR_INVALID_NODE_NAME, "invalid name: " + node_name)
		return

	var root: Node = _load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure
	var parent_path := _string_param(params, "parent")
	var parent := _resolve_node(root, parent_path)
	if parent == null:
		root.free()
		if _is_canonical_parent_path(parent_path):
			_fail(OP_ERROR_PARENT_NOT_FOUND, "parent node not found in scene: " + parent_path)
		else:
			_fail(OP_ERROR_PARENT_NOT_FOUND, "non-canonical parent path: " + parent_path
					+ " — address the parent exactly as node list reports it: '.' for the root, 'A/B' for a descendant")
		return
	if parent.get_node_or_null(NodePath(node_name)) != null:
		root.free()
		_fail(OP_ERROR_DUPLICATE_NODE_NAME, "parent " + parent_path + " already has a child named: " + node_name)
		return
	var has_index := _has_int_param(params, "index")
	var insert_index := _int_param(params, "index") if has_index else -1
	var child_count := parent.get_child_count()
	if has_index and (insert_index < 0 or insert_index > child_count):
		root.free()
		_fail(OP_ERROR_INVALID_CHILD_INDEX, "child index " + str(insert_index)
				+ " is out of range for parent " + parent_path
				+ ": expected 0.." + str(child_count))
		return

	var type := _string_param(params, "type")
	var instance_path := _string_param(params, "instance")
	var node: Node = null
	if instance_path != "":
		node = _instantiate_scene_instance(instance_path, path)
	else:
		node = _instantiate_node_type(type)
	if node == null:
		root.free()
		return  # the instantiation helper already recorded the failure

	# A parentless node never has its name rewritten: _is_valid_node_name already
	# rejected the chars Godot sanitizes, and the @-dedup suffix is only appended
	# inside add_child (already guarded by the duplicate-name check above). So the
	# assigned name is final; no post-assignment recheck is needed.
	node.name = node_name
	parent.add_child(node)
	if has_index:
		parent.move_child(node, insert_index)
	node.owner = root

	# Capture the node's identity off the live tree before re-saving frees it.
	var node_path := String(root.get_path_to(node))
	var node_type := node.get_class()
	var script_class: Variant = _script_class_of(node)
	if not _repack_and_save(root, path):
		return  # _repack_and_save already recorded the failure (and freed root)

	_succeed({
		"scene_path": path,
		"path": node_path,
		"name": node_name,
		"type": node_type,
		"script_class": script_class,
		"instance": instance_path if instance_path != "" else null,
	})


# node-list: load a .tscn and emit its node tree with per-node paths — the
# node-group verifier (issue #53): each node carries the address an agent
# feeds back into node add's --parent. Reads SceneState without instantiating,
# exactly like scene-get (issue #30): listing must not execute project code.
func _op_node_list(params: Dictionary) -> void:
	_diag("running operation: node-list")
	var packed: PackedScene = _load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var path := _string_param(params, "path")

	_succeed({
		"scene_path": path,
		"root": _tree_from_state(packed.get_state(), true, _scene_instance_paths_by_node_path(path)),
	})


# node-get: load a .tscn, resolve a node by node path, and emit its storage
# properties as typed JSON — the read half of issue #55. Unlike node-list,
# reporting a node's actual property VALUES requires the instantiated node:
# SceneState only stores explicitly-overridden values, not defaults, and not in
# a clean typed projection. Instantiating runs the _init of attached scripts
# (the same trust boundary as node-add), but node-get does not re-save, so it
# skips the unmaterialized-node guard (that boundary protects a re-save from
# silently dropping data, issue #64 — there is no save here to protect). The
# node still has to exist in the instantiated tree, reported as node_not_found.
func _op_node_get(params: Dictionary) -> void:
	_diag("running operation: node-get")
	var packed: PackedScene = _load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var root: Node = packed.instantiate()
	if root == null:
		_fail(OP_ERROR_MISSING_DEPENDENCY, "scene failed to instantiate: "
				+ _string_param(params, "path")
				+ " — an instanced sub-scene is unresolvable or empty; check the scene's dependencies and --project")
		return
	var node_path := _string_param(params, "node")
	var node := _resolve_node(root, node_path)
	if node == null:
		root.free()
		_fail_node_not_found(node_path)
		return

	var properties: Array = []
	for prop in node.get_property_list():
		if not _is_storage_property(prop):
			continue
		var prop_name := String(prop.get("name", ""))
		properties.append({
			"name": prop_name,
			"type": _type_name(int(prop.get("type", TYPE_NIL))),
			"value": _jsonify(node.get(prop_name)),
		})
	# Capture the node's identity before freeing the tree: freeing root frees
	# node too, and reading off a freed node is a runtime error.
	var node_name := String(node.name)
	var node_type := node.get_class()
	root.free()

	_succeed({
		"scene_path": _string_param(params, "path"),
		"path": node_path,
		"name": node_name,
		"type": node_type,
		"properties": properties,
	})


# node-set: load a .tscn, resolve a node by node path, set one property —
# coercing the CLI string value to the property's declared Godot type — then
# pack and save (the write half of issue #55, verifiable via node-get). As a
# mutating op it goes through the shared mutate-entry (load → instantiate →
# unmaterialized-node guard), so it honors the mutation-integrity boundary the
# command catalog promises (issue #64): a re-save can never silently drop an
# unresolvable instance or downgrade a substituted class.
func _op_node_set(params: Dictionary) -> void:
	_diag("running operation: node-set")
	var path := _string_param(params, "path")
	var root: Node = _load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure
	var node_path := _string_param(params, "node")
	var node := _resolve_node(root, node_path)
	if node == null:
		root.free()
		_fail_node_not_found(node_path)
		return

	var prop_name := _string_param(params, "property")
	if _is_control_position_write(node, prop_name):
		var control: Control = node as Control
		if _has_container_parent(control):
			root.free()
			_fail(OP_ERROR_UNKNOWN_PROPERTY,
					_control_position_unavailable_message("node " + node_path))
			return
		var raw_position := _string_param(params, "value")
		var coerced_position: Variant = _coerce_value(raw_position,
				TYPE_VECTOR2, control.position)
		if coerced_position == null:
			root.free()
			_fail(OP_ERROR_UNCOERCIBLE_VALUE, "cannot coerce value "
					+ raw_position.c_escape()
					+ " to Vector2 for property position on node " + node_path)
			return
		var target_position: Vector2 = coerced_position
		control.set_position(target_position)
		var stored_position: Variant = _jsonify(control.position)
		if not _repack_and_save(root, path):
			return  # _repack_and_save already recorded the failure (and freed root)

		_succeed({
			"scene_path": path,
			"path": node_path,
			"property": prop_name,
			"type": _type_name(TYPE_VECTOR2),
			"value": stored_position,
		})
		return

	var declared_type := _property_type(node, prop_name)
	if declared_type == TYPE_NIL:
		root.free()
		_fail(OP_ERROR_UNKNOWN_PROPERTY, "node " + node_path
				+ " has no settable property: " + prop_name)
		return

	var raw_value := _string_param(params, "value")
	var stored_value: Variant
	if declared_type == TYPE_OBJECT:
		# Object-typed property: assign an EXISTING Resource referenced by a res://
		# path (ADR-0033, #363). A separate, headless-only step from the shared
		# _coerce_value (it needs the expected-class hint that Variant.Type/current
		# container context cannot carry); it records its own distinct structured failure.
		var resolved := _resolve_object_value(prop_name,
				_storage_property_entry(node, prop_name), raw_value, "node " + node_path)
		if resolved == null:
			root.free()
			return  # _resolve_object_value already recorded the failure
		node.set(prop_name, resolved)
		# The echo is the same reference projection a subsequent get reads back
		# (ADR-0035): {type, resource_path}. On disk the assignment still
		# round-trips as its res:// path — the loaded resource carries a
		# resource_path, so re-packing serializes it as an ext_resource.
		stored_value = _jsonify(resolved)
	else:
		var current_value: Variant = node.get(prop_name)
		var coerced: Variant = _coerce_value(raw_value, declared_type, current_value)
		if coerced == null:
			root.free()
			_fail(OP_ERROR_UNCOERCIBLE_VALUE, "cannot coerce value " + raw_value.c_escape()
					+ " to " + _type_name(declared_type) + " for property " + prop_name
					+ " on node " + node_path)
			return

		node.set(prop_name, coerced)

		# Read the value back off the node before re-saving frees the tree — the node
		# now holds the coerced value in its canonical form, the same projection
		# node-get reports.
		stored_value = _jsonify(node.get(prop_name))
	if not _repack_and_save(root, path):
		return  # _repack_and_save already recorded the failure (and freed root)

	_succeed({
		"scene_path": path,
		"path": node_path,
		"property": prop_name,
		"type": _type_name(declared_type),
		"value": stored_value,
	})


func _is_control_position_write(node: Node, prop_name: String) -> bool:
	return prop_name == "position" and node is Control


func _has_container_parent(control: Control) -> bool:
	return control.get_parent() is Container


func _control_position_unavailable_message(subject: String) -> String:
	return subject + " is a direct child of a Container, so Control.position is not an actionable settable property; address offset_left, offset_top, offset_right, and offset_bottom instead"


# node-remove: load a .tscn, resolve a node by node path, delete it and its
# whole subtree, then re-pack and save — the first structural edit of issue #56.
# As a mutating op it goes through the shared mutate-entry (load → instantiate →
# unmaterialized-node guard), so it honors the mutation-integrity boundary
# (issue #64): a re-save never silently drops an unresolvable instance.
#
# The scene root has no parent to be detached from, and the re-pack needs a
# root, so removing '.' is refused with cannot_target_root rather than emptying
# the scene. A node path that resolves to nothing is node_not_found, the same
# code (and resolver) node get / node set use.
func _op_node_remove(params: Dictionary) -> void:
	_diag("running operation: node-remove")
	var path := _string_param(params, "path")
	var root: Node = _load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure
	var node_path := _string_param(params, "node")
	var node := _resolve_node(root, node_path)
	if node == null:
		root.free()
		_fail_node_not_found(node_path)
		return
	if node == root:
		root.free()
		_fail(OP_ERROR_CANNOT_TARGET_ROOT, "cannot remove the scene root: " + node_path
				+ " — the root has no parent to be removed from; delete the scene file instead")
		return

	# Capture the removed node's identity off the live tree before detaching and
	# re-saving free it.
	var removed_name := String(node.name)
	var removed_type := node.get_class()
	node.get_parent().remove_child(node)
	node.free()

	if not _repack_and_save(root, path):
		return  # _repack_and_save already recorded the failure (and freed root)

	_succeed({
		"scene_path": path,
		"path": node_path,
		"name": removed_name,
		"type": removed_type,
	})


# node-duplicate: load a .tscn, resolve a node by node path, duplicate it and
# its whole subtree under the SAME parent with a fresh non-colliding name, then
# re-pack and save (issue #56). Returns the copy's new node path so an agent can
# address it without re-listing. As a mutating op it goes through the shared
# mutate-entry, honoring the mutation-integrity boundary (issue #64).
#
# duplicate() copies the subtree (storage properties, script, children), but the
# copy and its descendants are unowned, so a re-pack would not serialize them;
# _reown_subtree claims the whole copied subtree under the scene root before
# saving. The scene root has no parent to host a sibling copy, so duplicating
# '.' is refused with cannot_target_root; a node path resolving to nothing is
# node_not_found, the node group's shared code.
func _op_node_duplicate(params: Dictionary) -> void:
	_diag("running operation: node-duplicate")
	var path := _string_param(params, "path")
	var root: Node = _load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure
	var node_path := _string_param(params, "node")
	var node := _resolve_node(root, node_path)
	if node == null:
		root.free()
		_fail_node_not_found(node_path)
		return
	if node == root:
		root.free()
		_fail(OP_ERROR_CANNOT_TARGET_ROOT, "cannot duplicate the scene root: " + node_path
				+ " — the root has no parent to host a sibling copy")
		return

	var parent := node.get_parent()
	var fresh_name := _fresh_child_name(parent, String(node.name))
	var copy := node.duplicate()
	copy.name = fresh_name
	parent.add_child(copy)
	# The duplicated subtree is unowned; claim every node under the scene root so
	# the re-pack serializes the whole copy, not just an empty placeholder.
	_reown_subtree(copy, root)

	# Capture the copy's identity off the live tree before re-saving frees it.
	var new_path := String(root.get_path_to(copy))
	var copy_name := String(copy.name)
	var copy_type := copy.get_class()
	if not _repack_and_save(root, path):
		return  # _repack_and_save already recorded the failure (and freed root)

	_succeed({
		"scene_path": path,
		"source_path": node_path,
		"path": new_path,
		"name": copy_name,
		"type": copy_type,
	})


# A fresh child name for `parent` derived from `base`, never colliding with an
# existing child (including the engine's internal children, which
# get_node_or_null resolves through). Mirrors the Godot editor's duplicate
# naming: append an incrementing integer starting at 2 ("Hero" → "Hero2", then
# "Hero3", …). A name Godot would itself rewrite can never be produced because
# `base` is an already-valid node name and only digits are appended.
func _fresh_child_name(parent: Node, base: String) -> String:
	var index := 2
	var candidate := base + str(index)
	while parent.get_node_or_null(NodePath(candidate)) != null:
		index += 1
		candidate = base + str(index)
	return candidate


# Claim `node` and its whole subtree under `owner` so the re-pack serializes
# every node (a node whose owner is not the scene root is dropped from the
# packed scene). Used after duplicate(), which produces an unowned copy.
func _reown_subtree(node: Node, owner: Node) -> void:
	node.owner = owner
	for child in node.get_children():
		_reown_subtree(child, owner)


# node-move: load a .tscn, resolve a node and a target parent by node path,
# reparent the node (and its whole subtree) under the target, then re-pack and
# save (the third and most complex structural edit of issue #56). Returns the
# node's new node path. As a mutating op it goes through the shared mutate-entry,
# honoring the mutation-integrity boundary (issue #64).
#
# Failure modes, each a registered code leaving the file untouched:
# - the moved node resolves to nothing → node_not_found; the scene root has no
#   parent to be reparented out of → cannot_target_root.
# - the target parent resolves to nothing → parent_not_found (the same code, and
#   canonical-vs-non-canonical message, node add reports for its --parent).
# - the target is the node itself or one of its OWN descendants → cyclic_target:
#   reparenting there would detach the whole subtree from the scene.
# - the target already has a different child with the moved node's name →
#   duplicate_node_name (the same code node add reports).
#
# Moving a node to the parent it ALREADY sits under is a successful no-op: the
# node is already where the request wants it, so move returns success without
# touching the tree or re-saving the file — a detach-and-reappend would shuffle
# the node to the end of its (unchanged) parent and silently reorder siblings,
# which is meaningful in Godot (issue #56 review).
#
# Reparenting uses Node.reparent(target, false) rather than a manual
# remove_child → add_child + _reown_subtree. reparent() preserves the moved
# node's owner AND its descendants' owners, so an instanced sub-scene under the
# node keeps its instance= reference, its [editable ...] marker, and its
# inherited/override children — a manual reown would rewrite those overrides into
# locally-owned type= nodes, breaking instance inheritance and violating the #64
# mutation-integrity boundary (verified empirically on Godot 4.6.3). The false
# (keep_global_transform=false) argument keeps the move purely structural: the
# node retains its LOCAL transform instead of having it rewritten to preserve a
# global position the headless edit never cared about.
func _op_node_move(params: Dictionary) -> void:
	_diag("running operation: node-move")
	var path := _string_param(params, "path")
	var root: Node = _load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure
	var node_path := _string_param(params, "node")
	var node := _resolve_node(root, node_path)
	if node == null:
		root.free()
		_fail_node_not_found(node_path)
		return
	if node == root:
		root.free()
		_fail(OP_ERROR_CANNOT_TARGET_ROOT, "cannot move the scene root: " + node_path
				+ " — the root has no parent to be reparented out of")
		return

	var target_path := _string_param(params, "to")
	var target := _resolve_node(root, target_path)
	if target == null:
		root.free()
		if _is_canonical_parent_path(target_path):
			_fail(OP_ERROR_PARENT_NOT_FOUND, "target parent node not found in scene: " + target_path)
		else:
			_fail(OP_ERROR_PARENT_NOT_FOUND, "non-canonical target path: " + target_path
					+ " — address the parent exactly as node list reports it: '.' for the root, 'A/B' for a descendant")
		return

	# Cyclic target: moving a node under itself or one of its own descendants
	# would detach the whole subtree from the scene. is_ancestor_of is false for
	# the node itself, so check identity separately.
	if target == node or node.is_ancestor_of(target):
		root.free()
		_fail(OP_ERROR_CYCLIC_TARGET, "cyclic move target: " + target_path
				+ " is the moved node " + node_path + " or one of its descendants"
				+ " — a node cannot become a child of its own subtree")
		return

	var has_index := _has_int_param(params, "index")
	var requested_index := _int_param(params, "index") if has_index else -1

	# Same-parent move without --index: the node is already under the requested
	# parent, so this remains the legacy successful no-op. With --index, the same
	# request becomes an explicit sibling reorder and is persisted with move_child.
	if node.get_parent() == target:
		var here_name := String(node.name)
		var here_type := node.get_class()
		var sibling_count := target.get_child_count()
		if has_index and (requested_index < 0 or requested_index >= sibling_count):
			root.free()
			_fail(OP_ERROR_INVALID_CHILD_INDEX, "child index " + str(requested_index)
					+ " is out of range for parent " + target_path
					+ ": expected 0.." + str(sibling_count - 1))
			return
		if has_index and requested_index != node.get_index():
			target.move_child(node, requested_index)
			if not _repack_and_save(root, path):
				return  # _repack_and_save already recorded the failure (and freed root)
		else:
			root.free()
		_succeed({
			"scene_path": path,
			"source_path": node_path,
			"new_parent": target_path,
			"path": node_path,
			"name": here_name,
			"type": here_type,
		})
		return

	# Name collision at the destination: the target already has a child with this
	# name. (The same-parent no-op above already returned for a node already under
	# the target, so any match here is a genuine different node.)
	var node_name := String(node.name)
	if target.get_node_or_null(NodePath(node_name)) != null:
		root.free()
		_fail(OP_ERROR_DUPLICATE_NODE_NAME, "target " + target_path
				+ " already has a child named: " + node_name)
		return
	var target_child_count := target.get_child_count()
	if has_index and (requested_index < 0 or requested_index > target_child_count):
		root.free()
		_fail(OP_ERROR_INVALID_CHILD_INDEX, "child index " + str(requested_index)
				+ " is out of range for parent " + target_path
				+ ": expected 0.." + str(target_child_count))
		return

	# reparent(target, false) preserves the moved node's and its descendants'
	# owners (so an instanced sub-scene keeps its overrides and editable marker)
	# and keeps the node's LOCAL transform (a purely structural move, no churn).
	node.reparent(target, false)
	if has_index:
		target.move_child(node, requested_index)

	# Capture the moved node's new identity off the live tree before re-saving.
	var new_path := String(root.get_path_to(node))
	var moved_name := String(node.name)
	var moved_type := node.get_class()
	if not _repack_and_save(root, path):
		return  # _repack_and_save already recorded the failure (and freed root)

	_succeed({
		"scene_path": path,
		"source_path": node_path,
		"new_parent": target_path,
		"path": new_path,
		"name": moved_name,
		"type": moved_type,
	})


# node-connect-signal: wire a source node's signal to a target node's method,
# persisted into the .tscn as a [connection] (issue #57). As a scene mutation it
# reuses the same load -> resolve -> mutate -> pack -> save round-trip as node-set,
# honoring the mutation-integrity boundary (#64) via _load_for_mutation.
#
# Persistence mechanism: PackedScene.pack only serializes a connection whose
# Callable was registered with Object.CONNECT_PERSIST — a plain connect() is a
# runtime-only wiring the pack drops. Setting it up on the instantiated tree with
# CONNECT_PERSIST makes pack(root) emit the [connection signal=... from=... to=...
# method=...] line, which a re-read sees as is_connected() == true.
#
# Contract (issue #57's design decision): the SIGNAL must exist on the source node
# (signal_not_found). The target METHOD need NOT exist — a [connection] is just
# persisted data, and Godot's own editor lets you wire a signal to a not-yet-
# written method, so a dangling method is allowed (verified on Godot 4.6.3:
# connecting to a missing method returns OK and serializes).
func _op_node_connect_signal(params: Dictionary) -> void:
	_diag("running operation: node-connect-signal")
	var path := _string_param(params, "path")
	var root: Node = _load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure

	var from_path := _string_param(params, "from")
	var source := _resolve_node(root, from_path)
	if source == null:
		root.free()
		_fail_node_not_found_labeled("source", from_path)
		return
	var to_path := _string_param(params, "to")
	var target := _resolve_node(root, to_path)
	if target == null:
		root.free()
		_fail_node_not_found_labeled("target", to_path)
		return

	var signal_name := _string_param(params, "signal")
	if not source.has_signal(signal_name):
		root.free()
		_fail(OP_ERROR_SIGNAL_NOT_FOUND, "source node " + from_path
				+ " has no signal: " + signal_name)
		return

	var method_name := _string_param(params, "method")
	var callable := Callable(target, method_name)
	# A duplicate connection is reported, not silently re-applied: a plain
	# connect() of an existing connection errors noisily (ERR_INVALID_PARAMETER),
	# so guard with is_connected and report already_connected instead.
	if source.is_connected(signal_name, callable):
		root.free()
		_fail(OP_ERROR_ALREADY_CONNECTED, from_path + "." + signal_name
				+ " is already connected to " + to_path + "." + method_name)
		return

	# CONNECT_PERSIST is what makes pack(root) serialize the connection into the
	# .tscn; without it the wiring is runtime-only and the pack drops it.
	var connect_err := source.connect(signal_name, callable, Object.CONNECT_PERSIST)
	if connect_err != OK:
		root.free()
		_fail(OP_ERROR_SAVE_FAILED, "failed to connect " + from_path + "." + signal_name
				+ " to " + to_path + "." + method_name + ": " + error_string(connect_err))
		return

	if not _repack_and_save(root, path):
		return  # _repack_and_save already recorded the failure (and freed root)

	_succeed({
		"scene_path": path,
		"from": from_path,
		"signal": signal_name,
		"to": to_path,
		"method": method_name,
	})


# node-disconnect-signal: remove an existing signal->method connection from the
# .tscn (issue #57). A connection that does not exist is a clean
# connection_not_found error rather than a silent no-op; a missing signal on the
# source means there can be no such connection, so it maps to the same code.
func _op_node_disconnect_signal(params: Dictionary) -> void:
	_diag("running operation: node-disconnect-signal")
	var path := _string_param(params, "path")
	var root: Node = _load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure

	var from_path := _string_param(params, "from")
	var source := _resolve_node(root, from_path)
	if source == null:
		root.free()
		_fail_node_not_found_labeled("source", from_path)
		return
	var to_path := _string_param(params, "to")
	var target := _resolve_node(root, to_path)
	if target == null:
		root.free()
		_fail_node_not_found_labeled("target", to_path)
		return

	var signal_name := _string_param(params, "signal")
	# A missing source signal is signal_not_found, symmetric with connect-signal
	# and the documented contract: a typo'd signal is fixed by naming the right
	# signal, not by being collapsed into an absent connection (issue #57 review).
	if not source.has_signal(signal_name):
		root.free()
		_fail(OP_ERROR_SIGNAL_NOT_FOUND, "source node " + from_path
				+ " has no signal: " + signal_name)
		return
	var method_name := _string_param(params, "method")
	var callable := Callable(target, method_name)
	# The signal exists but carries no such connection: nothing to remove. Guard
	# with is_connected rather than call disconnect() (which errors on an absent
	# connection).
	if not source.is_connected(signal_name, callable):
		root.free()
		_fail(OP_ERROR_CONNECTION_NOT_FOUND, "no such connection: " + from_path + "."
				+ signal_name + " -> " + to_path + "." + method_name)
		return

	source.disconnect(signal_name, callable)

	if not _repack_and_save(root, path):
		return  # _repack_and_save already recorded the failure (and freed root)

	_succeed({
		"scene_path": path,
		"from": from_path,
		"signal": signal_name,
		"to": to_path,
		"method": method_name,
	})


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
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _is_script_path(path):
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
		var base := _string_param(params, "extends_type")
		if base.is_empty():
			base = "Node"
		source = "extends " + base + "\n"

	var created_dirs: Variant = _ensure_parent_dirs(path)
	if created_dirs == null:
		return  # _ensure_parent_dirs already recorded the failure
	if not _write_script_file(path, source):
		return  # _write_script_file already recorded the failure

	var meta := _script_metadata(source)
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
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_script(path):
		return  # _require_existing_script already recorded the failure

	var source: Variant = _read_script_source(path)
	if source == null:
		return  # _read_script_source already recorded the failure

	var meta := _script_metadata(source)
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
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_script(path):
		return  # _require_existing_script already recorded the failure

	# Read the metadata before deletion so the result names the content removed.
	# A read error here is non-fatal: the file exists and is about to be deleted,
	# so fall back to null metadata rather than failing the delete.
	var meta := _script_metadata(FileAccess.get_file_as_string(path))

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
	var path := _string_param(params, "path")
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
	_capture_staleness_token(path)

	# Dispatch on the explicit mode discriminator the CLI resolved (issue #133):
	# the edit mode is decided once, at the CLI's mutual-exclusion check, and rides
	# through on `mode` — the op never re-infers it from which params are present,
	# so the op's dispatch can no longer drift from the CLI's exclusivity rule.
	var mode := _string_param(params, "mode")
	var new_source: Variant
	match mode:
		"search_replace":
			new_source = _apply_search_replace(source, params, "script")
		"line_range":
			new_source = _apply_line_range(source, params, "script")
		"full":
			# full overwrite: content is guaranteed present by the CLI's mode check.
			new_source = _string_param(params, "content")
		_:
			# The CLI always supplies one of the three modes; a missing/unknown mode
			# means a malformed direct op invocation, not a reachable CLI path.
			_fail(OP_ERROR_INVALID_PARAMS, "unknown script-set mode: " + mode)
			return
	if new_source == null:
		return  # the apply helper already recorded the failure

	# Recheck before the write (issue #226): refuse if a concurrent editor changed the
	# .gd in the read->write window.
	if not _check_unchanged():
		return
	if not _write_script_file(path, new_source):
		return  # _write_script_file already recorded the failure

	# Re-parse the written source so set round-trips through script get.
	var meta := _script_metadata(new_source)
	_succeed({
		"path": path,
		"class_name": meta["class_name"],
		"extends": meta["extends"],
	})


# search-replace edit: replace every literal occurrence of `search` with
# `replace`. An empty or absent search string can never be located, and a search
# string the source does not contain is a no_search_match failure (so an agent
# learns the edit landed nowhere rather than silently writing the file back
# unchanged). Returns null after recording the failure.
func _apply_search_replace(source: String, params: Dictionary, noun: String) -> Variant:
	var search := _string_param(params, "search")
	var replace := _string_param(params, "replace")
	if search.is_empty() or not source.contains(search):
		_fail(OP_ERROR_NO_SEARCH_MATCH, "search string not found in " + noun + ": " + search.c_escape())
		return null
	return source.replace(search, replace)


# line-range edit: replace the 1-based, inclusive line span [start_line,
# end_line] with `content`. Lines are the parts of the source split on its
# newline, so a trailing newline yields a final empty part ("a\nb\n" →
# ["a","b",""], N=3); the valid range is 1..N. end_line defaults to start_line
# (a single-line edit). A range outside the bounds, or end before start, is
# invalid_line_range. Returns null after recording the failure.
#
# The file's own newline (CRLF when the source uses it, else LF) is used to both
# split and rejoin, and the replacement `content` is normalized onto it, so
# editing a CRLF script preserves CRLF instead of corrupting the edited span to
# mixed endings. A mixed-ending file is pathological and resolves to CRLF.
func _apply_line_range(source: String, params: Dictionary, noun: String) -> Variant:
	var newline := "\r\n" if source.contains("\r\n") else "\n"
	var lines := source.split(newline)
	var line_count := lines.size()
	var start_line := int(params.get("start_line", 0))
	var end_line: int = int(params.get("end_line", start_line)) if params.get("end_line", null) != null else start_line
	if start_line < 1 or start_line > line_count or end_line < start_line or end_line > line_count:
		_fail(OP_ERROR_INVALID_LINE_RANGE, "line range " + str(start_line) + ".." + str(end_line)
				+ " is outside the " + noun + "'s bounds (1.." + str(line_count) + ") or ends before it starts")
		return null
	var content := _string_param(params, "content")
	var before := lines.slice(0, start_line - 1)
	var after := lines.slice(end_line)
	# Normalize the replacement's own newlines onto the file's so the whole edited
	# file keeps one consistent ending.
	var replacement := content.replace("\r\n", "\n").split("\n")
	var rebuilt: Array = []
	rebuilt.append_array(before)
	rebuilt.append_array(replacement)
	rebuilt.append_array(after)
	return newline.join(PackedStringArray(rebuilt))


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
	var path := _string_param(params, "path")

	# Primary subject first: load + instantiate the scene, then resolve the node —
	# validated before the secondary --script input (issue #132, Part 2).
	var root: Node = _load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure
	var node_path := _string_param(params, "node")
	var node := _resolve_node(root, node_path)
	if node == null:
		root.free()
		_fail_node_not_found(node_path)
		return

	# Secondary input: validate the --script arg only now — its .gd shape
	# (invalid_path) and existence (path_not_found), via the shared #135 helper — so
	# a scene/node problem is always reported ahead of a script problem (issue #132,
	# Part 2). The helper records the failure; the caller frees the live tree.
	var script_path := _string_param(params, "script")
	if not _require_existing_script(script_path):
		root.free()
		return  # _require_existing_script already recorded the failure
	if not _validate_script_preload_dependencies(script_path):
		root.free()
		return  # _validate_script_preload_dependencies already recorded the failure

	# load returns a non-null Script even for a .gd that does not compile (compile
	# errors go to stderr; the resource still loads), so a null here is a genuine
	# resource-load failure (e.g. no format loader), not a compile verdict — guard
	# it so set_script is never handed null (which would clear the node's script).
	var script := ResourceLoader.load(script_path) as Script
	if script == null:
		root.free()
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
		root.free()
		if compiles:
			_fail(OP_ERROR_INCOMPATIBLE_SCRIPT_TYPE, "script extends " + script_base
					+ ", which is incompatible with node " + node_path + " of type " + node_class
					+ " — attach it to a " + script_base + " node, or change the script's extends")
		else:
			_fail(OP_ERROR_SCRIPT_COMPILE_FAILED, "script does not compile, so it cannot be attached: "
					+ script_path + " — fix it, or check it with `gda script validate`")
		return

	# Capture the attached class_name off the live node before re-saving frees it.
	var class_name_value: Variant = _script_class_of(node)
	if not _repack_and_save(root, path):
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

	_succeed({
		"valid": aggregate,
		"scripts": scripts,
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


# resource-create: instantiate a Resource of the requested type and save it as a
# .tres at the requested path — the resource group's save tracer (issue #112).
# Establishes the .tres load/save plumbing the rest of the group reuses.
#
# No-clobber: an existing target is refused with already_exists, leaving it
# untouched (mirrors scene-create / script-create). The type must resolve to an
# instantiable Resource — a built-in Resource class OR a project-defined
# class_name (GDScript `class_name Foo extends Resource`), resolved the same way
# node add resolves --type (issue #342). An unknown type or a non-Resource class
# (e.g. a Node) is refused with invalid_resource_type; a registered class_name
# whose script broke since the project scan is uninstantiable_script — parallel
# to node add's invalid_node_type / uninstantiable_script split. A script-backed
# Resource runs the script's _init at construction (its constructor is project
# code, within the Trusted project assumption, ADR-0009); a built-in class
# constructs an engine class and runs none.
#
# The no-clobber check runs BEFORE construction, so an existing target is refused
# without ever executing a script-backed type's _init: a broken constructor over
# an existing file stays already_exists (no-clobber), never uninstantiable_script,
# and no _init side effect runs against a target that would not be written anyway.
func _op_resource_create(params: Dictionary) -> void:
	_diag("running operation: resource-create")
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _is_resource_path(path):
		_fail(OP_ERROR_INVALID_PATH, "resource path must end in .tres: " + path)
		return
	if FileAccess.file_exists(path) or DirAccess.dir_exists_absolute(path):
		_fail(OP_ERROR_ALREADY_EXISTS, "resource target already exists: " + path)
		return
	var type := _string_param(params, "type")
	var resource: Resource = _instantiate_resource_type(type)
	if resource == null:
		return  # _instantiate_resource_type already recorded the failure

	var created_dirs: Variant = _ensure_parent_dirs(path)
	if created_dirs == null:
		return  # _ensure_parent_dirs already recorded the failure
	var save_err := _atomic_save_resource(resource, path)
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message("resource", path, save_err))
		return

	_succeed({
		"path": path,
		"type": type,
		"created_dirs": created_dirs,
	})


# shader-create: author a new .gdshader as RAW TEXT (issue #115). A .gdshader is
# plain shader source — no engine compilation is needed to write it — so create
# is pure file authoring, exactly like script-create (issue #110): no-clobber
# (a target that exists is already_exists), and verbatim --content wins over the
# built-in shader_type template. The created file is verifiable end-to-end by
# shader-get (create → get returns the source).
func _op_shader_create(params: Dictionary) -> void:
	_diag("running operation: shader-create")
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _is_shader_path(path):
		_fail(OP_ERROR_INVALID_PATH, "shader path must end in .gdshader: " + path)
		return
	if FileAccess.file_exists(path) or DirAccess.dir_exists_absolute(path):
		_fail(OP_ERROR_ALREADY_EXISTS, "shader target already exists: " + path)
		return

	# Verbatim content wins; otherwise write a minimal template declaring the
	# requested shader_type (defaulting to canvas_item).
	var source: String
	var content: Variant = params.get("content", null)
	if content is String:
		source = content
	else:
		var shader_type := _string_param(params, "shader_type")
		if shader_type.is_empty():
			shader_type = "canvas_item"
		source = "shader_type " + shader_type + ";\n"

	var created_dirs: Variant = _ensure_parent_dirs(path)
	if created_dirs == null:
		return  # _ensure_parent_dirs already recorded the failure
	if not _write_text_file(path, source, "shader"):
		return  # _write_text_file already recorded the failure

	_succeed({
		"path": path,
		"shader_type": _shader_metadata(source),
		"created_dirs": created_dirs,
	})


# resource-get: load a .tres and emit its storage properties as typed JSON — the
# resource group's verifier (issue #112), which makes a resource-create
# verifiable end-to-end (create → get reports the resource). Reports the same
# typed projection node-get uses (name / declared Godot type / JSON value), so
# the two groups read property values through one shape.
#
# A .tres must exist and load as a Resource: a missing file is path_not_found, a
# non-.tres path invalid_path (the resource group's addressing boundary), and a
# file that does not load as a Resource is not a resource the group can report.
func _op_resource_get(params: Dictionary) -> void:
	_diag("running operation: resource-get")
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_resource(path):
		return  # _require_existing_resource already recorded the failure

	var resource := ResourceLoader.load(path) as Resource
	if resource == null:
		_fail(OP_ERROR_INVALID_PATH, "file could not be loaded as a Resource: " + path)
		return

	var properties: Array = []
	for prop in resource.get_property_list():
		if not _is_storage_property(prop):
			continue
		var prop_name := String(prop.get("name", ""))
		properties.append({
			"name": prop_name,
			"type": _type_name(int(prop.get("type", TYPE_NIL))),
			"value": _jsonify(resource.get(prop_name)),
		})

	_succeed({
		"path": path,
		"type": resource.get_class(),
		"properties": properties,
	})


# resource-set: load a .tres, coerce a CLI string value to a property's declared
# Godot type and set it, then re-save the resource (issue #120). Mirrors node-set
# / project-set: the declared type comes from the property the resource actually
# declares, never from guessing, and the coerced value is read back off the
# resource before reporting, so a set round-trips through resource get. set edits
# an EXISTING property — an unknown property is unknown_property, never a silent
# create — reusing the #55 codes (unknown_property / uncoercible_value).
func _op_resource_set(params: Dictionary) -> void:
	_diag("running operation: resource-set")
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_resource(path):
		return  # _require_existing_resource already recorded the failure

	var resource := ResourceLoader.load(path) as Resource
	if resource == null:
		_fail(OP_ERROR_INVALID_PATH, "file could not be loaded as a Resource: " + path)
		return
	# Capture the staleness token right after the read (issue #226) — resource-set
	# does not use the shared pack-and-save tail, so it wires capture/recheck itself.
	_capture_staleness_token(path)

	var prop_name := _string_param(params, "property")
	var declared_type := _resource_property_type(resource, prop_name)
	if declared_type == TYPE_NIL:
		_fail(OP_ERROR_UNKNOWN_PROPERTY, "resource " + path
				+ " has no settable property: " + prop_name)
		return

	var raw_value := _string_param(params, "value")
	var stored_value: Variant
	if declared_type == TYPE_OBJECT:
		# Object-typed property: assign an EXISTING Resource referenced by a res://
		# path (ADR-0033, #363) — the resource-on-resource counterpart of node set's
		# Object branch. Headless-only, separate from the shared _coerce_value; it
		# records its own distinct structured failure.
		var resolved := _resolve_object_value(prop_name,
				_storage_property_entry(resource, prop_name), raw_value, "resource " + path)
		if resolved == null:
			return  # _resolve_object_value already recorded the failure
		resource.set(prop_name, resolved)
		# The echo is the same reference projection a subsequent get reads back
		# (ADR-0035): {type, resource_path}. On disk the assignment still
		# round-trips as its res:// path — the loaded resource carries a
		# resource_path, so re-saving serializes it as an ext_resource.
		stored_value = _jsonify(resolved)
	else:
		var current_value: Variant = resource.get(prop_name)
		var coerced: Variant = _coerce_value(raw_value, declared_type, current_value)
		if coerced == null:
			_fail(OP_ERROR_UNCOERCIBLE_VALUE, "cannot coerce value " + raw_value.c_escape()
					+ " to " + _type_name(declared_type) + " for property " + prop_name
					+ " on resource " + path)
			return
		resource.set(prop_name, coerced)
		# Read the value back off the resource before reporting — it now holds the
		# coerced value in its canonical form, the same projection resource get
		# reports, so a set round-trips through a get.
		stored_value = _jsonify(resource.get(prop_name))

	# Recheck before the write (issue #226): refuse if a concurrent editor changed the
	# .tres in the read->write window.
	if not _check_unchanged():
		return
	var save_err := _atomic_save_resource(resource, path)
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message("resource", path, save_err))
		return

	_succeed({
		"path": path,
		"property": prop_name,
		"type": _type_name(declared_type),
		"value": stored_value,
	})


# resource-delete: remove a .tres file from disk, reporting what was removed
# (path + the resource's engine class, read before deletion), completing the
# create → get → set → delete lifecycle (issue #120). Mirrors script-delete:
# validate addressing/existence with _require_existing_resource, capture the
# identity before delete, then DirAccess.remove_absolute (delete_failed on error).
func _op_resource_delete(params: Dictionary) -> void:
	_diag("running operation: resource-delete")
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_resource(path):
		return  # _require_existing_resource already recorded the failure

	# Read the type before deletion so the result names the content removed. A
	# load failure here is non-fatal: the file exists and is about to be deleted,
	# so fall back to a generic Resource class rather than failing the delete.
	var resource := ResourceLoader.load(path) as Resource
	var type := resource.get_class() if resource != null else "Resource"

	var err := DirAccess.remove_absolute(path)
	if err != OK:
		_fail(OP_ERROR_DELETE_FAILED, "failed to delete resource " + path + ": " + error_string(err))
		return

	_succeed({
		"path": path,
		"type": type,
	})


# The declared Godot type of a settable storage property on a resource, or
# TYPE_NIL if the resource has no storage property by that name. resource set
# keys coercion off this: the value's target type comes from the property the
# resource actually declares, never from guessing — the resource counterpart of
# _property_type (which is typed to Node).
func _resource_property_type(resource: Resource, prop_name: String) -> int:
	for prop in resource.get_property_list():
		if String(prop.get("name", "")) == prop_name and _is_storage_property(prop):
			return int(prop.get("type", TYPE_NIL))
	return TYPE_NIL


# Whether a path names a resource file the resource group operates on: a .tres
# (text resource) file. Resource-file addressing is by extension, the same way
# scene addressing keys on .tscn and script addressing on .gd. The binary .res
# form is out of scope for this slice — the group is a .tres tracer (issue #112).
func _is_resource_path(path: String) -> bool:
	return path.get_extension().to_lower() == "tres"


# The resource group's addressing boundary for an EXISTING resource: the path
# must be a .tres (invalid_path otherwise) and the file must exist on disk
# (path_not_found otherwise). Returns true to proceed, or false after recording
# the failure (the caller must stop). Mirrors _require_existing_script.
func _require_existing_resource(path: String) -> bool:
	if not _is_resource_path(path):
		_fail(OP_ERROR_INVALID_PATH, "resource path must end in .tres: " + path)
		return false
	if not FileAccess.file_exists(path):
		_fail(OP_ERROR_PATH_NOT_FOUND, "resource file does not exist: " + path)
		return false
	return true


# shader-get: read a shader's source back as RAW TEXT and report it with the
# shader_type the source declares — the read half of issue #115, which makes a
# shader-create verifiable end-to-end (create → get returns the source). Like
# script-get, it never load()s/compiles the shader, so reading it can never run
# project code (issue #30).
func _op_shader_get(params: Dictionary) -> void:
	_diag("running operation: shader-get")
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_shader(path):
		return  # _require_existing_shader already recorded the failure

	var source: Variant = _read_text_file(path, "shader")
	if source == null:
		return  # _read_text_file already recorded the failure

	_succeed({
		"path": path,
		"source": source,
		"shader_type": _shader_metadata(source),
	})


# shader-set: edit an EXISTING .gdshader on disk as RAW TEXT (issue #115). It
# REUSES the script-set edit-mode interface (issue #118): the same three
# mutually-exclusive modes (search-replace / line-range / full), the same apply
# helpers, dispatched on the same explicit `mode` discriminator the CLI resolves
# (issue #133). It never compiles or loads the shader, so editing it cannot run
# project code (issue #30). set edits an existing shader; a missing target is
# path_not_found, never a silent create.
func _op_shader_set(params: Dictionary) -> void:
	_diag("running operation: shader-set")
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_shader(path):
		return  # _require_existing_shader already recorded the failure

	var source: Variant = _read_text_file(path, "shader")
	if source == null:
		return  # _read_text_file already recorded the failure
	# Capture the staleness token right after the read (issue #226) — shader-set writes
	# raw text directly, not via the shared tail, so it wires capture/recheck itself.
	_capture_staleness_token(path)

	var mode := _string_param(params, "mode")
	var new_source: Variant
	match mode:
		"search_replace":
			new_source = _apply_search_replace(source, params, "shader")
		"line_range":
			new_source = _apply_line_range(source, params, "shader")
		"full":
			# full overwrite: content is guaranteed present by the CLI's mode check.
			new_source = _string_param(params, "content")
		_:
			# The CLI always supplies one of the three modes; a missing/unknown mode
			# means a malformed direct op invocation, not a reachable CLI path.
			_fail(OP_ERROR_INVALID_PARAMS, "unknown shader-set mode: " + mode)
			return
	if new_source == null:
		return  # the apply helper already recorded the failure

	# Recheck before the write (issue #226): refuse if a concurrent editor changed the
	# .gdshader in the read->write window.
	if not _check_unchanged():
		return
	if not _write_text_file(path, new_source, "shader"):
		return  # _write_text_file already recorded the failure

	# Re-parse the written source so set round-trips through shader get.
	_succeed({
		"path": path,
		"shader_type": _shader_metadata(new_source),
	})


# theme-create: produce a loadable .tres Theme resource (issue #115). Unlike the
# shader trio (plain file authoring), a Theme is an ENGINE-BACKED resource: it is
# constructed as a Theme and written through ResourceSaver so the .tres is a
# genuine, loadable resource (the same ResourceSaver path scene-create uses for a
# PackedScene), not hand-written text — the file-level vs engine-backed split the
# script group draws between create/get/set and attach/validate. No-clobber: a
# target that exists is already_exists.
func _op_theme_create(params: Dictionary) -> void:
	_diag("running operation: theme-create")
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _is_theme_path(path):
		_fail(OP_ERROR_INVALID_PATH, "theme path must end in .tres: " + path)
		return
	if FileAccess.file_exists(path) or DirAccess.dir_exists_absolute(path):
		_fail(OP_ERROR_ALREADY_EXISTS, "theme target already exists: " + path)
		return

	var theme := Theme.new()
	var created_dirs: Variant = _ensure_parent_dirs(path)
	if created_dirs == null:
		return  # _ensure_parent_dirs already recorded the failure
	var save_err := _atomic_save_resource(theme, path)
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message("theme", path, save_err))
		return

	_succeed({
		"path": path,
		"type": "Theme",
		"created_dirs": created_dirs,
	})


# Whether a path names a shader file the shader group operates on: a .gdshader
# (Godot shader) file. Shader-file addressing is by extension, the same way
# script addressing keys on .gd and scene addressing on .tscn.
func _is_shader_path(path: String) -> bool:
	return path.get_extension().to_lower() == "gdshader"


# Whether a path names a theme resource file: a .tres. theme-create writes a
# Theme resource, addressed by extension like the rest of the asset-file groups.
func _is_theme_path(path: String) -> bool:
	return path.get_extension().to_lower() == "tres"


# Clear the shader group's addressing boundary for an EXISTING shader: the path
# must be a .gdshader (invalid_path otherwise) and the file must exist on disk
# (path_not_found otherwise). Returns true to proceed, or false after recording
# the failure (the caller must stop). Mirrors _require_existing_script: shared by
# shader get and set so they refuse a non-.gdshader target and a missing file
# identically.
func _require_existing_shader(path: String) -> bool:
	if not _is_shader_path(path):
		_fail(OP_ERROR_INVALID_PATH, "shader path must end in .gdshader: " + path)
		return false
	if not FileAccess.file_exists(path):
		_fail(OP_ERROR_PATH_NOT_FOUND, "shader file does not exist: " + path)
		return false
	return true


# export-list: enumerate the project's export presets (issue #114). Reads the
# project's res://export_presets.cfg with ConfigFile — a cheap config parse, not
# an export run (issue #121 owns running an export) — and reports each preset's
# index/name/platform/runnable. Like scene-list / script-list this needs a
# project (project_not_found otherwise); a project that has never configured an
# export has no export_presets.cfg, which is the distinct export_presets_not_found
# failure rather than a misleading empty listing.
func _op_export_list(_params: Dictionary) -> void:
	_diag("running operation: export-list")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "export list requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var config := _load_export_presets()
	if config == null:
		return  # _load_export_presets already recorded the failure

	var presets: Array = []
	for entry in _export_preset_sections(config):
		presets.append(_export_preset_summary(config, entry["section"], entry["index"]))

	_succeed({"presets": presets})


# export-get: report one export preset's details plus export-template install
# status (issue #114). Addresses the preset by its display NAME (as export-list
# reports it); an unknown name is the export_preset_not_found failure. Beyond the
# preset's own fields it reports whether the export templates for the running
# engine version are installed — the readiness check an agent makes before a
# future export run (issue #121) — and the version directory it checked.
func _op_export_get(params: Dictionary) -> void:
	_diag("running operation: export-get")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "export get requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var preset_name := _string_param(params, "preset")
	if preset_name.is_empty():
		_fail(OP_ERROR_INVALID_PARAMS, "missing required param: preset")
		return

	var config := _load_export_presets()
	if config == null:
		return  # _load_export_presets already recorded the failure

	for entry in _export_preset_sections(config):
		var section: String = entry["section"]
		if String(config.get_value(section, "name", "")) == preset_name:
			var summary := _export_preset_summary(config, section, entry["index"])
			summary["export_path"] = String(config.get_value(section, "export_path", ""))
			var version_dir := _export_templates_version_dir()
			summary["templates_version"] = version_dir
			summary["templates_installed"] = _export_templates_installed(version_dir)
			_succeed(summary)
			return

	_fail(OP_ERROR_EXPORT_PRESET_NOT_FOUND, "no export preset named: " + preset_name)


# Load the project's export_presets.cfg as a ConfigFile, or record a failure and
# return null (the caller must stop). A project with no export_presets.cfg has
# never configured an export, so it is the distinct export_presets_not_found
# failure; a present-but-unparseable file is a save_failed-style read error.
func _load_export_presets() -> ConfigFile:
	var presets_path := "res://export_presets.cfg"
	if not FileAccess.file_exists(presets_path):
		_fail(OP_ERROR_EXPORT_PRESETS_NOT_FOUND, "project has no export_presets.cfg; no export presets are defined")
		return null
	var config := ConfigFile.new()
	var err := config.load(presets_path)
	if err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to read export_presets.cfg: " + error_string(err))
		return null
	return config


# The export-preset sections of an export_presets.cfg, in file order, each as
# {"section": "preset.N", "index": N}. A preset is stored as a "preset.N" section
# with a sibling "preset.N.options" section; only the bare "preset.N" is a preset,
# so the ".options" companions are filtered out. The index is the preset's N, the
# stable 0-based position the file assigns it.
func _export_preset_sections(config: ConfigFile) -> Array:
	var sections: Array = []
	for section in config.get_sections():
		if not section.begins_with("preset."):
			continue
		var rest := section.substr("preset.".length())
		if not rest.is_valid_int():
			continue  # skip "preset.N.options" and any non-numeric suffix
		sections.append({"section": section, "index": int(rest)})
	return sections


# Summarize one export preset for the listing: its index/name/platform plus
# whether it is marked runnable. Read straight from the ConfigFile, never running
# an export. Missing keys degrade to safe defaults so a hand-edited file still
# lists rather than crashing.
func _export_preset_summary(config: ConfigFile, section: String, index: int) -> Dictionary:
	return {
		"index": index,
		"name": String(config.get_value(section, "name", "")),
		"platform": String(config.get_value(section, "platform", "")),
		"runnable": bool(config.get_value(section, "runnable", false)),
	}


# The export-templates version directory name for the running engine, e.g.
# "4.6.stable" (4.6.0) or "4.6.3.stable" (4.6.3) — major.minor[.patch].status,
# matching how the editor names the per-version templates folder under
# <data_dir>/<godot-dir>/export_templates/. The patch component is OMITTED when it
# is 0 — exactly as Engine.get_version_info()'s version string does (engine.cpp) and
# as the official export-template archives are named — so a .0 release resolves to
# "<major>.<minor>.<status>", not "<major>.<minor>.0.<status>".
# Known limitation (#304): a NON-standard build appends a module/precision suffix to
# the real dir name (FULL_CONFIG — e.g. "4.6.stable.mono" for a C# build, "...double"
# for double precision), which Engine.get_version_info() exposes no field to
# reconstruct. gda targets STANDARD official builds, where that suffix is empty.
func _export_templates_version_dir() -> String:
	var v := Engine.get_version_info()
	var dir := "%d.%d" % [v.major, v.minor]
	if int(v.patch) != 0:
		dir += ".%d" % v.patch
	return "%s.%s" % [dir, v.status]


# Whether the export templates for the running engine version are installed:
# their per-version directory exists under the user data dir's
# <godot-dir>/export_templates/. Headless --script runs have no EditorPaths
# singleton, so the path is derived from OS.get_data_dir() (the same root the editor
# uses) plus the "<godot-dir>/export_templates/<version>" layout, where <godot-dir>
# is the engine's per-platform user-dir name (see _godot_user_dir_name — lowercase
# "godot" on case-sensitive Linux, NOT the macOS/Windows "Godot"). This is the
# readiness signal an agent checks before a future export run (issue #121); it does
# not verify per-platform template files, only that the version's templates are
# present at all.
func _export_templates_installed(version_dir: String) -> bool:
	var templates_root := OS.get_data_dir().path_join(_godot_user_dir_name()).path_join("export_templates")
	return DirAccess.dir_exists_absolute(templates_root.path_join(version_dir))


# The engine's per-platform user-data directory name. macOS and Windows capitalize it
# ("Godot"); every other platform — Linux and the BSDs — uses lowercase "godot", and
# their filesystems are case-sensitive, so the case is load-bearing. Mirrors the C++
# OS::get_godot_dir_name() (its default is lowercase; only macOS/Windows override it),
# which a headless --script run cannot call.
func _godot_user_dir_name() -> String:
	var os_name := OS.get_name()
	return "Godot" if os_name == "macOS" or os_name == "Windows" else "godot"


# resource-uid: resolve a Godot resource UID to/from its resource path in BOTH
# directions against the engine's UID cache (issue #113). Read-only — it only
# queries ResourceUID / ResourceLoader, never mutating the cache or any file.
#
# The cache is the engine's own res://.godot/uid_cache.bin, loaded at startup
# (Main loads it via ResourceUID.load_from_cache for every run, and a non-editor
# run also enables the reverse cache that path->uid resolution reads). So
# resolution needs a project: a projectless headless run has no cache to query,
# refused with project_not_found rather than a misleading "no UID" answer.
#
# Direction is chosen by the target's form:
# - target begins with "uid://" -> resolve uid -> path:
#     text_to_id == INVALID_ID    -> invalid_uid    (malformed uid:// syntax)
#     not has_id                   -> unknown_uid    (valid syntax, not in cache)
#     else get_id_path(id)         -> the res:// path
# - otherwise target is a path -> resolve path -> uid:
#     not ResourceLoader.exists    -> path_not_found (no such resource)
#     get_resource_uid == INVALID  -> no_uid_assigned (exists, but no UID)
#     else id_to_text(id)          -> the uid:// value
# Both directions converge on the same {queried, uid, path} result, so an agent
# always gets both sides of the mapping regardless of which it queried.
func _op_resource_uid(params: Dictionary) -> void:
	_diag("running operation: resource-uid")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "resource uid requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var target := _string_param(params, "target")
	if target.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: target")
		return

	if target.begins_with("uid://"):
		_resolve_uid_to_path(target)
	else:
		_resolve_path_to_uid(target)


# uid -> path: extract the UID value, confirm it is in the cache, and report the
# path it maps to. A malformed uid:// is invalid_uid (text_to_id == INVALID_ID);
# a well-formed UID absent from the cache is unknown_uid (has_id false).
func _resolve_uid_to_path(uid_text: String) -> void:
	var id := ResourceUID.text_to_id(uid_text)
	if id == ResourceUID.INVALID_ID:
		_fail(OP_ERROR_INVALID_UID, "not a valid resource UID: " + uid_text)
		return
	if not ResourceUID.has_id(id):
		_fail(OP_ERROR_UNKNOWN_UID, "UID is not registered in the project's UID cache: " + uid_text)
		return
	_succeed({
		"queried": "uid",
		"uid": uid_text,
		"path": ResourceUID.get_id_path(id),
	})


# path -> uid: confirm the resource exists, then report its assigned UID. A path
# that names no resource is path_not_found; a resource with no UID in the cache
# is no_uid_assigned (get_resource_uid == INVALID_ID).
func _resolve_path_to_uid(path: String) -> void:
	if not ResourceLoader.exists(path):
		_fail(OP_ERROR_PATH_NOT_FOUND, "no resource at path: " + path)
		return
	var id := ResourceLoader.get_resource_uid(path)
	if id == ResourceUID.INVALID_ID:
		_fail(OP_ERROR_NO_UID_ASSIGNED, "resource has no UID assigned in the project's UID cache: " + path)
		return
	_succeed({
		"queried": "path",
		"uid": ResourceUID.id_to_text(id),
		"path": path,
	})


# project-info: report core project metadata — name, main scene, viewport size,
# and the engine version — as typed JSON (issue #111, the project-group tracer's
# read half). Reads ProjectSettings, which the engine populates from project.godot
# at startup; the engine version comes from Engine.get_version_info(), the same
# source gda info reports. The viewport/main-scene settings are read WITH A DEFAULT
# so a new project that never wrote them still reports a value (a fresh Godot 4
# project has no explicit main_scene and inherits the built-in viewport size)
# rather than failing.
#
# project-info needs a project: ProjectSettings without a resolved project would
# report only the engine's bare defaults, not the agent's project, so a projectless
# run is refused with project_not_found rather than returning a misleading result.
# Like every --project op it runs the project's autoloads at engine startup (#61,
# ADR-0009) — reading settings is a state-read at the operation level (it never
# instantiates a scene), but the startup autoload execution surface still applies.
func _op_project_info(_params: Dictionary) -> void:
	_diag("running operation: project-info")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project info requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	_succeed({
		"name": String(ProjectSettings.get_setting(PROJECT_NAME_SETTING, "")),
		"main_scene": String(ProjectSettings.get_setting(PROJECT_MAIN_SCENE_SETTING, "")),
		"viewport_width": int(ProjectSettings.get_setting(PROJECT_VIEWPORT_WIDTH_SETTING, 0)),
		"viewport_height": int(ProjectSettings.get_setting(PROJECT_VIEWPORT_HEIGHT_SETTING, 0)),
		"engine_version": Engine.get_version_info(),
	})


# project-get: read one project setting by its full "section/key" name and report
# it as typed JSON (issue #111). The reported `type` is the setting's declared
# Godot type name and `value` its JSON projection — the same {type, value}
# projection node get reports for a node property, so project get / set round-trip
# through the same shape as node get / set. A setting that does not exist is a
# clean unknown_setting error (not a null value), so a typo'd key is distinguished
# from a setting genuinely holding null.
#
# Like project-info it needs a project (project_not_found otherwise) and runs the
# project's autoloads at startup (#61, ADR-0009); reading a setting never
# instantiates a scene, so it is a state-read at the operation level.
func _op_project_get(params: Dictionary) -> void:
	_diag("running operation: project-get")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project get requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var setting := _string_param(params, "setting")
	if setting.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: setting")
		return
	if not ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_UNKNOWN_SETTING, "project setting not found: " + setting)
		return

	var value: Variant = ProjectSettings.get_setting(setting)
	_succeed({
		"setting": setting,
		"type": _type_name(typeof(value)),
		"value": _jsonify(value),
	})


# project-list: enumerate the project's ProjectSettings keys so an agent can
# DISCOVER which settings exist (issue #312) — the list half of the list → get →
# set workflow, since get/set both require you to already know the section/key.
# Each entry reuses the same {setting, type, value} projection project get reports
# (so a listed entry round-trips through project get), plus an is_default flag:
# false when the key is CUSTOMIZED (written in project.godot), true when it is at
# the engine's built-in default.
#
# Scope: by default only customized settings are listed (keeping the default
# output small and agent-useful); include_defaults widens it to the engine's
# built-in defaults too, and a non-empty section restricts to keys whose name
# begins with that section/ prefix — the two compose. Internal engine-bookkeeping
# settings (PROPERTY_USAGE_INTERNAL — features/tags/translation remaps/…) and the
# non-setting properties get_property_list() also returns (the ProjectSettings
# category, the `script` property) are filtered out, so only real ProjectSettings
# keys appear; the has_setting check is what distinguishes a real setting.
#
# Like every --project op it needs a project (project_not_found otherwise) and
# runs the project's autoloads at startup (#61, ADR-0009); enumerating settings
# never instantiates a scene, so it is a state-read at the operation level.
func _op_project_list(params: Dictionary) -> void:
	_diag("running operation: project-list")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project list requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var include_defaults := bool(params.get("include_defaults", false))
	var section := _string_param(params, "section")
	var customized := _customized_settings()

	var names: Array[String] = []
	for prop in ProjectSettings.get_property_list():
		var key := String(prop.get("name", ""))
		# Only entries ProjectSettings tracks as real settings answer has_setting —
		# this drops the category header and the `script` property.
		if not ProjectSettings.has_setting(key):
			continue
		# Internal engine bookkeeping is not an agent-facing setting key.
		if int(prop.get("usage", 0)) & PROPERTY_USAGE_INTERNAL:
			continue
		var is_default := not customized.has(key)
		if is_default and not include_defaults:
			continue
		if not section.is_empty() and not key.begins_with(section):
			continue
		names.append(key)

	# Sort by name so the listing is stable regardless of registration order.
	names.sort()
	var settings: Array = []
	for key in names:
		var value: Variant = ProjectSettings.get_setting(key)
		settings.append({
			"setting": key,
			"type": _type_name(typeof(value)),
			"value": _jsonify(value),
			"is_default": not customized.has(key),
		})

	_succeed({"settings": settings})


# The set of project setting names CUSTOMIZED in res://project.godot — the keys
# actually written there, as opposed to the engine's built-in defaults. Read by
# parsing project.godot with ConfigFile (the engine exposes no get_initial_value
# binding to compare a current value against its default): each [section] key
# becomes the full "section/key" setting name (a sectionless key like
# config_version maps to its bare name, harmlessly — it is not a real setting).
# project list reports is_default=false for these keys and true for the rest.
func _customized_settings() -> Dictionary:
	var customized := {}
	var cfg := ConfigFile.new()
	if cfg.load("res://project.godot") != OK:
		return customized
	for section in cfg.get_sections():
		for key in cfg.get_section_keys(section):
			var name := key if section.is_empty() else section + "/" + key
			customized[name] = true
	return customized


# project-set: write one project setting, coercing the CLI string value to the
# setting's DECLARED Godot type, then persist project.godot (issue #111, the write
# half — verifiable via project get). The declared type is read off the setting's
# CURRENT value (typeof), exactly as node set reads it off the node's property
# list, and the value is coerced with the SAME shared _coerce_value rules (#55):
# an uncoercible value is a clean uncoercible_value error, leaving project.godot
# untouched. set only writes a setting that already exists — an unknown key is
# unknown_setting, not a silent create — so the type to coerce to is always known.
#
# Persistence: ProjectSettings.set_setting mutates the in-memory settings, and
# ProjectSettings.save() writes them back to res://project.godot. A failed save is
# save_failed. Like every --project op it runs the project's autoloads at
# startup (#61, ADR-0009); the set itself never instantiates a scene.
func _op_project_set(params: Dictionary) -> void:
	_diag("running operation: project-set")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project set requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var setting := _string_param(params, "setting")
	if setting.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: setting")
		return
	if not ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_UNKNOWN_SETTING, "project setting not found: " + setting
				+ " — project set edits an existing setting; it never creates one")
		return

	var current_value: Variant = ProjectSettings.get_setting(setting)
	var declared_type := typeof(current_value)
	var raw_value := _string_param(params, "value")
	var coerced: Variant = _coerce_value(raw_value, declared_type, current_value)
	if coerced == null:
		_fail(OP_ERROR_UNCOERCIBLE_VALUE, "cannot coerce value " + raw_value.c_escape()
				+ " to " + _type_name(declared_type) + " for project setting " + setting)
		return

	ProjectSettings.set_setting(setting, coerced)
	var save_err := ProjectSettings.save()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to save project settings after setting "
				+ setting + ": " + error_string(save_err))
		return

	# Read the value back off ProjectSettings before reporting — it now holds the
	# coerced value in its canonical form, the same projection project get reports,
	# so a set round-trips through a get.
	var stored_value: Variant = _jsonify(ProjectSettings.get_setting(setting))
	_succeed({
		"setting": setting,
		"type": _type_name(declared_type),
		"value": stored_value,
	})


# project-add-autoload: register an autoload singleton (name -> script/scene path)
# under the autoload/<name> section of project.godot, then persist (issue #119).
# The value is stored in the ENABLED-singleton form — the res:// path with a
# leading "*" — which is the normal, globally-accessible autoload gda writes, the
# same value a `project get autoload/<name>` reads back so an add round-trips
# through a get.
#
# Failure modes use existing registered codes: an empty name or path is
# invalid_path; a name already registered is already_exists (add never silently
# overwrites — use remove + add to replace); a target file that does not exist is
# path_not_found; a failed save is save_failed. Like every --project op it runs
# the project's autoloads at startup (#61, ADR-0009); the registration itself
# never instantiates the autoload.
func _op_project_add_autoload(params: Dictionary) -> void:
	_diag("running operation: project-add-autoload")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project add-autoload requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var autoload_name := _string_param(params, "name")
	if autoload_name.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: name")
		return
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return

	var setting := AUTOLOAD_SETTING_PREFIX + autoload_name
	if ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_ALREADY_EXISTS, "autoload already registered: " + autoload_name
				+ " — add-autoload never overwrites; remove it first to replace it")
		return
	if not (FileAccess.file_exists(path) or ResourceLoader.exists(path)):
		_fail(OP_ERROR_PATH_NOT_FOUND, "autoload target does not exist: " + path)
		return

	var stored_path := AUTOLOAD_ENABLED_PREFIX + path
	ProjectSettings.set_setting(setting, stored_path)
	var save_err := ProjectSettings.save()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to save project settings after registering autoload "
				+ autoload_name + ": " + error_string(save_err))
		return

	_succeed({
		"name": autoload_name,
		"path": stored_path,
	})


# project-remove-autoload: unregister an autoload singleton by name (clearing the
# autoload/<name> section), then persist project.godot (issue #119). An autoload
# that is not registered is a clean unknown_setting error — the same code
# `project get` of a missing setting reports, since an autoload IS a project
# setting — not a silent no-op, so a typo'd name is distinguished from a genuine
# removal. A failed save is save_failed.
func _op_project_remove_autoload(params: Dictionary) -> void:
	_diag("running operation: project-remove-autoload")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project remove-autoload requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var autoload_name := _string_param(params, "name")
	if autoload_name.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: name")
		return

	var setting := AUTOLOAD_SETTING_PREFIX + autoload_name
	if not ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_UNKNOWN_SETTING, "autoload not registered: " + autoload_name)
		return

	# Clearing the setting (assigning null) removes it from ProjectSettings, so it
	# is dropped from project.godot on save rather than persisted as an empty key.
	ProjectSettings.set_setting(setting, null)
	var save_err := ProjectSettings.save()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to save project settings after removing autoload "
				+ autoload_name + ": " + error_string(save_err))
		return

	_succeed({
		"name": autoload_name,
	})


# Resolve one --key token to a Godot keycode (issue #380). A base-10 integer
# spelling is taken as a raw keycode and must be positive; anything else is
# looked up as a Godot key NAME via OS.find_keycode_from_string (e.g. "J",
# "Space", "Escape"). Returns KEY_NONE (0) when the token is unresolvable —
# unambiguous as a failure signal because no valid keycode is 0 or negative —
# which the caller reports as the registered invalid_key error naming the token.
func _resolve_input_keycode(token: String) -> int:
	var trimmed := token.strip_edges()
	if trimmed.is_valid_int():
		var keycode := trimmed.to_int()
		return keycode if keycode > 0 else KEY_NONE
	return OS.find_keycode_from_string(trimmed)


# project-add-input-action: register an InputMap action under input/<name> with
# one or more keyboard key bindings, then persist project.godot (issue #380).
#
# The stored value is the InputMap Dictionary shape — {deadzone, events} with
# real InputEventKey Objects, deadzone first (Godot's own key order) — set via
# ProjectSettings.set_setting and serialized by ProjectSettings.save() (the
# engine's own var_to_str form). gda never hand-builds the Object(InputEventKey,
# …) string, so the persisted entry is byte-equivalent to a hand-authored one.
#
# Failure modes use registered codes: an empty name is invalid_path (the
# missing-required-param convention the autoload ops set); malformed keys /
# deadzone / physical params are invalid_params; an action name already present
# is already_exists (add never silently clobbers — remove first to replace).
# NOTE: the engine registers the built-in ui_* actions (input/ui_accept, …) as
# ProjectSettings defaults, so has_setting answers true for them and adding e.g.
# ui_accept reports already_exists by design. An unresolvable key token is
# invalid_key (nothing saved); a failed save is save_failed.
func _op_project_add_input_action(params: Dictionary) -> void:
	_diag("running operation: project-add-input-action")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project add-input-action requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var action_name := _string_param(params, "name")
	if action_name.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: name")
		return
	# Defensive params reads: the params arrive as arbitrary JSON, so a wrong
	# shape surfaces as a structured failure rather than a runtime error.
	var raw_keys: Variant = params.get("keys")
	if not (raw_keys is Array) or (raw_keys as Array).is_empty():
		_fail(OP_ERROR_INVALID_PARAMS, "keys must be a non-empty array of key names or keycodes")
		return
	var raw_deadzone: Variant = params.get("deadzone", 0.5)
	if not (raw_deadzone is float or raw_deadzone is int):
		_fail(OP_ERROR_INVALID_PARAMS, "deadzone must be a number in 0..1")
		return
	var deadzone := float(raw_deadzone)
	var physical := bool(params.get("physical", false))

	var setting := INPUT_SETTING_PREFIX + action_name
	if ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_ALREADY_EXISTS, "input action already registered: " + action_name
				+ " — add-input-action never overwrites; remove it first to replace it")
		return

	# Resolve every key token before touching ProjectSettings, so a bad token
	# fails the whole add cleanly with nothing saved. `events` stays an UNTYPED
	# Array: a typed Array[InputEventKey] would serialize with an
	# `Array[InputEventKey](...)` annotation, not the plain `[Object(...)]` form
	# the editor writes — untyped keeps the persisted entry byte-equivalent.
	var events := []
	var reported_events := []
	for raw_token in (raw_keys as Array):
		if not (raw_token is String):
			_fail(OP_ERROR_INVALID_PARAMS, "keys must be a non-empty array of key names or keycodes")
			return
		var token: String = raw_token
		var keycode := _resolve_input_keycode(token)
		if keycode == KEY_NONE:
			_fail(OP_ERROR_INVALID_KEY, "cannot resolve key to a Godot keycode: " + token)
			return
		var event := InputEventKey.new()
		# Match from ANY device, the editor's convention (InputMap::ALL_DEVICES,
		# -1): InputMap matching filters on device, and a real keyboard event
		# carries DEVICE_ID_KEYBOARD (16), so the InputEventKey.new() default of
		# device 0 would never match a physical key press.
		event.device = -1
		# --physical binds the keyboard POSITION (physical_keycode) instead of
		# the layout symbol (keycode) — set only the requested one, exactly as
		# the editor's "Physical" toggle does, never both.
		if physical:
			event.physical_keycode = keycode as Key
		else:
			event.keycode = keycode as Key
		events.append(event)
		reported_events.append({
			"kind": "key",
			"key": token,
			"keycode": keycode,
			"physical": physical,
		})

	# deadzone first — the key order Godot itself writes for an input action.
	ProjectSettings.set_setting(setting, {"deadzone": deadzone, "events": events})
	var save_err := ProjectSettings.save()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to save project settings after registering input action "
				+ action_name + ": " + error_string(save_err))
		return

	_succeed({
		"name": action_name,
		"deadzone": deadzone,
		"events": reported_events,
	})


# project-remove-input-action: unregister an InputMap action by name (clearing
# the input/<name> setting), then persist project.godot (issue #380). An action
# that is not registered is a clean unknown_setting error — the same code
# `project get` of a missing setting reports, since an input action IS a project
# setting — not a silent no-op. A failed save is save_failed.
func _op_project_remove_input_action(params: Dictionary) -> void:
	_diag("running operation: project-remove-input-action")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project remove-input-action requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var action_name := _string_param(params, "name")
	if action_name.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: name")
		return

	var setting := INPUT_SETTING_PREFIX + action_name
	if not ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_UNKNOWN_SETTING, "input action not registered: " + action_name)
		return

	# Clearing the setting (assigning null) removes it from ProjectSettings, so it
	# is dropped from project.godot on save rather than persisted as an empty key.
	ProjectSettings.set_setting(setting, null)
	var save_err := ProjectSettings.save()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to save project settings after removing input action "
				+ action_name + ": " + error_string(save_err))
		return

	_succeed({
		"name": action_name,
	})


# Extract a .gdshader's declared shader_type from its raw source by lightweight
# line-by-line parsing — never compiling the shader (issue #30). Null when absent.
# A .gdshader leads with `shader_type <type>;`, after optional blank/comment
# lines; scan that header, capture the first shader_type, and stop at the first
# real statement so a shader_type-shaped token deeper in the body is never
# mistaken for the declaration.
func _shader_metadata(source: String) -> Variant:
	for raw_line in source.split("\n"):
		var line := raw_line.strip_edges()
		if line.is_empty() or line.begins_with("//"):
			continue
		if line.begins_with("shader_type "):
			# Drop the trailing ';' and any inline comment, keep the first token.
			var rest := line.substr("shader_type ".length())
			var semicolon := rest.find(";")
			if semicolon != -1:
				rest = rest.substr(0, semicolon)
			return _first_token(rest)
		# The first real line past the header: no shader_type can legally appear
		# after it, so stop scanning.
		break
	return null


# Read a text asset's source back as RAW TEXT, disambiguating an empty file from
# an unreadable one — the same trick as _read_script_source. Shared by the shader
# get/set ops; `noun` names the asset in the failure message.
func _read_text_file(path: String, noun: String) -> Variant:
	var source := FileAccess.get_file_as_string(path)
	if source.is_empty():
		var open_err := FileAccess.get_open_error()
		if open_err != OK:
			_fail(OP_ERROR_PATH_NOT_FOUND, noun + " file could not be read: " + path
					+ ": " + error_string(open_err))
			return null
	return source


# Write `source` to a text asset file as RAW TEXT, reporting both failure modes
# as save_failed — the generic twin of _write_script_file (which names "script"
# in its diagnostic). Returns true on a clean write, or false after recording the
# failure (the caller must stop). `noun` names the asset in the diagnostic.
func _write_text_file(path: String, source: String, noun: String) -> bool:
	var write_err := _atomic_write_text(path, source)
	if write_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message(noun, path, write_err))
		return false
	return true


# --- project static-analysis reads (issue #116) -----------------------------
#
# Four read-only, project-wide reads, all backed by a SINGLE static project scan
# (_scan_project). The scan reads files as TEXT — it parses each .tscn/.tres for
# its [ext_resource path="..."] entries and each .gd for its preload/load/extends
# references — and never instantiates a scene or loads/compiles a script (the
# read trust boundary of issue #30). Reads still run under --project, so the
# engine constructs the project's autoloads at startup before _initialize (the
# residual project-code execution of issue #61); the scan itself adds none.
#
# All four share one reference graph so they stay consistent (acceptance
# criterion): find-references reports the incoming references of one target;
# dependencies reports the outgoing references of every scene/resource;
# find-unused-resources reports the resources with no incoming reference (and not
# an entry point). A resource is "unused" exactly when find-references for it
# would return empty — the same graph, one truth.


# project-find-references: find every project file that references the target — a
# resource res:// path, or a script class_name (issue #116). Walks the project's
# res:// tree, parsing each file's references as text (no instantiation), and
# reports each referencing site (path + kind + matched context). A target nothing
# references is a SUCCESSFUL empty result, not a failure.
func _op_project_find_references(params: Dictionary) -> void:
	_diag("running operation: project-find-references")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project find-references requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var target := _string_param(params, "target")
	if target.is_empty():
		_fail(OP_ERROR_INVALID_TARGET, "missing required param: target")
		return

	# Resolve the target to the set of strings a reference can name it by. A
	# res:// path names a resource directly; a class_name names both the class
	# token (used in .gd as `extends Name` / type annotations) AND the script
	# path it resolves to (used as an ext_resource/preload). A bare token that is
	# neither a res:// path nor a class_name the unified resolver resolves to a .gd
	# (ADR-0032) is rejected: a filesystem path (or a typo) could never appear in a
	# res://-addressed reference, so scanning for it would only ever return a
	# misleading empty result.
	var target_paths := {}  # res:// paths a reference may name the target by
	var target_class := ""  # class_name token a .gd reference may name it by
	if target.begins_with("res://"):
		target_paths[target] = true
	else:
		# Resolve the class_name through the SAME unified resolver node add /
		# resource create use (ADR-0032), so find-references and resource create
		# agree on whether a class resolves in an editor-never-opened project, and
		# a class_name declared in more than one .gd is the shared ambiguous error.
		var resolution := _resolve_project_class_script(target)
		match resolution["status"]:
			"resolved":
				target_class = target
				target_paths[resolution["path"]] = true
			"ambiguous":
				_fail(OP_ERROR_AMBIGUOUS_CLASS_NAME, _ambiguous_class_name_message(target, resolution["paths"]))
				return
			_:
				_fail(OP_ERROR_INVALID_TARGET, "find-references target is not a res:// path, and no .gd script declares class_name " + target + " (check for a misspelled name): " + target)
				return

	var paths: Array[String] = []
	_collect_resource_paths("res://", paths)
	paths.sort()

	var references: Array = []
	for path in paths:
		_collect_references_from(path, target_paths, target_class, references)
	# Project-level references (autoloads, the main scene) live in
	# project.godot, not in a scanned file — add them from ProjectSettings.
	_collect_project_level_references(target_paths, references)

	_succeed({
		"target": target,
		"references": references,
	})


# project-dependencies: map every scene/resource in the project to the resources
# it references — its outgoing [ext_resource] / preload references (issue #116).
# A scene/resource with no external references is reported with an empty
# depends_on, not dropped.
func _op_project_dependencies(_params: Dictionary) -> void:
	_diag("running operation: project-dependencies")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project dependencies requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var paths: Array[String] = []
	_collect_resource_paths("res://", paths)
	paths.sort()

	var dependencies: Array = []
	for path in paths:
		# Only resources that can declare ext_resource dependencies (.tscn/.tres)
		# and scripts (.gd, via preload/load) are reported as dependency sources;
		# a leaf asset (an image) has no outgoing references to map.
		if not _has_outgoing_references(path):
			continue
		var depends_on := _outgoing_references_of(path)
		dependencies.append({
			"path": path,
			"depends_on": depends_on,
		})

	_succeed({"dependencies": dependencies})


# project-find-unused-resources: resources nothing references (issue #116). Built
# on the SAME reference graph as find-references/dependencies (acceptance
# criterion): a resource is unused exactly when no other file references it AND it
# is not a project entry point (the main scene, or an autoload's script/scene).
# Scripts (.gd) are excluded from the "unused resource" report — an unreferenced
# script is dead CODE, a different concern from an unused resource asset, and a
# project's scripts are routinely referenced only dynamically; reporting them
# would be noise. .tscn scenes and .tres/asset resources are the resources this
# reports.
func _op_project_find_unused_resources(_params: Dictionary) -> void:
	_diag("running operation: project-find-unused-resources")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project find-unused-resources requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var paths: Array[String] = []
	_collect_resource_paths("res://", paths)
	paths.sort()

	# Build the set of every res:// path that ANY file references — the union of
	# all outgoing references across the project, the exact graph find-references
	# reads one target at a time. A path absent from this set has zero incoming
	# references (find-references would return empty for it), the consistency the
	# issue requires.
	var referenced := {}
	for path in paths:
		for dep in _outgoing_references_of(path):
			referenced[dep["path"]] = true
	# Project-level entry points are "referenced" too, so they are never reported
	# unused: the main scene and the autoloads are entered directly, not via a
	# file reference.
	for entry in _project_entry_points():
		referenced[entry] = true

	var unused: Array = []
	for path in paths:
		# A script is dead CODE, not an unused resource asset (see the op note).
		if _is_script_path(path):
			continue
		if not referenced.has(path):
			unused.append(path)

	_succeed({"unused": unused})


# project-statistics: file/line counts, autoloads, plugins (issue #116). Counts
# every file under res:// (skipping the engine's .godot cache) by extension; sums
# line counts for text files (binary assets count as files but contribute no
# lines). Autoloads and plugins are read from ProjectSettings — never executed.
func _op_project_statistics(_params: Dictionary) -> void:
	_diag("running operation: project-statistics")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project statistics requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var paths: Array[String] = []
	_collect_all_file_paths("res://", paths)
	paths.sort()

	var total_files := 0
	var total_lines := 0
	var by_ext := {}  # extension -> {"files": int, "lines": int}
	var scene_count := 0
	var script_count := 0
	var resource_count := 0
	for path in paths:
		total_files += 1
		var ext := path.get_extension().to_lower()
		if not by_ext.has(ext):
			by_ext[ext] = {"files": 0, "lines": 0}
		by_ext[ext]["files"] += 1
		var lines := _count_lines(path)
		by_ext[ext]["lines"] += lines
		total_lines += lines
		match ext:
			"tscn":
				scene_count += 1
			"gd":
				script_count += 1
			"png", "jpg", "jpeg", "webp", "svg", "ogg", "wav", "mp3", "ttf", "otf", "import", "godot", "cfg":
				# import sidecars, the project file, and binary/asset files are not
				# "resource" files in the .tres sense; they still count as files.
				pass
			_:
				resource_count += 1

	var extensions: Array = []
	var ext_keys := by_ext.keys()
	ext_keys.sort()
	for ext in ext_keys:
		extensions.append({
			"extension": ext,
			"files": by_ext[ext]["files"],
			"lines": by_ext[ext]["lines"],
		})

	_succeed({
		"total_files": total_files,
		"total_lines": total_lines,
		"by_extension": extensions,
		"autoloads": _project_autoloads(),
		"plugins": _project_plugins(),
		"scene_count": scene_count,
		"script_count": script_count,
		"resource_count": resource_count,
	})


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
func _resolve_project_class_script(class_token: String) -> Dictionary:
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
# the root cache — reusing the shared recursive walker (_collect_resource_paths,
# which already enumerates .gd among the graph resources) — and parses each .gd's
# class_name from raw source with the existing never-compiled parser
# (_script_metadata). A class_name declared in more than one .gd maps to multiple
# paths (sorted, so an ambiguous_class_name error is deterministic regardless of
# traversal order). Runs NO project code.
func _project_class_name_index() -> Dictionary:
	if _project_class_index_built:
		return _project_class_index
	var paths: Array[String] = []
	_collect_resource_paths("res://", paths)
	for path in paths:
		if not _is_script_path(path):
			continue
		# get_file_as_string returns "" for an unreadable OR empty .gd; either way
		# it declares no class_name, so it simply contributes nothing to the index.
		var meta := _script_metadata(FileAccess.get_file_as_string(path))
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
func _ambiguous_class_name_message(class_token: String, paths: Array) -> String:
	return "class_name " + class_token + " is declared in more than one script, so it cannot be resolved to a single script; declare it in exactly one .gd. Conflicting scripts: " + ", ".join(PackedStringArray(paths))


# Whether a res:// walk descends into this child DIRECTORY. The ONE owner of the
# exclusion decision: every walk over the project tree (scripts, scenes, graph
# resources, all files) asks this and nothing else, so the rule cannot drift
# between them and a new walk inherits it by calling this.
#
# The comparison is the full path, never the directory NAME, because a `.godot`
# deeper in the tree is not this project's engine cache. It is usually authored
# content (an addon vendoring a sample project, a fixture tree), and excluding it
# hid real scripts from `script list` and let `script validate --all` report a
# valid aggregate for a project holding an invalid script (#663 review). Sometimes
# it is a vendored sub-project's own cache instead, whose artefacts then count in
# `project statistics` and `find-unused-resources` — accepted deliberately, since
# nothing in the path tells the two apart and a false-valid aggregate is worse.
#
# Three of the four walks once compared the NAME, so one project answered two
# ways: `script list` reported a script `project statistics` counted as zero
# (#712). One decision, one site — that is what keeps them in agreement.
#
# The test is LEXICAL and stays that way here: it does not resolve filesystem
# targets, so an alias that leads to the root cache is descended into, and a
# symlink cycle is descended until the OS path limit stops it. Symlink policy for
# the res:// walk is undecided and tracked in #760 — do not decide half of it
# in this predicate.
func _should_descend(child: String) -> bool:
	return child != ENGINE_CACHE_DIR


# Recursively collect every RESOURCE-bearing file under res:// — the files that
# can carry references (.tscn/.tres scenes & resources, .gd scripts) AND the leaf
# asset resources (everything else except import sidecars, the project file, and
# the .godot cache). Mirrors _collect_scene_paths: hidden entries enumerated,
# navigational entries off, directory descent decided by _should_descend. This is
# the universe the reference graph, find-unused and the class_name index range
# over.
func _collect_resource_paths(dir_path: String, out: Array[String]) -> void:
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return
	dir.include_hidden = true
	dir.list_dir_begin()
	var entry := dir.get_next()
	while not entry.is_empty():
		var child := dir_path.path_join(entry)
		if dir.current_is_dir():
			if _should_descend(child):
				_collect_resource_paths(child, out)
		elif _is_graph_resource_path(child):
			out.append(child)
		entry = dir.get_next()
	dir.list_dir_end()


# Recursively collect EVERY file under res:// (descending per _should_descend)
# for the statistics counts — unlike _collect_resource_paths this keeps import
# sidecars, project.godot and every asset, since statistics counts all files. The
# two walks therefore range over DIFFERENT universes under the same exclusion.
func _collect_all_file_paths(dir_path: String, out: Array[String]) -> void:
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return
	dir.include_hidden = true
	dir.list_dir_begin()
	var entry := dir.get_next()
	while not entry.is_empty():
		var child := dir_path.path_join(entry)
		if dir.current_is_dir():
			if _should_descend(child):
				_collect_all_file_paths(child, out)
		else:
			out.append(child)
		entry = dir.get_next()
	dir.list_dir_end()


# Whether a path names a file the reference graph / find-unused treat as a
# resource: a scene, a resource, a script, or a leaf asset — anything except the
# import sidecars and the project file the .godot cache and the engine own. Kept
# deliberately inclusive so an asset (an image, a font) referenced by a scene is
# itself a node in the graph and a candidate for find-unused. Distinct from the
# resource group's _is_resource_path (a strict .tres check): this is the project
# scan's graph-eligibility test, hence the separate name.
func _is_graph_resource_path(path: String) -> bool:
	var ext := path.get_extension().to_lower()
	if ext == "import" or ext == "godot" or ext == "cfg" or ext == "uid":
		return false
	return not ext.is_empty()


# Whether this file can declare OUTGOING references (so dependencies reports it as
# a source row): a scene/resource (.tscn/.tres, via [ext_resource]) or a script
# (.gd, via preload/load/extends). A leaf asset declares none.
func _has_outgoing_references(path: String) -> bool:
	var ext := path.get_extension().to_lower()
	return ext == "tscn" or ext == "tres" or ext == "gd"


# The outgoing references of one file as a list of {path, kind} entries, in the
# order they appear, de-duplicated. A .tscn/.tres yields its [ext_resource]
# paths; a .gd yields its preload/load/extends-by-path references. The referenced
# path is always a res:// path (a relative .gd preload is resolved against the
# file's own directory). Reading is pure text — no load/instantiate (issue #30).
func _outgoing_references_of(path: String) -> Array:
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
# .tscn/.tres file — the file's external dependencies. Parsed by text: each
# ext_resource line carries a path="..." attribute (Godot 4 also carries a uid,
# but always the path too). Returns res:// paths in line order.
func _ext_resource_paths(path: String) -> Array[String]:
	var out: Array[String] = []
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		return out
	for line in text.split("\n"):
		var stripped := line.strip_edges()
		if not stripped.begins_with("[ext_resource"):
			continue
		var ref := _quoted_attr(stripped, "path=")
		if not ref.is_empty():
			out.append(ref)
	return out


# A .gd script's outgoing references as {path, kind} entries: preload("res://…")
# and load("res://…") calls (kind preload / load), and an `extends "res://Base.gd"`
# base-class-by-path (kind class_extends). A relative path argument is resolved
# against the script's own directory so it becomes a res:// path comparable to the
# rest of the graph. Parsed by text — the script is never compiled (issue #30).
func _script_outgoing_references(path: String) -> Array:
	var out: Array = []
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		return out
	var base_dir := path.get_base_dir()
	for line in text.split("\n"):
		var stripped := line.strip_edges()
		out.append_array(_script_outgoing_references_in_line(stripped, base_dir))
	return out


# Resolve a reference-path argument to a res:// path: a res:// (or uid://) path is
# already absolute; a relative path is joined onto the referencing file's base
# directory and simplified, so "../shared/util.gd" from res://a/b.gd becomes
# res://shared/util.gd. uid:// references are left as-is (they round-trip through
# Godot's UID system, not the path graph).
func _resolve_ref_path(ref: String, base_dir: String) -> String:
	if ref.begins_with("res://") or ref.begins_with("uid://") or ref.begins_with("user://"):
		return ref
	return base_dir.path_join(ref).simplify_path()


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
func _collect_references_from(path: String, target_paths: Dictionary, target_class: String, references: Array) -> void:
	if not _has_outgoing_references(path):
		return
	var ext := path.get_extension().to_lower()
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		return
	if ext == "tscn" or ext == "tres":
		for line in text.split("\n"):
			var stripped := line.strip_edges()
			if not stripped.begins_with("[ext_resource"):
				continue
			var ref := _quoted_attr(stripped, "path=")
			if target_paths.has(ref):
				references.append({"path": path, "kind": "ext_resource", "context": stripped})
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
func _script_outgoing_references_in_line(stripped: String, base_dir: String) -> Array:
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
			if idx > 0 and _is_identifier_char(stripped[idx - 1]):
				continue
			var arg := _first_quoted_after(stripped, idx + call.length())
			if arg.is_empty():
				continue
			out.append({"path": _resolve_ref_path(arg, base_dir), "kind": marker})
	if stripped.begins_with("extends ") and stripped.find("\"") != -1:
		var ext_arg := _first_quoted_after(stripped, "extends ".length())
		if not ext_arg.is_empty():
			out.append({"path": _resolve_ref_path(ext_arg, base_dir), "kind": "class_extends"})
	return out


# Project-level references to the target that live in project.godot rather than a
# scanned file (issue #116): the main scene (run/main_scene) and the autoloads
# (autoload/*). These reference a resource by path the way a file's ext_resource
# does, so find-references must surface them or the target would look less
# referenced than it is.
func _collect_project_level_references(target_paths: Dictionary, references: Array) -> void:
	var main_scene := _main_scene_path()
	if not main_scene.is_empty() and target_paths.has(main_scene):
		references.append({"path": "project.godot", "kind": "main_scene", "context": "application/run/main_scene=" + main_scene})
	for autoload in _project_autoloads():
		if target_paths.has(autoload["path"]):
			references.append({"path": "project.godot", "kind": "autoload", "context": "autoload/" + autoload["name"] + "=" + autoload["path"]})


# The project entry points — paths that are "reached" without a file reference, so
# find-unused must never flag them: the main scene plus every autoload's path.
func _project_entry_points() -> Array[String]:
	var out: Array[String] = []
	var main_scene := _main_scene_path()
	if not main_scene.is_empty():
		out.append(main_scene)
	for autoload in _project_autoloads():
		out.append(autoload["path"])
	return out


# The project's main scene res:// path, or "" when none is set. Read from
# ProjectSettings — never run.
func _main_scene_path() -> String:
	var value: Variant = ProjectSettings.get_setting("application/run/main_scene", "")
	return String(value)


# The project's autoload singletons as {name, path} entries, read from
# ProjectSettings's autoload/* keys (never executed). The stored value carries a
# leading "*" enable marker for an enabled singleton; it is stripped so the path
# is the bare res:// path the rest of the graph compares against.
func _project_autoloads() -> Array:
	var out: Array = []
	for setting in ProjectSettings.get_property_list():
		var key := String(setting.get("name", ""))
		if not key.begins_with("autoload/"):
			continue
		var autoload_name: String = key.substr("autoload/".length())
		var value := String(ProjectSettings.get_setting(key, ""))
		out.append({"name": autoload_name, "path": value.trim_prefix("*")})
	return out


# The enabled editor plugins' plugin.cfg res:// paths (issue #116). Read from
# editor_plugins/enabled in ProjectSettings; each entry is already a
# res://addons/<name>/plugin.cfg path. Empty when the project enables none.
func _project_plugins() -> Array[String]:
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
func _count_lines(path: String) -> int:
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
func _is_text_extension(ext: String) -> bool:
	return ext in [
		"gd", "tscn", "tres", "godot", "cfg", "import", "gdshader", "gdshaderinc",
		"cs", "json", "txt", "md", "xml", "csv", "ini", "po", "pot", "gdextension",
	]


# The value of a quoted attribute (e.g. path="res://x") in a line, or "" when the
# attribute is absent. `attr` includes the trailing '=' ("path="). Returns the
# text between the first pair of double quotes after the attribute.
func _quoted_attr(line: String, attr: String) -> String:
	var idx := line.find(attr)
	if idx == -1:
		return ""
	return _first_quoted_after(line, idx + attr.length())


# Like _quoted_attr, but matches a full attribute name. This matters for
# ext_resource id="..." because uid="..." also contains the substring "id=".
func _quoted_named_attr(line: String, attr_name: String) -> String:
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
func _first_quoted_after(text: String, from: int) -> String:
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


# Whether a line uses `token` as a WHOLE-WORD identifier — bounded by a non
# identifier character (or the line edge) on both sides — so a class_name match
# is not a false positive on a substring of a longer name (Hero vs HeroSpawner)
# or inside another word. Best-effort static check for class_name references that
# carry no res:// path (extends Name, type annotations, Name.new()).
func _line_uses_token(line: String, token: String) -> bool:
	var from := 0
	while true:
		var idx := line.find(token, from)
		if idx == -1:
			return false
		var before_ok := idx == 0 or not _is_identifier_char(line[idx - 1])
		var after_index := idx + token.length()
		var after_ok := after_index >= line.length() or not _is_identifier_char(line[after_index])
		if before_ok and after_ok:
			return true
		from = idx + 1
	return false


func _is_identifier_char(ch: String) -> bool:
	return ch == "_" or (ch >= "a" and ch <= "z") or (ch >= "A" and ch <= "Z") or (ch >= "0" and ch <= "9")


# Whether an already-stripped .gd line is the `class_name <target>` declaration
# of the find-references target — the definition site, not a reference. Matches
# the same `class_name ` prefix _parse_script_meta keys on, with the first token
# of the remainder equal to the target class (so `class_name HeroSpawner` is not
# treated as Hero's declaration). Lets find-references exclude a class's own
# defining line from its class_reference hits (issue #116 review).
func _is_class_name_declaration_of(line: String, target_class: String) -> bool:
	if not line.begins_with("class_name "):
		return false
	return _first_token(line.substr("class_name ".length())) == target_class


# Whether a path names a scene file in the TEXT form gda authors and reads: a
# .tscn. Only scene-validate asks, because it is the only op whose answer comes
# from the file's own text rather than from the loaded resource — see the refusal
# it raises. Every other scene op keys on loadability instead, so a .scn that
# loads is served there as before.
func _is_scene_path(path: String) -> bool:
	return path.get_extension().to_lower() == "tscn"


# Whether a path names a SCENE FILE in either of the two forms Godot saves one
# under a scene extension: the .tscn text gda reads, or the binary .scn it cannot.
# The composed walk asks this rather than _is_scene_path because the two answers
# it needs are different: what it can descend into, and what it must REPORT as
# unread rather than skip (#721 review). Extension is the engine's own test too —
# ResourceLoader picks a format handler by recognized extension
# (ResourceFormatLoader::recognize_path), not by the type an [ext_resource] line
# declares.
#
# The PATH half of the sub-scene edge rule only: a PackedScene saved into a plain
# .res carries no scene extension, so _is_sub_scene_edge unions this with the
# line's declared type. Read that function for the whole rule.
func _is_scene_reference_path(path: String) -> bool:
	var ext := path.get_extension().to_lower()
	return ext == "tscn" or ext == "scn"


# Whether a path names a script file the script group operates on: a .gd
# (GDScript) file. Script-file addressing is by extension, the same way scene
# addressing keys on .tscn. C# (.cs) is out of scope for now — it needs the .NET
# build of Godot (ADR-0003 targets the standard build) and a dedicated decision.
func _is_script_path(path: String) -> bool:
	return path.get_extension().to_lower() == "gd"


# Clear the script group's addressing boundary for an EXISTING script: the path
# must be a .gd (invalid_path otherwise) and the file must exist on disk
# (path_not_found otherwise). Returns true to proceed, or false after recording
# the failure (the caller must stop). Shared by every op that reads or mutates an
# existing script — get / delete / set / validate / attach — so they all refuse a
# non-.gd target and a missing file identically, rather than operating on it.
func _require_existing_script(path: String) -> bool:
	if not _is_script_path(path):
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


# Extract a GDScript's declared class_name and extends from its raw source by
# lightweight line-by-line parsing — never compiling the script (issue #30).
# Both are null when absent. Only .gd scripts reach here (the entry points reject
# any other extension as invalid_path), so this keys off GDScript syntax alone.
func _script_metadata(source: String) -> Dictionary:
	var class_name_value: Variant = null
	var extends_value: Variant = null
	# class_name and extends, when present, lead a GDScript file: they sit in the
	# header, after the optional annotation lines (@tool, @icon(...), …) and
	# before the first real statement. Scan only that header — skip blanks,
	# comments and annotations, capture the first of each declaration, and STOP at
	# the first line that is neither. Stopping is what keeps a class_name/extends-
	# shaped line deeper in the body (e.g. inside a multiline string) from ever
	# being mistaken for the declaration.
	for raw_line in source.split("\n"):
		var line := raw_line.strip_edges()
		if line.is_empty() or line.begins_with("#") or line.begins_with("@"):
			continue
		if line.begins_with("class_name "):
			if class_name_value == null:
				class_name_value = _first_token(line.substr("class_name ".length()))
			continue
		if line.begins_with("extends "):
			if extends_value == null:
				extends_value = _first_token(line.substr("extends ".length()))
			continue
		# The first real statement past the header: no further class_name/extends
		# declaration can legally appear, so stop scanning.
		break
	return {"class_name": class_name_value, "extends": extends_value}


# The first token of a declaration's remainder — the class_name or base-class
# identifier. A bare identifier drops a trailing inline comment and stops at the
# first whitespace: "Hero # the hero" → "Hero", "Node2D" → "Node2D". The quoted
# base-class-by-path form (extends "res://Base.gd") is kept whole up to its
# closing quote — including any '#' inside the path, which is part of the string,
# not an inline comment.
func _first_token(rest: String) -> Variant:
	var trimmed := rest.strip_edges()
	if trimmed.is_empty():
		return null
	if trimmed.begins_with("\"") or trimmed.begins_with("'"):
		var quote := trimmed[0]
		var close := trimmed.find(quote, 1)
		# An unterminated quote is reported as-is rather than silently truncated.
		return trimmed.substr(0, close + 1) if close != -1 else trimmed
	var comment := trimmed.find("#")
	if comment != -1:
		trimmed = trimmed.substr(0, comment).strip_edges()
	var token := trimmed.split(" ", false)[0]
	return token if not token.is_empty() else null


# Whether this headless process is running against a Godot project. A project
# scan writes the resource UID cache under res://.godot; its presence is the
# marker the engine itself uses, and a projectless --script run (no --path to a
# project dir) does not have it. scene-list needs a real res:// tree to walk.
func _has_project() -> bool:
	return DirAccess.dir_exists_absolute("res://") and FileAccess.file_exists("res://project.godot")


# Recursively collect every .tscn under res:// (issue #54), descending per
# _should_descend. The dot prefix is not part of that test, so a legitimately
# hidden scene (a .hidden.tscn, or one under a dot-prefixed directory) is
# enumerated as promised (issue #54 review). Paths are returned as res:// paths
# so they round-trip into other scene commands.
func _collect_scene_paths(dir_path: String, out: Array[String]) -> void:
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return
	# Hidden entries are off by default; enable them so a .hidden.tscn or a scene
	# under a dot-prefixed directory is enumerated. Navigational entries ('.',
	# '..') stay off, so recursion cannot loop back on itself (issue #54 review).
	dir.include_hidden = true
	dir.list_dir_begin()
	var entry := dir.get_next()
	while not entry.is_empty():
		var child := dir_path.path_join(entry)
		if dir.current_is_dir():
			if _should_descend(child):
				_collect_scene_paths(child, out)
		elif entry.get_extension() == "tscn":
			out.append(child)
		entry = dir.get_next()
	dir.list_dir_end()


# Summarize one .tscn for the listing: its path plus the root node's name/type
# from stored state (no instantiation, issue #30). A file that cannot be loaded
# as a scene still appears, with null root info, rather than being dropped.
func _scene_summary(path: String) -> Dictionary:
	var packed := ResourceLoader.load(path, "PackedScene") as PackedScene
	if packed == null:
		return {"path": path, "root_name": null, "root_type": null}
	var state := packed.get_state()
	if state == null or state.get_node_count() == 0:
		return {"path": path, "root_name": null, "root_type": null}
	var root_fields := _state_node_projection_fields(state, 0)
	var instance_paths := _scene_instance_paths_by_node_path(path)
	if instance_paths.has("."):
		var instance_path := String(instance_paths["."])
		root_fields["instance_path"] = instance_path
		if not root_fields.has("instance_status"):
			root_fields["instance_status"] = _scene_instance_status_for_path(instance_path)
	return {
		"path": path,
		"root_name": String(state.get_node_name(0)),
		"root_type": root_fields["type"],
		"root_instance_path": root_fields.get("instance_path", null),
		"root_instance_status": root_fields.get("instance_status", null),
	}


# Recursively collect every .gd script under res:// (issue #117), descending per
# _should_descend. Hidden entries are enumerated (a .hidden.gd, or a script under
# a dot-prefixed directory) and navigational entries stay off. Paths are returned
# as res:// paths so they round-trip into other script commands.
func _collect_script_paths(dir_path: String, out: Array[String]) -> void:
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return
	dir.include_hidden = true
	dir.list_dir_begin()
	var entry := dir.get_next()
	while not entry.is_empty():
		var child := dir_path.path_join(entry)
		if dir.current_is_dir():
			if _should_descend(child):
				_collect_script_paths(child, out)
		elif entry.get_extension().to_lower() == "gd":
			out.append(child)
		entry = dir.get_next()
	dir.list_dir_end()


# Summarize one .gd for the listing: its path plus the class_name/extends parsed
# from its raw source (no compilation, issue #30 — reading a script must never
# run it). A script whose source declares neither (or could not be read) still
# appears, with null metadata, rather than being dropped.
func _script_summary(path: String) -> Dictionary:
	var meta := _script_metadata(FileAccess.get_file_as_string(path))
	return {
		"path": path,
		"class_name": meta["class_name"],
		"extends": meta["extends"],
	}


# Load the .tscn named by params.path for reading or mutation, validating the
# shared failure ladder: missing param → missing file → not loadable as a
# scene → scene without a root. Returns null after recording the failure.
func _load_scene(params: Dictionary) -> PackedScene:
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return null
	if not FileAccess.file_exists(path):
		_fail(OP_ERROR_PATH_NOT_FOUND, "scene file does not exist: " + path)
		return null
	var packed := ResourceLoader.load(path, "PackedScene") as PackedScene
	if packed == null:
		_fail(OP_ERROR_NOT_A_SCENE, "failed to load as a scene: " + path)
		return null
	var state := packed.get_state()
	if state == null or state.get_node_count() == 0:
		_fail(OP_ERROR_NOT_A_SCENE, "scene declares no root node: " + path)
		return null
	return packed


# The single mutate-entry for the node group (issue #55): load the .tscn,
# instantiate it, and clear the mutation-integrity boundary before any op
# touches the tree, returning the instantiated root (or null after recording
# the failure). Mutation REQUIRES instantiating the scene — only a real node
# tree can be edited and re-packed — which runs the _init of any script
# attached in the scene, so mutating ops execute project code where the read
# ops (issue #30) deliberately do not. Centralising load → instantiate → guard
# here means every current and future mutating op honors the boundary the
# command catalog promises, rather than re-inlining (and risking forgetting)
# the unmaterialized-node check (issue #64). The caller owns root.free().
func _load_for_mutation(params: Dictionary) -> Node:
	var packed: PackedScene = _load_scene(params)
	if packed == null:
		return null  # _load_scene already recorded the failure
	var path := _string_param(params, "path")
	# Capture the staleness token NOW — the instant after _load_scene's
	# ResourceLoader.load read the .tscn, and BEFORE instantiate() (which runs the
	# project's script _init and can take real time, ADR-0009) or any other work.
	# Capturing here rather than after instantiate makes the baseline reflect the
	# file gda actually read, so an external edit landing during instantiate is
	# still caught by _check_unchanged at write time (issue #226; PR #234 review
	# closed this read->capture window). Covers all 8 shared-tail mutating ops.
	_capture_staleness_token(path)
	# Test seam (issue #226): simulate an external edit that lands AFTER the read
	# but DURING instantiate — the window this early capture closes. Gated by the
	# env var, so it is dead code in production (mirrors GDA_TEST_PERTURB_BEFORE_SAVE).
	if OS.has_environment("GDA_TEST_PERTURB_AFTER_LOAD"):
		_test_perturb_target(path)
	# Mutating ops re-pack the host scene after editing the live tree. Instantiate
	# the host as the edited main scene so pre-existing instance children retain
	# their scene-instance state; otherwise the packer diffs them against class
	# defaults and serializes non-canonical `type=` / inherited-property churn.
	var root: Node = packed.instantiate(PackedScene.GEN_EDIT_STATE_MAIN)
	if root == null:
		# The engine returns null for a scene it cannot instantiate at all —
		# e.g. an instanced sub-scene whose resource loads but instantiates to
		# nothing (packed_scene.cpp propagates the nested null). Nothing exists
		# to edit or save, so refuse with the dependency code.
		_fail(OP_ERROR_MISSING_DEPENDENCY, "scene failed to instantiate: " + path
				+ " — an instanced sub-scene is unresolvable or empty; check the scene's dependencies and --project")
		return null
	var unmaterialized := _unmaterialized_node_paths(packed.get_state(), root)
	if not unmaterialized.is_empty():
		root.free()
		_fail(OP_ERROR_MISSING_DEPENDENCY, "scene nodes vanished or degraded on load: "
				+ ", ".join(unmaterialized) + " — re-saving would silently drop or downgrade them; check the scene's dependencies and --project")
		return null
	# Snapshot every node's external script path NOW — the instant after
	# instantiate, before any op-specific load can evict a sibling's script object
	# (issue #164). _repack_and_save re-anchors from this snapshot on the way out.
	_capture_source_attached_scripts(path)
	_capture_external_scripts(root)
	return root


# The single pack-and-save tail: pack `root` into a PackedScene and save it to the
# .tscn at `path`, then free the tree. Returns true on a clean save, or false after
# recording save_failed (the caller must stop). root.free() runs on EVERY path —
# pack failure, save failure, and success alike — so an instantiated scene (the most
# leak-prone object in the mutating ops) is never leaked. Shared by every op whose
# tail packs-and-saves a root: scene create (a freshly-built root) and the mutating
# ops node add / node set / node remove / node duplicate / node move / connect- &
# disconnect-signal / script attach (a re-packed instantiated tree, paired with
# _load_for_mutation). The caller captures any result fields it needs OFF THE TREE
# before calling, as the tree is gone once this returns; for scene create the caller
# also creates any missing parent dirs first, since this tail only packs and saves.
func _repack_and_save(root: Node, path: String) -> bool:
	# Re-anchor every external script captured at load time to the one canonical
	# cached resource for its res:// path BEFORE packing (issue #164). On the
	# editor build gda drives, the text scene saver dedups ext_resources through a
	# PATH-keyed cache (ResourceCache::resource_path_cache), not object identity. A
	# re-attach can leave two distinct in-memory Script objects sharing one res://
	# path: the engine's GDScriptCache upgrades a shallow script to a full one via
	# set_path(take_over=true), which evicts the previously cached object WITHOUT
	# freeing it, so a sibling node still holds the evicted orphan. With an
	# UNIMPORTED script the path string is the only identity (no uid://), so the
	# path-keyed dedup collapses the two same-path objects on save — silently
	# dropping the sibling's `script = ExtResource(...)` line (or re-embedding it as
	# a sub_resource). Re-anchoring repoints every node at the single cache owner
	# for its path, so the saver sees one consistent ext_resource per path.
	#
	# This is the CENTRAL shared-mutation hardening point. Because it runs from the
	# shared pack-and-save tail, it hardens every mutating re-pack op (node
	# add/set/remove/duplicate/move, signal connect/disconnect) — not only `script
	# attach` (issue #164's reported path). That broader reach is correct, not
	# overreach: _reanchor_external_scripts only repoints a node that STILL carries
	# its captured script (siblings preserved); it leaves a node the op
	# intentionally re-scripted to a different non-empty path alone; and it skips
	# nodes that vanished since capture (remove/move). `node add` is covered by
	# test_node_add_preserves_sibling_script_on_repack_when_unimported.
	#
	# Optimistic staleness recheck (issue #226): refuse the write if the .tscn changed
	# on disk since _load_for_mutation read it. Done BEFORE pack/save and after freeing
	# the tree on refusal, so a clobbering write never lands and no scene leaks.
	if not _check_unchanged():
		root.free()
		return false
	if not _validate_scene_script_preload_dependencies(root):
		root.free()
		return false
	_reanchor_external_scripts(root)
	var repacked := PackedScene.new()
	var pack_err := repacked.pack(root)
	if pack_err != OK:
		root.free()
		_fail(OP_ERROR_SAVE_FAILED, "failed to pack scene: " + error_string(pack_err))
		return false
	var save_err := _atomic_save_resource(repacked, path)
	root.free()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message("scene", path, save_err))
		return false
	return true


# {NodePath (root-relative) -> script res:// path} for every node that carried a
# file-backed script when the tree was first instantiated (issue #164). Captured
# by _capture_external_scripts the instant _load_for_mutation finishes
# instantiating — BEFORE any subsequent load (e.g. attach's --script) can run the
# GDScriptCache shallow→full upgrade that evicts a sibling's script object and
# clears its resource_path. Consumed by _reanchor_external_scripts at re-pack
# time, where the orphan's own resource_path is already empty and useless: the
# captured path is the only surviving anchor back to the script the node should
# carry. A single member is safe here — operations.gd is a one-shot process that
# runs exactly one operation, so there is no cross-operation state to leak.
var _captured_external_scripts: Dictionary = {}
var _source_attached_scripts: Dictionary = {}


# --- optimistic staleness guard for headless read-modify-write ops (issue #226) ---
#
# A file-mutating op reads a target (.tscn/.gd/.tres/.gdshader), transforms it, then
# writes it back. If a concurrent external editor (ADR-0018) changes that file on disk
# inside the in-process read->write window, a blind write would CLOBBER the external
# edit. The guard captures a cheap change token (mtime + size) right after the read and
# re-checks it right before the write; a difference is reported as
# file_changed_externally and the write is refused, leaving the external edit intact.
#
# The token is mtime+size, not mtime alone: FileAccess.get_modified_time is
# whole-SECONDS granularity, so a same-second external edit would be invisible to mtime;
# the file size (which an edit almost always changes) catches that case. A single member
# set is safe — operations.gd is a one-shot process running exactly one op — mirroring
# the _captured_external_scripts pattern above. An op that captured no token (a create)
# leaves _staleness_path empty, and _check_unchanged is then a no-op (returns true).
var _staleness_mtime: int = -1
var _staleness_size: int = -1
var _staleness_path: String = ""


# Capture the change token for `path` right after an op reads it. Uses the SAME path
# string the op passed to ResourceLoader.load / FileAccess (no globalize_path), so the
# recheck reads exactly the same file. Size is read via an explicit READ open + length;
# -1 marks an unreadable file (the recheck will still fire if it later becomes readable
# with a different token, which is the conservative outcome).
func _capture_staleness_token(path: String) -> void:
	_staleness_path = path
	_staleness_mtime = int(FileAccess.get_modified_time(path))
	_staleness_size = _file_size(path)


func _file_size(path: String) -> int:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return -1
	var size := file.get_length()
	file.close()
	return int(size)


# Re-check the captured token right before an op writes. Returns true when the file is
# unchanged (or when no token was captured, e.g. a create); returns false AFTER
# recording file_changed_externally when mtime or size differs. The single emission
# point for the guard — every wired op funnels its recheck through here.
func _check_unchanged() -> bool:
	# Production-inert test seam (issue #226): the in-process read->write window is
	# sub-second, so a normal test cannot race a real external edit into it. When this
	# env var is set, perturb the target's SIZE just before the comparison to simulate
	# an external edit landing in the window. Gated by has_environment, so it is dead
	# code in production — runner.py spawns Godot with no env= and never sets this var.
	if OS.has_environment("GDA_TEST_PERTURB_BEFORE_SAVE"):
		_test_perturb_target(_staleness_path)
	if _staleness_path.is_empty():
		return true  # no token captured (e.g. a create) — nothing to compare
	var current_mtime := int(FileAccess.get_modified_time(_staleness_path))
	var current_size := _file_size(_staleness_path)
	if current_mtime != _staleness_mtime or current_size != _staleness_size:
		_fail(OP_ERROR_FILE_CHANGED_EXTERNALLY,
				"target file changed on disk since gda read it (a concurrent editor may have"
				+ " edited it); refusing to overwrite: " + _staleness_path)
		return false
	return true


# Test-only: simulate an external edit landing in the read->write window by appending a
# byte to the target, guaranteeing a SIZE change so the guard fires regardless of mtime
# second-granularity. Reached only through the GDA_TEST_PERTURB_BEFORE_SAVE branch in
# _check_unchanged, so it never runs in production.
func _test_perturb_target(path: String) -> void:
	if path.is_empty():
		return
	var file := FileAccess.open(path, FileAccess.READ_WRITE)
	if file == null:
		return
	file.seek_end()
	file.store_8(10)  # a newline byte — any byte changes the size
	file.close()


# Record {NodePath -> script res:// path} for every node in the freshly
# instantiated tree that carries a file-backed script, so a later load that
# evicts one of those scripts can be undone before re-pack (issue #164). Read off
# the LIVE script object while its resource_path is still intact; a script with
# no resource_path (an embedded/sub-resource script) has no external identity to
# anchor and is skipped. Paths are root-relative (get_path_to) so they survive
# the round-trip to _reanchor_external_scripts regardless of the root's own name.
func _capture_external_scripts(root: Node) -> void:
	_captured_external_scripts = {}
	_capture_external_scripts_into(root, root)


func _capture_external_scripts_into(node: Node, root: Node) -> void:
	var script: Variant = node.get_script()
	if script is Script:
		var script_path: String = (script as Script).resource_path
		if not script_path.is_empty():
			_captured_external_scripts[root.get_path_to(node)] = script_path
	for child in node.get_children():
		_capture_external_scripts_into(child, root)


func _capture_source_attached_scripts(scene_path: String) -> void:
	_source_attached_scripts = _scene_attached_external_scripts(scene_path)


# Repoint every captured node that STILL carries its captured script at the
# SINGLE canonical cached resource for that script's res:// path, so a re-pack/save
# never serializes two distinct in-memory objects under one path (issue #164 root
# cause). For each captured {NodePath -> script_path}: re-load that path with
# CACHE_MODE_REPLACE — which installs one object as the sole ResourceCache owner of
# the path — and set_script it back onto the node, collapsing any evicted-but-alive
# orphan (the second same-path object the GDScriptCache shallow→full upgrade leaves
# behind) onto the canonical one.
#
# Re-anchor ONLY when the node was NOT intentionally re-scripted by the op in
# between. The discriminator is the node's CURRENT script resource_path:
#   - equals the captured path -> still the same script (possibly the corrupted
#     orphan instance); re-anchor to canonicalize.
#   - empty -> the orphan whose set_path(take_over) eviction cleared its path (the
#     exact #164 corruption signature); re-anchor to restore the captured binding.
#   - a DIFFERENT non-empty path -> the op deliberately overwrote this node's
#     script (e.g. script attach replacing one binding with another, issue #132);
#     leave it, or the re-anchor would silently undo the requested change.
# Idempotent: when a node already holds the canonical object, set_script re-binds
# the same resource, a no-op. A node that vanished since capture (a remove/move op
# may have detached or freed it) is skipped — its capture entry is stale.
func _reanchor_external_scripts(root: Node) -> void:
	for node_path: NodePath in _captured_external_scripts:
		var node := root.get_node_or_null(node_path)
		if node == null:
			continue
		var captured_path: String = _captured_external_scripts[node_path]
		var current: Variant = node.get_script()
		if current is Script:
			var current_path: String = (current as Script).resource_path
			if not current_path.is_empty() and current_path != captured_path:
				continue  # op intentionally replaced this node's script — leave it
		var canonical: Resource = ResourceLoader.load(
				captured_path, "Script", ResourceLoader.CACHE_MODE_REPLACE)
		if canonical is Script:
			node.set_script(canonical)


# Validate the executable preload() dependencies that can make GDScript
# compilation fail. This uses a focused lexer rather than the project-reference
# graph's raw line scanner: comments and unrelated string literals must not block
# a valid attach, while a real preload call may split its argument across lines.
func _validate_script_preload_dependencies(script_path: String) -> bool:
	for ref_path in _script_executable_preload_paths(script_path):
		if not ref_path.begins_with("res://"):
			continue
		if FileAccess.file_exists(ref_path):
			continue
		_fail(OP_ERROR_MISSING_DEPENDENCY, "script preload target does not exist: "
				+ ref_path + " (referenced by " + script_path
				+ ") — create the preloaded asset before attaching or saving the script")
		return false
	return true


func _script_executable_preload_paths(script_path: String) -> Array[String]:
	var out: Array[String] = []
	var source := FileAccess.get_file_as_string(script_path)
	if source.is_empty() and FileAccess.get_open_error() != OK:
		return out
	var base_dir := script_path.get_base_dir()
	var index := 0
	while index < source.length():
		var token_index := _find_code_token(source, "preload", index)
		if token_index == -1:
			break
		var after_token := token_index + "preload".length()
		var open_paren := _skip_gdscript_space_and_comments(source, after_token)
		if open_paren >= source.length() or source[open_paren] != "(":
			index = after_token
			continue
		var arg_start := _skip_gdscript_space_and_comments(source, open_paren + 1)
		var literal := _quoted_string_literal_at(source, arg_start)
		if not bool(literal.get("ok", false)):
			index = open_paren + 1
			continue
		out.append(_resolve_ref_path(String(literal["value"]), base_dir))
		index = int(literal["end"])
	return out


func _find_code_token(source: String, token: String, from: int) -> int:
	var index := from
	while index < source.length():
		var ch := source[index]
		if ch == "#":
			index = _skip_gdscript_line_comment(source, index)
			continue
		if ch == "\"" or ch == "'":
			index = _skip_quoted_string_literal(source, index)
			continue
		if source.substr(index, token.length()) == token:
			var before_ok := (
					index == 0
					or (not _is_identifier_char(source[index - 1]) and source[index - 1] != ".")
			)
			var after_index := index + token.length()
			var after_ok := (
					after_index >= source.length()
					or not _is_identifier_char(source[after_index])
			)
			if before_ok and after_ok:
				return index
		index += 1
	return -1


func _skip_gdscript_space_and_comments(source: String, from: int) -> int:
	var index := from
	while index < source.length():
		var ch := source[index]
		if ch == " " or ch == "\t" or ch == "\r" or ch == "\n":
			index += 1
			continue
		if ch == "#":
			index = _skip_gdscript_line_comment(source, index)
			continue
		break
	return index


func _skip_gdscript_line_comment(source: String, from: int) -> int:
	var index := from
	while index < source.length() and source[index] != "\n":
		index += 1
	return index


func _skip_quoted_string_literal(source: String, from: int) -> int:
	var literal := _quoted_string_literal_at(source, from)
	return int(literal["end"])


func _quoted_string_literal_at(source: String, from: int) -> Dictionary:
	if from >= source.length():
		return {"ok": false, "value": "", "end": source.length()}
	var quote := source[from]
	if quote != "\"" and quote != "'":
		return {"ok": false, "value": "", "end": from}
	var triple := quote + quote + quote
	if source.substr(from, 3) == triple:
		var content_start := from + 3
		var triple_end := source.find(triple, content_start)
		if triple_end == -1:
			return {"ok": false, "value": "", "end": source.length()}
		return {
			"ok": true,
			"value": source.substr(content_start, triple_end - content_start),
			"end": triple_end + 3,
		}
	var out := ""
	var index := from + 1
	while index < source.length():
		var ch := source[index]
		if ch == "\\":
			if index + 1 >= source.length():
				return {"ok": false, "value": "", "end": source.length()}
			out += source[index + 1]
			index += 2
			continue
		if ch == quote:
			return {"ok": true, "value": out, "end": index + 1}
		out += ch
		index += 1
	return {"ok": false, "value": "", "end": source.length()}


# Mutating scene ops save the current instantiated tree. Validate every
# file-backed script that would still be saved before packing, so a script whose
# missing preload left only engine stderr cannot turn into a clean success.
func _validate_scene_script_preload_dependencies(root: Node) -> bool:
	for node_path: NodePath in _source_attached_scripts:
		var node := root.get_node_or_null(node_path)
		if node == null:
			continue  # the op intentionally removed this node
		var source_path: String = _source_attached_scripts[node_path]
		var current: Variant = node.get_script()
		if current is Script:
			var current_path: String = (current as Script).resource_path
			if not current_path.is_empty() and current_path != source_path:
				continue  # the op intentionally replaced this node's script
		if not _validate_script_preload_dependencies(source_path):
			return false
	return _validate_node_script_preload_dependencies(root)


func _validate_node_script_preload_dependencies(node: Node) -> bool:
	var script := node.get_script() as Script
	if script != null:
		var script_path := script.resource_path
		if not script_path.is_empty() and not _validate_script_preload_dependencies(script_path):
			return false
	for child in node.get_children():
		if not _validate_node_script_preload_dependencies(child):
			return false
	return true


# The source scene's file-backed script bindings as {root-relative NodePath ->
# script res:// path}. This catches scripts that Godot failed to materialize
# because a preload target was missing: the node may still exist with no script,
# so walking the instantiated tree alone cannot see the dependency.
func _scene_attached_external_scripts(scene_path: String) -> Dictionary:
	var text := FileAccess.get_file_as_string(scene_path)
	if text.is_empty():
		return {}
	var script_resources := _scene_script_ext_resources(text)
	var attached := {}
	var current_node_path := ""
	for line in text.split("\n"):
		var stripped := line.strip_edges()
		if stripped.begins_with("[node "):
			current_node_path = _scene_node_path_from_header(stripped)
			continue
		if current_node_path.is_empty():
			continue
		if not stripped.begins_with("script") or stripped.find("ExtResource(") == -1:
			continue
		var resource_id := _first_quoted_after(stripped, stripped.find("ExtResource("))
		if script_resources.has(resource_id):
			attached[NodePath(current_node_path)] = script_resources[resource_id]
	return attached


func _scene_script_ext_resources(text: String) -> Dictionary:
	var resources := {}
	for line in text.split("\n"):
		var stripped := line.strip_edges()
		if not stripped.begins_with("[ext_resource"):
			continue
		if _quoted_attr(stripped, "type=") != "Script":
			continue
		var resource_id := _quoted_named_attr(stripped, "id")
		var path := _quoted_attr(stripped, "path=")
		if not resource_id.is_empty() and path.begins_with("res://"):
			resources[resource_id] = path
	return resources


func _scene_node_path_from_header(header: String) -> String:
	var name := _quoted_attr(header, "name=")
	if name.is_empty():
		return ""
	var parent := _quoted_attr(header, "parent=")
	if parent.is_empty():
		return "."
	if parent == ".":
		return name
	return parent + "/" + name


# Node paths declared in the scene's state that did not materialize faithfully
# in the instantiated tree (issue #64), in the two modes the engine survives
# silently:
# - vanished: the node is absent — typically an instanced sub-scene whose
#   ext_resource could not be resolved (missing file, or res:// without
#   project context); the instance, its overrides, and its editable marker
#   would all be erased by a re-save.
# - degraded: the node exists but as a substitute class — the declared class
#   was unavailable at instantiate time (e.g. an absent GDExtension/module)
#   and the engine fell back to a placeholder node at the same path; a re-save
#   would rewrite the node under the substitute type.
# Mutation must refuse before saving rather than report success over either
# data loss. Instance nodes and instance-override entries declare no type in
# the state, so only nodes this scene itself declares get the class check.
func _unmaterialized_node_paths(state: SceneState, root: Node) -> Array[String]:
	var unmaterialized: Array[String] = []
	for i in state.get_node_count():
		var state_path := _normalize_state_path(state, i)
		var node := root.get_node_or_null(NodePath(state_path))
		if node == null:
			unmaterialized.append(state_path + " (vanished)")
			continue
		var declared_type := String(state.get_node_type(i))
		if not declared_type.is_empty() and node.get_class() != declared_type:
			unmaterialized.append(state_path + " (declared " + declared_type
					+ ", materialized " + node.get_class() + ")")
	return unmaterialized


# Whether a parent path is in canonical root-relative form — exactly the form
# node list reports: "." for the root, or '/'-joined node names for a
# descendant. Godot's NodePath resolution silently accepts non-canonical forms
# ("A/.." walks back up to the root, "A/" / "A//B" / "A/./B" collapse the
# redundant segment, "A:position" drops the property part — all verified on
# 4.6.3), landing the node somewhere the literal string never named (issue
# #66). Addressing must be exact and round-trippable, so anything
# non-canonical is rejected rather than normalized. Every legal node name
# passes _is_valid_node_name (Godot sanitizes names on assignment with the
# same character set), so this can never reject a path node list reports.
func _is_canonical_parent_path(parent_path: String) -> bool:
	if parent_path == ".":
		return true
	for segment in parent_path.split("/"):
		if not _is_valid_node_name(segment):
			return false
	return true


# Resolve a node path against the scene root. Node-path addressing (issue #53)
# is relative to the scene root: '.' is the root itself, 'Player/Arm' a
# descendant. Only canonical paths resolve (issue #66) — this subsumes
# rejecting absolute paths ('/root/…' opens with an empty segment), which a
# loaded-for-editing tree outside any SceneTree could never serve. Shared by
# node add (its --parent), node get and node set (their --node): one strict
# resolver so every node-group op addresses nodes identically.
func _resolve_node(root: Node, node_path: String) -> Node:
	if not _is_canonical_parent_path(node_path):
		return null
	if node_path == ".":
		return root
	return root.get_node_or_null(NodePath(node_path))


# Record a node-not-found failure for node get / node set, distinguishing the
# two ways resolution can fail the same way node add does for its parent: a
# canonical path that names no node, versus a non-canonical path rejected by
# strict addressing (issue #66) rather than silently resolved elsewhere.
func _fail_node_not_found(node_path: String) -> void:
	if _is_canonical_parent_path(node_path):
		_fail(OP_ERROR_NODE_NOT_FOUND, "node not found in scene: " + node_path)
	else:
		_fail(OP_ERROR_NODE_NOT_FOUND, "non-canonical node path: " + node_path
				+ " — address the node exactly as node list reports it: '.' for the root, 'A/B' for a descendant")


# Like _fail_node_not_found but names which endpoint of a connection failed
# ("source"/"target", issue #57), so an agent knows which node path to fix.
func _fail_node_not_found_labeled(label: String, node_path: String) -> void:
	if _is_canonical_parent_path(node_path):
		_fail(OP_ERROR_NODE_NOT_FOUND, label + " node not found in scene: " + node_path)
	else:
		_fail(OP_ERROR_NODE_NOT_FOUND, "non-canonical " + label + " node path: " + node_path
				+ " — address the node exactly as node list reports it: '.' for the root, 'A/B' for a descendant")


# Instantiate a node by type: a built-in Node class first, then a project-local
# class_name resolved through the unified resolver (_resolve_project_class_script,
# ADR-0032) — the editor global class list (cache-first) with a gda-owned
# raw-source .gd static scan as the fallback on a cache miss, so a headless
# editor-never-opened project still resolves a valid class_name. Records the
# failure itself and returns null, telling apart the distinct modes: a type that
# resolves to nothing is invalid_node_type (with an actionable message), a
# class_name declared in more than one .gd is ambiguous_class_name, and a resolved
# class_name whose script broke since registration is uninstantiable_script (issue
# #65) — repair the script, not the type name.
func _instantiate_node_type(type: String) -> Node:
	# Tier 1 (built-in engine class) stays here, per-site with the Node base-class
	# check; the class_name → script-path step is the unified resolver (ADR-0032).
	# class_exists gates can_instantiate: probing a class ClassDB does not know
	# (a project-local class_name) logs a spurious engine ERROR (issue #377).
	if not type.is_empty() and ClassDB.class_exists(type) and ClassDB.can_instantiate(type) \
			and ClassDB.is_parent_class(type, "Node"):
		return ClassDB.instantiate(type)
	var resolution := _resolve_project_class_script(type)
	match resolution["status"]:
		"resolved":
			return _instantiate_script_class(type, String(resolution["path"]))
		"ambiguous":
			_fail(OP_ERROR_AMBIGUOUS_CLASS_NAME, _ambiguous_class_name_message(type, resolution["paths"]))
			return null
		_:
			_fail(OP_ERROR_INVALID_NODE_TYPE, "not an instantiable Node class, and no .gd script declares class_name " + type
					+ " (check for a misspelled name, or declare it with `class_name " + type + "`)")
			return null


# node-add --instance (#399): materialize the scene to compose as a child of
# the host. Instantiation stamps the child root's scene_file_path — the marker
# PackedScene.pack() keys on to serialize the child as an
# instance=ExtResource(...) stub — its descendants stay owned by the instanced
# root, so they are referenced, never inlined into the host. Instantiating runs
# the _init of any script inside the instanced scene: the same Project-code
# execution surface as the class_name path (ADR-0009). The failure ladder
# mirrors the dependency precedent (#392/#396): a missing file is the
# composition's missing dependency, a file that loads as something else is
# not_a_scene (keyed on the RECOGNIZED type — the wrong KIND of file), while a
# scene-typed file that fails to load, instantiates to nothing, or silently
# drops declared nodes (the engine instantiates around a missing nested
# dependency, the #64 hazard) is dependency-shaped: missing_dependency naming
# the instance path the caller passed, with the engine diagnostics carrying
# the nested culprit (PR #404 review). The direct self-cycle (instancing the
# host into itself) is refused up front as cyclic_target — the write would
# serialize a self-reference that can never finish loading; deeper A→B→A
# cycles stay the engine's load-time problem, outside this guard.
func _instantiate_scene_instance(instance_path: String, host_path: String) -> Node:
	if ProjectSettings.globalize_path(instance_path) == ProjectSettings.globalize_path(host_path):
		_fail(OP_ERROR_CYCLIC_TARGET, "cannot instance a scene into itself: " + instance_path
				+ " — the composition would create a cycle")
		return null
	if not ResourceLoader.exists(instance_path):
		_fail(OP_ERROR_MISSING_DEPENDENCY, "instanced scene not found: " + instance_path
				+ " — --instance must reference an existing scene file; check the path and --project")
		return null
	if not ResourceLoader.exists(instance_path, "PackedScene"):
		_fail(OP_ERROR_NOT_A_SCENE, "not a scene: " + instance_path
				+ " — --instance must reference a PackedScene (.tscn/.scn)")
		return null
	var packed := ResourceLoader.load(instance_path, "PackedScene") as PackedScene
	if packed == null:
		_fail(OP_ERROR_MISSING_DEPENDENCY, "instanced scene failed to load: " + instance_path
				+ " — a dependency is missing or the file is broken; see diagnostics")
		return null
	# GEN_EDIT_STATE_INSTANCE retains the child's scene_instance_state — what
	# the packer's states-stack walk keys on to emit the canonical instance
	# stub: no type= attribute, and properties diffed against the instanced
	# scene's own state rather than class defaults. Editor-build-only, which is
	# the build gda drives (issue #164's documented assumption); a plain
	# instantiate() would leave the state empty and serialize a non-canonical
	# type= + class-default property dump alongside the instance= reference.
	var child := packed.instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
	if child == null:
		_fail(OP_ERROR_MISSING_DEPENDENCY, "scene failed to instantiate: " + instance_path
				+ " — an instanced sub-scene is unresolvable or empty; check the scene's dependencies and --project")
		return null
	# The #64 vanished-node guard, applied to the INSTANCED scene: the engine
	# instantiates around a missing nested dependency (or substitutes an
	# unavailable class), so composing the degraded tree would bake the loss
	# into the host. Refuse instead, naming what did not materialize.
	var unmaterialized := _unmaterialized_node_paths(packed.get_state(), child)
	if not unmaterialized.is_empty():
		child.free()
		_fail(OP_ERROR_MISSING_DEPENDENCY, "instanced scene nodes vanished or degraded on load: "
				+ instance_path + " (" + ", ".join(unmaterialized)
				+ ") — check the scene's dependencies and --project")
		return null
	return child


# Instantiate a class_name from its resolved script. Resolution (ADR-0032:
# the editor cache or the gda-owned static scan) only proves a class_name
# declaration exists in a .gd — not that the script loads, compiles, or
# constructs (a cached entry may be stale, and the static scan parses raw text
# without compiling; issue #65) — so each step is checked and a failure reported
# as the script problem it is, never as an unknown type.
func _instantiate_script_class(type: String, script_path: String) -> Node:
	var script := ResourceLoader.load(script_path) as Script
	if script == null:
		_fail(OP_ERROR_UNINSTANTIABLE_SCRIPT, "registered class_name " + type
				+ " script failed to load: " + script_path
				+ " — broken or removed since the project scan; see diagnostics")
		return null
	if not script.can_instantiate():
		_fail(OP_ERROR_UNINSTANTIABLE_SCRIPT, "registered class_name " + type
				+ " script cannot be instantiated: " + script_path
				+ " — it no longer compiles; see diagnostics")
		return null
	var instance: Variant = _new_script_instance(script)
	if instance == null:
		_fail(OP_ERROR_UNINSTANTIABLE_SCRIPT, "registered class_name " + type
				+ " script constructor failed: " + script_path
				+ " — its _init may require arguments; see diagnostics")
		return null
	if instance is Node:
		return instance
	if instance is Object and not (instance is RefCounted):
		instance.free()
	_fail(OP_ERROR_INVALID_NODE_TYPE, "registered class_name " + type
			+ " is not a Node-derived script: " + script_path)
	return null


# Isolated so an engine-raised call error from Script.new() — a constructor
# that needs arguments, or a script broken in a way can_instantiate() does not
# catch — aborts only this helper frame; the caller observes null and reports
# the failure structurally instead of degrading into an unstructured abort.
func _new_script_instance(script: Script) -> Variant:
	return script.new()


# Instantiate a resource by type: a built-in Resource class first, then a
# project-local class_name resolved through the same unified resolver node add and
# find-references route through (_resolve_project_class_script, ADR-0032) — the
# editor global class list (cache-first) with a gda-owned raw-source .gd static
# scan as the fallback on a cache miss. The Resource-side twin of
# _instantiate_node_type (issue #342): records the failure itself and returns null,
# telling apart the distinct modes — a type that resolves to nothing is
# invalid_resource_type (with an actionable message), a class_name declared in more
# than one .gd is ambiguous_class_name, and a resolved class_name whose script broke
# since registration is uninstantiable_script (repair the script, not the type name).
func _instantiate_resource_type(type: String) -> Resource:
	# Tier 1 (built-in engine class) stays here, per-site with the Resource
	# base-class check; the class_name → script-path step is the unified resolver
	# (ADR-0032), the same one node add and find-references route through.
	# class_exists gates can_instantiate: probing a class ClassDB does not know
	# (a project-local class_name) logs a spurious engine ERROR (issue #377).
	if not type.is_empty() and ClassDB.class_exists(type) and ClassDB.can_instantiate(type) \
			and ClassDB.is_parent_class(type, "Resource"):
		return ClassDB.instantiate(type)
	var resolution := _resolve_project_class_script(type)
	match resolution["status"]:
		"resolved":
			return _instantiate_resource_script_class(type, String(resolution["path"]))
		"ambiguous":
			_fail(OP_ERROR_AMBIGUOUS_CLASS_NAME, _ambiguous_class_name_message(type, resolution["paths"]))
			return null
		_:
			_fail(OP_ERROR_INVALID_RESOURCE_TYPE, "not an instantiable Resource class, and no .gd script declares class_name " + type
					+ " (check for a misspelled name, or declare it with `class_name " + type + "`)")
			return null


# Instantiate a class_name from its resolved script as a Resource. The
# Resource-side twin of _instantiate_script_class (issue #342): resolution
# (ADR-0032: the editor cache or the gda-owned static scan) only proves a
# class_name declaration exists in a .gd, not that the script loads, compiles, or
# constructs, so each step is checked and a failure reported as the script problem
# it is, never as an unknown type. Reuses _new_script_instance so a constructor
# error stays observable as null rather than aborting the frame.
func _instantiate_resource_script_class(type: String, script_path: String) -> Resource:
	var script := ResourceLoader.load(script_path) as Script
	if script == null:
		_fail(OP_ERROR_UNINSTANTIABLE_SCRIPT, "registered class_name " + type
				+ " script failed to load: " + script_path
				+ " — broken or removed since the project scan; see diagnostics")
		return null
	if not script.can_instantiate():
		_fail(OP_ERROR_UNINSTANTIABLE_SCRIPT, "registered class_name " + type
				+ " script cannot be instantiated: " + script_path
				+ " — it no longer compiles; see diagnostics")
		return null
	var instance: Variant = _new_script_instance(script)
	if instance == null:
		_fail(OP_ERROR_UNINSTANTIABLE_SCRIPT, "registered class_name " + type
				+ " script constructor failed: " + script_path
				+ " — its _init may require arguments; see diagnostics")
		return null
	if instance is Resource:
		return instance
	if instance is Object and not (instance is RefCounted):
		instance.free()
	_fail(OP_ERROR_INVALID_RESOURCE_TYPE, "registered class_name " + type
			+ " is not a Resource-derived script: " + script_path)
	return null


# The class_name of the node's attached script, or null for a plain built-in
# node (or a script with no class_name) — the result field an agent asserts to
# confirm a class_name addition took effect.
func _script_class_of(node: Node) -> Variant:
	var script := node.get_script() as Script
	if script == null:
		return null
	var global_name := String(script.get_global_name())
	if global_name.is_empty():
		return null
	return global_name


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


# A SceneState node path normalized to the canonical root-relative form the
# node group addresses by and reports: the state stores "." for the root and a
# "./Hero/Hitbox" prefix form for a descendant, which becomes "Hero/Hitbox".
# Shared so the unmaterialized-node guard and the tree builder agree on one
# normalization rather than re-spelling it (issue #55 review).
func _normalize_state_path(state: SceneState, index: int) -> String:
	return String(state.get_node_path(index)).trim_prefix("./")


# Build the structured node tree from a SceneState. The state lists nodes in
# tree order; each carries a node path ("." for the root, "./Hero/Hitbox" for
# a descendant) and the path to its parent, which is enough to reconstruct the
# parent/child structure without instantiating anything. with_paths includes
# each node's path in the emitted tree (node-list's addressing contract),
# normalized to the root-relative form node add accepts and reports: the
# state's "./Hero" prefix form becomes "Hero", the root stays ".".
func _packed_scene_root_type(packed: PackedScene, depth := 0) -> String:
	if packed == null or depth > 16:
		return ""
	var state := packed.get_state()
	if state == null or state.get_node_count() == 0:
		return ""
	var root_type := String(state.get_node_type(0))
	if not root_type.is_empty():
		return root_type
	var root_instance := state.get_node_instance(0)
	if root_instance != null:
		return _packed_scene_root_type(root_instance, depth + 1)
	return ""


func _state_node_projection_fields(state: SceneState, index: int) -> Dictionary:
	var fields := {"type": String(state.get_node_type(index))}
	var instance := state.get_node_instance(index)
	if instance != null:
		fields["instance_status"] = "resolved"
		var instance_path := String(instance.resource_path)
		if not instance_path.is_empty():
			fields["instance_path"] = instance_path
		var root_type := _packed_scene_root_type(instance)
		if fields["type"].is_empty() and not root_type.is_empty():
			fields["type"] = root_type
		return fields

	var placeholder_path := String(state.get_node_instance_placeholder(index))
	if not placeholder_path.is_empty():
		fields["instance_path"] = placeholder_path
		fields["instance_status"] = "missing"
	return fields


func _scene_instance_status_for_path(path: String) -> String:
	return "resolved" if ResourceLoader.exists(path, "PackedScene") else "missing"


# SceneState exposes whether a node is an instance and can resolve the root type,
# but the public PackedScene object it returns does not reliably carry the
# original ext_resource path. Recover that marker from the .tscn header text and
# merge it into the SceneState projection.
func _scene_instance_paths_by_node_path(path: String) -> Dictionary:
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		return {}
	var ext_resources_by_id := {}
	for entry in _ext_resource_entries_from_text(text, path.get_base_dir()):
		ext_resources_by_id[String(entry["id"])] = String(entry["normalized_path"])

	var instance_paths := {}
	for line in text.split("\n"):
		var stripped := line.strip_edges()
		if not stripped.begins_with("[node ") or stripped.find("instance=ExtResource(") == -1:
			continue
		var id := _first_quoted_after(stripped, stripped.find("instance=ExtResource("))
		if id.is_empty() or not ext_resources_by_id.has(id):
			continue
		var node_path := _scene_node_path_from_header(stripped)
		if not node_path.is_empty():
			instance_paths[node_path] = ext_resources_by_id[id]
	return instance_paths


func _tree_from_state(state: SceneState, with_paths := false, instance_paths_by_node_path := {}) -> Dictionary:
	var by_path := {}
	var root: Dictionary = {}
	for i in state.get_node_count():
		var projection_fields := _state_node_projection_fields(state, i)
		var state_path := String(state.get_node_path(i))
		var normalized_path := _normalize_state_path(state, i)
		if instance_paths_by_node_path.has(normalized_path):
			var instance_path := String(instance_paths_by_node_path[normalized_path])
			projection_fields["instance_path"] = instance_path
			if not projection_fields.has("instance_status"):
				projection_fields["instance_status"] = _scene_instance_status_for_path(instance_path)
		var node := {
			"name": String(state.get_node_name(i)),
			"type": projection_fields["type"],
			"children": [],
		}
		if projection_fields.has("instance_path"):
			node["instance_path"] = projection_fields["instance_path"]
		if projection_fields.has("instance_status"):
			node["instance_status"] = projection_fields["instance_status"]
		if with_paths:
			node["path"] = normalized_path
		by_path[state_path] = node
		if i == 0:
			root = node
		else:
			var parent: Variant = by_path.get(String(state.get_node_path(i, true)))
			if parent != null:
				parent["children"].append(node)
	return root


# --- Object-typed property assignment via a res:// resource reference (ADR-0033, #363) ---
#
# node set / resource set assign an EXISTING Resource — referenced by a `res://`
# path — to an Object-typed property that expects a Resource (sub)class (e.g.
# CollisionShape2D.shape). This is a SEPARATE, headless-only step from the shared
# _coerce_value block below: scalar coercion keys off Variant.Type and typed-container
# coercion may use the current Dictionary/Array value, but resolving an Object needs
# the property's expected-CLASS hint, which lives on the property-list entry — so this
# deliberately is NOT mirrored into the harness (a live `game set` Object assignment is
# out of scope, ADR-0033) and the byte-identical coercion mirror stays untouched.
#
# The full storage-property list entry (name/type/hint/hint_string/class_name/usage)
# for `prop_name` on `target` (a Node or a Resource — both are Objects with a
# property list), or an empty Dictionary when the target has no storage property by
# that name. The shared _property_type returns only the Variant.Type, which cannot
# carry the expected-class hint the Object step needs, so this reads the whole entry.
func _storage_property_entry(target: Object, prop_name: String) -> Dictionary:
	for prop in target.get_property_list():
		if String(prop.get("name", "")) == prop_name and _is_storage_property(prop):
			return prop
	return {}


# The engine/script class an Object-typed property expects, read off its
# property-list entry. Godot records it in the entry's `class_name` (a StringName,
# e.g. &"Shape2D" for CollisionShape2D.shape, &"PlayerConfig" for a script
# class_name-typed export) and mirrors it in `hint_string` under
# PROPERTY_HINT_RESOURCE_TYPE. Returns "" when neither names a class.
func _object_expected_class(prop_entry: Dictionary) -> String:
	var cls := String(prop_entry.get("class_name", ""))
	if not cls.is_empty():
		return cls
	if int(prop_entry.get("hint", PROPERTY_HINT_NONE)) == PROPERTY_HINT_RESOURCE_TYPE:
		return String(prop_entry.get("hint_string", ""))
	return ""


# Resolve a `res://` --value into the EXISTING Resource to assign to an Object-typed
# property (ADR-0033). Returns the loaded Resource on success, or null AFTER recording
# a DISTINCT structured failure (the caller stops; unlike _coerce_value's null, the
# caller must NOT fall back to uncoercible_value). `subject` names the target in
# messages ("node Player/Col" / "resource res://foo.tres"). The failure modes:
#   - the `script` property is bound only by `script attach` (#118) → use_script_attach;
#   - a non-`res://` value → expected_resource_path;
#   - a property typed as a script class_name (not an engine class) is deferred to the
#     ADR-0032 resolver → unsupported_property_type (type-check scope is engine classes);
#   - a path that does not load as a Resource → not_a_resource;
#   - a loaded Resource whose type is incompatible with the expected class →
#     resource_type_mismatch.
func _resolve_object_value(prop_name: String, prop_entry: Dictionary, raw_value: String, subject: String) -> Resource:
	# The `script` property is bound with `script attach` — the one authoritative
	# script-binding path (compile + base-type verification + replaced-script report,
	# #118). Route it there rather than adding a second, unverified attach entry.
	if prop_name == "script":
		_fail(OP_ERROR_USE_SCRIPT_ATTACH, "property script on " + subject
				+ " is bound with `gda script attach`, not `set` — it verifies the script"
				+ " compiles and its base type matches, and reports any replaced script")
		return null

	# An Object-typed property takes an existing Resource by its res:// path. A
	# non-res:// value is a distinct structured failure, never the generic
	# uncoercible_value.
	if not raw_value.begins_with("res://"):
		_fail(OP_ERROR_EXPECTED_RESOURCE_PATH, "property " + prop_name + " on " + subject
				+ " expects a Resource; assign an existing resource by its res:// path"
				+ " (e.g. res://shapes/box.tres), not " + raw_value.c_escape())
		return null

	# Type-check scope is ENGINE-class-typed Object properties (e.g. shape: Shape2D).
	# A property typed as a script `class_name` names a class ClassDB does not know;
	# its validation is deferred to the ADR-0032 class_name resolver (ADR-0033), so
	# refuse it distinctly rather than mis-type-check it against the engine hierarchy.
	var expected_class := _object_expected_class(prop_entry)
	if expected_class.is_empty() or not ClassDB.class_exists(expected_class):
		var named := expected_class if not expected_class.is_empty() else "an unspecified Object type"
		_fail(OP_ERROR_UNSUPPORTED_PROPERTY_TYPE, "property " + prop_name + " on " + subject
				+ " expects " + named + ", which is not an engine class — assigning a Resource to"
				+ " a script class_name-typed property is not yet supported (deferred, ADR-0033)")
		return null

	# Load the referenced resource. A missing path, or a file that is not a resource,
	# yields null here (the engine logs why to stderr) → a distinct structured failure,
	# never uncoercible_value. res:// resolution needs project context (pass --project).
	var loaded := ResourceLoader.load(raw_value) as Resource
	if loaded == null:
		_fail(OP_ERROR_NOT_A_RESOURCE, "value does not load as a Resource: " + raw_value
				+ " — check the res:// path exists and names a resource (pass --project so res:// resolves)")
		return null

	# is_class walks the engine class hierarchy, so a RectangleShape2D satisfies a
	# Shape2D-typed property while a Gradient does not.
	if not loaded.is_class(expected_class):
		_fail(OP_ERROR_RESOURCE_TYPE_MISMATCH, "resource " + raw_value + " is a "
				+ loaded.get_class() + ", incompatible with property " + prop_name + " on "
				+ subject + " (expects " + expected_class + ")")
		return null

	return loaded


func _has_int_param(params: Dictionary, key: String) -> bool:
	return params.has(key) and params[key] != null


func _int_param(params: Dictionary, key: String) -> int:
	return int(params.get(key, 0))


# --- BEGIN shared coercion (keep byte-identical: operations.gd <-> gda_harness.gd) ---
# These pure property-introspection / value-coercion helpers are DUPLICATED
# verbatim into src/gda/harness/gda_harness.gd: operations.gd runs via
# `godot --headless --script <abs-fs-path>` (often projectless) while the harness
# is a res:// autoload, so no single preload() reaches both and install.py copies
# one file. tests/test_harness_coercion_mirror.py asserts the two blocks are
# byte-identical (modulo leading tabs), so an edit here must be mirrored there.
# Whether a property-list entry is a STORAGE property — the ones node get
# reports and node set targets: the properties that serialize into the .tscn,
# excluding the engine's category headers, group separators, and editor-only
# (non-storage) entries. This is the same usage flag the scene serializer keys
# on, so node get reports exactly the surface a saved scene can carry.
func _is_storage_property(prop: Dictionary) -> bool:
	var usage := int(prop.get("usage", 0))
	return (usage & PROPERTY_USAGE_STORAGE) != 0


# The declared Godot type of a settable property on the node, or TYPE_NIL if the
# node has no storage property by that name. node set keys coercion off this:
# the value's target type comes from the property the node actually declares,
# never from guessing.
func _property_type(node: Node, prop_name: String) -> int:
	for prop in node.get_property_list():
		if String(prop.get("name", "")) == prop_name and _is_storage_property(prop):
			return int(prop.get("type", TYPE_NIL))
	return TYPE_NIL


# Read a string param defensively: a non-string value (the params arrive as
# arbitrary JSON) is treated as absent rather than crashing a typed assignment,
# so a malformed param surfaces as a structured failure, not a runtime error.
func _string_param(params: Dictionary, key: String) -> String:
	var value: Variant = params.get(key, "")
	if value is String:
		return value
	return ""


# The Godot type name for a Variant.Type, as node get / node set report it
# (the same spelling type_string uses: "int", "Vector2", "Color", …).
func _type_name(type: int) -> String:
	return type_string(type)


# The value projection's hard recursion depth cap (ADR-0035): a compound value
# nested deeper than this degrades to its string form instead of recursing on.
# Deliberately NO visited-set — references are not descended and non-whitelisted
# Objects stop at str(), so on-disk stored values are acyclic trees; the cap is
# the backstop against a pathological self-referential Dictionary live-side.
const JSONIFY_MAX_DEPTH := 16

# The properties an inline value projection excludes (ADR-0035): the
# Object/Resource base bookkeeping — every InputEvent IS a Resource, so
# without the exclusion a path-less value Object would emit an empty
# resource_path and masquerade as a reference projection (and the rest is
# noise) — plus the RESERVED discriminator key `object_string` (#666): only
# the texture projection emits it, so an inline class's own storage property
# of that name is dropped, not copied — otherwise a presence-based consumer
# would misclassify the inline projection as a texture.
const JSONIFY_BOOKKEEPING_PROPS: Array[String] = [
	"resource_path", "resource_name", "resource_local_to_scene", "script",
	"object_string",
]

# The read-side Value projection (ADR-0035, grown from issue #55): render a
# Godot Variant into the structured JSON a result's value field carries.
# Scalars pass through; the fixed-shape value types node set supports become
# flat number arrays so node get's output is exactly the projection node set
# accepts back: Vector2 → [x, y], Vector2i likewise, Color → [r, g, b, a].
# A Dictionary projects to a JSON object (keys stringified), an Array and the
# packed-array family to a JSON array, each value re-entering the projection;
# an Object renders as a reference projection, an inline value projection, or
# the str() fallback (the TYPE_OBJECT arm below). Any other type degrades to
# its string form rather than crashing JSON.stringify on an unencodable
# Variant, and the depth cap bounds the recursion on the compound arms — so
# the projection is always JSON-encodable.
func _jsonify(value: Variant, depth: int = 0, texture_digest: bool = false) -> Variant:
	match typeof(value):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STRING, TYPE_STRING_NAME:
			return value
		TYPE_VECTOR2:
			return [value.x, value.y]
		TYPE_VECTOR2I:
			return [value.x, value.y]
		TYPE_COLOR:
			return [value.r, value.g, value.b, value.a]
		TYPE_DICTIONARY:
			# The cap guards only the compound arms: a scalar is never
			# stringified by depth, however deep it sits.
			if depth >= JSONIFY_MAX_DEPTH:
				return str(value)
			var out := {}
			# Insertion-ordered iteration; keys are coerced to strings, so two
			# keys that collide after stringification resolve last-wins by
			# assignment order (deterministic, ADR-0035).
			for key in value.keys():
				out[str(key)] = _jsonify(value[key], depth + 1, texture_digest)
			return out
		TYPE_ARRAY, TYPE_PACKED_BYTE_ARRAY, TYPE_PACKED_INT32_ARRAY, \
		TYPE_PACKED_INT64_ARRAY, TYPE_PACKED_FLOAT32_ARRAY, \
		TYPE_PACKED_FLOAT64_ARRAY, TYPE_PACKED_STRING_ARRAY, \
		TYPE_PACKED_VECTOR2_ARRAY, TYPE_PACKED_VECTOR3_ARRAY, \
		TYPE_PACKED_COLOR_ARRAY, TYPE_PACKED_VECTOR4_ARRAY:
			if depth >= JSONIFY_MAX_DEPTH:
				return str(value)
			var items := []
			# Element-wise re-entry: a PackedVector2Array element projects as
			# [x, y]; an element type with no structured arm of its own (e.g.
			# Vector3) stays str(), per the fixed-shape list above.
			for element in value:
				items.append(_jsonify(element, depth + 1, texture_digest))
			return items
		TYPE_OBJECT:
			# A freed live Object (harness side) must not be introspected.
			if not is_instance_valid(value):
				return str(value)
			if depth >= JSONIFY_MAX_DEPTH:
				return str(value)
			# Reference projection: a Resource with a res:// path is named by
			# type and path, never inlined — the read-side mirror of ADR-0033's
			# write-side reference. A sub-resource path (res://x.tscn::…)
			# counts as a reference too.
			if value is Resource and String(value.resource_path).begins_with("res://"):
				return {"type": value.get_class(), "resource_path": value.resource_path}
			# Texture projection (#666, ADR-0035 amendment): a PATH-LESS Texture2D
			# — a runtime-created texture (ImageTexture.create_from_image) has no
			# res:// path, so the reference arm above cannot name it and the string
			# fallback's instance ID cannot say what it shows. PATH-LESS only:
			# a non-empty, non-res:// path (user://, take_over_path) stays the
			# string fallback it always was — #666's scope is the empty path. A
			# fixed shape read off cheap getters: class + dimensions. `object_string` keeps the old
			# str() form as secondary diagnostics and is this kind's DISCRIMINATOR
			# (no other object shape emits it; `resource_path` stays
			# reference-only, not even null here). `digest` is opt-in
			# (texture_digest): get_image() is a GPU-to-CPU readback on the live
			# side, not a price every read should pay; an image the engine cannot
			# read back keeps digest null. Dimensions and format prefix the hashed
			# bytes so same-bytes textures of different shapes do not collide.
			if value is Texture2D and String(value.resource_path).is_empty():
				var texture_projection := {
					"type": value.get_class(),
					"width": value.get_width(),
					"height": value.get_height(),
					"object_string": str(value),
					"digest": null,
				}
				if texture_digest:
					var image: Image = value.get_image()
					if image != null and not image.is_empty():
						var ctx := HashingContext.new()
						if ctx.start(HashingContext.HASH_SHA256) == OK:
							var shape := "%dx%d:%d:" % [
								image.get_width(), image.get_height(), image.get_format(),
							]
							ctx.update(shape.to_utf8_buffer())
							ctx.update(image.get_data())
							texture_projection["digest"] = "sha256:" + ctx.finish().hex_encode()
				return texture_projection
			# Inline value projection: a whitelisted path-less value Object
			# (InputEvent subclasses initially) projects its own storage
			# properties. The whitelist is the risk-isolation boundary that
			# keeps this shared projection safe on the live side, where an
			# arbitrary Object could be a whole scene tree (ADR-0035).
			if value is InputEvent:
				var projected := {}
				for prop in value.get_property_list():
					if not _is_storage_property(prop):
						continue
					var prop_name := String(prop.get("name", ""))
					if prop_name in JSONIFY_BOOKKEEPING_PROPS:
						continue
					projected[prop_name] = _jsonify(value.get(prop_name), depth + 1, texture_digest)
				# Assigned AFTER the loop so the discriminator shadows a
				# storage property named "type" (ADR-0035 documents the
				# shadowing — order matters).
				projected["type"] = value.get_class()
				return projected
			# String fallback: any other Object (not whitelisted, no res://
			# path — e.g. a live Node) keeps the existing str() form.
			return str(value)
		_:
			return str(value)


# Coerce a CLI string value to a property's declared Godot type (issue #55).
# The supported types and their accepted string forms are documented in the
# command catalog's "Property value coercion" section — keep the two in sync.
# Returns null when the value cannot be coerced to that type, which the caller
# reports as the clean uncoercible_value error. null is unambiguous as a
# failure signal because no supported target type coerces TO null.
# `current` lets typed Dictionary/Array properties/settings provide the
# destination type Godot should assign into; untyped and scalar coercion ignores it.
func _coerce_value(raw: String, type: int, current: Variant = null) -> Variant:
	match type:
		TYPE_BOOL:
			return _coerce_bool(raw)
		TYPE_INT:
			return _coerce_int(raw)
		TYPE_FLOAT:
			return _coerce_float(raw)
		TYPE_STRING:
			return raw
		TYPE_STRING_NAME:
			return StringName(raw)
		TYPE_DICTIONARY:
			return _coerce_dictionary(raw, current)
		TYPE_ARRAY:
			return _coerce_array(raw, current)
		TYPE_VECTOR2:
			var parts: Variant = _coerce_float_list(raw, 2)
			return Vector2(parts[0], parts[1]) if parts != null else null
		TYPE_VECTOR2I:
			var parts: Variant = _coerce_int_list(raw, 2)
			return Vector2i(parts[0], parts[1]) if parts != null else null
		TYPE_COLOR:
			return _coerce_color(raw)
		_:
			return null


# A bool from "true"/"false" (case-insensitive), nothing else — so a typo never
# silently becomes false.
func _coerce_bool(raw: String) -> Variant:
	var lowered := raw.strip_edges().to_lower()
	if lowered == "true":
		return true
	if lowered == "false":
		return false
	return null


func _coerce_int(raw: String) -> Variant:
	var trimmed := raw.strip_edges()
	if not trimmed.is_valid_int():
		return null
	return trimmed.to_int()


func _coerce_float(raw: String) -> Variant:
	var trimmed := raw.strip_edges()
	# is_valid_float accepts integer spellings too, which is intended: "3" is a
	# valid float value, and Godot stores it as 3.0.
	if not trimmed.is_valid_float():
		return null
	return trimmed.to_float()


# Parse a comma-separated list of exactly `count` floats (e.g. "10,20" for a
# Vector2). Whitespace around each component is tolerated; a wrong count or a
# non-numeric component fails the whole coercion.
func _coerce_float_list(raw: String, count: int) -> Variant:
	var parts := raw.split(",")
	if parts.size() != count:
		return null
	var out: Array[float] = []
	for part in parts:
		var coerced: Variant = _coerce_float(part)
		if coerced == null:
			return null
		out.append(coerced)
	return out


func _coerce_int_list(raw: String, count: int) -> Variant:
	var parts := raw.split(",")
	if parts.size() != count:
		return null
	var out: Array[int] = []
	for part in parts:
		var coerced: Variant = _coerce_int(part)
		if coerced == null:
			return null
		out.append(coerced)
	return out


# A Color from either a "#rrggbb"/"#rrggbbaa" hex string or a comma-separated
# list of 3 (rgb) or 4 (rgba) floats in 0..1. Godot's Color.html validates the
# hex form; the float-list form reuses the shared numeric coercion.
func _coerce_color(raw: String) -> Variant:
	var trimmed := raw.strip_edges()
	if trimmed.begins_with("#"):
		if not Color.html_is_valid(trimmed):
			return null
		return Color.html(trimmed)
	var parts := trimmed.split(",")
	if parts.size() != 3 and parts.size() != 4:
		return null
	var out: Array[float] = []
	for part in parts:
		var coerced: Variant = _coerce_float(part)
		if coerced == null:
			return null
		out.append(coerced)
	if out.size() == 3:
		return Color(out[0], out[1], out[2])
	return Color(out[0], out[1], out[2], out[3])


func _coerce_dictionary(raw: String, current: Variant = null) -> Variant:
	var parsed: Variant = JSON.parse_string(raw)
	if not (parsed is Dictionary):
		return null
	var variant: Variant = str_to_var(raw)
	if not (variant is Dictionary):
		return null
	var dictionary: Dictionary = variant
	if current is Dictionary:
		var current_dictionary: Dictionary = current
		if current_dictionary.is_typed():
			var typed_dictionary: Dictionary = current_dictionary.duplicate()
			typed_dictionary.clear()
			typed_dictionary.assign(dictionary)
			if typed_dictionary.size() != dictionary.size():
				return null
			return typed_dictionary
	return dictionary


func _coerce_array(raw: String, current: Variant = null) -> Variant:
	var parsed: Variant = JSON.parse_string(raw)
	if not (parsed is Array):
		return null
	var variant: Variant = str_to_var(raw)
	if not (variant is Array):
		return null
	var array: Array = variant
	if current is Array:
		var current_array: Array = current
		if current_array.is_typed():
			var typed_array: Array = current_array.duplicate()
			typed_array.clear()
			typed_array.assign(array)
			if typed_array.size() != array.size():
				return null
			return typed_array
	return array
# --- END shared coercion ---


func _is_valid_node_name(node_name: String) -> bool:
	if node_name.is_empty():
		return false
	for invalid_char in NODE_NAME_INVALID_CHARS:
		if node_name.contains(String(invalid_char)):
			return false
	return true


func _ensure_parent_dirs(path: String) -> Variant:
	var parent := path.get_base_dir()
	if parent.is_empty() or DirAccess.dir_exists_absolute(parent):
		return []

	var missing: Array[String] = []
	var current := parent
	while not current.is_empty() and not DirAccess.dir_exists_absolute(current):
		missing.push_front(current)
		var next := current.get_base_dir()
		if next == current:
			break
		current = next

	var err := DirAccess.make_dir_recursive_absolute(parent)
	if err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to create parent directory " + parent + ": " + error_string(err))
		return null
	return missing


# Build a save-failure diagnostic for a `noun` (scene / script) written to
# `path`: the error, the parent directory, and a write-probe that names why the
# directory is unwritable when that is the cause. Shared by every save path so
# the diagnostic (and the probe) stays identical across groups.
func _save_failure_message(noun: String, path: String, save_err: Error) -> String:
	var parent := path.get_base_dir()
	var message := "failed to save " + noun + " to " + path
	if not parent.is_empty():
		message += " in parent directory " + parent
	message += ": " + error_string(save_err)

	var probe_dir := "."
	if not parent.is_empty():
		probe_dir = parent
	var probe_name := ".gda-write-check.tmp"
	var probe_path := probe_dir.path_join(probe_name)
	var probe := FileAccess.open(probe_path, FileAccess.WRITE)
	if probe == null:
		message += "; write probe " + probe_path + " failed: " + error_string(FileAccess.get_open_error())
	else:
		probe.close()
		var dir := DirAccess.open(probe_dir)
		if dir != null:
			dir.remove(probe_name)
	return message


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
	var write_err := _atomic_write_text(path, source)
	if write_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message("script", path, write_err))
		return false
	return true


# --- atomic write primitives (issue #226) -----------------------------------
#
# Godot's text savers (ResourceSaver for .tscn/.tres, FileAccess for .gd/.gdshader)
# open the destination directly and truncate-in-place, so a failed save TEARS the
# original. The engine has an atomic mode (FileAccess::set_backup_save(true)) but it
# is not bound to GDScript, so we replicate it: write to a SAME-DIRECTORY sibling
# temp, then DirAccess.rename_absolute(tmp, path) — a same-filesystem POSIX rename,
# which IS bound and IS atomic. On any failure the target is left byte-untouched and
# the temp is removed, so a concurrent reader (or our own staleness guard) never sees
# a half-written file. Returns an Error code (OK on success); the caller keeps its
# existing save_failed ladder and only translates a non-OK return.


# A sibling temp path in the target's own directory (so rename is same-filesystem
# and therefore atomic). The PID disambiguates parallel one-shot headless processes
# writing the same target, so their temps never collide. Pure string ops, so it
# works for res:// paths as well as absolute/user:// paths.
#
# The target's ORIGINAL extension is PRESERVED as the temp's trailing extension
# (".gda-<pid>-<file>.tmp.<ext>") because ResourceSaver.save picks its saver by the
# destination's recognized extension — a ".tmp" tail would be "File unrecognized"
# and fail every .tscn/.tres save. FileAccess writes (.gd/.gdshader) don't care, so
# preserving the extension is harmless there and correct for the resource path.
func _atomic_temp_path(path: String) -> String:
	var ext := path.get_extension()
	var suffix := ".tmp" if ext.is_empty() else ".tmp." + ext
	return path.get_base_dir().path_join(".gda-" + str(OS.get_process_id()) + "-" + path.get_file() + suffix)


# Remove a file if it exists, swallowing the outcome — used to clean up a temp on a
# failed atomic write, where the write error is what we want to report, not a
# secondary cleanup error.
func _remove_quiet(path: String) -> void:
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(path)


# Restore ext_resource ids that already existed in the target .tscn before
# ResourceSaver re-serialized it. Scope is deliberately narrow: match resources by
# their normalized ext_resource path, rewrite only id="..." attributes and
# ExtResource("...") references, and leave all other saver canonicalization alone
# (issue #393). If ResourceSaver collapses duplicate entries for the same path, keep
# the first old id for that canonical path rather than accepting a freshly generated
# id.
func _restore_existing_ext_resource_ids(
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


func _raw_ext_resource_entries_from_text(text: String) -> Array:
	var entries: Array = []
	for line in text.split("\n"):
		var stripped := line.strip_edges()
		if not stripped.begins_with("[ext_resource"):
			continue
		var ref_path := _quoted_named_attr(stripped, "path")
		var id := _quoted_named_attr(stripped, "id")
		if ref_path.is_empty() or id.is_empty():
			continue
		# `type` is the class the line DECLARES for the reference ("Script",
		# "Texture2D", …); "" when the line names none. Carried so scene-validate can
		# report what was expected at a path that did not resolve (#664) — the
		# id/path consumers ignore it.
		entries.append({"path": ref_path, "id": id, "type": _quoted_named_attr(stripped, "type")})
	return entries


func _ext_resource_entries_from_text(text: String, base_dir: String) -> Array:
	var entries: Array = []
	for entry in _raw_ext_resource_entries_from_text(text):
		var ref_path := String(entry["path"])
		entries.append({
			"path": ref_path,
			"normalized_path": _normalize_ext_resource_path(ref_path, base_dir),
			"id": String(entry["id"]),
			"type": String(entry.get("type", "")),
		})
	return entries


# The one CANONICAL IDENTITY of an [ext_resource] reference: the path every
# consumer keys a file by (#721 review).
#
# A relative reference is resolved against the scene's own directory, as before.
# An already-absolute one is simplified as well, and that half is the fix: it used
# to be returned verbatim, so `res://leaf.tscn` and `res://./leaf.tscn` were TWO
# keys for ONE file. Everything downstream keys on this string — the dependency
# walk's "a path declared twice is checked once and reported once" rule, the
# sub-scene walk's own `answered`/`reached_depth`/`chain` sets, and the
# id-restoring re-save — so a lexical alias defeated all three at once: two
# identical problems for one broken file, a cycle-closing edge that did not match
# its ancestor, and a per-file cost bound a hand-written alias could evade.
#
# simplify_path() is the ENGINE'S own normalization, not gda's invention: Godot
# reports `res://..\outside.gd` back as `res://../outside.gd` (measured on 4.6.3),
# and it leaves a scheme it does not own alone — `uid://abc` and `user://x.tscn`
# pass through unchanged. It collapses `.`, `..` and doubled separators without
# touching the scheme, which is exactly the identity question and nothing more.
func _normalize_ext_resource_path(ref_path: String, base_dir: String) -> String:
	if ref_path.begins_with("res://") or ref_path.begins_with("uid://") or ref_path.begins_with("user://"):
		return _canonical_resource_path(ref_path)
	return _canonical_resource_path(base_dir.path_join(ref_path))


# The canonical spelling of one already-absolute path — the identity half of
# _normalize_ext_resource_path, split out so a caller that has no base directory
# to resolve against can key by the SAME identity (#721 review round 3).
#
# The composed scene walk is that caller: its root arrives from the command line
# rather than from an [ext_resource] line, and seeding the walk with the caller's
# raw spelling put the root behind a different identity from every one of its
# children — `res://./main.tscn` and the `res://main.tscn` a child references back
# were two files, so the root was answered for twice.
func _canonical_resource_path(path: String) -> String:
	return path.simplify_path()


func _ext_resource_ids_by_path(text: String, base_dir: String) -> Dictionary:
	var by_path := {}
	for entry in _ext_resource_entries_from_text(text, base_dir):
		var ref_path := String(entry["normalized_path"])
		if not by_path.has(ref_path):
			by_path[ref_path] = []
		(by_path[ref_path] as Array).append(String(entry["id"]))
	return by_path


func _fresh_ext_resource_id(seed: String, used_ids: Dictionary, reserved_ids: Dictionary) -> String:
	var base := seed if not seed.is_empty() else "resource"
	var index := 2
	var candidate := base + "_gda" + str(index)
	while used_ids.has(candidate) or reserved_ids.has(candidate):
		index += 1
		candidate = base + "_gda" + str(index)
	return candidate


func _replace_ext_resource_ids(text: String, id_remap: Dictionary) -> String:
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


func _replace_ext_resource_id_attr(text: String, old_id: String, new_id: String) -> String:
	var old_attr := 'id="' + old_id + '"'
	var new_attr := 'id="' + new_id + '"'
	var lines := text.split("\n")
	for index in lines.size():
		var line := String(lines[index])
		if line.strip_edges().begins_with("[ext_resource"):
			lines[index] = line.replace(old_attr, new_attr)
	return "\n".join(lines)


# Save `res` to `path` atomically: ResourceSaver.save to a sibling temp, then rename
# the temp over the target. Returns OK on success, or the first non-OK Error (with
# the temp removed and the target untouched).
func _atomic_save_resource(res: Resource, path: String) -> int:
	var should_restore_ext_ids := (
			path.get_extension().to_lower() == "tscn" and FileAccess.file_exists(path)
	)
	var original_text := FileAccess.get_file_as_string(path) if should_restore_ext_ids else ""
	var tmp := _atomic_temp_path(path)
	var save_err := ResourceSaver.save(res, tmp)
	if save_err != OK:
		_remove_quiet(tmp)
		return save_err
	if should_restore_ext_ids:
		var saved_text := FileAccess.get_file_as_string(tmp)
		var stable_text := _restore_existing_ext_resource_ids(path, original_text, saved_text)
		if stable_text != saved_text:
			var rewrite_err := _atomic_write_text(tmp, stable_text)
			if rewrite_err != OK:
				_remove_quiet(tmp)
				return rewrite_err
	var rename_err := DirAccess.rename_absolute(tmp, path)
	if rename_err != OK:
		_remove_quiet(tmp)
		return rename_err
	return OK


# Write `content` to `path` atomically as RAW TEXT: store into a sibling temp,
# capture the write error BEFORE close() invalidates the handle (a disk-full/I/O
# error surfaces at get_error(), not at open), then rename the temp over the target.
# Returns OK on success, or the first non-OK Error (with the temp removed and the
# target untouched).
func _atomic_write_text(path: String, content: String) -> int:
	var tmp := _atomic_temp_path(path)
	var file := FileAccess.open(tmp, FileAccess.WRITE)
	if file == null:
		return FileAccess.get_open_error()
	file.store_string(content)
	var write_err := file.get_error()
	file.close()
	if write_err != OK:
		_remove_quiet(tmp)
		return write_err
	var rename_err := DirAccess.rename_absolute(tmp, path)
	if rename_err != OK:
		_remove_quiet(tmp)
		return rename_err
	return OK


# Record a successful result: emit it through the sentinel contract and mark
# the process to exit 0. The single quit() lives in _process.
func _succeed(payload: Dictionary) -> void:
	print(RESULT_BEGIN + JSON.stringify(payload) + RESULT_END)
	_exit_code = 0


func _diag(message: String) -> void:
	printerr(DIAG_PREFIX + message)


# Record a structured failure through the ADR-0002 sentinel contract. The
# process is left to exit non-zero via _process.
func _fail(code: String, message: String) -> void:
	print(RESULT_BEGIN + JSON.stringify({
		"error": {
			"code": code,
			"message": message,
		},
	}) + RESULT_END)
	_exit_code = 1
