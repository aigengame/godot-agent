extends SceneTree

## Logic seam (b) for S6a: exercise the PURE Kill-reward and HUD decisions
## headless — StatsSystem.gain_reward accumulation (gADR-0004 on gADR-0001's
## runtime holder) and HudController's static format functions (the readout
## decisions the HUD applies to the Player's hud_state() snapshot) — with
## every value injected as a parameter (node/physics/clock-free).
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_reward_hud_logic.gd
##
## preload() the scripts (a headless runtime has no editor-generated
## global_script_class_cache), construct in-memory stat blocks with KNOWN
## values, and assert each rule. Prints "LOGIC_SEAM: PASS" + quit(0) on
## success, else push_error + quit(1).

const StatsConfigScript := preload("res://systems/stats_config.gd")
const StatsSystemScript := preload("res://systems/stats_system.gd")
const HudControllerScript := preload("res://ui/hud_controller.gd")

# A known stat block: values chosen exactly representable.
const MAX_HP := 100.0
const MAX_MP := 50.0


func _make_stats() -> StatsSystemScript:
	var block := StatsConfigScript.new()
	block.max_hp = MAX_HP
	block.max_mp = MAX_MP
	block.attack = 10.0
	block.defense = 0.0
	var stats := StatsSystemScript.new()
	stats.init_from(block)
	return stats


func _fail(msg: String) -> void:
	push_error("LOGIC_SEAM: " + msg)
	quit(1)


func _init() -> void:
	# Behavior 1 — the accumulation identity (gADR-0001): a fresh actor's
	# EXP/Gold start at 0, structurally.
	var stats := _make_stats()
	if not is_zero_approx(stats.exp_points) or not is_zero_approx(stats.gold):
		_fail("EXP/Gold must start at the accumulation identity (0)")
		return

	# Behavior 2 — one Kill reward accumulates both amounts.
	stats.gain_reward(10.0, 5.0)
	if not is_equal_approx(stats.exp_points, 10.0) or not is_equal_approx(stats.gold, 5.0):
		_fail("one reward should accumulate exp 10 / gold 5")
		return

	# Behavior 3 — rewards ACCUMULATE across kills (never replace), including
	# mixed Tiers' amounts.
	stats.gain_reward(40.0, 20.0)
	if not is_equal_approx(stats.exp_points, 50.0) or not is_equal_approx(stats.gold, 25.0):
		_fail("rewards should accumulate: 10+40 exp, 5+20 gold")
		return

	# Behavior 4 — a zero reward is a no-op on the totals (and legal: the
	# schema allows 0 budgets).
	stats.gain_reward(0.0, 0.0)
	if not is_equal_approx(stats.exp_points, 50.0) or not is_equal_approx(stats.gold, 25.0):
		_fail("a zero reward must not change the totals")
		return

	# Behavior 5 — rewards never touch the survival resources: HP/MP stay at
	# their init_from values through every accumulation above.
	if not is_equal_approx(stats.hp, MAX_HP) or not is_equal_approx(stats.mp, MAX_MP):
		_fail("gain_reward must not touch HP/MP")
		return

	# Behavior 6 — format_bar: a capped stat readout. The current value uses
	# ceili — the readout never shows 0 while the death rule (hp <= 0) has not
	# fired — and shows 0 exactly at 0; integral values pass through.
	if HudControllerScript.format_bar("HP", 95.0, MAX_HP) != "HP 95/100":
		_fail("format_bar should render integral values as-is")
		return
	if HudControllerScript.format_bar("HP", 0.4, MAX_HP) != "HP 1/100":
		_fail("format_bar should never read 0 while alive (ceili)")
		return
	if HudControllerScript.format_bar("HP", 0.0, MAX_HP) != "HP 0/100":
		_fail("format_bar should read 0 exactly at 0")
		return

	# Behavior 7 — format_amount: an accumulating readout floors — it never
	# shows more than has actually been earned.
	if HudControllerScript.format_amount("EXP", 50.0) != "EXP 50":
		_fail("format_amount should render integral values as-is")
		return
	if HudControllerScript.format_amount("GOLD", 10.9) != "GOLD 10":
		_fail("format_amount should floor (never overstate the earned total)")
		return

	# Behavior 8 — format_weapon: both weapon identifiers render as display
	# names (the Current weapon glossary term, gADR-0002's toggle set).
	if HudControllerScript.format_weapon("laser_gun") != "LASER GUN":
		_fail("format_weapon should render laser_gun as LASER GUN")
		return
	if HudControllerScript.format_weapon("gravity_gun") != "GRAVITY GUN":
		_fail("format_weapon should render gravity_gun as GRAVITY GUN")
		return

	# Behavior 9 — format_lines maps a full hud_state() snapshot to the eight
	# display strings in one place (the whole readout pinned at once; the
	# snapshot carries the S6b Level since gADR-0006 and the S7 Consumable
	# counts since gADR-0008 — integers, format_amount passes them through).
	var lines: Dictionary = HudControllerScript.format_lines({
		"hp": 95.0,
		"max_hp": MAX_HP,
		"mp": 40.0,
		"max_mp": MAX_MP,
		"level": 3,
		"exp": 50.0,
		"gold": 25.0,
		"weapon": "gravity_gun",
		"bun": 2,
		"wine": 0,
	})
	var expected := {
		"hp": "HP 95/100",
		"mp": "MP 40/50",
		"level": "LV 3",
		"exp": "EXP 50",
		"gold": "GOLD 25",
		"weapon": "GRAVITY GUN",
		"bun": "BUN 2",
		"wine": "WINE 0",
	}
	for key: String in expected:
		if lines.get(key) != expected[key]:
			_fail("format_lines[%s]: got %s, want %s" % [key, lines.get(key), expected[key]])
			return

	print("LOGIC_SEAM: PASS")
	quit(0)
