extends "../op_base.gd"

# gda headless operations payload: assignment of an Object-typed value by
# res:// path (ADR-0033, ADR-0043 §2). An instance module.

const VALUE := preload("value.gd")


# --- Object-typed property assignment via a res:// resource reference (ADR-0033, #363) ---
#
# node set / resource set assign an EXISTING Resource — referenced by a `res://`
# path — to an Object-typed property that expects a Resource (sub)class (e.g.
# CollisionShape2D.shape). This is a SEPARATE, headless-only step from the shared
# _coerce_value block below: scalar coercion keys off Variant.Type and typed-container
# coercion may use the current Dictionary/Array value, but resolving an Object needs
# the property's expected-CLASS hint, which lives on the property-list entry — so this
# deliberately is NOT mirrored into the harness (a live `game set` Object assignment is
# out of scope, ADR-0033) and the byte-identical coercion mirror stays untouched.
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
# e.g. &"Shape2D" for CollisionShape2D.shape, &"PlayerConfig" for a script
# class_name-typed export) and mirrors it in `hint_string` under
# PROPERTY_HINT_RESOURCE_TYPE. Returns "" when neither names a class.
func _object_expected_class(prop_entry: Dictionary) -> String:
	var cls := String(prop_entry.get("class_name", ""))
	if not cls.is_empty():
		return cls
	if int(prop_entry.get("hint", PROPERTY_HINT_NONE)) == PROPERTY_HINT_RESOURCE_TYPE:
		return String(prop_entry.get("hint_string", ""))
	return ""


# Resolve a `res://` --value into the EXISTING Resource to assign to an Object-typed
# property (ADR-0033). Returns the loaded Resource on success, or null AFTER recording
# a DISTINCT structured failure (the caller stops; unlike _coerce_value's null, the
# caller must NOT fall back to uncoercible_value). `subject` names the target in
# messages ("node Player/Col" / "resource res://foo.tres"). The failure modes:
#   - the `script` property is bound only by `script attach` (#118) → use_script_attach;
#   - a non-`res://` value → expected_resource_path;
#   - a property typed as a script class_name (not an engine class) is deferred to the
#     ADR-0032 resolver → unsupported_property_type (type-check scope is engine classes);
#   - a path that does not load as a Resource → not_a_resource;
#   - a loaded Resource whose type is incompatible with the expected class →
#     resource_type_mismatch.
func _resolve_object_value(prop_name: String, prop_entry: Dictionary, raw_value: String, subject: String) -> Resource:
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

	# Type-check scope is ENGINE-class-typed Object properties (e.g. shape: Shape2D).
	# A property typed as a script `class_name` names a class ClassDB does not know;
	# its validation is deferred to the ADR-0032 class_name resolver (ADR-0033), so
	# refuse it distinctly rather than mis-type-check it against the engine hierarchy.
	var expected_class := _object_expected_class(prop_entry)
	if expected_class.is_empty() or not ClassDB.class_exists(expected_class):
		var named := expected_class if not expected_class.is_empty() else "an unspecified Object type"
		_fail(OP_ERROR_UNSUPPORTED_PROPERTY_TYPE, "property " + prop_name + " on " + subject
				+ " expects " + named + ", which is not an engine class — assigning a Resource to"
				+ " a script class_name-typed property is not yet supported (deferred, ADR-0033)")
		return null

	# Load the referenced resource. A missing path, or a file that is not a resource,
	# yields null here (the engine logs why to stderr) → a distinct structured failure,
	# never uncoercible_value. res:// resolution needs project context (pass --project).
	var loaded := ResourceLoader.load(raw_value) as Resource
	if loaded == null:
		_fail(OP_ERROR_NOT_A_RESOURCE, "value does not load as a Resource: " + raw_value
				+ " — check the res:// path exists and names a resource (pass --project so res:// resolves)")
		return null

	# is_class walks the engine class hierarchy, so a RectangleShape2D satisfies a
	# Shape2D-typed property while a Gradient does not.
	if not loaded.is_class(expected_class):
		_fail(OP_ERROR_RESOURCE_TYPE_MISMATCH, "resource " + raw_value + " is a "
				+ loaded.get_class() + ", incompatible with property " + prop_name + " on "
				+ subject + " (expects " + expected_class + ")")
		return null

	return loaded
