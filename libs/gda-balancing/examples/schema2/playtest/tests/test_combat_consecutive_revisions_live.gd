extends "res://tests/playtest_test_case.gd"

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const CombatAction = preload("res://content/combat_cast/combat_action.gd")
const CombatCastDocuments = preload(
	"res://content/combat_cast/combat_cast_documents.gd"
)


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var documents := CombatCastDocuments.new()
	var loaded: Dictionary = documents.load_maintained()
	_expect(loaded.get("ok", false), "maintained Combat documents load")
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
		loaded["model_source"], loaded["experiment"]
	)
	_expect(created.get("ok", false), "Combat session admits maintained documents")
	if not created.get("ok", false):
		await client.shutdown()
		_finish()
		return

	var state: Dictionary = loaded["combat_state"]
	var first := await _run_action(
		client, documents, created["session"], state, "player", 1, loaded["defeat_threshold"]
	)
	_expect(first.get("ok", false), "first player action validates")
	if first.get("ok", false):
		_expect(first["terminal"]["enemy_health"] == 63, "first action commits damage")
		state = first["terminal"]
	var second := await _run_action(
		client, documents, created["session"], state, "enemy", 2, loaded["defeat_threshold"]
	)
	_expect(second.get("ok", false), "enemy action uses the prior committed state")
	if second.get("ok", false):
		_expect(second["terminal"]["player_health"] == 86, "enemy action commits damage")
		_expect(
			second["revision"] != first.get("revision", ""),
			"complete actions produce distinct exact revisions",
		)

	await client.delete_session(created["session"])
	await client.shutdown()
	client.queue_free()
	_finish()


func _run_action(
	client: Node,
	documents: CombatCastDocuments,
	session: String,
	state: Dictionary,
	actor: String,
	index: int,
	defeat_threshold: int,
) -> Dictionary:
	var authored := documents.experiment_for_action(
		state, actor, "balanced", "normal", index
	)
	if not authored.get("ok", false):
		return authored
	var admitted: Dictionary = await client.admit_revision(session, authored["value"])
	if not admitted.get("ok", false):
		return admitted
	var run: Dictionary = await client.run_revision(session, admitted["revision"])
	if not run.get("ok", false):
		return run
	if index == 1:
		_test_projection_refusals(
			run["value"], state, actor, admitted["revision"], defeat_threshold
		)
	var action := CombatAction.new()
	var result := action.admit_run_result(
		run["value"], state, actor, admitted["revision"], defeat_threshold
	)
	if not result.get("ok", false):
		return result
	return {
		"ok": true,
		"revision": admitted["revision"],
		"terminal": action.terminal_state(),
	}


func _test_projection_refusals(
	run_result: Dictionary,
	state: Dictionary,
	actor: String,
	revision: String,
	defeat_threshold: int,
) -> void:
	var forged_outcome := run_result.duplicate(true)
	var event := _transition(forged_outcome)
	event["outcome"] = {"id": "target-defeated", "kind": "success"}
	_expect(
		not _projection_accepts(
			forged_outcome, state, actor, revision, defeat_threshold
		),
		"Content rejects a terminal outcome that contradicts target state",
	)
	var forged_damage := run_result.duplicate(true)
	var forged_event := _transition(forged_damage)
	_set_state_value(forged_event["state_after"], "enemy_health", 100)
	var snapshots: Array = forged_damage["artifacts"]["snapshot-series"]["snapshots"]
	_set_state_value(snapshots[-1]["values"], "enemy_health", 100)
	_set_metric_value(
		forged_damage["artifacts"]["metric-dataset"]["samples"],
		"enemy_health_remaining",
		100,
	)
	_expect(
		not _projection_accepts(forged_damage, state, actor, revision, defeat_threshold),
		"Content rejects state that contradicts the damage fact",
	)


func _projection_accepts(
	run_result: Dictionary,
	state: Dictionary,
	actor: String,
	revision: String,
	defeat_threshold: int,
) -> bool:
	var action := CombatAction.new()
	return action.admit_run_result(
		run_result, state, actor, revision, defeat_threshold
	).get("ok", false)


func _transition(run_result: Dictionary) -> Dictionary:
	for event in run_result["artifacts"]["event-trace"]["events"]:
		if event.get("ordering_key", {}).get("phase") == "transition":
			return event
	return {}


func _set_state_value(rows: Array, name: String, value: int) -> void:
	for row in rows:
		if row.get("name") == name:
			row["value"] = value
			return


func _set_metric_value(samples: Array, metric: String, value: int) -> void:
	for sample in samples:
		if sample.get("metric") == metric:
			sample["value"] = value
			return
