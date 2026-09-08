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
  "measurement": "godot-static-model-content-v1",
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

## Version 1 sampling rules

The headless and live implementations use the same sampling block. Version 1
walks the selected root and its bounded child prefix in stable child order. It
hashes each node's root-relative locator and engine class. It excludes the
selected root's name and local placement because those belong to its consumer;
it includes each descendant `Node3D` local transform.

For each `MeshInstance3D`, version 1 supports `ArrayMesh` surfaces without blend
shapes, LODs, skins, or material overlays. Other `VisualInstance3D` nodes and
`Camera3D` are unsupported because their visible content is outside this static
mesh measurement. The sampler hashes the surface index,
primitive type, format, and every value returned by
`ArrayMesh.surface_get_arrays()`. The sampler checks native stored mesh-buffer
size before expanding arrays. It has fixed ceilings of 4,096 surfaces, 32 MiB
of native stored mesh buffers, and 64 MiB of serialized hash input in addition
to the caller's node and vertex limits.

Godot 4.6's [ArrayMesh API](https://docs.godotengine.org/en/4.6/classes/class_arraymesh.html)
does not expose a public LOD reader. Version 1 therefore checks the native
[`_surfaces[].lods` storage shape](https://github.com/godotengine/godot/blob/4.6.3-stable/scene/resources/mesh.cpp#L1510-L1573).
A nonempty LOD set, an
unexpected private storage shape, or an engine version outside the supported
4.6 line makes that content unsupported; the sampler does not infer that LOD
data is absent.

The effective surface material comes from
`MeshInstance3D.get_active_material()`, so normal material and surface override
precedence is observed. A material is supported when it is an unscripted
`StandardMaterial3D`. Version 1 hashes its storage properties in property-name
order for these Variant types: null, bool, int, float, String, StringName,
Vector2, Vector3, Vector4, and Color. A null Object property is included. A
non-null Resource property, including a referenced texture, makes the sample
unsupported because version 1 does not recursively identify Resource content.
Resource bookkeeping fields such as `resource_name`, `resource_path`,
`resource_local_to_scene`, and `script` are excluded.

Scripted nodes, `Skeleton3D`, `AnimationPlayer`, skins, non-`ArrayMesh` meshes,
blend shapes, LODs, and other material or property types remain visible through
`unsupported`. They are not silently reduced to partial identity claims.

## Digest and incomplete results

The sampler feeds the admitted typed Godot values to SHA-256 in traversal and
property-name order. It excludes engine-version metadata, resource paths,
instance IDs, and the selected root's name and local placement. Those
exclusions let the same supported model content be compared between an imported
resource and one selected live instance within a compatible engine context.

`complete` is true only when both `unsupported` and `omitted` are empty and the
sample contains at least one surface and one vertex. Only a complete result
carries `digest`; otherwise `digest` is null. `unsupported`
means encountered content is outside version 1's admitted semantics. `omitted`
means a node, vertex, surface, index, stored-buffer, or serialized-byte limit
prevented complete sampling. The lists are sorted and deduplicated so the
incomplete result remains useful for diagnosis.

The digest identifies the admitted static content for measurement version 1.
It does not identify a full resource, rendered appearance, animated pose,
runtime behavior, or visual equivalence. Godot's Variant byte encoding and
imported representation participate in the measurement, so cross-version
digest identity is not promised. Compare the measurement identifier and actual
engine versions before interpreting two digests.
