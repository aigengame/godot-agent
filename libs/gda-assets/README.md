# Asset pipeline

Use `gda asset-pipeline run` to install selected PNG/GLB files and ask Godot to
load them. The internal `gda_assets` library ships in the normal gda distribution;
there is no separate executable or installation. For saved `.blend` export with
source inspection and uniform scale preparation, see the
[Blender production guide](docs/blender.md). Completed image-generation outputs
use explicit file handoff; this command does not generate images.

Use `gda asset-pipeline prompt-prepare` before external image generation to save
the exact prompt and reference inputs. Inspect or revise those saved inputs, then
register completed local output files. See the [prompt guide](docs/prompts.md)
for the four local operations and their external-tool handoff.

Use the concept workflow to preserve a model/sprite brief, select registered PNG
references, and run a bounded Blender blockout or sprite-sheet reference example.
See the [concept reference guide](docs/concepts.md).

Use `gda asset-pipeline check` to evaluate project-owned model expectations against
a current Godot inspection or a saved raw inspection report. See the
[model checks guide](docs/checks.md) for the JSON format, seven supported check
kinds, verdict semantics, partial coverage, and compatible baseline comparison.

Use `gda asset-pipeline preview` to render three fixed views of a self-contained GLB
in an isolated windowed Godot project and collect bounded inspection, capture,
diagnostic, and scene-level performance facts.

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

Add `--collect-observations` when you need bounded hashes and import facts for the
selected installed outputs. The optional result is returned as
`pipeline.content_observations`. `--observations-output` can also save it to a new
local JSON file, and `--declared-output-sha256` checks caller-declared output hashes
before import. See the [content observations guide](docs/observations.md) for the
command examples, result semantics, failure behavior, and limits.

Add `--refresh` to reset an explicit test scene after install, import, and load,
then compare one selected running GLB instance with the imported result. Runtime
state is discarded. Optional capture requires a windowed launch. See the
[runtime refresh guide](docs/runtime-refresh.md) for the request, supported model
content, stage results, and evidence limits. The two underlying fact commands share
the measurement documented in the [static model content guide](../../docs/model-content.md).

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

## Check an exported package

Use one expectation file first against the source project, then against the PCK:

```sh
gda asset-pipeline check --project ./consumer \
  --path res://art/model.glb --expectations ./model.expectations.json --json

gda export run --project ./consumer --preset "Linux/X11" \
  --mode pack --output ./build/game.pck --json

gda asset-pipeline check-package --package ./build/game.pck \
  --path res://art/model.glb --expectations ./model.expectations.json \
  --exclude res://dev/test.gd --json
```

`export run --mode pack` uses Godot's native export, including its cold import; do
not run a redundant source import first. The package check has no `--project`
option, ignores inherited `GDA_PROJECT` and working-directory project context, and
resolves `res://` only inside the staged PCK. Each repeated `--exclude` selects one
exact normalized resource path (at most 64), checked through the engine namespace;
there are no globs, recursive scans, or complete package inventory. Use optional
`--subtree`, `--max-nodes`, and `--max-items` to retain the same bounded model-fact
scope as a source check.

Always read `package_check.verdict`: completed `pass`, `fail`, and `insufficient`
results exit 0. The outer `origin` is `package_editor_inspection`; the reused inner
`check.observation_source` is `supplied_report` because the workflow hands the observed model
facts to the existing evaluator. The result also identifies the original and staged
package paths, SHA-256, size, inspecting engine, selected resource presence, exact
exclusion verdicts, completed stages, cleanup, failure, and limitations.

The input must be a regular standalone `.pck` no larger than 1 GiB. The workflow
copies it into owned temporary staging before starting Godot, removes staging after
the engine work, and retains the original package. Load or workflow failures exit
nonzero with `error.partial_result.package_check`; cleanup issues remain explicit.
This initial path requires a desktop editor-capable Godot binary. It does not run a
release executable or prove native input, rendering, or gameplay behavior.

Treat a failed `export run` as final even if it left an output file. Before loading a
package, gda narrowly refuses the Godot V3 `GDPC` header state whose directory
offset is still zero and reports it as an incomplete PCK; rebuild and check only the
output of a successful export. This is one known incomplete writer state, not
general PCK validation: opaque, short, other-version, and other malformed packages
remain engine-owned and can still reach the package inspection's 60-second timeout
with limited diagnostics. The
[architecture evidence](docs/ARCHITECTURE.md#evidence-limits-and-validation-gates)
records the native controls and Godot source basis for this boundary.

## Preview a model

Write captures to a new output directory:

```sh
gda asset-pipeline preview --path ./model.glb \
  --output-dir ./model-preview --json > ./preview.json
```

`--path` accepts a local GLB or a project-owned `res://` GLB; the latter requires
`--project`. The output directory must not exist. It retains only the three PNG
captures (`front`, `side`, and `three_quarter`). The workflow copies the source into
a private temporary Godot project, imports and inspects it, frames the views, starts
a windowed session, captures each applied view, samples performance at the final
view, reads bounded diagnostics, stops the session, and removes the temporary
project. It never modifies the source GLB or a user's project.

Use an optional settings file to change the viewport or framing:

```json
{"width":640,"height":360,"padding":1.15}
```

Pass it as `--settings ./preview-settings.json`. Structured params and generated MCP
use the same file-path string; the settings object remains inside that file. Width
and height are each limited to 64–2,048 pixels, and padding to `(1, 3]`. Without
camera overrides, the workflow fits orthographic views to complete finite
static-mesh bounds. Empty, incomplete, non-finite, or unsupported bounds fail
framing.

To freeze the setup when model bounds change, copy each
`preview.views[*].state.camera` object from a prior result into the settings file's
`cameras` array. Supply exactly `front`, `side`, and `three_quarter` in that order.
Each camera has `name`, three-number `position`, `target`, and `up` vectors, plus
positive `size` and `near`, and `far` greater than `near`. Vectors and distances use
Godot world-space units in the isolated fixture. The orthographic camera uses
`KEEP_HEIGHT`, so `size` is the visible vertical span; viewport aspect ratio
determines the horizontal span.

The compact `preview` result links the copied source SHA-256, imported-resource
inspection, applied camera/light/viewport/renderer/static-pose state, capture paths
and receipts, scene-level performance samples and optional budget verdicts,
diagnostics, completed stages, failure, and cleanup. Images stay on disk rather than
being embedded in JSON. The current fixture establishes only the static imported
pose and provides no overlays. Resource-relative Godot node names do not establish
a complete mapping back to Blender source objects.

Performance sampling begins immediately after the final view is applied, without a
stabilization period. Treat it as a bounded observation of that run, not evidence
that rendering reached equilibrium or a general benchmark.

An optional performance budget uses the existing `perf` budget format and the
preview monitor names `fps`, `draw_calls`, and `primitives_in_frame`:

```json
{"draw_calls":{"stat":"p95","max":100}}
```

For example, run a configured comparison against the first saved result:

```sh
gda asset-pipeline preview --path ./model.glb \
  --output-dir ./model-preview-next \
  --settings ./preview-settings.json --frames 60 \
  --budget ./preview-budget.json --baseline ./preview.json --json
```

`--baseline` reads an explicitly saved `{ "preview": ... }` result. Comparison is
`non_comparable` with reasons unless the actual camera, view, light, viewport,
Engine, platform, renderer, static pose, monitor set, and performance sample window
match. Comparable results report scene-level mean and p95 deltas per monitor. This
does not compare model content, promise identical pixels or performance across
runs, or infer per-mesh GPU cost. Runtime preview does not require the content
digest from `asset-pipeline run --refresh`.

Windowed execution requires a usable desktop session. On any failure, inspect the
typed error and `error.partial_result.preview` for completed stages, retained views,
diagnostics, and cleanup state. If the owned session cannot be stopped, the temporary
project is retained and diagnosed rather than removed underneath it.
