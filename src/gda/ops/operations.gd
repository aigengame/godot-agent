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

const OP_ERROR_USAGE := "usage_error"
const OP_ERROR_UNKNOWN_OPERATION := "unknown_operation"
const OP_ERROR_INVALID_PARAMS := "invalid_params"
const OP_ERROR_INVALID_PATH := "invalid_path"
const OP_ERROR_INVALID_ROOT_TYPE := "invalid_root_type"
const OP_ERROR_INVALID_ROOT_NAME := "invalid_root_name"
const OP_ERROR_ALREADY_EXISTS := "already_exists"
const OP_ERROR_SAVE_FAILED := "save_failed"
const OP_ERROR_PATH_NOT_FOUND := "path_not_found"
const OP_ERROR_NOT_A_SCENE := "not_a_scene"
const OP_ERROR_PARENT_NOT_FOUND := "parent_not_found"
const OP_ERROR_INVALID_NODE_TYPE := "invalid_node_type"
const OP_ERROR_INVALID_NODE_NAME := "invalid_node_name"
const OP_ERROR_DUPLICATE_NODE_NAME := "duplicate_node_name"
const OP_ERROR_MISSING_DEPENDENCY := "missing_dependency"

const NODE_NAME_INVALID_CHARS := [".", ":", "@", "/", "\"", "%"]

# The exit code the process will use. Defaults to failure, so an operation that
# aborts before recording an outcome (e.g. an uncaught runtime error) still
# exits non-zero rather than reporting a phantom success.
var _exit_code := 1


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
		"node-add":
			_op_node_add(params)
		"node-list":
			_op_node_list(params)
		_:
			_fail(OP_ERROR_UNKNOWN_OPERATION, "unknown operation: " + operation)


# Quit on the first idle frame, whatever happened during _initialize — this is
# the single exit point and the watchdog against a hung main loop (issue #31).
func _process(_delta: float) -> bool:
	quit(_exit_code)
	return true


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
	if root_type.is_empty() or not ClassDB.can_instantiate(root_type) \
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

	var packed := PackedScene.new()
	var pack_err := packed.pack(root)
	if pack_err != OK:
		root.free()
		_fail(OP_ERROR_SAVE_FAILED, "failed to pack scene: " + error_string(pack_err))
		return
	var created_dirs: Variant = _ensure_parent_dirs(path)
	if created_dirs == null:
		root.free()
		return
	var save_err := ResourceSaver.save(packed, path)
	root.free()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message(path, save_err))
		return

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

	_succeed({
		"path": _string_param(params, "path"),
		"root": _tree_from_state(packed.get_state()),
	})


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
	var packed: PackedScene = _load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var path := _string_param(params, "path")

	var node_name := _string_param(params, "name")
	if not _is_valid_node_name(node_name):
		_fail(OP_ERROR_INVALID_NODE_NAME, "invalid name: " + node_name)
		return

	var root: Node = packed.instantiate()
	if root == null:
		# The engine returns null for a scene it cannot instantiate at all —
		# e.g. an instanced sub-scene whose resource loads but instantiates to
		# nothing (packed_scene.cpp propagates the nested null). Nothing exists
		# to edit or save, so refuse with the dependency code.
		_fail(OP_ERROR_MISSING_DEPENDENCY, "scene failed to instantiate: " + path
				+ " — an instanced sub-scene is unresolvable or empty; check the scene's dependencies and --project")
		return
	var vanished := _vanished_node_paths(packed.get_state(), root)
	if not vanished.is_empty():
		root.free()
		_fail(OP_ERROR_MISSING_DEPENDENCY, "scene nodes vanished on load (unresolvable instanced sub-scene?): "
				+ ", ".join(vanished) + " — re-saving would silently drop them; check the scene's dependencies and --project")
		return
	var parent_path := _string_param(params, "parent")
	var parent := _resolve_parent(root, parent_path)
	if parent == null:
		root.free()
		_fail(OP_ERROR_PARENT_NOT_FOUND, "parent node not found in scene: " + parent_path)
		return
	if parent.get_node_or_null(NodePath(node_name)) != null:
		root.free()
		_fail(OP_ERROR_DUPLICATE_NODE_NAME, "parent " + parent_path + " already has a child named: " + node_name)
		return

	var type := _string_param(params, "type")
	var node := _instantiate_node_type(type)
	if node == null:
		root.free()
		_fail(OP_ERROR_INVALID_NODE_TYPE, "not an instantiable Node class or registered class_name: " + type)
		return

	node.name = node_name
	var actual_name := String(node.name)
	if actual_name != node_name:
		node.free()
		root.free()
		_fail(OP_ERROR_INVALID_NODE_NAME, "Godot rewrote name from " + node_name + " to " + actual_name)
		return
	parent.add_child(node)
	node.owner = root

	var repacked := PackedScene.new()
	var pack_err := repacked.pack(root)
	if pack_err != OK:
		root.free()
		_fail(OP_ERROR_SAVE_FAILED, "failed to pack scene: " + error_string(pack_err))
		return
	var node_path := String(root.get_path_to(node))
	var node_type := node.get_class()
	var script_class: Variant = _script_class_of(node)
	var save_err := ResourceSaver.save(repacked, path)
	root.free()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message(path, save_err))
		return

	_succeed({
		"scene_path": path,
		"path": node_path,
		"name": actual_name,
		"type": node_type,
		"script_class": script_class,
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

	_succeed({
		"scene_path": _string_param(params, "path"),
		"root": _tree_from_state(packed.get_state(), true),
	})


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


# Node paths declared in the scene's state that did not materialize in the
# instantiated tree — typically an instanced sub-scene whose ext_resource
# could not be resolved (missing file, or res:// without project context).
# The engine instantiates such a scene WITHOUT the vanished nodes (issue #64),
# so re-packing and saving would silently erase them — the instance, its
# overrides, and its editable marker — from the file. Mutation must refuse
# before saving rather than report success over that data loss.
func _vanished_node_paths(state: SceneState, root: Node) -> Array[String]:
	var vanished: Array[String] = []
	for i in range(1, state.get_node_count()):
		var state_path := String(state.get_node_path(i)).trim_prefix("./")
		if root.get_node_or_null(NodePath(state_path)) == null:
			vanished.append(state_path)
	return vanished


# Resolve a parent node path against the scene root. Node-path addressing
# (issue #53) is relative to the scene root: '.' is the root itself,
# 'Player/Arm' a descendant. Absolute paths are rejected — they would require
# the scene to live inside a SceneTree, which a loaded-for-editing tree does not.
func _resolve_parent(root: Node, parent_path: String) -> Node:
	if parent_path.is_empty():
		return null
	var node_path := NodePath(parent_path)
	if node_path.is_absolute():
		return null
	return root.get_node_or_null(node_path)


# Instantiate a node by type: a built-in Node class first, then a class_name
# from the project's global class list (script classes register only once the
# project has been imported/scanned). Returns null when the type resolves to
# nothing instantiable as a Node.
func _instantiate_node_type(type: String) -> Node:
	if type.is_empty():
		return null
	if ClassDB.can_instantiate(type) and ClassDB.is_parent_class(type, "Node"):
		return ClassDB.instantiate(type)
	for entry in ProjectSettings.get_global_class_list():
		if String(entry.get("class", "")) != type:
			continue
		var script := ResourceLoader.load(String(entry.get("path", ""))) as Script
		if script == null:
			return null
		var instance: Variant = script.new()
		if instance is Node:
			return instance
		if instance is Object and not (instance is RefCounted):
			instance.free()
		return null
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


# Build the structured node tree from a SceneState. The state lists nodes in
# tree order; each carries a node path ("." for the root, "./Hero/Hitbox" for
# a descendant) and the path to its parent, which is enough to reconstruct the
# parent/child structure without instantiating anything. with_paths includes
# each node's path in the emitted tree (node-list's addressing contract),
# normalized to the root-relative form node add accepts and reports: the
# state's "./Hero" prefix form becomes "Hero", the root stays ".".
func _tree_from_state(state: SceneState, with_paths := false) -> Dictionary:
	var by_path := {}
	var root: Dictionary = {}
	for i in state.get_node_count():
		var state_path := String(state.get_node_path(i))
		var node := {
			"name": String(state.get_node_name(i)),
			"type": String(state.get_node_type(i)),
			"children": [],
		}
		if with_paths:
			node["path"] = state_path.trim_prefix("./")
		by_path[state_path] = node
		if i == 0:
			root = node
		else:
			var parent: Variant = by_path.get(String(state.get_node_path(i, true)))
			if parent != null:
				parent["children"].append(node)
	return root


# Read a string param defensively: a non-string value (the params arrive as
# arbitrary JSON) is treated as absent rather than crashing a typed assignment,
# so a malformed param surfaces as a structured failure, not a runtime error.
func _string_param(params: Dictionary, key: String) -> String:
	var value: Variant = params.get(key, "")
	if value is String:
		return value
	return ""


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


func _save_failure_message(path: String, save_err: Error) -> String:
	var parent := path.get_base_dir()
	var message := "failed to save scene to " + path
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


# Record a successful result: emit it through the sentinel contract and mark
# the process to exit 0. The single quit() lives in _process.
func _succeed(payload: Dictionary) -> void:
	print(RESULT_BEGIN + JSON.stringify(payload) + RESULT_END)
	_exit_code = 0


func _diag(message: String) -> void:
	printerr("gda: " + message)


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
