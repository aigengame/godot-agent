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

# The live operations this harness serves, keyed by their wire op name (#220, #223).
const OP_GAME_TREE := "game-tree"
const OP_GAME_GET := "game-get"
const OP_GAME_SET := "game-set"
const OP_PERF_MONITORS := "perf-monitors"
const OP_PERF_MONITOR := "perf-monitor"

# The per-op LIVE failure codes the harness reports in-band (#220, #223). Each MUST
# be a registered LIVE-category code (src/gda/error_codes.py) so the daemon's exit-0
# relay is mapped by classify_live, not misrouted to contract_violation; a Python
# mirror test (tests/test_error_registry.py) keeps these in sync with the registry.
const LIVE_ERROR_NODE_NOT_FOUND := "live_node_not_found"
const LIVE_ERROR_UNKNOWN_PROPERTY := "live_unknown_property"
const LIVE_ERROR_UNCOERCIBLE_VALUE := "live_uncoercible_value"
const LIVE_ERROR_PERF_NODE_NOT_FOUND := "live_perf_node_not_found"
const LIVE_ERROR_PERF_PROPERTY_NOT_FOUND := "live_perf_property_not_found"
const LIVE_ERROR_PERF_SIGNAL_NOT_FOUND := "live_perf_signal_not_found"
const LIVE_ERROR_PERF_TIMEOUT := "live_perf_timeout"

# The frame count a time-windowed op may request before the harness clamps it
# (#223). A window collects one sample per frame, so an unbounded N would block the
# RPC for an unbounded time; this bounds the collection to a generous ceiling.
const MAX_WINDOW_FRAMES := 600

# A window's hard frame budget guard (#223). A window finalizes when it has
# collected its requested frame count, but if the engine stalls (a crash mid-window,
# a frame that never advances) the window must still fail rather than hang the RPC
# forever — the time-windowed analogue of the _pending_frames > 300 boot guard. The
# ceiling is the max requestable frames plus headroom for the few-frame settle.
const WINDOW_FRAME_LIMIT := MAX_WINDOW_FRAMES + 60

var _peer: StreamPeerUDS = null
var _authed := false
var _pending = null
var _pending_frames := 0
# The active time-windowed collection, or null when none is running (#223). A
# multi-frame handler sets this from _run instead of returning a payload; the
# _process loop then advances it one frame per tick until it finalizes. See
# _begin_window / _advance_window.
var _window_state = null


func _ready() -> void:
	_perf_monitors = {
		"fps": Performance.TIME_FPS,
		"process_time": Performance.TIME_PROCESS,
		"physics_process_time": Performance.TIME_PHYSICS_PROCESS,
		"static_memory": Performance.MEMORY_STATIC,
		"static_memory_max": Performance.MEMORY_STATIC_MAX,
		"object_count": Performance.OBJECT_COUNT,
		"node_count": Performance.OBJECT_NODE_COUNT,
		"orphan_node_count": Performance.OBJECT_ORPHAN_NODE_COUNT,
		"resource_count": Performance.OBJECT_RESOURCE_COUNT,
		"draw_calls": Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME,
		"objects_in_frame": Performance.RENDER_TOTAL_OBJECTS_IN_FRAME,
		"primitives_in_frame": Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME,
		"video_memory": Performance.RENDER_VIDEO_MEM_USED,
		"physics_2d_active_objects": Performance.PHYSICS_2D_ACTIVE_OBJECTS,
		"physics_3d_active_objects": Performance.PHYSICS_3D_ACTIVE_OBJECTS,
		"navigation_active_maps": Performance.NAVIGATION_ACTIVE_MAPS,
	}
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
	# A time-windowed op owns the connection until it finalizes (#223): advance it
	# one frame and serve nothing else this tick, so per-frame samples stay
	# frame-coherent (ADR-0020) and the single-writer order is preserved (one op at
	# a time). _advance_window replies once and clears _window_state when done.
	if _window_state != null:
		_advance_window()
		return
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
			# _run returns a finished sentinel payload for a single-frame op (reply
			# now), or null when the handler instead opened a multi-frame window
			# (_window_state is set) — then the loop above drives it to completion.
			var reply: Variant = _run(_pending)
			_pending = null
			if reply != null:
				_send_frame((reply as String).to_utf8_buffer())


func _send_frame(payload: PackedByteArray) -> void:
	_peer.put_u32(payload.size())
	_peer.put_data(payload)


# --- Time-windowed multi-frame base (#223) ------------------------------------
# A multi-frame handler does not return a finished payload from _run; instead it
# calls _begin_window with a per-frame `sample` Callable and a `finalize` Callable,
# returning null so _process keeps ticking. Each subsequent frame, _advance_window
# calls `sample` once (frame-coherent, ADR-0020) and accumulates its return into a
# samples Array; once `frames` samples are collected (or an error sample is
# returned) it calls `finalize(samples)` for the final payload and replies once.
# A hard frame budget (WINDOW_FRAME_LIMIT) fails with live_perf_timeout so a
# stalled/crashed engine cannot hang the RPC forever. #221's capture op reuses
# this same base by adding its own sample/finalize Callables — no _process change.

# Open a window: store its frame budget, sampler, and finalizer, then let
# _process drive it. `frames` is the number of per-frame samples to collect,
# clamped to MAX_WINDOW_FRAMES. Returns null so _run's caller does not reply now.
func _begin_window(frames: int, sample: Callable, finalize: Callable) -> Variant:
	var budget := clampi(frames, 1, MAX_WINDOW_FRAMES)
	_window_state = {
		"budget": budget,
		"elapsed": 0,
		"samples": [],
		"sample": sample,
		"finalize": finalize,
	}
	return null


# Advance the active window one frame. Collects one sample; finalizes once the
# frame budget is met. A sample handler may abort the window early by returning a
# Dictionary carrying an "error" key (e.g. a node that vanished mid-window) — that
# envelope is sent verbatim. The frame ceiling is the time-windowed boot-guard.
func _advance_window() -> void:
	var state: Dictionary = _window_state
	state["elapsed"] = int(state["elapsed"]) + 1
	if int(state["elapsed"]) > WINDOW_FRAME_LIMIT:
		_finish_window(_error(LIVE_ERROR_PERF_TIMEOUT,
				"time-windowed collection did not complete within "
				+ str(WINDOW_FRAME_LIMIT) + " frames"))
		return
	var sampler: Callable = state["sample"]
	var sampled: Variant = sampler.call()
	# A sampler may abort the window by returning a Dictionary with an "error" key
	# (e.g. the monitored node was freed mid-window): send that envelope verbatim.
	if typeof(sampled) == TYPE_DICTIONARY and (sampled as Dictionary).has("error"):
		_finish_window(RESULT_BEGIN + JSON.stringify(sampled) + RESULT_END)
		return
	var samples: Array = state["samples"]
	samples.append(sampled)
	if samples.size() >= int(state["budget"]):
		var finalizer: Callable = state["finalize"]
		_finish_window(finalizer.call(samples))


# Reply once with a window's final payload and clear the window so the loop
# resumes serving the next request.
func _finish_window(payload: String) -> void:
	_window_state = null
	_send_frame(payload.to_utf8_buffer())


# Dispatch one live request to its handler by op name (#220, #223). A request is
# the ADR-0002 {"op", "params"} envelope the daemon relays verbatim. A single-frame
# handler returns a full sentinel-framed payload (success via _ok, failure via
# _error). A multi-frame handler instead opens a window via _begin_window and
# returns null, so _process keeps ticking. Adding an op is one match arm + one
# handler.
func _run(request) -> Variant:
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
		OP_PERF_MONITORS:
			return _handle_perf_monitors()
		OP_PERF_MONITOR:
			return _handle_perf_monitor(params)
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


# --- perf (runtime performance monitoring, #223) ------------------------------

# The performance monitors snapshotted by `perf monitors`, keyed by their public
# name. Each entry pairs the human/wire name with the Godot Performance.Monitor
# enum to sample (#223). Built once at _ready (a plain var, not a const, so the
# initializer is an ordinary runtime expression and never a const-expression
# concern). One source of truth so the snapshot and any docs stay in step; the
# breadth covers timing, memory, object counts, render stats, and the active
# physics/navigation object counts.
var _perf_monitors := {}


# perf monitors: snapshot the running game's performance monitors in one frame —
# the instantaneous counters Godot's Performance singleton exposes (fps, frame
# timing, memory, object/node counts, render stats, active physics/navigation
# objects). Single-frame and frame-coherent (ADR-0020): every value reads on the
# same _process tick. The value's type is the Godot type Performance.get_monitor
# returns (a float), reported so a consumer need not guess.
func _handle_perf_monitors() -> String:
	var monitors := {}
	for name in _perf_monitors:
		var value: float = Performance.get_monitor(_perf_monitors[name])
		monitors[name] = {
			"name": name,
			"type": _type_name(typeof(value)),
			"value": _jsonify(value),
		}
	return _ok({
		"timestamp": Time.get_ticks_msec(),
		"monitors": monitors,
	})


# perf monitor: collect a per-frame timeline over a window (#223) — either a
# property's value each frame (--property) or a signal's emissions over the window
# (--signal). The first time-windowed live op, built on the multi-frame base: it
# resolves and validates up front (a missing node / property / signal fails
# immediately), then opens a window whose sampler runs once per frame. The reply
# is one blocking payload carrying the whole timeline (ADR-0017 one-shot RPC).
func _handle_perf_monitor(params: Dictionary) -> Variant:
	var path := _string_param(params, "node")
	var node := _resolve_runtime_node(path)
	if node == null:
		return _error(LIVE_ERROR_PERF_NODE_NOT_FOUND,
				"no node at runtime path: " + path)

	var frames := _int_param(params, "frames", 1)
	var prop_name := _string_param(params, "property")
	var signal_name := _string_param(params, "signal")

	if params.has("signal") and not signal_name.is_empty():
		return _begin_signal_monitor(node, path, signal_name, frames)
	if params.has("property") and not prop_name.is_empty():
		return _begin_property_monitor(node, path, prop_name, frames)
	# Neither selector given: a property monitor with an empty property is an
	# unknown property, the clearest of the two for a malformed request.
	return _error(LIVE_ERROR_PERF_PROPERTY_NOT_FOUND,
			"node " + path + " perf monitor needs a --property or --signal")


# Open a property timeline window: validate the property is readable, then sample
# its jsonified value each frame. The sampler re-resolves nothing — the node is
# captured — but a node freed mid-window yields a typed error sample that aborts
# the window cleanly.
func _begin_property_monitor(node: Node, path: String, prop_name: String, frames: int) -> Variant:
	if _property_type(node, prop_name) == TYPE_NIL:
		return _error(LIVE_ERROR_PERF_PROPERTY_NOT_FOUND,
				"node " + path + " has no readable property: " + prop_name)
	var node_ref: WeakRef = weakref(node)
	var frame_box := {"n": 0}
	var sample := func() -> Variant:
		var live: Node = node_ref.get_ref()
		if live == null:
			return {"error": {
				"code": LIVE_ERROR_PERF_NODE_NOT_FOUND,
				"message": "node " + path + " was freed during monitoring",
			}}
		var entry := {
			"frame": int(frame_box["n"]),
			"timestamp": Time.get_ticks_msec(),
			"value": _jsonify(live.get(prop_name)),
		}
		frame_box["n"] = int(frame_box["n"]) + 1
		return entry
	var finalize := func(samples: Array) -> String:
		return _ok({
			"node": path,
			"kind": "property",
			"property": prop_name,
			"frames": samples.size(),
			"samples": samples,
		})
	return _begin_window(frames, sample, finalize)


# Open a signal timeline window: validate the signal exists, connect a recorder
# that appends each emission ({frame, args, timestamp}), and sample the current
# frame index each frame. On finalize, disconnect and return the recorded
# emissions. The per-frame sample drives the window's clock; the recorder runs on
# the signal's own emission, so an emission is tagged with the frame it landed in.
func _begin_signal_monitor(node: Node, path: String, signal_name: String, frames: int) -> Variant:
	var arg_count := _signal_arg_count(node, signal_name)
	if arg_count < 0:
		return _error(LIVE_ERROR_PERF_SIGNAL_NOT_FOUND,
				"node " + path + " has no signal: " + signal_name)
	var emissions: Array = []
	var frame_box := {"n": 0}
	# A signal carries a fixed declared arg count; a recorder Callable connected to
	# a signal must accept at least that many positional args. A max-arity recorder
	# (4 defaulted params) accepts any signal up to 4 args, and the declared count
	# (captured above) tells it exactly how many of its params are real emission
	# args — so a legitimate null arg within the declared arity is preserved and a
	# trailing default is never mistaken for one.
	var recorder := func(arg0 = null, arg1 = null, arg2 = null, arg3 = null) -> void:
		var all_args := [arg0, arg1, arg2, arg3]
		var args: Array = []
		for i in mini(arg_count, all_args.size()):
			args.append(_jsonify(all_args[i]))
		emissions.append({
			"frame": int(frame_box["n"]),
			"timestamp": Time.get_ticks_msec(),
			"args": args,
		})
	node.connect(signal_name, recorder)
	var node_ref: WeakRef = weakref(node)
	var sample := func() -> Variant:
		frame_box["n"] = int(frame_box["n"]) + 1
		return null
	var finalize := func(_samples: Array) -> String:
		var live: Node = node_ref.get_ref()
		if live != null and live.is_connected(signal_name, recorder):
			live.disconnect(signal_name, recorder)
		return _ok({
			"node": path,
			"kind": "signal",
			"signal": signal_name,
			"frames": frames,
			"emissions": emissions,
		})
	return _begin_window(frames, sample, finalize)


# The declared positional argument count of `node`'s signal by this name, or -1
# when the node declares no such signal — read from get_signal_list (the runtime
# signal surface, including script-declared signals). Validating off the signal
# list, not a try/connect (which only fails at emit time), and the arg count
# bounds how many emission args the recorder records.
func _signal_arg_count(node: Node, signal_name: String) -> int:
	for sig in node.get_signal_list():
		if String(sig.get("name", "")) == signal_name:
			var args: Variant = sig.get("args", [])
			return (args as Array).size() if typeof(args) == TYPE_ARRAY else 0
	return -1


# Read an int param defensively (the params arrive as arbitrary JSON): a missing or
# non-numeric value falls back to `fallback` rather than crashing a typed
# assignment, so a malformed param degrades gracefully.
func _int_param(params: Dictionary, key: String, fallback: int) -> int:
	var value: Variant = params.get(key, fallback)
	if typeof(value) == TYPE_FLOAT or typeof(value) == TYPE_INT:
		return int(value)
	return fallback


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

