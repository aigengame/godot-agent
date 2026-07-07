class_name ProjectileController
extends Area2D

## Drives one bolt: applies its data-driven blockout in _ready, flies in a
## straight line, and resolves the FIRST body it overlaps — a body with
## take_hit takes the hit (duck-typed), terrain just stops it — then despawns.
## An unhit bolt despawns after its config lifetime.
##
## ONE controller, two scene variants that differ only in collision topology
## (project.godot [layer_names]): projectile.tscn is the Laser Gun bolt
## (layer=projectile(8), mask=terrain|enemy(5)); enemy_projectile.tscn is the
## S4 Ranged enemy bolt (same layer, mask=terrain|player(3)). The mask, not
## code, is what guarantees a bolt can only hit its targets — never its own
## side, never another bolt.
##
## The bolt is an Area2D on purpose: it needs overlap detection with zero
## physics response — motion is manual in _physics_process. The attacker's stat
## block is INJECTED by the shooter via setup() before the bolt enters the
## tree, so the damage formula reads real attacker stats (gADR-0001). The
## blockout+motion params default to the derived CombatConfig (the Laser Gun
## bolt, gADR-0000); a Ranged enemy overrides them per kind via configure()
## (also before add_child) — data-driven either way, no numbers here.
## Cross-script references use preload() (no editor class cache).

const StatsConfigScript := preload("res://src/resources/stats_config.gd")
const CombatConfigScript := preload("res://src/resources/combat_config.gd")
const GeneratedConfigScript := preload("res://src/util/generated_config.gd")
const ViewBuilderScript := preload("res://src/view/view_builder.gd")

const CONFIG_PATH := "res://data/generated/combat_config.tres"

var _direction := Vector2.RIGHT
var _attacker: StatsConfigScript
var _color: Color
var _size: Vector2
# The bolt's optional view asset reference (P2-S2, #436): resolved by the view
# seam — authored empty today, so the block fallback.
var _asset := ""
var _speed: float
var _lifetime: float
var _configured := false
# The time scale a Time Dilation Field imposes (S8, gADR-0009): 1.0 = full
# speed. Only the Player's bolt variant joins the "time_dilatable" group (the
# shooter opts it in), so an enemy bolt never receives this.
var _time_dilation := 1.0


## Aim the bolt and hand it the attacker's stat block. Called by the shooter
## BEFORE add_child, so _ready sees both.
func setup(direction: Vector2, attacker: StatsConfigScript) -> void:
	_direction = direction
	_attacker = attacker


## Override the bolt's blockout + motion (the S4 Ranged enemy's per-kind bolt).
## Called BEFORE add_child; a bolt never configured falls back to the
## CombatConfig Laser Gun params in _ready. `asset` is the bolt's config-fed
## view asset reference (P2-S2, #436).
func configure(
	color: Color, size: Vector2, speed: float, lifetime: float, asset: String = ""
) -> void:
	_color = color
	_size = size
	_speed = speed
	_lifetime = lifetime
	_asset = asset
	_configured = true


func _ready() -> void:
	if not _configured:
		var config: CombatConfigScript = GeneratedConfigScript.load_config(CONFIG_PATH)
		if config == null:
			queue_free()
			return
		configure(
			config.projectile_color,
			config.projectile_size,
			config.projectile_speed,
			config.projectile_lifetime,
			config.projectile_asset,
		)
	_apply_blockout()
	body_entered.connect(_on_body_entered)
	# Lifetime despawn. The timeout connection is dropped automatically if the
	# bolt was already freed by a hit (Godot disconnects a freed target).
	get_tree().create_timer(_lifetime).timeout.connect(queue_free)


## Time-dilation response contract (S8, gADR-0009): a Time Dilation Field
## slows the bolt's flight while it overlaps; despawn (the lifetime timer)
## stays on the real clock — a slowed bolt flies shorter, it does not linger.
func set_time_dilation(factor: float) -> void:
	_time_dilation = factor


func _physics_process(delta: float) -> void:
	if not _configured:
		return
	position += _direction * _speed * _time_dilation * delta


## Apply the data-driven blockout through the shared view seam (ViewBuilder,
## #436): the bolt block centered on the Area2D origin. No pivot — a bolt flies
## straight and never scale-tweens. The configured asset reference feeds the
## seam's resolution — authored empty today, so the block.
func _apply_blockout() -> void:
	ViewBuilderScript.apply_box(self, _color, _size, false, _asset)


func _on_body_entered(body: Node2D) -> void:
	# The mask guarantees body is terrain or a target; only a target can take a
	# hit. Either way the bolt is spent — one bolt, at most one hit.
	if body.has_method("take_hit"):
		body.take_hit(_attacker)
	queue_free()
