extends RefCounted

## Derives the Panda Adventure Editor's numeric hand-tune FORM fields straight
## from a config's JSON Schema (gADR-0012, #441).
##
## The forms MAP FROM the existing `data/schema/*.json` — the authoritative place
## the config's numeric types and ranges are already encoded — instead of a
## hand-forked field registry that could drift from the schema the builder
## validates against. This keeps ONE source for "which numbers exist and what
## bounds they carry": the schema. Each derived field becomes one SpinBox
## (EditorForms), bound to the JSON authority value, so a Save writes the number
## back to JSON and re-derives through the ONE Python builder (the forms half of
## the gADR-0012 round-trip: forms -> JSON -> builder -> reload).
##
## PURE and node-free (the logic-seam shape the game's systems use): a parsed
## schema Dictionary in, a field-spec Array out — so the extraction is exercised
## headless (the editor round-trip seam) without a Control tree.
##
## Scope: SCALAR numbers only (JSON Schema `type: "number"`). Array-valued numeric
## properties (RGBA colors, [x, y] positions/sizes, [w, h] extents) are the
## direct-manipulation / color-picker channel (#438), never a free-text or
## per-component form — so they are deliberately skipped here.


## The numeric scalar fields of a parsed JSON-Schema document, in schema order
## (Godot Dictionaries preserve JSON key order). Each field spec is:
##   {
##     "key": String,        # the JSON property name (the authority key)
##     "label": String,      # a humanized label for the SpinBox row
##     "min": float,         # lower bound (or -INF when the schema sets none)
##     "max": float,         # upper bound (or INF when the schema sets none)
##     "has_min": bool,      # whether the schema bounded it below
##     "has_max": bool,      # whether the schema bounded it above
##     "step": float,        # a sensible SpinBox increment for the field's range
##   }
## A non-object schema, or one without `properties`, yields an empty Array.
static func numeric_fields(schema: Dictionary) -> Array[Dictionary]:
	var fields: Array[Dictionary] = []
	var properties: Variant = schema.get("properties", {})
	if typeof(properties) != TYPE_DICTIONARY:
		return fields
	for key: String in (properties as Dictionary):
		var prop: Variant = properties[key]
		if typeof(prop) != TYPE_DICTIONARY:
			continue
		# Scalar numbers only: `type: "number"` (an array-of-number property is a
		# color/position/size — the direct-manipulation channel, never a form).
		if String((prop as Dictionary).get("type", "")) != "number":
			continue
		fields.append(_field_spec(key, prop))
	return fields


## Build one field spec from a property schema — folding the four JSON-Schema
## bound keywords (minimum / maximum and their exclusive siblings) into a single
## numeric floor/ceiling the SpinBox can enforce. An exclusive bound is treated
## as the SpinBox limit (the offline builder's jsonschema pass stays the hard
## gate that rejects the exact-boundary value on derive — the form only needs a
## humane range, not a re-implementation of schema validation).
static func _field_spec(key: String, prop: Dictionary) -> Dictionary:
	var has_min := prop.has("minimum") or prop.has("exclusiveMinimum")
	var has_max := prop.has("maximum") or prop.has("exclusiveMaximum")
	var lo := float(prop.get("minimum", prop.get("exclusiveMinimum", -INF)))
	var hi := float(prop.get("maximum", prop.get("exclusiveMaximum", INF)))
	return {
		"key": key,
		"label": _humanize(key),
		"min": lo,
		"max": hi,
		"has_min": has_min,
		"has_max": has_max,
		"step": _step_for(has_max, hi),
	}


## A readable SpinBox increment: tight (0.01 / 0.05) for the small unit ranges a
## 0..1 or seconds-scale field carries, 1.0 for the wide px / px·s⁻¹ feel numbers.
## The user can always type an exact value; this only sizes the arrow nudge.
static func _step_for(has_max: bool, hi: float) -> float:
	if has_max and hi <= 1.0:
		return 0.01
	if has_max and hi <= 4.0:
		return 0.05
	return 1.0


## "move_speed" -> "Move Speed": a per-word Title-Case of the snake_case key, for
## the SpinBox row label (the key stays the authority reference).
static func _humanize(key: String) -> String:
	var words := PackedStringArray()
	for word in key.split("_", false):
		words.append(word.substr(0, 1).to_upper() + word.substr(1))
	return " ".join(words)
