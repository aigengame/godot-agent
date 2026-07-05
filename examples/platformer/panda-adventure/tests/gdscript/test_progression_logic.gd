extends SceneTree

## Logic seam (b) for S6b: exercise the PURE progression decisions headless —
## GrowthSystem.resolve_level (the leveling curve: level as a function of the
## EXP total, max level = curve length + 1), EconomySystem.resolve_drops (the
## Drop-table roll: rolls are parameters, roll <= chance drops) and
## drop_offset (the deterministic scatter row), and StatsSystem.gain_gold
## (the Pickup path's pure gold accumulation) — with every value injected as
## a parameter (node/physics/clock/RNG-free), per gADR-0006 on gADR-0001's
## decision shape.
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_progression_logic.gd
##
## preload() the scripts (a headless runtime has no editor-generated
## global_script_class_cache), construct in-memory curves/tables with KNOWN
## values, and assert each rule. Prints "LOGIC_SEAM: PASS" + quit(0) on
## success, else push_error + quit(1).

const StatsConfigScript := preload("res://src/resources/stats_config.gd")
const StatsSystemScript := preload("res://src/systems/stats_system.gd")
const GrowthSystemScript := preload("res://src/systems/growth_system.gd")
const EconomySystemScript := preload("res://src/systems/economy_system.gd")

# A known curve: strictly increasing cumulative thresholds (max level 4).
const CURVE := [10.0, 50.0, 150.0]

# A known Drop table: a guaranteed entry, a coin-flip entry, a long-shot.
const TABLE := [
	{"item": "gold", "amount": 3, "chance": 1.0},
	{"item": "bun", "amount": 1, "chance": 0.5},
	{"item": "wine", "amount": 2, "chance": 0.1},
]


func _fail(msg: String) -> void:
	push_error("LOGIC_SEAM: " + msg)
	quit(1)


func _init() -> void:
	# Behavior 1 — the start of the curve: level 1 at the accumulation
	# identity (0 EXP) and anywhere below the first threshold.
	if GrowthSystemScript.resolve_level(0.0, CURVE) != 1:
		_fail("0 EXP must be level 1")
		return
	if GrowthSystemScript.resolve_level(9.9, CURVE) != 1:
		_fail("EXP below the first threshold must stay level 1")
		return

	# Behavior 2 — a threshold REACHED is a level-up (>=, not >): exactly at
	# the first threshold is level 2.
	if GrowthSystemScript.resolve_level(10.0, CURVE) != 2:
		_fail("EXP exactly at a threshold must level up")
		return
	if GrowthSystemScript.resolve_level(49.9, CURVE) != 2:
		_fail("EXP between thresholds must hold the level")
		return

	# Behavior 3 — level is a FUNCTION of the total: one big total is worth
	# every threshold it crosses (the multi-level-up rule).
	if GrowthSystemScript.resolve_level(150.0, CURVE) != 4:
		_fail("a total crossing several thresholds must yield them all")
		return

	# Behavior 4 — the cap: the max level is curve length + 1, however far
	# the EXP total runs past the last threshold (config, never code).
	if GrowthSystemScript.resolve_level(1000000.0, CURVE) != CURVE.size() + 1:
		_fail("the max level must be the curve length + 1")
		return

	# Behavior 5 — the curve LENGTH is the authority (the gADR-0005
	# waves.size() idiom at this seam): a longer curve raises the cap with no
	# code change, an empty curve pins level 1.
	if GrowthSystemScript.resolve_level(1000000.0, [5.0, 10.0, 15.0, 20.0, 25.0]) != 6:
		_fail("a 5-entry curve must cap at level 6")
		return
	if GrowthSystemScript.resolve_level(1000000.0, []) != 1:
		_fail("an empty curve must pin level 1")
		return

	# Behavior 6 — resolve_drops includes an entry iff its roll <= chance:
	# the INCLUSIVE boundary makes chance 1.0 a guaranteed drop even at the
	# roll domain's top (randf() includes 1.0).
	var all_top: Array = EconomySystemScript.resolve_drops(TABLE, [1.0, 1.0, 1.0])
	if all_top.size() != 1 or all_top[0]["item"] != "gold":
		_fail("at roll 1.0 only the guaranteed entry must drop")
		return
	var at_chance: Array = EconomySystemScript.resolve_drops(TABLE, [1.0, 0.5, 0.1])
	if at_chance.size() != 3:
		_fail("a roll exactly at an entry's chance must drop (inclusive)")
		return
	var above: Array = EconomySystemScript.resolve_drops(TABLE, [1.0, 0.51, 0.11])
	if above.size() != 1:
		_fail("a roll above an entry's chance must not drop")
		return

	# Behavior 7 — resolved drops keep table order and carry {item, amount}
	# only (the chance is consumed by the roll).
	var low: Array = EconomySystemScript.resolve_drops(TABLE, [0.0, 0.0, 0.0])
	if low.size() != 3:
		_fail("rolls of 0 must drop every entry")
		return
	if low[0]["item"] != "gold" or low[1]["item"] != "bun" or low[2]["item"] != "wine":
		_fail("resolved drops must keep table order")
		return
	if low[2]["amount"] != 2 or low[2].has("chance"):
		_fail("a resolved drop carries item+amount, never the chance")
		return

	# Behavior 8 — an empty Drop table resolves to no drops (a Tier that
	# drops nothing is legal config).
	if not EconomySystemScript.resolve_drops([], []).is_empty():
		_fail("an empty Drop table must resolve to no drops")
		return

	# Behavior 9 — the deterministic scatter row: centered on the death
	# position, spacing apart, no RNG.
	if EconomySystemScript.drop_offset(0, 1, 30.0) != Vector2.ZERO:
		_fail("a single drop must sit at the death position")
		return
	if EconomySystemScript.drop_offset(0, 2, 30.0) != Vector2(-15.0, 0.0):
		_fail("two drops must straddle the death position (left)")
		return
	if EconomySystemScript.drop_offset(1, 2, 30.0) != Vector2(15.0, 0.0):
		_fail("two drops must straddle the death position (right)")
		return
	if EconomySystemScript.drop_offset(2, 3, 30.0) != Vector2(30.0, 0.0):
		_fail("three drops must span a centered row")
		return

	# Behavior 10 — gain_gold accumulates gold ONLY, from the accumulation
	# identity, leaving EXP and the survival resources untouched (the Pickup
	# path next to the Kill reward's gain_reward, gADR-0006 on gADR-0001).
	var block := StatsConfigScript.new()
	block.max_hp = 100.0
	block.max_mp = 50.0
	block.attack = 10.0
	block.defense = 0.0
	var stats := StatsSystemScript.new()
	stats.init_from(block)
	stats.gain_gold(3.0)
	stats.gain_gold(50.0)
	if not is_equal_approx(stats.gold, 53.0):
		_fail("gain_gold must accumulate: 3+50 gold")
		return
	if not is_zero_approx(stats.exp_points):
		_fail("gain_gold must not touch EXP")
		return
	if not is_equal_approx(stats.hp, 100.0) or not is_equal_approx(stats.mp, 50.0):
		_fail("gain_gold must not touch HP/MP")
		return

	print("LOGIC_SEAM: PASS")
	quit(0)
