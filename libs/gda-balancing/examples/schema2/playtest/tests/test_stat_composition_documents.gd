extends "res://tests/playtest_test_case.gd"

const StatCompositionDocuments = preload(
	"res://content/stat_composition/stat_composition_documents.gd"
)


func _init() -> void:
	super()
	var documents := StatCompositionDocuments.new()
	var loaded: Dictionary = documents.load_maintained()
	_expect(loaded.get("ok", false), "maintained Stat Composition documents load")
	if loaded.get("ok", false):
		_expect(
			loaded["settings"]
			== {
				"buff_enabled": {"minimum": 0, "maximum": 1, "value": 1},
				"level": {"minimum": 1, "maximum": 10, "value": 3},
				"weapon_damage_bonus": {"minimum": 0, "maximum": 20, "value": 8},
			},
			"player controls use maintained bounds and defaults",
		)
		_expect(
			loaded["rules"]
			== {
				"base_damage": 20,
				"buff_percent": 25,
				"damage_per_level": 4,
				"maximum_damage": 60,
			},
			"visible rules come from the maintained Experiment",
		)
		var authored := documents.experiment_for_attack(
			70,
			{"buff_enabled": 0, "level": 6, "weapon_damage_bonus": 18},
			2,
		)
		_expect(authored.get("ok", false), "Content authors a complete attack revision")
		if authored.get("ok", false):
			var experiment: Dictionary = authored["value"]
			_expect(_assignment(experiment, "target_health") == 70, "current HP reaches the revision")
			_expect(_assignment(experiment, "level") == 6, "Level reaches the revision")
			_expect(
				_assignment(experiment, "weapon_damage_bonus") == 18,
				"Weapon Damage Bonus reaches the revision",
			)
			_expect(_assignment(experiment, "buff_enabled") == 0, "the Buff switch reaches the revision")
			_expect(
				experiment["metrics"].size() == loaded["experiment"]["metrics"].size(),
				"the complete maintained observation contract is retained",
			)
	_finish()


func _assignment(experiment: Dictionary, name: String) -> int:
	for assignment in experiment["scenarios"][0]["assignments"]:
		if assignment["target"]["name"] == name:
			return int(assignment["value"])
	return -1
