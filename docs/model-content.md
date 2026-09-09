# Static model content sampling

`gda resource inspect-model-content` and `gda game inspect-model-content` expose
the same bounded native sampler. They expose comparable digests of supported static
model content without publishing large mesh arrays in JSON. They are
independently usable core commands; asset workflows can compose their results.

```console
gda resource inspect-model-content --path res://models/ship.glb --json
gda game inspect-model-content --node /root/Main/Ship --json
```

Both commands accept `--max-nodes` (default 256, range 1–1024) and
`--max-vertices` (default 200,000, range 1–1,000,000). The result contains a
shared `content` object:

```json
{
  "measurement": "godot-static-model-content-v3",
  "engine_version": {"major": 4, "minor": 6},
  "complete": true,
  "digest": "<64 lowercase hexadecimal characters>",
  "nodes": 3,
  "surfaces": 1,
  "vertices": 24,
  "unsupported": [],
  "omitted": []
}
```

The full `engine_version` object has the standard gda engine-version shape.
`nodes`, `surfaces`, and `vertices` count facts encountered in the bounded
walk. They are observation totals, not gameplay, render, or performance
metrics.

## Two observation contexts

`resource inspect-model-content` accepts a project-owned `.glb` path. It loads
the imported `PackedScene`, instantiates its root, samples it outside a running
scene tree, and frees it. Loading and instantiation use the trusted-project
execution surface: resource and node initializers can run. This is not a script
sandbox promise. The command does not add the scene to the active tree or play
it, and it does not run a resource import pass. Import the GLB first when its
cache is absent or stale.

`game inspect-model-content` accepts an absolute runtime node path under
`/root`. It samples that existing instance in the daemon's running engine
session. It does not reload the scene from disk or create a replacement
instance. Its wrapper adds:

- `node`: the selected absolute runtime path.
- `instance_id`: a positive, session-local Godot object identifier.
- `scene_file_path`: the selected instance's current Godot scene-file path,
  which can be empty.
- `session_id`: the daemon session that produced the observation.
- `engine_frame`: Godot's nonnegative process-frame counter when the command
  produced the result.

`instance_id` is meaningful only within its engine session. `engine_frame`
locates the observation in that session; it does not make the traversal an
atomic frame snapshot.

## Version 3 sampling rules

The headless and live implementations use the same sampling block. Version 3
walks the selected root and its bounded child prefix in stable child order. It
hashes each node's root-relative locator and engine class. It excludes the
selected root's name and local placement because those belong to its consumer;
it includes each descendant `Node3D` local transform.

For each `MeshInstance3D`, version 3 supports `ArrayMesh` surfaces, including
static LODs, without blend shapes, skins, or material overlays. Other
`VisualInstance3D` nodes and `Camera3D` are unsupported because their visible
content is outside this static mesh measurement. The sampler hashes the surface index,
primitive type, format, and every value returned by
`ArrayMesh.surface_get_arrays()`. The sampler checks native stored mesh-buffer
size before expanding arrays. It has fixed ceilings of 4,096 surfaces, 32 MiB
of total public surface buffer data, 8 MiB of LOD index bytes, 1,024 LOD
entries, and 64 MiB of serialized hash input in addition to the caller's node
and vertex limits.

Version 3 reads each surface through public
[`RenderingServer.mesh_get_surface()`](https://docs.godotengine.org/en/4.6/classes/class_renderingserver.html#class-renderingserver-method-mesh-get-surface).
On the validated Godot 4.6 representation, a LOD is a Dictionary containing a
positive `edge_length` float and a nonempty `index_data` byte array. Entries are
strictly ordered by increasing threshold. The sampler hashes every threshold
and every index byte in that order. Godot stores two-byte indices when the
surface has at most 65,536 vertices and four-byte indices above that boundary;
version 3 validates the corresponding byte width without decoding or dropping
indices. Godot omits the `lods` key for a valid surface with no LODs. The sampler
accepts that omission only after validating the rest of the public surface
shape; an empty or malformed surface Dictionary is incomplete rather than
being interpreted as zero LODs. The representation and index-width rules come
from the
[public binding](https://github.com/godotengine/godot/blob/4.6.3-stable/servers/rendering/rendering_server.cpp#L2067-L2100)
and
[construction/readback paths](https://github.com/godotengine/godot/blob/4.6.3-stable/servers/rendering/rendering_server.cpp#L1332-L1370)
in the Godot 4.6.3 source.
An unknown LOD or surface representation, or an engine version outside the
supported 4.6 line, remains localized in `unsupported`.

The maintained native regression covers Godot 4.6.3 stable official
`7d41c59c4` on arm64 macOS with GL Compatibility in both headless imported
sampling and a windowed running game. The sampler requires the validated public
Dictionary shape on every surface and refuses another shape. Equivalent digest
behavior has not been established for Vulkan renderers, other operating
systems, or other engine minor versions.

The effective surface material comes from
`MeshInstance3D.get_active_material()`, so normal material and surface override
precedence is observed. A material is supported when it is an unscripted
`StandardMaterial3D`. Version 3 hashes its storage properties in property-name
order for these Variant types: null, bool, int, float, String, StringName,
Vector2, Vector3, Vector4, and Color. A null Object property is included. The non-null
`albedo_texture` property has the narrow image-content rule below. Other non-null
Resource properties remain unsupported; the sampler does not recursively identify
arbitrary Resource content.
Resource bookkeeping fields such as `resource_name`, `resource_path`,
`resource_local_to_scene`, and `script` are excluded.

For albedo, version 3 admits unscripted `ImageTexture` and `CompressedTexture2D`
whose public [`Texture2D.get_image()`](https://docs.godotengine.org/en/4.6/classes/class_texture2d.html#class-texture2d-method-get-image)
returns a nonempty, uncompressed RGB8 or RGBA8 `Image` with matching dimensions.
It hashes width, height, format, mipmap presence/count, and every returned image
byte, including mipmaps. This distinguishes an image-only change even when the
resource path, node names, geometry counts, and bounds stay the same. It also
observes global and surface material overrides through `get_active_material()`.
An absent image, inconsistent dimensions, another image format, a scripted or
procedural texture, and render-target textures remain unsupported. Non-albedo
texture slots remain unsupported even when their image data is readable.

The maintained GLB fixture contains an embedded base-color PNG. Godot's default
embedded-image option extracts it to a project PNG and imports a
`CompressedTexture2D`; sampling its decoded Image still measures the received
image content. This implementation does not infer production provenance from a
texture path or require the engine to retain the original embedding. See the
[Godot 4.6.3 extraction and texture loading path](https://github.com/godotengine/godot/blob/4.6.3-stable/modules/gltf/gltf_document.cpp#L2186-L2263).

Before each image read, the sampler charges the texture's reported base-level
width × height against a fixed aggregate limit of 16,777,216 pixels. Repeated
references and attempted reads that later fail consume that budget too. It checks
`Image.get_data_size()` against the remaining 64 MiB total serialized hash budget
before requesting the byte array; all mip levels count toward that byte budget.
The image shares this existing budget with geometry, LODs, and material values.
An omitted or unsupported image makes the complete sample's digest null.

The pixel check precedes `get_image()`. The byte check happens after that method
has returned: Godot may already have allocated or copied an image or read from the
GPU. Neither limit bounds that initial native allocation or latency. In the
validated 4.6.3 arm64/macOS GL Compatibility experiment, a default-imported 1024²
RGBA8 image had 10 mip levels and 5,592,404 data bytes. Headless and windowed
readback returned identical image metadata and raw SHA-256. Three windowed
`get_image()` reads took 2,629, 617, and 306 microseconds; headless reads took
1–3 microseconds. The coarse static-memory delta while retaining the windowed
image was about 11.2 MB, while the headless delta was zero. These snapshots reflect
allocator reuse and object lifetimes, not transient/native peak memory or an SLA.
A 2048² headless image had 11 mip levels and 22,369,620 bytes. Runtime-created
1024² RGB8 and RGBA8 `ImageTexture` controls also returned identical raw bytes
between headless and windowed GL Compatibility. Other formats and renderers are
not established by these measurements.

Scripted nodes, `Skeleton3D`, `AnimationPlayer`, skins, non-`ArrayMesh` meshes,
blend shapes, and other material or property types remain visible through
`unsupported`. They are not silently reduced to partial identity claims.

The sampler rejects a base index buffer whose known 16-bit or 32-bit size already
exceeds the remaining stored-buffer budget before it calls RenderingServer.
Once called, however, the public method materializes that surface's complete
base and LOD buffers before GDScript can inspect their sizes. The 32 MiB
total-buffer, 8 MiB LOD-index, and 1,024-entry ceilings therefore bound
subsequent script processing, hashing, and diagnostic output; they do not cap
that call's initial GPU readback or native allocation.
On that maintained untextured sphere imported with normal LOD generation, the
headless GL Compatibility probe returned 561 vertices, 3 LODs, 5,616 LOD index
bytes, and 18,492 bytes of public surface buffers. A single warm readback took
6 microseconds and the coarse `OS.get_static_memory_usage()` delta while
retaining the Dictionary was 7,952 bytes. These measurements describe that
local sample; allocator reuse,
renderer, driver, hardware, and mesh size can change them. The engine's
[GL Compatibility path](https://github.com/godotengine/godot/blob/4.6.3-stable/drivers/gles3/storage/mesh_storage.cpp#L614-L665)
and
[RenderingDevice path](https://github.com/godotengine/godot/blob/4.6.3-stable/servers/rendering/renderer_rd/storage_rd/mesh_storage.cpp#L637-L680)
both read every LOD buffer before returning, so the script-side ceilings must
not be used as a native memory or latency guarantee.

## Digest and incomplete results

The sampler feeds the admitted typed Godot values to SHA-256 in traversal and
property-name order. It excludes engine-version metadata, resource paths,
instance IDs, and the selected root's name and local placement. Those
exclusions let the same supported model content be compared between an imported
resource and one selected live instance within a compatible engine context.

`complete` is true only when both `unsupported` and `omitted` are empty and the
sample contains at least one surface and one vertex. Only a complete result
carries `digest`; otherwise `digest` is null. `unsupported`
means encountered content is outside version 3's admitted semantics. `omitted`
means a node, vertex, surface, index, stored-buffer, albedo-pixel, or serialized-byte limit
prevented complete sampling. The lists are sorted and deduplicated so the
incomplete result remains useful for diagnosis.

The digest identifies the admitted static content for measurement version 3.
It does not identify a full resource, rendered appearance, animated pose,
runtime behavior, or visual equivalence. Godot's Variant byte encoding and
imported representation participate in the measurement, so cross-version
digest identity is not promised. Compare the measurement identifier and actual
engine versions before interpreting two digests.

Version 3 supersedes version 2 when albedo image bytes become part of the
measurement. Digests with different measurement identifiers are not comparable,
even for a model without a texture.
