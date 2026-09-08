# Asset pipeline

Use `gda asset-pipeline run` to install selected PNG/GLB files and ask Godot to
load them. The internal `gda_assets` library ships in the normal gda distribution;
there is no separate executable or installation. For saved `.blend` export with
source inspection and uniform scale preparation, see the
[Blender production guide](docs/blender.md). Completed image-generation outputs
use explicit file handoff; this command does not generate images.

Use `gda asset-pipeline check` to evaluate project-owned model expectations against
a current Godot inspection or a saved raw inspection report. See the
[model checks guide](docs/checks.md) for the JSON format, seven supported check
kinds, verdict semantics, partial coverage, and compatible baseline comparison.

```sh
gda asset-pipeline run --project ./consumer --source-root ./production \
  --files '[{"source":"icon.png","target":"res://art/icon.png","resize":{"width":64,"height":64,"resampling":"nearest"}},{"source":"model.glb","target":"res://art/model.glb"}]' \
  --json
```

The consumer must contain `project.godot`. Set `GDA_GODOT` or pass `--godot` as
for other gda commands. `source_root` is the base for relative source paths; when
any source is relative this base must be supplied explicitly. It can be omitted
when every source is an absolute path. Targets always use the resolved
Godot project. Use `--overwrite` to
replace different target content; the default refuses it. Identical processed
output reports `unchanged` and does not rewrite the target.

The machine contract is `gda asset-pipeline run --schema`. The same typed input
works through `--params-json` and generated MCP. `files` and `provenance` use JSON
values on the ordinary CLI. Select `--source-mode imagegen` with optional
`--provenance '{"model":"caller-reported model"}'` for completed local generation
outputs. The result labels this metadata `caller_declared_provenance`; it is not
proof of generation or an engine observation. No prompt record is required.

## File sets and processing

A handoff contains one to 32 explicit mappings. PNG resizing accepts positive
integer dimensions, at most 16,384 per axis and 64 megapixels in total, with
`nearest`, `bilinear`, or `lanczos` resampling. Source PNGs also have a 64 megapixel
limit. Processing takes place in temporary staging and preserves selected sources.
GLBs bypass raster processing.

Declare each referenced file as a mapping, then name its target in the referring
file's `references` array. For example, a GLB with image URI `body.png` can use:

```json
[
  {"source":"panda.glb","target":"res://art/panda.glb","references":["res://art/body.png"]},
  {"source":"body.png","target":"res://art/body.png"}
]
```

Source and target placement must preserve that relative URI. The workflow neither
rewrites GLB links nor discovers a whole project's dependencies. This slice admits
PNG and GLB members; external buffers or textures in other formats are unsupported.
Export self-contained GLBs for those cases. Container and file checks are bounded
admission checks; actual Godot loading decides the engine result.

## Results and failures

The result reports completed stages, each installed/unchanged file, optional resize
parameters, the existing gda import result, and actual Godot resource type, engine
version, texture dimensions or scene node count. Import can perform project-wide
engine work, as its returned facts report. GLB load checks instantiate the imported
scene; normal Godot project-code execution rules apply.

Input/mapping checks and all staging finish before installation. Each target file
is replaced as one complete file, but the file set and engine import are not an
atomic transaction. On failure, the command exits nonzero and reports the failed
stage and completed file effects in `error.partial_result`. Underlying gda error
codes and diagnostics remain available. Earlier installed files remain in place;
the workflow stops before import after partial installation. It removes only its
temporary files and never retries generation. Fix the cause and explicitly rerun
with the intended overwrite policy.

## Installed-distribution smoke check

From the repository, build the normal gda distribution, install its wheel in a
clean environment, and run the owned smoke script with that environment's Python:

```sh
uv build --out-dir /tmp/gda-assets-dist
uv venv /tmp/gda-assets-consumer --python 3.13
uv pip install --python /tmp/gda-assets-consumer/bin/python /tmp/gda-assets-dist/gda-*.whl
/tmp/gda-assets-consumer/bin/python scripts/smoke_asset_pipeline.py \
  --gda /tmp/gda-assets-consumer/bin/gda --godot "$GDA_GODOT"
```

Use fresh task-specific directories when those paths already contain artifacts.
The script creates an isolated project, verifies PNG resize and a real GLB mesh
load, exercises a structured no-op repeat and a pre-installation refusal, then
cleans up its project. It also checks installed engine payload and guidance data.
No game example is a runtime or test prerequisite.

## Check model expectations

Evaluate a model through Godot:

```sh
gda asset-pipeline check --expectations ./model.expectations.json \
  --path res://art/model.glb --project ./consumer --json
```

Use `--report ./report.json` instead of `--path` to evaluate raw JSON previously
saved from `gda resource inspect-model`. Add `--baseline ./older-report.json` for
a separate compatible comparison. Completed `pass`, `fail`, and `insufficient`
verdicts all exit 0; malformed input or workflow failure exits nonzero.
