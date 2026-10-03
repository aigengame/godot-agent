extends "../op_base.gd"

# gda headless operations payload: assignment of an Object-typed value by
# res:// path (ADR-0033, ADR-0043 §2). An instance module.

const VALUE := preload("value.gd")


# --- Object-typed property assignment via a res:// resource reference (ADR-0033, #363) ---
#
# node set / resource set assign an EXISTING Resource — referenced by a `res://`
# path — to an Object-typed property that expects a Resource (sub)class (e.g.
# CollisionShape2D.shape). This is a SEPARATE, headless-only step from the shared
# _coerce_value block: scalar coercion keys off Variant.Type and typed-container
# coercion may use the current Dictionary/Array value, but resolving an Object needs
# the property's expected-CLASS hint, which lives on the property-list entry — so this
# deliberately is NOT in the shared value module the harness preloads (a live `game
# set` Object assignment is out of scope, ADR-0033) and the shared _coerce_value stays
# untouched.
#
# The full storage-property list entry (name/type/hint/hint_string/class_name/usage)
# for `prop_name` on `target` (a Node or a Resource — both are Objects with a
# property list), or an empty Dictionary when the target has no storage property by
# that name. The shared _property_type returns only the Variant.Type, which cannot
# carry the expected-class hint the Object step needs, so this reads the whole entry.
func _storage_property_entry(target: Object, prop_name: String) -> Dictionary:
	for prop in target.get_property_list():
		if String(prop.get("name", "")) == prop_name and VALUE._is_storage_property(prop):
			return prop
	return {}


# The engine/script class an Object-typed property expects, read off its
# property-list entry. Godot records it in the entry's `class_name` (a StringName,
# e.g. &"Shape2D" for CollisionShape2D.shape, &"AttackComponent" for an export
# typed with a project class_name) and mirrors it in `hint_string` under
# PROPERTY_HINT_RESOURCE_TYPE. Returns "" when neither names a class.
func _object_expected_class(prop_entry: Dictionary) -> String:
	var cls := String(prop_entry.get("class_name", ""))
	if not cls.is_empty():
		return cls
	if int(prop_entry.get("hint", PROPERTY_HINT_NONE)) == PROPERTY_HINT_RESOURCE_TYPE:
		return String(prop_entry.get("hint_string", ""))
	return ""


# Whether a property-list entry is a script member with a declared type — the one
# shape whose class the engine itself checks on set(). The GDScript compiler marks
# every script member PROPERTY_USAGE_SCRIPT_VARIABLE and writes the member's declared
# type into the entry's `class_name` (modules/gdscript/gdscript_compiler.cpp L2861-L2897
# at 4.6.3-stable), and GDScriptInstance::set refuses a value of another type for such
# a member (modules/gdscript/gdscript.cpp L1537-L1548). An entry a script returns from
# _get_property_list carries only the fields the script wrote (gdscript.cpp
# L1790-L1807): a RESOURCE_TYPE hint there names a class the engine never checks,
# because the value goes to the script's _set.
func _is_typed_script_member(prop_entry: Dictionary) -> bool:
	return (int(prop_entry.get("usage", 0)) & PROPERTY_USAGE_SCRIPT_VARIABLE) != 0 \
			and not String(prop_entry.get("class_name", "")).is_empty()


# Assign a `res://` --value, as the EXISTING Resource it names, to the Object-typed
# property `prop_name` on `target` (a Node or a Resource) — the one place node set
# and resource set assign an Object (ADR-0033, #1075). Returns the assigned Resource
# on success, or null AFTER recording a DISTINCT structured failure (the caller
# stops; unlike _coerce_value's null, the caller must NOT fall back to
# uncoercible_value). The caller saves only after a success, so a failure leaves
# the target file unchanged. `subject` names the target in messages ("node
# Player/Col" / "resource res://foo.tres"). The failure modes:
#   - the `script` property is bound only by `script attach` (#118) → use_script_attach;
#   - a non-`res://` value → expected_resource_path;
#   - an Object property that declares no class, or names a project class_name in a
#     hint only and not as the type of a script member → unsupported_property_type;
#   - a path that does not load as a Resource → not_a_resource;
#   - a loaded Resource that the expected class does not accept →
#     resource_type_mismatch.
func _assign_object_value(target: Object, prop_name: String, raw_value: String, subject: String) -> Resource:
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

	# The expected class is what a Resource is checked against, so a property that
	# declares none cannot be checked at all: refuse it before anything loads.
	var prop_entry := _storage_property_entry(target, prop_name)
	var expected_class := _object_expected_class(prop_entry)
	if expected_class.is_empty():
		_fail(OP_ERROR_UNSUPPORTED_PROPERTY_TYPE, "property " + prop_name + " on " + subject
				+ " declares no class, so gda cannot check a Resource against it")
		return null

	# A project class_name is checked by the engine's typed member and by nothing
	# else (gda has no class check of its own for it), so a property that names one
	# only in a hint — a _get_property_list entry — has no check at all: refuse it
	# before anything loads. An engine class is checked by gda below, whichever
	# entry names it.
	var engine_class := ClassDB.class_exists(expected_class)
	if not engine_class and not _is_typed_script_member(prop_entry):
		_fail(OP_ERROR_UNSUPPORTED_PROPERTY_TYPE, "property " + prop_name + " on " + subject
				+ " names " + expected_class + " in a hint only, not as the type of a script"
				+ " member, so the engine does not check a Resource against it and gda cannot")
		return null

	# Load the referenced resource. A missing path, or a file that is not a resource,
	# yields null here (the engine logs why to stderr) → a distinct structured failure,
	# never uncoercible_value. res:// resolution needs project context (pass --project).
	var loaded := ResourceLoader.load(raw_value) as Resource
	if loaded == null:
		_fail(OP_ERROR_NOT_A_RESOURCE, "value does not load as a Resource: " + raw_value
				+ " — check the res:// path exists and names a resource (pass --project so res:// resolves)")
		return null

	if engine_class:
		# An ENGINE class: is_class walks the engine class hierarchy, so a
		# RectangleShape2D satisfies a Shape2D-typed property while a Gradient does not.
		if not loaded.is_class(expected_class):
			_fail_type_mismatch(raw_value, loaded.get_class(), prop_name, subject, expected_class)
			return null
		target.set(prop_name, loaded)
		return loaded

	# A project `class_name` on a typed script member (#1075): the engine's typed
	# member is the check, and gda keeps no class check of its own. set() keeps a
	# value of the class or of a subclass and drops any other value with no error
	# output, so the read-back is the verdict: a value that does not read back as the
	# assigned object was refused. A setter that does not store the assigned object
	# reads back as something else, so it is refused the same way (a stated limit).
	target.set(prop_name, loaded)
	if not is_same(target.get(prop_name), loaded):
		_fail_type_mismatch(raw_value, _resource_class_name(loaded), prop_name, subject, expected_class)
		return null
	return loaded


# The class a resource_type_mismatch names for a loaded resource: its script's
# global class_name when it has one (a FireAttack .tres is a FireAttack), else its
# engine class.
func _resource_class_name(resource: Resource) -> String:
	var script := resource.get_script() as Script
	if script != null:
		var global_name := String(script.get_global_name())
		if not global_name.is_empty():
			return global_name
	return resource.get_class()


# The one resource_type_mismatch message, for both the engine-class and the
# class_name check.
func _fail_type_mismatch(raw_value: String, actual_class: String, prop_name: String,
		subject: String, expected_class: String) -> void:
	_fail(OP_ERROR_RESOURCE_TYPE_MISMATCH, "resource " + raw_value + " is a "
			+ actual_class + ", incompatible with property " + prop_name + " on "
			+ subject + " (expects " + expected_class + ")")
