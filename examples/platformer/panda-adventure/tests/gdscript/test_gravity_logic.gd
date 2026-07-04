extends SceneTree

## Logic seam (b) for S3: exercise the PURE gravity decisions headless —
## PlayerController.compute_next_weapon (weapon-switch state), StatsSystem's
## spend_mp / restore_mp (the MP economy rules), GravitySystem's
## compute_field_velocity / compute_clamped_offset (the field's data-driven
## effect and the clamped-displacement integration, gADR-0002), and
## GravityFieldController.should_affect (the opt-in contract filter: group AND
## method — either alone is not the contract). All static or
## node/physics/clock-free, per the gADR-0001 decision shape.
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_gravity_logic.gd
##
## preload() the scripts (a headless runtime has no editor-generated
## global_script_class_cache, so bare class_name types would not resolve),
## drive them with KNOWN values, and assert each rule. Prints
## "LOGIC_SEAM: PASS" + quit(0) on success, else push_error + quit(1).

const StatsSystemScript := preload("res://src/systems/stats_system.gd")
const GravitySystemScript := preload("res://src/systems/gravity_system.gd")
const PlayerControllerScript := preload("res://src/controllers/player_controller.gd")
const GravityFieldControllerScript := preload("res://src/controllers/gravity_field_controller.gd")
const ObstacleControllerScript := preload("res://src/controllers/obstacle_controller.gd")

# Fixed MP-economy params so every expectation is exact.
const MP_MAX := 50.0
const MP_COST := 10.0
const WINE_RESTORE := 15.0


func _fail(msg: String) -> void:
	push_error("LOGIC_SEAM: " + msg)
	quit(1)


func _init() -> void:
	# Behavior 1 — weapon-switch state: `fire` fires the CURRENT weapon, and
	# compute_next_weapon toggles it between the two Equipment guns; anything
	# outside the two-gun set falls back to the spawn default (Laser Gun).
	var laser: String = PlayerControllerScript.WEAPON_LASER
	var gravity: String = PlayerControllerScript.WEAPON_GRAVITY
	if PlayerControllerScript.compute_next_weapon(laser) != gravity:
		_fail("switch: laser should toggle to gravity")
		return
	if PlayerControllerScript.compute_next_weapon(gravity) != laser:
		_fail("switch: gravity should toggle back to laser")
		return
	if PlayerControllerScript.compute_next_weapon("bare_paws") != laser:
		_fail("switch: unknown state should fall back to the laser default")
		return

	# Behavior 2 — spend_mp deducts when affordable and reports success. The MP
	# rules operate on the live mp value alone (init_from is the combat seam's
	# turf), so the holder is driven directly.
	var stats := StatsSystemScript.new()
	stats.mp = MP_MAX
	if not stats.spend_mp(MP_COST):
		_fail("spend: affordable cost should succeed")
		return
	if not is_equal_approx(stats.mp, MP_MAX - MP_COST):
		_fail("spend: expected mp=%s, got %s" % [MP_MAX - MP_COST, stats.mp])
		return

	# Behavior 3 — exact-cost boundary: spending down to exactly 0 succeeds.
	stats.mp = MP_COST
	if not stats.spend_mp(MP_COST):
		_fail("spend: exact-cost spend should succeed")
		return
	if not is_zero_approx(stats.mp):
		_fail("spend: exact-cost spend should leave 0 MP, got %s" % stats.mp)
		return

	# Behavior 4 — at 0 MP the Gravity Gun cannot fire: refused, nothing spent.
	if stats.spend_mp(MP_COST):
		_fail("spend: at 0 MP the spend must be refused")
		return
	if not is_zero_approx(stats.mp):
		_fail("spend: a refused spend must not change MP, got %s" % stats.mp)
		return

	# Behavior 5 — insufficient (but nonzero) MP: all-or-nothing, no partial spend.
	stats.mp = MP_COST / 2.0
	if stats.spend_mp(MP_COST):
		_fail("spend: insufficient MP must be refused")
		return
	if not is_equal_approx(stats.mp, MP_COST / 2.0):
		_fail("spend: a refused spend must not change MP, got %s" % stats.mp)
		return

	# Behavior 6 — restore_mp adds the Wine amount, capped at max_mp.
	stats.mp = 0.0
	stats.restore_mp(WINE_RESTORE, MP_MAX)
	if not is_equal_approx(stats.mp, WINE_RESTORE):
		_fail("restore: expected mp=%s, got %s" % [WINE_RESTORE, stats.mp])
		return
	stats.mp = MP_MAX - WINE_RESTORE / 3.0
	stats.restore_mp(WINE_RESTORE, MP_MAX)
	if not is_equal_approx(stats.mp, MP_MAX):
		_fail("restore: overfill should clamp at max_mp, got %s" % stats.mp)
		return
	stats.restore_mp(WINE_RESTORE, MP_MAX)
	if not is_equal_approx(stats.mp, MP_MAX):
		_fail("restore: at max_mp the cap should hold, got %s" % stats.mp)
		return

	# Behavior 7 — compute_field_velocity: direction is normalized (strength is
	# the single magnitude authority) and lift/slam/redirect are DATA — three
	# directions through the ONE function (gADR-0002).
	var lift := GravitySystemScript.compute_field_velocity(Vector2(0.0, -1.0), 260.0)
	if not lift.is_equal_approx(Vector2(0.0, -260.0)):
		_fail("velocity: lift expected (0, -260), got %s" % lift)
		return
	var slam := GravitySystemScript.compute_field_velocity(Vector2(0.0, 2.0), 100.0)
	if not slam.is_equal_approx(Vector2(0.0, 100.0)):
		_fail("velocity: slam should normalize a non-unit direction, got %s" % slam)
		return
	var redirect := GravitySystemScript.compute_field_velocity(Vector2(3.0, -4.0), 50.0)
	if not redirect.is_equal_approx(Vector2(30.0, -40.0)):
		_fail("velocity: redirect expected (30, -40), got %s" % redirect)
		return
	var null_field := GravitySystemScript.compute_field_velocity(Vector2.ZERO, 260.0)
	if not null_field.is_equal_approx(Vector2.ZERO):
		_fail("velocity: a zero direction must yield a null field, got %s" % null_field)
		return

	# Behavior 8 — compute_clamped_offset integrates velocity * delta and clamps
	# the TOTAL offset length, then holds at the clamp (gADR-0002).
	var v := Vector2(0.0, -260.0)
	var offset := GravitySystemScript.compute_clamped_offset(Vector2.ZERO, v, 0.5, 200.0)
	if not offset.is_equal_approx(Vector2(0.0, -130.0)):
		_fail("offset: one step expected (0, -130), got %s" % offset)
		return
	offset = GravitySystemScript.compute_clamped_offset(offset, v, 0.5, 200.0)
	if not offset.is_equal_approx(Vector2(0.0, -200.0)):
		_fail("offset: accumulation should clamp at max length, got %s" % offset)
		return
	offset = GravitySystemScript.compute_clamped_offset(offset, v, 0.5, 200.0)
	if not offset.is_equal_approx(Vector2(0.0, -200.0)):
		_fail("offset: at the clamp further frames must hold, got %s" % offset)
		return
	var still := GravitySystemScript.compute_clamped_offset(offset, Vector2.ZERO, 0.5, 200.0)
	if not still.is_equal_approx(offset):
		_fail("offset: zero velocity must leave the offset unchanged, got %s" % still)
		return
	var diagonal := GravitySystemScript.compute_clamped_offset(
		Vector2.ZERO, Vector2(300.0, -400.0), 1.0, 250.0
	)
	if not diagonal.is_equal_approx(Vector2(150.0, -200.0)):
		_fail("offset: the clamp is a LENGTH limit, expected (150, -200), got %s" % diagonal)
		return

	# Behavior 9 — should_affect, the opt-in contract filter (gADR-0002): a
	# body is affected only with BOTH the "gravity_affectable" group AND the
	# apply_gravity_field method. An ObstacleController built off-tree has the
	# method but no group (the join happens in _ready, which never ran), so it
	# doubles as the method-only double; a plain Node2D in the group is the
	# group-only double. add_to_group/is_in_group work off-tree (node-local
	# group data), so no SceneTree attachment is needed.
	var member: Node = ObstacleControllerScript.new()
	member.add_to_group("gravity_affectable")
	var method_only: Node = ObstacleControllerScript.new()
	var group_only: Node = Node2D.new()
	group_only.add_to_group("gravity_affectable")
	var member_ok: bool = GravityFieldControllerScript.should_affect(member)
	var method_only_ok: bool = GravityFieldControllerScript.should_affect(method_only)
	var group_only_ok: bool = GravityFieldControllerScript.should_affect(group_only)
	member.free()
	method_only.free()
	group_only.free()
	if not member_ok:
		_fail("filter: group + method should be affected")
		return
	if method_only_ok:
		_fail("filter: a same-named method WITHOUT the group must not be affected")
		return
	if group_only_ok:
		_fail("filter: group membership WITHOUT the method must not be affected")
		return

	print("LOGIC_SEAM: PASS")
	quit(0)
