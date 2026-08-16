extends RefCounted

signal state_changed(state: Dictionary)

enum Phase {
	BEFORE_FIGHT,
	REWARD_READY,
	AFTER_FIGHT,
	COMPLETE,
}

var _trial: Dictionary = {}
var _phase := Phase.BEFORE_FIGHT
var _power := 0
var _target_health := 0
var _target_max_health := 0
var _second_target_health := 0
var _hits := 0


func start(
	trial_id: String,
	reward: Dictionary,
	build: Dictionary,
	first_target_health: int,
	second_target_health: int,
) -> void:
	_trial = {
		"id": trial_id,
		"reward": reward.duplicate(true),
		"build": build.duplicate(true),
	}
	_phase = Phase.BEFORE_FIGHT
	_power = int(_trial["build"]["power_before"])
	_target_health = first_target_health
	_target_max_health = first_target_health
	_second_target_health = second_target_health
	_hits = 0
	state_changed.emit(snapshot())


func primary_action() -> void:
	match _phase:
		Phase.BEFORE_FIGHT, Phase.AFTER_FIGHT:
			_strike()
		Phase.REWARD_READY:
			_equip_reward()


func snapshot() -> Dictionary:
	return {
		"build": _trial.get("build", {}).duplicate(true),
		"hits": _hits,
		"phase": _phase_name(),
		"power": _power,
		"reward": _trial.get("reward", {}).duplicate(true),
		"target_health": _target_health,
		"target_max_health": _target_max_health,
		"title": _trial.get("title", ""),
		"trial_id": _trial.get("id", ""),
	}


func _strike() -> void:
	_hits += 1
	_target_health = maxi(0, _target_health - _power)
	if _target_health == 0:
		if _phase == Phase.BEFORE_FIGHT:
			_phase = Phase.REWARD_READY
		else:
			_phase = Phase.COMPLETE
	state_changed.emit(snapshot())


func _equip_reward() -> void:
	_power = int(_trial["build"]["power_after"])
	_target_health = _second_target_health
	_target_max_health = _second_target_health
	_phase = Phase.AFTER_FIGHT
	state_changed.emit(snapshot())


func _phase_name() -> String:
	match _phase:
		Phase.BEFORE_FIGHT:
			return "before_fight"
		Phase.REWARD_READY:
			return "reward_ready"
		Phase.AFTER_FIGHT:
			return "after_fight"
		Phase.COMPLETE:
			return "run_complete"
	return "unknown"
