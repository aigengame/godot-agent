extends RefCounted

# gda headless operations payload: the op seam (ADR-0043 §4, §5).
#
# Every command-group file, and every concept module that reports failure,
# extends this base. It forwards _fail, _succeed, _diag and _begin_pending to
# the frame — the entry, operations.gd, which alone prints the sentinel result
# and sets the exit code — it holds the project guard, and it declares the
# operation-source error codes, so a moved operation body keeps its
# `_fail(OP_ERROR_…)` lines unchanged. The entry, a SceneTree, cannot extend
# this base; it reaches the three codes it uses through a preload constant.


const OP_ERROR_USAGE := "usage_error"
const OP_ERROR_UNKNOWN_OPERATION := "unknown_operation"
const OP_ERROR_INVALID_PARAMS := "invalid_params"
const OP_ERROR_INVALID_PATH := "invalid_path"
const OP_ERROR_INVALID_ROOT_TYPE := "invalid_root_type"
const OP_ERROR_INVALID_ROOT_NAME := "invalid_root_name"
const OP_ERROR_ALREADY_EXISTS := "already_exists"
const OP_ERROR_DESTINATION_NOT_EMPTY := "destination_not_empty"
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
# A class index entry whose compiled script declares another name (#1073).
const OP_ERROR_CLASS_INDEX_STALE := "class_index_stale"
const OP_ERROR_NODE_NOT_FOUND := "node_not_found"
const OP_ERROR_CANNOT_TARGET_ROOT := "cannot_target_root"
# A node another scene declares: inherited, or inside an instanced child (ADR-0044).
const OP_ERROR_CANNOT_TARGET_FOREIGN := "cannot_target_foreign"
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


# Whether this headless process is running against a Godot project: res:// is a
# directory and holds a project.godot, which a projectless --script run (no --path
# to a project dir) does not have. scene-list needs a real res:// tree to walk.
func _has_project() -> bool:
	return DirAccess.dir_exists_absolute("res://") and FileAccess.file_exists("res://project.godot")
