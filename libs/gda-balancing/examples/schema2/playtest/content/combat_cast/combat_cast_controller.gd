class_name CombatCastController
extends Node

signal view_state_changed(state: Dictionary)
signal feedback_saved(payload: Dictionary, path: String)

const CombatCastDocuments = preload(
	"res://content/combat_cast/combat_cast_documents.gd"
)
const CombatAction = preload("res://content/combat_cast/combat_action.gd")
const CombatDuel = preload("res://systems/combat_duel.gd")
const PlaytestFeedbackFile = preload(
	"res://addons/playtest_feedback_file/playtest_feedback_file.gd"
)
const FEEDBACK_PATH := "user://rpg_combat_cast_feedback.json"

var phase := "loading"
var playtest_complete := false
var last_feedback_path := ""

var _actions: Array[CombatAction] = []
var _battle_outcome := ""
var _busy := false
var _execution
var _combat_state: Dictionary = {}
var _documents := CombatCastDocuments.new()
var _duel: CombatDuel
var _defeat_threshold := 0
var _feedback := PlaytestFeedbackFile.new()
var _last_state: Dictionary = {}
var _model_source: Dictionary = {}
var _baseline_experiment: Dictionary = {}
var _rival_strength := "normal"
var _spell_style := "balanced"


func configure(execution, duel: CombatDuel) -> void:
	_execution = execution
	_duel = duel
	_duel.state_changed.connect(_on_duel_state_changed)


func start() -> Dictionary:
	_actions.clear()
	_battle_outcome = ""
	playtest_complete = false
	return await _prepare_live_session(false)


func primary_action() -> void:
	if playtest_complete or _busy:
		return
	match phase:
		"ready", "enemy_resolved":
			_run_action("player")
		"player_resolved":
			_run_action("enemy")
		"victory", "defeat":
			restart_battle()


func set_playtest_options(spell_style: String, rival_strength: String) -> Dictionary:
	if _busy or not _actions.is_empty() or phase != "ready":
		return _failure("options_locked", "restart before changing duel options")
	var initial := _documents.initial_state_for_options(spell_style, rival_strength)
	if not initial.get("ok", false):
		return initial
	_spell_style = spell_style
	_rival_strength = rival_strength
	_combat_state = initial["value"]
	_duel.start(_combat_state)
	return {"ok": true}


func restart_battle() -> void:
	if _busy:
		return
	var initial := _documents.initial_state_for_options(_spell_style, _rival_strength)
	if not initial.get("ok", false):
		_fail_exchange(initial)
		return
	_actions.clear()
	_battle_outcome = ""
	playtest_complete = false
	_combat_state = initial["value"]
	_duel.start(_combat_state)
	_log_event("combat_battle_restarted", _selected_options())


func open_feedback() -> void:
	if phase not in ["victory", "defeat"] or _busy:
		return
	playtest_complete = true
	phase = "feedback"
	_emit_state({"phase": phase})


func retry() -> Dictionary:
	if _busy:
		return _failure("action_in_flight", "a live action is already in flight")
	_busy = true
	var result := await _prepare_live_session(true)
	_busy = false
	return result


func shutdown() -> Dictionary:
	if _execution == null:
		return {"ok": true}
	return await _execution.shutdown()


func submit_feedback(
	spell_feel: String,
	readability: String,
	counterattack_feel: String,
	notes: String,
) -> Dictionary:
	if not playtest_complete:
		return {}
	var action_records: Array[Dictionary] = []
	for action in _actions:
		action_records.append(action.feedback_record())
	var result := _feedback.save(
		FEEDBACK_PATH,
		{
			"actions": action_records,
			"counterattack_feel": counterattack_feel,
			"created_at": Time.get_datetime_string_from_system(true),
			"feedback_kind": "hitl-product-feedback",
			"notes": notes.strip_edges(),
			"outcome": _battle_outcome,
			"playtest_options": _selected_options(),
			"spell_feel": spell_feel,
			"readability": readability,
			"schema_version": 2,
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


func _prepare_live_session(retrying: bool) -> Dictionary:
	phase = "preparing"
	_emit_state({"phase": phase})
	var loaded: Dictionary = _documents.load_maintained()
	if not loaded.get("ok", false):
		return _fail_preparation(loaded)
	_model_source = loaded["model_source"]
	_baseline_experiment = loaded["experiment"]
	_defeat_threshold = loaded["defeat_threshold"]
	var prepared_state := _combat_state.duplicate(true)
	if not retrying or prepared_state.is_empty():
		var initial := _documents.initial_state_for_options(_spell_style, _rival_strength)
		if not initial.get("ok", false):
			return _fail_preparation(initial)
		prepared_state = initial["value"]
	var established: Dictionary
	if retrying:
		established = await _execution.retry(_model_source, _baseline_experiment)
	else:
		established = await _execution.start(_model_source, _baseline_experiment)
	if not established.get("ok", false):
		return _fail_preparation(established)
	_combat_state = prepared_state
	if retrying and not _actions.is_empty():
		_on_duel_state_changed(_duel.snapshot())
	else:
		_duel.start(_combat_state)
	_log_event("combat_playtest_ready", _selected_options())
	return {"ok": true}


func _run_action(actor: String) -> void:
	if _busy:
		return
	_busy = true
	phase = "resolving_%s" % actor
	_emit_state({"combatants": _combat_state.duplicate(true), "phase": phase})
	var authored := _documents.experiment_for_action(
		_combat_state,
		actor,
		_spell_style,
		_rival_strength,
		_actions.size() + 1,
	)
	if not authored.get("ok", false):
		_fail_exchange(authored)
		return
	var run: Dictionary = await _execution.admit_and_run(authored["value"])
	if not run.get("ok", false):
		_fail_exchange(run)
		return
	var revision := str(run["revision"])
	var action := CombatAction.new()
	var projected: Dictionary = action.admit_run_result(
		run["value"], _combat_state, actor, revision, _defeat_threshold
	)
	if not projected.get("ok", false):
		_fail_exchange(projected)
		return
	_actions.append(action)
	_combat_state = action.terminal_state()
	_busy = false
	var terminal_phase := ""
	if action.target_defeated():
		terminal_phase = "victory" if actor == "player" else "defeat"
		_battle_outcome = terminal_phase
	_duel.present_action(action.gameplay_values(), terminal_phase)
	_log_event(
		"combat_action_resolved",
		{"action": _actions.size(), "actor": actor, "terminal": not terminal_phase.is_empty()},
	)


func _on_duel_state_changed(state: Dictionary) -> void:
	phase = state["phase"]
	_emit_state(state)


func _fail_exchange(error: Dictionary) -> void:
	_busy = false
	phase = "retry"
	_emit_state({"combatants": _combat_state.duplicate(true), "phase": phase})
	_log_event("combat_action_failed", error)


func _fail_preparation(error: Dictionary) -> Dictionary:
	phase = "retry"
	var state := {"phase": phase}
	if not _combat_state.is_empty():
		state["combatants"] = _combat_state.duplicate(true)
	_emit_state(state)
	_log_event("combat_preparation_failed", error)
	return error


func _emit_state(state: Dictionary) -> void:
	var view_state := state.duplicate(true)
	view_state["action_index"] = _actions.size()
	view_state["playtest_options"] = _selected_options()
	view_state["round"] = int(_actions.size() / 2) + 1
	_last_state = view_state
	view_state_changed.emit(_last_state.duplicate(true))


func _selected_options() -> Dictionary:
	return {"rival_strength": _rival_strength, "spell_style": _spell_style}


func _failure(kind: String, detail: String) -> Dictionary:
	return {"ok": false, "kind": kind, "detail": detail}


func _log_event(event_name: String, fields: Dictionary) -> void:
	var harness := get_node_or_null("/root/GdaHarness")
	if harness != null and harness.is_daemon_launched():
		harness.gda_log("info", event_name, fields)
	else:
		print(JSON.stringify({"event": event_name, "fields": fields}))
