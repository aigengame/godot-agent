class_name ProjectileController
extends Area2D

## Drives one Laser Gun bolt: applies its data-driven blockout in _ready, flies
## in a straight line, and resolves the FIRST body it overlaps — an Enemy takes
## the hit (duck-typed take_hit), terrain just stops it — then despawns. An
## unhit bolt despawns after its config lifetime.
##
## Collision topology (project.godot [layer_names]): layer=projectile(8),
## mask=terrain|enemy(5) — a bolt can never hit the Player or another bolt, so
## the mask, not code, is what guarantees body is terrain or an Enemy.
##
## The bolt is an Area2D on purpose: it needs overlap detection with zero
## physics response (no gravity, no sliding, no pushing) — motion is manual in
## _physics_process. All numbers come from the derived CombatConfig (gADR-0000);
## the attacker's stat block is INJECTED by the shooter via setup() before the
## bolt enters the tree, so the damage formula reads real attacker stats
## (gADR-0001). Cross-script references use preload() (no editor class cache).

const StatsConfigScript := preload("res://src/resources/stats_config.gd")
const CombatConfigScript := preload("res://src/resources/combat_config.gd")

const CONFIG_PATH := "res://data/generated/combat_config.tres"

var _config: CombatConfigScript
var _direction := Vector2.RIGHT
var _attacker: StatsConfigScript


## Aim the bolt and hand it the attacker's stat block. Called by the shooter
## BEFORE add_child, so _ready sees both.
func setup(direction: Vector2, attacker: StatsConfigScript) -> void:
	_direction = direction
	_attacker = attacker


func _ready() -> void:
	_config = load(CONFIG_PATH)
	if _config == null:
		# The derived .tres is committed; guard loudly rather than crash on a
		# half-checkout, pointing at the pipeline that regenerates it from JSON.
		push_error(
			"ProjectileController: could not load %s — run scripts/build_config.py." % CONFIG_PATH
		)
		queue_free()
		return
	_apply_blockout(_config)
	body_entered.connect(_on_body_entered)
	# Lifetime despawn. The timeout connection is dropped automatically if the
	# bolt was already freed by a hit (Godot disconnects a freed target).
	get_tree().create_timer(_config.projectile_lifetime).timeout.connect(queue_free)


func _physics_process(delta: float) -> void:
	if _config == null:
		return
	position += _direction * _config.projectile_speed * delta


## Apply the data-driven blockout: the bolt block centered on the Area2D origin.
## The collision shape is CREATED here (RectangleShape2D.new sized from config):
## gda cannot author inline sub-resources (#365), so the scene ships shape=null.
func _apply_blockout(config: CombatConfigScript) -> void:
	var half := config.projectile_size / 2.0

	var visual := $Visual as ColorRect
	visual.color = config.projectile_color
	visual.size = config.projectile_size
	visual.position = -half

	var shape := RectangleShape2D.new()
	shape.size = config.projectile_size
	($Collision as CollisionShape2D).shape = shape


func _on_body_entered(body: Node2D) -> void:
	# The mask guarantees body is terrain or an Enemy; only an Enemy can take a
	# hit. Either way the bolt is spent — one bolt, at most one hit.
	if body.has_method("take_hit"):
		body.take_hit(_attacker)
	queue_free()
