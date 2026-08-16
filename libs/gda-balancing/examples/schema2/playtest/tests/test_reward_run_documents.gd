extends SceneTree

const RewardRunDocuments = preload(
	"res://content/reward_run/reward_run_documents.gd"
)

var _failures: Array[String] = []


func _init() -> void:
	var example_dir := ProjectSettings.globalize_path("res://").path_join(
		"../roguelike-reward-build"
	).simplify_path()
	var documents := RewardRunDocuments.new()
	var loaded: Dictionary = documents.load(
		example_dir.path_join("model-source.json"),
		example_dir.path_join("experiment.json"),
	)
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


func _expect(condition: bool, message: String) -> void:
	if not condition:
		_failures.append(message)


func _finish() -> void:
	if _failures.is_empty():
		print(JSON.stringify({"passed": 5, "status": "passed"}))
		quit(0)
		return
	for failure in _failures:
		push_error(failure)
	quit(1)
