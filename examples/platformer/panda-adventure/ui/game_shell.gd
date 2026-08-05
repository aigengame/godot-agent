class_name GameShell
extends Node

## Thin composition root. UI depends downward on Content, binds the HUD's read
## source, observes the run result, and forwards retry intent.


func _ready() -> void:
	var gameplay := $Gameplay
	var hud := $Hud
	var end_screen := $EndScreen
	if gameplay.has_method("player_node") and hud.has_method("bind"):
		hud.bind(gameplay.player_node())
	gameplay.run_ended.connect(end_screen.show_end)
	end_screen.retry_requested.connect(gameplay.retry)
