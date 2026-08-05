extends SceneTree

## Regression for the #476 review's forms-drift finding: a form row and a direct-
## manipulation edit share JSON keys (arena_min_x / arena_max_x are BOTH SpinBox
## fields and drag targets), so a drag must re-seed the row or the SpinBox shows
## stale data and a later form edit clobbers the drag.
##
## Builds the real EditorForms over a loaded model, mutates a shared key through
## the DRAG-path setter (set_arena_min_x), and proves: before refresh the SpinBox
## is stale; after forms.refresh() it re-seeds from the model. Read-only.
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_editor_form_refresh.gd
## Prints "FORM_REFRESH: PASS" + quit(0) on success, else push_error + quit(1).

const ModelScript := preload("res://tools/editor/editor_level_model.gd")
const FormsScript := preload("res://tools/editor/editor_forms.gd")


func _fail(msg: String) -> void:
	push_error("FORM_REFRESH: " + msg)
	quit(1)


func _init() -> void:
	var model := ModelScript.new()
	if not model.load_authorities():
		_fail("could not load Level 1 JSON authorities")
		return
	var forms := FormsScript.new(model)
	var box := VBoxContainer.new()
	root.add_child(box)
	forms.build(box, [
		{
			"authority": ModelScript.AUTHORITY_LEVEL,
			"schema_path": "res://content/data/schema/level_config.schema.json",
			"title": "Level",
		},
	])

	var spin: SpinBox = _find_spin(forms, ModelScript.AUTHORITY_LEVEL, "arena_min_x")
	if spin == null:
		_fail("arena_min_x form row was not built")
		return
	var original: float = model.get_number(ModelScript.AUTHORITY_LEVEL, "arena_min_x")
	if spin.value != original:
		_fail("SpinBox was not seeded from the model: %s != %s" % [spin.value, original])
		return

	# Simulate a DRAG mutating the shared key through the direct-manipulation setter.
	var dragged := original - 32.0
	model.set_arena_min_x(dragged)
	# Before refresh the SpinBox is STALE (the drift the finding names).
	if spin.value != original:
		_fail("SpinBox unexpectedly changed without a refresh")
		return
	# refresh() re-seeds it from the model (the fix) without re-firing value_changed.
	forms.refresh()
	if spin.value != dragged:
		_fail("refresh did not re-seed the SpinBox: %s != %s" % [spin.value, dragged])
		return

	print("FORM_REFRESH: PASS")
	quit(0)


func _find_spin(forms, authority: String, key: String) -> SpinBox:
	for row in forms._rows:
		if row["authority"] == authority and row["key"] == key:
			return row["spin"] as SpinBox
	return null
