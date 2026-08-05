extends RefCounted

## Re-derives the Godot Resources from the JSON authority by invoking the ONE
## Python builder — `scripts/build_config.py` — through `OS.execute` (gADR-0012).
##
## The Editor NEVER re-implements the JSON->Resource derivation (defaults,
## reward/drop resolution, the Scale-spec composition) in GDScript: that is
## gADR-0012's explicit rejection of a second derivation path. It shells out to
## the exact same offline builder the config gate and the balancing pipeline run,
## so there is one derivation, one place drift can hide.
##
## Python resolution (the Editor is a dev-machine tool, so a Python toolchain is
## assumed present, gADR-0012): an overridable env var `PANDA_EDITOR_PYTHON` wins
## — for a dev venv or a hermetic test interpreter — else `/usr/bin/env python3`,
## which resolves `python3` from PATH WITHOUT hardcoding a machine-specific path.
## `build_config.py` resolves all its own paths from its `__file__`, so the
## working directory is irrelevant and it always builds the project it lives in.

const BUILDER_RES_PATH := "res://scripts/build_config.py"
const PYTHON_ENV_OVERRIDE := "PANDA_EDITOR_PYTHON"


## Run the builder synchronously. Returns
## {ok: bool, exit_code: int, python: String, output: String} — `ok` is true only
## on a clean exit (0). `exit_code` is -1 when the interpreter could not even be
## launched (Python absent / not on PATH), which the caller surfaces as the
## dev-machine-toolchain remedy.
static func run() -> Dictionary:
	var script_path := ProjectSettings.globalize_path(BUILDER_RES_PATH)
	var output: Array = []
	var override := OS.get_environment(PYTHON_ENV_OVERRIDE).strip_edges()
	var python: String
	var argv: Array
	if override != "":
		python = override
		argv = [script_path]
	else:
		# /usr/bin/env resolves python3 from PATH without a hardcoded path.
		python = "/usr/bin/env"
		argv = ["python3", script_path]
	var exit_code := OS.execute(python, argv, output, true)
	return {
		"ok": exit_code == 0,
		"exit_code": exit_code,
		"python": python if override != "" else "/usr/bin/env python3",
		"output": "\n".join(PackedStringArray(output)),
	}
