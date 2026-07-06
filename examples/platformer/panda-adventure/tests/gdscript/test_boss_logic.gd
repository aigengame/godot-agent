extends SceneTree

## Logic seam (b) for S8: exercise the PURE Warp-kit decisions headless —
## WarpSystem.has_warp / should_warp / warp_landing / is_inside_field
## (gADR-0009) — the presence gate, the anti-kite warp window
## (aggro >= distance > trigger, cooldown elapsed), the deterministic
## far-side landing with arena clamping, and the field membership rule,
## with positions and time injected as parameters (node/physics/clock-free,
## gADR-0001's decision shape).
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_boss_logic.gd
##
## preload() the scripts (a headless runtime has no editor-generated
## global_script_class_cache), construct in-memory EnemyConfig kinds with
## KNOWN values, and assert each rule. Prints "LOGIC_SEAM: PASS" + quit(0)
## on success, else push_error + quit(1).

const EnemyConfigScript := preload("res://src/resources/enemy_config.gd")
const WarpSystemScript := preload("res://src/systems/warp_system.gd")

# Fixed Warp params so every expectation is exact: the warp window is
# (TRIGGER, AGGRO] = (200, 400], the cooldown boundary probes >= with
# exactly-representable floats, and the landing offset is (60, -8).
const AGGRO := 400.0
const TRIGGER := 200.0
const COOLDOWN := 8.0
const OFFSET := Vector2(60.0, -8.0)
const ARENA_MIN_X := 40.0
const ARENA_MAX_X := 1240.0

# All distance cases place actors on the same horizontal line: distance then
# equals |dx|, so every range expectation is exact.
const SELF_POS := Vector2(500.0, 100.0)


func _make_warp_kind() -> EnemyConfigScript:
	var kind := EnemyConfigScript.new()
	kind.archetype = "tank"
	kind.aggro_range = AGGRO
	kind.warp_cooldown = COOLDOWN
	kind.warp_trigger_range = TRIGGER
	kind.warp_offset = OFFSET
	return kind


func _fail(msg: String) -> void:
	push_error("LOGIC_SEAM: " + msg)
	quit(1)


func _at(dx: float, dy: float = 0.0) -> Vector2:
	return SELF_POS + Vector2(dx, dy)


func _init() -> void:
	var warper := _make_warp_kind()
	# A kind WITHOUT the block: type defaults (warp_cooldown 0.0).
	var plain := EnemyConfigScript.new()
	plain.archetype = "melee"
	plain.aggro_range = AGGRO

	# Behavior 1 — the presence gate: only a kind carrying the block has Warp;
	# a plain kind never warps, whatever the geometry or clock.
	if not WarpSystemScript.has_warp(warper):
		_fail("a kind carrying the warp block should have Warp")
		return
	if WarpSystemScript.has_warp(plain):
		_fail("a kind without the warp block should not have Warp")
		return
	if WarpSystemScript.should_warp(SELF_POS, _at(300.0), plain, -INF, 100.0):
		_fail("a plain kind should never pass the warp gate")
		return

	# Behavior 2 — the warp window: inside (TRIGGER, AGGRO] with the -INF
	# never-warped sentinel, the gate opens; at or inside the trigger range it
	# stays shut (the Blink never fires in a brawl); beyond the Aggro Range
	# the enemy is dormant (gADR-0003's contract holds for abilities too).
	if not WarpSystemScript.should_warp(SELF_POS, _at(300.0), warper, -INF, 100.0):
		_fail("warp should fire inside the (trigger, aggro] window")
		return
	if WarpSystemScript.should_warp(SELF_POS, _at(TRIGGER), warper, -INF, 100.0):
		_fail("warp should not fire exactly AT the trigger range (engage tool)")
		return
	if WarpSystemScript.should_warp(SELF_POS, _at(50.0), warper, -INF, 100.0):
		_fail("warp should not fire point-blank")
		return
	if WarpSystemScript.should_warp(SELF_POS, _at(AGGRO + 1.0), warper, -INF, 100.0):
		_fail("warp should not fire beyond the Aggro Range (dormant)")
		return
	if not WarpSystemScript.should_warp(SELF_POS, _at(AGGRO), warper, -INF, 100.0):
		_fail("warp should fire exactly AT the Aggro Range edge")
		return

	# Behavior 3 — the cooldown gate: ready exactly AT expiry (>=), not ready
	# strictly within (exactly-representable floats).
	if not WarpSystemScript.should_warp(SELF_POS, _at(300.0), warper, 10.0, 18.0):
		_fail("warp cooldown: exactly at expiry should be ready")
		return
	if WarpSystemScript.should_warp(SELF_POS, _at(300.0), warper, 10.0, 17.5):
		_fail("warp cooldown: strictly within should not be ready")
		return

	# Behavior 4 — the far-side landing: the Boss lands the offset BEYOND the
	# Player, on the side away from the caster (cutting off the retreat), from
	# either side; y is the Player's y plus the offset y.
	var player_right := _at(300.0, 20.0)
	var landing := WarpSystemScript.warp_landing(
		SELF_POS, player_right, warper, ARENA_MIN_X, ARENA_MAX_X
	)
	if not landing.is_equal_approx(Vector2(player_right.x + OFFSET.x, player_right.y + OFFSET.y)):
		_fail("landing should overshoot a rightward Player to its far side")
		return
	var player_left := _at(-300.0, 20.0)
	landing = WarpSystemScript.warp_landing(
		SELF_POS, player_left, warper, ARENA_MIN_X, ARENA_MAX_X
	)
	if not landing.is_equal_approx(Vector2(player_left.x - OFFSET.x, player_left.y + OFFSET.y)):
		_fail("landing should overshoot a leftward Player to its far side")
		return

	# Behavior 5 — dx == 0 resolves to the +x side: deterministic, never random.
	landing = WarpSystemScript.warp_landing(
		SELF_POS, _at(0.0, -250.0), warper, ARENA_MIN_X, ARENA_MAX_X
	)
	if not is_equal_approx(landing.x, SELF_POS.x + OFFSET.x):
		_fail("a Player straight above should land on the +x side (tie-break)")
		return

	# Behavior 6 — the arena clamp bounds the landing x on both edges.
	landing = WarpSystemScript.warp_landing(
		SELF_POS, Vector2(ARENA_MAX_X - 10.0, 100.0), warper, ARENA_MIN_X, ARENA_MAX_X
	)
	if not is_equal_approx(landing.x, ARENA_MAX_X):
		_fail("landing should clamp at the arena's right edge")
		return
	landing = WarpSystemScript.warp_landing(
		SELF_POS, Vector2(ARENA_MIN_X + 10.0, 100.0), warper, ARENA_MIN_X, ARENA_MAX_X
	)
	if not is_equal_approx(landing.x, ARENA_MIN_X):
		_fail("landing should clamp at the arena's left edge")
		return

	# Behavior 7 — field membership: inside and exactly AT the radius are in,
	# strictly beyond is out (exactly-representable distances).
	var center := Vector2(600.0, 100.0)
	if not WarpSystemScript.is_inside_field(Vector2(680.0, 100.0), center, 160.0):
		_fail("a point inside the radius should be in the field")
		return
	if not WarpSystemScript.is_inside_field(Vector2(760.0, 100.0), center, 160.0):
		_fail("a point exactly AT the radius should be in the field")
		return
	if WarpSystemScript.is_inside_field(Vector2(760.5, 100.0), center, 160.0):
		_fail("a point strictly beyond the radius should be out of the field")
		return

	print("LOGIC_SEAM: PASS")
	quit(0)
