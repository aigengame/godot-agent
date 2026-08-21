class_name PeriodicEffectTimeline
extends RefCounted

signal state_changed(state: Dictionary)

var _timeline: Array = []
var _trial_kind := ""
var _cast_damage := 0
var _step := 0
var _complete := false


func start(gameplay: Dictionary) -> void:
	_timeline = gameplay.get("timeline", []).duplicate(true)
	_trial_kind = str(gameplay.get("trial_kind", ""))
	_cast_damage = int(gameplay.get("cast_damage", 0))
	_step = 0
	_complete = false
	state_changed.emit(snapshot())


func primary_action() -> void:
	if _timeline.is_empty() or _complete:
		return
	if _step + 1 < _timeline.size():
		_step += 1
	else:
		_complete = true
	state_changed.emit(snapshot())


func snapshot() -> Dictionary:
	if _timeline.is_empty():
		return {"phase": "empty"}
	var current: Dictionary = _timeline[_step]
	return {
		"cast_damage": _cast_damage,
		"damage": int(current.get("damage", 0)),
		"effect_active": bool(current.get("effect_active", false)),
		"health": int(current.get("health", 0)),
		"health_before": int(current.get("health_before", current.get("health", 0))),
		"lifecycle_phase": str(current.get("phase", "")),
		"phase": "trial_complete" if _complete else "timeline_step",
		"step": _step,
		"step_count": _timeline.size(),
		"trial_kind": _trial_kind,
	}
