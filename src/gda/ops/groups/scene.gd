extends "../op_base.gd"

# gda headless operations payload: the scene command group (ADR-0043). The
# entry, operations.gd, creates one instance per run and dispatches the group's
# operations to it.

const VALUE := preload("../lib/value.gd")
const PROJECT_WALK := preload("../lib/project_walk.gd")
const SCENE_TEXT := preload("../lib/scene_text.gd")
const FILE_WRITE := preload("../lib/file_write.gd")
const SCENE_STORE := preload("../lib/scene_store.gd")
const SCENE_VALIDATE := preload("../lib/scene_validate.gd")

# The instance concept modules this group's operations call, created with the
# group's frame and held for the group's life (ADR-0043 §4).
var _file_write: FILE_WRITE
var _scene_store: SCENE_STORE


func _init(frame) -> void:
	super(frame)
	_file_write = FILE_WRITE.new(frame)
	_scene_store = SCENE_STORE.new(frame)


# Preflight readiness as INDEPENDENT evidence, not part of the result sentinel
# (#709 review): printed the moment the scene reports ready, so the fact that it
# came up survives a project that ends the run (get_tree().quit() in _ready)
# before the pending tick can emit the result. Mirrored in gda.commands.scene,
# which reads it only off a clean exit that carried no result.
const PREFLIGHT_READY_EVIDENCE := "<<<GDA:PREFLIGHT-READY>>>"


# The startup verdicts scene-preflight reports (#664). The third one an agent can
# read, `timeout`, is gda's own: only the CLI knows the launch outran its bound,
# because an engine stuck inside a scene's `_ready` never reaches an idle frame, so
# _preflight_tick never runs to report anything at all.
const SCENE_STARTUP_READY := "ready"
const SCENE_STARTUP_NOT_READY := "not_ready"


# scene-preflight's own state across those frames: the scene it booted, the path
# it reports, and whether the booted root was EVER observed ready. Latched rather
# than sampled at the end, so a scene that frees itself after starting is still
# reported as having started.
var _preflight_instance: Node = null
var _preflight_path := ""
var _preflight_ready := false
# The frame budget this preflight gave to _begin_pending, read back by its tick.
var _preflight_frame_limit := 0


# scene-create: instantiate a root node of the requested type, pack it, save
# it as a .tscn at the requested path (issue #18). With `inherits`, write an
# Inherited scene of that base instead (#1050).
func _op_scene_create(params: Dictionary) -> void:
	_diag("running operation: scene-create")
	var path := VALUE._string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	var inherits := VALUE._string_param(params, "inherits")
	var root_type := VALUE._string_param(params, "root_type")
	# class_exists gates can_instantiate: probing a name ClassDB does not know
	# logs a spurious engine ERROR (issue #377); the miss still fails as
	# invalid_root_type through the same else path.
	if inherits.is_empty() and (root_type.is_empty() or not ClassDB.class_exists(root_type) \
			or not ClassDB.can_instantiate(root_type) \
			or not ClassDB.is_parent_class(root_type, "Node")):
		_fail(OP_ERROR_INVALID_ROOT_TYPE, "not an instantiable Node class: " + root_type)
		return
	var root_name := VALUE._string_param(params, "root_name")
	if not _scene_store._is_valid_node_name(root_name):
		_fail(OP_ERROR_INVALID_ROOT_NAME, "invalid root_name: " + root_name)
		return
	if FileAccess.file_exists(path) or DirAccess.dir_exists_absolute(path):
		_fail(OP_ERROR_ALREADY_EXISTS, "scene target already exists: " + path)
		return
	if not inherits.is_empty():
		_create_inherited_scene(path, root_name, inherits)
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


# scene-create --inherits (#1050, ADR-0044 decision 5): write the text the
# engine's saver writes for an Inherited scene of `inherits`, then load it back.
# The base is LOADED, never instantiated, so its scripts run no _init. Once the
# file is written, the engine must read it back as inherited from that base —
# get_node_instance(0) on its state, the route bound at ADR-0003's 4.4 floor
# (get_base_scene_state() is bound only from 4.5) — and with `root_name` as its
# root's name; a file that fails either check is removed, so a refusal leaves no
# file. The read-back is the load the static reads perform.
func _create_inherited_scene(path: String, root_name: String, inherits: String) -> void:
	if not ResourceLoader.exists(inherits):
		_fail(OP_ERROR_MISSING_DEPENDENCY, "base scene not found: " + inherits
				+ " — --inherits must reference an existing scene file; check the path and --project")
		return
	if not ResourceLoader.exists(inherits, "PackedScene"):
		_fail(OP_ERROR_NOT_A_SCENE, "not a scene: " + inherits
				+ " — --inherits must reference a PackedScene (.tscn/.scn)")
		return
	var base := ResourceLoader.load(inherits, "PackedScene") as PackedScene
	if base == null:
		_fail(OP_ERROR_MISSING_DEPENDENCY, "base scene failed to load: " + inherits
				+ " — a dependency is missing or the file is broken; see diagnostics")
		return
	var base_path := String(base.resource_path)
	var created_dirs: Variant = _file_write._ensure_parent_dirs(path)
	if created_dirs == null:
		return  # _ensure_parent_dirs already recorded the failure
	var write_err := _file_write._atomic_write_text(path, SCENE_TEXT._inherited_scene_text(root_name, base_path))
	if write_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _file_write._save_failure_message("scene", path, write_err))
		return

	var written := ResourceLoader.load(path, "PackedScene") as PackedScene
	var state := written.get_state() if written != null else null
	var read_base: PackedScene = null
	if state != null and state.get_node_count() > 0:
		read_base = state.get_node_instance(0)
	if read_base == null or String(read_base.resource_path) != base_path:
		_file_write._remove_quiet(path)
		_fail(OP_ERROR_SAVE_FAILED, "the engine does not read " + path + " back as a scene inheriting "
				+ base_path + "; the file was removed")
		return
	var read_root_name := String(state.get_node_name(0))
	if read_root_name != root_name:
		_file_write._remove_quiet(path)
		_fail(OP_ERROR_INVALID_ROOT_NAME, "Godot read root_name " + root_name + " back as "
				+ read_root_name + "; the file was removed")
		return

	_succeed({
		"path": path,
		"root_name": read_root_name,
		"root_type": _scene_store._packed_scene_root_type(written),
		"created_dirs": created_dirs,
		"inherits": base_path,
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
		"root": _scene_store._composed_tree(packed),
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
# content removed, not just the path. The type is read through the root
# projection scene-list reads (#1055) — the same call, so the two report the
# same type at every chain depth: an inherited scene's root entry stores no
# type, so its own state alone would report "".
func _op_scene_delete(params: Dictionary) -> void:
	_diag("running operation: scene-delete")
	var packed: PackedScene = _scene_store._load_scene(params)
	if packed == null:
		return  # _load_scene already recorded the failure
	var path := VALUE._string_param(params, "path")

	var state := packed.get_state()
	var root_name := String(state.get_node_name(0))
	var root_type := String(_scene_store._state_node_projection_fields(state, 0)["type"])

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
# why _script_binding_problem asks the loaded script first.) That is the boundary
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
	_frame.root.add_child(instance)
	# So the verdict is LATCHED from the signal rather than sampled later. Sampling
	# it on the first frame was wrong for a scene that hands off in its own _ready
	# (a splash or bootstrap scene calling queue_free): by then the node is gone,
	# the poll below cannot read it, and a scene that plainly started was reported
	# as not_ready. The connection is made after add_child and still lands before
	# the signal, because the propagation above has not happened yet.
	instance.ready.connect(_on_preflight_ready)
	# A _ready that never returns blocks the engine before any of that — no frame
	# ever runs, nothing more is printed, and only gda's own launch bound ends it.
	_preflight_frame_limit = int(frames)
	_begin_pending(_preflight_tick, _preflight_frame_limit)


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
	if frame < _preflight_frame_limit:
		return false
	_succeed({
		"path": _preflight_path,
		"status": SCENE_STARTUP_READY if _preflight_ready else SCENE_STARTUP_NOT_READY,
	})
	return true


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
