extends Node

const RewardOutcomeSource = preload("res://content/reward_run/reward_outcome_source.gd")
const RewardRunController = preload("res://content/reward_run/reward_run_controller.gd")

@onready var _view: Control = $RewardRunView


func _ready() -> void:
	var source := RewardOutcomeSource.new()
	var controller := RewardRunController.new()
	controller.name = "RewardRunController"
	add_child(controller)
	_view.bind(controller)
	if not controller.configure(source, "res://generated/reward_cases.json"):
		_view.show_error(source.last_error)
		return
	controller.start()
