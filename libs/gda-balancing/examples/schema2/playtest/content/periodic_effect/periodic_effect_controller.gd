class_name PeriodicEffectController
extends Node

signal view_state_changed(state: Dictionary)
signal feedback_saved(payload: Dictionary, path: String)

const PeriodicEffectDocuments = preload(
	"res://content/periodic_effect/periodic_effect_documents.gd"
)
const PeriodicEffectTrial = preload(
	"res://content/periodic_effect/periodic_effect_trial.gd"
)
const PeriodicEffectTimeline = preload(
	"res://systems/periodic_effect_timeline.gd"
)
const PlaytestFeedbackFile = preload(
	"res://addons/playtest_feedback_file/playtest_feedback_file.gd"
)
const FEEDBACK_PATH := "user://rpg_periodic_effect_feedback.json"
const TRIAL_KINDS: Array[String] = ["dynamic", "snapshot"]

var phase := "loading"
var playtest_complete := false
var last_feedback_path := ""

var _client: Node
var _executable_path := ""
var _documents := PeriodicEffectDocuments.new()
var _feedback := PlaytestFeedbackFile.new()
var _timeline: PeriodicEffectTimeline
var _model_source: Dictionary = {}
var _experiments: Dictionary = {}
var _session := ""
var _initial_revision := ""
var _initial_health := 0
var _damage_threshold := 0
var _trials: Array[PeriodicEffectTrial] = []
var _last_state: Dictionary = {}
var _busy := false


func configure(
	client: Node,
	executable_path: String,
	timeline: PeriodicEffectTimeline,
) -> void:
	_client = client
	_executable_path = executable_path
	_timeline = timeline
	_timeline.state_changed.connect(_on_timeline_state_changed)


func start() -> Dictionary:
	_trials.clear()
	playtest_complete = false
	return await _prepare_live_session()


func primary_action() -> void:
	if playtest_complete or _busy:
		return
	match phase:
		"ready":
			_run_next_trial()
		"timeline_step":
			_timeline.primary_action()
		"trial_complete":
			if _trials.size() == TRIAL_KINDS.size():
				playtest_complete = true
				phase = "feedback"
				_emit_state({"phase": phase})
			else:
				_emit_target_reset()


func target_reset_completed() -> void:
	if phase != "resetting_target" or _busy or _trials.size() >= TRIAL_KINDS.size():
		return
	_emit_ready()


func retry() -> Dictionary:
	if _busy:
		return _failure("trial_in_flight", "a live trial is already in flight")
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
	preferred_style: String,
	impact_clarity: String,
	timing_clarity: String,
	notes: String,
) -> Dictionary:
	if not playtest_complete:
		return {}
	var trial_records: Array[Dictionary] = []
	for trial in _trials:
		trial_records.append(trial.feedback_record())
	var result := _feedback.save(
		FEEDBACK_PATH,
		{
			"created_at": Time.get_datetime_string_from_system(true),
			"feedback_kind": "hitl-product-feedback",
			"impact_clarity": impact_clarity,
			"notes": notes.strip_edges(),
			"preferred_style": preferred_style,
			"schema_version": 1,
			"timing_clarity": timing_clarity,
			"tracking_issue": 706,
			"trials": trial_records,
		},
	)
	if result.is_empty():
		return {}
	var payload: Dictionary = result["payload"]
	last_feedback_path = result["path"]
	feedback_saved.emit(payload.duplicate(true), last_feedback_path)
	_log_event("periodic_feedback_saved", {"path": last_feedback_path})
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
	_initial_health = loaded["initial_health"]
	_damage_threshold = loaded["damage_threshold"]
	_experiments = {
		"dynamic": loaded["dynamic_experiment"],
		"snapshot": loaded["snapshot_experiment"],
	}
	var started: Dictionary = await _client.start(_executable_path)
	if not started.get("ok", false):
		return _fail_preparation(started)
	var created: Dictionary = await _client.create_session(
		_model_source,
		_experiments["dynamic"],
	)
	if not created.get("ok", false):
		await _client.shutdown()
		return _fail_preparation(created)
	_session = created["session"]
	_initial_revision = created["revision"]
	_emit_ready()
	_log_event("periodic_playtest_ready", {"completed": _trials.size()})
	return {"ok": true}


func _run_next_trial() -> void:
	if _busy or _trials.size() >= TRIAL_KINDS.size():
		return
	_busy = true
	phase = "preparing_trial"
	_emit_state({"phase": phase})
	var policy := TRIAL_KINDS[_trials.size()]
	var revision := _initial_revision
	if policy == "snapshot":
		var admitted: Dictionary = await _client.admit_revision(
			_session, _experiments[policy]
		)
		if not admitted.get("ok", false):
			_fail_trial(admitted)
			return
		revision = admitted["revision"]
	var run: Dictionary = await _client.run_revision(_session, revision)
	if not run.get("ok", false):
		_fail_trial(run)
		return
	var trial := PeriodicEffectTrial.new()
	var projected: Dictionary = trial.admit_run_result(
		run["value"],
		policy,
		"trial-%d" % (_trials.size() + 1),
		revision,
	)
	if not projected.get("ok", false):
		_fail_trial(projected)
		return
	_trials.append(trial)
	_busy = false
	_timeline.start(trial.gameplay_values())
	_log_event("periodic_trial_started", {"trial": _trials.size()})


func _emit_ready() -> void:
	phase = "ready"
	_emit_state(
		{
			"damage_threshold": _damage_threshold,
			"fresh_target": not _trials.is_empty(),
			"initial_health": _initial_health,
			"phase": phase,
			"trial_kind": TRIAL_KINDS[_trials.size()],
		}
	)


func _emit_target_reset() -> void:
	phase = "resetting_target"
	_emit_state(
		{
			"damage_threshold": _damage_threshold,
			"fresh_target": true,
			"initial_health": _initial_health,
			"phase": phase,
			"previous_health": int(_last_state.get("health", _initial_health)),
			"trial_kind": TRIAL_KINDS[_trials.size()],
		}
	)


func _on_timeline_state_changed(state: Dictionary) -> void:
	phase = state["phase"]
	var view_state := state.duplicate(true)
	view_state["damage_threshold"] = _damage_threshold
	view_state["initial_health"] = _initial_health
	view_state["trial_count"] = TRIAL_KINDS.size()
	view_state["trial_index"] = _trials.size() - 1
	_emit_state(view_state)


func _fail_trial(error: Dictionary) -> void:
	_busy = false
	phase = "retry"
	_emit_state({"phase": phase})
	_log_event("periodic_trial_failed", error)


func _fail_preparation(error: Dictionary) -> Dictionary:
	phase = "retry"
	_emit_state({"phase": phase})
	_log_event("periodic_preparation_failed", error)
	return error


func _emit_state(state: Dictionary) -> void:
	var view_state := state.duplicate(true)
	view_state["trial_count"] = TRIAL_KINDS.size()
	if not view_state.has("trial_index"):
		view_state["trial_index"] = _trials.size()
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
