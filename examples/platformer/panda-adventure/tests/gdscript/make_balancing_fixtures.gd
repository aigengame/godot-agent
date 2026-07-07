extends SceneTree

## Golden parity fixtures for the Balancing pipeline (gADR-0011, #437).
##
## The shipped GDScript logic seams — CombatSystem (compute_damage /
## is_invulnerable / is_dead), EnemyAI (compute_move_dir / is_attack_ready /
## can_attack), WarpSystem (should_warp / warp_landing / is_inside_field: the
## Boss Warp kit's pure decisions, gADR-0009), and ItemSystem
## (effective_defender's Spacesuit defense composition, gADR-0008) — are the
## GROUND-TRUTH oracle for the balancing pipeline's pure Python rule
## reimplementation (tools/balancing/rules.py). This script feeds each seam a
## fixed set of representative inputs, records the seam's OWN output as
## `expected`, and writes {inputs, expected} vectors to a JSON file. The
## Python model's fast-tier test reproduces every vector; an engine-tier test
## regenerates this file and asserts it matches the committed one — so a rule
## change on either side goes red (gADR-0011's parity gate).
##
## Positions are emitted as [x, y] arrays (reconstructed as Vector2 here) so the
## two languages agree exactly. The never-hit/never-attacked path uses a large
## finite "long ago" time (LONG_AGO) instead of -INF, which JSON cannot portably
## represent; the true -INF sentinel is pinned separately in the Python unit
## tests and the GDScript logic seams.
##
## Mirrors make_pixel_fixtures.gd: writes into the dir named by the
## BALANCING_FIXTURES_DIR environment variable, prints FIXTURES_DONE + quit(0);
## any environment/save failure prints FIXTURE_FAIL + quit(1).

const CombatSystemScript := preload("res://src/systems/combat_system.gd")
const EnemyAIScript := preload("res://src/systems/enemy_ai.gd")
const WarpSystemScript := preload("res://src/systems/warp_system.gd")
const ItemSystemScript := preload("res://src/systems/item_system.gd")
const EnemyConfigScript := preload("res://src/resources/enemy_config.gd")
const StatsConfigScript := preload("res://src/resources/stats_config.gd")
const CombatConfigScript := preload("res://src/resources/combat_config.gd")

const LONG_AGO := -1.0e30


func _damage_case(
	attack: float, defense: float, attack_scale: float, defense_scale: float, min_damage: float
) -> Dictionary:
	var attacker := StatsConfigScript.new()
	attacker.attack = attack
	var defender := StatsConfigScript.new()
	defender.defense = defense
	var params := CombatConfigScript.new()
	params.attack_scale = attack_scale
	params.defense_scale = defense_scale
	params.min_damage = min_damage
	return {
		"attacker_attack": attack,
		"defender_defense": defense,
		"attack_scale": attack_scale,
		"defense_scale": defense_scale,
		"min_damage": min_damage,
		"expected": CombatSystemScript.compute_damage(attacker, defender, params),
	}


func _invuln_case(last_hit_time: float, now: float, iframe_duration: float) -> Dictionary:
	return {
		"last_hit_time": last_hit_time,
		"now": now,
		"iframe_duration": iframe_duration,
		"expected": CombatSystemScript.is_invulnerable(last_hit_time, now, iframe_duration),
	}


func _dead_case(hp: float) -> Dictionary:
	return {"hp": hp, "expected": CombatSystemScript.is_dead(hp)}


func _make_kind(
	aggro_range: float,
	attack_range: float,
	attack_cooldown: float,
	keep_range_min: float,
	keep_range_max: float,
) -> EnemyConfigScript:
	var kind := EnemyConfigScript.new()
	kind.aggro_range = aggro_range
	kind.attack_range = attack_range
	kind.attack_cooldown = attack_cooldown
	kind.keep_range_min = keep_range_min
	kind.keep_range_max = keep_range_max
	return kind


func _move_case(
	self_pos: Array,
	player_pos: Array,
	aggro_range: float,
	keep_range_min: float,
	keep_range_max: float,
) -> Dictionary:
	var kind := _make_kind(aggro_range, 0.0, 0.0, keep_range_min, keep_range_max)
	var sp := Vector2(self_pos[0], self_pos[1])
	var pp := Vector2(player_pos[0], player_pos[1])
	return {
		"self_pos": self_pos,
		"player_pos": player_pos,
		"aggro_range": aggro_range,
		"keep_range_min": keep_range_min,
		"keep_range_max": keep_range_max,
		"expected": EnemyAIScript.compute_move_dir(sp, pp, kind),
	}


func _ready_case(last_attack_time: float, now: float, cooldown: float) -> Dictionary:
	return {
		"last_attack_time": last_attack_time,
		"now": now,
		"cooldown": cooldown,
		"expected": EnemyAIScript.is_attack_ready(last_attack_time, now, cooldown),
	}


func _can_attack_case(
	self_pos: Array,
	player_pos: Array,
	aggro_range: float,
	attack_range: float,
	attack_cooldown: float,
	last_attack_time: float,
	now: float,
) -> Dictionary:
	var kind := _make_kind(aggro_range, attack_range, attack_cooldown, 0.0, attack_range)
	var sp := Vector2(self_pos[0], self_pos[1])
	var pp := Vector2(player_pos[0], player_pos[1])
	return {
		"self_pos": self_pos,
		"player_pos": player_pos,
		"aggro_range": aggro_range,
		"attack_range": attack_range,
		"attack_cooldown": attack_cooldown,
		"last_attack_time": last_attack_time,
		"now": now,
		"expected": EnemyAIScript.can_attack(sp, pp, kind, last_attack_time, now),
	}


func _make_warp_kind(
	aggro_range: float, warp_trigger_range: float, warp_cooldown: float, warp_offset: Array
) -> EnemyConfigScript:
	var kind := EnemyConfigScript.new()
	kind.aggro_range = aggro_range
	kind.warp_trigger_range = warp_trigger_range
	kind.warp_cooldown = warp_cooldown
	kind.warp_offset = Vector2(warp_offset[0], warp_offset[1])
	return kind


func _should_warp_case(
	self_pos: Array,
	player_pos: Array,
	aggro_range: float,
	warp_trigger_range: float,
	warp_cooldown: float,
	last_warp_time: float,
	now: float,
) -> Dictionary:
	var kind := _make_warp_kind(aggro_range, warp_trigger_range, warp_cooldown, [0.0, 0.0])
	var sp := Vector2(self_pos[0], self_pos[1])
	var pp := Vector2(player_pos[0], player_pos[1])
	return {
		"self_pos": self_pos,
		"player_pos": player_pos,
		"aggro_range": aggro_range,
		"warp_trigger_range": warp_trigger_range,
		"warp_cooldown": warp_cooldown,
		"last_warp_time": last_warp_time,
		"now": now,
		"expected": WarpSystemScript.should_warp(sp, pp, kind, last_warp_time, now),
	}


func _warp_landing_case(
	self_pos: Array,
	player_pos: Array,
	warp_offset: Array,
	arena_min_x: float,
	arena_max_x: float,
) -> Dictionary:
	var kind := _make_warp_kind(0.0, 0.0, 1.0, warp_offset)
	var sp := Vector2(self_pos[0], self_pos[1])
	var pp := Vector2(player_pos[0], player_pos[1])
	var landing := WarpSystemScript.warp_landing(sp, pp, kind, arena_min_x, arena_max_x)
	return {
		"self_pos": self_pos,
		"player_pos": player_pos,
		"warp_offset": warp_offset,
		"arena_min_x": arena_min_x,
		"arena_max_x": arena_max_x,
		"expected": [landing.x, landing.y],
	}


func _inside_field_case(pos: Array, center: Array, radius: float) -> Dictionary:
	return {
		"pos": pos,
		"field_center": center,
		"radius": radius,
		"expected": WarpSystemScript.is_inside_field(
			Vector2(pos[0], pos[1]), Vector2(center[0], center[1]), radius
		),
	}


func _effective_defender_case(base_defense: float, defense_bonus: float) -> Dictionary:
	var base := StatsConfigScript.new()
	base.defense = base_defense
	var composed := ItemSystemScript.effective_defender(base, defense_bonus)
	return {
		"base_defense": base_defense,
		"defense_bonus": defense_bonus,
		"expected": composed.defense,
	}


func _build() -> Dictionary:
	return {
		"compute_damage": [
			_damage_case(10.0, 0.0, 2.0, 1.5, 1.0),  # zero defense -> undiminished
			_damage_case(10.0, 2.0, 2.0, 1.5, 1.0),  # mitigation subtracts defense
			_damage_case(1.0, 10.0, 2.0, 1.5, 1.0),  # floor: clamps to min_damage
			_damage_case(10.0, 0.0, 1.0, 1.0, 1.0),  # unit scales (game default)
			_damage_case(15.0, 5.0, 1.0, 1.0, 1.0),  # boss-tier stats
		],
		"is_invulnerable": [
			_invuln_case(10.0, 10.3, 0.6),  # within the window
			_invuln_case(10.0, 10.5, 0.5),  # exactly at expiry -> vulnerable
			_invuln_case(10.0, 11.0, 0.6),  # past the window
			_invuln_case(LONG_AGO, 0.0, 0.6),  # never-hit path
		],
		"is_dead": [
			_dead_case(0.0),  # dies at exactly 0
			_dead_case(-5.0),  # below 0 (overkill) is dead
			_dead_case(0.1),  # any positive HP is alive
			_dead_case(25.0),
		],
		"compute_move_dir": [
			_move_case([0.0, 0.0], [500.0, 0.0], 240.0, 0.0, 48.0),  # beyond aggro
			_move_case([0.0, 0.0], [100.0, 0.0], 240.0, 0.0, 48.0),  # close in (right)
			_move_case([100.0, 0.0], [0.0, 0.0], 240.0, 0.0, 48.0),  # close in (left)
			_move_case([0.0, 0.0], [160.0, 0.0], 260.0, 140.0, 200.0),  # hold in band
			_move_case([0.0, 0.0], [100.0, 0.0], 260.0, 140.0, 200.0),  # back off
			_move_case([0.0, 0.0], [0.0, 100.0], 240.0, 0.0, 48.0),  # directly above -> 0
			_move_case([0.0, 0.0], [40.0, 240.0], 240.0, 0.0, 48.0),  # 2D distance beyond aggro
		],
		"is_attack_ready": [
			_ready_case(0.0, 2.0, 1.0),  # elapsed > cooldown
			_ready_case(0.0, 0.5, 1.0),  # still cooling down
			_ready_case(0.0, 1.0, 1.0),  # exactly at expiry -> ready (>=)
			_ready_case(LONG_AGO, 0.0, 1.0),  # never-attacked path
		],
		"can_attack": [
			_can_attack_case([0.0, 0.0], [40.0, 0.0], 240.0, 48.0, 1.2, LONG_AGO, 5.0),  # in range & ready
			_can_attack_case([0.0, 0.0], [100.0, 0.0], 240.0, 48.0, 1.2, LONG_AGO, 5.0),  # out of attack range
			_can_attack_case([0.0, 0.0], [300.0, 0.0], 240.0, 400.0, 1.0, LONG_AGO, 5.0),  # beyond aggro
			_can_attack_case([0.0, 0.0], [40.0, 0.0], 240.0, 48.0, 2.0, 4.0, 5.0),  # cooling down
			_can_attack_case([0.0, 0.0], [230.0, 0.0], 260.0, 240.0, 1.6, LONG_AGO, 5.0),  # ranged in range
		],
		"should_warp": [
			_should_warp_case([700.0, 0.0], [400.0, 0.0], 400.0, 200.0, 8.0, LONG_AGO, 0.0),  # engage gate open
			_should_warp_case([700.0, 0.0], [550.0, 0.0], 400.0, 200.0, 8.0, LONG_AGO, 0.0),  # inside trigger: brawl
			_should_warp_case([700.0, 0.0], [200.0, 0.0], 400.0, 200.0, 8.0, LONG_AGO, 0.0),  # beyond aggro: dormant
			_should_warp_case([700.0, 0.0], [400.0, 0.0], 400.0, 200.0, 8.0, 0.0, 5.0),  # cooling down
			_should_warp_case([700.0, 0.0], [400.0, 0.0], 400.0, 200.0, 8.0, 0.0, 8.0),  # cooldown at expiry (>=)
			_should_warp_case([700.0, 0.0], [400.0, 0.0], 400.0, 200.0, 0.0, LONG_AGO, 0.0),  # no kit (cooldown 0)
		],
		"warp_landing": [
			_warp_landing_case([700.0, 0.0], [400.0, 0.0], [60.0, -32.0], -160.0, 1280.0),  # far side: left
			_warp_landing_case([100.0, 0.0], [400.0, 0.0], [60.0, -32.0], -160.0, 1280.0),  # far side: right
			_warp_landing_case([400.0, 100.0], [400.0, 0.0], [60.0, -32.0], -160.0, 1280.0),  # dx == 0 -> +x side
			_warp_landing_case([100.0, 0.0], [-180.0, 0.0], [60.0, -32.0], -160.0, 1280.0),  # clamped at arena min
			_warp_landing_case([100.0, 0.0], [1270.0, 0.0], [60.0, -32.0], -160.0, 1280.0),  # clamped at arena max
		],
		"is_inside_field": [
			_inside_field_case([0.0, 0.0], [60.0, 0.0], 160.0),  # inside
			_inside_field_case([160.0, 0.0], [0.0, 0.0], 160.0),  # exactly at the radius (<=)
			_inside_field_case([200.0, 0.0], [0.0, 0.0], 160.0),  # outside
			_inside_field_case([96.0, 128.0], [0.0, 0.0], 160.0),  # 2D distance at the radius
		],
		"effective_defender": [
			_effective_defender_case(0.0, 2.0),  # the game's shape: base 0 + Spacesuit
			_effective_defender_case(4.0, 2.0),  # a real base composes additively
			_effective_defender_case(3.0, 0.0),  # zero bonus is the identity
		],
	}


func _init() -> void:
	var out_dir := OS.get_environment("BALANCING_FIXTURES_DIR")
	if out_dir.is_empty():
		print("FIXTURE_FAIL: BALANCING_FIXTURES_DIR not set")
		quit(1)
		return
	var text := JSON.stringify(_build(), "  ")
	var path := out_dir.path_join("seams.json")
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		print("FIXTURE_FAIL: could not open ", path)
		quit(1)
		return
	file.store_string(text + "\n")
	file.close()
	print("FIXTURES_DONE")
	quit(0)
