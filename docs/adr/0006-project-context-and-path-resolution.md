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

`gda export run --output` is the one export-specific filesystem carve-out: the
native export process runs with the Godot project as its cwd, so a relative
`--output` is resolved against the invoker's cwd before the native export is
spawned. Preset-configured `export_path` values are not CLI paths and keep
Godot's project-relative export semantics; in particular, `~` in a preset value
is a literal path component, not shell-style home expansion.

## Consequences

- `res://` resolves deterministically against the chosen project regardless of
  `gda`'s cwd; a scene's inter-resource references resolve in their own project.
- Meta commands (`gda info`) take no path and no project — they run projectless.

  > **Amendment (2026-08-18, #670):** the enduring rule is that a meta command
  > never **inherits** a project — steps 2–3 of the precedence are skipped for
  > it, so an inherited invalid `$GDA_PROJECT` cannot break the commands an
  > agent reaches for first (#357). Whether it **accepts** an explicit
  > `--project` (step 1) is the command's own signature decision: `gda info`
  > now takes one, validated by this ADR's strictness rule, so an orchestrator
  > can pass a uniform argv to every command; `skill`/`version`/`help` take
  > none. The descriptor field recording inheritance is `inherits_project`
  > (ADR-0023).

- The test suite's temp-project fixture is exercised for real by passing
  `--project`, rather than being a directory the engine never sees.
- `--project`/`$GDA_PROJECT` is process context, not an operation parameter, so
  it does not appear in a command's `--schema` input contract (ADR-0004) — the
  same treatment as `--godot`.

> **Amendment (2026-08-31, #697 / #763) — a target another `project.godot` owns is
> REFUSED, not derived from; and containment is one answer, in one place.**
>
> The option below, "derive the project from the target path", stays rejected — and this
> amendment states what follows from that, which the original decision left for a caller
> to discover: gda refuses a target the resolved project does not own, and `--project`
> naming the owner is the supported way to say what you mean.
>
> **Why derivation stays rejected.** The reason recorded below got stronger, not weaker.
> One call spanning several paths could imply several roots — and since #663's batch
> `script validate` that is the normal case, not a corner. `project_root`, the field #695
> added so a caller can attribute a `res://` cascade, would stop naming one thing. And the
> dogfooded failure (GDA-DF-035) is a caller pointing gda at the wrong root: refusing NAMES
> that condition, while deriving would paper over it and leave the caller unable to tell
> which root a verdict came from.
>
> **What "does not own" means — two halves, one verdict.** A target belongs to the
> resolved project only when both hold, and either one failing is the same refusal:
>
> 1. **Containment** — the target is inside the resolved project's tree
>    (`gda.project.path_outside_project`). Unchanged in rule; see the second half of this
>    amendment for where it is now decided.
> 2. **Ownership** — the resolved project is the *nearest* `project.godot` at or above the
>    target (`gda.project.owning_project`). This half is new. A target can sit squarely
>    inside the resolved tree and still be owned by a nested project, and then its own
>    `res://` references resolve against a root that is not its own: `outer/inner/main.gd`
>    reads `valid` under `--project outer/inner` and `invalid` under `--project outer`,
>    from a cascade of false missing-file errors. #695 pinned that as a deliberate scope
>    line waiting on this amendment.
>
> **Finding an owner is not deriving one.** The walk is bounded (it stops at the resolved
> project), lexical (it reads the caller's own spelling, so a monorepo's symlinked-in
> shared directory stays inside as the engine reads it), and its result is REPORTED, never
> adopted: resolution is still flag > env > cwd, one call still has exactly one root, and a
> batch naming several owners still returns one verdict. The rejected option's two
> objections — undefined outside any project, several roots per call — do not apply: no
> owner simply means no refusal.
>
> **All three commands, for one reason each.** `script validate` and `script run` apply
> ownership because a target compiled or run against a foreign root resolves its OWN
> `res://` references there. `resource import` applies it because the ENGINE does: the
> editor's scan skips a directory holding a nested `project.godot`
> (`EditorFileSystem::_should_skip_directory`,
> `editor/file_system/editor_file_system.cpp:3482` — "Skip if another project inside
> this"), so such an asset cannot be imported into the outer project at all. Without the
> check gda accepted the request, spent an engine pass and returned `not_importable`,
> while `--dry-run` predicted a sidecar that would never appear. An earlier draft of this
> amendment exempted `resource import` on the claim that the import pass walks a nested
> project's files; that claim was false, and the engine source is what corrected it.
>
> **Projectless is checked too, and still exists.** With no project resolved there is
> nothing to be outside OF, so containment cannot fire — which is exactly how the other
> GDA-DF-035 reading (a project nested in a plain workspace, validated from the ancestor)
> reached a projectless engine and produced the same cascade with `project_root: null` as
> the only clue. Ownership runs to the filesystem root there and refuses, naming the
> owner. A standalone `.gd` that no `project.godot` claims is still validated projectless
> by filesystem path.
>
> This half NARROWS the fallback above, and says so rather than claiming a continuity it
> does not have. The original sentence — "keeps project context opt-in for callers who
> pass absolute paths and never touch `res://`" — is about a calling CONVENTION, and a
> caller using that convention on a file that does live in a project is now refused. Three
> things make it the right trade, and the third is a real cost:
>
> 1. a projectless verdict on a file inside a project is computed in a context that file
>    never runs in — `res://` resolves against gda's cwd, and the project's autoloads,
>    `class_name` registry (ADR-0032) and settings are all absent — so even `valid: true`
>    is only accidentally right;
> 2. the refusal names the exact `--project` to pass, so the true verdict is one flag away;
> 3. **but that flag widens the Project-code execution surface** (CONTEXT.md, ADR-0009): a
>    projectless validate runs no autoloads, and `--project` boots them. gda is trading a
>    verdict that could be wrong for one that costs the project's own startup code. Within
>    the Trusted project assumption that is the right way round — a wrong answer is worse
>    than a documented execution point — but it is a trade, not a free improvement.
>
> The `cd`-out remedy blessed below is for the CONTAINMENT half only. It does not escape
> ownership: that walk runs to the filesystem root regardless of cwd, so for a file some
> project claims, `--project` is the only remedy.
>
> **The standalone-script consequence is blessed, not worked around.** With the refusal in
> place and `--project ""` refused as empty, there is no flag that says "ignore the project
> I am standing in". Deliberately: the cwd is the LAST resolution step, so the CONTAINMENT
> answer is to not stand there — `cd` out, or name the owner — and a `--no-project` escape
> hatch would add a cross-cutting flag to every command in the surface for a case no
> dogfooding round has produced. Revisit it when one does. For a file another project OWNS,
> `cd` changes nothing (see above) and `--project <owner>` is the only remedy.
>
> **Scheme sets stay per-command.** `user://` and `uid://` are engine-virtual but not the
> project's namespace, so neither containment nor ownership says anything about them, and
> each command's scheme set follows from its own contract: `script run` refuses them
> because lifting a project-relative path onto `res://` cannot represent a second scheme
> (ADR-0031); `resource import` refuses them because an asset is by definition a `res://`
> member; `script validate` accepts them because the engine loads them and reports a true
> verdict (verified on Godot 4.6.3: `gda script validate user://bad.gd` returns the real
> parse error). Narrowing `script validate` would remove a working input with no
> demonstrated defect.
>
> **`target_outside_project` is minted** (ADR-0002 registry) and is what all of the above
> reports. `project_not_found` was true of neither the condition nor the remedy here — a
> project WAS resolved, and the fix is to name a different one — and #697 stated the honest
> trigger for a sibling code as a second producer of the class. Convergence produces three:
> `script validate`, `script run` and `resource import` all report it. The refusal carries
> the three coordinates of the mismatch as typed evidence (#687): `target_location`,
> `project_root`, `owning_project` — each omitted when that refusal does not know it, which
> is how gda hands over what it found without acting on it.
>
> **One containment answer, in the path authority (#763).** Three gates used to answer this
> ADR's own question three ways, and two of them disagreed: `resource import` refused ANY
> literal `..` (so `res://foo/../bar.gd`, which collapses net-inside, was refused there and
> accepted by both script commands) and split on `PurePosixPath`, so `res://..\x.png` was one
> segment carrying no `..` at all — inert on POSIX, a real parent-directory escape on
> Windows. `gda.project` now owns the whole answer: `canonical_res_path` (the engine's
> `String::simplify_path`, reproduced step by step — including the empty join, so the
> project root has ONE spelling, `res://`, closing the parity gap PR #766 documented),
> `res_escape_remainder` (canonicalize, then read what is still climbing), and the two
> functions above. `gda.script_errors`, where the canonicalizer was written, is now one
> consumer among several — the import that had this ADR's authority depending on a stderr
> parser is gone. What stays with `script run` is what is genuinely its own: the
> engine-`strip_edges` suffix and the engine-log line-boundary rules, which keep a canonical
> identity matchable against what the engine echoes back, plus the root address naming a
> directory rather than a script.
>
> **Scope: the commands that implement it.** This amendment states a rule about the
> commands whose gates ask the question — `script validate`, `script run`,
> `resource import`. Other path-taking commands do not ask it: `gda scene validate
> res://inner/main.tscn --project outer` still compiles a nested project's scene against
> the outer root and can produce the same class of cascade. Extending the rule is a
> separate decision with its own surface, not something this one silently implies.
>
> **Not closed here.** Two known gaps, both measured:
>
> - a case-differing project spelling (`--project …/Game` against on-disk `…/game`) is
>   still refused on a case-insensitive filesystem: both readings compare strings and
>   `Path.resolve()` does not canonicalize case. A real fix needs a `samefile`-style walk
>   and is independent of this decision;
> - `script validate --all` still produces the cascade. It enumerates through gda's OWN
>   `res://` walk (`operations.gd`'s `_should_descend`), which excludes only
>   `res://.godot`, while the engine's scan additionally skips a nested-project directory
>   (and a `.gdignore` one) — so `--all` compiles nested-project scripts against the outer
>   root and the same file gets opposite answers depending on the selector. Closing it
>   means changing the shared walk every collector uses (`script list`, `scene list`,
>   project analysis, the import gap listing), which is its own slice with its own blast
>   radius.

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
