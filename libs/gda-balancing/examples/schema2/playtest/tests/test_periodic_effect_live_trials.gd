extends "res://tests/playtest_test_case.gd"

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const PeriodicEffectDocuments = preload(
	"res://content/periodic_effect/periodic_effect_documents.gd"
)
const PeriodicEffectTrial = preload(
	"res://content/periodic_effect/periodic_effect_trial.gd"
)


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var documents := PeriodicEffectDocuments.new()
	var loaded: Dictionary = documents.load_maintained()
	_expect(
		loaded.get("ok", false),
		"maintained Periodic Effect documents load: %s" % JSON.stringify(loaded),
	)
	if not loaded.get("ok", false):
		_finish()
		return
	var normalized_locked: Dictionary = loaded["locked_experiment"].duplicate(true)
	normalized_locked["scenarios"][0]["event_plan"][0]["entrypoint"] = (
		loaded["reactive_experiment"]["scenarios"][0]["event_plan"][0]["entrypoint"]
	)
	_expect(
		normalized_locked == loaded["reactive_experiment"],
		"Effect entrypoint is the only gameplay value that differs",
	)

	var client := GdaExecutionClient.new()
	get_root().add_child(client)
	var started: Dictionary = await client.start(
		OS.get_environment("GDA_BALANCING_EXECUTABLE")
	)
	_expect(started.get("ok", false), "local execution service starts")
	if not started.get("ok", false):
		_finish()
		return
	var created: Dictionary = await client.create_session(
		loaded["model_source"],
		loaded["reactive_experiment"],
	)
	_expect(created.get("ok", false), "Periodic Effect session is admitted")
	if not created.get("ok", false):
		await client.shutdown()
		_finish()
		return
	var reactive := await _run_trial(
		client, created["session"], created["revision"], "reactive", "trial-one"
	)
	_expect(
		reactive.get("ok", false),
		"reactive Effect trial validates: %s" % JSON.stringify(reactive),
	)
	var admitted: Dictionary = await client.admit_revision(
		created["session"], loaded["locked_experiment"]
	)
	_expect(admitted.get("ok", false), "same session admits the locked Effect trial")
	var locked := await _run_trial(
		client, created["session"], admitted["revision"], "locked", "trial-two"
	)
	_expect(
		locked.get("ok", false),
		"locked Effect trial validates: %s" % JSON.stringify(locked),
	)
	if reactive.get("ok", false) and locked.get("ok", false):
		_expect(
			_phases(reactive["gameplay"]) == ["apply", "pulse", "attack", "pulse", "expire"],
			"reactive trial presents the full player-facing lifecycle",
		)
		_expect(
			int(reactive["gameplay"]["timeline"][-1]["health"]) == 75,
			"reactive trial ends at the validated health",
		)
		_expect(
			int(locked["gameplay"]["timeline"][-1]["health"]) == 60,
			"locked trial ends at the validated health",
		)
		_expect(
			not reactive["gameplay"].has("provenance")
			and reactive["feedback"].has("provenance"),
			"technical provenance stays in Content feedback",
		)
	_expect(
		created.get("revision") != admitted.get("revision"),
		"the two complete Experiments have distinct exact revisions",
	)
	await client.delete_session(created["session"])
	await client.shutdown()
	client.queue_free()
	_finish()


func _run_trial(
	client: Node,
	session: String,
	revision: String,
	policy: String,
	trial_id: String,
) -> Dictionary:
	var run: Dictionary = await client.run_revision(session, revision)
	if not run.get("ok", false):
		return run
	if policy == "reactive":
		_test_contradictory_pulses(run["value"], revision)
	var trial := PeriodicEffectTrial.new()
	var projected: Dictionary = trial.admit_run_result(
		run["value"], policy, trial_id, revision
	)
	if not projected.get("ok", false):
		return projected
	return {
		"ok": true,
		"feedback": trial.feedback_record(),
		"gameplay": trial.gameplay_values(),
	}


func _test_contradictory_pulses(
	run_result: Dictionary,
	revision: String,
) -> void:
	var forged := run_result.duplicate(true)
	var transitions := _transition_events(forged)
	_set_state_value(transitions[1]["state_after"], "target_health", 80)
	_set_state_value(transitions[2]["state_before"], "target_health", 80)
	_set_state_value(transitions[2]["state_after"], "target_health", 70)
	_set_state_value(transitions[3]["state_before"], "target_health", 70)
	var trial := PeriodicEffectTrial.new()
	var admitted: Dictionary = trial.admit_run_result(
		forged, "reactive", "mutation", revision
	)
	_expect(
		not admitted.get("ok", false),
		"Content rejects pulse damage that contradicts Formula evidence",
	)


func _transition_events(run_result: Dictionary) -> Array[Dictionary]:
	var transitions: Array[Dictionary] = []
	for event in run_result.get("artifacts", {}).get("event-trace", {}).get("events", []):
		if event.get("ordering_key", {}).get("phase") == "transition":
			transitions.append(event)
	return transitions


func _set_state_value(rows: Array, name: String, value: int) -> void:
	for row in rows:
		if row.get("name") == name:
			row["value"] = value
			return


func _phases(gameplay: Dictionary) -> Array[String]:
	var phases: Array[String] = []
	for step in gameplay.get("timeline", []):
		phases.append(str(step.get("phase", "")))
	return phases
