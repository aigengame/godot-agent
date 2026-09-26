extends RefCounted

# gda headless operations payload: the shared value module (ADR-0043 §2, §7).
# The Value projection, the --value coercion with its write-fidelity checks, and
# the parameter and property readers. Static: callers reach it through a preload
# constant, and it reports no failure. The block between the shared-coercion
# markers is mirrored byte-for-byte (modulo `static`) in the harness until #1016.


# --- BEGIN shared coercion (keep byte-identical: operations.gd <-> gda_harness.gd) ---
# These pure property-introspection / value-coercion helpers are DUPLICATED
# verbatim into src/gda/harness/gda_harness.gd: operations.gd runs via
# `godot --headless --script <abs-fs-path>` (often projectless) while the harness
# is a res:// autoload, so no single preload() reaches both and install.py copies
# one file. tests/harness/test_harness_coercion_mirror.py asserts the two blocks are
# byte-identical (modulo leading tabs), so an edit here must be mirrored there.
# Whether a property-list entry is a STORAGE property — the ones node get
# reports and node set targets: the properties that serialize into the .tscn,
# excluding the engine's category headers, group separators, and editor-only
# (non-storage) entries. This is the same usage flag the scene serializer keys
# on, so node get reports exactly the surface a saved scene can carry.
static func _is_storage_property(prop: Dictionary) -> bool:
	var usage := int(prop.get("usage", 0))
	return (usage & PROPERTY_USAGE_STORAGE) != 0


# The declared Godot type of a settable property on the node, or TYPE_NIL if the
# node has no storage property by that name. node set keys coercion off this:
# the value's target type comes from the property the node actually declares,
# never from guessing.
static func _property_type(node: Node, prop_name: String) -> int:
	for prop in node.get_property_list():
		if String(prop.get("name", "")) == prop_name and _is_storage_property(prop):
			return int(prop.get("type", TYPE_NIL))
	return TYPE_NIL


# Read a string param defensively: a non-string value (the params arrive as
# arbitrary JSON) is treated as absent rather than crashing a typed assignment,
# so a malformed param surfaces as a structured failure, not a runtime error.
static func _string_param(params: Dictionary, key: String) -> String:
	var value: Variant = params.get(key, "")
	if value is String:
		return value
	return ""


# The Godot type name for a Variant.Type, as node get / node set report it
# (the same spelling type_string uses: "int", "Vector2", "Color", …).
static func _type_name(type: int) -> String:
	return type_string(type)


# The value projection's hard recursion depth cap (ADR-0035): a compound value
# nested deeper than this degrades to its string form instead of recursing on.
# Deliberately NO visited-set — references are not descended and non-whitelisted
# Objects stop at str(), so on-disk stored values are acyclic trees; the cap is
# the backstop against a pathological self-referential Dictionary live-side.
const JSONIFY_MAX_DEPTH := 16

# The properties an inline value projection excludes (ADR-0035): the
# Object/Resource base bookkeeping — every InputEvent IS a Resource, so
# without the exclusion a path-less value Object would emit an empty
# resource_path and masquerade as a reference projection (and the rest is
# noise) — plus the RESERVED discriminator key `object_string` (#666): only
# the texture projection emits it, so an inline class's own storage property
# of that name is dropped, not copied — otherwise a presence-based consumer
# would misclassify the inline projection as a texture.
const JSONIFY_BOOKKEEPING_PROPS: Array[String] = [
	"resource_path", "resource_name", "resource_local_to_scene", "script",
	"object_string",
]

# The read-side Value projection (ADR-0035, grown from issue #55): render a
# Godot Variant into the structured JSON a result's value field carries.
# Scalars pass through; the fixed-shape value types node set supports become
# flat number arrays so node get's output is exactly the projection node set
# accepts back: Vector2 → [x, y], Vector2i likewise, Color → [r, g, b, a].
# A Dictionary projects to a JSON object (keys stringified), an Array and the
# packed-array family to a JSON array, each value re-entering the projection;
# an Object renders as a reference projection, an inline value projection, or
# the str() fallback (the TYPE_OBJECT arm below). Any other type degrades to
# its string form rather than crashing JSON.stringify on an unencodable
# Variant, and the depth cap bounds the recursion on the compound arms — so
# the projection is always JSON-encodable.
static func _jsonify(value: Variant, depth: int = 0, texture_digest: bool = false) -> Variant:
	match typeof(value):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STRING, TYPE_STRING_NAME:
			return value
		TYPE_VECTOR2:
			return [value.x, value.y]
		TYPE_VECTOR2I:
			return [value.x, value.y]
		TYPE_COLOR:
			return [value.r, value.g, value.b, value.a]
		TYPE_DICTIONARY:
			# The cap guards only the compound arms: a scalar is never
			# stringified by depth, however deep it sits.
			if depth >= JSONIFY_MAX_DEPTH:
				return str(value)
			var out := {}
			# Insertion-ordered iteration; keys are coerced to strings, so two
			# keys that collide after stringification resolve last-wins by
			# assignment order (deterministic, ADR-0035).
			for key in value.keys():
				out[str(key)] = _jsonify(value[key], depth + 1, texture_digest)
			return out
		TYPE_ARRAY, TYPE_PACKED_BYTE_ARRAY, TYPE_PACKED_INT32_ARRAY, \
		TYPE_PACKED_INT64_ARRAY, TYPE_PACKED_FLOAT32_ARRAY, \
		TYPE_PACKED_FLOAT64_ARRAY, TYPE_PACKED_STRING_ARRAY, \
		TYPE_PACKED_VECTOR2_ARRAY, TYPE_PACKED_VECTOR3_ARRAY, \
		TYPE_PACKED_COLOR_ARRAY, TYPE_PACKED_VECTOR4_ARRAY:
			if depth >= JSONIFY_MAX_DEPTH:
				return str(value)
			var items := []
			# Element-wise re-entry: a PackedVector2Array element projects as
			# [x, y]; an element type with no structured arm of its own (e.g.
			# Vector3) stays str(), per the fixed-shape list above.
			for element in value:
				items.append(_jsonify(element, depth + 1, texture_digest))
			return items
		TYPE_OBJECT:
			# A freed live Object (harness side) must not be introspected.
			if not is_instance_valid(value):
				return str(value)
			if depth >= JSONIFY_MAX_DEPTH:
				return str(value)
			# Reference projection: a Resource with a res:// path is named by
			# type and path, never inlined — the read-side mirror of ADR-0033's
			# write-side reference. A sub-resource path (res://x.tscn::…)
			# counts as a reference too.
			if value is Resource and String(value.resource_path).begins_with("res://"):
				return {"type": value.get_class(), "resource_path": value.resource_path}
			# Texture projection (#666, ADR-0035 amendment): a PATH-LESS Texture2D
			# — a runtime-created texture (ImageTexture.create_from_image) has no
			# res:// path, so the reference arm above cannot name it and the string
			# fallback's instance ID cannot say what it shows. PATH-LESS only:
			# a non-empty, non-res:// path (user://, take_over_path) stays the
			# string fallback it always was — #666's scope is the empty path. A
			# fixed shape read off cheap getters: class + dimensions. `object_string` keeps the old
			# str() form as secondary diagnostics and is this kind's DISCRIMINATOR
			# (no other object shape emits it; `resource_path` stays
			# reference-only, not even null here). `digest` is opt-in
			# (texture_digest): get_image() is a GPU-to-CPU readback on the live
			# side, not a price every read should pay; an image the engine cannot
			# read back keeps digest null. Dimensions and format prefix the hashed
			# bytes so same-bytes textures of different shapes do not collide.
			if value is Texture2D and String(value.resource_path).is_empty():
				var texture_projection := {
					"type": value.get_class(),
					"width": value.get_width(),
					"height": value.get_height(),
					"object_string": str(value),
					"digest": null,
				}
				if texture_digest:
					var image: Image = value.get_image()
					if image != null and not image.is_empty():
						var ctx := HashingContext.new()
						if ctx.start(HashingContext.HASH_SHA256) == OK:
							var shape := "%dx%d:%d:" % [
								image.get_width(), image.get_height(), image.get_format(),
							]
							ctx.update(shape.to_utf8_buffer())
							ctx.update(image.get_data())
							texture_projection["digest"] = "sha256:" + ctx.finish().hex_encode()
				return texture_projection
			# Inline value projection: a whitelisted path-less value Object
			# (InputEvent subclasses initially) projects its own storage
			# properties. The whitelist is the risk-isolation boundary that
			# keeps this shared projection safe on the live side, where an
			# arbitrary Object could be a whole scene tree (ADR-0035).
			if value is InputEvent:
				var projected := {}
				for prop in value.get_property_list():
					if not _is_storage_property(prop):
						continue
					var prop_name := String(prop.get("name", ""))
					if prop_name in JSONIFY_BOOKKEEPING_PROPS:
						continue
					projected[prop_name] = _jsonify(value.get(prop_name), depth + 1, texture_digest)
				# Assigned AFTER the loop so the discriminator shadows a
				# storage property named "type" (ADR-0035 documents the
				# shadowing — order matters).
				projected["type"] = value.get_class()
				return projected
			# String fallback: any other Object (not whitelisted, no res://
			# path — e.g. a live Node) keeps the existing str() form.
			return str(value)
		_:
			return str(value)


# Coerce a CLI string value to a property's declared Godot type (issue #55).
# The supported types and their accepted string forms are documented in the
# command catalog's "Property value coercion" section — keep the two in sync.
# Returns null when the value cannot be coerced to that type, which the caller
# reports as the clean uncoercible_value error. null is unambiguous as a
# failure signal because no supported target type coerces TO null.
# `current` lets typed Dictionary/Array properties/settings provide the
# destination type Godot should assign into; untyped and scalar coercion ignores it.
static func _coerce_value(raw: String, type: int, current: Variant = null) -> Variant:
	match type:
		TYPE_BOOL:
			return _coerce_bool(raw)
		TYPE_INT:
			return _coerce_int(raw)
		TYPE_FLOAT:
			return _coerce_float(raw)
		TYPE_STRING:
			return raw
		TYPE_STRING_NAME:
			return StringName(raw)
		TYPE_DICTIONARY:
			return _coerce_dictionary(raw, current)
		TYPE_ARRAY:
			return _coerce_array(raw, current)
		TYPE_VECTOR2:
			var parts: Variant = _coerce_float_list(raw, 2)
			return Vector2(parts[0], parts[1]) if parts != null else null
		TYPE_VECTOR2I:
			var parts: Variant = _coerce_int_list(raw, 2)
			return Vector2i(parts[0], parts[1]) if parts != null else null
		TYPE_COLOR:
			return _coerce_color(raw)
		_:
			return null


# A bool from "true"/"false" (case-insensitive), nothing else — so a typo never
# silently becomes false.
static func _coerce_bool(raw: String) -> Variant:
	var lowered := raw.strip_edges().to_lower()
	if lowered == "true":
		return true
	if lowered == "false":
		return false
	return null


static func _coerce_int(raw: String) -> Variant:
	var trimmed := raw.strip_edges()
	if not trimmed.is_valid_int():
		return null
	return trimmed.to_int()


# --- Float fidelity: the WRITE side of the engine's number domain (#772, #805) ---
#
# The rule below is about a LITERAL, not about a property type, so it reaches every
# float a write can spell: the scalar `--value` and the components of a Vector2 or a
# Color, which `_coerce_float` parses one at a time, and the JSON numbers inside a
# Dictionary or an Array value, which no per-element step parses at all and which
# `_destroyed_json_number` therefore reads from the raw text (#805). Until that was
# added the container was the one path where a destroyed float still landed
# silently — `--value '{"a": 1e-320}'` reported success and stored `{"a": 0.0}`.
#
# Godot reads a float literal with built_in_strtod (core/string/ustring.cpp),
# reached from GDScript as String.to_float() and from JSON.parse_string alike.
# ONE function, so the live wire's parser (#752) and this coercion do the same
# arithmetic and differ only in WHO spells the literal. On the wire gda spells it
# and must PREDICT the outcome (gda.live_numbers.wire_flattens_to_zero); here the
# CALLER spells it and the engine has already answered by the time coercion runs,
# so the policy OBSERVES the outcome instead. That is why one rule covers every
# way the parser destroys a value, each measured on Godot 4.6.3:
#   - an applied decimal exponent at or below -309 divides by an INFINITE power
#     of ten: "2.2250738585072014e-308" and "5e-324" arrive as 0.0 (#752's class);
#   - the parser keeps at most 18 mantissa digits COUNTING leading zeros, so a
#     fixed-notation literal that spends all 18 on zeros keeps no significant
#     digit at all: "0.000000000000000001" arrives as 0.0 while "1e-18" is exact.
#     That cliff is far higher than the wire's, and the wire never meets it,
#     because gda's own serializer writes scientific notation below 1e-4;
#   - a zero mantissa times an overflowed power is 0.0 * INF: "0e600" is NaN.
# A write PERSISTS — a .tscn, project.godot, a .tres, a running node's state — so
# gda REFUSES these instead of storing a number the caller never sent. Same answer
# as #752, reached from the same principle by a different route, and with a remedy
# the wire cannot offer: the caller owns the spelling, so re-spelling can work.
#
# NOT refused: low-order drift. The parser lands ordinary values 1 ULP away, and a
# full-precision literal between 1e-4 and 1e-2 up to 105 doubles away, because the
# leading zeros spend the 18-digit budget. Refusing that would reject ordinary game
# values, so it is DISCLOSED in the CLI contract instead, with its own remedy:
# scientific notation restores both of those corpus rows exactly. The measurement
# and the counts belong to `gda.live_numbers`, not to this comment.

# Whether `literal`'s own digits are all zeros — the spellings that MEAN zero
# ("0", "-0.0", "0.0000e5"), which the parser is right to read as 0.0.
static func _float_literal_names_zero(literal: String) -> bool:
	var mantissa := literal.lstrip("+-")
	var exponent_at := mantissa.to_lower().find("e")
	if exponent_at >= 0:
		mantissa = mantissa.left(exponent_at)
	for character in mantissa:
		if character != "0" and character != ".":
			return false
	return true


# Whether the parser DESTROYS `literal` — turns the number the caller spelled into
# a value that is not it at all. Asked of the literal the caller actually sent, and
# answered by RUNNING the parser rather than by modelling its arithmetic, so a
# mechanism this file does not know about is caught as well as the three it does.
# False for a value that is merely not a float spelling: that is the ordinary
# uncoercible failure, which this policy must not relabel.
static func _float_literal_is_destroyed(literal: String) -> bool:
	if not literal.is_valid_float():
		return false
	var parsed := literal.to_float()
	return is_nan(parsed) or (parsed == 0.0 and not _float_literal_names_zero(literal))


# Whether `character` can appear inside a JSON number token. Deliberately a
# CHARACTER class and not a number grammar: the scan below runs only on text the
# JSON parser already accepted, so the grammar has been checked once, by the
# engine, and re-implementing it here would be a second opinion about it.
static func _is_json_number_char(character: String) -> bool:
	return character == "-" or character == "+" or character == "." \
			or character == "e" or character == "E" \
			or (character >= "0" and character <= "9")


# The first JSON number literal in `raw` that the parser DESTROYS, or "" — the
# container half of the #772 rule (#805).
#
# A container's coercion is `JSON.parse_string` as the gate plus one atomic
# `str_to_var(raw)`; there is no per-element step to hook, and by the time a float
# exists inside the parsed value its literal is gone. So the literals are read from
# the RAW text, which is the only place they still are.
#
# Reading text needs one rule to be safe, and it is STRING-AWARENESS: a JSON
# string's bytes are never a number, whatever they spell. That single rule disposes
# of the two ways ORDINARY input invites a text scan to refuse a write the engine
# would have kept faithfully. A value that merely LOOKS numeric is one — `{"a":
# "1e-320"}` stores the six-character string, and no float is parsed anywhere in
# it. A KEY is the other — every JSON key is a string, so `{"1e-320": 1.0}` names a
# member and the `1.0` beside it is the only number present. Escapes are honoured
# while skipping, so a quote INSIDE a string (`{"a\": 1e-320 fake": 1.0}`, valid
# JSON whose key holds that text) does not end it early and leak its bytes into the
# scan.
#
# A third way is left open, ACCEPTED rather than closed: a member the parser then
# DISCARDS. Godot's JSON keeps the LAST value of a repeated key (measured on 4.6.3:
# `{"a": 1e-320, "a": 2.0}` parses to `{"a": 2.0}`), but the scan reads the text and
# sees the discarded literal too, so that write is refused although nothing
# destroyed would have been stored. Telling a discarded token from a kept one needs
# the key-and-position bookkeeping of a real parser — the second opinion about the
# engine's grammar this scan avoids by construction — while the over-refusal is in
# the safe direction: nothing wrong is written, and the remedy is to spell the key
# once.
#
# Outside strings, valid JSON spells only structure, `true`/`false`/`null`, and
# numbers, so a maximal run of number characters IS a number token — with the one
# exception of the lone "e" the two keyword spellings contribute, which is not a
# float spelling and which `_float_literal_is_destroyed` therefore answers false
# for. Nothing else needs excluding, because the text is already valid JSON.
#
# That "already valid JSON" is also what closes the third edge. `str_to_var`
# accepts richer Variant syntax than JSON, and `{"a": Vector2(1e-320, 0)}` really
# does build a zeroed Vector2 through it — but that text is NOT JSON (measured on
# Godot 4.6.3: the parse fails with "Expected 'true', 'false', or 'null', got
# 'Vector'"), so the gate refuses it before `str_to_var` is reached and a
# constructor is unreachable through this coercion. This scan deliberately does not
# try to read one: it would be reading text the gate has already rejected, and
# would blame the float parser for a syntax refusal.
static func _destroyed_json_number(raw: String) -> String:
	var index := 0
	var length := raw.length()
	while index < length:
		var character := raw[index]
		if character == "\"":
			index += 1
			while index < length:
				if raw[index] == "\\":
					index += 2
					continue
				if raw[index] == "\"":
					index += 1
					break
				index += 1
			continue
		if not _is_json_number_char(character):
			index += 1
			continue
		var start := index
		while index < length and _is_json_number_char(raw[index]):
			index += 1
		var literal := raw.substr(start, index - start)
		if _float_literal_is_destroyed(literal):
			return literal
	return ""


# The literal whose destruction ACTUALLY refused this coercion, or "" when the
# refusal was anything else. A note must never explain a failure it did not
# diagnose, so this walks exactly what `_coerce_value` walks for `type`, in the
# same order and behind the same gates: only TYPE_FLOAT, TYPE_VECTOR2, TYPE_COLOR
# (through `_coerce_float`) and TYPE_DICTIONARY / TYPE_ARRAY (through the raw-text
# scan) refuse on a destroyed literal at all — TYPE_INT, TYPE_VECTOR2I and the rest
# refuse for reasons of their own and no float spelling would help them; a wrong
# component count refuses on ARITY before a component is parsed; a Color in hex
# form parses no float; and a component that is not a float spelling at all is the
# ordinary uncoercible failure, which stops the walk where `_coerce_float_list`
# stops. The container arms repeat their coercion's JSON gate for the same reason:
# text that is not JSON — or is JSON of the OTHER container type — was refused by
# the gate, not by the float parser, so it keeps the plain message.
#
# For the SCALAR arms that second walk re-derives a different shape (split, arity,
# hex form), and that independence is what keeps the note honest. For the container
# arms it re-derives nothing — gate plus scan, twice — which is affordable at two
# arms and is the trigger to watch: if a THIRD container-shaped type ever reaches
# this rule, stop walking and have `_coerce_value` hand back the reason it refused.
static func _destroyed_float_literal(raw: String, type: int) -> String:
	var components: PackedStringArray
	match type:
		TYPE_FLOAT:
			components = PackedStringArray([raw])
		TYPE_VECTOR2:
			components = raw.split(",")
			if components.size() != 2:
				return ""
		TYPE_COLOR:
			var trimmed := raw.strip_edges()
			if trimmed.begins_with("#"):
				return ""
			components = trimmed.split(",")
			if components.size() != 3 and components.size() != 4:
				return ""
		TYPE_DICTIONARY, TYPE_ARRAY:
			if typeof(JSON.parse_string(raw)) != type:
				return ""
			return _destroyed_json_number(raw)
		_:
			return ""
	for part in components:
		var literal := part.strip_edges()
		if not literal.is_valid_float():
			return ""
		if _float_literal_is_destroyed(literal):
			return literal
	return ""


# The explanation appended to an uncoercible_value message when a destroyed
# literal is what refused the coercion, and "" for every OTHER coercion failure —
# so "abc" on a float, any value on an int, a non-JSON value on a Dictionary, and a
# three-component Vector2 all keep the message they always had. `type` is the
# declared type the failed `_coerce_value` was given; a list type names the ONE
# offending component, and a container the ONE offending JSON number, rather than
# the whole argument.
static func _float_fidelity_note(raw: String, type: int) -> String:
	var literal := _destroyed_float_literal(raw, type)
	if literal.is_empty():
		return ""
	var outcome := "NaN" if is_nan(literal.to_float()) else "0.0"
	return " — Godot's own float parser reads " + literal.c_escape() + " as " \
			+ outcome + ", so the write would store a number you did not send;" \
			+ " gda refuses it instead of changing your value silently. Try the" \
			+ " same value in scientific notation carrying only the digits it needs" \
			+ " (1e-18, not 0.000000000000000001); if that reads as 0.0 too, the" \
			+ " value is below this parser's reach and no decimal spelling delivers" \
			+ " it — the live wire refuses that same class as well"


static func _coerce_float(raw: String) -> Variant:
	var trimmed := raw.strip_edges()
	# is_valid_float accepts integer spellings too, which is intended: "3" is a
	# valid float value, and Godot stores it as 3.0.
	if not trimmed.is_valid_float():
		return null
	# A literal the parser destroys is refused (#772). null is the same uncoercible
	# signal a non-numeric value gives; _float_fidelity_note tells the caller which
	# of the two it was, so the two failures do not need two codes.
	if _float_literal_is_destroyed(trimmed):
		return null
	return trimmed.to_float()


# Parse a comma-separated list of exactly `count` floats (e.g. "10,20" for a
# Vector2). Whitespace around each component is tolerated; a wrong count or a
# non-numeric component fails the whole coercion.
static func _coerce_float_list(raw: String, count: int) -> Variant:
	var parts := raw.split(",")
	if parts.size() != count:
		return null
	var out: Array[float] = []
	for part in parts:
		var coerced: Variant = _coerce_float(part)
		if coerced == null:
			return null
		out.append(coerced)
	return out


static func _coerce_int_list(raw: String, count: int) -> Variant:
	var parts := raw.split(",")
	if parts.size() != count:
		return null
	var out: Array[int] = []
	for part in parts:
		var coerced: Variant = _coerce_int(part)
		if coerced == null:
			return null
		out.append(coerced)
	return out


# A Color from either a "#rrggbb"/"#rrggbbaa" hex string or a comma-separated
# list of 3 (rgb) or 4 (rgba) floats in 0..1. Godot's Color.html validates the
# hex form; the float-list form reuses the shared numeric coercion.
static func _coerce_color(raw: String) -> Variant:
	var trimmed := raw.strip_edges()
	if trimmed.begins_with("#"):
		if not Color.html_is_valid(trimmed):
			return null
		return Color.html(trimmed)
	var parts := trimmed.split(",")
	if parts.size() != 3 and parts.size() != 4:
		return null
	var out: Array[float] = []
	for part in parts:
		var coerced: Variant = _coerce_float(part)
		if coerced == null:
			return null
		out.append(coerced)
	if out.size() == 3:
		return Color(out[0], out[1], out[2])
	return Color(out[0], out[1], out[2], out[3])


static func _coerce_dictionary(raw: String, current: Variant = null) -> Variant:
	var parsed: Variant = JSON.parse_string(raw)
	if not (parsed is Dictionary):
		return null
	# A number the parser destroys is refused here exactly as `_coerce_float`
	# refuses a scalar one (#805): same code, same note, same reason — the write
	# would store a value the caller never sent. Scanned on the raw text, and only
	# now that the gate has accepted it (see `_destroyed_json_number`).
	if not _destroyed_json_number(raw).is_empty():
		return null
	var variant: Variant = str_to_var(raw)
	if not (variant is Dictionary):
		return null
	var dictionary: Dictionary = variant
	if current is Dictionary:
		var current_dictionary: Dictionary = current
		if current_dictionary.is_typed():
			var typed_dictionary: Dictionary = current_dictionary.duplicate()
			typed_dictionary.clear()
			typed_dictionary.assign(dictionary)
			if typed_dictionary.size() != dictionary.size():
				return null
			return typed_dictionary
	return dictionary


static func _coerce_array(raw: String, current: Variant = null) -> Variant:
	var parsed: Variant = JSON.parse_string(raw)
	if not (parsed is Array):
		return null
	# Same refusal as `_coerce_dictionary`'s, for the same reason (#805).
	if not _destroyed_json_number(raw).is_empty():
		return null
	var variant: Variant = str_to_var(raw)
	if not (variant is Array):
		return null
	var array: Array = variant
	if current is Array:
		var current_array: Array = current
		if current_array.is_typed():
			var typed_array: Array = current_array.duplicate()
			typed_array.clear()
			typed_array.assign(array)
			if typed_array.size() != array.size():
				return null
			return typed_array
	return array
# --- END shared coercion ---
