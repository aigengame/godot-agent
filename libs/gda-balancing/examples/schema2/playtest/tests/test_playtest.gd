extends SceneTree

const PlaytestSession = preload("res://systems/playtest_session.gd")
const PlaytestFeedback = preload("res://systems/playtest_feedback.gd")
const RewardRun = preload("res://systems/reward_run.gd")
const RewardOutcomeSource = preload(
	"res://content/reward_run/reward_outcome_source.gd"
)

var _failures: Array[String] = []


func _init() -> void:
	var source := RewardOutcomeSource.new("res://generated/reward_cases.json")
	var trials: Array = [
		source.outcome_for({"trial_id": "trial-one"}),
		source.outcome_for({"trial_id": "trial-two"}),
	]
	_expect(source.last_error.is_empty(), "prepared cases load")
	_expect(not trials.any(func(trial): return trial.is_empty()), "two outcomes load")
	if not trials.any(func(trial): return trial.is_empty()):
		_test_session(trials)
		_test_feedback(trials)
		_test_reward_run(trials[0], 1)
		_test_reward_run(trials[1], 3)

	if _failures.is_empty():
		print(JSON.stringify({"passed": 4, "status": "passed"}))
		quit(0)
		return
	for failure in _failures:
		push_error(failure)
	quit(1)


func _test_session(trials: Array) -> void:
	var session := PlaytestSession.new()
	_expect(session.configure(trials), "session accepts prepared trials")
	var state := session.start()
	_expect(state["trial"]["id"] == "trial-one", "session starts Trial 1")
	state = session.finish_current_trial()
	_expect(state["trial"]["id"] == "trial-two", "session advances to Trial 2")
	state = session.finish_current_trial()
	_expect(state["complete"], "session ends after Trial 2")


func _test_feedback(trials: Array) -> void:
	var session := PlaytestSession.new()
	session.configure(trials)
	var feedback := PlaytestFeedback.new("user://reward_run_feedback_test.json")
	var result := feedback.save(
		{
			"change_clarity": "Very clear",
			"feedback_kind": "hitl-product-feedback",
			"notes": "Readable",
			"preference": "Trial 1",
			"stronger_reward": "Trial 1",
			"tracking_issue": 585,
		},
		session.trial_references(),
	)
	_expect(not result.is_empty(), "feedback is persisted")
	_expect(result.get("payload", {}).get("schema_version") == 1, "feedback is framed")
	_expect(
		result.get("payload", {}).get("feedback_kind") == "hitl-product-feedback",
		"feedback kind is explicit",
	)
	_expect(result.get("payload", {}).get("tracking_issue") == 585, "issue is explicit")


func _test_reward_run(trial: Dictionary, expected_reward_hits: int) -> void:
	var run := RewardRun.new()
	run.start(trial)
	for unused in 3:
		run.primary_action()
	_expect(run.snapshot()["phase"] == "reward_ready", "first target unlocks reward")
	run.primary_action()
	_expect(run.snapshot()["phase"] == "after_fight", "reward equips")
	for unused in expected_reward_hits:
		run.primary_action()
	_expect(run.snapshot()["phase"] == "run_complete", "reward clears second target")


func _expect(condition: bool, message: String) -> void:
	if not condition:
		_failures.append(message)
