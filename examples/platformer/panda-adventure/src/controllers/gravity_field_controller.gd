class_name GravityFieldController
extends Area2D

## Drives one Gravity Field: the localized region of altered gravity the
## Gravity Gun spawns. Each physics frame it feeds its data-driven field
## velocity to every overlapping gravity-affectable body — the gADR-0002
## response contract: bodies opt in via the "gravity_affectable" group and
## `apply_gravity_field(field_velocity, delta)`; the field calls the method,
## the body integrates the velocity its own way.
##
## It NEVER acts on the Player — collision topology, not code: the field sits
## on layer 5 `gravity_field` and masks terrain|enemy only, so the Player's
## layer is invisible to it (the Projectile's mask-guarantee pattern). Plain
## terrain (the Platform) does overlap and is filtered out by should_affect
## (group + method, the full opt-in contract).
##
## Everything numeric is data (gADR-0000): the derived GravityConfig. The
## EFFECT is data too (gADR-0002): velocity = direction x strength, bounded by
## radius (CircleShape2D) and duration — lift is the shipped default,
## slam/redirect are config values. The blockout "animation" is the spawn
## fade-in / expiry fade-out modulate tween (property interpolation, GDD).
## Cross-script references use preload() (no editor class cache in this
## never-imported project).

const GravityConfigScript := preload("res://src/resources/gravity_config.gd")
const GravitySystemScript := preload("res://src/systems/gravity_system.gd")
const GameLogScript := preload("res://src/util/game_log.gd")
const GeneratedConfigScript := preload("res://src/util/generated_config.gd")
const ViewBuilderScript := preload("res://src/view/view_builder.gd")

const CONFIG_PATH := "res://data/generated/gravity_config.tres"

var _config: GravityConfigScript
var _field_velocity := Vector2.ZERO


func _ready() -> void:
	_config = GeneratedConfigScript.load_config(CONFIG_PATH)
	if _config == null:
		queue_free()
		return
	_field_velocity = GravitySystemScript.compute_field_velocity(
		_config.field_direction, _config.field_strength
	)
	_apply_blockout(_config)
	_play_spawn_tween()
	# Bounded lifetime: act for field_duration, then fade out and free.
	get_tree().create_timer(_config.field_duration).timeout.connect(_expire)
	GameLogScript.emit("info", "gravity_field_spawned", {
		"x": position.x,
		"y": position.y,
		"velocity_x": _field_velocity.x,
		"velocity_y": _field_velocity.y,
		"radius": _config.field_radius,
		"duration": _config.field_duration,
	})


## Pure contract filter (gADR-0002): a body is affected only when it opted in
## on BOTH axes — "gravity_affectable" group membership AND the
## apply_gravity_field method. Either alone is not the contract: a same-named
## method on a non-member must not be driven, and a member without the method
## has nothing to call. Static and field-state-free so the logic seam exercises
## exactly the rule the overlap loop runs.
static func should_affect(body: Node) -> bool:
	return body.is_in_group("gravity_affectable") and body.has_method("apply_gravity_field")


## Feed the field velocity to every overlapping gravity-affectable body, each
## physics frame while the field is live. Per-frame — so NOT logged (spawn and
## expiry are the log events; gda logger tail must stay legible, not per-frame
## spam). should_affect — group AND method — is the contract filter (gADR-0002);
## the mask already guarantees the Player is never among the overlaps.
func _physics_process(delta: float) -> void:
	if _config == null:
		return
	for body in get_overlapping_bodies():
		if should_affect(body):
			body.apply_gravity_field(_field_velocity, delta)


## Apply the data-driven blockout through the shared view seam (ViewBuilder,
## #436): a translucent square block over a circular collision area of the config
## radius, both centered on the Area2D origin.
func _apply_blockout(config: GravityConfigScript) -> void:
	ViewBuilderScript.apply_circle(self, config.field_color, config.field_radius)


## The blockout "animation", spawn half: fade the field block in from
## transparent to its config color (a property-tween, per the GDD).
func _play_spawn_tween() -> void:
	var visual := $Visual as ColorRect
	visual.modulate.a = 0.0
	var tween := create_tween()
	tween.tween_property(visual, "modulate:a", 1.0, _config.field_fade_duration)


## Expiry: stop acting IMMEDIATELY (field_duration bounds the effect window;
## the fade-out after it is visual only), then tween the block out and free.
func _expire() -> void:
	set_physics_process(false)
	GameLogScript.emit("info", "gravity_field_expired", {"x": position.x, "y": position.y})
	var tween := create_tween()
	tween.tween_property($Visual, "modulate:a", 0.0, _config.field_fade_duration)
	tween.tween_callback(queue_free)
