extends SceneTree

const PlaytestSession = preload("res://systems/playtest_session.gd")
const RewardRun = preload("res://systems/reward_run.gd")
const RewardOutcomeSource = preload(
	"res://content/reward_run/reward_outcome_source.gd"
)

var _failures: Array[String] = []


func _init() -> void:
	var source := RewardOutcomeSource.new()
	var trials: Array = source.load_cases("res://generated/reward_cases.json")
	_expect(source.last_error.is_empty(), "prepared cases load")
	_expect(trials.size() == 2, "exactly two trials load")
	if trials.size() == 2:
		_test_session(trials)
		_test_reward_run(trials[0], 1)
		_test_reward_run(trials[1], 3)

	if _failures.is_empty():
		print(JSON.stringify({"passed": 3, "status": "passed"}))
		quit(0)
		return
	for failure in _failures:
		push_error(failure)
	quit(1)


func _test_session(trials: Array) -> void:
	var session := PlaytestSession.new()
	_expect(session.configure(trials), "session accepts prepared trials")
	_expect(session.begin()["id"] == "trial-one", "session starts Trial 1")
	_expect(session.advance()["id"] == "trial-two", "session advances to Trial 2")
	_expect(session.advance().is_empty(), "session ends after Trial 2")


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
