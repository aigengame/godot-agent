# Runtime refresh

Use a controlled refresh after replacing a GLB at the same `res://` path when you
need to verify one running instance against the newly imported result. Add one JSON
request to the ordinary pipeline run:

```sh
gda asset-pipeline run --project ./consumer --source-root ./production \
  --files '[{"source":"model.glb","target":"res://model.glb"}]' \
  --overwrite \
  --refresh '{"path":"res://model.glb","scene":"res://test.tscn","node":"/root/Test/Model","windowed":true,"capture_output":"/tmp/view.png"}' \
  --json
```

`path` must select one GLB output from this handoff. `scene` must explicitly name a
`.tscn` or `.scn` resource, and `node` must be the absolute `/root/...` path of the
whole GLB root instance in that scene. `windowed` defaults to `false`. A
`capture_output` must be a filesystem path ending in `.png` and requires
`windowed: true`. Optional `timeout`, `max_nodes`, and `max_vertices` default to 25
seconds, 256 nodes, and 200,000 vertices; their maxima are 50 seconds, 1,024 nodes,
and 1,000,000 vertices.

Refresh is independent of `--collect-observations`. Use both when you also need the
optional disk/import observations described in [Content observations](observations.md).

## Inspect the installed output before choosing to refresh

For a single driver controlling the project, separate preparation from the reset:

1. Finish production and processing, then install/import/load without `--refresh`.
2. Inspect that selected installed output and review `content.complete`,
   `content.unsupported`, and `content.omitted`. A complete sample has a digest;
   localized reasons explain an incomplete sample. Choose whether to refresh only
   after reviewing these facts against the current [measurement scope](../../../docs/model-content.md).
3. Check that the selected files have not changed, then explicitly reuse the
   installed files with `--files` and `--refresh`. Omit production and already
   completed processing, such as `resize`.

For example, first install a completed GLB and inspect its imported content:

```sh
gda asset-pipeline run --project ./consumer --source-root ./production \
  --files '[{"source":"model.glb","target":"res://model.glb"}]' --overwrite --json
installed_hash=$(shasum -a 256 ./consumer/model.glb)
gda resource inspect-model-content --project ./consumer \
  --path res://model.glb --json
```

`resource inspect-model-content` does **not** import. Inspecting a pre-existing
cache before replacing and importing its source says nothing about support for the
incoming output. Keep the installed source and imported cache under this driver's
control between these steps. After reviewing the inspection and deciding to reset,
run the following separate step:

```sh
if [ "$installed_hash" = "$(shasum -a 256 ./consumer/model.glb)" ]; then
  gda asset-pipeline run --project ./consumer --source-root ./consumer \
    --files '[{"source":"model.glb","target":"res://model.glb"}]' --overwrite \
    --refresh '{"path":"res://model.glb","scene":"res://test.tscn","node":"/root/Test/Model"}' \
    --json
else
  printf '%s\n' 'Output changed: import and inspect it again before refreshing.' >&2
fi
```

The second call reuses the installed GLB; it still performs the ordinary
installation/import/load checks. It does not call Blender, regenerate the source,
or repeat omitted processing. For a selected set, check every output and its
required referenced files. This procedure has no lock or atomicity guarantee;
changes by another driver or engine invalidate the inspected state. Re-import and
inspect again after a change. No saved receipt or mandatory inspection gate is
introduced.

LOD and embedded albedo were incomplete at the initial dogfood baseline. They are
not permanent rejection criteria: use the scope of the delivered measurement. An
explicitly low vertex budget (for example `--max-vertices 1` for a larger model)
still demonstrates a localized omission. An incomplete sample does not cancel a
later explicit reset request; it prevents verification from passing.

## What the workflow does

Refresh starts only after file processing, installation, Godot import and load, and
any requested content-observation collection complete successfully. It then:

1. samples the newly imported GLB through `resource inspect-model-content`;
2. reads the current daemon and Engine session status;
3. resets the runtime through the existing `daemon stop`, `daemon start --scene`,
   and `daemon wait-ready` lifecycle;
4. samples the selected running instance through `game inspect-model-content`;
5. compares the imported and runtime samples; and
6. optionally captures a later frame in the same new session.

The result is `pipeline.refresh`. Its `completed` list separates imported sampling,
stop, start, readiness, instance sampling, comparison, and capture. `before`,
`ready_session`, and `after` report session state; `stop`, `start`, and `ready`
retain projected lifecycle facts, including harness installation or synchronization
and created paths or sections. `imported`, `instance`, and `comparison`
contain the facts used for the verdict. The top-level pipeline stages remain
separate from these refresh stages.

`status: verified` requires a new ready session in the requested window mode, an
instance observation bound to that session, the requested resource and node paths,
complete comparable content, and equal content digests. A stale session or a wrong
resource, node, or content digest cannot pass. Unsupported or incomplete sampling
returns `incomplete`; differing comparable content returns `mismatch`. Either causes
the pipeline to fail with its useful partial result retained.

Runtime state is not preserved across the reset. The workflow does not hot reload,
rebind arbitrary resources, keep history or a registry, create asset identities, or
call project methods to bypass the read-only observation boundary. Recovery does not
regenerate producer output or repeat a destructive action.

## Model content comparison

Refresh composes the independently usable `resource inspect-model-content` and
`game inspect-model-content` fact commands. Their shared native measurement,
supported geometry and material scope, limits, trust effects, and incomplete-result
rules are defined in the [static model content guide](../../../docs/model-content.md).

The workflow uses the same configured Godot executable for import sampling and
the new session. It compares only complete samples with matching measurement and
reported engine version strings. This is a compatibility check, not an executable
fingerprint. Unsupported or omitted content is `incomplete`; it cannot be accepted
as verified. A complete digest mismatch reports `mismatch`. The digest remains a
bounded content comparison, not a general resource identity or proof of all visual
behavior.

## Capture and failure evidence

A requested capture occurs after the instance observation. It must report the same
new session, the requested launched scene, and a later or equal Engine frame. This
associates the PNG with the session and observation order. It does not prove that
the selected instance remained unchanged until the captured pixels. The capture's
`launched_scene` remains the scene used to launch the session; it does not mean the
selected asset or current scene.

On timeout, launch failure, missing instance, unsupported content, mismatch, or
capture failure, inspect `error.partial_result.refresh`. Its `completed`
stages show what finished. Native gda failure codes, diagnostics, and causes remain
available rather than being replaced by a successful earlier-stage result. `after`
is the final status read and is the best available last-known daemon/session state;
it does not itself prove readiness. If that final read also fails, `issues` records
that the final state is unavailable. The workflow does not silently retry the launch
or rebuild the asset.

For incomplete verification, the error message also summarizes the completed
reset stages and the before/last-observed running state and session IDs. A result
can therefore report a new running session and still be unverified. Completed
stop/start/readiness stages are not undone when comparison is incomplete. If no
reset stage completed or the final status is unavailable, the message says so;
consult the retained stage facts and localized content reasons before another
explicit refresh.

A completed content match remains a match if capture or the final session check
fails later. In that case, the message preserves the comparison and identifies the
failed refresh stage; it does not describe the content as unverified. If comparison
was never reached, the message says it was not completed.
