---
status: accepted
---

# Per-command-group modules: vertical group slices over the shared descriptor core

> **Amendment (2026-08-20, #657):** the module-tree sketch below annotates
> `daemon.py` as "recipe-backed, not LIVE". Since #657 the group carries ONE
> `kind = LIVE` command — `daemon wait-ready`, which routes through the live
> channel (daemon-served, like `diag errors`) because its object is the engine
> session the daemon holds. The rest of the group stays recipe-backed as
> decided; the module docstring of `gda.commands.daemon` records the exception.

ADR-0023 made the `HeadlessCommand` descriptor the single per-command registration
and left one follow-on open: the per-command-group module split, "rejected for now
... revisit in its own ADR if the descriptor consolidation proves insufficient."
The evidence since #353/#357 shows the flat layout no longer expresses the
structure the descriptor created:

- `models.py` (4272 lines), `cli.py` (3624), `render.py` (822), and `errors.py`
  (701) are four central files that every command change crosses. Adding one
  command touches all four, plus a test file — a five-file change for a
  one-concept edit.
- The per-group clusters inside `models.py` and `cli.py` are already cohesive and
  mutually independent (no cluster imports another), but physically interleaved:
  `resource`, `shader`, and `project` symbols alternate in both files, so file
  order no longer maps to any boundary.
- The whole-file suppressions on `cli.py` (`F811` in ruff, `reportRedeclaration`
  in pyright — ADR-0029/0030) exist only because 15 sub-app command sets share
  one module; both ADRs record that they also mask genuine redefinitions.

The two conditions ADR-0023 attached to this move now hold: registration is
consolidated (the descriptor plus the live Typer tree, never a parallel
registry), and this split consolidates the import surface (a group module
imports shared machinery downward; the composition root imports group modules,
not hundreds of symbols).

## Decision

**The command surface splits into one module per `Command group` under
`gda/commands/`, over an unchanged shared core.** The target tree:

```text
src/gda/
  cli.py             # composition root: root Typer app, mounts every group
  dispatch.py        # CLI dispatch tails + runner seams (moved out of cli.py)
  commands/
    scene.py node.py script.py resource.py shader.py theme.py
    project.py export.py                      # headless domain groups
    game.py diag.py logger.py perf.py
    input.py screen.py                        # live groups (ADR-0017/0019)
    daemon.py                                 # gda's own daemon lifecycle group
                                              #   (ADR-0017; recipe-backed, not LIVE)
    meta.py                                   # info, skill, schema (ADR-0005)
  models.py          # shared contract core (shrunk; see below)
  errors.py          # shared classifier machinery (shrunk)
  render.py          # shared render helpers (format_value, render_node_tree)
  headless.py surface.py runner.py export_runner.py live_runner.py
  parser.py error_codes.py exit_codes.py execution.py
  binary.py display.py project.py skill_targets.py
  daemon/  harness/  mcp/  ops/  skill/       # unchanged
```

1. **A group module owns its whole vertical slice**: the group's params/result
   models, its render functions, its group-specific classifiers, its
   `HeadlessCommand` descriptors, its recipe implementations, and its Typer
   command bodies. The recipe modules merge into their groups: `export_run.py`
   → `commands/export.py`, `script_run.py` → `commands/script.py`,
   `screen_ops.py` → `commands/screen.py`, `daemon_ops.py` →
   `commands/daemon.py`, `skill_ops.py` → `commands/meta.py`. This also brings
   `EXPORT_RUN_COMMAND` / `SCRIPT_RUN_COMMAND` (previously in `cli.py`, tied to
   its runner seams) home to their groups.
2. **Each group module exposes one `register(root: typer.Typer) -> None`.**
   A domain group mounts its sub-app (`root.add_typer(...)`); `meta.py` attaches
   its top-level commands (ADR-0005) and closes over `root` for the `gda schema`
   surface walk. `cli.py` calls the sixteen `register` functions in the current
   `add_typer` order, so `--help` output is unchanged. Mounting **is** the
   registration — the live Typer tree stays the only registry (ADR-0012/0023).
3. **`gda/dispatch.py` owns the CLI dispatch tails** — `_emit`,
   `_resolve_project_or_fail`, `dispatch_domain`, `dispatch_meta`,
   `dispatch_recipe`, `_run_params_json` plus its
   `register_params_json_dispatch` call, the argv params-building rule
   `params_or_bad_parameter`, and the runner seams `make_runner` /
   `make_export_runner` / `make_live_runner`. It sits below the group modules
   (which call the tails) and above `headless.py` (which stays free of CLI
   imports, ADR-0015). Seams are referenced late (`dispatch.make_runner` at
   call time), so test monkeypatches keep binding.
4. **The shared core keeps every single authority where it is.** `models.py`
   shrinks to the cross-command contract core: error/envelope models,
   schema/manifest models, path normalization, the value-projection models
   (ADR-0035), and shared field-description constants. `errors.py` keeps the
   shared decision tree (`Failure`, `classify_run`, `classify_launch_or_crash`);
   a classifier moves out only when a single group consumes it. The
   failure-CONSTRUCTOR taxonomy (the `*_failure` builders over `make_failure`)
   stays in `errors.py` whole, single-consumer ones included, so the taxonomy
   still reads from one place (ADR-0002's registry framing) — only *classifiers*
   are group-local. `error_codes.py`, `exit_codes.py`, `parser.py`,
   `execution.py`, `skill_targets.py` (ADR-0027 quarantine), `binary.py`,
   `display.py`, and `project.py` do not move — `binary`/`display` are also
   imported by the Panda Adventure e2e tier.
5. **Dependency direction**: `cli` → `commands/*` → `dispatch` → `headless` →
   runners / `errors` / `models` → foundation. A group may import another
   group's public symbol one-way where the language genuinely shares a shape —
   four such edges exist: `node` → `scene` for `SceneNode` and
   `derive_scene_root_name` (the filename-stem default an `--instance`
   composition reuses); `shader` → `script` for the `ScriptSetMode` edit
   interface `shader set` reuses; `logger` → `diag` for the `SourceFrame`
   location and the `--limit` option the two log-reading groups share (the
   ADR-0022/0026 lineage); and `screen` → `input` for the
   `InputSequenceEvent` union that `screen capture --await-events` embeds
   (#661): the event shapes are the input group's owned contract — the
   discriminated union, its per-kind field rules, and their harness
   application — and the predicate capture REUSES them verbatim rather than
   forking a second event vocabulary, so the edge points at the owner and
   stays one-way (added 2026-08-25). No reciprocal group imports. A shape **no single
   group owns** stays in the `gda.models` core rather than moving into one,
   because several groups read it (`NodeProperty`, `EngineVersion`,
   `MAX_WINDOW_FRAMES`). A shape a **single group does own** moves to that
   group even when its name points elsewhere: `ResourceReference` reads as the
   `resource` group's but is `project find-references`'s result shape, so it
   lives in `commands/project.py`.

## Considered options

- **Horizontal split only** (per-group `models/`, `render/`, `cli/` trees, no
  vertical merge). Rejected: smaller files, same coupling — one command change
  still crosses three trees, which is the cost this ADR removes.
- **Directory per group** (`commands/scene/{models,render,cli}.py`, the ADR-0023
  sketch). Rejected for now: triple the files with no added boundary; a single
  module per group is the smallest usable shape, and promoting a group to a
  package later is a reversible local move.
- **A `gda.models` compatibility façade re-exporting moved symbols.** Rejected:
  Python import paths are not public ABI (ADR-0011 — agents consume the CLI/MCP
  surface only); a façade is a second import surface that can only drift.
  In-repo consumers (tests) update instead.

## Consequences

- Adding a command touches its group module, the SKILL.md command table (CI-gated
  by `tests/test_skill_surface_sync.py`), and its test file — plus
  `ops/operations.gd` for a sentinel op (out of scope here). The five-file change
  amplification across the shared core is gone.
- The `cli.py` whole-file suppressions (`F811`, `reportRedeclaration`) are
  dropped; command function names are unique within each group module.
- Tests keep driving the same public surface; per-group test files update
  imports; the registration-invariant, schema, and human-output tests hold
  unchanged semantics. Runner-seam monkeypatch targets move from `gda.cli` to
  `gda.dispatch` (one shared helper in `tests/support.py`, plus direct uses).
- `gda.cli:app` (entry point), `__main__.py`, `daemon/`, `harness/`, `mcp/`,
  and both `.gd` payloads are untouched. The public CLI/MCP ABI does not change.
- The GDScript side (`operations.gd` dispatch, the byte-identical harness
  mirror) stays under its own future decision (ADR-0018/0023) — out of scope.
- Migration lands in reversible slices, each keeping ruff, pyright, and the
  fast suite green: extract `dispatch.py`; move the headless domain groups; move
  the live groups and `meta`; shrink the core files and drop the suppressions.

> **Outcome (2026-09-01, #687):** the ADR-0004 amendment that put typed `evidence` on
> the failure envelope moved two edges in the core, and §5's chain is the reason both
> ended up where they did.
>
> - **`gda.models` -> `gda.script_errors` (new).** `FailureEvidence.script_errors` is a
>   `list[ScriptError]`, so the models core now names a foundation module. Downward and
>   consistent with §5, but not free: `script_errors` can never reach back for the
>   shared field-description constants §4 assigns to `models.py` without closing a
>   cycle. Accepted on cohesion — `ScriptError` is the parser's own published type and
>   splitting it from the parser to satisfy an import would be worse.
> - **`gda.errors` -> `gda.render` (added, then removed in the same PR's review).**
>   Building the failure `diagnostics` prose from a renderer helper put the
>   presentation layer inside the core's import closure, which §5's chain does not
>   admit — `gda.render` is reached DOWN into from group altitude, and its symbols are
>   imported nowhere else. It also gave one function two reasons to change, one of them
>   a wire field: the same helper fed human stdout and a published `diagnostics`
>   string. The form moved to `gda.script_errors` as `script_error_line()`, a lexical
>   projection of the type that module owns, so `errors -> script_errors <- render` and
>   both edges point downward. Pinned by
>   `tests/test_render.py::test_the_core_never_imports_the_presentation_module`.
>
> No general import-boundary gate was added. The one test above pins the single
> direction this review found inverted; a repo-wide gate is a larger decision with its
> own cost, and nothing yet shows the narrow pin is insufficient.

> **Outcome (2026-09-01, #685):** giving the failure channel a human rendering adds
> one importer of `gda.render` from below group altitude — `gda.headless`, for
> `render_failure` alone.
>
> The direction §5 fixes still holds. `gda.render` imports `gda.models` and
> `gda.script_errors` and nothing else, which places it on the same tier as
> `gda.errors`, so `headless -> render` is the chain's own
> `headless -> runners / errors / models` step and closes no cycle. What #687's
> review found was the OPPOSITE edge — the core reaching UP into presentation, with
> a wire field on the other end of it.
>
> The edge cannot be removed by injection the way the success channel's is.
> `emit_result` takes a renderer as an argument because the group binds `render=` on
> its own descriptor (ADR-0023); `render_failure` is ONE layout for every registered
> code precisely so a command cannot grow a private one, so no group owns it and
> none can supply it. Nor may the edge widen: the allowance is pinned to that single
> symbol by
> `tests/test_render.py::test_the_failure_channel_takes_only_the_renderer_no_group_can_supply`,
> so headless cannot become a general consumer of presentation. The guard test the
> #687 note names was renamed and widened to state both halves.
