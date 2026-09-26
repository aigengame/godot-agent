extends RefCounted

# gda headless operations payload: the op seam (ADR-0043 §4, §5).
#
# Every command-group file, and every concept module that reports failure,
# extends this base. It forwards _fail, _succeed, _diag and _begin_pending to
# the frame — the entry, operations.gd, which alone prints the sentinel result
# and sets the exit code — it holds the project guard, and it declares the
# operation-source error codes, so a moved operation body keeps its
# `_fail(OP_ERROR_…)` lines unchanged. Until the last step of #1015 the entry
# keeps a copy of the codes and of the project guard; a test pins the copy to
# this file (tests/cli/test_error_registry.py).


const OP_ERROR_USAGE := "usage_error"
const OP_ERROR_UNKNOWN_OPERATION := "unknown_operation"
const OP_ERROR_INVALID_PARAMS := "invalid_params"
const OP_ERROR_INVALID_PATH := "invalid_path"
const OP_ERROR_INVALID_ROOT_TYPE := "invalid_root_type"
const OP_ERROR_INVALID_ROOT_NAME := "invalid_root_name"
const OP_ERROR_ALREADY_EXISTS := "already_exists"
const OP_ERROR_SAVE_FAILED := "save_failed"
const OP_ERROR_DELETE_FAILED := "delete_failed"
const OP_ERROR_FILE_CHANGED_EXTERNALLY := "file_changed_externally"
const OP_ERROR_PROJECT_NOT_FOUND := "project_not_found"
const OP_ERROR_PATH_NOT_FOUND := "path_not_found"
const OP_ERROR_NOT_A_SCENE := "not_a_scene"
const OP_ERROR_PARENT_NOT_FOUND := "parent_not_found"
const OP_ERROR_INVALID_NODE_TYPE := "invalid_node_type"
const OP_ERROR_INVALID_NODE_NAME := "invalid_node_name"
const OP_ERROR_DUPLICATE_NODE_NAME := "duplicate_node_name"
const OP_ERROR_INVALID_CHILD_INDEX := "invalid_child_index"
const OP_ERROR_MISSING_DEPENDENCY := "missing_dependency"
const OP_ERROR_UNINSTANTIABLE_SCRIPT := "uninstantiable_script"
const OP_ERROR_AMBIGUOUS_CLASS_NAME := "ambiguous_class_name"
const OP_ERROR_NODE_NOT_FOUND := "node_not_found"
const OP_ERROR_CANNOT_TARGET_ROOT := "cannot_target_root"
const OP_ERROR_CYCLIC_TARGET := "cyclic_target"
const OP_ERROR_UNKNOWN_PROPERTY := "unknown_property"
const OP_ERROR_UNCOERCIBLE_VALUE := "uncoercible_value"
# Object-typed property assignment via a res:// resource reference (ADR-0033, #363).
const OP_ERROR_EXPECTED_RESOURCE_PATH := "expected_resource_path"
const OP_ERROR_NOT_A_RESOURCE := "not_a_resource"
const OP_ERROR_RESOURCE_TYPE_MISMATCH := "resource_type_mismatch"
const OP_ERROR_USE_SCRIPT_ATTACH := "use_script_attach"
const OP_ERROR_UNSUPPORTED_PROPERTY_TYPE := "unsupported_property_type"
const OP_ERROR_NO_SEARCH_MATCH := "no_search_match"
const OP_ERROR_INVALID_LINE_RANGE := "invalid_line_range"
const OP_ERROR_SCRIPT_COMPILE_FAILED := "script_compile_failed"
const OP_ERROR_INCOMPATIBLE_SCRIPT_TYPE := "incompatible_script_type"
const OP_ERROR_SIGNAL_NOT_FOUND := "signal_not_found"
const OP_ERROR_ALREADY_CONNECTED := "already_connected"
const OP_ERROR_CONNECTION_NOT_FOUND := "connection_not_found"
const OP_ERROR_INVALID_RESOURCE_TYPE := "invalid_resource_type"
const OP_ERROR_EXPORT_PRESETS_NOT_FOUND := "export_presets_not_found"
const OP_ERROR_EXPORT_PRESET_NOT_FOUND := "export_preset_not_found"
const OP_ERROR_INVALID_UID := "invalid_uid"
const OP_ERROR_UNKNOWN_UID := "unknown_uid"
const OP_ERROR_NO_UID_ASSIGNED := "no_uid_assigned"
const OP_ERROR_UNKNOWN_SETTING := "unknown_setting"
const OP_ERROR_INVALID_TARGET := "invalid_target"
const OP_ERROR_INVALID_KEY := "invalid_key"


# The frame: the SceneTree entry that constructed this instance. Untyped on
# purpose — the entry extends SceneTree, and the forwards below are the calls
# that cross this seam (ADR-0043 §4).
var _frame


func _init(frame) -> void:
	_frame = frame


func _fail(code: String, message: String) -> void:
	_frame._fail(code, message)


func _succeed(payload: Dictionary) -> void:
	_frame._succeed(payload)


func _diag(message: String) -> void:
	_frame._diag(message)


func _begin_pending(tick: Callable, frames: int) -> void:
	_frame._begin_pending(tick, frames)


# Whether this headless process is running against a Godot project. A project
# scan writes the resource UID cache under res://.godot; its presence is the
# marker the engine itself uses, and a projectless --script run (no --path to a
# project dir) does not have it. scene-list needs a real res:// tree to walk.
func _has_project() -> bool:
	return DirAccess.dir_exists_absolute("res://") and FileAccess.file_exists("res://project.godot")


# --- transitional forwards (#1015, step 1) -----------------------------------
# The four shared helpers below still live in the entry until their concept
# modules exist: `_string_param` moves to the shared value module, the other
# three to the file write. Each forward is deleted in the step that moves its
# helper, and the group's call is then qualified with that module's preload
# constant. Meanwhile they keep the moved bodies verbatim: a `var x :=
# _frame.helper()` in a group would not compile, because a call through the
# untyped frame has no set type.
func _string_param(params: Dictionary, key: String) -> String:
	return _frame._string_param(params, key)


func _ensure_parent_dirs(path: String) -> Variant:
	return _frame._ensure_parent_dirs(path)


func _atomic_save_resource(res: Resource, path: String) -> int:
	return _frame._atomic_save_resource(res, path)


func _save_failure_message(noun: String, path: String, save_err: Error) -> String:
	return _frame._save_failure_message(noun, path, save_err)
