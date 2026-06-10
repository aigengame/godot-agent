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
# An operation that fails reports it structurally on stderr as
# `gda-error:<code>: <message>` and quits non-zero; gda's shared classifier
# surfaces <code> as the stable GdaError.code (issue #18).

const RESULT_BEGIN := "<<<GDA:RESULT>>>"
const RESULT_END := "<<<GDA:END>>>"


func _init() -> void:
	# Everything after `--` on the Godot command line — i.e. <operation>
	# [params_json] — arrives here, independent of engine argument ordering.
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		_fail("usage: godot --headless --script operations.gd -- <operation> [params_json]")
		return

	var operation := args[0]

	var params: Dictionary = {}
	if args.size() > 1:
		var parsed: Variant = JSON.parse_string(args[1])
		if parsed == null or not (parsed is Dictionary):
			_fail("params is not a JSON object: " + args[1])
			return
		params = parsed

	# Each op returns whether it succeeded; a failing op has already quit(1),
	# so only a successful run may reach the final quit() — quitting twice
	# would overwrite the failure exit code.
	var ok: bool
	match operation:
		"info":
			ok = _op_info()
		"scene-create":
			ok = _op_scene_create(params)
		"scene-get":
			ok = _op_scene_get(params)
		_:
			_fail("unknown operation: " + operation)
			return

	if ok:
		quit()


# info: emit Engine.get_version_info() through the structured-output contract.
func _op_info() -> bool:
	_diag("running operation: info")
	_emit_result(JSON.stringify(Engine.get_version_info()))
	return true


# scene-create: instantiate a root node of the requested type, pack it, save
# it as a .tscn at the requested path (issue #18).
func _op_scene_create(params: Dictionary) -> bool:
	_diag("running operation: scene-create")
	var path: String = params.get("path", "")
	if path.is_empty():
		return _fail_op("invalid_path", "missing required param: path")
	var root_type: String = params.get("root_type", "")
	if root_type.is_empty() or not ClassDB.can_instantiate(root_type) \
			or not ClassDB.is_parent_class(root_type, "Node"):
		return _fail_op("invalid_root_type", "not an instantiable Node class: " + root_type)

	var root: Node = ClassDB.instantiate(root_type)
	root.name = path.get_file().get_basename()
	var root_name := String(root.name)

	var packed := PackedScene.new()
	var pack_err := packed.pack(root)
	if pack_err != OK:
		root.free()
		return _fail_op("save_failed", "failed to pack scene: " + error_string(pack_err))
	var save_err := ResourceSaver.save(packed, path)
	root.free()
	if save_err != OK:
		return _fail_op("save_failed", "failed to save scene to " + path + ": " + error_string(save_err))

	_emit_result(JSON.stringify({
		"path": path,
		"root_name": root_name,
		"root_type": root_type,
	}))
	return true


# scene-get: load a .tscn from disk and emit its structured node tree.
func _op_scene_get(params: Dictionary) -> bool:
	_diag("running operation: scene-get")
	var path: String = params.get("path", "")
	if path.is_empty():
		return _fail_op("invalid_path", "missing required param: path")
	if not FileAccess.file_exists(path):
		return _fail_op("path_not_found", "scene file does not exist: " + path)

	var packed := ResourceLoader.load(path, "PackedScene") as PackedScene
	if packed == null:
		return _fail_op("not_a_scene", "failed to load as a scene: " + path)
	var root := packed.instantiate()
	if root == null:
		return _fail_op("not_a_scene", "scene has no instantiable root: " + path)

	var tree := _node_dict(root)
	root.free()
	_emit_result(JSON.stringify({"path": path, "root": tree}))
	return true


func _node_dict(node: Node) -> Dictionary:
	var children: Array = []
	for child in node.get_children():
		children.append(_node_dict(child))
	return {"name": String(node.name), "type": node.get_class(), "children": children}


func _emit_result(json_payload: String) -> void:
	print(RESULT_BEGIN + json_payload + RESULT_END)


func _diag(message: String) -> void:
	printerr("gda: " + message)


# A structured operation failure: the stable finer code rides the stderr
# marker; returns false so the caller can stop without reaching quit().
func _fail_op(code: String, message: String) -> bool:
	printerr("gda-error:" + code + ": " + message)
	quit(1)
	return false


func _fail(message: String) -> void:
	_diag(message)
	quit(1)
