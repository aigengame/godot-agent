extends "res://tests/playtest_test_case.gd"

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const RewardRunDocuments = preload(
	"res://content/reward_run/reward_run_documents.gd"
)
const RewardTrial = preload("res://content/reward_run/reward_trial.gd")

func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var executable := OS.get_environment("GDA_BALANCING_EXECUTABLE")
	var example_dir := ProjectSettings.globalize_path("res://").path_join(
		"../roguelike-reward-build"
	).simplify_path()
	var documents := RewardRunDocuments.new()
	var loaded: Dictionary = documents.load(
		example_dir.path_join("model-source.json"),
		example_dir.path_join("experiment.json"),
	)
	_expect(loaded.get("ok", false), "maintained documents load")
	if not loaded.get("ok", false) or executable.is_empty():
		_finish()
		return

	var client := GdaExecutionClient.new()
	get_root().add_child(client)
	var started: Dictionary = await client.start(executable)
	_expect(started.get("ok", false), "service starts")
	if not started.get("ok", false):
		client.queue_free()
		_finish()
		return
	var created: Dictionary = await client.create_session(
		loaded["model_source"],
		loaded["experiment"],
	)
	_expect(created.get("ok", false), "session admits maintained authorities")
	if not created.get("ok", false):
		await client.shutdown()
		client.queue_free()
		_finish()
		return

	var baseline: Dictionary = await _live_trial(
		client, documents, created["session"], 5
	)
	var tuned: Dictionary = await _live_trial(
		client, documents, created["session"], 2
	)
	_expect(baseline.get("ok", false), "baseline live trial projects")
	_expect(tuned.get("ok", false), "later live trial projects")
	if baseline.get("ok", false) and tuned.get("ok", false):
		_expect(
			baseline["revision"] != tuned["revision"],
			"different complete Experiments have different exact revisions",
		)
		_expect(
			baseline["trial"]["reward"] == {
				"key": "volatile_crown", "rarity": "rare"
			},
			"baseline projects the rare reward",
		)
		_expect(
			baseline["trial"]["build"]["power_after"] == 90,
			"baseline projects the stronger build",
		)
		_expect(
			tuned["trial"]["reward"] == {
				"key": "steady_guard", "rarity": "common"
			},
			"later revision projects the common reward",
		)
		_expect(
			tuned["trial"]["build"] == {
				"previous_item": "starter_blade",
				"equipped_item": "steady_guard",
				"power_before": 10,
				"power_after": 30,
			},
			"later revision projects the complete build replacement",
		)
		_expect(
			baseline["gameplay"].size() == 2
			and baseline["gameplay"].has("reward")
			and baseline["gameplay"].has("build"),
			"gameplay projection excludes revision and provenance",
		)
		_expect(
			not baseline["feedback"].has("revision")
			and baseline["feedback"].has("provenance"),
			"feedback projection keeps opaque provenance without the revision handle",
		)
		var contradictory: Dictionary = baseline["run_result"].duplicate(true)
		_mutate_selected_reward(contradictory, "contradictory_reward")
		var contradictory_trial := RewardTrial.new()
		var rejected: Dictionary = contradictory_trial.admit_run_result(
			contradictory,
			5,
			"contradictory-trial",
			"sha256:contradictory-revision",
		)
		_expect(
			not rejected.get("ok", false)
			and rejected.get("detail") == "selected_reward_mismatch",
			"Reward Trial rejects contradictory reward and build artifacts",
		)

	await client.delete_session(created["session"])
	await client.shutdown()
	client.queue_free()
	_finish()


func _live_trial(
	client,
	documents,
	session: String,
	reward_frequency: int,
) -> Dictionary:
	var revised: Dictionary = documents.experiment_with_reward_frequency(
		reward_frequency
	)
	if not revised.get("ok", false):
		return revised
	var admitted: Dictionary = await client.admit_revision(session, revised["value"])
	if not admitted.get("ok", false):
		return admitted
	var run: Dictionary = await client.run_revision(session, admitted["revision"])
	if not run.get("ok", false):
		return run
	var trial := RewardTrial.new()
	var projected: Dictionary = trial.admit_run_result(
		run["value"],
		reward_frequency,
		"trial-%d" % reward_frequency,
		admitted["revision"],
	)
	if not projected.get("ok", false):
		return projected
	return {
		"ok": true,
		"revision": admitted["revision"],
		"trial": trial.snapshot(),
		"gameplay": trial.gameplay_values(),
		"feedback": trial.feedback_record(),
		"run_result": run["value"],
	}


func _mutate_selected_reward(run_result: Dictionary, replacement: String) -> void:
	var trace: Dictionary = run_result["artifacts"]["event-trace"]
	for event in trace["events"]:
		if event.get("operation") != "game.generation.select-reward-v1":
			continue
		for fact in event["facts"]:
			if fact.get("name") == "reward_result":
				fact["value"]["value"]["selected"]["key"] = replacement
				return
