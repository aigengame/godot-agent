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
const OP_ERROR_DELETE_FAILED := "delete_failed"
const OP_ERROR_PROJECT_NOT_FOUND := "project_not_found"
const OP_ERROR_PATH_NOT_FOUND := "path_not_found"
const OP_ERROR_NOT_A_SCENE := "not_a_scene"
const OP_ERROR_PARENT_NOT_FOUND := "parent_not_found"
const OP_ERROR_INVALID_NODE_TYPE := "invalid_node_type"
const OP_ERROR_INVALID_NODE_NAME := "invalid_node_name"
const OP_ERROR_DUPLICATE_NODE_NAME := "duplicate_node_name"
const OP_ERROR_MISSING_DEPENDENCY := "missing_dependency"
const OP_ERROR_UNINSTANTIABLE_SCRIPT := "uninstantiable_script"
const OP_ERROR_NODE_NOT_FOUND := "node_not_found"
const OP_ERROR_CANNOT_TARGET_ROOT := "cannot_target_root"
const OP_ERROR_CYCLIC_TARGET := "cyclic_target"
const OP_ERROR_UNKNOWN_PROPERTY := "unknown_property"
const OP_ERROR_UNCOERCIBLE_VALUE := "uncoercible_value"
const OP_ERROR_NO_SEARCH_MATCH := "no_search_match"
const OP_ERROR_INVALID_LINE_RANGE := "invalid_line_range"
const OP_ERROR_SCRIPT_COMPILE_FAILED := "script_compile_failed"
const OP_ERROR_INCOMPATIBLE_SCRIPT_TYPE := "incompatible_script_type"
const OP_ERROR_SIGNAL_NOT_FOUND := "signal_not_found"
const OP_ERROR_ALREADY_CONNECTED := "already_connected"
const OP_ERROR_CONNECTION_NOT_FOUND := "connection_not_found"
const OP_ERROR_INVALID_RESOURCE_TYPE := "invalid_resource_type"

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
		"scene-get-exports":
			_op_scene_get_exports(params)
		"scene-list":
			_op_scene_list(params)
		"scene-delete":
			_op_scene_delete(params)
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

	_succeed({
		"path": _string_param(params, "path"),
		"root": _tree_from_state(packed.get_state()),
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

	var type := _string_param(params, "type")
	var node := _instantiate_node_type(type)
	if node == null:
		root.free()
		return  # _instantiate_node_type already recorded the failure

	# A parentless node never has its name rewritten: _is_valid_node_name already
	# rejected the chars Godot sanitizes, and the @-dedup suffix is only appended
	# inside add_child (already guarded by the duplicate-name check above). So the
	# assigned name is final; no post-assignment recheck is needed.
	node.name = node_name
	parent.add_child(node)
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
	var declared_type := _property_type(node, prop_name)
	if declared_type == TYPE_NIL:
		root.free()
		_fail(OP_ERROR_UNKNOWN_PROPERTY, "node " + node_path
				+ " has no settable property: " + prop_name)
		return

	var raw_value := _string_param(params, "value")
	var coerced: Variant = _coerce_value(raw_value, declared_type)
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
	var stored_value: Variant = _jsonify(node.get(prop_name))
	if not _repack_and_save(root, path):
		return  # _repack_and_save already recorded the failure (and freed root)

	_succeed({
		"scene_path": path,
		"path": node_path,
		"property": prop_name,
		"type": _type_name(declared_type),
		"value": stored_value,
	})


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

	# Same-parent move: the node is already under the requested parent, so this is
	# a successful no-op. Report its current identity and return WITHOUT reparenting
	# or re-saving — re-homing it under the same parent would append it to the end
	# and silently reorder siblings (issue #56 review), and there is nothing to
	# persist that is not already on disk.
	if node.get_parent() == target:
		var here_name := String(node.name)
		var here_type := node.get_class()
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

	# reparent(target, false) preserves the moved node's and its descendants'
	# owners (so an instanced sub-scene keeps its overrides and editable marker)
	# and keeps the node's LOCAL transform (a purely structural move, no churn).
	node.reparent(target, false)

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

	# Dispatch on the explicit mode discriminator the CLI resolved (issue #133):
	# the edit mode is decided once, at the CLI's mutual-exclusion check, and rides
	# through on `mode` — the op never re-infers it from which params are present,
	# so the op's dispatch can no longer drift from the CLI's exclusivity rule.
	var mode := _string_param(params, "mode")
	var new_source: Variant
	match mode:
		"search_replace":
			new_source = _apply_search_replace(source, params)
		"line_range":
			new_source = _apply_line_range(source, params)
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
func _apply_search_replace(source: String, params: Dictionary) -> Variant:
	var search := _string_param(params, "search")
	var replace := _string_param(params, "replace")
	if search.is_empty() or not source.contains(search):
		_fail(OP_ERROR_NO_SEARCH_MATCH, "search string not found in script: " + search.c_escape())
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
func _apply_line_range(source: String, params: Dictionary) -> Variant:
	var newline := "\r\n" if source.contains("\r\n") else "\n"
	var lines := source.split(newline)
	var line_count := lines.size()
	var start_line := int(params.get("start_line", 0))
	var end_line: int = int(params.get("end_line", start_line)) if params.get("end_line", null) != null else start_line
	if start_line < 1 or start_line > line_count or end_line < start_line or end_line > line_count:
		_fail(OP_ERROR_INVALID_LINE_RANGE, "line range " + str(start_line) + ".." + str(end_line)
				+ " is outside the script's bounds (1.." + str(line_count) + ") or ends before it starts")
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


# script-validate: syntax/compile-check a .gd script (issue #118). Read the file
# text, set it on a fresh GDScript at the script's REAL res:// path, and reload()
# it: err == OK means it compiles. Validating an INVALID script is a SUCCESSFUL
# operation — the op exits 0 with valid=false; the op only FAILS (non-zero) for op
# errors (empty/non-.gd path → invalid_path, missing/unreadable file →
# path_not_found).
#
# Unlike the other script-file ops, validate DOES compile the script (reload
# parses and compiles it), but it never INSTANTIATES it, so it does not run the
# script's instance code. The line/message of a compile error are not available
# from any bound API (is_valid() is not even callable from GDScript) — only from
# the engine's stderr — so the op emits just {path, valid, error_string} in the
# sentinel and gda parses the advisory line/message diagnostics from stderr.
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
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_script(path):
		return  # _require_existing_script already recorded the failure

	var source: Variant = _read_script_source(path)
	if source == null:
		return  # _read_script_source already recorded the failure

	# Compile-check without instantiating: set the source on a fresh GDScript at the
	# script's real res:// path and reload() it. The reload error (and its
	# diagnostics on stderr) is the verdict; the real path makes relative preloads
	# resolve as in-engine (issue #131).
	var script := GDScript.new()
	script.source_code = source
	script.take_over_path(path)
	var err := script.reload()
	_succeed({
		"path": path,
		"valid": err == OK,
		"error_string": null if err == OK else error_string(err),
	})


# resource-create: instantiate a Resource of the requested type and save it as a
# .tres at the requested path — the resource group's save tracer (issue #112).
# Establishes the .tres load/save plumbing the rest of the group reuses.
#
# No-clobber: an existing target is refused with already_exists, leaving it
# untouched (mirrors scene-create / script-create). The type must be an
# instantiable Resource subclass — an unknown type or a non-Resource class (e.g.
# a Node) is refused with invalid_resource_type, parallel to scene-create's
# invalid_root_type check against Node. A plain Resource holds data, so creating
# one runs no project code (it constructs an engine class, not a script).
func _op_resource_create(params: Dictionary) -> void:
	_diag("running operation: resource-create")
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _is_resource_path(path):
		_fail(OP_ERROR_INVALID_PATH, "resource path must end in .tres: " + path)
		return
	var type := _string_param(params, "type")
	if type.is_empty() or not ClassDB.can_instantiate(type) \
			or not ClassDB.is_parent_class(type, "Resource"):
		_fail(OP_ERROR_INVALID_RESOURCE_TYPE, "not an instantiable Resource class: " + type)
		return
	if FileAccess.file_exists(path) or DirAccess.dir_exists_absolute(path):
		_fail(OP_ERROR_ALREADY_EXISTS, "resource target already exists: " + path)
		return

	var resource: Resource = ClassDB.instantiate(type)
	var created_dirs: Variant = _ensure_parent_dirs(path)
	if created_dirs == null:
		return  # _ensure_parent_dirs already recorded the failure
	var save_err := ResourceSaver.save(resource, path)
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message("resource", path, save_err))
		return

	_succeed({
		"path": path,
		"type": type,
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


# Recursively collect every .tscn under res:// (issue #54), skipping only the
# engine's own res://.godot cache directory (import artifacts, not authored
# scenes). The skip is scoped to that one directory name rather than every
# dot-prefixed entry, so legitimately hidden scenes (a .hidden.tscn, or a scene
# under a dot-prefixed directory) are still enumerated as promised (issue #54
# review). Paths are returned as res:// paths so they round-trip into other
# scene commands.
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
			if entry != ".godot":
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
	return {
		"path": path,
		"root_name": String(state.get_node_name(0)),
		"root_type": String(state.get_node_type(0)),
	}


# Recursively collect every .gd script under res:// (issue #117), skipping only
# the engine's own res://.godot cache directory. Mirrors _collect_scene_paths
# (issue #54): hidden entries are enumerated (a .hidden.gd, or a script under a
# dot-prefixed directory), navigational entries stay off, and the skip is scoped
# to res://.godot alone. Paths are returned as res:// paths so they round-trip
# into other script commands.
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
			if entry != ".godot":
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
	var root: Node = packed.instantiate()
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
	var repacked := PackedScene.new()
	var pack_err := repacked.pack(root)
	if pack_err != OK:
		root.free()
		_fail(OP_ERROR_SAVE_FAILED, "failed to pack scene: " + error_string(pack_err))
		return false
	var save_err := ResourceSaver.save(repacked, path)
	root.free()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message("scene", path, save_err))
		return false
	return true


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


# Instantiate a node by type: a built-in Node class first, then a class_name
# from the project's global class list (script classes register only once the
# project has been imported/scanned). Records the failure itself and returns
# null when the type resolves to nothing instantiable as a Node, telling apart
# the two distinct failure modes (issue #65): a type that resolves to nothing
# is invalid_node_type, while a registered class_name whose script broke since
# registration is uninstantiable_script — repair the script, not the type name.
func _instantiate_node_type(type: String) -> Node:
	if not type.is_empty() and ClassDB.can_instantiate(type) and ClassDB.is_parent_class(type, "Node"):
		return ClassDB.instantiate(type)
	for entry in ProjectSettings.get_global_class_list():
		if String(entry.get("class", "")) == type:
			return _instantiate_script_class(type, String(entry.get("path", "")))
	_fail(OP_ERROR_INVALID_NODE_TYPE, "not an instantiable Node class or registered class_name: " + type)
	return null


# Instantiate a registered class_name from its script. Registration only
# proves the script was valid when the project was last scanned — the script
# on disk may have broken since (issue #65), so each step is checked and a
# failure reported as the script problem it is, never as an unknown type.
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
			node["path"] = _normalize_state_path(state, i)
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


# The Godot type name for a Variant.Type, as node get / node set report it
# (the same spelling type_string uses: "int", "Vector2", "Color", …).
func _type_name(type: int) -> String:
	return type_string(type)


# Project a Godot property value into JSON-safe form for the result payload
# (issue #55). Scalars pass through; the packed value types node set supports
# become flat number arrays so node get's output is exactly the projection node
# set accepts back: Vector2 → [x, y], Vector2i likewise, Color → [r, g, b, a].
# Any other type degrades to its string form rather than crashing JSON.stringify
# on an unencodable Variant — node get reports the whole storage surface, but
# only the coercible types claim a structured projection.
func _jsonify(value: Variant) -> Variant:
	match typeof(value):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STRING, TYPE_STRING_NAME:
			return value
		TYPE_VECTOR2:
			return [value.x, value.y]
		TYPE_VECTOR2I:
			return [value.x, value.y]
		TYPE_COLOR:
			return [value.r, value.g, value.b, value.a]
		_:
			return str(value)


# Coerce a CLI string value to a property's declared Godot type (issue #55).
# The supported types and their accepted string forms are documented in the
# command catalog's "Property value coercion" section — keep the two in sync.
# Returns null when the value cannot be coerced to that type, which the caller
# reports as the clean uncoercible_value error. null is unambiguous as a
# failure signal because no supported target type coerces TO null.
func _coerce_value(raw: String, type: int) -> Variant:
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
# script create and script set, the two ops that write script text.
func _write_script_file(path: String, source: String) -> bool:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message("script", path, FileAccess.get_open_error()))
		return false
	file.store_string(source)
	var write_err := file.get_error()
	file.close()
	if write_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message("script", path, write_err))
		return false
	return true


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
