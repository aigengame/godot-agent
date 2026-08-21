extends Node

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const PeriodicEffectController = preload(
	"res://content/periodic_effect/periodic_effect_controller.gd"
)
const PeriodicEffectTimeline = preload(
	"res://systems/periodic_effect_timeline.gd"
)

@onready var _view: Control = $PeriodicEffectView

var _client: GdaExecutionClient
var _controller: PeriodicEffectController
var _shutting_down := false


func _ready() -> void:
	get_tree().auto_accept_quit = false
	_client = GdaExecutionClient.new()
	_client.name = "GdaExecutionClient"
	add_child(_client)
	_controller = PeriodicEffectController.new()
	_controller.name = "PeriodicEffectController"
	add_child(_controller)
	_view.bind(_controller)
	_controller.configure(
		_client,
		_user_option("gda-balancing-executable"),
		PeriodicEffectTimeline.new(),
	)
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
