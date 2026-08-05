extends SceneTree

## Logic seam (b) for S2: exercise the PURE combat decisions headless —
## CombatSystem.compute_damage / is_invulnerable / is_dead, StatsSystem's
## init_from / apply_damage, and PlayerMovementSystem.compute_facing. These are the
## functions the offline Monte-Carlo balancing sim reuses (gADR-0001), so they
## must stay node/physics/clock-free.
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_combat_logic.gd
##
## preload() the scripts (a headless runtime has no editor-generated
## global_script_class_cache, so bare class_name types would not resolve),
## construct in-memory configs with KNOWN values, and assert each combat rule.
## Prints "LOGIC_SEAM: PASS" + quit(0) on success, else push_error + quit(1).

const StatsConfigScript := preload("res://systems/stats_config.gd")
const CombatConfigScript := preload("res://content/config/combat_config.gd")
const StatsSystemScript := preload("res://systems/stats_system.gd")
const CombatSystemScript := preload("res://systems/combat_system.gd")
const PlayerMovementSystemScript := preload("res://systems/player_movement_system.gd")

# Fixed formula params so every expectation is exact (distinct scales prove each
# term is applied to the right stat).
const ATTACK_SCALE := 2.0
const DEFENSE_SCALE := 1.5
const MIN_DAMAGE := 1.0
const IFRAME_DURATION := 0.6

# Two DIFFERENT stat blocks so the attacker<->defender symmetry is observable.
const PLAYER_ATTACK := 10.0
const PLAYER_DEFENSE := 4.0
const ENEMY_ATTACK := 6.0
const ENEMY_DEFENSE := 2.0


func _make_params() -> CombatConfigScript:
	var p := CombatConfigScript.new()
	p.attack_scale = ATTACK_SCALE
	p.defense_scale = DEFENSE_SCALE
	p.min_damage = MIN_DAMAGE
	p.iframe_duration = IFRAME_DURATION
	return p


func _make_stats(max_hp: float, max_mp: float, attack: float, defense: float) -> StatsConfigScript:
	var s := StatsConfigScript.new()
	s.max_hp = max_hp
	s.max_mp = max_mp
	s.attack = attack
	s.defense = defense
	return s


func _damage(
	attacker: StatsConfigScript,
	defender: StatsConfigScript,
	params: CombatConfigScript,
) -> float:
	return CombatSystemScript.compute_damage(
		attacker,
		defender,
		params.attack_scale,
		params.defense_scale,
		params.min_damage,
	)


func _fail(msg: String) -> void:
	push_error("LOGIC_SEAM: " + msg)
	quit(1)


func _init() -> void:
	var params := _make_params()
	var player := _make_stats(100.0, 50.0, PLAYER_ATTACK, PLAYER_DEFENSE)
	var enemy := _make_stats(25.0, 0.0, ENEMY_ATTACK, ENEMY_DEFENSE)

	# Behavior 1 — zero defense: damage is attack * attack_scale, undiminished.
	var undefended := _make_stats(25.0, 0.0, ENEMY_ATTACK, 0.0)
	var raw := _damage(player, undefended, params)
	if not is_equal_approx(raw, PLAYER_ATTACK * ATTACK_SCALE):
		_fail("zero defense: expected %s, got %s" % [PLAYER_ATTACK * ATTACK_SCALE, raw])
		return

	# Behavior 2 — mitigation: defense * defense_scale is subtracted.
	var mitigated := _damage(player, enemy, params)
	var expected_pe := PLAYER_ATTACK * ATTACK_SCALE - ENEMY_DEFENSE * DEFENSE_SCALE
	if not is_equal_approx(mitigated, expected_pe):
		_fail("mitigation: expected %s, got %s" % [expected_pe, mitigated])
		return

	# Behavior 3 — floor: when defense swamps attack, damage clamps to min_damage.
	var weak := _make_stats(100.0, 0.0, 1.0, 0.0)
	var tank := _make_stats(100.0, 0.0, 0.0, 10.0)
	var floored := _damage(weak, tank, params)
	if not is_equal_approx(floored, MIN_DAMAGE):
		_fail("min-damage floor: expected %s, got %s" % [MIN_DAMAGE, floored])
		return

	# Behavior 4 — symmetry: the SAME function serves both directions (the S4
	# enemy->Player reuse contract), each direction reading its own stats.
	var enemy_on_player := _damage(enemy, player, params)
	var expected_ep := ENEMY_ATTACK * ATTACK_SCALE - PLAYER_DEFENSE * DEFENSE_SCALE
	if not is_equal_approx(enemy_on_player, expected_ep):
		_fail("symmetry enemy->player: expected %s, got %s" % [expected_ep, enemy_on_player])
		return
	if is_equal_approx(enemy_on_player, mitigated):
		_fail("symmetry: both directions returned %s — stats not per-role" % mitigated)
		return

	# Behavior 5 — i-frames: invulnerable strictly WITHIN the window, vulnerable
	# at/after expiry, and the -INF first-hit sentinel is always vulnerable.
	if not CombatSystemScript.is_invulnerable(10.0, 10.3, IFRAME_DURATION):
		_fail("i-frame: 0.3s after a hit should be invulnerable")
		return
	# Boundary probed with exactly-representable floats (0.5, not 0.6) so the
	# `elapsed < window` contract is what's tested, not float rounding.
	if CombatSystemScript.is_invulnerable(10.0, 10.5, 0.5):
		_fail("i-frame: exactly at window expiry should be vulnerable")
		return
	if CombatSystemScript.is_invulnerable(10.0, 11.0, IFRAME_DURATION):
		_fail("i-frame: past the window should be vulnerable")
		return
	if CombatSystemScript.is_invulnerable(-INF, 0.0, IFRAME_DURATION):
		_fail("i-frame: the -INF first-hit sentinel should never be invulnerable")
		return

	# Behavior 6 — StatsSystem.init_from: all four stats live (HP/MP from the
	# stat block, EXP/Gold at their accumulation identity 0).
	var stats := StatsSystemScript.new()
	stats.init_from(player)
	if not is_equal_approx(stats.hp, 100.0):
		_fail("init_from: expected hp=100, got %s" % stats.hp)
		return
	if not is_equal_approx(stats.mp, 50.0):
		_fail("init_from: expected mp=50, got %s" % stats.mp)
		return
	if not (is_zero_approx(stats.exp_points) and is_zero_approx(stats.gold)):
		_fail("init_from: expected exp=0 gold=0, got %s / %s" % [stats.exp_points, stats.gold])
		return

	# Behavior 7 — apply_damage: reduces HP; overkill clamps at 0 (never negative).
	stats.apply_damage(30.0)
	if not is_equal_approx(stats.hp, 70.0):
		_fail("apply_damage: expected hp=70, got %s" % stats.hp)
		return
	stats.apply_damage(1000.0)
	if not is_zero_approx(stats.hp):
		_fail("apply_damage overkill: expected hp=0, got %s" % stats.hp)
		return

	# Behavior 8 — is_dead: 0 HP and below are dead, any positive HP is alive.
	if not CombatSystemScript.is_dead(0.0):
		_fail("is_dead: hp=0 should be dead")
		return
	if not CombatSystemScript.is_dead(-5.0):
		_fail("is_dead: hp<0 should be dead")
		return
	if CombatSystemScript.is_dead(0.1):
		_fail("is_dead: hp>0 should be alive")
		return

	# Behavior 9 — compute_facing: a nonzero input re-aims (sign-normalized),
	# zero input preserves the current facing.
	if not is_equal_approx(PlayerMovementSystemScript.compute_facing(1.0, -0.5), -1.0):
		_fail("facing: left input should face -1")
		return
	if not is_equal_approx(PlayerMovementSystemScript.compute_facing(-1.0, 1.0), 1.0):
		_fail("facing: right input should face 1")
		return
	if not is_equal_approx(PlayerMovementSystemScript.compute_facing(-1.0, 0.0), -1.0):
		_fail("facing: zero input should keep the current facing")
		return

	print("LOGIC_SEAM: PASS")
	quit(0)
