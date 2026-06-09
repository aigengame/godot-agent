#!/usr/bin/env -S godot --headless --script
extends SceneTree

# gda headless operations payload (ADR-0001, ADR-0002).
#
# Invoked as: godot --headless --script operations.gd <operation> [params_json]
#
# Each operation emits EXACTLY ONE result to stdout, wrapped in the GDA
# sentinels, and routes all of its own diagnostics to stderr. stdout carries
# nothing but the sentinel-delimited result; everything else is engine noise.

const RESULT_BEGIN := "<<<GDA:RESULT>>>"
const RESULT_END := "<<<GDA:END>>>"


func _init() -> void:
	var args := OS.get_cmdline_args()
	var script_index := args.find("--script")
	if script_index == -1:
		_fail("could not find --script argument")
		return

	# The operation name sits two positions after --script (the script path
	# itself is at script_index + 1).
	var operation_index := script_index + 2
	if args.size() <= operation_index:
		_fail("usage: godot --headless --script operations.gd <operation> [params_json]")
		return

	var operation := args[operation_index]

	match operation:
		"info":
			_op_info()
		_:
			_fail("unknown operation: " + operation)
			return

	quit()


# info: emit Engine.get_version_info() through the structured-output contract.
func _op_info() -> void:
	_diag("running operation: info")
	_emit_result(JSON.stringify(Engine.get_version_info()))


func _emit_result(json_payload: String) -> void:
	print(RESULT_BEGIN + json_payload + RESULT_END)


func _diag(message: String) -> void:
	printerr("gda: " + message)


func _fail(message: String) -> void:
	_diag(message)
	quit(1)
