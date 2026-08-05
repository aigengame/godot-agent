class_name WaveSystem
extends RefCounted

## The pure Wave-progression decision for S5 (gADR-0005): one enemy death
## folded into the current wave's state. Static, deterministic, and
## node/clock-free — counts in, decision out (the CombatSystem/EnemyAI
## decision shape, gADR-0001/gADR-0003) — so the logic seam exercises the
## advance-on-clear rule headless at ANY wave count (the no-hardcoded-count
## guarantee lives here: `wave_count` is always a parameter, read from the
## Wave schedule's waves.size() by the caller). The LevelController
## orchestrates: it owns the live counts, spawns the next wave on `advance`,
## and logs the wave_started/wave_cleared/all_waves_cleared records.


## Resolve one enemy death against the current wave: `alive_before` live
## enemies of wave `wave_index` (0-based) out of `wave_count` scheduled waves.
## Returns the full decision as a Dictionary:
## - "alive": the wave's remaining live count (never below 0);
## - "cleared": this death emptied the wave;
## - "advance": cleared AND a next wave exists — the caller spawns it;
## - "all_cleared": cleared AND this was the final wave — the schedule is done.
static func resolve_death(alive_before: int, wave_index: int, wave_count: int) -> Dictionary:
	var alive := maxi(alive_before - 1, 0)
	var cleared := alive == 0
	var has_next := wave_index + 1 < wave_count
	return {
		"alive": alive,
		"cleared": cleared,
		"advance": cleared and has_next,
		"all_cleared": cleared and not has_next,
	}
