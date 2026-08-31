extends Node

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const StatCompositionController = preload(
	"res://content/stat_composition/stat_composition_controller.gd"
)
const PlaytestExecutionCoordinator = preload(
	"res://content/playtest_execution_coordinator.gd"
)

@onready var _view: Control = $StatCompositionView

var _client: GdaExecutionClient
var _controller: StatCompositionController
var _execution: PlaytestExecutionCoordinator
var _shutting_down := false


func _ready() -> void:
	get_tree().auto_accept_quit = false
	_client = GdaExecutionClient.new()
	_client.name = "GdaExecutionClient"
	add_child(_client)
	_execution = PlaytestExecutionCoordinator.new()
	_execution.configure(_client, _user_option("gda-balancing-executable"))
	_controller = StatCompositionController.new()
	_controller.name = "StatCompositionController"
	add_child(_controller)
	_view.bind(_controller)
	_controller.configure(_execution)
	await _controller.start()


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST and not _shutting_down:
		_shutting_down = true
		call_deferred("_shutdown_and_quit")


func _shutdown_and_quit() -> void:
	if _controller != null:
		await _controller.shutdown()
	get_tree().quit()


func _user_option(name: String) -> String:
	var prefix := "--%s=" % name
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with(prefix):
			return argument.trim_prefix(prefix)
	return ""
