class_name CombatDuel
extends RefCounted

signal state_changed(state: Dictionary)

enum Phase {
	BEFORE_EXCHANGE,
	PLAYER_RESOLVED,
	ENEMY_RESOLVED,
	COMPLETE,
}

var _exchange: Dictionary = {}
var _phase := Phase.BEFORE_EXCHANGE
var _combatants: Dictionary = {}


func start(exchange: Dictionary) -> void:
	_exchange = exchange.duplicate(true)
	_phase = Phase.BEFORE_EXCHANGE
	_combatants = _exchange.get("initial", {}).duplicate(true)
	state_changed.emit(snapshot())


func primary_action() -> void:
	match _phase:
		Phase.BEFORE_EXCHANGE:
			_combatants = _exchange.get("after_player", {}).duplicate(true)
			_phase = Phase.PLAYER_RESOLVED
		Phase.PLAYER_RESOLVED:
			_combatants = _exchange.get("terminal", {}).duplicate(true)
			_phase = Phase.ENEMY_RESOLVED
		Phase.ENEMY_RESOLVED:
			_phase = Phase.COMPLETE
	state_changed.emit(snapshot())


func snapshot() -> Dictionary:
	return {
		"combatants": _combatants.duplicate(true),
		"damage": _exchange.get("damage", {}).duplicate(true),
		"mana_cost": _exchange.get("mana_cost", {}).duplicate(true),
		"phase": _phase_name(),
	}


func _phase_name() -> String:
	match _phase:
		Phase.BEFORE_EXCHANGE:
			return "before_exchange"
		Phase.PLAYER_RESOLVED:
			return "player_resolved"
		Phase.ENEMY_RESOLVED:
			return "enemy_resolved"
		Phase.COMPLETE:
			return "exchange_complete"
	return "unknown"
