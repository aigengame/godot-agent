class_name ScaleSpecConfig
extends Resource

## The Scale spec's typed anchors (P2-S0, gADR-0013): the pixel-art regime
## numbers and the presentation policy, for view-layer consumers — the Phase-2
## View skin reads tile_size; the presentation fields are the authored source
## project.godot's display block mirrors (the engine reads project.godot
## directly, so the data-seam gate cross-checks the mirror instead of deriving
## it).
##
## Per-ELEMENT dimensions (the Player box, enemy boxes, pickup boxes, radii,
## font sizes) are NOT fields here on purpose: the builder composes them into
## each consumer's own config Resource (compose_scale_spec), so every runtime
## module keeps its single config read.
##
## This Resource is a DERIVED artifact: it is regenerated from the
## authoritative data/json/scale_spec.json by scripts/build_config.py and
## emitted to data/generated/scale_spec.tres. Never hand-edit the generated
## .tres or hardcode these values — change the JSON (gADR-0000).
##
## The @export fields carry NO default literals on purpose (see PlayerConfig).

# Art-pixel to world-pixel ratio (1.0 = assets authored at native world
# resolution — the pixel-art regime's root anchor).
@export var ppu: float
# The terrain tile unit in world pixels — the grid the View skin's tile
# vocabulary composes on; level segment dimensions are multiples of it.
@export var tile_size: float
# The Design base (GAME-CONTEXT): the fixed design-space viewport the game is
# authored and framed against — outputs scale via the stretch policy.
@export var design_base: Vector2
# The presentation policy, mirrored into project.godot's display block.
@export var stretch_mode: String
@export var stretch_aspect: String
@export var texture_filter: String
@export var snap_2d_transforms_to_pixel: bool
# The standard walkable-segment thickness (a tile-grid multiple) — the slab
# the Editor defaults new segments to; segment geometry stays level content.
@export var platform_thickness: float
