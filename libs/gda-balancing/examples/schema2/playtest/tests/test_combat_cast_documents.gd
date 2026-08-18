extends "res://tests/playtest_test_case.gd"

const CombatCastDocuments = preload(
	"res://content/combat_cast/combat_cast_documents.gd"
)


func _init() -> void:
	super()
	var documents := CombatCastDocuments.new()
	var loaded: Dictionary = documents.load_maintained()
	_expect(loaded.get("ok", false), "maintained Combat documents load")
	if loaded.get("ok", false):
		var state: Dictionary = loaded["combat_state"]
		var player := documents.experiment_for_action(
			state, "player", "efficient", "strong", 1
		)
		_expect(player.get("ok", false), "Content authors a complete player action")
		if player.get("ok", false):
			var experiment: Dictionary = player["value"]
			_expect(
				experiment["scenarios"][0]["event_plan"].size() == 1
				and experiment["scenarios"][0]["event_plan"][0]["root_event_ref"]
				== "player-attacks-enemy",
				"player revision selects only the player action",
			)
			_expect(_assignment(experiment, "player_action_cost") == 6, "efficient cast costs 6 MP")
			_expect(_assignment(experiment, "player_base_damage") == 34, "efficient cast deals less damage")
			_expect(
				_metric_ids(experiment)
				== ["enemy_health_remaining", "player_resource_remaining"],
				"player revision keeps only outcome-independent state metrics",
			)
		var enemy := documents.experiment_for_action(
			state, "enemy", "efficient", "strong", 2
		)
		_expect(enemy.get("ok", false), "Content authors a complete enemy action")
		if enemy.get("ok", false):
			_expect(
				_assignment(enemy["value"], "enemy_base_damage") == 32,
				"strong rival changes the authored enemy damage input",
			)
	_finish()


func _assignment(experiment: Dictionary, name: String) -> int:
	for assignment in experiment["scenarios"][0]["assignments"]:
		if assignment["target"]["name"] == name:
			return int(assignment["value"])
	return -1


func _metric_ids(experiment: Dictionary) -> Array:
	return experiment["metrics"].map(func(metric: Dictionary) -> String: return metric["id"])
