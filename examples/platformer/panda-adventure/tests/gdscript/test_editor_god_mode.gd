extends SceneTree

## Regression for the #476 review's god-mode correctness finding: the debug
## palette's god-mode must PREVENT death, not paper over it after the fact.
##
## Boots the real game (main.tscn), then drives the Player's set_debug_invulnerable
## API — the exact seam the palette's _process drives — and proves a LETHAL hit is
## refused at the source (take_hit), so the death latch never fires:
##
##   god-mode ON  -> a hit with attack far above the Player's HP does NO damage and
##                   does NOT kill (the run cannot end via game_lost).
##   god-mode OFF -> the SAME lethal hit now kills, proving god-mode did the work.
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_editor_god_mode.gd
## Read-only (no save/derive). Prints "GOD_MODE: PASS" + quit(0) on success, else
## push_error + quit(1). Runs from source (not a template build), so the take_hit
## debug gate is active — exactly the dev-machine editor context god-mode targets.

const MainScene := preload("res://scenes/main.tscn")
const StatsConfigScript := preload("res://src/resources/stats_config.gd")


func _fail(msg: String) -> void:
	push_error("GOD_MODE: " + msg)
	quit(1)


func _init() -> void:
	var main := MainScene.instantiate()
	root.add_child(main)
	# Two frames: the level + Player _ready run and the Player's stats initialize.
	await process_frame
	await process_frame

	var player := get_first_node_in_group("player")
	if player == null:
		_fail("player not found in the running game")
		return
	if player._dead:
		_fail("player already dead at boot")
		return

	# A lethal attacker: attack far above the Player's HP, so the mitigated damage
	# (attack * scale - defense * scale) exceeds max_hp in one hit.
	var attacker := StatsConfigScript.new()
	attacker.max_hp = 1.0
	attacker.max_mp = 0.0
	attacker.attack = 1_000_000.0
	attacker.defense = 0.0

	# --- god-mode ON: the lethal hit is refused; the Player survives untouched.
	player.set_debug_invulnerable(true)
	var hp_before: float = player._stats.hp
	player.take_hit(attacker)
	if player._dead:
		_fail("player died despite god-mode")
		return
	if player._stats.hp != hp_before:
		_fail("god-mode still applied damage: %s -> %s" % [hp_before, player._stats.hp])
		return

	# --- god-mode OFF: the SAME lethal hit now kills — god-mode was the difference.
	player.set_debug_invulnerable(false)
	player.take_hit(attacker)
	if not player._dead:
		_fail("lethal hit did not kill with god-mode off")
		return

	print("GOD_MODE: PASS")
	quit(0)
