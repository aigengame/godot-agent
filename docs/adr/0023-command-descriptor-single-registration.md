---
status: accepted
---

# The command descriptor is the single per-command registration; render, dispatch channel, and schema are projections of it

ADR-0017 put a static `kind` (`HEADLESS` / `EXPORT` / `LIVE`) on the command
descriptor so the runner factory selects an execution channel by a single field,
not an identity special-case. ADR-0004 / ADR-0012 made `--schema` and the
aggregate manifest *derive* from the descriptor's models, walking the **live Typer
command tree** rather than a hand-maintained list (zero central registry to keep in
sync). Both ADRs point the same way: **one fact per command, everything else
derived.** This ADR finishes that arc for the two facts still left out.

Today the [command descriptor](../../CONTEXT.md) (`HeadlessCommand`: `operation`,
`input_model`, `output_model`, `classify`, `kind`) holds five of a command's facts,
but two more live elsewhere:

- **The human renderer** lives in `render.py`'s 61-entry, type-keyed `_RENDERERS`
  dict. Adding a command means defining the renderer *and* appending a dict entry —
  a central append hot-spot ~hundreds of lines from the descriptor, and a
  parallel-merge conflict point.
- **The execution channel for recipe commands** (the `daemon` lifecycle group and
  `screen` capture) is selected by **two identity frozensets**
  (`_DAEMON_COMMANDS`, `_SCREEN_COMMANDS` in `cli.py`) — a *third* selection
  mechanism alongside `kind` (export) and the default sentinel/live path. The
  dispatch in `_run_params_json` (and its argv twin) branches three different ways;
  a command added to the wrong-or-no frozenset routes **silently to the wrong
  runner**, with no test asserting the sets are complete.

So adding or renaming one command touches ~5 sites across `cli.py`, `render.py`, and
`models.py`, held together only by the `operation`-name string convention. An
architecture review (the 2026-06-23 deepening sweep) had two independent passes —
command dispatch, and models/schema/render — converge on the same root cause: **the
descriptor is the natural single registration, but it is only half-built.**

## Decision

**1. The `HeadlessCommand` descriptor is the single per-command registration. It
absorbs the two missing facts.**

- **`render`** — the per-result renderer, typed `Callable[[M], str]` against the
  command's `output_model` `M`. `emit_result` renders through the descriptor's
  `render`; the type-keyed `_RENDERERS` dict in `render.py` is **removed**. (The
  renderer *functions* stay in `render.py`; only the dispatch dict goes.)
- **`recipe`** — an optional execution-channel seam. A command **with** a `recipe`
  is fulfilled by it (the `export` / `daemon` / `screen` paths that bypass the
  sentinel `cmd.emit`): the recipe **produces the outcome** (resolve the project +
  run the CLI-side operation, returning the result model or a `Failure`), and a
  shared dispatch tail emits it through the descriptor's **own `render`** — so a
  recipe command renders identically to a sentinel one and emission stays
  single-sourced, never duplicated per recipe. A command **without** a recipe goes
  through `cmd.emit` with the `kind`-selected runner (sentinel `operations.gd` for
  `HEADLESS`, daemon IPC for `LIVE`). This collapses the tri-modal selection —
  export-by-`kind`, daemon-by-identity, screen-by-identity — into **one**
  descriptor-driven branch (`recipe is None`?) and **dissolves both identity
  frozensets** and the per-command identity-branching inside the old daemon
  dispatch (each daemon command now carries its own recipe).

  > **Outcome (2026-07-01, #353/#357):** project resolution moved OUT of the recipe
  > into the shared `_dispatch_recipe` tail — it resolves once (via the same
  > `_resolve_project_or_fail` the sentinel `_dispatch` uses) and hands the recipe an
  > ALREADY-resolved project, so an invalid `--project` is a structured
  > `project_not_found` on the recipe channel exactly as on the sentinel one, with no
  > per-recipe resolution. A recipe now **produces the outcome from a resolved project**
  > (it no longer resolves). A `projectless: bool` descriptor field excludes pure meta
  > emitters (e.g. `gda skill`, ADR-0024) from resolution, so an inherited invalid
  > `$GDA_PROJECT` cannot make a projectless meta command fail.

  > **Outcome (2026-08-18, #670):** the field is now `inherits_project: bool`
  > (default `True`; meta commands set `False`), because "projectless" had come
  > to overstate it: the field decides only whether a command **inherits** a
  > project context (`$GDA_PROJECT`, then the cwd). Whether a command **accepts**
  > an explicit `--project` is its CLI signature's decision — `gda info` takes
  > one and has it validated (ADR-0006 amendment), while `skill`/`version`/`help`
  > take none. The exclusion-from-inheritance behaviour above is unchanged.

**2. The render map and dispatch routing are projections of the descriptor, not
parallel registries.** On the `cmd.emit` path the descriptor is already in hand, so
rendering and channel selection read off `cmd` directly. Where a whole-surface view
is needed, it is built by walking the **live Typer tree** — the same authority
ADR-0012 established for the schema manifest (`surface.py`), each leaf already
carrying its backing descriptor as `gda_command` — never a hand-maintained list.

**3. Scope is the Python side only; behavior is preserved.** The cross-language
`operation`-name contract (the Python ↔ GDScript `OP_ERROR` mirror) and the GDScript
dispatch in `operations.gd` are **out of scope** (left to their own future
decision). The public contract is unchanged: same `--json` / `GdaError` / `--schema`
output, same dispatch outcomes. This is an internal deepening.

**4. A registration invariant test replaces the runtime `KeyError`.** A test walks
the live Typer tree and asserts every dispatchable command's descriptor carries a
renderer and resolves to exactly one channel (`recipe` xor `kind`-runner), and that
no renderer is orphaned. The "command wired without a renderer" failure
(`render()`'s `KeyError`) moves from first-invocation to test time.

## Considered options

- **Per-command-group modules** (`gda/commands/scene/` holding that group's models +
  descriptor + renderer + CLI wiring). Rejected **for now**: a much larger move on
  the central files, higher parallel-merge risk, and — as the review's models/render
  pass cautioned — it can merely *spread* the `models.py` god-file across many files
  without deepening anything unless the import surface and registration are also
  consolidated. Revisit in its own ADR if the descriptor consolidation proves
  insufficient.

  > Outcome (2026-08-14, ADR-0040) — revisited and adopted. Both attached
  > conditions held (registration consolidated on the descriptor + live Typer
  > tree; the split consolidates the import surface), and the central files kept
  > growing interleaved. ADR-0040 records the split.
- **Keep the type-keyed `_RENDERERS` dict; only dissolve the frozensets.** Rejected:
  it leaves the render append hot-spot and a second registry standing — half the
  friction the review identified.
- **A decorator / explicit registry of all descriptors.** Rejected: the live Typer
  tree already *is* the registry (ADR-0012); a parallel registry duplicates that
  authority and reintroduces the very drift this ADR removes.
- **Fold only `daemon`/`screen` into the descriptor, leave `export` on its
  `kind`-path.** Rejected: it would leave the dispatch bimodal (recipe-by-field +
  export-by-kind) for no real gain; one uniform `recipe` seam is simpler and
  complete.

## Consequences

- **One place per command.** The render map and dispatch are derived, so the two
  append hot-spots dissolve and the silent-misroute frozenset risk is gone.
- **`recipe` signature unification is the one-time cost.** The three recipes
  (`run_export_operation`, the per-command `run_daemon_*_operation`, `run_screen_*`)
  are wrapped as thin per-command closures of one shape — `recipe(params, *,
  project, godot)` returning the result model or a `Failure` — so the dispatcher
  calls them uniformly and a shared tail emits the outcome via `cmd.render`.
  Emission is **not** duplicated in each recipe; it stays the one shared path both
  channels use. Contained, and paid once.
- **`emit_result` gains a renderer argument**; `render(result)`'s type dispatch is
  removed (or retained only as a thin internal fallback). `render.py` keeps the
  renderer functions and loses the 61-entry table.
- **gda-mcp is unaffected** — it still derives its tool surface from the aggregate
  manifest (ADR-0011/0012); the descriptor's new fields are not part of the wire
  schema.
- **Two follow-ons stay open, each its own ADR if pursued**: the cross-language
  `operation`-name contract / GDScript dispatch (the review's deferred candidate),
  and the per-group module split above.
- Generalises the `kind` selector of ADR-0017 and reuses the tree-walk of ADR-0012;
  amends neither — it completes the direction both set.
