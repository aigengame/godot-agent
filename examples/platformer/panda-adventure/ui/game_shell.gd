class_name GameShell
extends Node

## Thin composition root. UI depends downward on Content, binds the HUD's read
## source, observes the run result, and forwards retry intent.

const GameLogScript := preload("res://addons/game_log/game_log.gd")


func _ready() -> void:
	var gameplay := $Gameplay
	var hud := $Hud
	var end_screen := $EndScreen
	var player_bound := false
	if gameplay.has_method("player_node") and hud.has_method("bind"):
		hud.bind(gameplay.player_node())
		player_bound = true
	gameplay.run_ended.connect(end_screen.show_end)
	end_screen.retry_requested.connect(gameplay.retry)
	GameLogScript.emit("info", "game_shell_ready", {"player_bound": player_bound})
