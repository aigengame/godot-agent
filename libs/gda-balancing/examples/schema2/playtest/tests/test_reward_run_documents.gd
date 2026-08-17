extends "res://tests/playtest_test_case.gd"

const RewardRunDocuments = preload(
	"res://content/reward_run/reward_run_documents.gd"
)

func _init() -> void:
	super()
	var documents := RewardRunDocuments.new()
	var loaded: Dictionary = documents.load_maintained()
	_expect(loaded.get("ok", false), "maintained Reward Run documents load")
	if loaded.get("ok", false):
		_expect(
			loaded["reward_frequency"]
			== {"minimum": 0, "maximum": 90, "value": 5},
			"Rare reward frequency derives from maintained authorities",
		)
		var revised: Dictionary = documents.experiment_with_reward_frequency(2)
		_expect(revised.get("ok", false), "a complete later Experiment is created")
		if revised.get("ok", false):
			_expect(
				_rare_weight(revised["value"]) == 2,
				"later Experiment contains the player choice",
			)
			_expect(
				_rare_weight(loaded["experiment"]) == 5,
				"the admitted baseline remains immutable",
			)

	_finish()


func _rare_weight(experiment: Dictionary) -> int:
	for assignment in experiment["scenarios"][0]["assignments"]:
		if assignment["target"]["name"] == "rare_weight":
			return int(assignment["value"])
	return -1
