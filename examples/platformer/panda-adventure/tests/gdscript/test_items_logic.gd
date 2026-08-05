extends SceneTree

## Logic seam (b) for S7: exercise the PURE Consumable-use and
## Equipment-mitigation decisions headless (gADR-0008) — ItemSystem's supply
## gate + count decrement + effective-defender composition,
## StatsSystem.restore_hp (the Bun's capped restore, restore_mp's mirror), and
## the composed defender feeding CombatSystem.compute_damage's mitigation term
## with the formula untouched — every value injected as a parameter
## (node/physics/clock-free).
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_items_logic.gd
##
## preload() the scripts (a headless runtime has no editor-generated
## global_script_class_cache), construct in-memory stat blocks with KNOWN
## values, and assert each rule. Prints "LOGIC_SEAM: PASS" + quit(0) on
## success, else push_error + quit(1).

const StatsConfigScript := preload("res://systems/stats_config.gd")
const CombatConfigScript := preload("res://content/config/combat_config.gd")
const StatsSystemScript := preload("res://systems/stats_system.gd")
const CombatSystemScript := preload("res://systems/combat_system.gd")
const ItemSystemScript := preload("res://systems/item_system.gd")

# A known stat block: values chosen exactly representable.
const MAX_HP := 100.0
const MAX_MP := 50.0
const BASE_DEFENSE := 1.0


func _make_block() -> StatsConfigScript:
	var block := StatsConfigScript.new()
	block.max_hp = MAX_HP
	block.max_mp = MAX_MP
	block.attack = 10.0
	block.defense = BASE_DEFENSE
	return block


func _make_params() -> CombatConfigScript:
	var params := CombatConfigScript.new()
	params.attack_scale = 1.0
	params.defense_scale = 1.0
	params.min_damage = 1.0
	return params


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
	# Behavior 1 — the supply gate is one-input (gADR-0008): empty refuses,
	# any held count permits.
	if ItemSystemScript.can_consume(0):
		_fail("can_consume(0) must refuse — nothing held")
		return
	if not ItemSystemScript.can_consume(1) or not ItemSystemScript.can_consume(3):
		_fail("can_consume must permit any positive count")
		return

	# Behavior 2 — consumed decrements by exactly one and floors at 0 (a
	# miscounted hook can never go negative).
	if ItemSystemScript.consumed(3) != 2 or ItemSystemScript.consumed(1) != 0:
		_fail("consumed should decrement by exactly one")
		return
	if ItemSystemScript.consumed(0) != 0:
		_fail("consumed must floor at 0")
		return

	# Behavior 3 — restore_hp (the Bun's effect): a partial restore adds the
	# amount, a big restore caps at max_hp (the cap is a parameter, gADR-0001).
	var stats := StatsSystemScript.new()
	stats.init_from(_make_block())
	stats.apply_damage(40.0)
	stats.restore_hp(25.0, MAX_HP)
	if not is_equal_approx(stats.hp, 85.0):
		_fail("restore_hp should add the amount below the cap (60+25=85)")
		return
	stats.restore_hp(25.0, MAX_HP)
	if not is_equal_approx(stats.hp, MAX_HP):
		_fail("restore_hp must cap at max_hp (85+25 -> 100)")
		return
	stats.restore_hp(25.0, MAX_HP)
	if not is_equal_approx(stats.hp, MAX_HP):
		_fail("restore_hp at full HP must stay at the cap")
		return

	# Behavior 4 — restore_hp never touches the other stats (restore_mp's
	# mirror keeps the same single-stat contract).
	if not is_equal_approx(stats.mp, MAX_MP):
		_fail("restore_hp must not touch MP")
		return

	# Behavior 5 — effective_defender composes a FRESH block: defense = base
	# + bonus, every other stat copied, and the base is NOT mutated (the
	# load()-alias safety this composition exists for, gADR-0001/gADR-0008).
	var base := _make_block()
	var composed: StatsConfigScript = ItemSystemScript.effective_defender(base, 2.0)
	if not is_equal_approx(composed.defense, BASE_DEFENSE + 2.0):
		_fail("effective_defender should raise defense by the bonus")
		return
	if (
		not is_equal_approx(composed.max_hp, base.max_hp)
		or not is_equal_approx(composed.max_mp, base.max_mp)
		or not is_equal_approx(composed.attack, base.attack)
	):
		_fail("effective_defender must copy the non-defense stats unchanged")
		return
	if not is_equal_approx(base.defense, BASE_DEFENSE):
		_fail("effective_defender must NEVER mutate the base block")
		return
	if composed == base:
		_fail("effective_defender must return a fresh block, not the base")
		return

	# Behavior 6 — a zero bonus composes an equivalent defender (a purely
	# cosmetic suit is legal config).
	var bare: StatsConfigScript = ItemSystemScript.effective_defender(base, 0.0)
	if not is_equal_approx(bare.defense, BASE_DEFENSE):
		_fail("a zero-bonus suit should leave defense at the base value")
		return

	# Behavior 7 — the composed defender feeds the UNTOUCHED formula's
	# mitigation term: damage drops by exactly bonus * defense_scale.
	var params := _make_params()
	var attacker := _make_block()  # attack 10
	var raw: float = _damage(attacker, base, params)
	var mitigated: float = _damage(attacker, composed, params)
	if not is_equal_approx(raw - mitigated, 2.0):
		_fail("the Spacesuit bonus should reduce damage by bonus * defense_scale")
		return

	# Behavior 8 — the min_damage floor survives any suit: an overwhelming
	# bonus cannot push damage below the formula's floor.
	var fortress: StatsConfigScript = ItemSystemScript.effective_defender(base, 1000.0)
	var floored: float = _damage(attacker, fortress, params)
	if not is_equal_approx(floored, params.min_damage):
		_fail("min_damage must floor the mitigated damage")
		return

	print("LOGIC_SEAM: PASS")
	quit(0)
