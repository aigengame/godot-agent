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

# The active opt-in log marker (#282, ADR-0026 decision 2). `gda_log()` emits one
# `<<<GDA:LOG>>>{json}` line into the Session log (the daemon's --log-file); the
# Python parser (gda.daemon.diag.LOG_BEGIN) recognises the prefix and decodes the
# JSON into a field-carrying LogRecord. A SEPARATE marker family from RESULT_BEGIN
# above, so a log line is never mistaken for an op result. Mirrored in Python
# (gda.daemon.diag.LOG_BEGIN); a const test (tests/test_error_registry.py) keeps
# the two byte-identical.
const LOG_MARKER := "<<<GDA:LOG>>>"

# The live operations this harness serves, keyed by their wire op name (#220, #223).
const OP_GAME_TREE := "game-tree"
const OP_GAME_GET := "game-get"
const OP_GAME_RECT := "game-rect"
const OP_GAME_SET := "game-set"
const OP_GAME_CALL := "game-call"
const OP_PERF_MONITORS := "perf-monitors"
const OP_PERF_MONITOR := "perf-monitor"
const OP_PERF_SAMPLE := "perf-sample"
const OP_INPUT_KEY := "input-key"
const OP_INPUT_MOUSE_CLICK := "input-mouse-click"
const OP_INPUT_MOUSE_MOVE := "input-mouse-move"
const OP_INPUT_ACTION := "input-action"
const OP_INPUT_TAP := "input-tap"
const OP_INPUT_SEQUENCE := "input-sequence"
const OP_SCREEN_CAPTURE := "screen-capture"
const OP_SCREEN_FRAMES := "screen-frames"

# The per-op LIVE failure codes the harness reports in-band (#220, #223). Each MUST
# be a registered LIVE-category code (src/gda/error_codes.py) so the daemon's exit-0
# relay is mapped by classify_live, not misrouted to contract_violation; a Python
# mirror test (tests/test_error_registry.py) keeps these in sync with the registry.
const LIVE_ERROR_NODE_NOT_FOUND := "live_node_not_found"
const LIVE_ERROR_NOT_CONTROL := "live_not_control"
const LIVE_ERROR_UNKNOWN_PROPERTY := "live_unknown_property"
const LIVE_ERROR_UNCOERCIBLE_VALUE := "live_uncoercible_value"
const LIVE_ERROR_PERF_NODE_NOT_FOUND := "live_perf_node_not_found"
const LIVE_ERROR_PERF_PROPERTY_NOT_FOUND := "live_perf_property_not_found"
const LIVE_ERROR_PERF_SIGNAL_NOT_FOUND := "live_perf_signal_not_found"
const LIVE_ERROR_INVALID_KEY := "live_invalid_key"
const LIVE_ERROR_UNKNOWN_ACTION := "live_unknown_action"
const LIVE_ERROR_INVALID_EVENT_SPEC := "live_invalid_event_spec"
const LIVE_ERROR_DISPLAY_UNAVAILABLE := "live_display_unavailable"
const LIVE_ERROR_PREDICATE_UNMET := "live_predicate_unmet"
const LIVE_ERROR_UNKNOWN_METHOD := "live_unknown_method"
const LIVE_ERROR_METHOD_NOT_ALLOWLISTED := "live_method_not_allowlisted"
const LIVE_ERROR_INVALID_CALL_ARGS := "live_invalid_call_args"

# The script constant a project class declares its gda-callable methods in
# (#673): `const GDA_CALLABLE := ["method_name"]`. Read STATICALLY from the
# script's constant map, so learning what may be called never runs project code.
const GDA_CALLABLE_CONST := "GDA_CALLABLE"

# The frame count a time-windowed op may request (#223). A window collects one
# sample per frame, so an unbounded N would block the one-shot RPC for an unbounded
# time; this bounds the collection to a generous ceiling. The bound is ENFORCED
# model-side (PerfMonitorParams.frames, ADR-0015), so an over-range request is
# rejected before it reaches the harness — the harness no longer clamps. Mirrored
# in src/gda/models.py (MAX_WINDOW_FRAMES); a test keeps the two in sync.
const MAX_WINDOW_FRAMES := 600
const WINDOW_CLOCK_PROCESS := "process"
const WINDOW_CLOCK_PHYSICS := "physics"

var _peer: StreamPeerUDS = null
var _authed := false
# True once this run was launched by gda-daemon (the LAUNCH_MARKER is present in the
# user args), independent of whether the IPC connection then succeeded. Gates the
# opt-in `gda_log()` so the harness stays inert — no `<<<GDA:LOG>>>` output — in a
# human editor run, a plain run, and a shipped build (CONTEXT.md, ADR-0018).
var _daemon_launched := false
# The scene selector the daemon requested (`gda daemon start --scene`, #278), or ""
# for none. The harness verifies the ACTUALLY-loaded scene against it ONCE at launch
# and sends the result as the second handshake frame; _scene_verified gates serving
# ops until that frame is sent (so a mismatch is caught before any op runs).
var _requested_scene := ""
# The daemon-minted Engine-session identity (#660), or "" when the launcher
# predates it. Fixed for this run's lifetime; stamped into every capture
# receipt so the image correlates with `gda daemon status`'s session_id.
var _session_id := ""
# The LAUNCHED scene's identity (#660): the path the session verified at the
# handshake and that scene file's own header uid, read once at verification —
# the receipt reports the session's launch fact, per issue #660, not the scene
# a later frame happens to present.
var _launched_scene_path := ""
var _launched_scene_uid: Variant = null
var _scene_verified := false
var _verify_frames := 0
var _pending = null
var _pending_frames := 0
# The active time-windowed collection, or null when none is running (#223). A
# multi-frame handler sets this from _run instead of returning a payload; the
# _process or _physics_process loop then advances it one frame per selected clock
# tick until it finalizes. See _begin_window / _advance_window.
var _window_state = null


func _ready() -> void:
	# Defence in depth (ADR-0028): stay fully inert in any EXPORTED build, even if a
	# build somehow shipped with the harness installed (e.g. exported outside `gda
	# export run`, which strips it). `template` is true ONLY in an exported template
	# build and false on the editor (tools) binary every gda-daemon session runs on —
	# so this never disables a legitimate session, and a shipped build does literally
	# nothing here regardless of the launch args below.
	if OS.has_feature("template"):
		return
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
	# Launched by the daemon (with a daemon-owned --log-file): the opt-in gda_log()
	# protocol is now active. Set before the connect attempt — the log file is
	# daemon-owned regardless of whether the live-op IPC connection then succeeds.
	_daemon_launched = true
	# Keep serving live operations while the game's SceneTree is paused (#656).
	# A real pause menu sets SceneTree.paused = true; the harness's default
	# process mode (PROCESS_MODE_INHERIT, effectively pausable at the top of the
	# tree) would then stop THIS node's own _process from ticking too — freezing
	# the one loop that serves the socket at exactly the state an agent needs to
	# inspect, and with no way back in: resuming the game needs an input op, and
	# input injection is itself served from this same loop. PROCESS_MODE_ALWAYS
	# keeps the harness ticking through a pause, independent of the game's own
	# process-mode tree — mirroring how a real pause-menu script must set its own
	# process mode to keep handling "resume" input while paused. Scoped inside
	# this daemon-launched gate (the same condition gda_log() checks), so a human
	# editor run, a plain run, and a shipped build never have their process mode
	# touched — the ADR-0018 inertness guarantee is unaffected.
	process_mode = Node.PROCESS_MODE_ALWAYS
	# Mirror the root viewport's mouse-entered state (#647). The engine keeps it
	# private (Viewport.gui.mouse_in_viewport has no getter), but the root Window
	# emits mouse_entered/mouse_exited on the SAME notifications that flip it —
	# for an OS-driven enter in a windowed session and for the harness's own
	# notify_mouse_entered() alike — so these two connections track it faithfully.
	# _prepare_mouse_input consults the mirror to notify only on a real edge;
	# re-notifying an already-entered viewport is an engine warning that pollutes
	# `gda diag errors` with harness-owned noise. Scoped inside the daemon-launched
	# gate: a human editor run and a plain run get no connections (ADR-0018).
	get_tree().root.mouse_entered.connect(func() -> void: _mouse_in_viewport = true)
	get_tree().root.mouse_exited.connect(func() -> void: _mouse_in_viewport = false)
	var socket_path: String = user_args[idx + 1]
	var token: String = user_args[idx + 2]
	# The requested scene selector (#278) follows the token; "" (or absent) = none.
	if idx + 3 < user_args.size():
		_requested_scene = user_args[idx + 3]
	# The daemon-minted session identity (#660) follows the selector; "" (or
	# absent, from a launcher that predates it) = none.
	if idx + 4 < user_args.size():
		_session_id = user_args[idx + 4]

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
	# Launch-time scene verification (#278): before serving ANY op, send the second
	# handshake frame reporting whether the scene the session ACTUALLY loaded matches
	# the requested `--scene` selector. current_scene is null at autoload _ready (the
	# main scene loads after autoloads), so wait for it on a frame boundary — the same
	# wait the op loop uses — with a bounded fallback so a sceneless project never
	# hangs the handshake. Verified ONCE, never re-checked per op.
	if not _scene_verified:
		_verify_frames += 1
		if get_tree().current_scene != null or _verify_frames > 300:
			_send_scene_verification()
			_scene_verified = true
		return
	# A time-windowed op owns the connection until it finalizes (#223): process-clock
	# windows advance here, physics-clock windows advance in _physics_process. Either
	# way, serve nothing else this tick so the single-writer order is preserved (one
	# op at a time). _advance_window replies once and clears _window_state when done.
	if _window_state != null:
		if _window_clock() == WINDOW_CLOCK_PROCESS:
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


func _physics_process(_delta: float) -> void:
	if _window_state == null:
		return
	if _window_clock() != WINDOW_CLOCK_PHYSICS:
		return
	_advance_window()


func _send_frame(payload: PackedByteArray) -> void:
	_peer.put_u32(payload.size())
	_peer.put_data(payload)


# Send the launch-time scene-verification frame (#278): the JSON
# {"scene_ok": bool, "current": "res://…"} the daemon reads after the token. With no
# selector requested (_requested_scene == ""), scene_ok is trivially true (the
# main_scene default is unchanged). Otherwise scene_ok is whether the ACTUALLY-loaded
# scene matches the requested selector — the no-silent-fallback guarantee, including
# a bad uid:// that Godot replaced with main_scene.
func _send_scene_verification() -> void:
	var current: Node = get_tree().current_scene
	var current_path := String(current.scene_file_path) if current != null else ""
	var ok := true
	if not _requested_scene.is_empty():
		ok = _scene_matches(_requested_scene, current_path)
	# Remember the LAUNCHED scene's identity for capture receipts (#660, PR #746
	# review): the receipt's scene fields are the session's launch fact per the
	# issue, not a per-frame claim — so they are read ONCE here, at the same
	# moment the daemon verifies the scene, never re-derived at capture time.
	_launched_scene_path = current_path
	_launched_scene_uid = _scene_header_uid(current_path)
	var frame := {"scene_ok": ok, "current": current_path}
	_send_frame(JSON.stringify(frame).to_utf8_buffer())


# Whether the loaded scene path matches the requested selector (#278). A `res://…`
# (or filesystem) selector compares directly to the loaded scene_file_path. A
# `uid://…` selector is resolved to its res:// path via ResourceUID and compared; a
# uid the project does not know resolves to nothing, so it never matches — which is
# exactly how a bad uid (that Godot silently replaced with main_scene) is caught.
func _scene_matches(requested: String, current_path: String) -> bool:
	if current_path.is_empty():
		return false
	if requested.begins_with("uid://"):
		var id := ResourceUID.text_to_id(requested)
		if id == -1 or not ResourceUID.has_id(id):
			return false
		return ResourceUID.get_id_path(id) == current_path
	return requested == current_path


# --- Time-windowed multi-frame base (#223) ------------------------------------
# A multi-frame handler does not return a finished payload from _run; instead it
# calls _begin_window with a per-frame `sample` Callable and a `finalize` Callable,
# returning null so _process or _physics_process keeps ticking on the selected
# clock. Each subsequent selected-clock frame, _advance_window calls `sample` once
# (frame-coherent, ADR-0020) and accumulates its return into a samples Array; once
# `frames` samples are collected (or an error sample is returned) it calls
# `finalize(samples)` for the final payload and replies once. A truly stalled
# engine never runs _advance_window at all, so the window has no timeout of its own
# — the daemon-level `live_timeout` is the stalled-engine guard. #221's capture op
# reuses this same base by adding its own sample/finalize Callables — no _process
# change.

# Open a window: store its frame budget, sampler, finalizer, and selected clock,
# then let _process or _physics_process drive it. `frames` is the number of
# per-frame samples to collect; it is already bounded to 1..MAX_WINDOW_FRAMES
# model-side (PerfMonitorParams / InputSequenceParams, ADR-0015), so the harness
# does not clamp. Returns null so _run's caller does not reply now.
func _begin_window(
		frames: int,
		sample: Callable,
		finalize: Callable,
		clock: String = WINDOW_CLOCK_PROCESS) -> Variant:
	_window_state = {
		"budget": frames,
		"clock": clock,
		"samples": [],
		"sample": sample,
		"finalize": finalize,
	}
	return null


func _window_clock() -> String:
	if _window_state == null:
		return WINDOW_CLOCK_PROCESS
	var state: Dictionary = _window_state
	return String(state.get("clock", WINDOW_CLOCK_PROCESS))


# Advance the active window one frame. Collects one sample; finalizes once the
# frame budget is met. A sample handler may end the window early two ways: a
# Dictionary carrying an "error" key aborts with that envelope verbatim (e.g. a
# node that vanished mid-window), and a Dictionary carrying a "complete" key
# finishes successfully with _ok of that payload (e.g. a predicate capture that
# just held, #661) — the budget is the CEILING, not the required duration.
func _advance_window() -> void:
	var state: Dictionary = _window_state
	var sampler: Callable = state["sample"]
	var sampled: Variant = sampler.call()
	# A sampler may abort the window by returning a Dictionary with an "error" key
	# (e.g. the monitored node was freed mid-window): send that envelope verbatim.
	if typeof(sampled) == TYPE_DICTIONARY and (sampled as Dictionary).has("error"):
		_finish_window(RESULT_BEGIN + JSON.stringify(sampled) + RESULT_END)
		return
	# ...or complete it early with a success payload (#661 predicate capture).
	if typeof(sampled) == TYPE_DICTIONARY and (sampled as Dictionary).has("complete"):
		_finish_window(_ok((sampled as Dictionary)["complete"]))
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
		OP_GAME_RECT:
			return _handle_game_rect(params)
		OP_GAME_SET:
			return _handle_game_set(params)
		OP_GAME_CALL:
			return _handle_game_call(params)
		OP_PERF_MONITORS:
			return _handle_perf_monitors()
		OP_PERF_MONITOR:
			return _handle_perf_monitor(params)
		OP_PERF_SAMPLE:
			return _handle_perf_sample(params)
		OP_INPUT_KEY:
			return _handle_input_key(params)
		OP_INPUT_MOUSE_CLICK:
			return _handle_input_mouse_click(params)
		OP_INPUT_MOUSE_MOVE:
			return _handle_input_mouse_move(params)
		OP_INPUT_ACTION:
			return _handle_input_action(params)
		OP_INPUT_TAP:
			return _handle_input_tap(params)
		OP_INPUT_SEQUENCE:
			return _handle_input_sequence(params)
		OP_SCREEN_CAPTURE:
			return _handle_screen_capture(params)
		OP_SCREEN_FRAMES:
			return _handle_screen_frames(params)
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

	# The texture-digest opt-in (#666): threaded into the shared projection so
	# a path-less Texture2D value carries its content digest on request.
	var texture_digest := bool(params.get("texture_digest", false))
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
			"value": _jsonify(node.get(prop_name), 0, texture_digest),
		})
	if has_filter and properties.is_empty():
		var script_property := _explicit_script_variable_property(
				node, wanted, texture_digest)
		if not script_property.is_empty():
			properties.append(script_property)
	if has_filter and properties.is_empty():
		return _error(LIVE_ERROR_UNKNOWN_PROPERTY,
				_unknown_runtime_property_message(path, wanted))

	return _ok({
		"path": path,
		"name": String(node.name),
		"type": node.get_class(),
		"properties": properties,
	})


func _explicit_script_variable_property(
		node: Node, prop_name: String, texture_digest: bool = false) -> Dictionary:
	for prop in node.get_property_list():
		if String(prop.get("name", "")) != prop_name:
			continue
		if not _is_script_variable(prop):
			continue
		var value: Variant = node.get(prop_name)
		var declared_type := int(prop.get("type", TYPE_NIL))
		if declared_type == TYPE_NIL:
			declared_type = typeof(value)
		return {
			"name": prop_name,
			"type": _type_name(declared_type),
			"value": _jsonify(value, 0, texture_digest),
		}
	return {}


# game rect: resolve a node by its ABSOLUTE runtime path, require it to be a
# Control, and report its rendered viewport-space rect. This reads layout output
# via Control.get_global_rect(), not a storage property surface.
func _handle_game_rect(params: Dictionary) -> String:
	var path := _string_param(params, "node")
	var node := _resolve_runtime_node(path)
	if node == null:
		return _error(LIVE_ERROR_NODE_NOT_FOUND,
				"no node at runtime path: " + path)
	if not (node is Control):
		return _error(LIVE_ERROR_NOT_CONTROL,
				"node at runtime path is not a Control: " + path)

	var control: Control = node as Control
	var rect := control.get_global_rect()
	return _ok({
		"path": path,
		"name": String(control.name),
		"type": control.get_class(),
		"position": _jsonify(rect.position),
		"size": _jsonify(rect.size),
	})


# game set: resolve a node by its ABSOLUTE runtime path, coerce the CLI string
# value to the property's declared Godot type, and set it on the live node — the
# runtime counterpart of headless node set, using the SAME coercion table. The
# write runs synchronously on the main thread at the _process frame boundary
# (frame-coherent, ADR-0020); no extra threading. The coerced value is read back
# and echoed in the same JSON projection game get reports. A completed live set
# returns whether that observed read-back value matches the coerced requested
# value; the harness does not guess whether a mismatch is a no-op or an
# edge-triggered/self-consuming variable.
# game call: invoke ONE method the addressed node's class DECLARED as callable,
# and project its return value (#673, GDA-DF-033). The dogfooding gap: a debug
# state contract exposed as a method was unreadable — `game get` reads stored
# properties only — so evidence fell back to index properties plus screenshots.
#
# The declaration site is the class's own script constant `GDA_CALLABLE` (an
# Array of method names), merged across the script's base chain, so the
# read-only assertion sits beside the code it describes and is reviewed with it
# (ADR-0041). It is read STATICALLY from the script constant map: learning what
# may be called runs no project code, so the bootstrap itself cannot have side
# effects. A node with no script, no constant, or a constant that does not name
# the method declares nothing — default deny.
#
# gda cannot verify that a declared method has no side effects; the allowlist
# records the DECLARER's assertion. What gda guarantees is that no UNDECLARED
# method is callable. Failures are distinguishable: a method the node does not
# have is live_unknown_method (checked first — the project is trusted, ADR-0009,
# so the more precise diagnosis is the useful one), a method it has but never
# declared is live_method_not_allowlisted (whose message names the declared set),
# and an argument count outside the method's accepted range is
# live_invalid_call_args — refused BEFORE the call, since callv would otherwise
# push an engine error and return a null gda would report as a successful read.
func _handle_game_call(params: Dictionary) -> String:
	var path := _string_param(params, "node")
	var node := _resolve_runtime_node(path)
	if node == null:
		return _error(LIVE_ERROR_NODE_NOT_FOUND,
				"no node at runtime path: " + path)
	var method := _string_param(params, "method")
	if not node.has_method(method):
		return _error(LIVE_ERROR_UNKNOWN_METHOD,
				"the node at " + path + " has no method named " + method)
	var declared := _declared_callables(node)
	if not declared.has(method):
		var names := ", ".join(declared) if not declared.is_empty() else "(none)"
		return _error(LIVE_ERROR_METHOD_NOT_ALLOWLISTED,
				"the method " + method + " is not declared callable by the node at "
				+ path + "; its class declares: " + names
				+ ". Declare it in the script constant `const "
				+ GDA_CALLABLE_CONST + " := [\"" + method + "\"]` to allow it")
	var raw_args: Variant = params.get("args", [])
	var args: Array = raw_args if typeof(raw_args) == TYPE_ARRAY else []
	var arity := _call_arity_error(node, method, args.size())
	if not arity.is_empty():
		return _error(LIVE_ERROR_INVALID_CALL_ARGS, arity)
	return _ok({
		"path": path,
		"name": String(node.name),
		"type": node.get_class(),
		"method": method,
		"value": _jsonify(node.callv(method, args)),
	})


# The method names a node's class declared gda-callable (#673), merged along the
# script's base chain so a base class's declaration covers its subclasses the way
# any other class member would. Read from the constant map — never by calling
# into the project — and normalized to Strings, so a malformed declaration (a
# non-Array constant, or entries that are not names) declares nothing rather
# than failing the call with an unrelated error.
func _declared_callables(node: Node) -> Array:
	var names: Array = []
	var script: Script = node.get_script() as Script
	while script != null:
		var constants: Dictionary = script.get_script_constant_map()
		var declared: Variant = constants.get(GDA_CALLABLE_CONST, null)
		if typeof(declared) == TYPE_ARRAY or typeof(declared) == TYPE_PACKED_STRING_ARRAY:
			for entry in declared:
				if typeof(entry) != TYPE_STRING and typeof(entry) != TYPE_STRING_NAME:
					continue
				var entry_name := String(entry)
				if not names.has(entry_name):
					names.append(entry_name)
		script = script.get_base_script()
	return names


# Why the supplied argument count cannot reach `method`, or "" when it can
# (#673). Required = declared args minus defaults; a vararg method has no upper
# bound. A method the list does not describe is not second-guessed here — the
# has_method gate above already established it exists.
func _call_arity_error(node: Node, method: String, supplied: int) -> String:
	for entry in node.get_method_list():
		if String(entry.get("name", "")) != method:
			continue
		var declared_args: Array = entry.get("args", [])
		var defaults: Array = entry.get("default_args", [])
		var required := declared_args.size() - defaults.size()
		var vararg := (int(entry.get("flags", 0)) & METHOD_FLAG_VARARG) != 0
		if supplied < required:
			return ("the method " + method + " needs at least " + str(required)
					+ " argument(s); " + str(supplied) + " supplied")
		if not vararg and supplied > declared_args.size():
			return ("the method " + method + " accepts at most "
					+ str(declared_args.size()) + " argument(s); " + str(supplied)
					+ " supplied")
		return ""
	return ""


func _handle_game_set(params: Dictionary) -> String:
	var path := _string_param(params, "node")
	var node := _resolve_runtime_node(path)
	if node == null:
		return _error(LIVE_ERROR_NODE_NOT_FOUND,
				"no node at runtime path: " + path)

	var prop_name := _string_param(params, "property")
	if _is_control_position_write(node, prop_name):
		var control: Control = node as Control
		if _has_container_parent(control):
			return _error(LIVE_ERROR_UNKNOWN_PROPERTY,
					_control_position_unavailable_message("node " + path))
		var raw_position := _string_param(params, "value")
		var coerced_position: Variant = _coerce_value(raw_position,
				TYPE_VECTOR2, control.position)
		if coerced_position == null:
			return _error(LIVE_ERROR_UNCOERCIBLE_VALUE,
					"cannot coerce value " + raw_position.c_escape()
					+ " to Vector2 for property position on node " + path)
		var target_position: Vector2 = coerced_position
		control.set_position(target_position)
		var current_position: Variant = _jsonify(control.position)
		return _ok({
			"path": path,
			"property": prop_name,
			"type": _type_name(TYPE_VECTOR2),
			"value": current_position,
			"verified": control.position == target_position,
		})

	var prop_info := _runtime_set_property_info(node, prop_name)
	if prop_info.is_empty():
		return _error(LIVE_ERROR_UNKNOWN_PROPERTY,
				_unknown_runtime_property_message(path, prop_name))
	var declared_type := int(prop_info.get("type", TYPE_NIL))
	var source := String(prop_info.get("source", "property"))

	var raw_value := _string_param(params, "value")
	var before: Variant = node.get(prop_name)
	var coerced: Variant = _coerce_value(raw_value, declared_type, before)
	if coerced == null:
		var subject := "script variable " + prop_name \
				if source == "script variable" else "property " + prop_name
		return _error(LIVE_ERROR_UNCOERCIBLE_VALUE,
				"cannot coerce value " + raw_value.c_escape()
				+ " to " + _type_name(declared_type) + " for " + subject
				+ " on node " + path)

	node.set(prop_name, coerced)
	var current: Variant = node.get(prop_name)
	return _ok({
		"path": path,
		"property": prop_name,
		"type": _type_name(declared_type),
		"value": _jsonify(current),
		"verified": current == coerced,
	})


func _runtime_set_property_info(node: Node, prop_name: String) -> Dictionary:
	var storage_type := _property_type(node, prop_name)
	if storage_type != TYPE_NIL:
		return {"type": storage_type, "source": "property"}
	for prop in node.get_property_list():
		if String(prop.get("name", "")) != prop_name:
			continue
		var usage := int(prop.get("usage", 0))
		if (usage & PROPERTY_USAGE_SCRIPT_VARIABLE) == 0:
			continue
		var declared_type := int(prop.get("type", TYPE_NIL))
		if declared_type == TYPE_NIL:
			declared_type = typeof(node.get(prop_name))
		return {"type": declared_type, "source": "script variable"}
	return {}


func _is_control_position_write(node: Node, prop_name: String) -> bool:
	return prop_name == "position" and node is Control


func _has_container_parent(control: Control) -> bool:
	return control.get_parent() is Container


func _control_position_unavailable_message(subject: String) -> String:
	return subject + " is a direct child of a Container, so Control.position is not an actionable settable property; address offset_left, offset_top, offset_right, and offset_bottom instead"


func _unknown_runtime_property_message(path: String, prop_name: String) -> String:
	return "node " + path + " has no runtime, storage, or script property: " + prop_name


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


# perf sample: collect the ENGINE performance monitors per frame over a bounded
# window (#662) — the windowed counterpart of the one-frame `perf monitors`
# snapshot, on the same time-windowed base `perf monitor` uses (#223). Each
# selected-clock frame the sampler reads every SELECTED monitor (all of them
# when the selection is empty), frame-coherently (ADR-0020), and the reply
# carries the raw timestamped samples. The harness stays dumb on purpose: the
# aggregate statistics and any budget verdicts are computed CLI-side, where the
# numeric semantics are unit-testable without an engine. The frame count is
# bounded model-side (ADR-0015); the unknown-monitor arm below is defensive
# only (the CLI validates names against its mirrored table before dispatch).
func _handle_perf_sample(params: Dictionary) -> Variant:
	var frames := _int_param(params, "frames", 60)
	var raw_names: Variant = params.get("monitors", [])
	var names: Array = raw_names if typeof(raw_names) == TYPE_ARRAY else []
	if names.is_empty():
		names = _perf_monitors.keys()
	for name in names:
		if not _perf_monitors.has(String(name)):
			return _error("operation_failed",
					"unknown performance monitor: " + String(name))
	var frame_box := {"n": 0}
	var sample := func() -> Variant:
		var values := {}
		for name in names:
			values[String(name)] = Performance.get_monitor(_perf_monitors[String(name)])
		var entry := {
			"frame": int(frame_box["n"]),
			"timestamp": Time.get_ticks_msec(),
			"values": values,
		}
		frame_box["n"] = int(frame_box["n"]) + 1
		return entry
	var finalize := func(samples: Array) -> String:
		return _ok({
			"kind": "sample",
			"frames": samples.size(),
			"monitors": names,
			"samples": samples,
		})
	return _begin_window(frames, sample, finalize)


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
	var finalize := func(samples: Array) -> String:
		var live: Node = node_ref.get_ref()
		if live != null and live.is_connected(signal_name, recorder):
			live.disconnect(signal_name, recorder)
		# Report the ACTUAL window length (one per-frame sample was accumulated each
		# tick), consistent with the property finalizer's samples.size() — not the
		# originally-requested `frames`.
		return _ok({
			"node": path,
			"kind": "signal",
			"signal": signal_name,
			"frames": samples.size(),
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


# --- input (runtime input simulation, #221) -----------------------------------
#
# Inject input into the RUNNING game on the main thread at a frame boundary
# (ADR-0020). Key/mouse events ride the game's real input flow via the root
# viewport's push_input (scene-aware); actions go through Input.action_press/
# release against the running InputMap. The model bounds every request up front
# (ADR-0015), so the harness only decides what needs the live engine: a key name
# the engine cannot resolve (live_invalid_key) and an action the running InputMap
# does not declare (live_unknown_action). `input sequence` reuses the time-windowed
# multi-frame base (#223): each selected-clock frame, the sampler applies the events
# due at that index, and finalize returns the applied-events summary. Existing
# `frame` offsets use the harness/process clock; #391's `physics_frame` offsets use
# Godot's fixed physics clock.


# The root Viewport push_input targets, the same surface real OS input flows
# through, so an injected event is dispatched to the game exactly as a genuine one
# would be (scene-aware). One source of truth for every key/mouse injection.
func _input_viewport() -> Viewport:
	return get_tree().root


var _last_injected_mouse_position: Variant = null
var _injected_mouse_button_mask := 0
# Whether the root viewport currently believes the mouse is in its area, mirrored
# from the root Window's mouse_entered/mouse_exited signals (connected at _ready,
# #647). Starts false: a fresh engine session has received no enter notification.
var _mouse_in_viewport := false


func _prepare_mouse_input() -> Viewport:
	var viewport := _input_viewport()
	# Notify only on a real edge (#647): notify_mouse_entered() on an
	# already-entered viewport is an engine warning ("The Viewport was previously
	# notified...") that lands in the Session log and pollutes `gda diag errors`
	# on every injected mouse event after the first. The mirror also covers an
	# OS-driven enter in a windowed session (no notify needed at all) and an
	# OS-driven exit (the next injection re-notifies).
	if not _mouse_in_viewport:
		viewport.notify_mouse_entered()
	return viewport


# Resolve a key name to a Godot keycode via the engine's own name table. Returns
# KEY_NONE (0) for a name the engine does not recognize — the one runtime failure
# the model cannot pre-validate (the keycode table is the engine's), surfaced as
# live_invalid_key.
func _resolve_keycode(key: String) -> int:
	return OS.find_keycode_from_string(key)


# Build an InputEventKey for a resolved keycode, applying the modifier flags from
# the request. The modifier set is already bounded model-side, so an unknown
# modifier never reaches here; the loop maps each known name to its flag.
func _make_key_event(keycode: int, modifiers: Array, pressed: bool) -> InputEventKey:
	var event := InputEventKey.new()
	event.keycode = keycode
	event.physical_keycode = keycode
	event.pressed = pressed
	for modifier in modifiers:
		match String(modifier):
			"shift":
				event.shift_pressed = true
			"ctrl":
				event.ctrl_pressed = true
			"alt":
				event.alt_pressed = true
			"meta":
				event.meta_pressed = true
	return event


# The Godot MOUSE_BUTTON_* index for a CLI button name. The model bounds the name
# to the known enum, so the fallthrough is only reached by a request that bypassed
# the model; it degrades to the left button rather than crashing.
func _mouse_button_index(button: String) -> int:
	match button:
		"right":
			return MOUSE_BUTTON_RIGHT
		"middle":
			return MOUSE_BUTTON_MIDDLE
		_:
			return MOUSE_BUTTON_LEFT


func _mouse_button_mask(button: String) -> int:
	match button:
		"right":
			return MOUSE_BUTTON_MASK_RIGHT
		"middle":
			return MOUSE_BUTTON_MASK_MIDDLE
		_:
			return MOUSE_BUTTON_MASK_LEFT


# Push a WHOLE mouse click — the press, then the release — on one frame. A bare
# press never completes an activation: a default Button emits `pressed` only on
# the release, so a "click" that stops at the press leaves the button held down
# forever (#652, GDA-DF-004). Used by a sequence `mouse_click` event, which puts
# the whole click at one clock offset (a same-frame pair fully activates a
# Button, verified against a live engine); the standalone `input mouse-click` op
# spreads its move/press/release gesture across frames instead (see
# _handle_input_mouse_click).
func _push_whole_mouse_click(pos: Vector2, button: String, double: bool) -> void:
	_push_mouse_button_phase(pos, button, true, double)
	_push_mouse_button_phase(pos, button, false, false)


func _push_mouse_button_phase(pos: Vector2, button: String, pressed: bool, double: bool) -> void:
	var viewport := _prepare_mouse_input()
	var mask := _mouse_button_mask(button)
	if pressed:
		_injected_mouse_button_mask = _injected_mouse_button_mask | mask
	else:
		_injected_mouse_button_mask = _injected_mouse_button_mask & ~mask
	var event := InputEventMouseButton.new()
	event.button_index = _mouse_button_index(button)
	event.button_mask = _injected_mouse_button_mask
	event.position = pos
	event.pressed = pressed
	event.double_click = double
	viewport.push_input(event, true)
	_last_injected_mouse_position = pos


# Push a mouse-motion event to a viewport position. Shared by the single-frame move
# op and a sequence mouse-move event.
func _push_mouse_move(pos: Vector2) -> void:
	var viewport := _prepare_mouse_input()
	var previous := viewport.get_mouse_position()
	if _last_injected_mouse_position is Vector2:
		previous = _last_injected_mouse_position
	var event := InputEventMouseMotion.new()
	event.position = pos
	event.relative = pos - previous
	event.button_mask = _injected_mouse_button_mask
	viewport.push_input(event, true)
	_last_injected_mouse_position = pos


# input key: inject one InputEventKey (press or release) into the running game's
# root viewport. Resolves the key name to a keycode via the engine table; an
# unresolvable name is the typed live_invalid_key error.
func _handle_input_key(params: Dictionary) -> String:
	var key := _string_param(params, "key")
	var keycode := _resolve_keycode(key)
	if keycode == KEY_NONE:
		return _error(LIVE_ERROR_INVALID_KEY,
				"could not resolve key name to a keycode: " + key)
	var modifiers: Array = params.get("modifiers", [])
	if typeof(modifiers) != TYPE_ARRAY:
		modifiers = []
	var pressed := not bool(params.get("released", false))
	_input_viewport().push_input(_make_key_event(keycode, modifiers, pressed))
	return _ok({
		"kind": "key",
		"key": key,
		"keycode": keycode,
		"modifiers": modifiers,
		"pressed": pressed,
	})


# The runtime path of the root viewport's current focus owner, or null with no
# focused Control — the before/after focus evidence the activation ops report
# (#652). A pure read; the engine exposes no equivalent "was the event handled"
# evidence, so focus is the observable half.
func _focus_owner_path() -> Variant:
	var owner := _input_viewport().gui_get_focus_owner()
	if owner == null:
		return null
	return String(owner.get_path())


# input mouse-click: inject the COMPLETE click gesture at (x, y) into the root
# viewport — the initial move, the press, and the release, one per process frame
# (frames 0/1/2 of a 3-frame window on the #223 multi-frame base). The gesture is
# what the op's name implies: a bare press never completes a UI activation (a
# default Button emits `pressed` only on the release) and leaves the button held
# down forever (#652, GDA-DF-004); the initial move settles hover state at the
# click position first. Each phase applies at its own frame boundary (ADR-0020).
func _handle_input_mouse_click(params: Dictionary) -> Variant:
	var x := _float_param(params, "x", 0.0)
	var y := _float_param(params, "y", 0.0)
	var button := _string_param(params, "button")
	if button.is_empty():
		button = "left"
	var double := bool(params.get("double", false))
	var pos := Vector2(x, y)
	var focus_before: Variant = _focus_owner_path()
	var frame_box := {"n": 0}
	var sample := func() -> Variant:
		var current := int(frame_box["n"])
		match current:
			0:
				_push_mouse_move(pos)
			1:
				_push_mouse_button_phase(pos, button, true, double)
			2:
				# A release is never a double click; the double flag rides the press.
				_push_mouse_button_phase(pos, button, false, false)
		frame_box["n"] = current + 1
		return current
	var finalize := func(_samples: Array) -> String:
		return _ok({
			"kind": "mouse_click",
			"position": [x, y],
			"button": button,
			"double": double,
			"phases": [
				{"frame": 0, "phase": "move"},
				{"frame": 1, "phase": "press"},
				{"frame": 2, "phase": "release"},
			],
			"focus_before": focus_before,
			"focus_after": _focus_owner_path(),
		})
	return _begin_window(3, sample, finalize)


# input mouse-move: inject an InputEventMouseMotion to (x, y) into the root
# viewport. A single-frame op.
func _handle_input_mouse_move(params: Dictionary) -> String:
	var x := _float_param(params, "x", 0.0)
	var y := _float_param(params, "y", 0.0)
	_push_mouse_move(Vector2(x, y))
	return _ok({
		"kind": "mouse_move",
		"position": [x, y],
		"button": null,
		"double": null,
	})


# input action: press or release a named input action against the running
# InputMap. The action MUST exist in the running InputMap — an unknown action is
# the typed live_unknown_action error (validated via InputMap.has_action).
func _handle_input_action(params: Dictionary) -> String:
	var action := _string_param(params, "action")
	if not InputMap.has_action(action):
		return _error(LIVE_ERROR_UNKNOWN_ACTION,
				"the running InputMap has no action: " + action)
	var release := bool(params.get("release", false))
	var strength := _float_param(params, "strength", 1.0)
	if release:
		Input.action_release(action)
	else:
		Input.action_press(action, strength)
	return _ok({
		"kind": "action",
		"action": action,
		"pressed": not release,
		"strength": 0.0 if release else strength,
	})


# input tap: the complete press-hold-release gesture for ONE key or ONE action
# (#652). Godot needs the press and the release to land on separate process
# frames for a UI activation — a pair contained in one immediate frame reports
# success without advancing the focused UI (GDA-DF-034) — so the tap presses at
# window frame 0, holds for `hold_frames` frames, releases at frame
# `hold_frames`, then lets `settle_frames` more frames run so the game observes
# the release before the op returns. Built on the #223 multi-frame base; the
# frame counts are bounded model-side (ADR-0015). Validation is up front: an
# unresolvable key is live_invalid_key, an action missing from the running
# InputMap is live_unknown_action — the same two live-only failures the
# single-event ops defer to the harness.
func _handle_input_tap(params: Dictionary) -> Variant:
	var hold := _int_param(params, "hold_frames", 2)
	var settle := _int_param(params, "settle_frames", 2)
	var key := _string_param(params, "key")
	var action := _string_param(params, "action")
	var press := Callable()
	var release := Callable()
	var echo := {}
	if not action.is_empty():
		if not InputMap.has_action(action):
			return _error(LIVE_ERROR_UNKNOWN_ACTION,
					"the running InputMap has no action: " + action)
		var strength := _float_param(params, "strength", 1.0)
		press = func() -> void: Input.action_press(action, strength)
		release = func() -> void: Input.action_release(action)
		echo = {"action": action, "strength": strength}
	else:
		var keycode := _resolve_keycode(key)
		if keycode == KEY_NONE:
			return _error(LIVE_ERROR_INVALID_KEY,
					"could not resolve key name to a keycode: " + key)
		var modifiers: Array = params.get("modifiers", [])
		if typeof(modifiers) != TYPE_ARRAY:
			modifiers = []
		press = func() -> void:
			_input_viewport().push_input(_make_key_event(keycode, modifiers, true))
		release = func() -> void:
			_input_viewport().push_input(_make_key_event(keycode, modifiers, false))
		echo = {"key": key, "keycode": keycode, "modifiers": modifiers}
	var focus_before: Variant = _focus_owner_path()
	var frame_box := {"n": 0}
	var sample := func() -> Variant:
		var current := int(frame_box["n"])
		if current == 0:
			press.call()
		elif current == hold:
			release.call()
		frame_box["n"] = current + 1
		return current
	var finalize := func(_samples: Array) -> String:
		var payload := {
			"kind": "tap",
			"hold_frames": hold,
			"settle_frames": settle,
			"frames": hold + settle + 1,
			"phases": [
				{"frame": 0, "phase": "press"},
				{"frame": hold, "phase": "release"},
			],
			"focus_before": focus_before,
			"focus_after": _focus_owner_path(),
		}
		payload.merge(echo)
		return _ok(payload)
	return _begin_window(hold + settle + 1, sample, finalize)


# input sequence: inject a list of events across either process or physics frames,
# returned as ONE blocking result via the time-windowed multi-frame base (#223). The
# window spans one past the largest selected-clock offset; each selected-clock frame
# the sampler applies the events due at that index. An event whose type the harness
# does not recognize aborts the window with live_invalid_event_spec (the defensive
# arm — the model bounds the type).
func _handle_input_sequence(params: Dictionary) -> Variant:
	var raw_events: Variant = params.get("events", [])
	if typeof(raw_events) != TYPE_ARRAY or (raw_events as Array).is_empty():
		return _error(LIVE_ERROR_INVALID_EVENT_SPEC,
				"input sequence needs a non-empty events list")
	var events: Array = raw_events
	# The window runs for as many selected-clock frames as the largest event offset
	# requires (at least one), so every event's relative index lands within it.
	var uses_physics := false
	var uses_process := false
	var max_offset := 0
	for event in events:
		if typeof(event) == TYPE_DICTIONARY:
			if _sequence_event_uses_physics(event):
				uses_physics = true
			else:
				uses_process = true
			max_offset = maxi(max_offset, _sequence_event_offset(event))
	if uses_physics and uses_process:
		return _error(LIVE_ERROR_INVALID_EVENT_SPEC,
				"input sequence cannot mix frame and physics_frame offsets")
	var clock := WINDOW_CLOCK_PHYSICS if uses_physics else WINDOW_CLOCK_PROCESS
	var total_frames := max_offset + 1
	var frame_box := {"n": 0}
	_injected_mouse_button_mask = 0
	# The sampler applies every event due at the current selected-clock index, then
	# advances that clock. A bad event type aborts the window with a typed error sample.
	var sample := func() -> Variant:
		var current := int(frame_box["n"])
		for event in events:
			if typeof(event) != TYPE_DICTIONARY:
				continue
			if _sequence_event_offset(event) != current:
				continue
			var err: Variant = _apply_sequence_event(event)
			if err != null:
				_injected_mouse_button_mask = 0
				return {"error": err}
		frame_box["n"] = current + 1
		return current
	var finalize := func(_samples: Array) -> String:
		_injected_mouse_button_mask = 0
		return _ok({
			"kind": "sequence",
			"clock": clock,
			"events": events.size(),
			"frames": total_frames,
		})
	return _begin_window(total_frames, sample, finalize, clock)


func _sequence_event_uses_physics(event: Dictionary) -> bool:
	return event.has("physics_frame") and event.get("physics_frame") != null


func _sequence_event_offset(event: Dictionary) -> int:
	if _sequence_event_uses_physics(event):
		return _int_param(event, "physics_frame", 0)
	return _int_param(event, "frame", 0)


# Apply one sequence event at a frame boundary. Returns null on success, or a typed
# {code, message} error envelope to abort the window. The event types mirror the
# single-frame ops; an unrecognized type is live_invalid_event_spec.
func _apply_sequence_event(event: Dictionary) -> Variant:
	var type := _string_param(event, "type")
	match type:
		"key":
			var key := _string_param(event, "key")
			var keycode := _resolve_keycode(key)
			if keycode == KEY_NONE:
				return {"code": LIVE_ERROR_INVALID_KEY,
						"message": "could not resolve key name to a keycode: " + key}
			var modifiers: Array = event.get("modifiers", [])
			if typeof(modifiers) != TYPE_ARRAY:
				modifiers = []
			var pressed := not bool(event.get("released", false))
			_input_viewport().push_input(_make_key_event(keycode, modifiers, pressed))
			return null
		"mouse_click":
			var button := _string_param(event, "button")
			if button.is_empty():
				button = "left"
			_push_whole_mouse_click(
					Vector2(_float_param(event, "x", 0.0), _float_param(event, "y", 0.0)),
					button, bool(event.get("double", false)))
			return null
		"mouse_button":
			var button := _string_param(event, "button")
			if button.is_empty():
				button = "left"
			_push_mouse_button_phase(
					Vector2(_float_param(event, "x", 0.0), _float_param(event, "y", 0.0)),
					button,
					bool(event.get("pressed", false)),
					bool(event.get("double", false)))
			return null
		"mouse_move":
			_push_mouse_move(
					Vector2(_float_param(event, "x", 0.0), _float_param(event, "y", 0.0)))
			return null
		"action":
			var action := _string_param(event, "action")
			if not InputMap.has_action(action):
				return {"code": LIVE_ERROR_UNKNOWN_ACTION,
						"message": "the running InputMap has no action: " + action}
			if bool(event.get("release", false)):
				Input.action_release(action)
			else:
				Input.action_press(action, _float_param(event, "strength", 1.0))
			return null
		_:
			return {"code": LIVE_ERROR_INVALID_EVENT_SPEC,
					"message": "unsupported input sequence event type: " + type}


# --- screen (runtime viewport capture, #222) ----------------------------------
#
# Capture the running game's VIEWPORT over the LIVE channel: read the viewport's
# rendered texture as an Image, PNG-encode it, and base64 the PNG into the ADR-0002
# sentinel reply (a UTF-8-safe wire). The CLI decodes it and writes the file.
#
# Display guard: a viewport capture needs a real DisplayServer to have rendered
# pixels. Under `--headless` Godot uses the dummy "headless" DisplayServer whose
# texture is empty, so a capture there is the typed `live_display_unavailable`
# (start the daemon `--windowed`). Checked up front, before opening any window.
#
# GPU-framebuffer timing: `get_viewport().get_texture().get_image()` reads the
# texture for the LAST rendered frame, which can be empty if read before the first
# real frame has rendered (the harness's _ready runs before the main scene is even
# instantiated). Both ops therefore capture INSIDE a window tick — reusing the #223
# time-windowed base — so the sample runs on a _process frame boundary AFTER the
# scene is up (the _process loop only dispatches once current_scene != null), by
# which point a frame has rendered. `screen capture` is a 1-frame window; `screen
# frames` an N-frame one. No _process change — same sampler/finalizer base as perf.


# True when the running session has no real display — the dummy "headless"
# DisplayServer (`--headless`, i.e. the daemon was NOT started --windowed), whose
# viewport renders no pixels. The one runtime fact the model cannot pre-check.
func _display_is_headless() -> bool:
	return DisplayServer.get_name() == "headless"


# Capture the current viewport frame as a base64 PNG + its dims. Returns a frame
# Dictionary on success, or an {"error": {...}} envelope (window-aborting form) if
# the image could not be read/encoded. Shared by both screen ops' samplers so the
# single-frame and multi-frame captures encode identically.
func _capture_frame() -> Dictionary:
	var texture := get_viewport().get_texture()
	if texture == null:
		return {"error": {
			"code": LIVE_ERROR_DISPLAY_UNAVAILABLE,
			"message": "the running viewport has no texture to capture",
		}}
	var image: Image = texture.get_image()
	if image == null or image.is_empty():
		return {"error": {
			"code": LIVE_ERROR_DISPLAY_UNAVAILABLE,
			"message": "the running viewport rendered no image to capture",
		}}
	var png := image.save_png_to_buffer()
	return {
		"width": image.get_width(),
		"height": image.get_height(),
		"format": "png",
		"bytes": png.size(),
		"png_base64": Marshalls.raw_to_base64(png),
	}


# The capture receipt (#660, GDA-DF-026/031): the engine-side identity facts that
# bind ONE captured image to the session, its launched scene, and the frame it
# came from. `session_id` is the daemon-minted identity from the launch tail (""
# from a launcher that predates it); `scene_path` / `scene_uid` are the LAUNCHED
# scene's identity per issue #660 — remembered at the handshake's scene
# verification, the same value the daemon verified, so they are a launch fact,
# not a claim about what an individual frame presents (a game that switches
# scenes mid-session still receipts under its launched scene; the uid is the
# scene FILE's own header declaration, null for a gda-authored scene, ADR-0036).
# `engine_frame` is read at the SAME frame boundary as the pixels; `observed` is
# the predicate echo for a gated capture (null on a plain one — the CLI refuses
# an unsolicited echo). The CLI adds the output hash after writing the file.
func _capture_receipt(observed: Variant) -> Dictionary:
	return {
		"session_id": _session_id,
		"scene_path": _launched_scene_path,
		"scene_uid": _launched_scene_uid,
		"engine_frame": Engine.get_process_frames(),
		"observed": observed,
	}


# The scene file's own uid:// identity, as the FILE HEADER declares it (#660;
# ADR-0036's read side: "the project provides one" means the header carries it).
# `ResourceLoader.get_resource_uid` cannot serve here: outside the editor it
# consults only the runtime UID registry (core/io/resource_loader.cpp), which an
# editor-never-opened project has no `.godot/uid_cache.bin` to fill — so read
# the same header attribute the engine's TEXT loader reads in editor mode
# (`ResourceFormatLoaderText::get_resource_uid`). Text scene formats only;
# anything else — including a header without the attribute — reports null.
func _scene_header_uid(scene_path: String) -> Variant:
	if not (scene_path.ends_with(".tscn") or scene_path.ends_with(".tres")):
		return null
	var file := FileAccess.open(scene_path, FileAccess.READ)
	if file == null:
		return null
	var header := file.get_line()
	file.close()
	var pattern := RegEx.new()
	# Godot's header parser accepts horizontal whitespace around `=` (PR #746
	# review: `uid = "uid://…"` is a legal, engine-preserved header), so the
	# match must too.
	if pattern.compile("\\buid[ \\t]*=[ \\t]*\"(uid://[a-z0-9]+)\"") != OK:
		return null
	var found := pattern.search(header)
	return found.get_string(1) if found != null else null


# screen capture: capture ONE viewport frame, returned as a base64 PNG + dims (the
# CLI writes the file). A 1-frame window so the capture lands on a _process tick
# after the scene is up and a frame has rendered (the GPU-timing fix). A headless
# session is the typed live_display_unavailable, refused up front.
func _handle_screen_capture(params: Dictionary) -> Variant:
	if _display_is_headless():
		return _error(LIVE_ERROR_DISPLAY_UNAVAILABLE,
				"the engine session is headless (no DisplayServer to render pixels); "
				+ "start the daemon with `gda daemon start --windowed`")
	var await_spec: Variant = params.get("await", null)
	if typeof(await_spec) == TYPE_DICTIONARY:
		return _begin_predicate_capture(await_spec, params.get("events", []))
	var sample := func() -> Variant:
		var frame := _capture_frame()
		if frame.has("error"):
			return frame  # abort the window with the typed error envelope
		# The receipt is built INSIDE the sample (#660), at the same frame
		# boundary the pixels were read at, so its engine_frame is the frame
		# the image presents. A plain capture echoes no predicate (null).
		frame["receipt"] = _capture_receipt(null)
		return frame
	var finalize := func(samples: Array) -> String:
		# A 1-frame window: the single sample is the captured frame, returned flat.
		return _ok(samples[0])
	return _begin_window(1, sample, finalize)


# screen frames: capture a WINDOW of N viewport frames, one per frame boundary,
# returned as the per-frame base64 PNG list (the CLI writes one file per frame).
# Reuses the #223 time-windowed base with its own capture sampler/finalizer — no
# _process change. A headless session is the typed live_display_unavailable.
func _handle_screen_frames(params: Dictionary) -> Variant:
	if _display_is_headless():
		return _error(LIVE_ERROR_DISPLAY_UNAVAILABLE,
				"the engine session is headless (no DisplayServer to render pixels); "
				+ "start the daemon with `gda daemon start --windowed`")
	var frames := _int_param(params, "frames", 1)
	var sample := func() -> Variant:
		var frame := _capture_frame()
		if frame.has("error"):
			return frame  # abort the window with the typed error envelope
		return frame
	var finalize := func(samples: Array) -> String:
		return _ok({
			"count": samples.size(),
			"frames": samples,
		})
	return _begin_window(frames, sample, finalize)


# screen capture --await (#661): the predicate-gated capture, GDA-DF-023. Input
# and capture as separate round trips routinely miss a 3-8 frame transient, so
# the window arms at request arrival and does the whole job game-side, on the
# PROCESS clock (physics-clock event offsets are refused): each frame it first
# applies the inline input events due at that offset (the atomic
# input-and-capture form; the events reuse the input-sequence shapes and
# _apply_sequence_event verbatim), then evaluates the predicate
# `node.property == value`. Each tick EVALUATES BEFORE it injects (#743
# re-review, ARC-743-004): the property is read before this tick's events run,
# so the observed value is always the state of the previously COMPLETED frame —
# exactly the frame the viewport texture presents — and the pixels are read at
# that same boundary. This holds for both trigger paths, verified live: a
# _process-driven flip is observed with its own presentation, and a state an
# injected event writes (a synchronous _input callback) is observed one
# boundary LATER, together with its presentation. Two declared consequences:
# the predicate sees frame-boundary state only (a value overwritten before its
# frame completes is never observable — the typed unmet error, not a capture
# of mismatched pixels), and an event's effect is observable from the NEXT
# boundary, so the last state-changing event needs at least one frame of
# window left. The reply waits for every accepted event — an early match must
# not leave a scheduled release unexecuted — and a DECLARED EVENT FAILURE is
# the reply even after a capture succeeded (#743 re-review, ARC-743-001): the
# capture payload is discarded, later events still drain, and the CLI writes
# no file. A predicate that never holds within `frames` is the typed
# live_predicate_unmet, carrying the last observed value.
func _begin_predicate_capture(await_spec: Dictionary, raw_events: Variant) -> Variant:
	var node_path := String(await_spec.get("node", ""))
	var node := _resolve_runtime_node(node_path)
	if node == null:
		return _error(LIVE_ERROR_NODE_NOT_FOUND,
				"no node at runtime path: " + node_path)
	var prop := String(await_spec.get("property", ""))
	if not _runtime_property_declared(node, prop):
		return _error(LIVE_ERROR_UNKNOWN_PROPERTY,
				_unknown_runtime_property_message(node_path, prop))
	var expected: Variant = await_spec.get("value", null)
	var frames := _int_param(await_spec, "frames", 60)
	var events: Array = raw_events if typeof(raw_events) == TYPE_ARRAY else []
	var last_event := -1
	for event in events:
		if typeof(event) != TYPE_DICTIONARY:
			continue
		if _sequence_event_uses_physics(event):
			return _error(LIVE_ERROR_INVALID_EVENT_SPEC,
					"a predicate capture applies its events on the process clock; "
					+ "'physics_frame' offsets are not accepted")
		last_event = maxi(last_event, _sequence_event_offset(event))
	var state := {"n": 0, "observed": null, "outcome": null}
	_injected_mouse_button_mask = 0
	var sample := func() -> Variant:
		var current := int(state["n"])
		state["n"] = current + 1
		# Evaluate BEFORE this tick's events run (#743 re-review): the read
		# then always sees the previously completed frame — the same frame the
		# texture presents — never a mid-tick write from a synchronous input
		# callback. The value is read HERE only; the up-front resolution is
		# metadata-only, so a scripted getter runs exactly once per sampled
		# frame (#743 review, ARC-743-002).
		if state["outcome"] == null:
			if not is_instance_valid(node):
				state["outcome"] = {"error": {
					"code": LIVE_ERROR_NODE_NOT_FOUND,
					"message": "the awaited node was freed mid-window: " + node_path,
				}}
			else:
				var observed: Variant = node.get(prop)
				state["observed"] = observed
				if _predicate_matches(observed, expected):
					# Capture at the SAME boundary the predicate was observed
					# at — property and presentation both belong to the frame
					# that just completed (verified live, see above).
					var captured := _capture_frame()
					if captured.has("error"):
						state["outcome"] = captured
					else:
						captured["predicate"] = {
							"node": node_path,
							"property": prop,
							"expected": expected,
							"observed": _predicate_echo(observed),
							"engine_frame": Engine.get_process_frames(),
							"frames_waited": current,
						}
						# Same tick as the evaluation and the pixels (#660), so
						# the receipt's engine_frame IS the evaluation frame and
						# its echo IS the predicate's — the CLI refuses a reply
						# where the two disagree.
						captured["receipt"] = _capture_receipt(
								_predicate_echo(observed))
						state["outcome"] = {"complete": captured}
				elif current + 1 >= frames:
					state["outcome"] = {"error": {
						"code": LIVE_ERROR_PREDICATE_UNMET,
						"message": "the predicate " + node_path + "." + prop
								+ " == " + JSON.stringify(expected)
								+ " did not hold within " + str(frames)
								+ " frames (last observed: "
								+ str(state["observed"]) + ")",
					}}
		# Then inject: every ACCEPTED event fires at its offset, even after
		# the outcome is decided, so a press injected early is never left held
		# (#743 review). A declared event FAILURE becomes the reply — it
		# replaces a captured success (the CLI then writes no file) but never
		# an earlier error — while later events still drain, best effort.
		for event in events:
			if typeof(event) != TYPE_DICTIONARY:
				continue
			if _sequence_event_offset(event) != current:
				continue
			var err: Variant = _apply_sequence_event(event)
			if err != null:
				var outcome: Variant = state["outcome"]
				if outcome == null or (outcome as Dictionary).has("complete"):
					state["outcome"] = {"error": err}
		if state["outcome"] != null and current >= last_event:
			_injected_mouse_button_mask = 0
			return state["outcome"]
		return current
	var finalize := func(_samples: Array) -> String:
		# Defensive only: the sampler decides every path within the budget.
		_injected_mouse_button_mask = 0
		return _error(LIVE_ERROR_PREDICATE_UNMET,
				"the predicate " + node_path + "." + prop + " == "
				+ JSON.stringify(expected) + " did not hold within "
				+ str(frames) + " frames (last observed: "
				+ str(state["observed"]) + ")")
	return _begin_window(maxi(frames, last_event + 1) + 1, sample, finalize)


# The one runtime-property resolution rule, metadata only (#743 review,
# ARC-743-002): a STORAGE property or an explicit SCRIPT VARIABLE — the same
# two-step game get resolves with — decided from get_property_list() alone, so
# resolving NEVER invokes a getter; the owning use case reads the value.
func _runtime_property_declared(node: Node, prop_name: String) -> bool:
	for entry in node.get_property_list():
		if String(entry.get("name", "")) != prop_name:
			continue
		if _is_storage_property(entry) or _is_script_variable(entry):
			return true
	return false


func _is_script_variable(prop: Dictionary) -> bool:
	return (int(prop.get("usage", 0)) & PROPERTY_USAGE_SCRIPT_VARIABLE) != 0


# JSON-typed predicate equality (#661): bool compares to bool, numbers
# numerically (int frame counters match JSON integers), strings against the
# String rendering (covers StringName), anything else never matches — the
# predicate is a JSON-scalar contract, not a Variant matcher.
func _predicate_matches(observed: Variant, expected: Variant) -> bool:
	match typeof(expected):
		TYPE_BOOL:
			return typeof(observed) == TYPE_BOOL and observed == expected
		TYPE_INT, TYPE_FLOAT:
			if typeof(observed) == TYPE_INT or typeof(observed) == TYPE_FLOAT:
				return float(observed) == float(expected)
			return false
		TYPE_STRING:
			if typeof(observed) == TYPE_STRING or typeof(observed) == TYPE_STRING_NAME:
				return String(observed) == String(expected)
			return false
		TYPE_NIL:
			return typeof(observed) == TYPE_NIL
	return false


# The JSON-safe echo of the observed value for the result (#661; #660's receipt
# echoes it onward): scalars pass through, everything else the diagnostic
# String form — the predicate compares scalars, so the echo never needs the
# full Value projection.
func _predicate_echo(observed: Variant) -> Variant:
	match typeof(observed):
		TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STRING:
			return observed
		TYPE_NIL:
			return null
	return str(observed)


# Read a float param defensively (the params arrive as arbitrary JSON): a missing
# or non-numeric value falls back to `fallback` rather than crashing a typed
# assignment, mirroring _int_param for the float-valued input params (x/y/strength).
func _float_param(params: Dictionary, key: String, fallback: float) -> float:
	var value: Variant = params.get(key, fallback)
	if typeof(value) == TYPE_FLOAT or typeof(value) == TYPE_INT:
		return float(value)
	return fallback


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


# The PUBLIC, stable predicate reporting whether gda-daemon launched this run (#362)
# — the SAME condition `gda_log()` gates on (`_daemon_launched`). Game code should
# branch on THIS, not on harness *presence*: where the harness IS installed it only
# captures logs when the daemon launched the session, so gating on presence silently
# drops every record in a plain/editor run. (A supported `gda export run` artifact
# OMITS the harness entirely per ADR-0028, so this predicate is not even present to
# call there — game code must resolve the autoload by node path and null-check it, as
# the `GdaHarness` global does not parse when absent.) A game-side logging helper gates
# on this predicate and falls back to `print()` when the node is absent or the predicate
# is false. It is a PURE READ — no connection, no output, no state change — so the
# ADR-0018 inert-when-dormant guarantee holds: it returns false in a human editor run, a
# plain run, and an export that BYPASSED `gda export run` (the harness physically present
# but inert — `_ready` returns at the `template` gate before `_daemon_launched` is ever
# set), with no side effect in any.
func is_daemon_launched() -> bool:
	return _daemon_launched


# The active opt-in rich-log protocol (#282, ADR-0026). Project code in a live
# session calls `GdaHarness.gda_log(level, message, fields)` to emit ONE fully
# structured, field-carrying log record. It prints a single `<<<GDA:LOG>>>{json}`
# line into the engine log — which the daemon captures via --log-file (ADR-0022) —
# so the daemon's parser turns it into a rich LogRecord (`gda logger tail`).
# JSON.stringify keeps the payload single-line (newlines in `message`/`fields` are
# escaped), so one call is always one log line. It uses a marker DISTINCT from
# RESULT_BEGIN, so a log line can never be mistaken for an op result. Unlike the
# live ops above, this is a plain stdout print, NOT an IPC reply — but it is GATED on a
# daemon-launched session: outside one (a human editor run, a plain run, a shipped
# build) the harness is inert (CONTEXT.md, ADR-0018) and gda_log() is a no-op, so the
# `<<<GDA:LOG>>>` protocol never leaks into ordinary game output. In a daemon-launched
# session it is OBSERVED through the daemon-owned Session log (--log-file, ADR-0022).
func gda_log(level: String, message: String, fields: Dictionary = {}) -> void:
	if not _daemon_launched:
		return
	print(LOG_MARKER + JSON.stringify({
		"level": level,
		"message": message,
		"fields": fields,
	}))


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
func _jsonify(value: Variant, depth: int = 0, texture_digest: bool = false) -> Variant:
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
func _coerce_value(raw: String, type: int, current: Variant = null) -> Variant:
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


func _coerce_dictionary(raw: String, current: Variant = null) -> Variant:
	var parsed: Variant = JSON.parse_string(raw)
	if not (parsed is Dictionary):
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


func _coerce_array(raw: String, current: Variant = null) -> Variant:
	var parsed: Variant = JSON.parse_string(raw)
	if not (parsed is Array):
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
