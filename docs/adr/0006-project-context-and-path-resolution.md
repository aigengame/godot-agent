---
status: accepted
---

# Project context and path resolution for headless operations

Headless operations act on files addressed by path. Godot resolves `res://`
paths — and inter-resource references inside a scene/resource — against the
*project* it was launched with. A one-shot `godot --headless --script` process
launched with no `--path` infers its project from the current working
directory, so the same command run from a different directory resolves `res://`
differently, or runs projectless. That made results silently cwd-dependent and
left no defined home for path semantics as the command surface grows
(`node`, `script`, `resource`, … all take paths).

## Decision

**`gda` resolves a project directory and passes it to the engine as `--path`.**
Resolution precedence, mirroring the `--godot` binary resolution (`gda.binary`):

1. The `--project <dir>` flag.
2. The `GDA_PROJECT` environment variable.
3. The current working directory.

An explicitly named directory (flag or env) **must** be a Godot project (hold a
`project.godot`) or `gda` surfaces it as an error rather than running against
the wrong context. The cwd fallback counts as a project only when it holds the
marker; otherwise resolution yields *no project* and the engine runs
**projectless** — the pre-existing behaviour, under which only filesystem paths
(absolute or cwd-relative) resolve. This keeps project context opt-in for
callers who pass absolute paths and never touch `res://`.

**Path normalization happens once, at the CLI layer**, before a path reaches an
operation: engine-resolved virtual paths (`res://`, `user://`, `uid://`) pass
through untouched (the engine resolves them against the project), and a
filesystem path has `~` expanded. Operations therefore receive a path whose
resolution rule is already fixed and documented, rather than each operation
inventing its own.

This applies to every path-taking command, not just `scene` — it is the project
of record for the whole Phase-1 surface.

## Consequences

- `res://` resolves deterministically against the chosen project regardless of
  `gda`'s cwd; a scene's inter-resource references resolve in their own project.
- Meta commands (`gda info`) take no path and no project — they run projectless.
- The test suite's temp-project fixture is exercised for real by passing
  `--project`, rather than being a directory the engine never sees.
- `--project`/`$GDA_PROJECT` is process context, not an operation parameter, so
  it does not appear in a command's `--schema` input contract (ADR-0004) — the
  same treatment as `--godot`.

## Considered options

- **`--project` flag, projectless fallback** (chosen) — explicit and
  agent-controllable, mirrors `--godot`, and preserves absolute-path usage with
  no project.
- **Derive the project from the target path** (walk up to the nearest
  `project.godot`) — zero-config, but undefined when the target is outside any
  project, and a single call spanning multiple paths could imply different
  roots.
- **Filesystem paths only, no `res://`** — simplest, but `res://` is core Godot
  vocabulary that later slices (`node`, `script`, `resource`) need, so this only
  defers the decision.
