extends SceneTree

# gda editor-context payload (ADR-0048).
#
# Invoked as: godot --headless -e --language en --path <project> --script editor.gd -- <operation> [params_json]
#
# The second entry beside operations.gd. The engine boots the editor around this
# script. It waits until the editor's first filesystem scan has ended, runs one
# operation, and reports it through the same stdout sentinels as operations.gd
# (ADR-0002). The operation bodies stay in their command-group files (ADR-0043):
# this entry is a frame for them, as operations.gd is.
#
# Readiness: the editor singletons do not exist at _initialize, so the wait is in
# _process. EditorFileSystem.is_scanning() is true from construction until the
# first scan has updated the class index and re-imported (first_scan in
# editor/file_system/editor_file_system.cpp, 4.6.3). One frame that reads it false
# is therefore enough.
#
# Control flow: the single quit of operations.gd (issue #31). The operation runs on
# the first frame that finds the scan ended, and the next frame prints the recorded
# result and quits. An uncaught runtime error in the operation aborts that frame
# only, so the process still quits on the next frame, with the default non-zero
# exit code.

# The op base declares the operation-source codes (ADR-0043 §5). This entry, a
# SceneTree, cannot extend it, so it qualifies the codes it uses.
const OP_BASE := preload("op_base.gd")
const PROJECT_GROUP := preload("groups/project.gd")
# The shared value module holds the reply JSON writer, _json (ADR-0043 §3, §7).
const VALUE := preload("lib/value.gd")

const RESULT_BEGIN := "<<<GDA:RESULT>>>"
const RESULT_END := "<<<GDA:END>>>"
const DIAG_PREFIX := "gda: "

# Defaults to failure, so an operation that aborts before it records an outcome
# exits non-zero.
var _exit_code := 1

# The result line that _succeed / _fail recorded, printed by _process on the quit
# frame. Empty when no outcome was recorded.
var _result := ""

var _operation := ""
var _params: Dictionary = {}

# True once the operation ran, or once _initialize recorded a failure that leaves
# nothing to run. The frame after that quits.
var _done := false

# The group instance that serves the operation, held until the quit frame: a
# Callable does not keep its RefCounted target alive (ADR-0043 probe 5).
var _group: RefCounted = null


func _initialize() -> void:
	# Everything after `--` on the Godot command line: <operation> [params_json].
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		_fail(OP_BASE.OP_ERROR_USAGE, "usage: godot --headless -e --path <project> --script editor.gd -- <operation> [params_json]")
		_done = true
		return
	_operation = args[0]
	if args.size() > 1:
		var parsed: Variant = JSON.parse_string(args[1])
		if not (parsed is Dictionary):
			_fail(OP_BASE.OP_ERROR_INVALID_PARAMS, "params is not a JSON object: " + args[1])
			_done = true
			return
		_params = parsed


func _process(_delta: float) -> bool:
	if not _done:
		if not _scan_ended():
			return false
		_done = true
		_dispatch()
		return false
	_group = null
	if not _result.is_empty():
		print(_result)
	quit(_exit_code)
	return true


# Whether the editor exists and its first filesystem scan has ended (see the
# readiness note above).
func _scan_ended() -> bool:
	var editor: Object = Engine.get_singleton("EditorInterface") if Engine.has_singleton("EditorInterface") else null
	if editor == null:
		return false
	var filesystem: Object = editor.get_resource_filesystem()
	return filesystem != null and not filesystem.is_scanning()


func _dispatch() -> void:
	match _operation:
		"project-scan":
			_project_group()._op_project_scan(_params)
		_:
			_fail(OP_BASE.OP_ERROR_UNKNOWN_OPERATION, "unknown operation: " + _operation)


func _project_group() -> PROJECT_GROUP:
	var group := PROJECT_GROUP.new(self)
	_group = group
	return group


# Record a successful result in the sentinel contract and mark the process to
# exit 0. _process prints it and holds the single quit().
func _succeed(payload: Dictionary) -> void:
	_result = RESULT_BEGIN + VALUE._json(payload) + RESULT_END
	_exit_code = 0


func _diag(message: String) -> void:
	printerr(DIAG_PREFIX + message)


# Record a structured failure in the ADR-0002 sentinel contract. _process prints
# it and leaves the process to exit non-zero.
func _fail(code: String, message: String) -> void:
	_result = RESULT_BEGIN + VALUE._json({
		"error": {
			"code": code,
			"message": message,
		},
	}) + RESULT_END
	_exit_code = 1
