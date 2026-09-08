# Concept references

Use the concept workflow before authoring a new model or sprite sheet. It preserves
the project brief and prompt, accepts explicitly registered local PNG candidates,
copies the selected references into a movable handoff, and runs one of two bounded
reference-use examples. It does not call an image provider or install anything into
Godot.

Create a brief such as `concept.json`:

```json
{
  "use": "model",
  "subject": "A squat brass maintenance robot",
  "style": "Readable low-poly shapes with a warm industrial palette",
  "views": ["front", "three-quarter"],
  "poses": ["neutral"],
  "instructions": "Keep the silhouette clear at gameplay camera distance."
}
```

`use`, `subject`, and `style` are required. Supply at least one view or pose;
the unused list and `instructions` can be omitted. Unknown fields are rejected.

Then prepare one exclusive prompt-record directory:

```sh
gda asset-pipeline concept-prepare --brief ./concept.json \
  --record ./concept-attempt-a --json
```

Optional `--producer` and JSON-object `--requested-options` record the requested
external tool settings. The `preparation` result includes the saved brief and the existing prompt preparation with
`action: external_generation_required` and `generation_status: unknown`. Submit the
saved prompt to the external image tool yourself. Preparation alone is not image
generation. After the tool returns a local PNG, register it with the existing
operation:

```sh
gda asset-pipeline prompt-register-output --record ./concept-attempt-a \
  --output ./generated/robot.png --name robot.png \
  --caller-declarations '{"generation_completed":true}' --json
gda asset-pipeline prompt-inspect --record ./concept-attempt-a --json
```

`generation_completed` is the caller's declaration, not proof from the provider.
The prompt record keeps requested options, declarations, reported facts, and saved
file facts separate. Create another record for another attempt; previous attempts
are not overwritten.

Select one to eight ordered candidates into a new handoff directory:

```sh
gda asset-pipeline concept-select --brief-record ./concept-attempt-a \
  --handoff ./robot-references \
  --candidates '[{"record":"./concept-attempt-a","output":"robot.png"}]' \
  --json
```

Selection requires the exact registered output, a true caller completion
declaration, and PNG bytes that still match their saved facts. It copies selected
files and relative record/output links without changing candidates. Moving the
complete handoff directory preserves those internal links. Reusing it never calls a
provider. Read the result under `selection`.

Use exactly one selected reference with a supported demonstration consumer:

```sh
gda asset-pipeline concept-author --handoff ./robot-references \
  --consumer blender-reference-blockout --output ./robot-blockout \
  --reference-index 0 --json
```

The Blender example loads the selected PNG as a reference before geometry, derives
a simple material color from its pixels, and writes one `.blend` plus one `.glb`.
It demonstrates reference loading and observable pixel influence, not shape
inference, finished modeling, image similarity, or the saved-source export workflow.

For a sprite brief, use the other bounded consumer:

```sh
gda asset-pipeline concept-author --handoff ./sprite-references \
  --consumer sprite-sheet-reference --output ./sprite-example \
  --reference-index 0 \
  --sprite-layout '{"width":256,"height":64,"cell_width":64,"cell_height":64,"frames":4}' \
  --json
```

This example reads the selected PNG before deriving frame pixels, then verifies the
declared sheet dimensions, cell grid, and frame count. It is not an animation-quality
check, Aseprite support, or a declaration that the output is runtime-ready.

Both authoring results identify the consumed handoff file and digest,
`reference_loaded`, the bounded influence, artifacts, and limitations. Missing,
changed, corrupt, unselected, or completion-unknown references stop before authoring.
Unsupported consumers also fail explicitly. Destination record, handoff, and output
directories must be new. No command silently retries generation, changes prompt
status, or maps a concept image into a Godot project.

All three concept commands are projectless and support `--json`, `--params-json`,
and `--schema`. `concept-author` returns its result under `authoring`; pass
`--blender-executable` only when selecting the Blender consumer.

The bounded native workflow has been observed with one registered 1,254×1,254
agent-generated PNG. The same selected SHA-256 was loaded first by Blender 5.2.1,
which wrote a one-cube material-influenced `.blend` and GLB, and separately by the
sprite consumer, which wrote and checked a 256×256 sheet containing four 128×128
cells. Reuse made no new provider call. This evidence establishes the declared
reference-use mechanics within the limits above; final independent review and CI
remain tracked by the implementation issue.
