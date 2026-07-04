extends SceneTree

## Logic seam (b) for S4: exercise the PURE Archetype-AI decisions headless —
## EnemyAI.compute_move_dir / can_attack / is_attack_ready (gADR-0003) — the
## closing-distance / keeping-distance steering and the attack-cooldown gating,
## with positions and time injected as parameters (node/physics/clock-free,
## gADR-0001's decision shape).
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_enemies_logic.gd
##
## preload() the scripts (a headless runtime has no editor-generated
## global_script_class_cache), construct in-memory EnemyConfig kinds with KNOWN
## values, and assert each AI rule. Prints "LOGIC_SEAM: PASS" + quit(0) on
## success, else push_error + quit(1).

const EnemyConfigScript := preload("res://src/resources/enemy_config.gd")
const EnemyAIScript := preload("res://src/systems/enemy_ai.gd")

# Fixed AI params so every expectation is exact. The Melee shape: band
# [0, 48] (never back off), attack range == the band edge — the melee contact
# invariant (attack_range <= keep_range_max, enforced at the data seam by
# validate_enemies_semantics) means melee damage is point-blank only. The
# Ranged shape: a standoff band [220, 380], long attack range. Cooldowns
# chosen exactly representable.
const MELEE_AGGRO := 240.0
const MELEE_ATTACK_RANGE := 48.0
const MELEE_BAND_MAX := 48.0
const RANGED_AGGRO := 700.0
const RANGED_ATTACK_RANGE := 520.0
const RANGED_BAND_MIN := 220.0
const RANGED_BAND_MAX := 380.0
const COOLDOWN := 0.5

# All cases place actors on the same horizontal line unless stated: distance
# then equals |dx|, so every range expectation is exact.
const SELF_POS := Vector2(500.0, 100.0)


func _make_kind(
	archetype: String,
	aggro_range: float,
	attack_range: float,
	band_min: float,
	band_max: float,
) -> EnemyConfigScript:
	var kind := EnemyConfigScript.new()
	kind.archetype = archetype
	kind.aggro_range = aggro_range
	kind.attack_range = attack_range
	kind.keep_range_min = band_min
	kind.keep_range_max = band_max
	kind.attack_cooldown = COOLDOWN
	return kind


func _fail(msg: String) -> void:
	push_error("LOGIC_SEAM: " + msg)
	quit(1)


func _at(dx: float, dy: float = 0.0) -> Vector2:
	return SELF_POS + Vector2(dx, dy)


func _init() -> void:
	var melee := _make_kind("melee", MELEE_AGGRO, MELEE_ATTACK_RANGE, 0.0, MELEE_BAND_MAX)
	var ranged := _make_kind(
		"ranged", RANGED_AGGRO, RANGED_ATTACK_RANGE, RANGED_BAND_MIN, RANGED_BAND_MAX
	)
	var tank := _make_kind("tank", MELEE_AGGRO, MELEE_ATTACK_RANGE, 0.0, MELEE_BAND_MAX)

	# Behavior 1 — Melee closes distance: inside aggro and beyond the band it
	# steers toward the Player, from either side.
	if not is_equal_approx(EnemyAIScript.compute_move_dir(SELF_POS, _at(200.0), melee), 1.0):
		_fail("melee should approach a Player 200px to the right")
		return
	if not is_equal_approx(EnemyAIScript.compute_move_dir(SELF_POS, _at(-200.0), melee), -1.0):
		_fail("melee should approach a Player 200px to the left")
		return

	# Behavior 2 — Melee holds point-blank: inside the band (min 0 = never
	# backs off) it stops and lets the attack gate take over.
	if not is_zero_approx(EnemyAIScript.compute_move_dir(SELF_POS, _at(30.0), melee)):
		_fail("melee inside its band (30 < 48) should hold, not jitter")
		return

	# Behavior 3 — Aggro gate: beyond the Aggro Range every archetype is dormant.
	if not is_zero_approx(EnemyAIScript.compute_move_dir(SELF_POS, _at(300.0), melee)):
		_fail("melee beyond aggro (300 > 240) should stay dormant")
		return
	if not is_zero_approx(EnemyAIScript.compute_move_dir(SELF_POS, _at(800.0), ranged)):
		_fail("ranged beyond aggro (800 > 700) should stay dormant")
		return

	# Behavior 4 — Ranged closes to its band: beyond keep_range_max it approaches.
	if not is_equal_approx(EnemyAIScript.compute_move_dir(SELF_POS, _at(-450.0), ranged), -1.0):
		_fail("ranged beyond its band (450 > 380) should approach")
		return

	# Behavior 5 — Ranged KEEPS distance: inside keep_range_min it backs off,
	# away from the Player, from either side.
	if not is_equal_approx(EnemyAIScript.compute_move_dir(SELF_POS, _at(100.0), ranged), -1.0):
		_fail("ranged crowded from the right (100 < 220) should back off left")
		return
	if not is_equal_approx(EnemyAIScript.compute_move_dir(SELF_POS, _at(-100.0), ranged), 1.0):
		_fail("ranged crowded from the left should back off right")
		return

	# Behavior 6 — Ranged holds inside the band.
	if not is_zero_approx(EnemyAIScript.compute_move_dir(SELF_POS, _at(300.0), ranged)):
		_fail("ranged inside its band (220 <= 300 <= 380) should hold")
		return

	# Behavior 7 — the distance is the full 2D distance: a Player 300px away
	# vertically-diagonally counts against the ranges even when |dx| is small.
	if not is_zero_approx(EnemyAIScript.compute_move_dir(SELF_POS, _at(30.0, 300.0), melee)):
		_fail("melee should be dormant when the 2D distance (301) exceeds aggro")
		return

	# Behavior 8 — a Player directly above (dx == 0) yields no horizontal steer.
	if not is_zero_approx(EnemyAIScript.compute_move_dir(SELF_POS, _at(0.0, -100.0), melee)):
		_fail("melee with the Player straight above should not steer")
		return

	# Behavior 9 — Tank AI is DEFERRED (gADR-0003): representable in data, but
	# it neither moves nor attacks, whatever the geometry.
	if not is_zero_approx(EnemyAIScript.compute_move_dir(SELF_POS, _at(200.0), tank)):
		_fail("tank should never move (AI deferred)")
		return
	if EnemyAIScript.can_attack(SELF_POS, _at(30.0), tank, -INF, 100.0):
		_fail("tank should never attack (AI deferred)")
		return

	# Behavior 10 — cooldown gate: ready exactly AT expiry (>=), not ready
	# strictly within, and the -INF never-attacked sentinel is always ready.
	# Boundary probed with exactly-representable floats (0.5).
	if not EnemyAIScript.is_attack_ready(10.0, 10.5, COOLDOWN):
		_fail("cooldown: exactly at expiry should be ready")
		return
	if EnemyAIScript.is_attack_ready(10.0, 10.25, COOLDOWN):
		_fail("cooldown: 0.25s into a 0.5s cooldown should NOT be ready")
		return
	if not EnemyAIScript.is_attack_ready(-INF, 0.0, COOLDOWN):
		_fail("cooldown: the -INF never-attacked sentinel should be ready")
		return

	# Behavior 11 — can_attack combines range + cooldown: in range and ready ->
	# true; in range but cooling down -> false; and melee damage is CONTACT
	# damage: with the contact invariant (attack_range <= keep_range_max,
	# enforced at the data seam), any Player outside the point-blank band —
	# even barely (55 > 48) — cannot be hit.
	if not EnemyAIScript.can_attack(SELF_POS, _at(30.0), melee, -INF, 100.0):
		_fail("melee point-blank and off cooldown should attack")
		return
	if EnemyAIScript.can_attack(SELF_POS, _at(30.0), melee, 100.0, 100.25):
		_fail("melee mid-cooldown should not attack")
		return
	if EnemyAIScript.can_attack(SELF_POS, _at(55.0), melee, -INF, 100.0):
		_fail("melee just outside the band (55 > 48) should not attack")
		return
	if EnemyAIScript.can_attack(SELF_POS, _at(100.0), melee, -INF, 100.0):
		_fail("melee far beyond the band (100 > 48) should not attack")
		return

	# Behavior 12 — Ranged attacks from afar: anywhere inside its long attack
	# range (including while still approaching, beyond the band).
	if not EnemyAIScript.can_attack(SELF_POS, _at(440.0), ranged, -INF, 100.0):
		_fail("ranged at 440 (<= 520) should attack from afar")
		return
	if EnemyAIScript.can_attack(SELF_POS, _at(600.0), ranged, -INF, 100.0):
		_fail("ranged beyond attack range (600 > 520) should not attack")
		return

	# Behavior 13 — the aggro gate also bounds attacks when attack_range
	# exceeds aggro_range (misconfigured or sniper kinds stay leashed).
	var sniper := _make_kind("ranged", 200.0, 520.0, 0.0, 100.0)
	if EnemyAIScript.can_attack(SELF_POS, _at(300.0), sniper, -INF, 100.0):
		_fail("attack beyond aggro (300 > 200) should be gated even in range")
		return

	print("LOGIC_SEAM: PASS")
	quit(0)
