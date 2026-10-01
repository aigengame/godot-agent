extends "../op_base.gd"

# gda headless operations payload: the node command group (ADR-0043). The
# entry, operations.gd, creates one instance per run and dispatches the group's
# operations to it.

const VALUE := preload("../lib/value.gd")
const SCENE_TEXT := preload("../lib/scene_text.gd")
const CLASS_INDEX := preload("../lib/class_index.gd")
const OBJECT_REF := preload("../lib/object_ref.gd")
const SCENE_STORE := preload("../lib/scene_store.gd")

# The instance concept modules this group's operations call, created with the
# group's frame and held for the group's life (ADR-0043 §4).
var _object_ref: OBJECT_REF
var _scene_store: SCENE_STORE


func _init(frame) -> void:
	super(frame)
	_object_ref = OBJECT_REF.new(frame)
	_scene_store = SCENE_STORE.new(frame)


# node-add: load a .tscn, add a child node under a parent node path, pack and
# save it back — the node-group mutate tracer (issue #53). The parent is
# addressed by node path relative to the scene root ('.' is the root itself).
#
# Unlike the read operations, mutation REQUIRES instantiating the scene — only
# a real node tree can be edited and re-packed. Instantiating runs the _init
# of any script attached in the scene, so node-add executes project code where
# scene-get (issue #30) deliberately does not; likewise creating a class_name
# node runs that script's constructor. Inherent to headless file mutation.
#
# A parent inside an instanced child the root does not hold as editable is
# refused with cannot_target_foreign: the packer skips the parent's subtree, so
# the file would record nothing of the new node (#1054).
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
	if _scene_store._refuse_foreign_write(root, SCENE_STORE.Write.ADD_UNDER, parent):
		root.free()
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
	# The instanced scene as the file stores it (#1055), not as the caller spelled
	# it: PackedScene.instantiate stamps the loaded scene's resource_path as the
	# child's scene_file_path, and the packer loads that path to write the
	# ext_resource entry (scene/resources/packed_scene.cpp L2519-L2521 and L846
	# at 4.6.3-stable). A filesystem spelling therefore echoes as res://.
	var instance: Variant = node.scene_file_path if instance_path != "" else null
	if not _scene_store._repack_and_save(root, path):
		return  # _repack_and_save already recorded the failure (and freed root)

	_succeed({
		"scene_path": path,
		"path": node_path,
		"name": node_name,
		"type": node_type,
		"script_class": script_class,
		"instance": instance,
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
		"root": _scene_store._composed_tree(packed, true),
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
# unresolvable instance or downgrade a substituted class. A node inside an
# instanced child the root does not hold as editable is refused with
# cannot_target_foreign: the file would record nothing of the write (#1054).
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
	if _scene_store._refuse_foreign_write(root, SCENE_STORE.Write.SET, node):
		root.free()
		return

	var prop_name := VALUE._string_param(params, "property")
	if VALUE._is_control_position_write(node, prop_name):
		var control: Control = node as Control
		if VALUE._has_container_parent(control):
			# Read the message BEFORE the tree is freed: it asks the control's
			# parent for the inputs it carries.
			var refusal := VALUE._control_position_unavailable_message("node " + node_path, control)
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


# node-remove: load a .tscn, resolve a node by node path, delete it and its
# whole subtree, then re-pack and save — the first structural edit of issue #56.
# As a mutating op it goes through the shared mutate-entry (load → instantiate →
# unmaterialized-node guard), so it honors the mutation-integrity boundary
# (issue #64): a re-save never silently drops an unresolvable instance.
#
# The scene root has no parent to be detached from, and the re-pack needs a
# root, so removing '.' is refused with cannot_target_root rather than emptying
# the scene. A Foreign node — one the scene inherits, or one inside an instanced
# child — is refused with cannot_target_foreign: the file has no entry that could
# delete it (#1049, ADR-0044). A node path that resolves to nothing is
# node_not_found, the same code (and resolver) node get / node set use.
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
	if _scene_store._refuse_foreign_write(root, SCENE_STORE.Write.REMOVE, node):
		root.free()
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
# node_not_found, the node group's shared code. A source whose parent — the
# copy's destination — is inside an instanced child the root does not hold as
# editable is refused with cannot_target_foreign: the packer skips that
# parent's subtree, copy included (#1054).
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
	if _scene_store._refuse_foreign_write(root, SCENE_STORE.Write.DUPLICATE, node):
		root.free()
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
#   parent to be reparented out of → cannot_target_root; a Foreign node (one the
#   scene inherits, or one inside an instanced child) → cannot_target_foreign, in
#   every form, the same-parent no-op below included (#1049, ADR-0044).
# - the target parent resolves to nothing → parent_not_found (the same code, and
#   canonical-vs-non-canonical message, node add reports for its --parent); a
#   target inside an instanced child the root does not hold as editable →
#   cannot_target_foreign: the packer skips the target's subtree, so the file
#   would lose the moved node's entry (#1054).
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
# node keeps its instance= reference, its [editable ...] marker, and the
# override entries on the nodes its own scene declares — a manual reown would
# rewrite those overrides into locally-owned type= nodes, cutting them loose from
# the instanced scene and violating the #64 mutation-integrity boundary (verified
# empirically on Godot 4.6.3). The false
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
	if _scene_store._refuse_foreign_write(root, SCENE_STORE.Write.MOVE, node):
		root.free()
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
	if _scene_store._refuse_foreign_write(root, SCENE_STORE.Write.MOVE_UNDER, node, target):
		root.free()
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
#
# A SOURCE inside an instanced child the root does not hold as editable is
# refused with cannot_target_foreign: the packer skips a connection from such a
# node (#1054). The target is not checked: a connection whose source the root
# owns stores its target by path, and saves.
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
	if _scene_store._refuse_foreign_write(root, SCENE_STORE.Write.CONNECT_FROM, source):
		root.free()
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
# A Foreign connection — one a scene in the base chain, or an instanced child's
# scene, declares — is refused with cannot_target_foreign: the file has no entry
# that could remove it (#1052, ADR-0044).
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
	if _scene_store._refuse_foreign_write(root, SCENE_STORE.Write.DISCONNECT, source, target,
			signal_name, method_name):
		root.free()
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


func _has_int_param(params: Dictionary, key: String) -> bool:
	return params.has(key) and params[key] != null


func _int_param(params: Dictionary, key: String) -> int:
	return int(params.get(key, 0))
