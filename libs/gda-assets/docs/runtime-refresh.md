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

Measurement version 2 includes the complete admitted static LOD thresholds and
index bytes returned by Godot 4.6's public RenderingServer surface readback. This
lets refresh reject an old running instance after generated LOD content changes
and accept the replacement after the controlled session reset. The LOD data is a
Godot import/runtime representation; a standard GLB does not itself carry that
Godot representation. The sampler's script-side limits apply after the engine has
materialized the public surface Dictionary, as detailed in the static-content
guide.

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
