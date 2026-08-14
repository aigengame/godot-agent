extends Node

signal view_state_changed(state: Dictionary)
signal feedback_saved(payload: Dictionary, path: String)

const PlaytestSession = preload("res://systems/playtest_session.gd")
const RewardRun = preload("res://systems/reward_run.gd")

var phase: String = "loading"
var current_trial: String = ""
var playtest_complete: bool = false
var last_feedback_path: String = ""

var _session := PlaytestSession.new()
var _run := RewardRun.new()
var _source: RefCounted
var _last_state: Dictionary = {}


func _init() -> void:
	_run.state_changed.connect(_on_run_state_changed)


func configure(source: RefCounted, case_path: String) -> bool:
	_source = source
	var trials: Array = _source.load_cases(case_path)
	if trials.is_empty():
		return false
	return _session.configure(trials)


func start() -> void:
	playtest_complete = false
	_start_trial(_session.begin())
	_log_event("playtest_started", {"trial_count": _session.trial_count()})


func primary_action() -> void:
	if playtest_complete:
		return
	if phase == "run_complete":
		var next_trial := _session.advance()
		if next_trial.is_empty():
			playtest_complete = true
			phase = "feedback"
			_last_state = {
				"phase": phase,
				"trial_count": _session.trial_count(),
				"trial_index": _session.trial_count(),
			}
			view_state_changed.emit(_last_state.duplicate(true))
			_log_event("playtest_ready_for_feedback", {})
			return
		_start_trial(next_trial)
		return
	_run.primary_action()


func submit_feedback(
	preference: String,
	stronger_reward: String,
	change_clarity: String,
	notes: String,
) -> Dictionary:
	if not playtest_complete:
		return {}
	var payload := {
		"change_clarity": change_clarity,
		"created_at": Time.get_datetime_string_from_system(true),
		"notes": notes.strip_edges(),
		"preference": preference,
		"schema_version": 1,
		"stronger_reward": stronger_reward,
		"trials": _session.trial_references(),
	}
	last_feedback_path = "user://reward_run_feedback.json"
	var file := FileAccess.open(last_feedback_path, FileAccess.WRITE)
	if file == null:
		return {}
	file.store_string(JSON.stringify(payload, "\t") + "\n")
	feedback_saved.emit(payload.duplicate(true), last_feedback_path)
	_log_event("playtest_feedback_saved", {"path": last_feedback_path})
	return payload


func current_state() -> Dictionary:
	return _last_state.duplicate(true)


func _start_trial(trial: Dictionary) -> void:
	current_trial = str(trial["id"])
	_run.start(trial)
	_log_event(
		"trial_started",
		{"trial": current_trial, "trial_index": _session.current_index()},
	)


func _on_run_state_changed(state: Dictionary) -> void:
	phase = state["phase"]
	state["trial_index"] = _session.current_index()
	state["trial_count"] = _session.trial_count()
	_last_state = state.duplicate(true)
	view_state_changed.emit(_last_state.duplicate(true))
	if phase == "run_complete":
		_log_event(
			"trial_completed",
			{"hits": state["hits"], "trial": current_trial},
		)


func _log_event(event_name: String, fields: Dictionary) -> void:
	var harness := get_node_or_null("/root/GdaHarness")
	if harness != null and harness.is_daemon_launched():
		harness.gda_log("info", event_name, fields)
	else:
		print(JSON.stringify({"event": event_name, "fields": fields}))
