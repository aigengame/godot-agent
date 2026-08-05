extends SceneTree

## Logic seam for the P2-S2 view-construction seam (ViewBuilder, #436): exercise
## the ONE shared blockout builder headless — the path every controller's
## `_apply_blockout` now routes through — by building synthetic Visual/Collision
## node pairs and pinning the EXACT view it produces.
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_view_builder_logic.gd
##
## Covers the shipped block fallback exhaustively (box with/without the center
## pivot, and the circle field shape), so "renders exactly as before P2-S2" is
## pinned; and the asset-reference resolution branch (a non-empty asset is the
## resolved sprite path, so the seam loads the texture and renders a Sprite child —
## asset references are data, gADR-0000; #439). preload() the seam (a headless
## runtime has no editor-generated global_script_class_cache). Prints "LOGIC_SEAM:
## PASS" + quit(0) on success, else push_error + quit(1).

const ViewBuilderScript := preload("res://content/presentation/view_builder.gd")

const EPS := 0.0001


func _fail(msg: String) -> void:
	push_error("LOGIC_SEAM: " + msg)
	quit(1)


## A fresh detached root carrying the "Visual" (ColorRect) + "Collision"
## (CollisionShape2D) pair every blockout scene ships — the shape the seam
## configures. Not added to the SceneTree root: get_node resolves on the local
## children regardless.
func _make_root() -> Node:
	var root := Node2D.new()
	var visual := ColorRect.new()
	visual.name = "Visual"
	root.add_child(visual)
	var collision := CollisionShape2D.new()
	collision.name = "Collision"
	root.add_child(collision)
	return root


func _vec_eq(a: Vector2, b: Vector2) -> bool:
	return a.is_equal_approx(b)


func _init() -> void:
	if not _check_box_with_pivot():
		return
	if not _check_box_without_pivot():
		return
	if not _check_circle():
		return
	if not _check_asset_resolution():
		return
	if not _check_sprite_frames_resolution():
		return
	print("LOGIC_SEAM: PASS")
	quit(0)


## A box blockout with the center pivot (the actors that scale-tween): color,
## size, center position, center pivot_offset, and a RectangleShape2D of the same
## size on the Collision.
func _check_box_with_pivot() -> bool:
	var root := _make_root()
	var color := Color(0.2, 0.4, 0.6, 1.0)
	var size := Vector2(48, 32)
	ViewBuilderScript.apply_box(root, color, size, true)

	var visual := root.get_node("Visual") as ColorRect
	if visual.color != color:
		_fail("box: visual.color %s != %s" % [visual.color, color])
		return false
	if not _vec_eq(visual.size, size):
		_fail("box: visual.size %s != %s" % [visual.size, size])
		return false
	if not _vec_eq(visual.position, -size / 2.0):
		_fail("box: visual.position %s != %s" % [visual.position, -size / 2.0])
		return false
	if not _vec_eq(visual.pivot_offset, size / 2.0):
		_fail("box: visual.pivot_offset %s != %s" % [visual.pivot_offset, size / 2.0])
		return false

	var shape := (root.get_node("Collision") as CollisionShape2D).shape
	if not (shape is RectangleShape2D):
		_fail("box: collision shape is not a RectangleShape2D (%s)" % shape)
		return false
	if not _vec_eq((shape as RectangleShape2D).size, size):
		_fail("box: shape.size %s != %s" % [(shape as RectangleShape2D).size, size])
		return false
	root.free()
	return true


## A box blockout WITHOUT the pivot (the static props / straight-flying bolts):
## same block, but pivot_offset stays at the ColorRect default (0,0).
func _check_box_without_pivot() -> bool:
	var root := _make_root()
	var size := Vector2(12, 20)
	ViewBuilderScript.apply_box(root, Color.RED, size)

	var visual := root.get_node("Visual") as ColorRect
	if not _vec_eq(visual.position, -size / 2.0):
		_fail("box-no-pivot: visual.position %s != %s" % [visual.position, -size / 2.0])
		return false
	if not _vec_eq(visual.pivot_offset, Vector2.ZERO):
		_fail("box-no-pivot: pivot_offset %s must stay default (0,0)" % visual.pivot_offset)
		return false
	if not _vec_eq(visual.size, size):
		_fail("box-no-pivot: visual.size %s != %s" % [visual.size, size])
		return false
	root.free()
	return true


## A circle blockout (Gravity/Time Field): the Visual is the enclosing 2·radius
## square centered on the origin; the Collision is a CircleShape2D of the radius.
func _check_circle() -> bool:
	var root := _make_root()
	var color := Color(0.1, 0.9, 0.3, 0.5)
	var radius := 64.0
	ViewBuilderScript.apply_circle(root, color, radius)

	var visual := root.get_node("Visual") as ColorRect
	var side := radius * 2.0
	if visual.color != color:
		_fail("circle: visual.color %s != %s" % [visual.color, color])
		return false
	if not _vec_eq(visual.size, Vector2(side, side)):
		_fail("circle: visual.size %s != %s" % [visual.size, Vector2(side, side)])
		return false
	if not _vec_eq(visual.position, -Vector2(radius, radius)):
		_fail("circle: visual.position %s != %s" % [visual.position, -Vector2(radius, radius)])
		return false

	var shape := (root.get_node("Collision") as CollisionShape2D).shape
	if not (shape is CircleShape2D):
		_fail("circle: collision shape is not a CircleShape2D (%s)" % shape)
		return false
	if absf((shape as CircleShape2D).radius - radius) > EPS:
		_fail("circle: shape.radius %s != %s" % [(shape as CircleShape2D).radius, radius])
		return false
	root.free()
	return true


## The asset-reference resolution (gADR-0000: asset references are data; #439): a
## non-empty asset reference is the RESOLVED sprite path (the builder composed the
## Asset manifest id -> res:// path, gADR-0014), so the seam loads the texture and
## renders it as a "Sprite" TextureRect child of a transparent Visual frame — NOT
## the colored block. Pinned against the committed tracer texture (the Obstacle
## crate), which doubles as a headless load-and-import smoke of that asset.
func _check_asset_resolution() -> bool:
	var root := _make_root()
	var asset := "res://content/assets/textures/obstacle_crate.png"
	var size := Vector2(40, 40)
	ViewBuilderScript.apply_box(root, Color.WHITE, size, false, asset)

	var visual := root.get_node("Visual") as ColorRect
	# The Visual is sized/positioned like any block, but colored transparent — the
	# sprite is the visual now.
	if not _vec_eq(visual.size, size):
		_fail("asset: visual.size %s != %s" % [visual.size, size])
		return false
	if not _vec_eq(visual.position, -size / 2.0):
		_fail("asset: visual.position %s != %s" % [visual.position, -size / 2.0])
		return false
	if visual.color.a != 0.0:
		_fail("asset: visual must be a transparent frame, got color %s" % visual.color)
		return false
	# The resolved texture renders as a "Sprite" TextureRect child of the Visual,
	# scaled to the block size (the postprocess stage conformed it to that size).
	var sprite := visual.get_node_or_null("Sprite") as TextureRect
	if sprite == null:
		_fail("asset: no 'Sprite' TextureRect child was added for the asset branch")
		return false
	if sprite.texture == null:
		_fail("asset: the Sprite's texture is null (the tracer asset failed to load)")
		return false
	if not _vec_eq(sprite.size, size):
		_fail("asset: sprite.size %s != %s" % [sprite.size, size])
		return false
	root.free()
	return true


## The ANIMATED-sprite resolution branch (P2-S5, #443): a reference that resolves
## to a SpriteFrames (the committed Player set) renders as an "AnimatedSprite2D"
## child of a transparent Visual frame — NOT the static "Sprite" TextureRect and NOT
## the colored block. Pins the second dispatch branch headless and doubles as a
## load-and-import smoke of the committed player.tres + its sheets.
func _check_sprite_frames_resolution() -> bool:
	var root := _make_root()
	var asset := "res://content/assets/sprites/player.tres"
	var size := Vector2(48, 64)
	ViewBuilderScript.apply_box(root, Color.WHITE, size, true, asset)

	var visual := root.get_node("Visual") as ColorRect
	if visual.color.a != 0.0:
		_fail("frames: visual must be a transparent frame, got color %s" % visual.color)
		return false
	# The static TextureRect branch must NOT have been taken.
	if visual.get_node_or_null("Sprite") != null:
		_fail("frames: a 'Sprite' TextureRect was added for a SpriteFrames asset")
		return false
	var sprite := visual.get_node_or_null("AnimatedSprite") as AnimatedSprite2D
	if sprite == null:
		_fail("frames: no 'AnimatedSprite' AnimatedSprite2D child for the SpriteFrames branch")
		return false
	if sprite.sprite_frames == null:
		_fail("frames: the AnimatedSprite2D has no SpriteFrames (player.tres failed to load)")
		return false
	if not sprite.sprite_frames.has_animation(&"idle"):
		_fail("frames: the resolved SpriteFrames is missing the 'idle' animation")
		return false
	root.free()
	return true
