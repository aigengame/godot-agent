extends Node

# The gda harness (ADR-0017, ADR-0018). Installed as a project [autoload] by
# `gda daemon`. It is INERT unless gda-daemon launched this run: at startup it
# looks for the daemon's launch marker in the user args (after `--`); absent it,
# it returns early — opening no connection, starting no server — and stays
# resident. It must NOT free()/queue_free() itself: Godot crashes if an autoload
# is freed at runtime, so a resident do-nothing node is the safe inert form. Thus
# it does nothing in a human editor run, a plain `godot --path` run, and a
# shipped/exported build.
#
# When the daemon DID launch this run, the marker is followed by the daemon's
# harness socket path and an auth token. The harness connects back over a Unix
# domain socket (StreamPeerUDS, Godot 4.6+), presents the token, then serves one
# live op at a time: it reads a length-prefixed JSON request, runs it on the main
# thread at a frame boundary (frame-coherent, ADR-0020), and writes back the
# ADR-0002 sentinel payload as one length-prefixed frame.

const LAUNCH_MARKER := "gda-daemon"
const RESULT_BEGIN := "<<<GDA:RESULT>>>"
const RESULT_END := "<<<GDA:END>>>"

# The live operations this harness serves, keyed by their wire op name (#220).
const OP_GAME_TREE := "game-tree"
const OP_GAME_GET := "game-get"
const OP_GAME_SET := "game-set"

# The per-op LIVE failure codes the harness reports in-band (#220). Each MUST be a
# registered LIVE-category code (src/gda/error_codes.py) so the daemon's exit-0
# relay is mapped by classify_live, not misrouted to contract_violation; a Python
# mirror test (tests/test_error_registry.py) keeps these in sync with the registry.
const LIVE_ERROR_NODE_NOT_FOUND := "live_node_not_found"
const LIVE_ERROR_UNKNOWN_PROPERTY := "live_unknown_property"
const LIVE_ERROR_UNCOERCIBLE_VALUE := "live_uncoercible_value"

var _peer: StreamPeerUDS = null
var _authed := false
var _pending = null
var _pending_frames := 0


func _ready() -> void:
	var user_args := OS.get_cmdline_user_args()
	var idx := user_args.find(LAUNCH_MARKER)
	if idx == -1 or idx + 2 >= user_args.size():
		# Inert: not launched by gda-daemon. Stay resident and do nothing.
		return
	var socket_path: String = user_args[idx + 1]
	var token: String = user_args[idx + 2]

	var peer := StreamPeerUDS.new()
	peer.big_endian = true
	if peer.connect_to_host(socket_path) != OK:
		return
	_peer = peer
	# The first frame the daemon expects is the auth token.
	_send_frame(token.to_utf8_buffer())
	_authed = true


func _process(_delta: float) -> void:
	if _peer == null or not _authed:
		return
	_peer.poll()
	# Read one pending request when a full length prefix is available; the body
	# follows in the same daemon write, so get_data does not block in practice.
	if _pending == null and _peer.get_available_bytes() >= 4:
		var length := _peer.get_u32()
		var chunk := _peer.get_data(length)
		if chunk[0] == OK:
			_pending = JSON.parse_string((chunk[1] as PackedByteArray).get_string_from_utf8())
			_pending_frames = 0
	# Serve only once the runtime scene graph is up — the harness autoload's
	# _ready runs BEFORE the main scene is instantiated, so a request that arrives
	# during boot waits for current_scene (frame-coherent, ADR-0020); a bounded
	# fallback to the SceneTree root means a sceneless project never hangs.
	if _pending != null:
		_pending_frames += 1
		if get_tree().current_scene != null or _pending_frames > 300:
			_send_frame(_run(_pending).to_utf8_buffer())
			_pending = null


func _send_frame(payload: PackedByteArray) -> void:
	_peer.put_u32(payload.size())
	_peer.put_data(payload)


# Dispatch one live request to its handler by op name (#220). A request is the
# ADR-0002 {"op", "params"} envelope the daemon relays verbatim; each handler
# returns a full sentinel-framed payload (a success via _ok or a failure via
# _error), so adding an op is one match arm + one handler.
func _run(request) -> String:
	if typeof(request) != TYPE_DICTIONARY:
		return _error("operation_failed", "unsupported live operation")
	var op: Variant = request.get("op")
	var params: Variant = request.get("params", {})
	if typeof(params) != TYPE_DICTIONARY:
		params = {}
	match op:
		OP_GAME_TREE:
			return _handle_game_tree()
		OP_GAME_GET:
			return _handle_game_get(params)
		OP_GAME_SET:
			return _handle_game_set(params)
		_:
			return _error("operation_failed", "unsupported live operation")


func _handle_game_tree() -> String:
	var scene: Node = get_tree().current_scene
	if scene == null:
		scene = get_tree().root
	return _ok({"root": _serialize(scene)})


# game get: resolve a node by its ABSOLUTE runtime path (as game tree reports it,
# e.g. /root/Main/Player) and report its storage properties as typed JSON — the
# runtime counterpart of headless node get. An optional `property` param filters
# to that single property; absent from the storage set, it is live_unknown_property.
func _handle_game_get(params: Dictionary) -> String:
	var path := _string_param(params, "node")
	var node := _resolve_runtime_node(path)
	if node == null:
		return _error(LIVE_ERROR_NODE_NOT_FOUND,
				"no node at runtime path: " + path)

	var wanted := _string_param(params, "property")
	var has_filter := params.has("property") and not wanted.is_empty()
	var properties: Array = []
	for prop in node.get_property_list():
		if not _is_storage_property(prop):
			continue
		var prop_name := String(prop.get("name", ""))
		if has_filter and prop_name != wanted:
			continue
		properties.append({
			"name": prop_name,
			"type": _type_name(int(prop.get("type", TYPE_NIL))),
			"value": _jsonify(node.get(prop_name)),
		})
	if has_filter and properties.is_empty():
		return _error(LIVE_ERROR_UNKNOWN_PROPERTY,
				"node " + path + " has no readable property: " + wanted)

	return _ok({
		"path": path,
		"name": String(node.name),
		"type": node.get_class(),
		"properties": properties,
	})


# game set: resolve a node by its ABSOLUTE runtime path, coerce the CLI string
# value to the property's declared Godot type, and set it on the live node — the
# runtime counterpart of headless node set, using the SAME coercion table. The
# write runs synchronously on the main thread at the _process frame boundary
# (frame-coherent, ADR-0020); no extra threading. The coerced value is read back
# and echoed in the same JSON projection game get reports.
func _handle_game_set(params: Dictionary) -> String:
	var path := _string_param(params, "node")
	var node := _resolve_runtime_node(path)
	if node == null:
		return _error(LIVE_ERROR_NODE_NOT_FOUND,
				"no node at runtime path: " + path)

	var prop_name := _string_param(params, "property")
	var declared_type := _property_type(node, prop_name)
	if declared_type == TYPE_NIL:
		return _error(LIVE_ERROR_UNKNOWN_PROPERTY,
				"node " + path + " has no settable property: " + prop_name)

	var raw_value := _string_param(params, "value")
	var coerced: Variant = _coerce_value(raw_value, declared_type)
	if coerced == null:
		return _error(LIVE_ERROR_UNCOERCIBLE_VALUE,
				"cannot coerce value " + raw_value.c_escape()
				+ " to " + _type_name(declared_type) + " for property " + prop_name
				+ " on node " + path)

	node.set(prop_name, coerced)
	return _ok({
		"path": path,
		"property": prop_name,
		"type": _type_name(declared_type),
		"value": _jsonify(node.get(prop_name)),
	})


# Resolve a node by its ABSOLUTE runtime path (e.g. /root/Main/Player), the form
# game tree emits via Node.get_path(). The headless _resolve_node takes a
# scene-root-relative path and rejects absolute, so the live layer resolves off
# the SceneTree root instead. null when the path resolves to nothing.
func _resolve_runtime_node(path: String) -> Node:
	if path.is_empty():
		return null
	return get_tree().root.get_node_or_null(NodePath(path))


func _serialize(node: Node) -> Dictionary:
	var children: Array = []
	for child in node.get_children():
		children.append(_serialize(child))
	return {
		"name": String(node.name),
		"type": node.get_class(),
		"path": String(node.get_path()),
		"children": children,
	}


func _ok(payload: Dictionary) -> String:
	return RESULT_BEGIN + JSON.stringify(payload) + RESULT_END


func _error(code: String, message: String) -> String:
	return RESULT_BEGIN + JSON.stringify({"error": {"code": code, "message": message}}) + RESULT_END


# --- BEGIN shared coercion (keep byte-identical: operations.gd <-> gda_harness.gd) ---
# These pure property-introspection / value-coercion helpers are DUPLICATED
# verbatim into src/gda/harness/gda_harness.gd: operations.gd runs via
# `godot --headless --script <abs-fs-path>` (often projectless) while the harness
# is a res:// autoload, so no single preload() reaches both and install.py copies
# one file. tests/test_harness_coercion_mirror.py asserts the two blocks are
# byte-identical (modulo leading tabs), so an edit here must be mirrored there.
# Whether a property-list entry is a STORAGE property — the ones node get
# reports and node set targets: the properties that serialize into the .tscn,
# excluding the engine's category headers, group separators, and editor-only
# (non-storage) entries. This is the same usage flag the scene serializer keys
# on, so node get reports exactly the surface a saved scene can carry.
func _is_storage_property(prop: Dictionary) -> bool:
	var usage := int(prop.get("usage", 0))
	return (usage & PROPERTY_USAGE_STORAGE) != 0


# The declared Godot type of a settable property on the node, or TYPE_NIL if the
# node has no storage property by that name. node set keys coercion off this:
# the value's target type comes from the property the node actually declares,
# never from guessing.
func _property_type(node: Node, prop_name: String) -> int:
	for prop in node.get_property_list():
		if String(prop.get("name", "")) == prop_name and _is_storage_property(prop):
			return int(prop.get("type", TYPE_NIL))
	return TYPE_NIL


# Read a string param defensively: a non-string value (the params arrive as
# arbitrary JSON) is treated as absent rather than crashing a typed assignment,
# so a malformed param surfaces as a structured failure, not a runtime error.
func _string_param(params: Dictionary, key: String) -> String:
	var value: Variant = params.get(key, "")
	if value is String:
		return value
	return ""


# The Godot type name for a Variant.Type, as node get / node set report it
# (the same spelling type_string uses: "int", "Vector2", "Color", …).
func _type_name(type: int) -> String:
	return type_string(type)


# Project a Godot property value into JSON-safe form for the result payload
# (issue #55). Scalars pass through; the packed value types node set supports
# become flat number arrays so node get's output is exactly the projection node
# set accepts back: Vector2 → [x, y], Vector2i likewise, Color → [r, g, b, a].
# Any other type degrades to its string form rather than crashing JSON.stringify
# on an unencodable Variant — node get reports the whole storage surface, but
# only the coercible types claim a structured projection.
func _jsonify(value: Variant) -> Variant:
	match typeof(value):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STRING, TYPE_STRING_NAME:
			return value
		TYPE_VECTOR2:
			return [value.x, value.y]
		TYPE_VECTOR2I:
			return [value.x, value.y]
		TYPE_COLOR:
			return [value.r, value.g, value.b, value.a]
		_:
			return str(value)


# Coerce a CLI string value to a property's declared Godot type (issue #55).
# The supported types and their accepted string forms are documented in the
# command catalog's "Property value coercion" section — keep the two in sync.
# Returns null when the value cannot be coerced to that type, which the caller
# reports as the clean uncoercible_value error. null is unambiguous as a
# failure signal because no supported target type coerces TO null.
func _coerce_value(raw: String, type: int) -> Variant:
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
func _coerce_bool(raw: String) -> Variant:
	var lowered := raw.strip_edges().to_lower()
	if lowered == "true":
		return true
	if lowered == "false":
		return false
	return null


func _coerce_int(raw: String) -> Variant:
	var trimmed := raw.strip_edges()
	if not trimmed.is_valid_int():
		return null
	return trimmed.to_int()


func _coerce_float(raw: String) -> Variant:
	var trimmed := raw.strip_edges()
	# is_valid_float accepts integer spellings too, which is intended: "3" is a
	# valid float value, and Godot stores it as 3.0.
	if not trimmed.is_valid_float():
		return null
	return trimmed.to_float()


# Parse a comma-separated list of exactly `count` floats (e.g. "10,20" for a
# Vector2). Whitespace around each component is tolerated; a wrong count or a
# non-numeric component fails the whole coercion.
func _coerce_float_list(raw: String, count: int) -> Variant:
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


func _coerce_int_list(raw: String, count: int) -> Variant:
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
func _coerce_color(raw: String) -> Variant:
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
# --- END shared coercion ---

