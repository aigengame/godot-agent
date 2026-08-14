extends Node

signal view_state_changed(state: Dictionary)
signal feedback_saved(payload: Dictionary, path: String)

const PlaytestSession = preload("res://systems/playtest_session.gd")
const PlaytestFeedback = preload("res://systems/playtest_feedback.gd")
const RewardRun = preload("res://systems/reward_run.gd")
const FEEDBACK_PATH := "user://reward_run_feedback.json"
const TRIAL_REQUESTS := [
	{"trial_id": "trial-one"},
	{"trial_id": "trial-two"},
]

var phase: String = "loading"
var current_trial: String = ""
var playtest_complete: bool = false
var last_feedback_path: String = ""

var _session := PlaytestSession.new()
var _feedback := PlaytestFeedback.new(FEEDBACK_PATH)
var _run := RewardRun.new()
var _source: RefCounted
var _last_state: Dictionary = {}
var _session_state: Dictionary = {}


func _init() -> void:
	_run.state_changed.connect(_on_run_state_changed)


func configure(source: RefCounted) -> bool:
	_source = source
	var trials: Array[Dictionary] = []
	for request in TRIAL_REQUESTS:
		var outcome: Dictionary = _source.outcome_for(request)
		if outcome.is_empty():
			return false
		trials.append(outcome)
	return _session.configure(trials)


func start() -> void:
	playtest_complete = false
	_session_state = _session.start()
	_start_trial()
	_log_event("playtest_started", {"trial_count": _session_state["trial_count"]})


func primary_action() -> void:
	if playtest_complete:
		return
	if phase == "run_complete":
		_session_state = _session.finish_current_trial()
		if _session_state["complete"]:
			playtest_complete = true
			phase = "feedback"
			_last_state = {
				"phase": phase,
				"trial_count": _session_state["trial_count"],
				"trial_index": _session_state["trial_index"],
			}
			view_state_changed.emit(_last_state.duplicate(true))
			_log_event("playtest_ready_for_feedback", {})
			return
		_start_trial()
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
	var result := _feedback.save(
		{
			"change_clarity": change_clarity,
			"feedback_kind": "hitl-product-feedback",
			"notes": notes.strip_edges(),
			"preference": preference,
			"stronger_reward": stronger_reward,
			"tracking_issue": 585,
		},
		_session.trial_references(),
	)
	if result.is_empty():
		return {}
	var payload: Dictionary = result["payload"]
	last_feedback_path = result["path"]
	feedback_saved.emit(payload.duplicate(true), last_feedback_path)
	_log_event("playtest_feedback_saved", {"path": last_feedback_path})
	return payload


func current_state() -> Dictionary:
	return _last_state.duplicate(true)


func _start_trial() -> void:
	var trial: Dictionary = _session_state["trial"]
	current_trial = str(trial["id"])
	_run.start(trial)
	_log_event(
		"trial_started",
		{"trial": current_trial, "trial_index": _session_state["trial_index"]},
	)


func _on_run_state_changed(state: Dictionary) -> void:
	phase = state["phase"]
	state["trial_index"] = _session_state["trial_index"]
	state["trial_count"] = _session_state["trial_count"]
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
