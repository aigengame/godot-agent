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
const OP_ERROR_SAVE_FAILED := "save_failed"
const OP_ERROR_PATH_NOT_FOUND := "path_not_found"
const OP_ERROR_NOT_A_SCENE := "not_a_scene"

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

	var root: Node = ClassDB.instantiate(root_type)
	root.name = path.get_file().get_basename()
	var root_name := String(root.name)

	var packed := PackedScene.new()
	var pack_err := packed.pack(root)
	if pack_err != OK:
		root.free()
		_fail(OP_ERROR_SAVE_FAILED, "failed to pack scene: " + error_string(pack_err))
		return
	var save_err := ResourceSaver.save(packed, path)
	root.free()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to save scene to " + path + ": " + error_string(save_err))
		return

	_succeed({
		"path": path,
		"root_name": root_name,
		"root_type": root_type,
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
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not FileAccess.file_exists(path):
		_fail(OP_ERROR_PATH_NOT_FOUND, "scene file does not exist: " + path)
		return

	var packed := ResourceLoader.load(path, "PackedScene") as PackedScene
	if packed == null:
		_fail(OP_ERROR_NOT_A_SCENE, "failed to load as a scene: " + path)
		return
	var state := packed.get_state()
	if state == null or state.get_node_count() == 0:
		_fail(OP_ERROR_NOT_A_SCENE, "scene declares no root node: " + path)
		return

	_succeed({"path": path, "root": _tree_from_state(state)})


# Build the structured node tree from a SceneState. The state lists nodes in
# tree order; each carries a node path ("." for the root, "Hero/Hitbox" for a
# descendant) and the path to its parent, which is enough to reconstruct the
# parent/child structure without instantiating anything.
func _tree_from_state(state: SceneState) -> Dictionary:
	var by_path := {}
	var root: Dictionary = {}
	for i in state.get_node_count():
		var node := {
			"name": String(state.get_node_name(i)),
			"type": String(state.get_node_type(i)),
			"children": [],
		}
		by_path[String(state.get_node_path(i))] = node
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
