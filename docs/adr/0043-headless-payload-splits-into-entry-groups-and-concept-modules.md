---
status: proposed
---

# The headless operations payload splits into an entry, command-group files, and concept modules

Every [headless operation](../../CONTEXT.md) runs one GDScript payload:
`godot --headless [--path <project>] --script <abs>/ops/operations.gd -- <operation>
[params_json]` (ADR-0001, ADR-0002). The payload is one file. On `main` at
`778a5b2ba` it had 7613 lines: 53 `match` arms that call 47 operation functions,
204 helpers, and about 400 lines of frame code, constants and member state.

| Role in the file | Lines |
|---|---|
| Operation bodies | 2450 |
| Helpers that one command group uses | 2325 |
| Helpers that two or more command groups use | 2430 |
| Frame, constants and state | 408 |

548 lines of the shared helpers exist a second time in `harness/gda_harness.gd`. A
drift test keeps the two copies byte-identical (ADR-0018, #220 Outcome).

Three earlier records left the file in this shape. The premises of the first two no
longer hold, and the third left the question open:

- An architecture review on 2026-06-17 deferred a split. It said that the leverage was
  spent because the Phase-1 fan-out was complete. Its trigger was a new wave of
  headless operations or about 15 live operations. Since then the file grew from 3733
  to 7613 lines, while the operations grew only from 44 to 53: the growth is the
  hardening of existing operations. The harness now serves 17 live operations.
- ADR-0018's #220 Outcome duplicated the Value projection helpers into the harness,
  because "no single `preload()` reaches both runtime contexts, and the harness
  installer copies exactly one file". Probe 1 below disproves the first half. The
  second half is an installer choice.
- ADR-0023 §3 and ADR-0040 left "the GDScript dispatch in `operations.gd`" and "the
  byte-identical harness mirror" to their own future decision.

The single file has three costs. Every headless slice edits it, so parallel slices
collide on it. An agent that changes one operation pages through thousands of lines
of unrelated code. And a concept that several operations share has no file of its
own, so nothing shows its interface: the reference graph exposes 10 of its 17
functions to the rest of the file, and the scene store's snapshot is filled by one
private function and read by another.

Probes on 2026-09-25 and 2026-09-26 used Godot 4.6.3 on macOS. Each ran both
projectless and with `--path`:

1. An absolute-path `--script` payload loads other files by a relative `preload()`
   and by a relative `extends "…"`, also with `..` segments from a subdirectory.
2. A script that extends the op base reads the base's constants without
   qualification, and reaches the frame's `_fail` and `_succeed` through a stored
   reference.
3. The engine checks two kinds of call at load time: a static function called through
   a preload constant, and a function inherited from the op base. A wrong name is a
   parse error that fails every operation. A call through an instance reference is
   checked only when it runs, also when the member has a script type.
4. A `static var` in a preloaded module is initialized once per process.
5. A `Callable` does not keep its `RefCounted` target alive. When no member held the
   group instance, the pending tick of a multi-frame operation was invalid, the run
   emitted no result, and the process exited 1.
6. The probe project declared a global `class_name` with the same name as a payload
   preload constant (`Value`). It also set
   `debug/gdscript/warnings/shadowed_global_identifier` to error. The payload then
   failed to compile, so every operation failed. With the default setting, the
   engine reported nothing.
7. A preload cycle between two static modules loads.

Headless support starts at Godot 4.4. The probes ran on 4.6.3 only. The engine code
that resolves a relative `preload()` and `extends` path against the script's own
directory (`modules/gdscript/gdscript_analyzer.cpp`) is the same in the `4.4-stable`
and `4.5-stable` sources. No 4.4 or 4.5 binary was run.

## Decision

### 1. Two steps, then an evaluation

1. #1015 splits the payload. It is a relocation: operation bodies and helpers move
   with no change to their logic. The only edits in a moved body are the
   qualifications that a call or a constant in another file needs.
2. #1016, which #1015 blocks, makes the harness preload the Value projection module
   that #1015 extracts, and deletes the mirror.
3. The deepenings that the 2026-09-25 focused review found are evaluated after both
   steps land, each on its own record (see "Not decided here").

The relocation and the deepenings are kept apart so that each diff proves one thing.
A relocation diff shows moved code (`git diff --color-moved`). A deepening diff shows
a changed interface. When one diff does both, a behaviour change hides in the moved
lines.

### 2. Module map

```text
src/gda/ops/
  operations.gd   entry: lifecycle, params, dispatch, emission, pending tail, `info`
  op_base.gd      op seam, project guard, operation-source error codes
  groups/         one file per command group (mirrors src/gda/commands/, ADR-0040)
  lib/            concept modules
```

| Tier | Module | Owns | Kind | ≈ lines |
|---|---|---|---|---|
| entry | `operations.gd` | Process lifecycle, the parameter parse, the operation `match`, result emission, the pending-frame tail, and `info` | frame | 180 |
| seam | `op_base.gd` | Forwards to the frame, the project guard, and the operation-source error codes (§5) | instance base | 20 |
| group | `project` | 12 operations and their one-group helpers | instance | 860 |
| group | `node` | 9 operations | instance | 860 |
| group | `script` | 7 operations | instance | 560 |
| group | `scene` | 7 operations, including the `scene validate` body and the preflight state | instance | 515 |
| group | `resource` | 5 operations | instance | 350 |
| group | `shader` | 3 operations | instance | 255 |
| group | `export` | 2 operations | instance | 205 |
| group | `theme` | 1 operation | instance | 40 |
| concept | `scene_store` | Load for mutation and its snapshot, node addressing, the staleness token, the atomic save, and the preload-dependency gate that runs before a save | instance | 770 |
| concept | `scene_validate` | Composed static validation of a scene and the sub-scenes it references (#664, #721) | static | 710 |
| concept | `value` | The [Value projection](../../CONTEXT.md): `--value` coercion to a declared type, the JSON projection, and write fidelity | static | 560 |
| concept | `reference_graph` | Reference edges between project files | static | 345 |
| concept | `scene_text` | The text reader for `.tscn` and `.tres` headers and `ext_resource` entries, including the resolution of the paths they carry | static | 335 |
| concept | `project_walk` | The engine-side `res://` walk (ADR-0032) | static | 265 |
| concept | `gdscript_scan` | GDScript source scan: tokens, string and comment skipping, `class_name` metadata, and executable preload paths | static | 190 |
| concept | `class_index` | The `class_name` → script index and its resolver (ADR-0032) | static, with a per-process cache | 180 |
| concept | `object_ref` | Assignment of an Object-typed value by `res://` path (ADR-0033) | instance | 85 |
| concept | `text_edit` | Search-and-replace and line-range edits for `script set` and `shader set` | instance | 80 |

The line counts are function lines measured at `778a5b2ba`. Comments between
functions and the moved constants add to them. The map is the target. If the move
shows a better place for a helper, the implementing PR changes this table in the
same PR. The dependency rules in §3 do not change that way.

A group file holds the bodies of its operations and the helpers that only that group
uses. A concept module holds the helpers of one concept, whether one group uses it or
several. A helper goes where its knowledge belongs, not where its callers are. Scene
validation serves one operation, but it is its own concept (#664, #721) and has about
710 lines, so it is a concept module. The `scene validate` operation body stays in
the scene group.

`info` stays in the entry. It is the only headless operation of the `meta` command
group and has 5 lines, so a group file for it would only pass the call through.

### 3. Dependency rules

- The entry depends on the op base and on the group files. It holds no operation body
  other than `info`.
- A group file depends on the op base and on concept modules. It never depends on
  another group file.
- A concept module depends on other concept modules and on the op base only. It never
  depends on a group file or on the entry.
- Concept modules form no cycle.

Three helper cycles exist today. The placement resolves them; no layer is added:

- The two helpers that resolve and canonicalize a resource path
  (`_resolve_ref_path`, `_canonical_resource_path`) and `_ext_resource_ids_in_line`
  go to the scene text reader. This removes the cycle between the scene text reader
  and the reference graph, the edge from the scene text reader to scene validation,
  and the edge from the GDScript source scan to the reference graph.
- The three preload-dependency gates (`_validate_script_preload_dependencies` and
  its scene and node variants) go to the scene store. The scene store runs them
  before a save and owns the state they read. The GDScript source scan then has no
  failure path and no state.

The resulting order, leaves first:

```text
value, project_walk, scene_text
gdscript_scan     -> scene_text
class_index       -> gdscript_scan, project_walk
reference_graph   -> gdscript_scan, scene_text
scene_validate    -> gdscript_scan, scene_text
scene_store       -> gdscript_scan, scene_text, value
object_ref        -> value
text_edit         -> value
```

Probe 7 shows that the engine loads a cycle, so the last rule is a design rule, not an
engine limit. An acyclic set can be read, tested and changed from the leaves up.

A unit test reads the `preload` and `extends` targets of every payload file and fails
when a rule is broken.

### 4. The op seam, module kinds, and state

The payload calls `_fail` on 196 lines, and `_succeed` and `_diag` on many more. To
keep the moved bodies unchanged, every group file extends one op base. The shape below
follows the probe. It is not final code:

```gdscript
extends RefCounted
# the operation-source error codes (§5)
var _frame
func _init(frame) -> void:
	_frame = frame
func _fail(code: String, message: String) -> void:
	_frame._fail(code, message)
func _succeed(payload: Dictionary) -> void:
	_frame._succeed(payload)
func _diag(message: String) -> void:
	_frame._diag(message)
func _begin_pending(tick: Callable, frames: int) -> void:
	_frame._begin_pending(tick, frames)
func _has_project() -> bool:
	return DirAccess.dir_exists_absolute("res://") and FileAccess.file_exists("res://project.godot")
```

The op base's interface is four forwards and the project guard. Emission stays in the
entry: its `_succeed` and `_fail` print the sentinel and set the exit code. Thus one
place writes the result to stdout, and the single `quit()` stays in `_process`, as
before (#31).

There are two kinds of module:

- **Instance modules** extend the op base. They are every group file and each concept
  module that reports failure: the scene store, the object reference, and the text
  edit. They get the frame reference when they are constructed.
- **Static modules** hold only `static func`s, and callers reach them through a
  preload constant. They are the Value projection, the project walk, the scene text
  reader, the GDScript source scan, the reference graph, scene validation, and the
  `class_name` index. A static module reports no failure. It returns a value, and its
  caller decides.

A new concept module is static when its concept allows it. Its calls are checked at
load time (probe 3), and it has no lifetime to manage.

State and lifetime:

- The entry keeps the exit code and the pending-frame tail.
- Per-run state moves into the module that owns it: the snapshot and the staleness
  token go into the scene store, and the preflight state goes into the scene group.
- The `class_name` index keeps its lazy index in a `static var`. One process runs one
  operation, so a per-process cache is a per-run cache (probe 4).
- The entry creates the group instance for the requested operation and holds it in a
  member until the process quits. A group creates the concept instances it uses and
  holds them in the same way. Probe 5 is the reason: a pending tick on a group that
  nothing holds is lost with no diagnostic.

### 5. Constants and names

- The operation-source error codes (`OP_ERROR_*`) are the failure vocabulary of the
  op seam. The entry, the groups and the instance concept modules use them, so the op
  base declares them once. Instance modules inherit them without qualification. The
  entry qualifies the three codes it uses.
- Every other constant goes to the module whose concept owns it. A constant with one
  user moves with that user: the `JOY_*` name tables go to the project group,
  `SCENE_PROBLEM_*` goes to scene validation, `SCENE_STARTUP_*` and
  `PREFLIGHT_READY_EVIDENCE` go to the scene group, `VALIDATE_MARKER` goes to the
  script group, and the walk markers go to the project walk. `DIAG_PREFIX` and the
  result sentinels stay in the entry, with `_diag` and the emission. Today one
  constant has users in two modules: `ENGINE_CACHE_DIR` goes to the project walk, and
  the `class_name` index qualifies it.
- No constant is declared again under a second name to re-export it.
- A preload constant uses the payload's constant style, UPPER_SNAKE_CASE, for example
  `const VALUE := preload("../lib/value.gd")`. No payload file declares a
  `class_name`. When an operation runs with `--path`, the payload compiles inside the
  user's project, and a project's class names are PascalCase by the GDScript style
  guide. Probe 6 shows that a name clash fails every operation in a project that
  treats the shadowing warning as an error.

ADR-0002 says that "`operations.gd` declares exactly the `operation`-source rows".
After the split, the op base declares them. #1015 adds a dated Outcome note to
ADR-0002 in the PR that moves them. In all other documents (ADRs, CONTEXT.md,
comments, and READMEs), "`operations.gd`" continues to name the headless payload as a
whole. Thus the split needs no documentation sweep.

### 6. Invocation, packaging, and contract tests

- The entry keeps its path. `gda.runner.OPERATIONS_GD` and every launch stay the same.
  Relative preloads resolve from the directory of the file that contains them.
- The payload files ship in the wheel with the rest of `src/gda`, because the
  `uv_build` backend includes the package tree. #1015 verifies this on a built wheel.
- Tests that read the payload as text get the sources from one shared test helper.
  The operation-code mirror test reads the op base. The guard against literal error
  codes reads every payload file: a guard that read only the entry would pass on code
  that moved away from it. Each of these parses fails when it finds no match.
- The #164 regression loads the payload inside a project. It copies the payload
  directory instead of one file.

### 7. One Value projection module for both payloads (#1016)

This step reopens ADR-0018's #220 Outcome.

- The headless payload and the harness preload the same module. The installer copies
  it beside the harness into `res://addons/gda_harness/`, and the harness preloads it
  by a sibling relative path.
- The harness copy of the block and the mirror drift test are deleted. `_json` and
  the Control-position write policy, which are mirrored today, move into the module.
- A near-twin outside the mirrored block (the storage-property loop and the Control
  position write) joins the module only where both copies are identical. A
  difference is recorded on #1016 and left as it is. A merge of two different copies
  changes what one channel does, and that is a separate decision.
- The module declares no `class_name` and preloads nothing, because the installer
  copies it alone into the user's project.
- `harness_artifacts()` stays the only list of the files that the install owns
  (#654). Every consumer reads that list: install, uninstall, the created-paths
  receipt, and `HarnessSnapshot` for the export strip (ADR-0028) and the failed-start
  restore. The installed-versus-bundled drift check, the version header and the
  version guard also cover the module. A change to the module bumps
  `HARNESS_VERSION`.

While #1015 is open, the harness does not change. The mirror drift test reads the new
module and ignores the `static` keyword that the module adds.

### 8. Principles as rules

The split adds the abstraction that the move needs, and nothing more. Each principle
maps to rules above:

- **No platformization.** The split adds no operation registry or router table (the
  `match` stays), no load by name, no dependency container, no plugin discovery, no
  code generation, no base-class hierarchy beyond the one op base, and no GDScript
  unit framework. No module is made for a hypothetical second adapter.
- **DRY.** Each constant has one declaration (§5). After #1016 the Value projection
  has one copy. One test helper reads the payload sources.
- **Orthogonality.** Groups do not depend on each other. Concept modules do not depend
  on groups or on the entry, and they form no cycle (§3). A change to one command
  group edits its group file and, at most, its arms in the entry.
- **Deep modules.** #1015 does not add an interface to hide complexity. It puts each
  concept's current interface in a file of its own, where it can be seen and judged.
  Making a module deeper is a separate decision ("Not decided here"). No catch-all
  file (`util`, `common`, `helpers`) is allowed: a helper goes to the concept it
  serves, or stays with its only user.
- **SOLID.** Single responsibility: each file has one reason to change, which is the
  behaviour of one command group or one concept. Open/closed: a new operation adds
  one `match` arm and one function in its group file, as today. Interface
  segregation: the op base exposes four forwards and the project guard. Liskov
  substitution and dependency inversion have no seam here: there is one frame and one
  implementation of each module, and the split does not invent a second one.

## Considered options

- **Keep one file.** Rejected. The three costs in the context grow with every
  hardening slice, and the premises of the 2026-06-17 deferral and the #220 Outcome
  no longer hold.
- **Concept modules only, with the operation bodies left in the entry.** This was the
  first recommendation of the 2026-09-25 review. Rejected: the operation bodies and
  the one-group helpers are about 4800 lines, and they would keep the entry as the
  point where slices collide.
- **Group files only, with the shared helpers left in the entry.** Rejected: every
  group would depend on the entry, and 2430 lines of shared helpers would stay in one
  file with no concept boundaries.
- **Reach the frame through `Engine.get_main_loop()`.** Rejected: it is a hidden global
  dependency that every module could use. The stored frame reference is explicit, and
  only instance modules have it.
- **Change every failure path to return a value.** Rejected for #1015: it rewrites
  196 lines and the six failure conventions in the same diff as the move. It is a
  deepening ("Not decided here").
- **A separate error-code file, re-exported through the op base.** Rejected: one
  constant with two names.
- **An operation registry keyed by name, with files loaded on demand.** Rejected as
  platformization. The 53-arm `match` has two lines per operation, and it is not the
  friction.

## Consequences

- The largest file has about 860 lines, down from 7613.
- A headless slice edits its group file and its `match` arms. Slices in different
  groups collide only on the arms.
- Each concept's interface is visible, so each later deepening can be judged on one
  module.
- After #1016 the Value projection has one copy, and the two unguarded near-twins are
  visible on the record.
- GDScript has no unit tier here, so each move step needs the full e2e suite on a real
  engine.
- A call through an instance reference is checked only when it runs (probe 3). A wrong
  qualification on a path that the e2e suite does not reach fails only on that path.
  The mitigations are the moved-code diff, which shows every line that did not only
  move, and a preference for static modules.
- A missed hold of an instance fails with no diagnostic (probe 5). The preflight e2e
  covers the one multi-frame operation.
- A project that treats the shadowing warning as an error constrains every name in the
  payload, not only the new constants (probe 6). The naming rule in §5 keeps the new
  names in the payload's existing style.
- Relative `preload()` and `extends` were run on Godot 4.6.3 only. The 4.4 and 4.5
  evidence is the engine source.
- After #1016 the harness install copies two files, and the installer's one-file
  assumptions change with it.

## Not decided here

These candidates from the 2026-09-25 focused review are evaluated after #1015 and
#1016 land, each on its own record:

- one guarded file edit: open or create, the staleness token, and the atomic write;
- one scene edit session that owns the loaded root;
- one declared-type property write for `node set`, `resource set` and `project set`,
  and whether `game set` joins it;
- one file classification behind the reference graph;
- a typed problem record for scene validation;
- one failure convention across modules, instead of six;
- a unit guard that pairs each descriptor's `operation` with a `match` arm. This is
  the cross-language operation-name contract that ADR-0023 left open.

## Relation to other ADRs

- **ADR-0018, #220 Outcome:** probe 1 disproves its first premise. #1016 removes the
  duplication that it accepted.
- **ADR-0023 §3 and ADR-0040:** this ADR decides the structure of the GDScript payload
  that both left open. The operation-name contract stays open.
- **ADR-0002:** the op base declares the operation-source rows after #1015, which adds
  the Outcome note.
- **ADR-0032 and ADR-0033:** the project walk, the `class_name` index and the
  object-reference assignment move with no change to their contracts.
