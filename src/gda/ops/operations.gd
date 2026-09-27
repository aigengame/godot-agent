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
#
# The operation bodies live in one file per command group (ADR-0043); this entry
# keeps the lifecycle, the parameter parse, the dispatch, the emission, the
# pending tail and `info`. Every group is preloaded here, so `info` compiles the
# whole payload. Relative paths resolve from this file's directory.

const EXPORT_GROUP := preload("groups/export.gd")
const THEME_GROUP := preload("groups/theme.gd")
const VALUE := preload("lib/value.gd")
const PROJECT_WALK := preload("lib/project_walk.gd")
const SCENE_TEXT := preload("lib/scene_text.gd")
const GDSCRIPT_SCAN := preload("lib/gdscript_scan.gd")
const CLASS_INDEX := preload("lib/class_index.gd")
const REFERENCE_GRAPH := preload("lib/reference_graph.gd")
const FILE_WRITE := preload("lib/file_write.gd")
const OBJECT_REF := preload("lib/object_ref.gd")
const TEXT_EDIT := preload("lib/text_edit.gd")
const SCENE_STORE := preload("lib/scene_store.gd")
const SCENE_VALIDATE := preload("lib/scene_validate.gd")

const RESULT_BEGIN := "<<<GDA:RESULT>>>"
const RESULT_END := "<<<GDA:END>>>"
# Preflight readiness as INDEPENDENT evidence, not part of the result sentinel
# (#709 review): printed the moment the scene reports ready, so the fact that it
# came up survives a project that ends the run (get_tree().quit() in _ready)
# before the pending tick can emit the result. Mirrored in gda.commands.scene,
# which reads it only off a clean exit that carried no result.
const PREFLIGHT_READY_EVIDENCE := "<<<GDA:PREFLIGHT-READY>>>"

# Transitional copy (#1015): op_base.gd declares these codes. A test pins this
# copy to it (tests/cli/test_error_registry.py) until the last step of #1015
# deletes the copy.
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


# The startup verdicts scene-preflight reports (#664). The third one an agent can
# read, `timeout`, is gda's own: only the CLI knows the launch outran its bound,
# because an engine stuck inside a scene's `_ready` never reaches the frame loop
# below to report anything at all.
const SCENE_STARTUP_READY := "ready"
const SCENE_STARTUP_NOT_READY := "not_ready"


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
# InputEvent.device is a 32-bit field: a larger int wraps on assignment (issue
# #842 review), so the op refuses it as the CLI does rather than storing a
# different device than the caller named.
const INPUT_EVENT_DEVICE_MAX := 2147483647

# The exit code the process will use. Defaults to failure, so an operation that
# aborts before recording an outcome (e.g. an uncaught runtime error) still
# exits non-zero rather than reporting a phantom success.
var _exit_code := 1


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

# The group instance that serves this run's operation, created by the dispatch
# arm and held here until the process quits. A Callable does not keep its
# RefCounted target alive (ADR-0043 probe 5): a group that only a pending tick
# referenced would be freed before the tick ran, and the run would emit no result.
var _group: RefCounted = null

# The instance concept modules the op bodies still in this file call, created
# with this frame and held here until the process quits (ADR-0043 §4). Each
# moves to the group that owns its callers with those bodies (#1015).
var _file_write := FILE_WRITE.new(self)
var _object_ref := OBJECT_REF.new(self)
var _text_edit := TEXT_EDIT.new(self)
var _scene_store := SCENE_STORE.new(self)


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
			_export_group()._op_export_list(params)
		"export-get":
			_export_group()._op_export_get(params)
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
			_theme_group()._op_theme_create(params)
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


# The group instance for the requested operation: created with this frame and
# held in `_group` (see there) before the dispatch arm calls into it.
func _export_group() -> EXPORT_GROUP:
	var group := EXPORT_GROUP.new(self)
	_group = group
	return group


func _theme_group() -> THEME_GROUP:
	var group := THEME_GROUP.new(self)
	_group = group
	return group


# info: emit Engine.get_version_info() through the structured-output contract.
func _op_info() -> void:
	_diag("running operation: info")
	_succeed(Engine.get_version_info())


# scene-create: instantiate a root node of the requested type, pack it, save
# it as a .tscn at the requested path (issue #18).
func _op_scene_create(params: Dictionary) -> void:
	_diag("running operation: scene-create")
	var path := VALUE._string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	var root_type := VALUE._string_param(params, "root_type")
	# class_exists gates can_instantiate: probing a name ClassDB does not know
	# logs a spurious engine ERROR (issue #377); the miss still fails as
	# invalid_root_type through the same else path.
	if root_type.is_empty() or not ClassDB.class_exists(root_type) \
			or not ClassDB.can_instantiate(root_type) \
			or not ClassDB.is_parent_class(root_type, "Node"):
		_fail(OP_ERROR_INVALID_ROOT_TYPE, "not an instantiable Node class: " + root_type)
		return
	var root_name := VALUE._string_param(params, "root_name")
	if not _scene_store._is_valid_node_name(root_name):
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
	var created_dirs: Variant = _file_write._ensure_parent_dirs(path)
	if created_dirs == null:
		root.free()
		return  # _ensure_parent_dirs already recorded the failure
	if not _scene_store._repack_and_save(root, path):
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
	var packed: PackedScene = _scene_store._load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var path := VALUE._string_param(params, "path")

	_succeed({
		"path": path,
		"root": _scene_store._tree_from_state(packed.get_state(), false, SCENE_TEXT._scene_instance_paths_by_node_path(path)),
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
	var packed: PackedScene = _scene_store._load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var root: Node = packed.instantiate()
	if root == null:
		_fail(OP_ERROR_MISSING_DEPENDENCY, "scene failed to instantiate: "
				+ VALUE._string_param(params, "path")
				+ " — an instanced sub-scene is unresolvable or empty; check the scene's dependencies and --project")
		return

	var nodes: Array = []
	_collect_node_exports(root, root, nodes)
	# Capture the path before freeing the tree (reading off a freed node errors).
	var scene_path := VALUE._string_param(params, "path")
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
			"type": VALUE._type_name(int(prop.get("type", TYPE_NIL))),
			"hint": int(prop.get("hint", 0)),
			"hint_string": String(prop.get("hint_string", "")),
			"value": VALUE._jsonify(node.get(prop_name)),
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
	var packed: PackedScene = _scene_store._load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var path := VALUE._string_param(params, "path")

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
	var raw_path := VALUE._string_param(params, "path")
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
	var path := SCENE_TEXT._canonical_resource_path(raw_path)
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
	if not SCENE_VALIDATE._has_scene_header(text):
		_fail(OP_ERROR_NOT_A_SCENE, "not a scene document (no [gd_scene] header): " + path)
		return

	# The dependency scan runs BEFORE the load, and its answer OUTRANKS a load
	# failure. Godot tolerates an unresolvable [ext_resource] referenced from a NODE
	# (it substitutes null and the scene still loads) but hard-fails the whole load
	# when the same reference sits in a [sub_resource] — an AtlasTexture's atlas, a
	# script-backed custom Resource (verified against Godot 4.6.3). Gating on the load
	# would answer `not_a_scene` for exactly the broken dependency this command exists
	# to report, and about a file that IS a scene.
	var own: Variant = SCENE_VALIDATE._scene_own_problems(path)
	if own == null:
		# Nothing found and nothing loadable is the group's ordinary not-a-scene,
		# reported in its words. The ROOT's contract only: a SUB-scene that does not
		# load is a finding about the composition, never a refusal of the whole call
		# (#721) — the caller asked about THIS file, and it is a scene.
		_fail(OP_ERROR_NOT_A_SCENE, "failed to load as a scene: " + path)
		return
	var problems := SCENE_VALIDATE._attributed_problems(own as Array, path)
	# The COMPOSED verdict (#721): a scene that references a broken one is broken,
	# and its own walk cannot see it — Godot resolves res://child.tscn perfectly
	# well while everything inside the child is gone. The walk therefore descends
	# into each referenced .tscn and adds its findings, each stamped with the file
	# it was found in. The depth-bound findings are settled only once every route
	# has been walked, so they come last.
	var walk := SCENE_VALIDATE._new_scene_walk(path, problems)
	SCENE_VALIDATE._collect_sub_scene_problems(path, walk)
	SCENE_VALIDATE._flush_pending_depth_problems(walk)

	_succeed({
		"path": path,
		"valid": problems.is_empty(),
		"problems": problems,
	})


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
	var packed: PackedScene = _scene_store._load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var path := VALUE._string_param(params, "path")

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
	var path := VALUE._string_param(params, "path")

	var node_name := VALUE._string_param(params, "name")
	if not _scene_store._is_valid_node_name(node_name):
		_fail(OP_ERROR_INVALID_NODE_NAME, "invalid name: " + node_name)
		return

	var root: Node = _scene_store._load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure
	var parent_path := VALUE._string_param(params, "parent")
	var parent := _scene_store._resolve_node(root, parent_path)
	if parent == null:
		root.free()
		if _scene_store._is_canonical_parent_path(parent_path):
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

	var type := VALUE._string_param(params, "type")
	var instance_path := VALUE._string_param(params, "instance")
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
	var script_class: Variant = CLASS_INDEX._script_class_of(node)
	if not _scene_store._repack_and_save(root, path):
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
	var packed: PackedScene = _scene_store._load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var path := VALUE._string_param(params, "path")

	_succeed({
		"scene_path": path,
		"root": _scene_store._tree_from_state(packed.get_state(), true, SCENE_TEXT._scene_instance_paths_by_node_path(path)),
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
	var packed: PackedScene = _scene_store._load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var root: Node = packed.instantiate()
	if root == null:
		_fail(OP_ERROR_MISSING_DEPENDENCY, "scene failed to instantiate: "
				+ VALUE._string_param(params, "path")
				+ " — an instanced sub-scene is unresolvable or empty; check the scene's dependencies and --project")
		return
	var node_path := VALUE._string_param(params, "node")
	var node := _scene_store._resolve_node(root, node_path)
	if node == null:
		root.free()
		_scene_store._fail_node_not_found(node_path)
		return

	var properties: Array = []
	for prop in node.get_property_list():
		if not VALUE._is_storage_property(prop):
			continue
		var prop_name := String(prop.get("name", ""))
		properties.append({
			"name": prop_name,
			"type": VALUE._type_name(int(prop.get("type", TYPE_NIL))),
			"value": VALUE._jsonify(node.get(prop_name)),
		})
	# Capture the node's identity before freeing the tree: freeing root frees
	# node too, and reading off a freed node is a runtime error.
	var node_name := String(node.name)
	var node_type := node.get_class()
	root.free()

	_succeed({
		"scene_path": VALUE._string_param(params, "path"),
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
	var path := VALUE._string_param(params, "path")
	var root: Node = _scene_store._load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure
	var node_path := VALUE._string_param(params, "node")
	var node := _scene_store._resolve_node(root, node_path)
	if node == null:
		root.free()
		_scene_store._fail_node_not_found(node_path)
		return

	var prop_name := VALUE._string_param(params, "property")
	if _is_control_position_write(node, prop_name):
		var control: Control = node as Control
		if _has_container_parent(control):
			# Read the message BEFORE the tree is freed: it asks the control's
			# parent for the inputs it carries.
			var refusal := _control_position_unavailable_message("node " + node_path, control)
			root.free()
			_fail(OP_ERROR_UNKNOWN_PROPERTY, refusal)
			return
		var raw_position := VALUE._string_param(params, "value")
		var coerced_position: Variant = VALUE._coerce_value(raw_position,
				TYPE_VECTOR2, control.position)
		if coerced_position == null:
			root.free()
			_fail(OP_ERROR_UNCOERCIBLE_VALUE, "cannot coerce value "
					+ raw_position.c_escape()
					+ " to Vector2 for property position on node " + node_path
					+ VALUE._float_fidelity_note(raw_position, TYPE_VECTOR2))
			return
		var target_position: Vector2 = coerced_position
		control.set_position(target_position)
		var stored_position: Variant = VALUE._jsonify(control.position)
		if not _scene_store._repack_and_save(root, path):
			return  # _repack_and_save already recorded the failure (and freed root)

		_succeed({
			"scene_path": path,
			"path": node_path,
			"property": prop_name,
			"type": VALUE._type_name(TYPE_VECTOR2),
			"value": stored_position,
		})
		return

	var declared_type := VALUE._property_type(node, prop_name)
	if declared_type == TYPE_NIL:
		root.free()
		_fail(OP_ERROR_UNKNOWN_PROPERTY, "node " + node_path
				+ " has no settable property: " + prop_name)
		return

	var raw_value := VALUE._string_param(params, "value")
	var stored_value: Variant
	if declared_type == TYPE_OBJECT:
		# Object-typed property: assign an EXISTING Resource referenced by a res://
		# path (ADR-0033, #363). A separate, headless-only step from the shared
		# _coerce_value (it needs the expected-class hint that Variant.Type/current
		# container context cannot carry); it records its own distinct structured failure.
		var resolved := _object_ref._resolve_object_value(prop_name,
				_object_ref._storage_property_entry(node, prop_name), raw_value, "node " + node_path)
		if resolved == null:
			root.free()
			return  # _resolve_object_value already recorded the failure
		node.set(prop_name, resolved)
		# The echo is the same reference projection a subsequent get reads back
		# (ADR-0035): {type, resource_path}. On disk the assignment still
		# round-trips as its res:// path — the loaded resource carries a
		# resource_path, so re-packing serializes it as an ext_resource.
		stored_value = VALUE._jsonify(resolved)
	else:
		var current_value: Variant = node.get(prop_name)
		var coerced: Variant = VALUE._coerce_value(raw_value, declared_type, current_value)
		if coerced == null:
			root.free()
			_fail(OP_ERROR_UNCOERCIBLE_VALUE, "cannot coerce value " + raw_value.c_escape()
					+ " to " + VALUE._type_name(declared_type) + " for property " + prop_name
					+ " on node " + node_path
					+ VALUE._float_fidelity_note(raw_value, declared_type))
			return

		node.set(prop_name, coerced)

		# Read the value back off the node before re-saving frees the tree — the node
		# now holds the coerced value in its canonical form, the same projection
		# node-get reports.
		stored_value = VALUE._jsonify(node.get(prop_name))
	if not _scene_store._repack_and_save(root, path):
		return  # _repack_and_save already recorded the failure (and freed root)

	_succeed({
		"scene_path": path,
		"path": node_path,
		"property": prop_name,
		"type": VALUE._type_name(declared_type),
		"value": stored_value,
	})


func _is_control_position_write(node: Node, prop_name: String) -> bool:
	return prop_name == "position" and node is Control


func _has_container_parent(control: Control) -> bool:
	return control.get_parent() is Container


func _control_layout_inputs(control: Control) -> String:
	# The ONE statement of which layout inputs a Control carries, shared by the
	# `game get` redirect and the `position` setter refusal (and mirrored in
	# operations.gd for the headless `node set`), so the two cannot disagree —
	# they did: the setter kept naming offset_* on a container child after the
	# getter had learned better (PR #967, third review). The engine strips
	# PROPERTY_USAGE_STORAGE from offset_* / anchor_* when the parent is a
	# Container (Control::_validate_property), so on such a child the inputs are
	# custom_minimum_size, the size flags, and the parent's own layout.
	if _has_container_parent(control):
		return " This Control is a direct child of a Container, which owns its" \
				+ " position and size: the offset_* and anchor_* properties are" \
				+ " not in its storage set. The layout inputs it does carry are" \
				+ " the storage properties custom_minimum_size," \
				+ " size_flags_horizontal and size_flags_vertical; the rest is" \
				+ " the parent Container's own layout"
	return " The layout inputs are the" \
			+ " storage properties offset_left, offset_top, offset_right," \
			+ " offset_bottom and anchor_left, anchor_top, anchor_right," \
			+ " anchor_bottom"


func _control_position_unavailable_message(subject: String, control: Control) -> String:
	return subject + " is a direct child of a Container, so Control.position is not an actionable settable property." \
			+ _control_layout_inputs(control)


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
	var path := VALUE._string_param(params, "path")
	var root: Node = _scene_store._load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure
	var node_path := VALUE._string_param(params, "node")
	var node := _scene_store._resolve_node(root, node_path)
	if node == null:
		root.free()
		_scene_store._fail_node_not_found(node_path)
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

	if not _scene_store._repack_and_save(root, path):
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
	var path := VALUE._string_param(params, "path")
	var root: Node = _scene_store._load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure
	var node_path := VALUE._string_param(params, "node")
	var node := _scene_store._resolve_node(root, node_path)
	if node == null:
		root.free()
		_scene_store._fail_node_not_found(node_path)
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
	if not _scene_store._repack_and_save(root, path):
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
	var path := VALUE._string_param(params, "path")
	var root: Node = _scene_store._load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure
	var node_path := VALUE._string_param(params, "node")
	var node := _scene_store._resolve_node(root, node_path)
	if node == null:
		root.free()
		_scene_store._fail_node_not_found(node_path)
		return
	if node == root:
		root.free()
		_fail(OP_ERROR_CANNOT_TARGET_ROOT, "cannot move the scene root: " + node_path
				+ " — the root has no parent to be reparented out of")
		return

	var target_path := VALUE._string_param(params, "to")
	var target := _scene_store._resolve_node(root, target_path)
	if target == null:
		root.free()
		if _scene_store._is_canonical_parent_path(target_path):
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
			if not _scene_store._repack_and_save(root, path):
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
	if not _scene_store._repack_and_save(root, path):
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
	var path := VALUE._string_param(params, "path")
	var root: Node = _scene_store._load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure

	var from_path := VALUE._string_param(params, "from")
	var source := _scene_store._resolve_node(root, from_path)
	if source == null:
		root.free()
		_fail_node_not_found_labeled("source", from_path)
		return
	var to_path := VALUE._string_param(params, "to")
	var target := _scene_store._resolve_node(root, to_path)
	if target == null:
		root.free()
		_fail_node_not_found_labeled("target", to_path)
		return

	var signal_name := VALUE._string_param(params, "signal")
	if not source.has_signal(signal_name):
		root.free()
		_fail(OP_ERROR_SIGNAL_NOT_FOUND, "source node " + from_path
				+ " has no signal: " + signal_name)
		return

	var method_name := VALUE._string_param(params, "method")
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

	if not _scene_store._repack_and_save(root, path):
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
	var path := VALUE._string_param(params, "path")
	var root: Node = _scene_store._load_for_mutation(params)
	if root == null:
		return  # _load_for_mutation already recorded the failure

	var from_path := VALUE._string_param(params, "from")
	var source := _scene_store._resolve_node(root, from_path)
	if source == null:
		root.free()
		_fail_node_not_found_labeled("source", from_path)
		return
	var to_path := VALUE._string_param(params, "to")
	var target := _scene_store._resolve_node(root, to_path)
	if target == null:
		root.free()
		_fail_node_not_found_labeled("target", to_path)
		return

	var signal_name := VALUE._string_param(params, "signal")
	# A missing source signal is signal_not_found, symmetric with connect-signal
	# and the documented contract: a typo'd signal is fixed by naming the right
	# signal, not by being collapsed into an absent connection (issue #57 review).
	if not source.has_signal(signal_name):
		root.free()
		_fail(OP_ERROR_SIGNAL_NOT_FOUND, "source node " + from_path
				+ " has no signal: " + signal_name)
		return
	var method_name := VALUE._string_param(params, "method")
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

	if not _scene_store._repack_and_save(root, path):
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
		root.free()
		_scene_store._fail_node_not_found(node_path)
		return

	# Secondary input: validate the --script arg only now — its .gd shape
	# (invalid_path) and existence (path_not_found), via the shared #135 helper — so
	# a scene/node problem is always reported ahead of a script problem (issue #132,
	# Part 2). The helper records the failure; the caller frees the live tree.
	var script_path := VALUE._string_param(params, "script")
	if not _require_existing_script(script_path):
		root.free()
		return  # _require_existing_script already recorded the failure
	if not _scene_store._validate_script_preload_dependencies(script_path):
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
	var path := VALUE._string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _is_resource_path(path):
		_fail(OP_ERROR_INVALID_PATH, "resource path must end in .tres: " + path)
		return
	if FileAccess.file_exists(path) or DirAccess.dir_exists_absolute(path):
		_fail(OP_ERROR_ALREADY_EXISTS, "resource target already exists: " + path)
		return
	var type := VALUE._string_param(params, "type")
	var resource: Resource = _instantiate_resource_type(type)
	if resource == null:
		return  # _instantiate_resource_type already recorded the failure

	var created_dirs: Variant = _file_write._ensure_parent_dirs(path)
	if created_dirs == null:
		return  # _ensure_parent_dirs already recorded the failure
	var save_err := _file_write._atomic_save_resource(resource, path)
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _file_write._save_failure_message("resource", path, save_err))
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
	var path := VALUE._string_param(params, "path")
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
		var shader_type := VALUE._string_param(params, "shader_type")
		if shader_type.is_empty():
			shader_type = "canvas_item"
		source = "shader_type " + shader_type + ";\n"

	var created_dirs: Variant = _file_write._ensure_parent_dirs(path)
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
	var path := VALUE._string_param(params, "path")
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
		if not VALUE._is_storage_property(prop):
			continue
		var prop_name := String(prop.get("name", ""))
		properties.append({
			"name": prop_name,
			"type": VALUE._type_name(int(prop.get("type", TYPE_NIL))),
			"value": VALUE._jsonify(resource.get(prop_name)),
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
	var path := VALUE._string_param(params, "path")
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
	_file_write._capture_staleness_token(path)

	var prop_name := VALUE._string_param(params, "property")
	var declared_type := _resource_property_type(resource, prop_name)
	if declared_type == TYPE_NIL:
		_fail(OP_ERROR_UNKNOWN_PROPERTY, "resource " + path
				+ " has no settable property: " + prop_name)
		return

	var raw_value := VALUE._string_param(params, "value")
	var stored_value: Variant
	if declared_type == TYPE_OBJECT:
		# Object-typed property: assign an EXISTING Resource referenced by a res://
		# path (ADR-0033, #363) — the resource-on-resource counterpart of node set's
		# Object branch. Headless-only, separate from the shared _coerce_value; it
		# records its own distinct structured failure.
		var resolved := _object_ref._resolve_object_value(prop_name,
				_object_ref._storage_property_entry(resource, prop_name), raw_value, "resource " + path)
		if resolved == null:
			return  # _resolve_object_value already recorded the failure
		resource.set(prop_name, resolved)
		# The echo is the same reference projection a subsequent get reads back
		# (ADR-0035): {type, resource_path}. On disk the assignment still
		# round-trips as its res:// path — the loaded resource carries a
		# resource_path, so re-saving serializes it as an ext_resource.
		stored_value = VALUE._jsonify(resolved)
	else:
		var current_value: Variant = resource.get(prop_name)
		var coerced: Variant = VALUE._coerce_value(raw_value, declared_type, current_value)
		if coerced == null:
			_fail(OP_ERROR_UNCOERCIBLE_VALUE, "cannot coerce value " + raw_value.c_escape()
					+ " to " + VALUE._type_name(declared_type) + " for property " + prop_name
					+ " on resource " + path
					+ VALUE._float_fidelity_note(raw_value, declared_type))
			return
		resource.set(prop_name, coerced)
		# Read the value back off the resource before reporting — it now holds the
		# coerced value in its canonical form, the same projection resource get
		# reports, so a set round-trips through a get.
		stored_value = VALUE._jsonify(resource.get(prop_name))

	# Recheck before the write (issue #226): refuse if a concurrent editor changed the
	# .tres in the read->write window.
	if not _file_write._check_unchanged():
		return
	var save_err := _file_write._atomic_save_resource(resource, path)
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _file_write._save_failure_message("resource", path, save_err))
		return

	_succeed({
		"path": path,
		"property": prop_name,
		"type": VALUE._type_name(declared_type),
		"value": stored_value,
	})


# resource-delete: remove a .tres file from disk, reporting what was removed
# (path + the resource's engine class, read before deletion), completing the
# create → get → set → delete lifecycle (issue #120). Mirrors script-delete:
# validate addressing/existence with _require_existing_resource, capture the
# identity before delete, then DirAccess.remove_absolute (delete_failed on error).
func _op_resource_delete(params: Dictionary) -> void:
	_diag("running operation: resource-delete")
	var path := VALUE._string_param(params, "path")
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
		if String(prop.get("name", "")) == prop_name and VALUE._is_storage_property(prop):
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
	var path := VALUE._string_param(params, "path")
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
	var path := VALUE._string_param(params, "path")
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
	_file_write._capture_staleness_token(path)

	var mode := VALUE._string_param(params, "mode")
	var new_source: Variant
	match mode:
		"search_replace":
			new_source = _text_edit._apply_search_replace(source, params, "shader")
		"line_range":
			new_source = _text_edit._apply_line_range(source, params, "shader")
		"full":
			# full overwrite: content is guaranteed present by the CLI's mode check.
			new_source = VALUE._string_param(params, "content")
		_:
			# The CLI always supplies one of the three modes; a missing/unknown mode
			# means a malformed direct op invocation, not a reachable CLI path.
			_fail(OP_ERROR_INVALID_PARAMS, "unknown shader-set mode: " + mode)
			return
	if new_source == null:
		return  # the apply helper already recorded the failure

	# Recheck before the write (issue #226): refuse if a concurrent editor changed the
	# .gdshader in the read->write window.
	if not _file_write._check_unchanged():
		return
	if not _write_text_file(path, new_source, "shader"):
		return  # _write_text_file already recorded the failure

	# Re-parse the written source so set round-trips through shader get.
	_succeed({
		"path": path,
		"shader_type": _shader_metadata(new_source),
	})


# Whether a path names a shader file the shader group operates on: a .gdshader
# (Godot shader) file. Shader-file addressing is by extension, the same way
# script addressing keys on .gd and scene addressing on .tscn.
func _is_shader_path(path: String) -> bool:
	return path.get_extension().to_lower() == "gdshader"


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

	var target := VALUE._string_param(params, "target")
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
	var setting := VALUE._string_param(params, "setting")
	if setting.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: setting")
		return
	if not ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_UNKNOWN_SETTING, "project setting not found: " + setting)
		return

	var value: Variant = ProjectSettings.get_setting(setting)
	_succeed({
		"setting": setting,
		"type": VALUE._type_name(typeof(value)),
		"value": VALUE._jsonify(value),
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
	var section := VALUE._string_param(params, "section")
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
			"type": VALUE._type_name(typeof(value)),
			"value": VALUE._jsonify(value),
			"is_default": not customized.has(key),
		})

	_succeed({"settings": settings})


# The set of project setting names CUSTOMIZED in res://project.godot — the keys
# actually written there, as opposed to the engine's built-in defaults. Read by
# parsing project.godot with ConfigFile: each [section] key becomes the full
# "section/key" setting name (a sectionless key like config_version maps to its
# bare name, harmlessly — it is not a real setting). project list reports
# is_default=false for these keys and true for the rest.
#
# The file is the right source even though the initial value IS reachable
# (ProjectSettings.property_get_revert, which _op_project_set uses): "written in
# project.godot" and "differs from the engine default" are different facts, and
# this listing is about the first. A key the caller declared AT the default is
# customized — it is in the file — while property_get_revert would call it a
# default and hide it from a bare `project list`.
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
#
# The save RESERIALIZES the whole file, which is the CLI's business to bound and
# report (#843) — with one part only the engine can do: a value equal to the
# setting's default would be dropped by the writer, so this op keeps the line by
# moving that default aside, and names the setting in restored_settings.
func _op_project_set(params: Dictionary) -> void:
	_diag("running operation: project-set")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project set requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var setting := VALUE._string_param(params, "setting")
	if setting.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: setting")
		return
	if not ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_UNKNOWN_SETTING, "project setting not found: " + setting
				+ " — project set edits an existing setting; it never creates one")
		return

	var current_value: Variant = ProjectSettings.get_setting(setting)
	var declared_type := typeof(current_value)
	var raw_value := VALUE._string_param(params, "value")
	var coerced: Variant = VALUE._coerce_value(raw_value, declared_type, current_value)
	if coerced == null:
		_fail(OP_ERROR_UNCOERCIBLE_VALUE, "cannot coerce value " + raw_value.c_escape()
				+ " to " + VALUE._type_name(declared_type) + " for project setting " + setting
				+ VALUE._float_fidelity_note(raw_value, declared_type))
		return

	# The engine's writer DROPS every setting whose value equals its INITIAL value
	# (ProjectSettings::save_custom: `if (v->variant == v->initial) continue;`), so
	# setting one TO its default would persist nothing at all — the file would come
	# back without the line the caller just asked for. property_get_revert reads the
	# very value that comparison uses, so when they match, move the initial aside and
	# let the ENGINE write the line in its own serialization; gda never hand-builds a
	# Godot literal for it (the ADR-0033 rule). Reported as restored_settings, which
	# the CLI merges with the declarations it restored from the pre-write file (#843).
	var restored: Array = []
	if ProjectSettings.property_get_revert(setting) == coerced:
		ProjectSettings.set_initial_value(setting, null)
		restored.append(setting)
	ProjectSettings.set_setting(setting, coerced)
	var save_err := ProjectSettings.save()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to save project settings after setting "
				+ setting + ": " + error_string(save_err))
		return

	# Read the value back off ProjectSettings before reporting — it now holds the
	# coerced value in its canonical form, the same projection project get reports,
	# so a set round-trips through a get.
	var stored_value: Variant = VALUE._jsonify(ProjectSettings.get_setting(setting))
	_succeed({
		"setting": setting,
		"type": VALUE._type_name(declared_type),
		"value": stored_value,
		"restored_settings": restored,
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
	var autoload_name := VALUE._string_param(params, "name")
	if autoload_name.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: name")
		return
	var path := VALUE._string_param(params, "path")
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
	var autoload_name := VALUE._string_param(params, "name")
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


# The JoyButton / JoyAxis names --joy-button and --joy-axis accept (issue #842),
# each mapped to the ENGINE's own global constant. Godot ships no name resolver
# for the joypad enums — there is no counterpart of OS.find_keycode_from_string —
# so gda has to carry the table; mapping every name to the engine constant keeps
# each VALUE the engine's (the GDScript compiler resolves it) and leaves gda
# owning only the SPELLING. The enums' INVALID / SDL_MAX / MAX entries are
# deliberately absent: they are enum bookkeeping, not bindable inputs.
# tests/project/test_input_action_joy_names.py diffs both tables against the enum
# the engine itself dumps, so an engine that gains a button fails a test here
# instead of silently going unbindable.
const JOY_BUTTON_BY_NAME := {
	"A": JOY_BUTTON_A,
	"B": JOY_BUTTON_B,
	"X": JOY_BUTTON_X,
	"Y": JOY_BUTTON_Y,
	"Back": JOY_BUTTON_BACK,
	"Guide": JOY_BUTTON_GUIDE,
	"Start": JOY_BUTTON_START,
	"LeftStick": JOY_BUTTON_LEFT_STICK,
	"RightStick": JOY_BUTTON_RIGHT_STICK,
	"LeftShoulder": JOY_BUTTON_LEFT_SHOULDER,
	"RightShoulder": JOY_BUTTON_RIGHT_SHOULDER,
	"DPadUp": JOY_BUTTON_DPAD_UP,
	"DPadDown": JOY_BUTTON_DPAD_DOWN,
	"DPadLeft": JOY_BUTTON_DPAD_LEFT,
	"DPadRight": JOY_BUTTON_DPAD_RIGHT,
	"Misc1": JOY_BUTTON_MISC1,
	"Paddle1": JOY_BUTTON_PADDLE1,
	"Paddle2": JOY_BUTTON_PADDLE2,
	"Paddle3": JOY_BUTTON_PADDLE3,
	"Paddle4": JOY_BUTTON_PADDLE4,
	"Touchpad": JOY_BUTTON_TOUCHPAD,
}

const JOY_AXIS_BY_NAME := {
	"LeftX": JOY_AXIS_LEFT_X,
	"LeftY": JOY_AXIS_LEFT_Y,
	"RightX": JOY_AXIS_RIGHT_X,
	"RightY": JOY_AXIS_RIGHT_Y,
	"TriggerLeft": JOY_AXIS_TRIGGER_LEFT,
	"TriggerRight": JOY_AXIS_TRIGGER_RIGHT,
}


# Fold a joypad binding name to its comparison form: case- and separator-
# insensitive, so DPadLeft, dpad_left and DPAD_LEFT all name the same button —
# a caller may spell it gda's way or the engine documentation's way.
# Separator-insensitivity is total on purpose: separators are DELETED, not
# normalized, so a leading or trailing one folds away too ("A-" is A). That
# widens the spellings accepted and never makes two buttons collide — the
# oracle test asserts the folded names stay unique — and the alternative would
# be a separator grammar for a token no caller writes deliberately.
func _fold_joy_name(token: String) -> String:
	return token.strip_edges().replace("_", "").replace("-", "").replace(" ", "").to_upper()


# Look one folded token up in a joypad name table, or return -1 (the INVALID
# member both enums share) when nothing matches.
func _lookup_joy_name(table: Dictionary, token: String) -> int:
	var folded := _fold_joy_name(token)
	for name in table:
		if _fold_joy_name(name) == folded:
			return table[name]
	return -1


# The accepted-name list a refusal message names, read off the table itself so
# the message cannot drift from what the resolver accepts.
func _joy_name_list(table: Dictionary) -> String:
	return ", ".join(PackedStringArray(table.keys()))


# Resolve one --joy-button token to a JoyButton index (issue #842). A base-10
# integer is taken as a raw index and must sit inside the engine's own JoyButton
# range (0..JOY_BUTTON_MAX - 1 — a device may report more buttons than the SDL
# names cover); anything else is a name looked up case- and separator-
# insensitively. Returns JOY_BUTTON_INVALID when the token names nothing.
func _resolve_joy_button(token: String) -> int:
	var trimmed := token.strip_edges()
	if trimmed.is_valid_int():
		var index := trimmed.to_int()
		return index if index >= 0 and index < JOY_BUTTON_MAX else JOY_BUTTON_INVALID
	return _lookup_joy_name(JOY_BUTTON_BY_NAME, trimmed)


# Resolve one --joy-axis token to a JoyAxis index (issue #842), same rules as
# _resolve_joy_button over the JoyAxis range. Returns JOY_AXIS_INVALID when the
# token names nothing.
func _resolve_joy_axis(token: String) -> int:
	var trimmed := token.strip_edges()
	if trimmed.is_valid_int():
		var index := trimmed.to_int()
		return index if index >= 0 and index < JOY_AXIS_MAX else JOY_AXIS_INVALID
	return _lookup_joy_name(JOY_AXIS_BY_NAME, trimmed)


# Split one --joy-axis token into its axis part and its axis_value (issue #842).
# The token is `<axis>[:<sign>]`: an axis names a whole stick DIMENSION, so the
# sign is what turns it into one bindable direction (`LeftX:-` is "stick left").
# An omitted sign is the positive direction — the only sensible reading for a
# trigger, which never goes negative. Returns an empty Dictionary when the token
# is not a resolvable direction; the caller reports it with the accepted set.
func _parse_joy_axis_token(token: String) -> Dictionary:
	var parts := token.strip_edges().split(":")
	if parts.size() > 2:
		return {}
	var axis := _resolve_joy_axis(parts[0])
	if axis == JOY_AXIS_INVALID:
		return {}
	var axis_value := 1.0
	if parts.size() == 2:
		match parts[1]:
			"+":
				axis_value = 1.0
			"-":
				axis_value = -1.0
			_:
				return {}
	return {"axis": axis, "axis_value": axis_value}


# project-add-input-action: register an InputMap action under input/<name> with
# keyboard and/or joypad bindings, then persist project.godot (issues #380, #842).
#
# The stored value is the InputMap Dictionary shape — {deadzone, events} with
# real InputEvent Objects, deadzone first (Godot's own key order) — set via
# ProjectSettings.set_setting and serialized by ProjectSettings.save() (the
# engine's own var_to_str form). gda never hand-builds the Object(InputEventKey,
# …) string, so the persisted entry is byte-equivalent to a hand-authored one.
# That holds for every event kind: the joypad kinds are real
# InputEventJoypadButton / InputEventJoypadMotion objects, serialized the same way.
#
# The events are appended in kind order — keys, then joypad buttons, then joypad
# axis directions — so one call's persisted order is deterministic.
#
# Failure modes use registered codes: an empty name is invalid_path (the
# missing-required-param convention the autoload ops set); malformed params,
# and a call naming no binding at all, are invalid_params; an action name already
# present is already_exists (add never silently clobbers — remove first to
# replace). NOTE: the engine registers the built-in ui_* actions
# (input/ui_accept, …) as ProjectSettings defaults, so has_setting answers true
# for them and adding e.g. ui_accept reports already_exists by design. An
# unresolvable BINDING token — a key, a joypad button or a joypad axis direction —
# is invalid_key naming the accepted set (nothing saved); a failed save is
# save_failed.
func _op_project_add_input_action(params: Dictionary) -> void:
	_diag("running operation: project-add-input-action")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project add-input-action requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var action_name := VALUE._string_param(params, "name")
	if action_name.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: name")
		return
	# Defensive params reads: the params arrive as arbitrary JSON, so a wrong
	# shape surfaces as a structured failure rather than a runtime error.
	var raw_keys: Variant = params.get("keys", [])
	if not (raw_keys is Array):
		_fail(OP_ERROR_INVALID_PARAMS, "keys must be an array of key names or keycodes")
		return
	var raw_joy_buttons: Variant = params.get("joy_buttons", [])
	if not (raw_joy_buttons is Array):
		_fail(OP_ERROR_INVALID_PARAMS, "joy_buttons must be an array of JoyButton names or indices")
		return
	var raw_joy_axes: Variant = params.get("joy_axes", [])
	if not (raw_joy_axes is Array):
		_fail(OP_ERROR_INVALID_PARAMS, "joy_axes must be an array of <axis>[:<sign>] tokens")
		return
	# An action with no event matches nothing, so the op refuses it rather than
	# registering a dead entry. On the argv path the same rule is a model-side
	# usage error before dispatch (ADR-0015); this is the params-json edge.
	if (raw_keys as Array).is_empty() and (raw_joy_buttons as Array).is_empty() \
			and (raw_joy_axes as Array).is_empty():
		_fail(OP_ERROR_INVALID_PARAMS, "at least one binding is required: keys, joy_buttons or joy_axes")
		return
	var raw_deadzone: Variant = params.get("deadzone", 0.5)
	if not (raw_deadzone is float or raw_deadzone is int):
		_fail(OP_ERROR_INVALID_PARAMS, "deadzone must be a number in 0..1")
		return
	var deadzone := float(raw_deadzone)
	var physical := bool(params.get("physical", false))
	var raw_device: Variant = params.get("device", -1)
	if (not (raw_device is int or raw_device is float) or int(raw_device) < -1
			or int(raw_device) > INPUT_EVENT_DEVICE_MAX):
		_fail(OP_ERROR_INVALID_PARAMS, "device must be an integer in -1.." + str(INPUT_EVENT_DEVICE_MAX)
				+ " (-1 matches every joypad; the engine stores the device as a 32-bit integer)")
		return
	var device := int(raw_device)

	var setting := INPUT_SETTING_PREFIX + action_name
	if ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_ALREADY_EXISTS, "input action already registered: " + action_name
				+ " — add-input-action never overwrites; remove it first to replace it")
		return

	# Resolve every binding token before touching ProjectSettings, so a bad token
	# fails the whole add cleanly with nothing saved. `events` stays an UNTYPED
	# Array: a typed Array[InputEventKey] would serialize with an
	# `Array[InputEventKey](...)` annotation, not the plain `[Object(...)]` form
	# the editor writes — untyped keeps the persisted entry byte-equivalent, and
	# it is also what lets the three event kinds share one array.
	var events := []
	var reported_events := []
	for raw_token in (raw_keys as Array):
		if not (raw_token is String):
			_fail(OP_ERROR_INVALID_PARAMS, "keys must be an array of key names or keycodes")
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
		# device 0 would never match a physical key press. --device names a
		# JOYPAD and so is never applied to a key event.
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
	for raw_token in (raw_joy_buttons as Array):
		if not (raw_token is String):
			_fail(OP_ERROR_INVALID_PARAMS, "joy_buttons must be an array of JoyButton names or indices")
			return
		var token: String = raw_token
		var button_index := _resolve_joy_button(token)
		if button_index == JOY_BUTTON_INVALID:
			_fail(OP_ERROR_INVALID_KEY, "cannot resolve joypad button: " + token
					+ " — accepted names (case- and separator-insensitive): "
					+ _joy_name_list(JOY_BUTTON_BY_NAME)
					+ "; or an index 0.." + str(JOY_BUTTON_MAX - 1))
			return
		var event := InputEventJoypadButton.new()
		# InputEvent::device defaults to 0 in the engine, which matches only the
		# FIRST joypad; --device defaults to -1 (InputMap::ALL_DEVICES) and is set
		# explicitly here for the same reason the key path sets it.
		event.device = device
		event.button_index = button_index as JoyButton
		events.append(event)
		reported_events.append({
			"kind": "joy_button",
			"button": token,
			"button_index": button_index,
			"device": device,
		})
	for raw_token in (raw_joy_axes as Array):
		if not (raw_token is String):
			_fail(OP_ERROR_INVALID_PARAMS, "joy_axes must be an array of <axis>[:<sign>] tokens")
			return
		var token: String = raw_token
		var parsed := _parse_joy_axis_token(token)
		if parsed.is_empty():
			_fail(OP_ERROR_INVALID_KEY, "cannot resolve joypad axis direction: " + token
					+ " — expected <axis>[:<sign>] with sign + or - (default +) and an axis"
					+ " named (case- and separator-insensitive): "
					+ _joy_name_list(JOY_AXIS_BY_NAME)
					+ "; or an index 0.." + str(JOY_AXIS_MAX - 1))
			return
		var axis: int = parsed["axis"]
		var axis_value: float = parsed["axis_value"]
		var event := InputEventJoypadMotion.new()
		event.device = device
		event.axis = axis as JoyAxis
		event.axis_value = axis_value
		events.append(event)
		reported_events.append({
			"kind": "joy_axis",
			"axis": token,
			"axis_index": axis,
			"axis_value": axis_value,
			"device": device,
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
	var action_name := VALUE._string_param(params, "name")
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
			return GDSCRIPT_SCAN._first_token(rest)
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
	var write_err := _file_write._atomic_write_text(path, source)
	if write_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _file_write._save_failure_message(noun, path, write_err))
		return false
	return true


# --- project static-analysis reads (issue #116) -----------------------------
#
# Four read-only, project-wide reads, backed by TWO static scans over different
# file universes. find-references, dependencies and find-unused-resources share
# the extension-filtered scan (_collect_resource_paths); statistics counts with
# the unfiltered one (_collect_all_file_paths), which also sees the .import
# sidecars and project.godot the other excludes — so its file total does not
# reconcile with the others' candidate set. The two scans share one traversal
# (_collect_paths) and one directory-exclusion rule (_should_descend), which is
# what keeps them from disagreeing about the TREE while ranging over different
# files within it.
#
# Both scans read files as TEXT — parsing each .tscn/.tres for its
# [ext_resource path="..."] entries and each .gd for its preload/load/extends
# references — and never instantiate a scene or load/compile a script (the read
# trust boundary of issue #30). Reads still run under --project, so the engine
# constructs the project's autoloads at startup before _initialize (the residual
# project-code execution of issue #61); the scans themselves add none.
#
# The THREE reference-graph reads share one graph so they stay consistent
# (acceptance criterion): find-references reports the incoming references of one
# target; dependencies reports the outgoing references of every scene/resource;
# find-unused-resources reports the resources with no incoming reference (and not
# an entry point). A resource is "unused" exactly when find-references for it
# would return empty — the same graph, one truth. statistics is not on that graph:
# it only counts what its own scan reaches.
#
# ONE graph needs ONE identity per file, and that identity is the path the ENGINE
# resolves a declaration to — not the string the declaration spells. Two spellings
# reach the same file:
#
# - an ALIAS of an absolute address (res://leaf.tscn and res://sub/../leaf.tscn),
#   folded by _canonical_resource_path, the engine's own simplify_path;
# - a RELATIVE address, which the engine resolves against the DECLARING file's
#   own directory — `path="../shared/leaf.tscn"` in res://scenes/main.tscn loads
#   res://shared/leaf.tscn (measured on 4.6.3), and `preload("../shared/x.gd")`
#   in res://scripts/user.gd loads res://shared/x.gd (measured likewise).
#
# So every path that enters the graph is folded by the ONE owner that knows its
# base directory — _resolve_ref_path, for an [ext_resource] line and for a
# preload/load/extends argument alike. Only two entrants have no
# declaring file to anchor to and are absolute by construction — project.godot's
# main scene and autoloads, and the caller's find-references query — and those go
# straight to _canonical_resource_path.
#
# Keying on the raw spelling broke all three reads at once (#774): dependencies
# named a node no file on disk answers to, find-references for the resolved path
# missed the declaration, and find-unused-resources therefore advised DELETING a
# scene the project instances — wrong advice with a destructive follow-up. The
# other side of every comparison is canonical by construction: the walk builds each
# path by joining directory entries, never by echoing a declaration.


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
	var target := VALUE._string_param(params, "target")
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
		# The query is canonicalized like every harvested path (#774), so a caller
		# that spells the target res://sub/../leaf.tscn asks about the same node
		# the graph keys res://leaf.tscn under. The echoed "target" keeps the
		# caller's own spelling — it also carries a class_name, which is no path.
		target_paths[SCENE_TEXT._canonical_resource_path(target)] = true
	else:
		# Resolve the class_name through the SAME unified resolver node add /
		# resource create use (ADR-0032), so find-references and resource create
		# agree on whether a class resolves in an editor-never-opened project, and
		# a class_name declared in more than one .gd is the shared ambiguous error.
		var resolution := CLASS_INDEX._resolve_project_class_script(target)
		match resolution["status"]:
			"resolved":
				target_class = target
				target_paths[SCENE_TEXT._canonical_resource_path(String(resolution["path"]))] = true
			"ambiguous":
				_fail(OP_ERROR_AMBIGUOUS_CLASS_NAME, CLASS_INDEX._ambiguous_class_name_message(target, resolution["paths"]))
				return
			_:
				_fail(OP_ERROR_INVALID_TARGET, "find-references target is not a res:// path, and no .gd script declares class_name " + target + " (check for a misspelled name): " + target)
				return

	var paths: Array[String] = []
	PROJECT_WALK._collect_resource_paths("res://", paths)
	paths.sort()

	var references: Array = []
	for path in paths:
		REFERENCE_GRAPH._collect_references_from(path, target_paths, target_class, references)
	# Project-level references (autoloads, the main scene) live in
	# project.godot, not in a scanned file — add them from ProjectSettings.
	REFERENCE_GRAPH._collect_project_level_references(target_paths, references)

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
	PROJECT_WALK._collect_resource_paths("res://", paths)
	paths.sort()

	var dependencies: Array = []
	for path in paths:
		# Only resources that can declare ext_resource dependencies (.tscn/.tres)
		# and scripts (.gd, via preload/load) are reported as dependency sources;
		# a leaf asset (an image) has no outgoing references to map.
		if not REFERENCE_GRAPH._has_outgoing_references(path):
			continue
		var depends_on := REFERENCE_GRAPH._outgoing_references_of(path)
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
	PROJECT_WALK._collect_resource_paths("res://", paths)
	paths.sort()

	# Build the set of every res:// path that ANY file references — the union of
	# all outgoing references across the project, the exact graph find-references
	# reads one target at a time. A path absent from this set has zero incoming
	# references (find-references would return empty for it), the consistency the
	# issue requires.
	var referenced := {}
	for path in paths:
		for dep in REFERENCE_GRAPH._outgoing_references_of(path):
			referenced[dep["path"]] = true
	# Project-level entry points are "referenced" too, so they are never reported
	# unused: the main scene and the autoloads are entered directly, not via a
	# file reference.
	for entry in REFERENCE_GRAPH._project_entry_points():
		referenced[entry] = true

	var unused: Array = []
	for path in paths:
		# A script is dead CODE, not an unused resource asset (see the op note).
		if GDSCRIPT_SCAN._is_script_path(path):
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
	PROJECT_WALK._collect_all_file_paths("res://", paths)
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
		var lines := REFERENCE_GRAPH._count_lines(path)
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
		"autoloads": REFERENCE_GRAPH._project_autoloads(),
		"plugins": REFERENCE_GRAPH._project_plugins(),
		"scene_count": scene_count,
		"script_count": script_count,
		"resource_count": resource_count,
	})


# Whether a path names a scene file in the TEXT form gda authors and reads: a
# .tscn. Two callers ask. scene-validate asks because it is the only op whose
# answer comes from the file's own text rather than from the loaded resource —
# see the refusal it raises. The scene walk asks because it lists exactly that
# universe, and reusing this predicate is what keeps the listing and the refusal
# from disagreeing about what a scene file is (#764). Every other scene op keys on
# loadability instead, so a .scn that loads is served there as before.
#
# The comparison is case-insensitive because the engine's own recognition is:
# ResourceFormatLoader::recognize_path matches the extension with nocasecmp_to.
func _is_scene_path(path: String) -> bool:
	return path.get_extension().to_lower() == "tscn"


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


# Whether this headless process is running against a Godot project. A project
# scan writes the resource UID cache under res://.godot; its presence is the
# marker the engine itself uses, and a projectless --script run (no --path to a
# project dir) does not have it. scene-list needs a real res:// tree to walk.
func _has_project() -> bool:
	return DirAccess.dir_exists_absolute("res://") and FileAccess.file_exists("res://project.godot")


# Recursively collect every .tscn under res:// (issue #54) over the shared
# traversal, which enumerates hidden entries and asks _should_descend about every
# directory. Paths are returned as res:// paths so they round-trip into other
# scene commands.
#
# The acceptance test is _is_scene_path, so the extension is matched WITHOUT
# regard to case. It used to be matched case-sensitively here and only here, and
# that made one project answer two ways: `project statistics` counted a Level.TSCN
# as a scene (it lowercases the extension before classifying) while `scene list`
# could not see it at all. The engine is the arbiter and it is case-insensitive —
# ResourceFormatLoader::recognize_path compares the extension with nocasecmp_to
# (core/io/resource_loader.cpp), ResourceSaver does the same, and the editor's own
# filesystem scan lowercases every extension before classifying it
# (editor/file_system/editor_file_system.cpp). A Level.TSCN IS a scene to Godot,
# so `scene list` now reports it; that listing is the one output this change grew
# (#764).
func _collect_scene_paths(dir_path: String, out: Array[String]) -> void:
	PROJECT_WALK._collect_paths(dir_path, _is_scene_path, out)


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
	var root_fields := _scene_store._state_node_projection_fields(state, 0)
	var instance_paths := SCENE_TEXT._scene_instance_paths_by_node_path(path)
	if instance_paths.has("."):
		var instance_path := String(instance_paths["."])
		root_fields["instance_path"] = instance_path
		if not root_fields.has("instance_status"):
			root_fields["instance_status"] = _scene_store._scene_instance_status_for_path(instance_path)
	return {
		"path": path,
		"root_name": String(state.get_node_name(0)),
		"root_type": root_fields["type"],
		"root_instance_path": root_fields.get("instance_path", null),
		"root_instance_status": root_fields.get("instance_status", null),
	}


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


# Like _fail_node_not_found but names which endpoint of a connection failed
# ("source"/"target", issue #57), so an agent knows which node path to fix.
func _fail_node_not_found_labeled(label: String, node_path: String) -> void:
	if _scene_store._is_canonical_parent_path(node_path):
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
	var resolution := CLASS_INDEX._resolve_project_class_script(type)
	match resolution["status"]:
		"resolved":
			return _instantiate_script_class(type, String(resolution["path"]))
		"ambiguous":
			_fail(OP_ERROR_AMBIGUOUS_CLASS_NAME, CLASS_INDEX._ambiguous_class_name_message(type, resolution["paths"]))
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
	var unmaterialized := _scene_store._unmaterialized_node_paths(packed.get_state(), child)
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
	var instance: Variant = CLASS_INDEX._new_script_instance(script)
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
	var resolution := CLASS_INDEX._resolve_project_class_script(type)
	match resolution["status"]:
		"resolved":
			return _instantiate_resource_script_class(type, String(resolution["path"]))
		"ambiguous":
			_fail(OP_ERROR_AMBIGUOUS_CLASS_NAME, CLASS_INDEX._ambiguous_class_name_message(type, resolution["paths"]))
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
	var instance: Variant = CLASS_INDEX._new_script_instance(script)
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


func _has_int_param(params: Dictionary, key: String) -> bool:
	return params.has(key) and params[key] != null


func _int_param(params: Dictionary, key: String) -> int:
	return int(params.get(key, 0))


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


# The ONE JSON writer for every headless reply (#771) — the same choice the live
# harness made in #752, for the same reason, because it is the same engine
# function. Godot's default JSON.stringify renders a float through String::num,
# which formats FIXED-POINT with at most MAX_DECIMALS (32) decimals: it flattened
# every value below ~1e-32.6 to 0.0 and rounded ordinary values to ~15 significant
# digits (3.141592653589793 came back as 3.14159265358979, and an @export of
# 1e-300 read back as 0.0). The full_precision argument switches it to
# String::num_scientific (grisu2, shortest round-tripping form), which loses none
# of those and still spells every float with a "." or an "e", so a JSON number
# that was a float stays one. The measured corpus and its counts belong to the one
# authority that owns them, `gda.live_numbers` (Python side) — not restated here.
# The other three arguments keep their defaults ("" indent, sort_keys true), so
# ONLY the number spelling changes. One residual, disclosed in the CLI contract:
# the engine emits "0.0" for a NEGATIVE ZERO before this argument is consulted.
#
# This is the REPORTING half. The way IN — the --value string the ops coerce with
# String.to_float(), the engine's own parser — is answered by #772, in the shared
# coercion block above: a literal that parser turns into 0.0 or NaN although the
# caller did not write a zero is REFUSED, and its low-order drift is disclosed.
func _json(value: Variant) -> String:
	return JSON.stringify(value, "", true, true)


# Record a successful result: emit it through the sentinel contract and mark
# the process to exit 0. The single quit() lives in _process.
func _succeed(payload: Dictionary) -> void:
	print(RESULT_BEGIN + _json(payload) + RESULT_END)
	_exit_code = 0


func _diag(message: String) -> void:
	printerr(DIAG_PREFIX + message)


# Record a structured failure through the ADR-0002 sentinel contract. The
# process is left to exit non-zero via _process.
func _fail(code: String, message: String) -> void:
	print(RESULT_BEGIN + _json({
		"error": {
			"code": code,
			"message": message,
		},
	}) + RESULT_END)
	_exit_code = 1
