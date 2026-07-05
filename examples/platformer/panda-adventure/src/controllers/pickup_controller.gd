class_name PickupController
extends Area2D

## One dropped Pickup block (S6b, gADR-0006): carries one resolved drop
## ({item, amount}) from a defeated Enemy's Drop table, sitting in the world
## until the Player walks into it. On contact it hands the drop to the
## Player's collect_drop (gold -> the Player's Gold, an item -> the S6b item
## count hook), disarms itself, and shrinks away.
##
## The drop is INJECTED by the spawner via setup() before add_child (the
## EnemyController pattern), so one scene serves every item. The blockout
## (per-item color/size), the spawn squash, and the collect shrink are data
## (gADR-0000): the derived ProgressionConfig Resource, never hardcoded. The
## decision of WHAT dropped was the pure EconomySystem's (rolled by the
## spawner); this controller only orchestrates — blockout, tweens, contact
## delivery, and logs. Cross-script references use preload() (no editor
## class cache in this never-imported project).
##
## Collision: ON the pickup layer (6), masking ONLY the player layer (2) —
## enemies, bolts, and Gravity Fields never touch a Pickup, and the Pickup
## blocks nothing (an Area2D overlap, not a body).

const ProgressionConfigScript := preload("res://src/resources/progression_config.gd")
const GameLogScript := preload("res://src/util/game_log.gd")

const PROGRESSION_CONFIG_PATH := "res://data/generated/progression_config.tres"

var _item := ""
var _amount := 0
var _config: ProgressionConfigScript
# Collected latch: contact delivers the drop exactly once (the tween-out
# keeps the node in the tree for a moment after).
var _collected := false


## Hand this Pickup its resolved drop. Called by the spawner BEFORE
## add_child, so _ready sees the drop (the EnemyController setup() pattern).
func setup(item: String, amount: int) -> void:
	_item = item
	_amount = amount


func _ready() -> void:
	_config = load(PROGRESSION_CONFIG_PATH)
	if _config == null or _item.is_empty():
		# The derived .tres is committed and the spawner must setup() first;
		# guard loudly rather than crash, pointing at the pipeline.
		push_error(
			"PickupController: missing drop (setup() before add_child) or %s — run scripts/build_config.py."
			% PROGRESSION_CONFIG_PATH
		)
		return
	_apply_blockout()
	body_entered.connect(_on_body_entered)
	_play_spawn_tween()
	GameLogScript.emit("info", "pickup_spawned", {
		"item": _item,
		"amount": _amount,
		"x": position.x,
		"y": position.y,
	})


## Apply the item's data-driven blockout: the pickup block (visual +
## collision centered on the area origin) styled per drop_items[item]. The
## collision shape is CREATED here (the EnemyController pattern — gda cannot
## author inline sub-resources, #365), so the scene ships shape=null.
func _apply_blockout() -> void:
	var style: Dictionary = _config.drop_items[_item]
	var size: Vector2 = style["size"]
	var half := size / 2.0

	var visual := $Visual as ColorRect
	visual.color = style["color"]
	visual.size = size
	visual.position = -half
	visual.pivot_offset = half  # scale/tween about the block center

	var shape := RectangleShape2D.new()
	shape.size = size
	($Collision as CollisionShape2D).shape = shape


## The Player walked into this Pickup (the mask admits nothing else): deliver
## the drop exactly once, disarm, and shrink away. The Player owns the
## accumulation and its log (gold_collected / item_collected); this node just
## hands the drop over.
func _on_body_entered(body: Node2D) -> void:
	if _collected or not body.has_method("collect_drop"):
		return
	_collected = true
	set_deferred("monitoring", false)
	body.collect_drop(_item, _amount)
	_play_collect_tween()


## The spawn telegraph: punch the block's scale from the config squash and
## tween back to normal (the gADR-0005 spawn idiom).
func _play_spawn_tween() -> void:
	var visual := $Visual as ColorRect
	visual.scale = _config.pickup_spawn_squash
	var tween := create_tween()
	var recover := tween.tween_property(visual, "scale", Vector2.ONE, _config.pickup_spawn_tween_duration)
	recover.set_trans(Tween.TRANS_SINE)


## The collect "juice": shrink the block to nothing, then free the node (a
## property-tween, per the GDD — no sprite frames).
func _play_collect_tween() -> void:
	var visual := $Visual as ColorRect
	var tween := create_tween()
	var shrink := tween.tween_property(
		visual, "scale", Vector2.ZERO, _config.pickup_collect_tween_duration
	)
	shrink.set_trans(Tween.TRANS_SINE)
	tween.tween_callback(queue_free)
