extends "../op_base.gd"

# gda headless operations payload: the resource command group (ADR-0043). The
# entry, operations.gd, creates one instance per run and dispatches the group's
# operations to it.

const VALUE := preload("../lib/value.gd")
const CLASS_INDEX := preload("../lib/class_index.gd")
const FILE_WRITE := preload("../lib/file_write.gd")
const OBJECT_REF := preload("../lib/object_ref.gd")

# The instance concept modules this group's operations call, created with the
# group's frame and held for the group's life (ADR-0043 §4).
var _file_write: FILE_WRITE
var _object_ref: OBJECT_REF


func _init(frame) -> void:
	super(frame)
	_file_write = FILE_WRITE.new(frame)
	_object_ref = OBJECT_REF.new(frame)


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
		var resolved := _object_ref._assign_object_value(resource, prop_name, raw_value,
				"resource " + path)
		if resolved == null:
			return  # _assign_object_value already recorded the failure
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
	# The stale-entry predicate (#1073), after the load and compile checks so a
	# script that does not compile keeps uninstantiable_script: an entry whose
	# compiled script declares another name would write that name under this one.
	if CLASS_INDEX._declares_other_class(script, type):
		_fail(OP_ERROR_CLASS_INDEX_STALE, CLASS_INDEX._stale_entry_message(
				CLASS_INDEX._stale_entry(type, script_path, script)))
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
