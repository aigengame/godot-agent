extends "res://tests/playtest_test_case.gd"

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const CombatCastDocuments = preload(
	"res://content/combat_cast/combat_cast_documents.gd"
)
const CombatExchange = preload(
	"res://content/combat_cast/combat_exchange.gd"
)


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var documents := CombatCastDocuments.new()
	var loaded: Dictionary = documents.load_maintained()
	_expect(
		loaded.get("ok", false),
		"maintained Combat documents load: %s" % JSON.stringify(loaded),
	)
	if not loaded.get("ok", false):
		_finish()
		return

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
		loaded["experiment"],
	)
	_expect(created.get("ok", false), "Combat session admits maintained documents")
	if not created.get("ok", false):
		await client.shutdown()
		_finish()
		return

	var first := await _run_exchange(
		client,
		created["session"],
		created["revision"],
		loaded["combat_state"],
		"exchange-one",
	)
	_expect(
		first.get("ok", false),
		"first complete Combat revision validates: %s" % JSON.stringify(first),
	)
	if not first.get("ok", false):
		await client.delete_session(created["session"])
		await client.shutdown()
		_finish()
		return
	_expect(
		first["gameplay"]["terminal"]
		== {
			"enemy_health": 63,
			"enemy_mana": 23,
			"player_health": 86,
			"player_mana": 26,
		},
		"first exchange returns the maintained terminal combat state",
	)
	_expect(
		first["gameplay"]["damage"] == {"enemy": 14, "player": 37},
		"first exchange returns the maintained reciprocal damage",
	)
	_expect(
		first["gameplay"].get("mana_cost", {}) == {"enemy": 7, "player": 9},
		"first exchange returns the maintained reciprocal mana cost",
	)

	var revised: Dictionary = documents.experiment_from_terminal(
		first["terminal"]
	)
	_expect(revised.get("ok", false), "Content creates the complete next Experiment")
	var admitted: Dictionary = await client.admit_revision(
		created["session"],
		revised["value"],
	)
	_expect(admitted.get("ok", false), "same session admits the next exact revision")
	var second := await _run_exchange(
		client,
		created["session"],
		admitted["revision"],
		first["terminal"],
		"exchange-two",
	)
	_expect(second.get("ok", false), "second complete Combat revision validates")
	if second.get("ok", false):
		_expect(
			second["gameplay"]["initial"] == first["gameplay"]["terminal"],
			"second exchange starts from the first terminal health and mana",
		)
		_expect(
			second["gameplay"]["terminal"]
			== {
				"enemy_health": 26,
				"enemy_mana": 16,
				"player_health": 72,
				"player_mana": 17,
			},
			"second exchange continues the maintained duel",
		)
		_expect(
			not second["gameplay"].has("provenance")
			and second["feedback"].has("provenance"),
			"technical provenance stays in Content feedback",
		)
	_expect(
		admitted.get("revision", "") != created.get("revision", ""),
		"complete Combat Experiments produce distinct exact revisions",
	)

	await client.delete_session(created["session"])
	await client.shutdown()
	client.queue_free()
	_finish()


func _run_exchange(
	client: Node,
	session: String,
	revision: String,
	expected_initial: Dictionary,
	exchange_id: String,
) -> Dictionary:
	var run: Dictionary = await client.run_revision(session, revision)
	if not run.get("ok", false):
		return run
	if exchange_id == "exchange-one":
		_test_contradictory_combat_artifacts(
			run["value"], expected_initial, revision
		)
	var exchange := CombatExchange.new()
	var admitted: Dictionary = exchange.admit_run_result(
		run["value"],
		expected_initial,
		exchange_id,
		revision,
	)
	if not admitted.get("ok", false):
		return admitted
	return {
		"ok": true,
		"feedback": exchange.feedback_record(),
		"gameplay": exchange.gameplay_values(),
		"terminal": exchange.terminal_state(),
	}


func _test_contradictory_combat_artifacts(
	run_result: Dictionary,
	expected_initial: Dictionary,
	revision: String,
) -> void:
	var shifted_damage := run_result.duplicate(true)
	var shifted_transitions := _transition_events(shifted_damage)
	_set_state_value(
		shifted_transitions[0]["state_after"],
		"enemy_health",
		int(expected_initial["enemy_health"]),
	)
	_set_state_value(
		shifted_transitions[1]["state_before"],
		"enemy_health",
		int(expected_initial["enemy_health"]),
	)
	_expect(
		not _projection_accepts(shifted_damage, expected_initial, revision),
		"Content rejects damage moved to the wrong exchange transition",
	)

	var forged_mana := run_result.duplicate(true)
	var mana_transitions := _transition_events(forged_mana)
	for rows in [
		mana_transitions[0]["state_after"],
		mana_transitions[1]["state_before"],
		mana_transitions[1]["state_after"],
	]:
		_set_state_value(rows, "player_mana", 999)
	var mana_artifacts: Dictionary = forged_mana["artifacts"]
	var mana_snapshots: Array = mana_artifacts["snapshot-series"]["snapshots"]
	_set_state_value(mana_snapshots[-1]["values"], "player_mana", 999)
	_set_metric_value(
		mana_artifacts["metric-dataset"]["samples"],
		"player_resource_remaining",
		999,
	)
	_expect(
		not _projection_accepts(forged_mana, expected_initial, revision),
		"Content rejects resource changes that contradict the cast cost",
	)

	var extra_state := run_result.duplicate(true)
	var extra_transitions := _transition_events(extra_state)
	for rows in [
		extra_transitions[0]["state_after"],
		extra_transitions[1]["state_before"],
		extra_transitions[1]["state_after"],
	]:
		rows.append({"name": "runtime_debug", "value": 1})
	var extra_artifacts: Dictionary = extra_state["artifacts"]
	var extra_snapshots: Array = extra_artifacts["snapshot-series"]["snapshots"]
	extra_snapshots[-1]["values"].append({"name": "runtime_debug", "value": 1})
	_expect(
		not _projection_accepts(extra_state, expected_initial, revision),
		"Content rejects state outside the application-owned combat surface",
	)


func _projection_accepts(
	run_result: Dictionary,
	expected_initial: Dictionary,
	revision: String,
) -> bool:
	var exchange := CombatExchange.new()
	return exchange.admit_run_result(
		run_result, expected_initial, "mutation", revision
	).get("ok", false)


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


func _set_metric_value(
	samples: Array,
	metric: String,
	value: int,
) -> void:
	for sample in samples:
		if sample.get("metric") == metric:
			sample["value"] = value
			return
