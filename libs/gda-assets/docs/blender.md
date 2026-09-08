# Saved Blender production

`gda asset-pipeline run` can export an already authored `.blend` source, install
its GLB, and ask Godot to import and load it. It uses the same file admission,
installation, conflict handling and Godot operations as existing-file handoff.
It does not author models or require prompts or concept images.

## Input

Select exactly one of `files` and `production`. The producer request has a `kind`,
explicit output roles/destinations, and adapter-owned `options`:

```sh
gda asset-pipeline run --project ./consumer --source-root ./production \
  --production '{"kind":"blender_saved","outputs":[{"role":"model","target":"res://art/model.glb"}],"options":{"source":"model.blend","scene":"AssetScene","root":"AssetRoot","uniform_scale":2}}' \
  --json
```

The consumer must contain `project.godot`. Resolve Blender through
`options.executable`, then `GDA_BLENDER`, then `blender` on `PATH`. Godot uses the
normal `--godot` / `GDA_GODOT` configuration. A relative source requires an explicit
`--source-root`; an absolute source does not. Keep production files outside the
consumer project to avoid Godot's project-wide import scanning the `.blend` too.

`--production` takes one JSON object token. The same object is the `production`
property in `--params-json` or the generated `asset_pipeline_run` MCP tool. Run
`gda asset-pipeline run --schema` for the common request and result contract.
Producer options are validated inside the selected adapter:

| Blender option | Contract |
| --- | --- |
| `source` | Required saved `.blend` file |
| `scene`, `root` | Required exact names; absent or ambiguous selection fails |
| `uniform_scale` | Positive finite number, default `1`; booleans/strings refused |
| `export.animations` | Boolean, default `false` |
| `export.materials` | `EXPORT` or `NONE`, default `EXPORT` |
| `export.apply_modifiers` | Boolean, default `true` |
| `executable` | Optional Blender executable path/name |
| `timeout_seconds` | Positive number up to 3,600 seconds, default `120` |

Unknown options are refused. The first producer emits exactly one `model` output
with a `.glb` destination. It requests a self-contained GLB; unexpected external
references must pass shared file admission and cannot silently add dependencies.
`source_mode` is observed as `blender_saved`; do not combine production with a
caller `imagegen` declaration. `provenance` remains caller-declared metadata.

## Source inspection and preparation

A separate background Blender process loads the original saved file, with factory
startup and automatic script execution disabled. It modifies only that process's
in-memory scene and writes into the invocation's temporary workspace. It never
saves the source or connects to the user's open Blender session. Loading at the
original path preserves source-relative linked resources. This is the export
workspace; it is not an on-disk copy with rebased dependencies. Successful results
also verify that the saved source bytes did not change during the invocation.

Selection includes the root and its descendants in the selected scene, up to
1,024 objects. Hidden objects in that subtree are included; unrelated objects and
external parents are not selected. Objects excluded from the active view layer
are unsupported. The GLB excludes cameras and lights. The bounded source report
lists selected names/types, actual scene, root, Blender version and view layer.

`before` and `after` are unions of evaluated mesh bounding-box corners transformed
into Blender Z-up world coordinates at the source's current frame. They describe
this selection, not every object in the source, and are not vertex counts or
animation-wide bounds. A selection without finite evaluated mesh bounds fails.
The report records the scene unit scale; this path does not normalize project
units. The standard fixture uses unit scale `1`; export uses glTF Y-up and Godot
performs its normal import. Use Godot-loaded facts for consumer dimensions.

Uniform scaling multiplies the selected root's local scale in the isolated
process. Preparation checks that the evaluated dimensions follow that factor.
Non-unit scaling of a root with animation data, NLA or drivers is unsupported:
export-time evaluation can undo the change. This refusal applies even when
animation export is disabled. Supporting animated scaling requires a separately
validated authoring/export policy. Unit scaling does not promise to validate all
rigs, animations or constraints. Exporter options are checked against the running
Blender's glTF operator before use; unavailable options fail at the export stage.
The real-engine tests currently cover Blender 5.2.1 LTS and Godot 4.6.3.

## Results and recovery

`pipeline.production` records source inspection, preparation, actually used export
options and native diagnostics. Its `completed` list and `stage` distinguish
`inspect`, `prepare` and `export`. These are separate from the outer pipeline's
`produce`, `validate`, `stage`, `install`, `import`, `load` stages. A successful
Blender process alone never proves successful Godot loading.

Native results are capped at 128 KiB; stdout/stderr retain their final 16 KiB each.
A missing executable, timeout, failed process, malformed result, absent output or
invalid GLB produces a nonzero structured failure. `error.partial_result` retains
completed stages and affected files. `cleanup.workspace_removed` reports removal
of the invocation-owned temporary workspace. Source files and installed outputs
are not cleanup targets.

After a Godot import failure, installed GLBs remain available. Fix the import
cause, then explicitly use the existing-file handoff or `gda resource import` and
load/inspection commands. The workflow never reruns Blender automatically. Running
`--production` again is an explicit new export; choose `--overwrite` deliberately.
There is no persisted run/resume protocol.

## Reproducible validation

From a development checkout with Blender and Godot configured:

```sh
uv run pytest tests/asset_pipeline/test_e2e_blender_producer.py -q
```

The tests create saved sources outside isolated consumer projects. They prove
1x/2x Godot-loaded dimensions, hidden-subtree inclusion, unrelated-object exclusion,
wrong-root and animated-root refusals, a real export filesystem failure, and a
real Godot post-import rejection with retained GLB and no producer retry. Every
native case checks source preservation. Fast tests cover invalid configuration,
process/result failures, timeout diagnostics and CLI/schema/MCP contracts. The
installed-distribution smoke checks that the worker ships with gda; discovery and
ordinary file handoff do not require Blender.
