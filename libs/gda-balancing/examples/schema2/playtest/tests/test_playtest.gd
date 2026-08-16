extends SceneTree

const RewardFeedbackRecorder = preload(
	"res://content/reward_run/reward_feedback_recorder.gd"
)
const RewardRun = preload("res://systems/reward_run.gd")
const PlaytestPreferences = preload("res://ui/playtest_preferences.gd")

var _failures: Array[String] = []


func _init() -> void:
	var rare_trial := _trial("trial-one", "volatile_crown", "rare", 90, 5)
	var common_trial := _trial("trial-two", "steady_guard", "common", 30, 2)
	_test_feedback([rare_trial, common_trial])
	_test_reward_run(rare_trial, 1)
	_test_reward_run(common_trial, 3)
	_test_player_preferences()

	if _failures.is_empty():
		print(JSON.stringify({"passed": 4, "status": "passed"}))
		quit(0)
		return
	for failure in _failures:
		push_error(failure)
	quit(1)


func _trial(
	id: String,
	reward_key: String,
	rarity: String,
	power_after: int,
	reward_frequency: int,
) -> Dictionary:
	return {
		"id": id,
		"reward_frequency": reward_frequency,
		"reward": {"key": reward_key, "rarity": rarity},
		"build": {
			"previous_item": "starter_blade",
			"equipped_item": reward_key,
			"power_before": 10,
			"power_after": power_after,
		},
		"provenance": {
			"experiment_identity": "sha256:experiment-%s" % id,
			"event_trace_identity": "sha256:trace-%s" % id,
		},
	}


func _test_player_preferences() -> void:
	var preferences := PlaytestPreferences.new()
	preferences.install_translations()
	_expect(
		preferences.default_resolution_id() == "2k",
		"2K is the default resolution",
	)
	_expect(
		preferences.resolution_size("1080p") == Vector2i(1920, 1080),
		"1080p resolution is available",
	)
	_expect(
		preferences.resolution_size("2k") == Vector2i(2560, 1440),
		"2K resolution is available",
	)
	_expect(
		preferences.resolution_size("4k") == Vector2i(3840, 2160),
		"4K resolution is available",
	)
	_expect(preferences.default_locale() == "en", "English is the default locale")
	_expect(preferences.supports_locale("zh_CN"), "Chinese locale is available")
	for resolution_id in ["1080p", "2k", "4k"]:
		_expect(
			preferences.apply_resolution(get_root(), resolution_id),
			"%s resolution can be applied" % resolution_id,
		)
		_expect(
			get_root().size == preferences.resolution_size(resolution_id),
			"%s changes the window size" % resolution_id,
		)
	preferences.apply_resolution(get_root(), preferences.default_resolution_id())
	TranslationServer.set_locale("zh_CN")
	_expect(
		TranslationServer.translate("SETTINGS_RESOLUTION") == "分辨率",
		"Chinese translation catalog is loaded",
	)
	TranslationServer.set_locale("en")


func _test_feedback(trials: Array[Dictionary]) -> void:
	var feedback := RewardFeedbackRecorder.new(
		"user://reward_run_feedback_test.json"
	)
	var result := feedback.save(
		{
			"change_clarity": "Very clear",
			"feedback_kind": "hitl-product-feedback",
			"notes": "Readable",
			"preference": "Trial 1",
			"stronger_reward": "Trial 1",
			"tracking_issue": 585,
		},
		trials,
	)
	_expect(not result.is_empty(), "feedback is persisted")
	_expect(result.get("payload", {}).get("schema_version") == 1, "feedback is framed")
	_expect(
		result.get("payload", {}).get("feedback_kind") == "hitl-product-feedback",
		"feedback kind is explicit",
	)
	_expect(result.get("payload", {}).get("tracking_issue") == 585, "issue is explicit")
	_expect(
		result.get("payload", {}).get("trials", [])[1].get("reward_frequency") == 2,
		"feedback retains the player's live frequency",
	)


func _test_reward_run(trial: Dictionary, expected_reward_hits: int) -> void:
	var run := RewardRun.new()
	run.start(trial["id"], trial["reward"], trial["build"], 30, 90)
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
