extends SceneTree

## Logic seam (b) for S5: exercise the PURE Wave-progression decision headless
## — WaveSystem.resolve_death (gADR-0005) — by folding full schedules through
## it at wave counts 3, 4, AND 5 (the issue-#334 no-hardcoded-count proof:
## the same rule must play any schedule length, four is only the demo's data).
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_waves_logic.gd
##
## preload() the script (a headless runtime has no editor-generated
## global_script_class_cache), fold synthetic per-wave spawn counts, and
## assert every intermediate and boundary decision. Prints "LOGIC_SEAM: PASS"
## + quit(0) on success, else push_error + quit(1).

const WaveSystemScript := preload("res://systems/wave_system.gd")

# Per-wave spawn counts to slice per tested wave count: mixed sizes (single
# spawns, a swarm, an empty-tail guard is impossible — the schema requires at
# least one spawn per wave, so 1 is the smallest wave).
const SPAWN_COUNTS := [1, 3, 2, 1, 4]

# The wave counts under test: below, at, and above the demo default of 4.
const WAVE_COUNTS := [3, 4, 5]


func _fail(msg: String) -> void:
	push_error("LOGIC_SEAM: " + msg)
	quit(1)


## Fold one whole schedule of `wave_count` waves through resolve_death,
## asserting every decision along the way. Returns false after _fail.
func _fold_schedule(wave_count: int) -> bool:
	var advances := 0
	var all_cleared_count := 0
	for wave_index in range(wave_count):
		var alive: int = SPAWN_COUNTS[wave_index]
		while alive > 0:
			var decision: Dictionary = WaveSystemScript.resolve_death(
				alive, wave_index, wave_count
			)
			if decision["alive"] != alive - 1:
				_fail(
					"count %d wave %d: alive %d should decrement to %d, got %s"
					% [wave_count, wave_index, alive, alive - 1, decision["alive"]]
				)
				return false
			var expect_cleared := alive == 1
			if decision["cleared"] != expect_cleared:
				_fail(
					"count %d wave %d: cleared should be %s at alive_before %d"
					% [wave_count, wave_index, expect_cleared, alive]
				)
				return false
			var is_final := wave_index == wave_count - 1
			if decision["advance"] != (expect_cleared and not is_final):
				_fail(
					"count %d wave %d: advance should fire exactly on a non-final wave's last death"
					% [wave_count, wave_index]
				)
				return false
			if decision["all_cleared"] != (expect_cleared and is_final):
				_fail(
					"count %d wave %d: all_cleared should fire exactly on the final wave's last death"
					% [wave_count, wave_index]
				)
				return false
			if decision["advance"]:
				advances += 1
			if decision["all_cleared"]:
				all_cleared_count += 1
			alive = decision["alive"]
	if advances != wave_count - 1:
		_fail(
			"count %d: the schedule should advance exactly %d times, got %d"
			% [wave_count, wave_count - 1, advances]
		)
		return false
	if all_cleared_count != 1:
		_fail(
			"count %d: all_cleared should fire exactly once, got %d"
			% [wave_count, all_cleared_count]
		)
		return false
	return true


func _init() -> void:
	# The advance-on-clear fold holds at EVERY tested wave count — 3, 4, and 5
	# — proving the rule reads the count as data (no hardcoded 4 anywhere).
	for wave_count in WAVE_COUNTS:
		if not _fold_schedule(wave_count):
			return

	# Boundary: a death reported against an already-empty wave stays clamped
	# at 0 alive (defensive contract — the controller never sends it).
	var clamped: Dictionary = WaveSystemScript.resolve_death(0, 0, 3)
	if clamped["alive"] != 0:
		_fail("alive must clamp at 0, got %s" % clamped["alive"])
		return

	# A single-wave schedule's only clear IS the schedule's completion.
	var solo: Dictionary = WaveSystemScript.resolve_death(1, 0, 1)
	if not (solo["cleared"] and solo["all_cleared"] and not solo["advance"]):
		_fail("a 1-wave schedule must all_clear on its only wave: %s" % solo)
		return

	print("LOGIC_SEAM: PASS")
	quit(0)
