---
status: accepted
---

# gda harness lifecycle, and the concurrent-editor trust boundary

ADR-0017 serves [live operations](../../CONTEXT.md) by running `gda` code inside a
gda-owned game — the [engine session](../../CONTEXT.md) — via the
[gda harness](../../CONTEXT.md). Getting that code into a *running game* is
constrained by the engine: Godot has **no `--autoload` CLI flag** (autoloads come
from `project.godot`'s `[autoload]` section), `--script` **replaces** the main loop
(so it cannot run *alongside* the real game the way `operations.gd` runs a headless
op), `EditorPlugin.add_autoload_singleton()` is **editor-only** and **edits
`project.godot`**, and `override.cfg` is for **exported** projects. So in-engine
code cannot be as zero-install as Phase-1's bundled `--script operations.gd`.

Separately, ADR-0009's trust boundary assumes `gda` operates on a *trusted* project
but says nothing about *who else* operates on it. In Phase 2 a human plausibly opens
a Godot editor on the same project to view, run, or verify agent output — a
[concurrent external editor](../../CONTEXT.md) — and Godot takes **no project lock**,
so two instances can touch the project at once.

> **Outcome (2026-06-22, #220) — the harness is a multi-op `match` dispatcher, and
> it carries a duplicated-with-drift-test copy of the headless coercion helpers.**
> Adding `game get` / `game set` turned the bootstrap harness's hardcoded
> single-op `if op == "game-tree"` check into a `match op:` dispatcher with one
> handler per live op — the natural shape as the live catalogue grows. More
> consequentially, `game set` must coerce a CLI string to a property's declared
> Godot type using the **same** table headless `node set` uses (the command
> catalogue promises one coercion contract). The two cannot share a `.gd` module:
> `operations.gd` runs via `godot --headless --script <abs-fs-path>` (often
> projectless), while the harness is a `res://addons/gda_harness/` autoload inside
> the project — no single `preload()` reaches both runtime contexts, and the
> harness installer copies exactly one file. So the pure coercion / property-
> introspection helpers are **duplicated verbatim** into the harness, delimited by
> matching marker comments in both files, with a drift test asserting the two
> blocks stay byte-identical. The duplication is a deliberate consequence of the
> irreconcilable runtime contexts, not an oversight; if the appended-helper count
> grows, the treatment to revisit is per-module fragments + an automatic summary
> (the same direction RULES.md flags for central registries), under its own ADR.

> **Outcome (2026-06-22, #225 / PR #247) — the harness lifecycle is complete:
> version self-sync and paired uninstall.** Point 1's "self-syncs the harness to the
> running `gda` version" is realized: `_materialize` prepends a `# gda-harness-version:
> <N>` header (from a `HARNESS_VERSION` const — NOT the package version, since the
> harness changes far less often than `gda` ships), so the version check rides the
> existing idempotent content-compare: a mismatch re-materializes, a match is a no-op
> (never an unconditional overwrite, which would bump mtime and trip the concurrent-
> editor prompt of point 4). `gda daemon start` runs this self-sync **whether or not a
> daemon is already up** (PR #247 review), so upgrading `gda` never strands a stale
> harness; `harness_synced` is true only on a real stale→current rewrite, distinct from
> a first install (`installed_harness`). The paired `gda daemon uninstall` strips the
> `[autoload]` entry **first**, then deletes the files — crash-safe ordering, so a
> mid-failure leaves a harmless stray inert `.gd`, never a dangling autoload (point 3);
> the autoload edit is scoped to the `[autoload]` section so a same-named key elsewhere
> is never touched. Verified resident-inert in a plain run and an exported PCK.

## Decision

**1. The harness is an installed autoload, not a runtime injection.** `gda` bundles
the harness and installs it into the trusted project's `project.godot [autoload]`
via an idempotent, agent-runnable `gda daemon install`. `gda daemon start`
auto-installs when missing and **reports** the effect (e.g. `installed_harness:
true`), and **self-syncs** the harness to the running `gda` version. This is a
**one-time, version-controllable, install-time write** — not a per-launch mutation
(which would corrupt config against a concurrent editor, see point 4).

**2. A runtime gate keeps the harness inert unless the daemon launched the session.**
At startup the harness checks for the daemon's launch marker (in the args after
`--`); absent it, it **returns early — starting no server and opening no connection —
and stays resident**. It must *not* free itself: Godot autoloads must not be removed
with `free()` / `queue_free()` at runtime (it crashes the engine), so a resident
do-nothing autoload is the safe inert form. Thus it is dormant in a human editor run,
a plain `godot --path` run, and — crucially — a **shipped/exported build**. No
uninstall is required for safety (only for build hygiene, point 3).

**3. `gda daemon uninstall` removes the autoload entry and the harness files
together.** A release-hygiene step for teams that require dev tooling to be
physically absent from the build. Removal is **paired**: stripping the files via an
export `exclude_filter` while leaving the `[autoload]` entry pointing at a missing
script **crashes the exported game at startup**, so removal goes through `gda`, not a
hand-edited export filter.

**4. Concurrent external editor is out of scope; single-driver is assumed
(extending ADR-0009).** `gda`, running outside the editor, cannot see the editor's
open buffers, so it **cannot** replicate godot-mcp-pro's open-file write guards
(pro can, because it *is* the editor). Phase 2 therefore declares a concurrent
external editor's writes out of scope, with two cheap safeguards:

- **Live injection performs zero runtime `project.godot` mutation** (point 1),
  eliminating the worst tier — config corruption.
- **Headless writes are atomic with an optimistic mtime check**, failing with
  `file_changed_externally` when the target changed since `gda` last read it. The
  human's editor provides the reciprocal "file changed on disk, reload?" prompt on
  its side.

## Considered options

- **Runtime-injected autoload, reverted on stop** — rejected: per-launch
  `project.godot` mutation races a concurrent editor and leaves the project dirty if
  the daemon crashes mid-session.
- **Auto-generated wrapper main scene** that hosts the harness and loads the real
  main scene as a child — rejected: it intercepts the boot flow and changes
  SceneTree-root semantics, breaking games that assume they are the root main scene.
- **Human-enabled editor plugin (godot-mcp-pro's model)** — rejected: it inserts a
  human gate into an agent-driven flow.
- **Defend against a concurrent external editor** (lock files, process scans,
  open-buffer detection) — rejected for Phase 2: Godot takes no project lock and
  leaves no reliable signal, so detection is unreliable; the single-driver
  assumption is documented instead.

## Consequences

- Phase-2 live carries a **one-time install step**; Phase-1 headless stays
  zero-install. The boundary is explicit and intentional (ADR-0017).
- ADR-0009's trust boundary gains a second axis: from "trusted project" to also
  "**single driver**". New glossary terms: `gda harness`, `engine session`
  (ADR-0017), `concurrent external editor`.
- `file_changed_externally` is a **candidate** operation-source code — registered in
  the `src/gda/error_codes.py` registry and the ADR-0002 table by the slice that
  implements it, not by this ADR. (Realized as an operation-source code by #226: the
  guard is engine-side, emitted from `operations.gd` via `_fail(...)`, not assigned by
  the classifier.)
- `.godot/` import-cache races between a concurrent editor and an engine session
  remain possible but are recoverable (md5-keyed reimport); not defended, documented.
