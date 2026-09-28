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
#
# The operation bodies live in one file per command group (ADR-0043); this entry
# keeps the lifecycle, the parameter parse, the dispatch, the emission, the
# pending tail and `info`. Every group is preloaded here, so `info` compiles the
# whole payload. Relative paths resolve from this file's directory.

# The op base declares the operation-source codes (ADR-0043 §5). This entry, a
# SceneTree, cannot extend it, so it qualifies the three codes it uses.
const OP_BASE := preload("op_base.gd")
const SCENE_GROUP := preload("groups/scene.gd")
const NODE_GROUP := preload("groups/node.gd")
const SCRIPT_GROUP := preload("groups/script.gd")
const RESOURCE_GROUP := preload("groups/resource.gd")
const EXPORT_GROUP := preload("groups/export.gd")
const PROJECT_GROUP := preload("groups/project.gd")
const SHADER_GROUP := preload("groups/shader.gd")
const THEME_GROUP := preload("groups/theme.gd")
# The shared value module holds the reply JSON writer, _json (ADR-0043 §3, §7).
const VALUE := preload("lib/value.gd")

const RESULT_BEGIN := "<<<GDA:RESULT>>>"
const RESULT_END := "<<<GDA:END>>>"


# The prefix every gda diagnostic line carries on stderr (see _diag), so a reader
# can tell gda's own lines from the engine's. A const rather than an inline
# literal because one diagnostic — VALIDATE_MARKER — is PARSED by gda, not
# merely displayed, which makes this prefix half of a cross-language contract.
const DIAG_PREFIX := "gda: "


# The exit code the process will use. Defaults to failure, so an operation that
# aborts before recording an outcome (e.g. an uncaught runtime error) still
# exits non-zero rather than reporting a phantom success.
var _exit_code := 1


# The multi-frame tail of an operation that cannot answer inside _initialize
# (#664). Every other operation finishes in one call and quits on the first idle
# frame; scene-preflight has to keep the main loop running so the scene it booted
# actually gets frames. `_pending_tick` is called once per idle frame with the
# 1-based frame number and returns true when it has recorded its outcome.
var _pending_tick := Callable()
var _pending_frames := 0
var _pending_frame_limit := 0


# The group instance that serves this run's operation, created by the dispatch
# arm and held here until the process quits. A Callable does not keep its
# RefCounted target alive (ADR-0043 probe 5): a group that only a pending tick
# referenced would be freed before the tick ran, and the run would emit no result.
var _group: RefCounted = null


func _initialize() -> void:
	# Everything after `--` on the Godot command line — i.e. <operation>
	# [params_json] — arrives here, independent of engine argument ordering.
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		_fail(OP_BASE.OP_ERROR_USAGE, "usage: godot --headless --script operations.gd -- <operation> [params_json]")
		return

	var operation: String = args[0]
	var params: Variant = _parse_params(args)
	if params == null:
		return  # _parse_params already recorded the failure

	match operation:
		"info":
			_op_info()
		"scene-create":
			_scene_group()._op_scene_create(params)
		"scene-get":
			_scene_group()._op_scene_get(params)
		"scene-get-exports":
			_scene_group()._op_scene_get_exports(params)
		"scene-list":
			_scene_group()._op_scene_list(params)
		"scene-delete":
			_scene_group()._op_scene_delete(params)
		"scene-validate":
			_scene_group()._op_scene_validate(params)
		"scene-preflight":
			_scene_group()._op_scene_preflight(params)
		"node-add":
			_node_group()._op_node_add(params)
		"node-list":
			_node_group()._op_node_list(params)
		"node-get":
			_node_group()._op_node_get(params)
		"node-set":
			_node_group()._op_node_set(params)
		"node-remove":
			_node_group()._op_node_remove(params)
		"node-duplicate":
			_node_group()._op_node_duplicate(params)
		"node-move":
			_node_group()._op_node_move(params)
		"node-connect-signal":
			_node_group()._op_node_connect_signal(params)
		"node-disconnect-signal":
			_node_group()._op_node_disconnect_signal(params)
		"script-create":
			_script_group()._op_script_create(params)
		"script-get":
			_script_group()._op_script_get(params)
		"script-list":
			_script_group()._op_script_list(params)
		"script-delete":
			_script_group()._op_script_delete(params)
		"script-set":
			_script_group()._op_script_set(params)
		"script-attach":
			_script_group()._op_script_attach(params)
		"script-validate":
			_script_group()._op_script_validate(params)
		"resource-create":
			_resource_group()._op_resource_create(params)
		"resource-get":
			_resource_group()._op_resource_get(params)
		"resource-set":
			_resource_group()._op_resource_set(params)
		"resource-delete":
			_resource_group()._op_resource_delete(params)
		"export-list":
			_export_group()._op_export_list(params)
		"export-get":
			_export_group()._op_export_get(params)
		"resource-uid":
			_resource_group()._op_resource_uid(params)
		"project-info":
			_project_group()._op_project_info(params)
		"project-create":
			_project_group()._op_project_create(params)
		"project-get":
			_project_group()._op_project_get(params)
		"project-list":
			_project_group()._op_project_list(params)
		"project-set":
			_project_group()._op_project_set(params)
		"project-add-autoload":
			_project_group()._op_project_add_autoload(params)
		"project-remove-autoload":
			_project_group()._op_project_remove_autoload(params)
		"project-add-input-action":
			_project_group()._op_project_add_input_action(params)
		"project-remove-input-action":
			_project_group()._op_project_remove_input_action(params)
		"shader-create":
			_shader_group()._op_shader_create(params)
		"shader-get":
			_shader_group()._op_shader_get(params)
		"shader-set":
			_shader_group()._op_shader_set(params)
		"theme-create":
			_theme_group()._op_theme_create(params)
		"project-find-references":
			_project_group()._op_project_find_references(params)
		"project-dependencies":
			_project_group()._op_project_dependencies(params)
		"project-find-unused-resources":
			_project_group()._op_project_find_unused_resources(params)
		"project-statistics":
			_project_group()._op_project_statistics(params)
		_:
			_fail(OP_BASE.OP_ERROR_UNKNOWN_OPERATION, "unknown operation: " + operation)


# Quit on the first idle frame, whatever happened during _initialize — this is
# the single exit point and the watchdog against a hung main loop (issue #31).
#
# An operation that declared a pending tail (_begin_pending, #664) keeps the loop
# running until its tick says it is done. The watchdog survives that: the frame is
# COUNTED and CAPPED before the tick runs, so a tick aborted by an uncaught runtime
# error — which makes this function return its default `false` and be called again
# next frame — still ends the run at the cap instead of erroring forever. The op's
# own budget is the cap, so a tick that never records an outcome quits non-zero
# (the generic operation_failed) rather than spinning.
func _process(_delta: float) -> bool:
	if _pending_tick.is_valid():
		_pending_frames += 1
		if _pending_frames <= _pending_frame_limit and not _pending_tick.call(_pending_frames):
			return false
	quit(_exit_code)
	return true


# Keep the main loop running for up to `frames` idle frames, calling `tick` on
# each with the 1-based frame number until it returns true (#664).
func _begin_pending(tick: Callable, frames: int) -> void:
	_pending_tick = tick
	_pending_frame_limit = frames


# Parse the optional params JSON into a Dictionary; null signals a recorded
# failure (the caller must stop). A missing payload is an empty Dictionary.
func _parse_params(args: PackedStringArray) -> Variant:
	if args.size() <= 1:
		return {}
	var parsed: Variant = JSON.parse_string(args[1])
	if not (parsed is Dictionary):
		_fail(OP_BASE.OP_ERROR_INVALID_PARAMS, "params is not a JSON object: " + args[1])
		return null
	return parsed


# The group instance for the requested operation: created with this frame and
# held in `_group` (see there) before the dispatch arm calls into it.
func _export_group() -> EXPORT_GROUP:
	var group := EXPORT_GROUP.new(self)
	_group = group
	return group


func _theme_group() -> THEME_GROUP:
	var group := THEME_GROUP.new(self)
	_group = group
	return group


func _scene_group() -> SCENE_GROUP:
	var group := SCENE_GROUP.new(self)
	_group = group
	return group


func _node_group() -> NODE_GROUP:
	var group := NODE_GROUP.new(self)
	_group = group
	return group


func _script_group() -> SCRIPT_GROUP:
	var group := SCRIPT_GROUP.new(self)
	_group = group
	return group


func _resource_group() -> RESOURCE_GROUP:
	var group := RESOURCE_GROUP.new(self)
	_group = group
	return group


func _project_group() -> PROJECT_GROUP:
	var group := PROJECT_GROUP.new(self)
	_group = group
	return group


func _shader_group() -> SHADER_GROUP:
	var group := SHADER_GROUP.new(self)
	_group = group
	return group


# info: emit Engine.get_version_info() through the structured-output contract.
func _op_info() -> void:
	_diag("running operation: info")
	_succeed(Engine.get_version_info())


# Record a successful result: emit it through the sentinel contract and mark
# the process to exit 0. The single quit() lives in _process.
func _succeed(payload: Dictionary) -> void:
	print(RESULT_BEGIN + VALUE._json(payload) + RESULT_END)
	_exit_code = 0


func _diag(message: String) -> void:
	printerr(DIAG_PREFIX + message)


# Record a structured failure through the ADR-0002 sentinel contract. The
# process is left to exit non-zero via _process.
func _fail(code: String, message: String) -> void:
	print(RESULT_BEGIN + VALUE._json({
		"error": {
			"code": code,
			"message": message,
		},
	}) + RESULT_END)
	_exit_code = 1
