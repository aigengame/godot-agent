extends Node

const GdaExecutionClient = preload(
	"res://addons/gda_balancing_client/gda_execution_client.gd"
)
const CombatCastController = preload(
	"res://content/combat_cast/combat_cast_controller.gd"
)
const CombatDuel = preload("res://systems/combat_duel.gd")

@onready var _view: Control = $CombatCastView

var _client: GdaExecutionClient
var _controller: CombatCastController
var _shutting_down := false


func _ready() -> void:
	get_tree().auto_accept_quit = false
	_client = GdaExecutionClient.new()
	_client.name = "GdaExecutionClient"
	add_child(_client)
	_controller = CombatCastController.new()
	_controller.name = "CombatCastController"
	add_child(_controller)
	_view.bind(_controller)
	_controller.configure(
		_client,
		_user_option("gda-balancing-executable"),
		CombatDuel.new(),
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
