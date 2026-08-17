class_name RewardRunController
extends Node

signal view_state_changed(state: Dictionary)
signal feedback_saved(payload: Dictionary, path: String)

const RewardRunDocuments = preload(
	"res://content/reward_run/reward_run_documents.gd"
)
const RewardTrial = preload("res://content/reward_run/reward_trial.gd")
const RewardFeedbackRecorder = preload(
	"res://content/reward_run/reward_feedback_recorder.gd"
)
const RewardRun = preload("res://systems/reward_run.gd")
const FEEDBACK_PATH := "user://reward_run_feedback.json"
const TRIAL_IDS: Array[String] = ["trial-one", "trial-two"]
const FIRST_TARGET_HEALTH := 30
const SECOND_TARGET_HEALTH := 90

var phase := "loading"
var current_trial := ""
var playtest_complete := false
var last_feedback_path := ""

var _client: Node
var _executable_path := ""
var _documents := RewardRunDocuments.new()
var _feedback := RewardFeedbackRecorder.new(FEEDBACK_PATH)
var _run := RewardRun.new()
var _model_source: Dictionary = {}
var _baseline_experiment: Dictionary = {}
var _reward_frequency: Dictionary = {}
var _selected_reward_frequency := 0
var _session := ""
var _trials: Array[RewardTrial] = []
var _last_state: Dictionary = {}
var _busy := false


func _init() -> void:
	_run.state_changed.connect(_on_run_state_changed)


func configure(
	client: Node,
	executable_path: String,
) -> void:
	_client = client
	_executable_path = executable_path


func start() -> Dictionary:
	_trials.clear()
	playtest_complete = false
	return await _prepare_live_session()


func start_trial(reward_frequency: int) -> Dictionary:
	if _busy:
		return _failure("trial_in_flight", "a live trial is already in flight")
	if phase != "choose_frequency" or _trials.size() >= TRIAL_IDS.size():
		return _failure("trial_not_ready", phase)
	_busy = true
	_selected_reward_frequency = reward_frequency
	_emit_state(
		{
			"phase": "preparing_trial",
			"reward_frequency": _control_state(reward_frequency),
			"trial_count": TRIAL_IDS.size(),
			"trial_index": _trials.size(),
		}
	)

	var revised: Dictionary = _documents.experiment_with_reward_frequency(
		reward_frequency
	)
	if not revised.get("ok", false):
		return _fail_trial(revised)
	var admitted: Dictionary = await _client.admit_revision(
		_session,
		revised["value"],
	)
	if not admitted.get("ok", false):
		return _fail_trial(admitted)
	var executed: Dictionary = await _client.run_revision(
		_session,
		admitted["revision"],
	)
	if not executed.get("ok", false):
		return _fail_trial(executed)
	var trial := RewardTrial.new()
	var projected: Dictionary = trial.admit_run_result(
		executed["value"],
		reward_frequency,
		TRIAL_IDS[_trials.size()],
		admitted["revision"],
	)
	if not projected.get("ok", false):
		return _fail_trial(projected)

	_trials.append(trial)
	current_trial = trial.trial_id()
	_busy = false
	var gameplay: Dictionary = trial.gameplay_values()
	_run.start(
		gameplay["reward"],
		gameplay["build"],
		FIRST_TARGET_HEALTH,
		SECOND_TARGET_HEALTH,
	)
	_log_event(
		"trial_started",
		{
			"reward_frequency": reward_frequency,
			"trial": current_trial,
			"trial_index": _trials.size() - 1,
		},
	)
	return {"ok": true, "trial": trial.snapshot()}


func primary_action() -> void:
	if playtest_complete or _busy:
		return
	if phase == "run_complete":
		if _trials.size() == TRIAL_IDS.size():
			playtest_complete = true
			phase = "feedback"
			_emit_state(
				{
					"phase": phase,
					"trial_count": TRIAL_IDS.size(),
					"trial_index": _trials.size(),
				}
			)
			_log_event("playtest_ready_for_feedback", {})
			return
		_emit_frequency_choice()
		return
	if phase not in ["before_fight", "reward_ready", "after_fight"]:
		return
	_run.primary_action()


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
	preference: String,
	stronger_reward: String,
	change_clarity: String,
	notes: String,
) -> Dictionary:
	if not playtest_complete:
		return {}
	var trial_records: Array[Dictionary] = []
	for trial in _trials:
		trial_records.append(trial.feedback_record())
	var result := _feedback.save(
		{
			"change_clarity": change_clarity,
			"feedback_kind": "hitl-product-feedback",
			"notes": notes.strip_edges(),
			"preference": preference,
			"stronger_reward": stronger_reward,
			"tracking_issue": 585,
		},
		trial_records,
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


func _prepare_live_session() -> Dictionary:
	phase = "preparing"
	_emit_state(
		{
			"phase": phase,
			"trial_count": TRIAL_IDS.size(),
			"trial_index": _trials.size(),
		}
	)
	var loaded: Dictionary = _documents.load_maintained()
	if not loaded.get("ok", false):
		return _fail_preparation(loaded)
	_model_source = loaded["model_source"]
	_baseline_experiment = loaded["experiment"]
	_reward_frequency = loaded["reward_frequency"]
	if _trials.is_empty():
		_selected_reward_frequency = int(_reward_frequency["value"])
	elif (
		_selected_reward_frequency < int(_reward_frequency["minimum"])
		or _selected_reward_frequency > int(_reward_frequency["maximum"])
	):
		_selected_reward_frequency = int(_reward_frequency["value"])

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
	_emit_frequency_choice()
	_log_event(
		"playtest_ready",
		{"completed_trials": _trials.size(), "trial_count": TRIAL_IDS.size()},
	)
	return {"ok": true}


func _emit_frequency_choice() -> void:
	phase = "choose_frequency"
	_emit_state(
		{
			"phase": phase,
			"reward_frequency": _control_state(_selected_reward_frequency),
			"trial_count": TRIAL_IDS.size(),
			"trial_index": _trials.size(),
		}
	)


func _control_state(value: int) -> Dictionary:
	return {
		"minimum": int(_reward_frequency.get("minimum", 0)),
		"maximum": int(_reward_frequency.get("maximum", 0)),
		"value": value,
	}


func _fail_trial(error: Dictionary) -> Dictionary:
	_busy = false
	phase = "retry"
	_emit_state(
		{
			"phase": phase,
			"reward_frequency": _control_state(_selected_reward_frequency),
			"trial_count": TRIAL_IDS.size(),
			"trial_index": _trials.size(),
		}
	)
	_log_event("live_trial_failed", error)
	return error


func _fail_preparation(error: Dictionary) -> Dictionary:
	phase = "retry"
	_emit_state(
		{
			"phase": phase,
			"trial_count": TRIAL_IDS.size(),
			"trial_index": _trials.size(),
		}
	)
	_log_event("playtest_preparation_failed", error)
	return error


func _on_run_state_changed(state: Dictionary) -> void:
	phase = state["phase"]
	var view_state := state.duplicate(true)
	view_state["reward_frequency_value"] = _selected_reward_frequency
	view_state["trial_index"] = _trials.size() - 1
	view_state["trial_count"] = TRIAL_IDS.size()
	_emit_state(view_state)
	if phase == "run_complete":
		_log_event(
			"trial_completed",
			{"hits": state["hits"], "trial": current_trial},
		)


func _emit_state(state: Dictionary) -> void:
	_last_state = state.duplicate(true)
	view_state_changed.emit(_last_state.duplicate(true))


func _failure(kind: String, detail: String) -> Dictionary:
	return {"ok": false, "kind": kind, "detail": detail}


func _log_event(event_name: String, fields: Dictionary) -> void:
	var harness := get_node_or_null("/root/GdaHarness")
	if harness != null and harness.is_daemon_launched():
		harness.gda_log("info", event_name, fields)
	else:
		print(JSON.stringify({"event": event_name, "fields": fields}))
