class_name CombatCastController
extends Node

signal view_state_changed(state: Dictionary)
signal feedback_saved(payload: Dictionary, path: String)

const CombatCastDocuments = preload(
	"res://content/combat_cast/combat_cast_documents.gd"
)
const CombatExchange = preload(
	"res://content/combat_cast/combat_exchange.gd"
)
const CombatDuel = preload("res://systems/combat_duel.gd")
const PlaytestFeedbackFile = preload(
	"res://addons/playtest_feedback_file/playtest_feedback_file.gd"
)
const FEEDBACK_PATH := "user://rpg_combat_cast_feedback.json"
const EXCHANGE_IDS: Array[String] = ["exchange-one", "exchange-two"]

var phase := "loading"
var playtest_complete := false
var last_feedback_path := ""

var _client: Node
var _executable_path := ""
var _documents := CombatCastDocuments.new()
var _feedback := PlaytestFeedbackFile.new()
var _duel: CombatDuel
var _model_source: Dictionary = {}
var _baseline_experiment: Dictionary = {}
var _initial_state: Dictionary = {}
var _session := ""
var _initial_revision := ""
var _exchanges: Array[CombatExchange] = []
var _last_state: Dictionary = {}
var _busy := false


func configure(client: Node, executable_path: String, duel: CombatDuel) -> void:
	_client = client
	_executable_path = executable_path
	_duel = duel
	_duel.state_changed.connect(_on_duel_state_changed)


func start() -> Dictionary:
	_exchanges.clear()
	playtest_complete = false
	return await _prepare_live_session()


func primary_action() -> void:
	if playtest_complete or _busy:
		return
	match phase:
		"ready":
			_run_next_exchange()
		"before_exchange", "player_resolved", "enemy_resolved":
			_duel.primary_action()
		"exchange_complete":
			if _exchanges.size() == EXCHANGE_IDS.size():
				playtest_complete = true
				phase = "feedback"
				_emit_state({"phase": phase})
			else:
				_emit_ready()


func retry() -> Dictionary:
	if _busy:
		return _failure("exchange_in_flight", "a live exchange is already in flight")
	_busy = true
	if not _session.is_empty():
		await _client.delete_session(_session)
	await _client.shutdown()
	_session = ""
	_busy = false
	return await _prepare_live_session()


func shutdown() -> Dictionary:
	if _client == null:
		return {"ok": true}
	if not _session.is_empty():
		await _client.delete_session(_session)
		_session = ""
	return await _client.shutdown()


func submit_feedback(
	preferred_exchange: String,
	readability: String,
	counterattack_feel: String,
	notes: String,
) -> Dictionary:
	if not playtest_complete:
		return {}
	var exchange_records: Array[Dictionary] = []
	for exchange in _exchanges:
		exchange_records.append(exchange.feedback_record())
	var result := _feedback.save(
		FEEDBACK_PATH,
		{
			"counterattack_feel": counterattack_feel,
			"created_at": Time.get_datetime_string_from_system(true),
			"exchanges": exchange_records,
			"feedback_kind": "hitl-product-feedback",
			"notes": notes.strip_edges(),
			"preferred_exchange": preferred_exchange,
			"readability": readability,
			"schema_version": 1,
			"tracking_issue": 706,
		},
	)
	if result.is_empty():
		return {}
	var payload: Dictionary = result["payload"]
	last_feedback_path = result["path"]
	feedback_saved.emit(payload.duplicate(true), last_feedback_path)
	_log_event("combat_feedback_saved", {"path": last_feedback_path})
	return payload


func current_state() -> Dictionary:
	return _last_state.duplicate(true)


func _prepare_live_session() -> Dictionary:
	phase = "preparing"
	_emit_state({"phase": phase})
	var loaded: Dictionary = _documents.load_maintained()
	if not loaded.get("ok", false):
		return _fail_preparation(loaded)
	_model_source = loaded["model_source"]
	_baseline_experiment = loaded["experiment"]
	_initial_state = loaded["combat_state"]
	var started: Dictionary = await _client.start(_executable_path)
	if not started.get("ok", false):
		return _fail_preparation(started)
	var created: Dictionary = await _client.create_session(
		_model_source,
		_baseline_experiment,
	)
	if not created.get("ok", false):
		await _client.shutdown()
		return _fail_preparation(created)
	_session = created["session"]
	_initial_revision = created["revision"]
	_emit_ready()
	_log_event("combat_playtest_ready", {"completed": _exchanges.size()})
	return {"ok": true}


func _run_next_exchange() -> void:
	if _busy or _exchanges.size() >= EXCHANGE_IDS.size():
		return
	_busy = true
	phase = "preparing_exchange"
	_emit_state(
		{
			"combatants": _next_initial_state(),
			"phase": phase,
		}
	)
	var revision := _initial_revision
	var expected_initial := _next_initial_state()
	if not _exchanges.is_empty():
		var revised := _documents.experiment_from_terminal(expected_initial)
		if not revised.get("ok", false):
			_fail_exchange(revised)
			return
		var admitted: Dictionary = await _client.admit_revision(
			_session,
			revised["value"],
		)
		if not admitted.get("ok", false):
			_fail_exchange(admitted)
			return
		revision = admitted["revision"]
	var run: Dictionary = await _client.run_revision(_session, revision)
	if not run.get("ok", false):
		_fail_exchange(run)
		return
	var exchange := CombatExchange.new()
	var projected: Dictionary = exchange.admit_run_result(
		run["value"],
		expected_initial,
		EXCHANGE_IDS[_exchanges.size()],
		revision,
	)
	if not projected.get("ok", false):
		_fail_exchange(projected)
		return
	_exchanges.append(exchange)
	_busy = false
	_duel.start(exchange.gameplay_values())
	_log_event("combat_exchange_started", {"exchange": _exchanges.size()})


func _emit_ready() -> void:
	phase = "ready"
	_emit_state(
		{
			"combatants": _next_initial_state(),
			"phase": phase,
		}
	)


func _next_initial_state() -> Dictionary:
	if _exchanges.is_empty():
		return _initial_state.duplicate(true)
	return _exchanges[-1].terminal_state()


func _on_duel_state_changed(state: Dictionary) -> void:
	phase = state["phase"]
	var view_state := state.duplicate(true)
	view_state["exchange_count"] = EXCHANGE_IDS.size()
	view_state["exchange_index"] = _exchanges.size() - 1
	_emit_state(view_state)


func _fail_exchange(error: Dictionary) -> void:
	_busy = false
	phase = "retry"
	_emit_state(
		{
			"combatants": _next_initial_state(),
			"phase": phase,
		}
	)
	_log_event("combat_exchange_failed", error)


func _fail_preparation(error: Dictionary) -> Dictionary:
	phase = "retry"
	_emit_state({"phase": phase})
	_log_event("combat_preparation_failed", error)
	return error


func _emit_state(state: Dictionary) -> void:
	var view_state := state.duplicate(true)
	view_state["exchange_count"] = EXCHANGE_IDS.size()
	if not view_state.has("exchange_index"):
		view_state["exchange_index"] = _exchanges.size()
	_last_state = view_state
	view_state_changed.emit(_last_state.duplicate(true))


func _failure(kind: String, detail: String) -> Dictionary:
	return {"ok": false, "kind": kind, "detail": detail}


func _log_event(event_name: String, fields: Dictionary) -> void:
	var harness := get_node_or_null("/root/GdaHarness")
	if harness != null and harness.is_daemon_launched():
		harness.gda_log("info", event_name, fields)
	else:
		print(JSON.stringify({"event": event_name, "fields": fields}))
