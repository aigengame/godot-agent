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
