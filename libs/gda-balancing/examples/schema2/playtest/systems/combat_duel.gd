class_name CombatDuel
extends RefCounted

signal state_changed(state: Dictionary)

var _actor := ""
var _combatants: Dictionary = {}
var _damage := 0
var _mana_cost := 0
var _phase := "ready"


func start(initial: Dictionary) -> void:
	_actor = ""
	_combatants = initial.duplicate(true)
	_damage = 0
	_mana_cost = 0
	_phase = "ready"
	state_changed.emit(snapshot())


func present_action(action: Dictionary, terminal_phase: String = "") -> void:
	_actor = str(action.get("actor", ""))
	_combatants = action.get("terminal", {}).duplicate(true)
	_damage = int(action.get("damage", 0))
	_mana_cost = int(action.get("mana_cost", 0))
	if terminal_phase in ["victory", "defeat"]:
		_phase = terminal_phase
	else:
		_phase = "player_resolved" if _actor == "player" else "enemy_resolved"
	state_changed.emit(snapshot())


func snapshot() -> Dictionary:
	return {
		"actor": _actor,
		"combatants": _combatants.duplicate(true),
		"damage": _damage,
		"mana_cost": _mana_cost,
		"phase": _phase,
	}
