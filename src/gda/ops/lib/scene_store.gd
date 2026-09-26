extends "../op_base.gd"

# gda headless operations payload: the scene store (ADR-0043 §2) — scene load,
# load for mutation and its #164 snapshot, repack and save, the preload-
# dependency gate that runs before a save, node addressing, and the projection
# of a stored node tree. An instance module: it reports failure through the op
# base, and it holds the file write it saves through.

const FILE_WRITE := preload("file_write.gd")
const GDSCRIPT_SCAN := preload("gdscript_scan.gd")
const SCENE_TEXT := preload("scene_text.gd")
const VALUE := preload("value.gd")

# The file write the repack-and-save tail saves through, created with this
# module's frame and held for the module's life (ADR-0043 §4).
var _file_write: FILE_WRITE


func _init(frame) -> void:
	super(frame)
	_file_write = FILE_WRITE.new(frame)


const NODE_NAME_INVALID_CHARS := [".", ":", "@", "/", "\"", "%"]


# Load the .tscn named by params.path for reading or mutation, validating the
# shared failure ladder: missing param → missing file → not loadable as a
# scene → scene without a root. Returns null after recording the failure.
func _load_scene(params: Dictionary) -> PackedScene:
	var path := VALUE._string_param(params, "path")
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
	var path := VALUE._string_param(params, "path")
	# Capture the staleness token NOW — the instant after _load_scene's
	# ResourceLoader.load read the .tscn, and BEFORE instantiate() (which runs the
	# project's script _init and can take real time, ADR-0009) or any other work.
	# Capturing here rather than after instantiate makes the baseline reflect the
	# file gda actually read, so an external edit landing during instantiate is
	# still caught by _check_unchanged at write time (issue #226; PR #234 review
	# closed this read->capture window). Covers all 8 shared-tail mutating ops.
	_file_write._capture_staleness_token(path)
	# Test seam (issue #226): simulate an external edit that lands AFTER the read
	# but DURING instantiate — the window this early capture closes. Gated by the
	# env var, so it is dead code in production (mirrors GDA_TEST_PERTURB_BEFORE_SAVE).
	if OS.has_environment("GDA_TEST_PERTURB_AFTER_LOAD"):
		_file_write._test_perturb_target(path)
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
	if not _file_write._check_unchanged():
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
	var save_err := _file_write._atomic_save_resource(repacked, path)
	root.free()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _file_write._save_failure_message("scene", path, save_err))
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
	_source_attached_scripts = SCENE_TEXT._scene_attached_external_scripts(scene_path)


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
	for ref_path in GDSCRIPT_SCAN._script_executable_preload_paths(script_path):
		if not ref_path.begins_with("res://"):
			continue
		if FileAccess.file_exists(ref_path):
			continue
		_fail(OP_ERROR_MISSING_DEPENDENCY, "script preload target does not exist: "
				+ ref_path + " (referenced by " + script_path
				+ ") — create the preloaded asset before attaching or saving the script")
		return false
	return true


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


func _is_valid_node_name(node_name: String) -> bool:
	if node_name.is_empty():
		return false
	for invalid_char in NODE_NAME_INVALID_CHARS:
		if node_name.contains(String(invalid_char)):
			return false
	return true
