# Content observations

Use optional content observation collection when a resource path or UID is not
enough to distinguish the installed bytes. Collection is part of
`gda asset-pipeline run`; it does not add a separate command, store, or persistent
asset identity.

```sh
gda asset-pipeline run --project ./consumer --source-root ./production \
  --files '[{"source":"model.glb","target":"res://art/model.glb"}]' \
  --collect-observations --json
```

The result appears at `pipeline.content_observations`. To save the same object,
name a new local file explicitly:

```sh
gda asset-pipeline run --project ./consumer --source-root ./production \
  --files '[{"source":"model.glb","target":"res://art/model.glb"}]' \
  --collect-observations \
  --observations-output ./model-observations.json --json
```

The output path is exclusive: the command refuses an existing file instead of
overwriting it. Saving is optional, including for a partial or failed collection.
Without `--collect-observations`, the ordinary install, import, and handoff behavior
is unchanged. `--observations-output` and `--declared-output-sha256` require
collection.

## Check a declared output hash

`--declared-output-sha256` accepts a JSON map from selected installed `res://`
outputs to caller-declared SHA-256 values:

```sh
gda asset-pipeline run --project ./consumer --source-root ./production \
  --files '[{"source":"model.glb","target":"res://art/model.glb"}]' \
  --collect-observations \
  --declared-output-sha256 \
  '{"res://art/model.glb":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}' \
  --json
```

The check reads the selected file after processing and installation, before Godot
import. For example, it hashes a resized PNG rather than its original production
file. A mismatch stops before import and returns the observed digest in the partial
result. This declaration is caller-provided provenance, separate from observed
file and engine facts. The existing `caller_declared_provenance` field remains
separate as well.

## What the result means

Each selected asset reports the installed source bytes before and after import,
using SHA-256 and byte size. It also reports:

- `declared_dependencies`: selected recipe references; other importer inputs remain
  unresolved;
- `configuration_before` and `configuration_after`: hashes of the raw bytes in the
  Godot-published import sidecar, when available;
- `import_before` and `import_after`: Godot-published cache status, artifact paths,
  and the importer and source-file declarations recorded by the sidecar;
- `artifacts`: hashes and sizes of the published import artifacts;
- `engine`: engine identity returned by a completed Godot load check; and
- `unavailable`, `issues`, and digest `reason` values that explain facts which could
  not be collected.

An importer named by a sidecar is only the declared importer. It does not prove
that the importer is registered or active. Likewise, the configuration digest
identifies the observed sidecar bytes. It is not a semantic configuration identity,
does not normalize equivalent rewrites, and does not prove every effective importer
setting. On a cold import, `configuration_before` can be `null` and
`import_before.cache_status` can be `missing`; the post-import fields then describe
what Godot published. Engine identity is available only from a completed load.

Different installed bytes at the same `res://` path produce different source
digests. Identical observed bytes produce the same digest. A raw sidecar byte change
produces a different configuration digest even when the source stays unchanged.
These facts describe disk and import observations; they do not prove the content of
a running instance or complete reproducibility.

## Stability, failures, and limits

The collector reads selected installed sources and any available configurations
before import. After the import attempt and any completed load checks, it reads the
selected sources, configurations, and reported artifacts, then reads that covered set once more.
A pre-existing source or configuration whose observed bytes change across this
window is refused rather than reported as stable. A configuration first created by
a cold import is expected and is not treated as a change.

`status: stable` means only that the covered, bounded byte reads were stable under
the single-driver assumption. The process is not a filesystem transaction and does
not coordinate other tools. It cannot detect an unobserved ABA change that restores
the same bytes and metadata before a read, and it makes no runtime or reproducibility
claim.

Collection uses these bounds:

- at most 128 distinct resource paths across file reads;
- at most 256 MiB for one file;
- at most 1 GiB in total across all reads, including final stability reads; and
- at most 128 import-artifact locators from Godot in each before/after observation
  phase. The distinct-path limit can be reached first.

Omitted artifact locators and unavailable, missing, changed, or over-limit reads are
diagnosed in the result. A collection failure returns the useful facts gathered so
far in the command's partial result without claiming successful completion. If an
observation output was requested and can be created, that partial observation is
saved explicitly; an existing output file is never replaced.
