class_name ViewBuilder
extends RefCounted

## The single view-construction seam (P2-S2, #436): the ONE place a controller's
## blockout is built, so the `_apply_blockout` construction that was duplicated
## across every view-layer controller (Enemy, Obstacle, Pickup, Projectile,
## Player, the Gravity/Time Fields, and the Level's platform segments) collapses
## to one path — the CanvasItem layer of gADR-0000's Resource/Controller/CanvasItem
## split.
##
## It RESOLVES what to render from config (asset references are data, gADR-0000):
## a non-empty `asset` reference is the resolved sprite path; an empty one is the
## colored-block fallback. The RESOLUTION is config-fed as of P2-S2: every caller
## passes its config's optional asset reference (JSON authority -> build_config ->
## derived Resource -> here), and the builder resolves the Asset manifest id -> the
## single-homed res:// path (P2-S1, #439, gADR-0014). The sprite RENDERING branch
## (`_apply_visual` / `_apply_sprite`) DISPATCHES on the resolved resource kind: a
## `Texture2D` renders as the static "Sprite" TextureRect (the tracer's Obstacle,
## #439), a `SpriteFrames` as an "AnimatedSprite2D" a controller drives through its
## view-integration hooks (the Player, P2-S5 #443, gADR-0015). Sibling asset slices
## wire the rest BY DATA with no controller edits (each just authors its config's
## reference). A reference that cannot load — or resolves to neither kind — guards
## loudly and falls back to the colored block.
##
## Static, like the pure Systems (CombatSystem, GravitySystem, …) and the
## GeneratedConfig loader — this is stateless one-shot construction, not a
## stateful per-owner driver (the EnemyWarpDriver / GameFlowDirector idiom is for
## orchestration that holds live state across frames; a blockout is built once and
## holds nothing). A controller calls it once in _ready against ITSELF (its
## `$Visual`/`$Collision` children, the shared blockout scene shape), and the Level
## calls it per instanced platform segment — the `root` is whichever node carries
## the "Visual" (ColorRect) + "Collision" (CollisionShape2D) pair.
##
## No per-construction logging: a blockout is built once per spawn, so logging here
## would be exactly the per-call spam the gda-logger-tail convention warns against
## — the actors already log their own `_ready` entry (enemy_ready, …). The
## collision shape is CREATED here (RectangleShape2D / CircleShape2D sized from
## config): gda cannot author inline sub-resources (#365), so the blockout scenes
## ship shape=null and this fills it.


## Build a rectangular blockout on `root`'s Visual/Collision children: the ColorRect
## sized `size` and centered on the origin (position = -size/2), and a
## RectangleShape2D of the same size on the CollisionShape2D. Set `pivot` for a block
## that scale-tweens (the actors that squash: Player, Enemy, Pickup) so the punch is
## about the block center; leave it false for a block that never scales. `asset` is
## the caller's config-fed asset reference — authored empty today (see the
## resolution in `_apply_visual`).
static func apply_box(
	root: Node, color: Color, size: Vector2, pivot: bool = false, asset: String = ""
) -> void:
	_apply_visual(root, color, size, pivot, asset)
	var shape := RectangleShape2D.new()
	shape.size = size
	(root.get_node("Collision") as CollisionShape2D).shape = shape


## Build a circular blockout (the Gravity/Time Field shape): the ColorRect is the
## enclosing 2·radius square block, the CollisionShape2D a CircleShape2D of `radius`
## — both centered on the origin. The square-visual-over-circle-collision is the
## field's translucent-block look; the fields never scale, so no pivot.
static func apply_circle(root: Node, color: Color, radius: float, asset: String = "") -> void:
	var side := radius * 2.0
	_apply_visual(root, color, Vector2(side, side), false, asset)
	var shape := CircleShape2D.new()
	shape.radius = radius
	(root.get_node("Collision") as CollisionShape2D).shape = shape


## Resolve the VISUAL for this view and apply it to `root`'s "Visual" ColorRect
## (asset references are data, gADR-0000): a non-empty `asset` is the resolved
## sprite path, an empty one is the colored-block fallback. The resolution is
## config-fed (P2-S2, #436: every caller passes its config's optional asset
## reference), and the builder resolves the Asset manifest id -> the single-homed
## res:// path before it reaches here (P2-S1, #439, gADR-0014), so `asset` is a
## loadable resource path. The "Visual" ColorRect is always sized/positioned/
## pivoted (so a scale tween squashes about the block center either way); the block
## branch colors it, the asset branch makes it a transparent frame and fills it
## with the sprite. A reference whose texture cannot load is a genuine fault (the
## pipeline promises the file present) — guard loudly (the codebase's push_error
## idiom) and fall back to the colored block so the game still renders.
static func _apply_visual(
	root: Node, color: Color, size: Vector2, pivot: bool, asset: String
) -> void:
	var visual := root.get_node("Visual") as ColorRect
	visual.size = size
	visual.position = -size / 2.0
	if pivot:
		visual.pivot_offset = size / 2.0  # scale/tween about the block center
	if asset.is_empty():
		visual.color = color
		return
	_apply_sprite(visual, size, asset, color)


## Render the resolved `asset` inside the "Visual" rect, DISPATCHING on the loaded
## resource kind (P2-S1 #439 static texture; P2-S5 #443 animated sprite): the
## ColorRect becomes a transparent frame and the sprite is added as its child, so
## it inherits the Visual's transform. Two branches on what the reference resolved
## to:
##   - a `Texture2D` -> the STATIC path (#439): a "Sprite" TextureRect child scaled
##     to `size`. This node contract is a fixed seam (the Obstacle texture e2e and
##     the view-builder logic seam pin the "Sprite" TextureRect) and is preserved
##     byte-for-byte here.
##   - a `SpriteFrames` -> the ANIMATED path (#443): an "AnimatedSprite2D" child the
##     view driver (PlayerAnimator) plays, sized to `size`. gADR-0015's SpriteFrames
##     is the committed animated look; a controller drives its states via the
##     view-integration hooks.
## Nearest filtering keeps the pixel-art crisp (the project default too, gADR-0013).
## A null load, or a resource that is neither kind, is a not-shipped/mis-typed asset
## fault: guard loudly and fall back to the colored block so the game still renders.
static func _apply_sprite(visual: ColorRect, size: Vector2, asset: String, color: Color) -> void:
	var resource := load(asset)
	if resource == null:
		push_error(
			"ViewBuilder: asset '%s' failed to load — rendering the colored-block fallback."
			% asset
		)
		visual.color = color
		return
	visual.color = Color(0, 0, 0, 0)  # transparent frame; the sprite is the visual
	if resource is SpriteFrames:
		_apply_animated_sprite(visual, size, resource)
	elif resource is Texture2D:
		_apply_static_sprite(visual, size, resource)
	else:
		push_error(
			(
				"ViewBuilder: asset '%s' is neither a Texture2D nor a SpriteFrames (%s) — "
				+ "rendering the colored-block fallback."
			)
			% [asset, resource.get_class()]
		)
		visual.color = color


## The STATIC texture branch (#439), preserved verbatim: a "Sprite" TextureRect
## child of the Visual, scaled to `size` (postprocess already conformed the texture
## to the Scale spec dimensions, so this is 1:1). The node NAME and TYPE are a fixed
## contract other slices depend on (the Obstacle texture e2e).
static func _apply_static_sprite(visual: ColorRect, size: Vector2, texture: Texture2D) -> void:
	var sprite := TextureRect.new()
	sprite.name = "Sprite"
	sprite.texture = texture
	sprite.size = size
	sprite.stretch_mode = TextureRect.STRETCH_SCALE
	sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	sprite.mouse_filter = Control.MOUSE_FILTER_IGNORE
	visual.add_child(sprite)


## The ANIMATED sprite branch (#443): an "AnimatedSprite2D" child of the Visual,
## centered in the block and scaled so a frame maps onto `size` (postprocess
## conforms frames to the Scale-spec box, so this is 1:1). It plays the set's first
## animation by default so any SpriteFrames renders animated even without a driver;
## a controller's view driver (PlayerAnimator) then drives the animation STATE from
## the controller's view-integration hooks. Nearest filtering keeps pixel art crisp.
static func _apply_animated_sprite(visual: ColorRect, size: Vector2, frames: SpriteFrames) -> void:
	var sprite := AnimatedSprite2D.new()
	sprite.name = "AnimatedSprite"
	sprite.sprite_frames = frames
	sprite.centered = true
	sprite.position = size / 2.0  # the Visual's centre, in its local (top-left) space
	sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	var names := frames.get_animation_names()
	if not names.is_empty():
		var frame := frames.get_frame_texture(names[0], 0)
		if frame != null:
			var frame_size := frame.get_size()
			if frame_size.x > 0.0 and frame_size.y > 0.0:
				sprite.scale = size / frame_size
		sprite.play(names[0])
	visual.add_child(sprite)
