---
status: proposed
---

# The Python core splits into functional packages in its import order

`src/gda` holds the Python side of gda as 30 top-level modules, 13,744 lines at
`6d5da3df3` (the tip of `refactor/gda-layering-dev`; `src/` is byte-identical to
`main` at `e1c49b93d`, where the 2026-10-04 architecture review measured it), beside
the packages that ADR-0040's target tree left as they were: `commands/`, `daemon/`,
`harness/`, `mcp/`, and the payload directories `ops/` and `skill/`. ADR-0040 moved
the command groups out of the core and said of the core: "the shared core keeps every
single authority where it is". It gave the core a direction, point 5's chain `cli →
commands/* → dispatch → headless → runners / errors / models → foundation`, and its
#687 Outcome note declined a gate for that direction: "a repo-wide gate is a larger
decision with its own cost, and nothing yet shows the narrow pin is insufficient".

The direction holds. The 57 import edges between the 30 modules form no cycle, and
the longest path from each module to a leaf puts every module on one of ten tiers:

| Tier | Modules |
|---|---|
| 0 | `engine_log`, `execution`, `exit_codes`, `import_evidence`, `live_numbers`, `parser`, `project_file`, `skill_targets` |
| 1 | `project`, `project_tree` |
| 2 | `binary`, `runner`, `script_errors` |
| 3 | `export_runner`, `live_runner`, `models`, `provenance` |
| 4 | `display`, `error_codes`, `render` |
| 5 | `errors` |
| 6 | `completed_run`, `headless` |
| 7 | `dispatch`, `hints`, `import_pass`, `surface` |
| 8 | `cli` |
| 9 | `__main__` |

The directory does not show it. The 30 files are one alphabetical list, in which
`exit_codes` (tier 0; read by the launch primitive, the error-code registry and the
daemon protocol, and linked from the READMEs as the source of the public exit-status
ABI) stands beside `cli` (the composition root). A reader learns the order by reading
imports, and finds the modules that most of the tree reads the same way:

| Module | Importing modules under `src/gda` |
|---|---|
| `headless` | 21 |
| `models` | 20 |
| `dispatch` | 16 |
| `project` | 16 |
| `errors` | 15 |
| `execution` | 14 |
| `runner` | 13 |

Five modules hold two or more concepts each, and the concepts have names in
CONTEXT.md:

| Module | Lines | Concepts in the file |
|---|---|---|
| `errors` | 1659 | the `Failure` primitive with 23 constructors (16 of them called from one module each, 4 only from inside the file), and the decision trees `classify_run`, `classify_launch_or_crash` and `classify_live` with the remedies |
| `models` | 1390 | the four clusters ADR-0040 point 4 names: the `Error envelope` models, the schema and manifest models, the `Value projection` with the shared result shapes and path normalization, and the `Project-tree mutation report` records |
| `runner` | 1199 | the `User-data placement`, the `Headless launch` with the `Raw run`, and the sentinel argv spelling with the payload path |
| `project` | 991 | the ADR-0006 path authority with containment and project resolution, and the main-scene verdict a live launch reads (#829) |
| `headless` | 860 | the `Command descriptor` with its emission, the Typer option factories with the ancestor `--json` propagation, and the argv bindings that `--schema` publishes (#669) |

Three homes contradict their imports. `display` has three importers, all
daemon-side (the daemon command group, the daemon server and the session), and sits
at the root. `live_runner` is the LIVE channel's client and the only top-level
module that imports a subpackage (`daemon.discovery`, `daemon.protocol`); it sits
beside the headless core. `forward_child_stderr`, the producer half of ADR-0002's
#803 child-stderr rule, sits in `headless`, so the import-pass step (#1079) reaches
up into the command descriptor's module for one function that needs only a
`Failure` and a `Raw run`. Two more edges hide under `TYPE_CHECKING` in `models`
(`UserDataReport` from `runner`, `ProjectTreeSettlement` from `project_tree`), with
a comment that says the core and the primitive "sit on the SAME tier". They annotate
function parameters only, no model is rebuilt, and neither `runner` nor
`project_tree` imports `models`.

Three Outcome notes on ADR-0040 (#979, #985, #1079) each placed a module that "owns
BEHAVIOUR and not only a shape" beside the core, in neither `models` nor a group:
`completed_run`, `project_tree`, `import_pass`. The pattern has a rule but no place
in the tree.

One more line divides the 30 modules, and the directory does not show it either.
The CLI framework (`typer`, `click`, `rich`) is imported by `cli`, by every command
group, and by exactly four core modules: `dispatch`, `headless`, `hints`, `surface`.
The other 24 modules, and `daemon/` and `harness/`, import none of it. The daemon is
also a process of its own: `gda daemon start` spawns `python -m gda.daemon`, and
`daemon/__main__.py` is that entry.

The friction is navigation, not correctness. A slice that touches the core reads a
flat list. An agent that changes one concept pages through a file that holds three.
A reviewer checks a dependency direction by hand, because the #687 note left the
gate for later.

## Decision

### 1. A `core` package of five library packages, in the import order

The shared core moves into five packages under one package, `gda.core`, ordered by
their imports. The daemon, the harness and the command surface sit beside it at the
root, above it in the order:

```text
exit_codes < core.project < core.engine < core.contract < core.failure < core.steps
           < daemon < harness < surface < commands < cli
```

```text
src/gda/
  __main__.py  cli.py  exit_codes.py   root: the entry point and the exit-status ABI
  core/                                the library every component and the surface build on
    project/    the Trusted project on disk: files, tree, import cache, paths, main scene
    engine/     one Godot process: binary, launch, user data, sentinel wire, logs, errors
    contract/   the ADR-0004 structured output: envelope, schema, values, mutations, render
    failure/    the Error envelope's producers: catalog, classify, error codes, child stderr
    steps/      Shared steps: the import pass and the completed run
  daemon/     gda-daemon, in place, now with its display probe and its client
  harness/    the gda harness and its installer                         unchanged
  surface/    the Command surface: descriptor, options, bindings, dispatch, hints, manifest
  commands/   one module per Command group (ADR-0040)                   unchanged
  mcp/  ops/  skill/                                                    unchanged
```

- `gda.core.project` holds what is on disk before any engine runs: `project_file`,
  `project_tree`, `import_evidence`, and the `project` module split into `paths`
  (the ADR-0006 path authority, containment and project resolution) and
  `main_scene` (the main-scene verdict a live session launch reads).
- `gda.core.engine` holds one Godot process: `binary`, `engine_log`,
  `script_errors`, `export_runner`, `execution`; the `runner` module split into
  `launch` (the `Headless launch` with the `Raw run` and the runner seam),
  `user_data` (the `User-data placement`) and `sentinel` (the ADR-0002 sentinel
  wire: the argv half, the result half that is `parser` today, and the default
  sentinel runner).
- `gda.core.contract` holds the ADR-0004 structured output: `models` split into
  `envelope`, `schema`, `values` and `mutations`; `render`; `live_numbers`.
- `gda.core.failure` holds the producers of the `Error envelope`: `errors` split
  into `catalog` and `classify`; `error_codes`; and `child_stderr`, the new home of
  `forward_child_stderr`.
- `gda.core.steps` holds the `Shared step`s: `import_pass`, `completed_run`.
- `gda.daemon` stays where it is and gains `display` and, as `client`,
  `live_runner`.
- `gda.surface` holds the `Command surface`: `headless` split into `descriptor`,
  `options` and `bindings`; `dispatch`; `hints`; the `surface` module as
  `manifest`; `provenance`; `skill_targets`.

`gda.core` is a library, and three measured properties say what that word means
here. The test of §6 asserts all three:

- **Closed.** Every module under `gda.core` imports only `gda.core` and
  `gda.exit_codes`. Nothing under it imports the daemon, the harness, the surface,
  a command group or the CLI.
- **Framework-free.** No module under `gda.core` imports `typer`, `click` or
  `rich`. The CLI framework enters at `surface` and above.
- **Process-free.** No `__main__.py` sits anywhere under `gda.core`, and no entry
  point in `pyproject.toml` names a module under it. `gda.daemon` has a
  `__main__.py` (spawned by `gda daemon start`), and `cli` and `__main__` are the
  CLI's entries; all three stay outside.

`gda.core` holds packages only: no module sits directly under it, so there is no
`core/util.py` to grow.

Three modules stay at the root. `exit_codes` is the bottom of the order and the one
module outside `gda.core` that `gda.core` imports: the launch primitive, the
error-code registry and the daemon protocol read it, and the READMEs link
`src/gda/exit_codes.py` as the source of the public exit-status ABI. It stays beside
`cli` as the second of gda's two public faces: `cli` is the command ABI,
`exit_codes` the exit-status ABI. `__main__` sits above `cli`. The entry points
`gda.cli:app` and `gda.mcp:main` do not change.

`commands`, `harness`, `mcp`, `ops` and `skill` do not change. For the order they
rank as follows. `daemon` sits above `gda.core`: it imports `project`, `engine` and
`contract`, and nothing in the core imports it. `harness` sits above `daemon`: its
one edge goes to `project_file`, and the daemon and export command groups import
it; the `daemon` package does not. `surface` sits above both: `dispatch` imports the
daemon client. `commands` sits above `surface`, as ADR-0040 point 5 says. `mcp` sits
above `cli`: it imports no core module today (ADR-0011: its only dependency on gda
is the public CLI ABI), and nothing imports it. `ops` and `skill` hold no Python
module.

A package name is the concept, not the tier: `failure` is "what produces a
failure", not "tier 5", and `core` is "the library", with the three properties
above, not "everything below `commands`". A module goes to the package whose
concept owns it. Where that puts the module in the order is a consequence, and §3
checks it.

### 2. Module map

Every top-level module and its new name. A module that is not split keeps its file
name and its content.

| Package | Module today | Module after | Owns |
|---|---|---|---|
| root | `exit_codes` | `gda.exit_codes` | the exit-status table (public ABI) |
| root | `cli` | `gda.cli` | the composition root |
| root | `__main__` | `gda.__main__` | `python -m gda` |
| core/project | `project_file` | `gda.core.project.project_file` | the `project.godot` text format |
| core/project | `project_tree` | `gda.core.project.project_tree` | the `Project tree inventory` |
| core/project | `import_evidence` | `gda.core.project.import_evidence` | the `Import evidence` |
| core/project | `project` (part) | `gda.core.project.paths` | the ADR-0006 path authority, containment, project resolution |
| core/project | `project` (part) | `gda.core.project.main_scene` | the main-scene verdict (#829) |
| core/engine | `binary` | `gda.core.engine.binary` | Godot binary resolution |
| core/engine | `engine_log` | `gda.core.engine.engine_log` | the engine log parse |
| core/engine | `script_errors` | `gda.core.engine.script_errors` | recognized script errors and the shutdown leak |
| core/engine | `export_runner` | `gda.core.engine.export_runner` | the native-export launch |
| core/engine | `execution` | `gda.core.engine.execution` | the execution kinds and the live-stack constraint |
| core/engine | `runner` (part) | `gda.core.engine.launch` | the `Headless launch`, the `Raw run`, the runner seam |
| core/engine | `runner` (part) | `gda.core.engine.user_data` | the `User-data placement` |
| core/engine | `parser` + `runner` (part) | `gda.core.engine.sentinel` | the ADR-0002 sentinel wire |
| core/contract | `models` (part) | `gda.core.contract.envelope` | the `Error envelope` models |
| core/contract | `models` (part) | `gda.core.contract.schema` | the `--schema` and manifest models |
| core/contract | `models` (part) | `gda.core.contract.values` | the `Value projection`, shared result shapes, path normalization |
| core/contract | `models` (part) | `gda.core.contract.mutations` | the `Project-tree mutation report` records |
| core/contract | `render` | `gda.core.contract.render` | the shared human renderers |
| core/contract | `live_numbers` | `gda.core.contract.live_numbers` | the numeric-literal fidelity rule |
| core/failure | `errors` (part) | `gda.core.failure.catalog` | `Failure`, `make_failure`, every constructor, the message helpers |
| core/failure | `errors` (part) | `gda.core.failure.classify` | the decision trees and the remedies |
| core/failure | `error_codes` | `gda.core.failure.error_codes` | the `Gda error code` registry |
| core/failure | `headless` (one function) | `gda.core.failure.child_stderr` | `forward_child_stderr` |
| core/steps | `import_pass` | `gda.core.steps.import_pass` | the engine import pass (#1079) |
| core/steps | `completed_run` | `gda.core.steps.completed_run` | the completed-run fields and projection (#979) |
| daemon | `display` | `gda.daemon.display` | the windowed-session display probe |
| daemon | `live_runner` | `gda.daemon.client` | the LIVE channel's client |
| surface | `headless` (part) | `gda.surface.descriptor` | the `Command descriptor`, emission, the Typer command class |
| surface | `headless` (part) | `gda.surface.options` | the option factories, the ancestor `--json` propagation |
| surface | `headless` (part) | `gda.surface.bindings` | the argv bindings `--schema` publishes (#669) |
| surface | `dispatch` | `gda.surface.dispatch` | the dispatch tails and the runner seams |
| surface | `hints` | `gda.surface.hints` | the `Near-miss hint` table |
| surface | `surface` | `gda.surface.manifest` | the `gda schema` manifest walk |
| surface | `provenance` | `gda.surface.provenance` | the `gda version` provenance |
| surface | `skill_targets` | `gda.surface.skill_targets` | the ADR-0027 known-agent targets |

The five split modules, definition by definition. A name that starts with `_` moves
with the public definition that uses it, and the list names it where two files
could claim it. Line counts are definition spans at `6d5da3df3`, without the module
header.

**`runner` → `launch` (≈695), `user_data` (≈395), `sentinel` (≈80, plus the 90 of
`parser`).**

- `launch`: `DEFAULT_TIMEOUT_SECONDS`, `DEFAULT_TIMEOUT_LABEL`, `LaunchFailure`,
  `TimeoutBound`, `RunResult`, `LaunchWatch`, `_CaptureOnly`, `_StreamCapture` with
  the four poll and grace constants, `launch`, `_launch_under`,
  `_not_found_result`, `_spawn_streamed`, `_end_process`, `LaunchFn`,
  `GodotRunner`.
- `user_data`: `USER_DATA_ROOT_ENV`, `UserDataReport`, `set_user_data_root`,
  `resolve_user_data_root`, `engine_data_path`, `data_path_env`,
  `UserDataUnwritable`, `UserDataPlacement`, `user_data_placement`,
  `_probe_data_path`, `_user_data_unwritable_stderr`, and the override global.
- `sentinel`: `OPERATIONS_GD`, `sentinel_args`, `SubprocessGodotRunner`, and the
  whole of `parser` (`RESULT_BEGIN`, `RESULT_END`, `result_sentinel_start`,
  `parse_result`, `build_result`, `error_envelope`).

`SubprocessGodotRunner` goes with the argv it spells, not with the primitive it
calls: the launch then names no payload, and `launch` is what the export runner,
`script run`, `scene preflight` and the import pass already call without one. The
`GodotRunner` seam stays with the `Raw run` it returns; the daemon client implements
it from below `surface`, and `dispatch` binds it.

**`errors` → `catalog` (≈1245), `classify` (≈330).**

- `catalog`: `Failure`, `make_failure`, the `M` type variable, every `*_failure`
  constructor and `containment_refusal`, the six output headers,
  `_labelled_output`, `_labelled_script_output`, `_tail`,
  `CAPTURED_OUTPUT_TAIL_CAP_BYTES`, `termination_phase`,
  `_recognized_errors_prose`, `_placement_evidence`, `_ended_run_diagnostics`,
  and `validation_error_message` with `_is_too_deep`: the primitive, the
  constructors, and the helpers that build their text.
- `classify`: `MIN_GODOT_VERSION`, `classify_launch_or_crash`, `classify_run`,
  `classify_live`, `_operation_error_from_payload`, `_live_error_from_payload`,
  `_LIVE_CLIENT_CODES`, `resolve_godot_binary_or_failure`,
  `unresolved_class_names`, `class_resolution_remedy` and their two constants:
  what reads a `Raw run`, a payload or an environment and decides which failure it
  is.

`classify` imports `catalog`. No edge goes the other way: a constructor builds one
failure and decides nothing.

**`models` → `envelope` (≈515), `schema` (≈260), `values` (≈385), `mutations`
(≈195).**

- `envelope`: `ErrorCategory`, `EnvironmentProbe`, `TerminationPhase`,
  `FailureEvidence`, `PLACEMENT_FIELD_NAMES`, `placement_fields`, `GdaError`,
  `GdaErrorEnvelope`, `OperationError`, `OperationErrorEnvelope`, `LiveError`,
  `LiveErrorEnvelope`, `LiveStackConstraints`.
- `schema`: `ArgvKind`, `ArgvBinding` with its spelling-schema constant,
  `CommandSchema`, `CommandManifestEntry`, `SurfaceManifest`.
- `values`: `normalize_path`, `NormalizedPath`, `RelayedLiveParams`,
  `ProjectRootedResult`, `ReferenceProjection`, `InlineValueProjection`,
  `TextureProjection`, `projected_value_schema_extra`, `NodeProperty`,
  `EngineVersion`, `StaleClassEntry`, `MAX_WINDOW_FRAMES`, and the shared
  description constants (`VALUE_PROJECTION_DESC`, `SET_ECHO_VALUE_DESC`,
  `OBJECT_SET_ECHO_DESC`, `STALE_CLASS_ENTRIES_DESC`, `CREATED_DIRS_DESC`,
  `RUNTIME_NODE_DESC`).
- `mutations`: `ExportCreatedFile`, `ExportModifiedFile`, `ProjectTreeMutations`.

`schema` imports `envelope`: `CommandSchema` embeds the error envelope and the
constraint. The two `TYPE_CHECKING` imports become ordinary imports: `envelope`
imports `UserDataReport` from `gda.core.engine.user_data`, and `mutations` imports
`ProjectTreeSettlement` from `gda.core.project.project_tree`. Both point down, and
neither target imports the contract.

**`headless` → `descriptor` (≈445), `options` (≈275), `bindings` (≈100), and
`forward_child_stderr` with `T` → `child_stderr`.**

- `descriptor`: the type aliases `M`, `Classifier`, `Renderer`, `Recipe`,
  `RunnerFactory`; `make_subprocess_runner`; `command_constraints`;
  `emit_failure`; `emit_result`; the params-json dispatch registration
  (`ParamsJsonDispatch`, which names `HeadlessCommand`, its registered global,
  `register_params_json_dispatch`); `schema_command_class` with
  `_from_command_line`, which reads that global; `HeadlessCommand`.
- `options`: `godot_option`, `project_option`, `schema_option`,
  `params_json_option`, `json_option`, `_GLOBAL_OPTION_NAMES`; the ancestor
  `--json` propagation (`ANCESTOR_JSON_META_KEY`, `set_ancestor_json`,
  `ancestor_json`, `RAW_ARGV_META_KEY`, `remember_argv`, `json_in_effect`,
  `_inherit_ancestor_json`, `_record_group_json`, `_group_json`,
  `walk_mounted_groups`, `adopt_group_json`).
- `bindings`: `command_argv_bindings`, `_bound_property`, `_takes_a_json_value`,
  `_is_compound_spec`.
- `child_stderr` (in `gda.core.failure`): `forward_child_stderr` and `T`, the
  unbound type variable that only its signature uses.

`schema_command_class` is the descriptor's Typer face: `HeadlessCommand` builds it,
and it reads the descriptor's models, kind and constraints. It is in `descriptor` so
that `bindings` imports nothing above it. The params-json registration is in
`descriptor` for two reasons: its callback type names `HeadlessCommand`, and
`schema_command_class` reads the global it rebinds, which an import of the value
from another module would read as its initial `None`. `descriptor` imports
`options` and `bindings`; `bindings` imports `options` for the global option
names; `options` imports neither.

**`project` → `paths` (≈770), `main_scene` (≈175).**

- `paths`: `GDA_PROJECT_ENV`, `PROJECT_MARKER`, `RES_PREFIX`,
  `ENGINE_VIRTUAL_PREFIXES`, `is_engine_virtual_path`, `expand_user_or_none`,
  `expand_user`, `project_anchored`, `canonical_res_path`,
  `res_escape_remainder`, `path_outside_project`, `target_location`,
  `owner_relative_target`, `owning_project`, `project_absolute`, the three
  violation classes, `case_mismatch`, `containment_violation`,
  `resolve_project_dir`, and their private helpers.
- `main_scene`: `MAIN_SCENE_UNDEFINED`, `MAIN_SCENE_UNRESOLVED`,
  `MainSceneUnrunnable`, `_MainSceneSetting`, `_unquoted_literal`,
  `_read_main_scene`, `_uid_cache_present`, `main_scene_unrunnable`, and the six
  setting-name constants.

`main_scene` imports `paths` for `PROJECT_MARKER`. The cache-directory name it
derives beside `import_evidence`'s constant moves as it is (#1077).

The map is the target. If a move shows a better place for a definition, the
implementing PR changes this map in the same PR. The rules in §3 do not change that
way.

### 3. Dependency rules

- Every import edge points down the order of §1. Inside a package the split files
  form no cycle, and the edges §2 names are the only ones between them.
- `gda.core` is closed, framework-free and process-free, as §1 defines the three
  words, and holds packages only.
- Every new package `__init__.py` is empty: `core` and its five packages, and
  `surface`. The three that exist today with a docstring (`daemon`, `harness`,
  `mcp`) keep it and gain nothing. A caller imports the leaf module:
  `from gda.core.failure.catalog import Failure`, never
  `from gda.core.failure import Failure`.
- No module re-exports another module's name. ADR-0040 rejected a façade, and one
  symbol under two names is what a façade is. Import paths are not a public ABI:
  gda-mcp consumes the CLI (ADR-0011), and every importer is in this repository.
- `tests/` keeps its layout. Its packages are drawn by reason to change (#836), not
  by the module under test. A test changes its import statements and its
  patch-target strings, nothing else.

Most of the order is measured. `binary`, `runner` and `script_errors` import
`project`, so `engine` is above `project`. `models` imports `execution`,
`script_errors`, `project`, `import_evidence` and the two type-only names, so
`contract` is above both. `errors` and `error_codes` import `models`, so `failure`
is above `contract`. Both steps classify, so `steps` is above `failure`. The daemon
server, session and protocol import `project`, `engine` and `contract`, and
nothing in the core imports the daemon, so `daemon` is above `gda.core`.
`dispatch` imports the daemon client, so `surface` is above `daemon`. Nothing in
`surface` imports a step; `commands` does.

Two orderings are choices, and the rule records why. `steps` is below `daemon`
although no edge joins them: both steps are headless, and keeping them inside the
closed core is what lets the test of §6 say "nothing in the library imports the
daemon". A shared step that must drive a session would be a new decision, not an
import. `daemon` is below `harness` although no edge joins them either: the
daemon and export command groups import the harness installer, and the daemon
package knows nothing of it.

The package edges at `6d5da3df3`, under the assignment of §1 and as counts of
import statements, before any move:

```text
core.engine   -> exit_codes 1, core.project 3
core.contract -> core.project 3, core.engine 4
core.failure  -> exit_codes 1, core.project 2, core.engine 5, core.contract 2
core.steps    -> core.engine 2, core.failure 2, surface 1   <- the one edge that points up
daemon        -> exit_codes 1, core.project 3, core.engine 7, core.contract 2
harness       -> core.project 1
surface       -> core.project 1, core.engine 6, core.contract 3, core.failure 3, daemon 1
commands      -> core.project 12, core.engine 23, core.contract 26, core.failure 10,
                 core.steps 4, daemon 5, harness 2, surface 43
cli           -> core.engine 1, surface 3, commands 1
```

The one upward edge is `import_pass -> headless` for `forward_child_stderr`. Its
move into `gda.core.failure.child_stderr` turns it into `core.steps ->
core.failure`, and the test of §6 then has nothing to report.

### 4. Relocation only

- A definition moves with its logic unchanged. The only edits in moved code are the
  import statements and the qualification that a reference across modules needs
  (ADR-0043 §1), plus two location anchors, which the slice that moves them
  corrects so that each keeps its meaning: `OPERATIONS_GD` in `runner` is
  `Path(__file__).parent / "ops" / "operations.gd"` and must still name
  `gda/ops/operations.gd` from `core/engine/sentinel.py` (#1091);
  `_imported_package_path` in `provenance` returns `dirname(__file__)` and must
  still return the `gda` package directory from `surface/provenance.py` (#1095).
  Each is one expression. The payload-entry check in `tests/support.py` pins the
  first; `test_package_path_names_the_module_that_actually_ran` pins the second
  and re-points its expected parent.
- Every class and function keeps its name. Pydantic names a `$defs` entry after the
  class, not the module, so `gda schema` does not change; the help and the skill
  carry no module path. The harness of §5 checks all three on every slice.
- A defect found during a move is its own issue, fixed before or after the move,
  never inside it.
- Living documents change in the slice that moves the module they name: CONTEXT.md
  (`gda.completed_run` under `Raw run`, `src/gda/hints.py` under `Near-miss
  hint`), `docs/command-catalog.md` (`src/gda/project.py`,
  `gda.import_evidence.classify_created_file`, `gda.live_numbers` three times,
  `gda.models.RelayedLiveParams`), and docstrings, comments and the two
  misconfiguration messages in `headless` that name a moved module by its dotted
  path. The README's repository-layout block and its three translations change
  once, in the last slice, to the package tree, and the translations are
  re-stamped with `scripts/update_readme_i18n.py`. Between slices the block is
  stale on the integration branch only.
- Schema-bearing text names no Python-internal reference. A model docstring or a
  `Field` description is a `description` in `gda schema`, written for the agent
  that reads it, so it names no module, function, constant, private symbol or
  Sphinx role; a class name is a `$defs` key and may stay. At `6d5da3df3` 36 of
  the 929 distinct descriptions carried such references, nine dotted module names
  among them (`gda.errors.classify_run` in the `ErrorCategory` docstring, repeated
  under every command). #1098 moves the cross-references a Python reader needs into
  `#` comments beside the models, which no schema reads, and lands on `main` before
  #1090 with one test on the aggregate schema that keeps the rule. A relocation
  slice then meets no stale pointer behind the byte gate of §5, and the public
  descriptions no longer follow the package layout.
- Accepted ADRs keep the dotted names of their date: `gda.runner.OPERATIONS_GD` in
  ADR-0043 §6, `gda.headless.forward_child_stderr` in ADR-0002's notes,
  `gda.models` in ADR-0040's. They are records, not references, and ADR-0043 §5
  made the same choice for `operations.gd`. Only ADR-0040 and ADR-0002 get a dated
  Outcome note, from the PR that adds this ADR.

### 5. Order of the work and the harness

One package per slice, bottom-up, each a PR on the integration branch
`refactor/gda-layering-dev`, in the order of §1: `core.project` (#1090, which
also creates `gda.core`), `core.engine` (#1091), `core.contract` (#1092),
`core.failure` (#1093), `daemon` and `core.steps` (#1094), `surface` (#1095). The
first slice changes this ADR's status to `accepted`. Bottom-up means that a slice
re-points every importer of the modules it moves, whether that importer has moved
already or not; no slice waits on a later one. Before the first slice, #1098 (§4)
lands on `main`, so the schema the gate compares against names no module.

Each PR is green on:

- ruff and pyright. Pyright resolves every import statically, so an import
  statement that still spells a moved name by its old path is an error before any
  test runs. A patch-target string escapes that check; the fast suite covers it,
  because `monkeypatch.setattr` on a string that names nothing raises.
- The fast suite (`-m "not e2e"`).
- `gda schema`, `gda skill` and every `--help`, byte-identical to the base,
  engine-less (`TERM=dumb COLUMNS=200 NO_COLOR=1`). The last slice also checks the
  `gda-mcp` tool list.
- `git diff --color-moved`: every moved body shows as moved, and the reviewer reads
  only the lines that did not.
- The e2e tests of the package's consumers on a real engine, run serially (the
  tiers each issue names).

`surface`'s consumers are every command group, so #1095's e2e set is the full
suite. The wave-tip run before promotion to `main` is at the final head of the
branch, after #1096, which follows the relocation (§8).

### 6. The import-direction test

ADR-0040's #687 note deferred a repo-wide import-boundary gate until "the narrow pin
is insufficient". The pin is narrow by construction, and the order this ADR makes
physical would otherwise be guarded by review alone. This ADR takes the gate:

- One unit test reads every import statement under `src/gda` with `ast`. For the
  `gda.*` imports it assigns each module the rank of its package in the order of §1
  (`exit_codes`, `cli` and `__main__` ranked as the root modules §1 places them;
  `harness`, `mcp`, `ops` and `skill` at the ranks §1 gives them), and fails on an
  edge from a lower rank to a higher one. Edges inside a package are not its
  concern: the split files are few, and §2 lists their edges.
- The same test asserts the three properties of `gda.core` and its layout: no
  module under it imports a `gda.*` module outside `gda.core` other than
  `gda.exit_codes`; no module under it imports `typer`, `click` or `rich`; no
  `__main__.py` sits anywhere under `gda/core/`; and no `.py` file other than the
  empty `__init__.py` sits directly under `gda/core/`. The entry points in
  `pyproject.toml` are #1095's "does not change" criterion, not this test's.
- It lands with the last slice (#1095), when every package exists. A mutant that
  adds one upward edge, for example an import of `gda.surface.dispatch` from
  `gda.core.engine.launch`, is RED; so is a mutant that imports `typer` in
  `gda.core.contract.render`, one that adds `gda/core/engine/__main__.py`, and
  one that adds `gda/core/util.py`.
- The two tests in `tests/cli/test_render.py` that pin the `render` direction by
  file (`test_the_core_never_imports_the_presentation_module`,
  `test_the_failure_channel_takes_only_the_renderer_no_group_can_supply`) keep
  their assertions and re-point: the module name in the `contract` slice, and the
  one core file that may import `render` (`descriptor`) in the `surface` slice.
  They stay, because they state what the rank test does not: `surface` may import
  `render`, but only `descriptor` may, and only for `render_failure`.

### 7. Out of scope, recorded

- **Constructors into group modules.** ADR-0040 point 4's rule stands: the taxonomy
  reads from one file, single-consumer constructors included. Only the file name
  changes.
- **A shared path normalizer.** PR #987 split the normalizers on purpose, and the
  split stands.
- **A "launch prefix" step** over resolve → launch → classify. The shared part is
  three calls; each channel's bulk is its own policy (the completion marker, the
  strict gate, the artifact resolution). A step with three callers and three
  policies would have an interface as wide as its body.
- **The launch seam spellings.** Tests patch `dispatch.make_runner`, the `launch`
  name bound in the module under test, or the `make_launch` parameter of the
  export runner. Unifying them is not a move; they do not change.
- **The cache-directory name** that `main_scene` derives beside `import_evidence`'s
  constant (#1077).
- **The `tests/` layout** (#836).
- **The GDScript payload** (`ops/`, ADR-0043) and the cross-language operation-name
  contract it left open.

### 8. Principles as rules

- **No platformization.** No package registry, no plugin discovery, no dependency
  container, no import hook, no shim for an old path. A package is a directory with
  an empty `__init__.py`.
- **DRY.** Each definition has one name and one file (§3). The map in §2 is the one
  place that says where a definition lives, until the tree itself does.
- **Orthogonality.** A package depends on the packages below it only (§3), the
  library knows no component and no framework (§1), and the test of §6 says so on
  every run. Inside a package the split files form no cycle (§2).
- **Deep modules.** The move adds no interface. It puts each concept's current
  interface in a file of its own, where it can be judged. The one deepening of the
  milestone (#1096, the completed-run step) is a separate slice on its own tests,
  after the relocation.
- **Single responsibility.** Each file has one reason to change: one concept. That
  is why `catalog` and `classify` are two files although one imports the other, and
  why `bindings` is its own 100-line file: the manifest reads it without the option
  factories.

## Considered options

- **Keep the flat list and add only the test of §6.** Rejected: the test guards the
  order but does not show it, and the navigation cost in the context stays.
- **Two packages, a flat `core/` of 23 modules beside `surface/`.** Rejected:
  `core/` would hold the same flat list, with the same five concept-mixing files.
- **The five library packages directly at the root, beside the components** (the
  first draft of this ADR). Rejected: the root then mixes five library layers with
  five components, and a reader needs the order to tell `contract/` from
  `daemon/`. The `core` package names the library, and gives the test of §6 three
  properties to assert that the flat root could not state.
- **`surface` under `core`.** Rejected: `surface` is where `typer`, `click` and
  `rich` enter (today `dispatch`, `headless`, `hints`, `surface`), and a core with
  the CLI framework in it has no boundary a test can state beyond "below
  `commands`".
- **`daemon` under `core`.** Rejected: it is a component with a process entry of
  its own (`python -m gda.daemon`, `daemon/__main__.py`) and a name in CONTEXT.md,
  like `mcp` and `harness`, which stay at the root. In place it keeps its spawn
  string, the test patch strings that name `gda.daemon.*`, and the names ADR-0002
  and ADR-0022 record.
- **One package per tier (nine).** Rejected: a tier is a measurement. A new import
  would move a file between tiers, and `tier3/` names nothing a reader looks for.
- **Packages with a façade `__init__`** (`from gda.core.failure import Failure`).
  Rejected: ADR-0040 rejected a façade; a façade gives one symbol two names and
  hides which file owns it; and an import of the façade makes the package's
  internal edges invisible to the test of §6.
- **Shims for the old module paths** (`gda/runner.py` re-exporting
  `gda.core.engine.launch`). Rejected: import paths are not a public ABI
  (ADR-0011), the only importers are in this repository, and a shim is a façade
  with a deprecation.
- **Move `exit_codes` into `core`.** Rejected: it is the public exit-status ABI the
  READMEs link at the root, the daemon protocol reads it from outside the library,
  and a module directly under `core/` would break "core holds packages only". The
  root is where the two public faces sit.
- **Keep `forward_child_stderr` in the descriptor and let `steps` import
  `surface`.** Rejected: it is the one edge that points up, and the function needs
  nothing of the descriptor.
- **Move `display` and `live_runner` into `engine`.** Rejected: `display` decides
  whether a windowed session can start, and only the daemon asks; `live_runner`
  speaks the daemon's protocol. Both are daemon concerns in files at the root.
- **Split `errors` by command group** (an export file, a script file). Rejected by
  ADR-0040 point 4; a group's constructor file would be a second group module.
- **Keep `SubprocessGodotRunner` beside `launch`.** Rejected: the launch primitive
  would still name the payload path, which four of its five channels never pass.
- **Do the whole move in one PR.** Rejected: six packages touch 176 import lines in
  `src` and 178 in `tests`, and one diff cannot show six relocations as moved code.

## Consequences

- The largest file is `catalog` at about 1250 lines, down from 1659. Four of the
  five concept-mixing files are gone, and `catalog` holds one concept.
- The order of §1 is the directory tree, and the test of §6 fails a PR that breaks
  it. The #687 note's deferral is closed. `gda.core` is closed, framework-free and
  process-free, and the same test says so.
- The root lists the product's parts: the two public faces, the library, and the
  components and layers CONTEXT.md names (`daemon`, `harness`, `surface`,
  `commands`, `mcp`, `ops`, `skill`).
- An import path under the library has four segments
  (`gda.core.failure.catalog`). The move edits every import line anyway, so the
  extra segment adds no churn; a reader types one more word.
- 176 import lines in `src` and 178 in `tests` change, plus the patch-target strings
  (`gda.import_pass.launch` 42 times, `gda.dispatch.make_runner` 24, the display,
  runner and client probes). Pyright catches the first set; the fast suite the
  second. The strings that name `gda.daemon.*` and the daemon's spawn string do
  not change.
- Every open branch that edits `src/gda` needs a rebase onto the slice that moved
  its file. At this date one draft PR (#933) edits three core files (`cli.py` and
  two command modules), none of which moves.
- `git log --follow` keeps the history of a module that moves whole. For a split
  module, `git log -C` and `git blame -C` find a definition's history, and
  `--color-moved` shows the split in the PR.
- Accepted ADRs name modules by their old dotted paths. A reader of ADR-0043 §6 or
  of ADR-0002's #803 notes maps `gda.runner` and `gda.headless` through §2.
- The risk of a relocation is a wrong name on a path the fast suite does not reach,
  or one of the two location anchors of §4 read from its new depth. The mitigations
  are pyright, the two tests that pin the anchors, the consumer e2e per slice, and
  the full suite at the tip.
- The README's layout block is stale on the integration branch between the first
  slice and the last.
- Until #1095 lands, the order is guarded by review and by the two `render` tests
  only, as today.

## Not decided here

- The completed-run step (#1096): one entry on `gda.core.steps.completed_run` that
  settles `script run` and `export smoke` after the launch classification. It is a
  deepening, judged on its own tests, after the relocation.
- Whether `gda.mcp.project_context` should read `gda.core.project.paths` instead
  of keeping its own resolver. ADR-0011 keeps gda-mcp on the public ABI; nothing
  here changes that.
- Whether the modules inside `daemon/` split further.
- The cache-directory derivation (#1077).

## Relation to other ADRs

- **ADR-0040:** this ADR takes up the core that ADR-0040 left flat. Its target tree
  and point 4's "do not move" list are superseded by §2; point 4's constructor rule
  continues as `gda.core.failure.catalog`; point 5's chain is now the tree and a
  test; its #979, #985 and #1079 notes get the `core.steps` and `core.project`
  packages as the place their rule lacked. Points 1 to 3 and the group-to-group
  edges do not change.
- **ADR-0043:** the shape of the relocation (§4) is ADR-0043 §1's, and the payload
  it split does not change. Its §6 names `gda.runner.OPERATIONS_GD`; the constant is
  `gda.core.engine.sentinel.OPERATIONS_GD` after #1091.
- **ADR-0002:** the sentinel wire's two halves, `sentinel_args` and `parser`,
  become one file, `gda.core.engine.sentinel`; the #803 producer half moves to
  `gda.core.failure.child_stderr`. The rule, its producers and the classification
  rules do not change.
- **ADR-0004:** the contract's models move; no field, name or `$defs` key changes,
  and the harness of §5 proves it per slice.
- **ADR-0006:** the path authority is `gda.core.project.paths`.
- **ADR-0011:** import paths are not the public ABI, which is why no shim exists.
- **ADR-0017, ADR-0021:** the daemon package gains the client and the display
  probe and stays at the root; the protocol does not change.
- **ADR-0012, ADR-0023:** the `Command descriptor` and the manifest walk move; what
  they project does not.
- **ADR-0027:** `skill_targets` moves into `surface` and stays the one module that
  names skill targets.
