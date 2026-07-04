class_name ObstacleController
extends StaticBody2D

## Drives the S3 Obstacle block: a gravity-affectable environment prop, floating
## on the terrain layer, that a Gravity Field can lift/slam/redirect. It applies
## its data-driven blockout + placement in _ready and joins the
## "gravity_affectable" group — the gADR-0002 response contract — integrating
## the field velocity as clamped position displacement (the pure decision in
## GravitySystem). It never moves on its own and damages nothing.
##
## All numbers come from the derived GravityConfig (gADR-0000). Cross-script
## references use preload() (no editor class cache in this never-imported
## project).

const GravityConfigScript := preload("res://src/resources/gravity_config.gd")
const GravitySystemScript := preload("res://src/systems/gravity_system.gd")
const GameLogScript := preload("res://src/util/game_log.gd")

const CONFIG_PATH := "res://data/generated/gravity_config.tres"

var _config: GravityConfigScript
# Total displacement Gravity Fields have accumulated on this body — clamped at
# config.obstacle_max_gravity_offset (gADR-0002), so it can never leave level.
var _gravity_offset := Vector2.ZERO


func _ready() -> void:
	_config = load(CONFIG_PATH)
	if _config == null:
		# The derived .tres is committed; guard loudly rather than crash on a
		# half-checkout, pointing at the pipeline that regenerates it from JSON.
		push_error(
			"ObstacleController: could not load %s — run scripts/build_config.py." % CONFIG_PATH
		)
		return
	position = _config.obstacle_position
	_apply_blockout(_config)
	add_to_group("gravity_affectable")
	GameLogScript.emit("info", "obstacle_ready", {"x": position.x, "y": position.y})


## Gravity-response contract (gADR-0002): a Gravity Field feeds this body its
## field velocity each overlapping physics frame; this static block integrates
## it as clamped position displacement.
func apply_gravity_field(field_velocity: Vector2, delta: float) -> void:
	if _config == null:
		return
	var next := GravitySystemScript.compute_clamped_offset(
		_gravity_offset, field_velocity, delta, _config.obstacle_max_gravity_offset
	)
	position += next - _gravity_offset
	_gravity_offset = next


## Apply the data-driven blockout: the Obstacle block centered on the body
## origin. The collision shape is CREATED here (RectangleShape2D.new sized from
## config): gda cannot author inline sub-resources (#365), so the scene ships
## shape=null.
func _apply_blockout(config: GravityConfigScript) -> void:
	var half := config.obstacle_size / 2.0

	var visual := $Visual as ColorRect
	visual.color = config.obstacle_color
	visual.size = config.obstacle_size
	visual.position = -half

	var shape := RectangleShape2D.new()
	shape.size = config.obstacle_size
	($Collision as CollisionShape2D).shape = shape
