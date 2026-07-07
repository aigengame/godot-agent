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
## a non-empty `asset` reference is the future sprite path; an empty one is the
## colored-block fallback shipped today. P2-S2 wires ONLY the fallback — no assets
## are authored yet — so every current spec resolves to a ColorRect block that
## renders EXACTLY as before this slice (same size/color/center). A later slice
## (the visual pipeline, P2-S6/S7) fills the sprite branch and feeds the asset
## reference from config, wiring sprites BY DATA instead of editing every
## controller again.
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
## about the block center; leave it false for a block that never scales. `asset`
## carries the (future) sprite reference — empty today (see the resolution in
## `_apply_visual`).
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
## (asset references are data, gADR-0000): a non-empty `asset` is the future sprite
## path; empty is the colored-block fallback. P2-S2 (#436) ships only the fallback,
## so no current caller passes an asset. A spec that carries one before the sprite
## slice (P2-S6/S7) wires it is a not-yet-wired fault — guard loudly (the codebase's
## push_error idiom) rather than silently render nothing. The block branch is byte-
## for-byte the old per-controller construction: color, size, center, optional
## center pivot.
static func _apply_visual(
	root: Node, color: Color, size: Vector2, pivot: bool, asset: String
) -> void:
	if not asset.is_empty():
		push_error(
			"ViewBuilder: asset reference '%s' is not wired yet — P2-S2 (#436) ships the block fallback only."
			% asset
		)
		return
	var visual := root.get_node("Visual") as ColorRect
	visual.color = color
	visual.size = size
	visual.position = -size / 2.0
	if pivot:
		visual.pivot_offset = size / 2.0  # scale/tween about the block center
