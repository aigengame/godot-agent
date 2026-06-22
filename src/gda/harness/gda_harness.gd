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


func _run(request) -> String:
	if typeof(request) != TYPE_DICTIONARY or request.get("op") != "game-tree":
		return _error("operation_failed", "unsupported live operation")
	var scene: Node = get_tree().current_scene
	if scene == null:
		scene = get_tree().root
	return RESULT_BEGIN + JSON.stringify({"root": _serialize(scene)}) + RESULT_END


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


func _error(code: String, message: String) -> String:
	return RESULT_BEGIN + JSON.stringify({"error": {"code": code, "message": message}}) + RESULT_END
