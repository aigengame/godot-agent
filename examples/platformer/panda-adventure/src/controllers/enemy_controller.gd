class_name EnemyController
extends StaticBody2D

## Drives the S2 static Enemy block: applies its data-driven blockout in _ready,
## owns its live StatsSystem, and resolves incoming hits — i-frame gate, the
## symmetric damage formula, a hit-flash property tween (the blockout
## "animation"), and death at 0 HP (died signal + removal). It does not move or
## attack; Archetype AI and enemy->Player damage are S4.
##
## Decisions stay PURE (CombatSystem, gADR-0001): this controller only
## orchestrates — it reads the real clock, mutates its StatsSystem, tweens, and
## logs. Stats and every number come from the derived StatsConfig/CombatConfig
## Resources (gADR-0000). Cross-script references use preload() (no editor
## class cache in this never-imported project).

signal died

const StatsConfigScript := preload("res://src/resources/stats_config.gd")
const CombatConfigScript := preload("res://src/resources/combat_config.gd")
const StatsSystemScript := preload("res://src/systems/stats_system.gd")
const CombatSystemScript := preload("res://src/systems/combat_system.gd")
const GameLogScript := preload("res://src/util/game_log.gd")

const STATS_PATH := "res://data/generated/stats_enemy.tres"
const CONFIG_PATH := "res://data/generated/combat_config.tres"

var _stats_config: StatsConfigScript
var _combat: CombatConfigScript
var _stats: StatsSystemScript
# When this defender last took a hit (seconds). -INF = never hit, so the first
# hit always lands (CombatSystem.is_invulnerable's sentinel contract).
var _last_hit_time := -INF


func _ready() -> void:
	_stats_config = load(STATS_PATH)
	_combat = load(CONFIG_PATH)
	if _stats_config == null or _combat == null:
		# The derived .tres are committed; guard loudly rather than crash on a
		# half-checkout, pointing at the pipeline that regenerates them from JSON.
		push_error(
			"EnemyController: could not load %s / %s — run scripts/build_config.py."
			% [STATS_PATH, CONFIG_PATH]
		)
		return
	_stats = StatsSystemScript.new()
	_stats.init_from(_stats_config)
	_apply_blockout(_combat)
	GameLogScript.emit("info", "enemy_ready", {
		"max_hp": _stats_config.max_hp,
		"x": position.x,
		"y": position.y,
	})


## Resolve one incoming hit from an attacker's stat block. Inside the i-frame
## window the hit is ignored — a single overlap cannot chain hits across frames.
func take_hit(attacker: StatsConfigScript) -> void:
	if _stats == null:
		return
	var now := _now()
	if CombatSystemScript.is_invulnerable(_last_hit_time, now, _combat.iframe_duration):
		return
	_last_hit_time = now
	var damage := CombatSystemScript.compute_damage(attacker, _stats_config, _combat)
	_stats.apply_damage(damage)
	GameLogScript.emit("info", "enemy_hit", {"damage": damage, "hp_left": _stats.hp})
	_play_hit_flash()
	if CombatSystemScript.is_dead(_stats.hp):
		died.emit()
		GameLogScript.emit("info", "enemy_died", {"x": position.x, "y": position.y})
		queue_free()


## The runtime clock feeding the pure i-frame decision; the Monte-Carlo sim
## supplies its own simulated time instead.
func _now() -> float:
	return Time.get_ticks_msec() / 1000.0


## Apply the data-driven blockout: the Enemy block centered on the body origin.
## The collision shape is CREATED here (RectangleShape2D.new sized from config):
## gda cannot author inline sub-resources (#365), so the scene ships shape=null.
func _apply_blockout(config: CombatConfigScript) -> void:
	var half := config.enemy_size / 2.0

	var visual := $Visual as ColorRect
	visual.color = config.enemy_color
	visual.size = config.enemy_size
	visual.position = -half

	var shape := RectangleShape2D.new()
	shape.size = config.enemy_size
	($Collision as CollisionShape2D).shape = shape


## The blockout "animation": flash the block to the hit color and tween back to
## its own color (a property-tween, per the GDD — the S2 sibling of S1's
## landing squash).
func _play_hit_flash() -> void:
	var visual := $Visual as ColorRect
	visual.color = _combat.hit_flash_color
	var tween := create_tween()
	var recover := tween.tween_property(
		visual, "color", _combat.enemy_color, _combat.hit_flash_duration
	)
	recover.set_trans(Tween.TRANS_SINE)
