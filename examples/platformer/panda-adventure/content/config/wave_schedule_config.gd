class_name WaveScheduleConfig
extends Resource

## The Wave schedule (gADR-0005): the ordered, data-driven list of Waves the
## level plays through. Each element of `waves` is a Dictionary
## {"spawns": Array} whose spawns are gADR-0003 Spawn Roster entries
## ({"kind": String, "name": String, "position": Vector2}) referencing an
## Enemy Kind by its enemies_config.json key. The wave COUNT is waves.size()
## — config, never code. `spawn_squash`/`spawn_tween_duration` are the
## spawn-telegraph tween numbers the spawner hands each spawned enemy.
##
## This Resource is a DERIVED artifact: regenerated from the authoritative
## content/data/json/enemies_config.json `waves` array by scripts/build_config.py into
## content/data/generated/wave_schedule.tres. Never hand-edit it (gADR-0000). It
## replaced S4's EnemyRosterConfig/enemy_roster.tres — the old boot roster is
## Wave 1 of this schedule.

@export var spawn_squash: Vector2
@export var spawn_tween_duration: float
@export var waves: Array
