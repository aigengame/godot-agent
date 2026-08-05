class_name GrowthSystem
extends RefCounted

## The pure leveling decision for S6b (gADR-0006): the Player's level as a
## FUNCTION of accumulated EXP against the data-driven leveling curve.
## Static, deterministic, and node/clock-free (the CombatSystem/WaveSystem
## decision shape, gADR-0001) — totals in, level out — so the logic seam
## exercises the curve headless at ANY curve length (the no-hardcoded-count
## guarantee: the curve is always a parameter, read from the derived
## ProgressionConfig by the caller). The PlayerController orchestrates: it
## re-resolves after each Kill reward, detects the old->new edge, logs
## level_up, and plays the flash tween.


## Resolve the level implied by `exp_points` total EXP against `level_curve`
## (cumulative EXP thresholds, strictly increasing — the builder's semantic
## gate): level 1 is the start, and each threshold reached is one level-up,
## so the level is 1 + the thresholds crossed and the MAX level is
## level_curve.size() + 1 (config, never code). Deriving from the TOTAL —
## rather than folding per-gain — makes one big reward worth several
## thresholds a multi-level-up for free, and re-resolution idempotent.
static func resolve_level(exp_points: float, level_curve: Array) -> int:
	var level := 1
	for threshold in level_curve:
		if exp_points >= float(threshold):
			level += 1
	return level
