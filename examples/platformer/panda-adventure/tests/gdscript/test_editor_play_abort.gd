extends SceneTree

## Regression seam for the review-round correctness finding on #438: a FAILED
## save+derive must ABORT the edit->play switch. Playing after a failed builder
## run would silently instance main.tscn against STALE derived .tres — the exact
## "plays the edited level immediately" promise broken.
##
## Run via gda (ADR-0031) with the builder FORCED TO FAIL — the seam test points
## PANDA_EDITOR_PYTHON at an interpreter that exits non-zero (/usr/bin/false) —
## against a THROWAWAY PROJECT COPY (the save half succeeds, so data/json is
## written in place):
##   PANDA_EDITOR_PYTHON=/usr/bin/false gda script run \
##       res://tests/gdscript/test_editor_play_abort.gd
##
## Instances the REAL editor entry scene (its _ready loads the authorities), dirties
## the model through the same setter a drag uses, then drives _enter_play() and
## asserts the abort: edit mode holds, no play instance under PlayHost, and the
## status carries derive_failed. Prints "PLAY_ABORT: PASS" + quit(0) on success.

const EditorScene := preload("res://scenes/editor.tscn")


func _fail(msg: String) -> void:
	push_error("PLAY_ABORT: " + msg)
	quit(1)


func _init() -> void:
	if OS.get_environment("PANDA_EDITOR_PYTHON").is_empty():
		_fail("PANDA_EDITOR_PYTHON must point at a failing interpreter for this seam")
		return

	var editor := EditorScene.instantiate()
	root.add_child(editor)
	# Await one frame so the tree is initialized and the editor's _ready has
	# certainly run (adding during SceneTree _init predates tree initialization).
	await process_frame

	if editor._model == null:
		_fail("editor _ready did not load the authorities")
		return
	if editor.is_playing:
		_fail("editor must boot in edit mode")
		return

	# Dirty the model through the same setter a drag/nudge uses.
	editor._model.set_arena_min_x(editor._model.get_arena_min_x() + 16.0)
	if not editor._model.dirty:
		_fail("model must be dirty after the edit")
		return

	# The edit->play switch: save succeeds (JSON written), derive FAILS
	# (PANDA_EDITOR_PYTHON exits non-zero) -> play entry must abort.
	editor._enter_play()

	if editor.is_playing:
		_fail("play mode entered despite a failed derive — stale .tres would play")
		return
	if editor.get_node("PlayHost").get_child_count() != 0:
		_fail("a play instance was added despite the failed derive")
		return
	if editor.last_action != "derive_failed":
		_fail("last_action should read derive_failed, got %s" % editor.last_action)
		return
	if not String(editor.status_line).contains("derive_failed"):
		_fail("status line must surface the failure, got %s" % editor.status_line)
		return

	print("PLAY_ABORT: PASS")
	quit(0)
