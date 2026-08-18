extends "res://tests/playtest_test_case.gd"

const PlaytestFeedbackFile = preload(
	"res://addons/playtest_feedback_file/playtest_feedback_file.gd"
)
const RewardRun = preload("res://systems/reward_run.gd")
const CombatDuel = preload("res://systems/combat_duel.gd")
const PeriodicEffectTimeline = preload("res://systems/periodic_effect_timeline.gd")
const PlaytestPreferences = preload("res://ui/playtest_preferences.gd")

func _init() -> void:
	super()
	var rare_trial := _trial("trial-one", "volatile_crown", "rare", 90, 5)
	var common_trial := _trial("trial-two", "steady_guard", "common", 30, 2)
	_test_feedback([rare_trial, common_trial])
	_test_reward_run(rare_trial, 1)
	_test_reward_run(common_trial, 3)
	_test_combat_duel()
	_test_periodic_effect_timeline()
	_test_player_preferences()
	_finish()


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
	var feedback := PlaytestFeedbackFile.new()
	var result := feedback.save(
		"user://reward_run_feedback_test.json",
		{
			"change_clarity": "Very clear",
			"created_at": "2026-08-17T00:00:00Z",
			"feedback_kind": "hitl-product-feedback",
			"notes": "Readable",
			"preference": "Trial 1",
			"schema_version": 1,
			"stronger_reward": "Trial 1",
			"tracking_issue": 585,
			"trials": trials,
		},
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
	run.start(trial["reward"], trial["build"], 30, 90)
	for unused in 3:
		run.primary_action()
	_expect(run.snapshot()["phase"] == "reward_ready", "first target unlocks reward")
	run.primary_action()
	_expect(run.snapshot()["phase"] == "after_fight", "reward equips")
	for unused in expected_reward_hits:
		run.primary_action()
	_expect(run.snapshot()["phase"] == "run_complete", "reward clears second target")


func _test_combat_duel() -> void:
	var duel := CombatDuel.new()
	duel.start(
		{
			"enemy_health": 100,
			"enemy_mana": 30,
			"player_health": 100,
			"player_mana": 35,
		}
	)
	_expect(duel.snapshot()["phase"] == "ready", "duel starts ready")
	duel.present_action(
		{
			"actor": "player",
			"damage": 37,
			"mana_cost": 9,
			"terminal": {
				"enemy_health": 63,
				"enemy_mana": 30,
				"player_health": 100,
				"player_mana": 26,
			},
		}
	)
	_expect(duel.snapshot()["mana_cost"] == 9, "duel presents the validated mana cost")
	_expect(
		duel.snapshot()["combatants"]["enemy_health"] == 63,
		"duel presents the validated player result",
	)
	duel.present_action(
		{
			"actor": "enemy",
			"damage": 14,
			"mana_cost": 7,
			"terminal": {
				"enemy_health": 63,
				"enemy_mana": 23,
				"player_health": 86,
				"player_mana": 26,
			},
		}
	)
	_expect(
		duel.snapshot()["combatants"]["player_health"] == 86,
		"duel presents the validated enemy result",
	)
	_expect(duel.snapshot()["phase"] == "enemy_resolved", "duel continues")
	_expect(not duel.snapshot().has("provenance"), "duel owns gameplay values only")


func _test_periodic_effect_timeline() -> void:
	var timeline := PeriodicEffectTimeline.new()
	timeline.start(
		{
			"timeline": [
				{"damage": 0, "effect_active": true, "health": 100, "phase": "apply"},
				{"damage": 15, "effect_active": true, "health": 85, "phase": "pulse"},
				{"damage": 10, "effect_active": true, "health": 75, "phase": "attack"},
				{"damage": 0, "effect_active": true, "health": 75, "phase": "pulse"},
				{"damage": 0, "effect_active": false, "health": 75, "phase": "expire"},
			],
			"trial_kind": "reactive",
		}
	)
	_expect(timeline.snapshot()["lifecycle_phase"] == "apply", "Effect starts at apply")
	for expected in ["pulse", "attack", "pulse", "expire"]:
		timeline.primary_action()
		_expect(
			timeline.snapshot()["lifecycle_phase"] == expected,
			"Effect presents the validated %s step" % expected,
		)
	timeline.primary_action()
	_expect(timeline.snapshot()["phase"] == "trial_complete", "Effect trial completes")
	_expect(
		not timeline.snapshot().has("provenance"),
		"Effect timeline owns gameplay values only",
	)
