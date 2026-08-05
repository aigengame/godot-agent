extends RefCounted

## The Panda Adventure Editor's numeric hand-tune FORMS (gADR-0012, #441): a
## structured SpinBox per schema-derived scalar number, NEVER free-text JSON.
##
## Builds one labeled SpinBox row per field EditorFormSpec derives from a config's
## JSON Schema (so the field set and its ranges come from `content/data/schema/*.json`,
## the same contract the builder validates against — no hand-forked registry).
## Each row is two-way bound to the EditorLevelModel: it seeds from the JSON
## authority's current value and, on edit, writes back through `set_number`
## (marking that authority dirty). A Save then writes ONLY the JSON authority and
## re-derives through the ONE Python builder (gADR-0012's forms round-trip:
## forms -> JSON -> builder -> reload) — the forms never touch a `.tres`.
##
## Thin over Godot's own SpinBox (numeric field with min/max/step, keyboard entry,
## arrow nudge). Held by the EditorController; the built rows live under a Control
## the controller supplies. Emits `field_edited` so the controller can refresh the
## unsaved-edits marker exactly as a drag does.

const FormSpecScript := preload("res://tools/editor/editor_form_spec.gd")

## One numeric field was edited (the authority dirtied) — the controller refreshes
## its status line / save-state marker, the drag path's `_set_status` sibling.
signal field_edited

var _model
# Total SpinBox rows built across all sections — the editor_ready log's proof the
# schema-driven forms materialized (and a headless seam's assertable count).
var _field_count := 0
# Each built row: {authority, key, spin}. Kept so refresh() can re-seed every
# SpinBox from the model after direct manipulation touches a form-backed key.
var _rows: Array = []


func _init(model) -> void:
	_model = model


func field_count() -> int:
	return _field_count


## Build every section's rows under `container` (a VBoxContainer). `sections` is an
## ordered Array of {authority, schema_path, title}: for each, a heading Label
## then one SpinBox row per numeric scalar the schema declares. Idempotent per
## call is not required (the controller builds once in _ready).
func build(container: VBoxContainer, sections: Array) -> void:
	for section: Dictionary in sections:
		_build_section(container, section)


func _build_section(container: VBoxContainer, section: Dictionary) -> void:
	var authority := String(section["authority"])
	var schema: Dictionary = _model.read_schema(String(section["schema_path"]))
	var fields := FormSpecScript.numeric_fields(schema)
	if fields.is_empty():
		return
	var heading := Label.new()
	heading.text = String(section["title"])
	container.add_child(heading)
	for field: Dictionary in fields:
		container.add_child(_build_row(authority, field))


## One "<label>  [SpinBox]" row bound to `authority[field.key]`. The SpinBox range
## comes from the schema (an unbounded side allows lesser/greater so the field is
## not silently clamped); the display step is refined from the seed value so a
## seconds-scale number keeps its decimals while a wide feel number nudges by 1.
func _build_row(authority: String, field: Dictionary) -> HBoxContainer:
	var row := HBoxContainer.new()
	var label := Label.new()
	label.text = String(field["label"])
	label.custom_minimum_size = Vector2(220.0, 0.0)
	row.add_child(label)

	var value: float = _model.get_number(authority, String(field["key"]))
	var spin := SpinBox.new()
	var step := _display_step(float(field["step"]), value)
	spin.step = step
	spin.allow_lesser = not bool(field["has_min"])
	spin.allow_greater = not bool(field["has_max"])
	# Exclusive schema bounds are made UNSELECTABLE (#476 review): offset the
	# SpinBox limit one step inside the boundary so the invalid exact-boundary value
	# cannot be entered. Clamp the limit so the current (valid) seed value stays
	# selectable — seeding must never move the authored number.
	if bool(field["has_min"]):
		var lo := float(field["min"])
		spin.min_value = minf(lo + step if bool(field["exclusive_min"]) else lo, value)
	else:
		spin.min_value = -1_000_000.0
	if bool(field["has_max"]):
		var hi := float(field["max"])
		spin.max_value = maxf(hi - step if bool(field["exclusive_max"]) else hi, value)
	else:
		spin.max_value = 1_000_000.0
	spin.value = value
	spin.custom_minimum_size = Vector2(160.0, 0.0)
	# bind(authority, key): the SpinBox reports only the new value; the binding
	# routes it to the right authority key (the LevelController group-lookup idiom
	# — no per-field method, one handler).
	spin.value_changed.connect(_on_value_changed.bind(authority, String(field["key"])))
	row.add_child(spin)
	_rows.append({"authority": authority, "key": String(field["key"]), "spin": spin})
	_field_count += 1
	return row


func _on_value_changed(value: float, authority: String, key: String) -> void:
	_model.set_number(authority, key, value)
	field_edited.emit()


## Re-seed every SpinBox from the model — called after DIRECT MANIPULATION mutates
## a JSON key a form also exposes (arena_min_x/arena_max_x are drag targets AND
## form fields), so a drag and its form row never drift and a later form edit
## never overwrites the drag with stale data (#476 review). Uses set_value_no_signal
## so the refresh does not re-fire value_changed — no dirty loop, no clobber.
func refresh() -> void:
	for row: Dictionary in _rows:
		var spin: SpinBox = row["spin"]
		spin.set_value_no_signal(_model.get_number(String(row["authority"]), String(row["key"])))


## A humane SpinBox step: never coarser than the schema hint, but fine enough that
## the seed value keeps its own precision (a 0.15s duration must not display/snap
## as an integer just because its field carries no upper bound). Value-scale wins
## for small magnitudes; wide feel numbers keep the schema's 1.0 nudge.
static func _display_step(schema_step: float, value: float) -> float:
	var magnitude := absf(value)
	var value_step := 1.0
	if magnitude > 0.0 and magnitude < 4.0:
		value_step = 0.01
	elif magnitude < 50.0:
		value_step = 0.1
	return minf(schema_step, value_step)
