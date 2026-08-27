class_name StatCompositionController
extends Node

signal view_state_changed(state: Dictionary)
signal feedback_saved(payload: Dictionary, path: String)

const PlaytestFeedbackFile = preload(
	"res://addons/playtest_feedback_file/playtest_feedback_file.gd"
)
const StatCompositionAttack = preload(
	"res://content/stat_composition/stat_composition_attack.gd"
)
const StatCompositionDocuments = preload(
	"res://content/stat_composition/stat_composition_documents.gd"
)
const FEEDBACK_PATH := "user://rpg_stat_composition_feedback.json"

var phase := "loading"
var playtest_complete := false
var last_feedback_path := ""

var _attacks: Array[StatCompositionAttack] = []
var _baseline_experiment: Dictionary = {}
var _busy := false
var _client: Node
var _documents := StatCompositionDocuments.new()
var _documents_ready := false
var _executable_path := ""
var _feedback := PlaytestFeedbackFile.new()
var _last_attack: Dictionary = {}
var _last_state: Dictionary = {}
var _model_source: Dictionary = {}
var _rules: Dictionary = {}
var _session := ""
var _settings := {"buff_enabled": 1, "level": 3, "weapon_damage_bonus": 8}
var _setting_contracts: Dictionary = {}
var _target_health := 120
var _target_max_health := 120


func configure(client: Node, executable_path: String) -> void:
	_client = client
	_executable_path = executable_path


func start() -> Dictionary:
	_attacks.clear()
	_last_attack.clear()
	playtest_complete = false
	_documents_ready = false
	_target_health = 120
	return await _prepare_live_session()


func set_playtest_options(
	level: int, weapon_damage_bonus: int, buff_enabled: bool
) -> Dictionary:
	if _busy or phase != "ready":
		return _failure("options_locked", "wait for the next attack")
	var selected := {
		"buff_enabled": 1 if buff_enabled else 0,
		"level": level,
		"weapon_damage_bonus": weapon_damage_bonus,
	}
	for name in selected:
		var contract: Dictionary = _setting_contracts.get(name, {})
		var value := int(selected[name])
		if (
			contract.is_empty()
			or value < int(contract["minimum"])
			or value > int(contract["maximum"])
		):
			return _failure("setting_out_of_range", name)
	_settings = selected
	_emit_state()
	return {"ok": true}


func primary_action() -> void:
	if _busy or playtest_complete:
		return
	if phase == "ready":
		_run_attack()
	elif phase == "retry":
		retry()
	elif phase == "defeated":
		restart_training()


func restart_training() -> void:
	if _busy:
		return
	_attacks.clear()
	_last_attack.clear()
	playtest_complete = false
	_target_health = _target_max_health
	phase = "ready"
	_emit_state()
	_log_event("stat_training_restarted", _settings)


func open_feedback() -> void:
	if phase != "defeated" or _busy:
		return
	playtest_complete = true
	phase = "feedback"
	_emit_state()


func retry() -> Dictionary:
	if _busy:
		return _failure("attack_in_flight", "an attack is already in flight")
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
	clarity: String,
	maximum_clarity: String,
	least_clear: String,
	notes: String,
) -> Dictionary:
	if not playtest_complete:
		return {}
	var records: Array[Dictionary] = []
	var reached_cap := false
	for attack in _attacks:
		var record := attack.feedback_record()
		records.append(record)
		reached_cap = reached_cap or bool(record["capped"])
	var result := _feedback.save(
		FEEDBACK_PATH,
		{
			"attacks": records,
			"completion_state": "dummy-defeated",
			"created_at": Time.get_datetime_string_from_system(true),
			"feedback_kind": "hitl-product-feedback",
			"least_clear": least_clear,
			"maximum_clarity": maximum_clarity,
			"notes": notes.strip_edges(),
			"relationship_clarity": clarity,
			"reached_cap": reached_cap,
			"schema_version": 1,
			"tracking_issue": 546,
		},
	)
	if result.is_empty():
		return {}
	var payload: Dictionary = result["payload"]
	last_feedback_path = result["path"]
	feedback_saved.emit(payload.duplicate(true), last_feedback_path)
	_log_event("stat_training_feedback_saved", {"path": last_feedback_path})
	return payload


func current_state() -> Dictionary:
	return _last_state.duplicate(true)


func _prepare_live_session() -> Dictionary:
	phase = "preparing"
	_emit_state()
	if not _documents_ready:
		var loaded: Dictionary = _documents.load_maintained()
		if not loaded.get("ok", false):
			return _fail_preparation(loaded)
		_model_source = loaded["model_source"]
		_baseline_experiment = loaded["experiment"]
		_rules = loaded["rules"]
		_setting_contracts = loaded["settings"]
		_target_max_health = int(loaded["target_max_health"])
		_target_health = _target_max_health
		for name in _settings:
			_settings[name] = int(_setting_contracts[name]["value"])
		_documents_ready = true
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
	phase = "ready"
	_emit_state()
	_log_event("stat_training_ready", {"completed_attacks": _attacks.size()})
	return {"ok": true}


func _run_attack() -> void:
	_busy = true
	phase = "attacking"
	_emit_state()
	var attack_index := _attacks.size() + 1
	var authored := _documents.experiment_for_attack(
		_target_health,
		_settings,
		attack_index,
	)
	if not authored.get("ok", false):
		_fail_attack(authored)
		return
	var admitted: Dictionary = await _client.admit_revision(_session, authored["value"])
	if not admitted.get("ok", false):
		_fail_attack(admitted)
		return
	var revision := str(admitted["revision"])
	var run: Dictionary = await _client.run_revision(_session, revision)
	if not run.get("ok", false):
		_fail_attack(run)
		return
	var attack := StatCompositionAttack.new()
	var projected := attack.admit_run_result(
		run["value"],
		_target_health,
		_settings,
		int(_rules["maximum_damage"]),
		attack_index,
		revision,
	)
	if not projected.get("ok", false):
		_fail_attack(projected)
		return
	_attacks.append(attack)
	_last_attack = attack.gameplay_values()
	_target_health = int(_last_attack["metrics"]["target_health"])
	_busy = false
	phase = "defeated" if _target_health == 0 else "ready"
	_emit_state()
	_log_event(
		"stat_training_attack_resolved",
		{
			"attack": attack_index,
			"capped": _last_attack["capped"],
			"target_health": _target_health,
		},
	)


func _fail_attack(error: Dictionary) -> void:
	_busy = false
	phase = "retry"
	_emit_state()
	_log_event("stat_training_attack_failed", error)


func _fail_preparation(error: Dictionary) -> Dictionary:
	phase = "retry"
	_emit_state()
	_log_event("stat_training_preparation_failed", error)
	return error


func _emit_state() -> void:
	var state := {
		"attack_count": _attacks.size(),
		"phase": phase,
		"rules": _rules.duplicate(true),
		"settings": _settings.duplicate(true),
		"setting_contracts": _setting_contracts.duplicate(true),
		"target_health": _target_health,
		"target_max_health": _target_max_health,
	}
	if not _last_attack.is_empty():
		state["last_attack"] = _last_attack.duplicate(true)
	_last_state = state
	view_state_changed.emit(_last_state.duplicate(true))


func _failure(kind: String, detail: String) -> Dictionary:
	return {"ok": false, "kind": kind, "detail": detail}


func _log_event(event_name: String, fields: Dictionary) -> void:
	var harness := get_node_or_null("/root/GdaHarness")
	if harness != null and harness.is_daemon_launched():
		harness.gda_log("info", event_name, fields)
	else:
		print(JSON.stringify({"event": event_name, "fields": fields}))
