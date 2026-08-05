class_name GameShell
extends Node

## Thin composition root. UI depends downward on Content, binds the HUD's read
## source, observes the run result, and owns composition-scene lifecycle. A
## missing Player is a composition error: abort all shell wiring instead of
## continuing with a partially working UI.

const GameLogScript := preload("res://addons/game_log/game_log.gd")

var _gameplay: Node


func _ready() -> void:
	_gameplay = $Gameplay
	var hud := $Hud
	var end_screen := $EndScreen
	var player = _gameplay.player_node()
	if not is_instance_valid(player):
		push_error("GameShell: Gameplay did not provide a valid Player.")
		return
	hud.bind(player)
	_gameplay.run_ended.connect(end_screen.show_end)
	end_screen.retry_requested.connect(_on_retry_requested)
	GameLogScript.emit("info", "game_shell_ready", {})


## Ask Content to accept the application intent, then reload the UI-owned
## composition scene only when the run is in an End state.
func _on_retry_requested() -> void:
	if _gameplay.retry():
		get_tree().reload_current_scene()
