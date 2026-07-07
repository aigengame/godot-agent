class_name TimeFieldController
extends Area2D

## Drives one Time Dilation Field: the static, duration-bound slow zone the
## Boss's Warp Blink drops at its landing (S8, gADR-0009) — the time-warp
## mirror of the Gravity Field (the Player bends gravity, the Boss bends
## time). Each physics frame it sets the config time factor on every
## overlapping time-dilatable node and RESETS a node to 1.0 the frame it
## leaves — the opt-in response contract mirroring gADR-0002: nodes join the
## "time_dilatable" group and implement `set_time_dilation(factor)`.
##
## It slows the PLAYER's side only — collision topology plus contract, the
## inverse of the Gravity Field's never-the-Player mask: the field sits on
## layer 7 `time_field` and masks player|projectile, so enemies never
## overlap; and of the projectiles only the Player's laser bolts opt into the
## group (the enemy-bolt scene variant never joins), so the contract filter
## excludes them. The Boss, the Gravity Gun, and everything else run at full
## speed by design (gADR-0009).
##
## Everything numeric is data (gADR-0000): the field is configure()d from the
## casting kind's EnemyConfig warp block by the spawner BEFORE add_child (the
## Projectile setup() pattern), so one scene serves any Warp kind. The
## blockout "animation" is the spawn fade-in / expiry fade-out modulate tween
## (the Gravity Field's visual pattern).

const EnemyConfigScript := preload("res://src/resources/enemy_config.gd")
const GameLogScript := preload("res://src/util/game_log.gd")
const ViewBuilderScript := preload("res://src/view/view_builder.gd")

var _radius := 0.0
var _factor := 1.0
var _duration := 0.0
var _color := Color.WHITE
var _fade_duration := 0.0
# The nodes this field set a factor on last physics frame (instance id ->
# node): the diff against the current overlaps is what RESETS a leaver to
# 1.0 — the exit half of the contract.
var _affected: Dictionary = {}


## Hand this field its casting kind's warp block. Called by the spawner
## BEFORE add_child, so _ready sees the numbers.
func configure(kind: EnemyConfigScript) -> void:
	_radius = kind.time_field_radius
	_factor = kind.time_field_factor
	_duration = kind.time_field_duration
	_color = kind.time_field_color
	_fade_duration = kind.time_field_fade_duration


func _ready() -> void:
	if _radius <= 0.0:
		# The spawner must configure() first; guard loudly rather than run a
		# zero-radius no-op field.
		push_error("TimeFieldController: configure() must run before add_child.")
		queue_free()
		return
	_apply_blockout()
	_play_spawn_tween()
	# Bounded lifetime: act for the config duration, then release and free.
	get_tree().create_timer(_duration).timeout.connect(_expire)
	GameLogScript.emit("info", "time_field_spawned", {
		"x": position.x,
		"y": position.y,
		"radius": _radius,
		"factor": _factor,
		"duration": _duration,
	})


## Pure contract filter (the gADR-0002 shape): a node is affected only when
## it opted in on BOTH axes — "time_dilatable" group membership AND the
## set_time_dilation method. Static and field-state-free so the logic seam
## could exercise exactly the rule the overlap loop runs.
static func should_affect(node: Node) -> bool:
	return node.is_in_group("time_dilatable") and node.has_method("set_time_dilation")


## Set the factor on every overlapping time-dilatable node and reset the
## ones that left, each physics frame while the field is live. Per-frame —
## so NOT logged here (spawn and expiry are the field's log events; the
## affected node logs its own dilation EDGE, so gda logger tail stays
## legible, not per-frame spam). Bodies (the Player) and areas (laser bolts)
## both participate: the bolt scene is an Area2D.
func _physics_process(_delta: float) -> void:
	var current: Dictionary = {}
	for node in get_overlapping_bodies() + get_overlapping_areas():
		if should_affect(node):
			current[node.get_instance_id()] = node
			node.set_time_dilation(_factor)
	for id in _affected:
		if not current.has(id):
			var leaver: Node = _affected[id]
			if is_instance_valid(leaver):
				leaver.set_time_dilation(1.0)
	_affected = current


## Apply the data-driven blockout through the shared view seam (ViewBuilder,
## #436): a translucent square block over a circular collision area of the config
## radius, both centered on the Area2D origin (the Gravity Field's blockout shape).
func _apply_blockout() -> void:
	ViewBuilderScript.apply_circle(self, _color, _radius)


## The blockout "animation", spawn half: fade the zone in from transparent
## to its config color (a property-tween, per the GDD).
func _play_spawn_tween() -> void:
	var visual := $Visual as ColorRect
	visual.modulate.a = 0.0
	var tween := create_tween()
	tween.tween_property(visual, "modulate:a", 1.0, _fade_duration)


## Expiry: stop acting IMMEDIATELY and release every still-affected node back
## to full speed (the duration bounds the effect window; the fade-out after
## it is visual only), then tween the block out and free.
func _expire() -> void:
	set_physics_process(false)
	for id in _affected:
		var node: Node = _affected[id]
		if is_instance_valid(node):
			node.set_time_dilation(1.0)
	_affected = {}
	GameLogScript.emit("info", "time_field_expired", {"x": position.x, "y": position.y})
	var tween := create_tween()
	tween.tween_property($Visual, "modulate:a", 0.0, _fade_duration)
	tween.tween_callback(queue_free)
