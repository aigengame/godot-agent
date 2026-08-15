---
status: accepted
---

# Harness export-cleanliness: `gda export run` strips it, the harness self-disables in exported builds

ADR-0017/0018 install the [gda harness](../../CONTEXT.md) as a `project.godot` `[autoload]`
entry plus a `res://addons/gda_harness/` script, so `gda-daemon` can run [live
operations](../../CONTEXT.md) inside an [Engine session](../../CONTEXT.md). ADR-0018 makes
the harness **inert** in a non-daemon run and offers an explicit `gda daemon uninstall`
teardown. But a **shipped build must carry zero daemon-related files or config — as if the
mechanism never existed — and this must not depend on the developer remembering to
uninstall.** Inert-but-present is not enough (build hygiene, store/AV review, and "no
orphaned dev tooling" are real requirements); and `gda export run` had no harness awareness,
so a forgotten harness shipped verbatim.

> **Outcome (2026-08-15, #654) — decision 1's snapshot file list now comes from the
> installer.** #654 widened `gda daemon uninstall` to also delete the engine-generated
> `gda_harness.gd.uid` sidecar, so the strip below removes it too. The snapshot therefore
> reads its file list from `harness_artifacts()` (script + `.uid`) rather than naming the
> files itself — otherwise the strip would delete a file the restore never puts back and
> the "dev project is left byte-identical" guarantee would break. Decision 1's text, which
> names "`project.godot` + the harness file", is preserved as the point-in-time record.

The engine forecloses the obvious fixes (verified against the Godot source):

- **An export cannot remove a `project.godot` autoload after the fact.** `project.binary` is
  serialized **whole** from `ProjectSettings` *after* every `EditorExportPlugin` hook, and no
  hook can alter the packed settings (`editor/export/editor_export_platform.cpp`
  `save_custom`; `editor/export/editor_export_plugin.h` exposes only file/resource/scene
  hooks). So once the autoload is in `project.godot`, it is in every export.
- **`override.cfg` re-leaks it.** Settings loaded from `override.cfg` go through `set()` into
  the very `props` map `save_custom` serializes (`core/config/project_settings.cpp`), so any
  export run by a binary that loads `override.cfg` — including the editor binary `gda export
  run` uses — writes the autoload straight back into `project.binary`.
- **`exclude_filter` removes only files**, never the autoload entry. A file-excluded but
  still-referenced autoload then logs `ERR_CONTINUE` and is skipped at startup
  (`main/main.cpp` autoload loop) — startup error spam in the shipped game (this corrects
  ADR-0018 point 3's "crashes the exported game" wording: it is skip-with-error, not a hard
  crash, on the current engine — but still unacceptable).
- **Feature-tagged autoloads are not supported** — `autoload/GdaHarness.editor=…` registers an
  autoload literally *named* `GdaHarness.editor`; the feature override is never consulted at
  autoload load.

So the only reliable guarantee is that the autoload is **gone before the export reads the
project** — it must never be present at export time, not stripped during it.

## Decision

**1. `gda export run` strips the harness transactionally.** Before the native
`--export-<mode>` run (the [Headless launch](../../CONTEXT.md) native-export channel), the
operation paired-uninstalls the harness — autoload entry first, then files, the crash-safe
ordering ADR-0018 already uses — then, in a `finally`, **restores the exact pre-export state**
(a byte-exact snapshot of `project.godot` + the harness file, NOT a fresh install — which
would canonicalize a noncanonical autoload, synthesize one for a stray harness file that had
none, or rewrite a stale body to the current version). The artifact is therefore harness-free
**by construction and forget-proof** (no `gda daemon uninstall` step required), the dev
project is left **byte-identical**, and a mid-export crash leaves the project harness-**absent**
(the safe direction — no orphaned autoload), which the next `gda daemon start` repairs. It is
a no-op when no harness is installed.

**2. The harness self-disables in any exported build.** As defence in depth for export routes
that bypass `gda export run` (the Godot editor GUI, a raw `godot --export-*`), the harness
`_ready()` returns immediately under `OS.has_feature("template")`. `template` is true **only**
in an exported template build and false on the editor (tools) binary every daemon session runs
on (`core/os/os.cpp`), so this never disables a legitimate session and a harness that *did*
reach a shipped build does literally nothing, regardless of launch args.

**3. Coverage: gda export = physically clean; every other route = provably inert.** The
supported, agent-driven release path (`gda export run`) gives full physical absence; any other
export route gives guaranteed inertness (the harness may physically remain there but never
activates). Extending *physical* cleanliness to non-gda routes is deliberately **not** taken
on here (see Considered options).

## Considered options

- **Strip the autoload at export via an `EditorExportPlugin` (rejected — impossible).** No hook
  can modify the packed `ProjectSettings`/autoload list; `project.binary` is written wholesale
  after all plugin hooks. This is the pivotal constraint that rules out an "export-time filter".
- **`exclude_filter` the harness file only (rejected).** Removes the file but leaves the
  autoload entry dangling → startup `ERR_CONTINUE` error spam in the shipped game. Removal must
  be **paired** (entry + file), which is what `gda daemon uninstall` / the decision-1 strip do.
- **Install the autoload via `override.cfg` instead of `project.godot` (rejected).** Aimed to
  keep `project.godot` clean, but `override.cfg` settings are loaded into the same `props` map
  `save_custom` serializes, so the export (run by an `override.cfg`-loading binary) re-leaks the
  autoload into `project.binary`. It also packs/loads in the exported context. Buys nothing.
- **Feature-tagged autoload `autoload/GdaHarness.editor` (rejected).** Unsupported by the engine
  (registers a literally-named autoload; feature override not consulted at autoload load).
- **Rely on the existing manual `gda daemon uninstall` before export (rejected).** Forget-prone
  — the exact failure this ADR exists to remove. Kept as an explicit teardown, not the guarantee.
- **Ephemeral install — auto-uninstall on daemon/session stop, self-heal on next start
  (deferred).** Would make the project clean between sessions and thus give *physical*
  cleanliness on **all** export routes (incl. the editor GUI). Deferred: it reopens ADR-0018
  Decision 1's "no per-launch `project.godot` mutation" (concurrent-editor races, dirty-on-crash),
  adds per-session churn, and still leaves a crash-residual window (covered as inert by
  decision 2). Revisit only if non-gda routes later need physical, not just inert, cleanliness.

## Consequences

- `gda export run` (`run_export_operation`) now brackets the native export with the harness
  strip/restore: the strip reuses the ADR-0018 paired `uninstall`, but the restore **replays a
  byte-exact snapshot** (not `install`), so the dev project is byte-identical even for a
  stale / stray-file / noncanonical prior state; a no-op when no harness is present. Verified
  by unit tests (byte-identical restore, stray-file → no autoload synthesized, stale-body →
  not re-materialized, restore-on-exception) and an e2e (`export run --mode pack` archive omits
  `gda_harness.gd` **and** the packed `project.binary` declares no `GdaHarness` autoload, the
  project restored after).
- The `template` gate is proven **statically** (a CI-runnable test asserts `if
  OS.has_feature("template"): return` is the first statement of `_ready()`). Its
  **behavioural** proof needs a real exported template binary (export templates + the e2e job)
  and is deferred to **issue #301**, guarded by a tripwire e2e that warns once templates exist.
  The separate "exported pck runs inert" e2e proves the **no-marker** resident-inert path
  (ADR-0018 point 2) — it runs on the editor binary, where `template` is false — packing via a
  **raw** `godot --export-pack` (which does not strip) and asserting the harness is genuinely
  present, so "inert" stays meaningful.
- **ADR-0018 is the harness *install/lifecycle* record; this ADR owns the *export/teardown*
  half.** ADR-0018 carries a dated pointer to this ADR and retains the corrected note on its
  point 3 (the dangling-autoload behaviour is `ERR_CONTINUE`, not a crash). The trust model is
  unchanged (ADR-0009): this is build hygiene + defence in depth, not a new security boundary —
  a shipped harness was already inert by the launch-marker gate (ADR-0018 point 2).
- CONTEXT.md needs no new term: the [gda harness](../../CONTEXT.md) glossary entry ("stays
  dormant in … a shipped build") remains accurate; the strip is a `gda export run` behaviour, not
  a property of the term.
- README states the harness is dev-only (stripped from `gda export run` artifacts, self-disables
  in shipped builds) and that `gda daemon uninstall` is the explicit manual teardown.
