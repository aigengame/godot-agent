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
	var normalized_snapshot: Dictionary = loaded["snapshot_experiment"].duplicate(true)
	normalized_snapshot["scenarios"][0]["event_plan"][0]["entrypoint"] = (
		loaded["dynamic_experiment"]["scenarios"][0]["event_plan"][0]["entrypoint"]
	)
	_expect(
		normalized_snapshot == loaded["dynamic_experiment"],
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
		loaded["dynamic_experiment"],
	)
	_expect(created.get("ok", false), "Periodic Effect session is admitted")
	if not created.get("ok", false):
		await client.shutdown()
		_finish()
		return
	var dynamic := await _run_trial(
		client, created["session"], created["revision"], "dynamic", "trial-one"
	)
	_expect(
		dynamic.get("ok", false),
		"dynamic Effect trial validates: %s" % JSON.stringify(dynamic),
	)
	var admitted: Dictionary = await client.admit_revision(
		created["session"], loaded["snapshot_experiment"]
	)
	_expect(admitted.get("ok", false), "same session admits the fixed Effect trial")
	var snapshot := await _run_trial(
		client, created["session"], admitted["revision"], "snapshot", "trial-two"
	)
	_expect(
		snapshot.get("ok", false),
		"fixed Effect trial validates: %s" % JSON.stringify(snapshot),
	)
	if dynamic.get("ok", false) and snapshot.get("ok", false):
		_expect(
			_phases(dynamic["gameplay"]) == ["apply", "pulse", "attack", "pulse", "expire"],
			"dynamic trial presents the full player-facing lifecycle",
		)
		_expect(
			_pulse_damage(dynamic["gameplay"]) == [15, 0],
			"dynamic pulses expose the cutoff result on both recalculations",
		)
		_expect(
			int(dynamic["gameplay"]["timeline"][-1]["health"]) == 75,
			"dynamic trial preserves the validated terminal health",
		)
		_expect(
			_pulse_damage(snapshot["gameplay"]) == [15, 15],
			"fixed pulses repeat the cast-time damage",
		)
		_expect(
			int(snapshot["gameplay"].get("cast_damage", -1)) == 15,
			"fixed gameplay names the validated cast-time damage for player presentation",
		)
		_expect(
			int(snapshot["gameplay"]["timeline"][-1]["health"]) == 60,
			"fixed trial ends at the validated health",
		)
		_expect(
			not dynamic["gameplay"].has("provenance")
			and dynamic["feedback"].has("provenance"),
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
	if policy == "dynamic":
		_test_dynamic_projection_failures(run["value"], revision)
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


func _test_dynamic_projection_failures(
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
		forged, "dynamic", "mutation", revision
	)
	_expect(
		not admitted.get("ok", false),
		"Content rejects pulse damage that contradicts Formula evidence",
	)

	var inactive := run_result.duplicate(true)
	var inactive_transitions := _transition_events(inactive)
	_set_state_value(inactive_transitions[0]["state_after"], "effect_active", 0)
	for index in range(1, inactive_transitions.size()):
		_set_state_value(inactive_transitions[index]["state_before"], "effect_active", 0)
		_set_state_value(inactive_transitions[index]["state_after"], "effect_active", 0)
	var inactive_trial := PeriodicEffectTrial.new()
	var inactive_admitted: Dictionary = inactive_trial.admit_run_result(
		inactive, "dynamic", "mutation", revision
	)
	_expect(
		not inactive_admitted.get("ok", false),
		"Content rejects pulses after an inactive Effect application",
	)

	var refused := run_result.duplicate(true)
	var refused_transitions := _transition_events(refused)
	refused_transitions[0]["outcome"] = {
		"id": "effect-refused", "kind": "refusal"
	}
	var refused_trial := PeriodicEffectTrial.new()
	var refused_admitted: Dictionary = refused_trial.admit_run_result(
		refused, "dynamic", "mutation", revision
	)
	_expect(
		not refused_admitted.get("ok", false),
		"Content rejects a refused lifecycle transition",
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


func _pulse_damage(gameplay: Dictionary) -> Array[int]:
	var values: Array[int] = []
	for step in gameplay.get("timeline", []):
		if step.get("phase") == "pulse":
			values.append(int(step.get("damage", 0)))
	return values
