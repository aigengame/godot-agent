# Model checks

`gda asset-pipeline check` evaluates project-owned expectations against the
bounded facts from `gda resource inspect-model`. It can inspect a Godot resource
now or consume a previously saved raw JSON report.

Inspect a resource in the selected Godot project:

```sh
gda asset-pipeline check \
  --expectations ./model.expectations.json \
  --path res://models/character.glb \
  --project ./game \
  --json
```

To work offline, first save the native report without changing its JSON shape,
then pass it to `--report`:

```sh
gda resource inspect-model res://models/character.glb \
  --project ./game --json > ./reports/character.json
gda asset-pipeline check \
  --expectations ./model.expectations.json \
  --report ./reports/character.json \
  --json
```

Select exactly one of `--path` and `--report`. `--path` accepts the native
inspection controls `--subtree`, `--max-nodes`, and `--max-items`. A supplied
report already carries its scope and limits, so these controls cannot override it.

The command schema describes CLI and structured inputs:

```sh
gda asset-pipeline check --schema
```

The expectation document format is described below. It is intentionally local
JSON rather than a registry or saved workflow.

## Expectation document

The document contains 1 to 256 checks. Each check has a unique, nonempty `id`
and one of seven `kind` values. The file must be at most 1 MiB.

This small example checks a model like the fixture used by
`tests/asset_pipeline/fixtures/model_check_fixture.gd`:

```json
{
  "checks": [
    {
      "id": "left-arm",
      "kind": "node",
      "node": "Character/RootBone/Skeleton3D/Arm_L",
      "type": "MeshInstance3D"
    },
    {
      "id": "model-size",
      "kind": "dimensions",
      "min": [5.9, 3.9, 0.9],
      "max": [6.1, 4.1, 1.1]
    },
    {
      "id": "meshes",
      "kind": "count",
      "metric": "mesh_instance_count",
      "min": 2,
      "max": 2
    }
  ]
}
```

Node locators are exact resource-relative paths. A short name such as `Arm_L`
does not match the full path above. `.` means the resource root; selecting a subtree
does not rebase node paths. Discover paths,
surface indexes, binds, animations, tracks, and observed coverage with
`gda resource inspect-model` before writing expectations.

Range bounds are inclusive, finite, and nonnegative. Supply `min`, `max`, or both.
`dimensions` uses three-axis vectors and checks resource-space static mesh AABB
size. It does not infer posed or collision dimensions.

Keep the expectation JSON in version control with the code that consumes the
model. Change its conditions when project intent changes; do not silently relax
conditions to accept a new export. Save a baseline report explicitly when a
comparison is useful, and retain its engine and measurement scope. Neither file
requires a registry or a persistent run history.

## Check kinds

| Kind | Required fields | Meaning |
| --- | --- | --- |
| `node` | `node`; optional `type` | Requires the exact node path and, when supplied, its exact Godot type. |
| `count` | `metric`; `min` and/or `max` | Checks `node_count`, `mesh_instance_count`, or `unique_mesh_count` over the inspected subtree. |
| `dimensions` | `min` and/or `max` | Checks the three inclusive resource-space size ranges. |
| `material` | `node`, `surface`; optional `name`, `path` | Requires an effective material on the selected surface and optionally matches its name or resource path. |
| `bone` | `node`, `name` | Requires the named bone on the selected `Skeleton3D`. |
| `skin_bind` | `node`, `bind`, `skeleton`, `bone` | Requires an explicit resolved skin bind to the exact skeleton path and bone name. |
| `animation_target` | `node`, `animation`, `track`, `target`; optional `bone` | Checks a statically resolved animation track target and optional bone. It does not prove successful playback. |

Material presence and name can pass when the engine reports them. If an expected
material path is unavailable, the result is `insufficient`, not an inferred match
or mismatch. Missing detail in partial surface, bone, skin, or animation coverage
is also `insufficient` when the report identifies that omission.

## Verdicts and failures

Every check returns its `id`, `location`, `expected`, `actual`, `reason`, and one
of these verdicts:

- `pass`: the observed facts satisfy the expectation.
- `fail`: complete observed facts contradict the expectation.
- `insufficient`: bounded coverage cannot decide the expectation.

The overall verdict is `fail` if any check fails, otherwise `insufficient` if any
check is insufficient, otherwise `pass`. All three are completed evaluations and
exit with status 0. Read the structured `verdict`; do not use process status as the
content verdict.

Malformed expectations, invalid reports, missing projects, and native inspection
failures exit nonzero. Their structured error preserves the native gda failure and
includes the bounded partial result when available.

A saved report is caller-provided evidence. `observation_source` is
`supplied_report`; the command does not claim that the report is fresh or that its
original inspection is reproducible. Reports are admitted as raw native
`resource inspect-model` JSON and are limited to 16 MiB.

## Baseline comparison

Add `--baseline` to compare a saved native report with the selected current report:

```sh
gda asset-pipeline check \
  --expectations ./model.expectations.json \
  --report ./reports/current.json \
  --baseline ./reports/baseline.json \
  --json
```

The expectation `verdict` and `comparison` are separate results. A comparison is
compatible only when engine major/minor, inspected subtree, and measurement basis
match. Engine patch versions are ignored. The two resource paths may differ and
are reported as `resources.before` and `resources.after`.

Compatible complete reports list observed additions, removals, and changes.
When either report has omitted or unavailable relevant facts, comparison status is `partial` and
lists incomplete sections. It never interprets an absent item in partial coverage
as a deletion. Incompatible reports return `non_comparable` with reasons rather
than fabricated changes.
