# gda command catalog

A **non-binding roadmap** of the `gda` command surface (ADR-0005). This is a *feature
map, not a task tracker*: it shows the territory each command group covers so we can
prioritise and so agents can see the shape of the whole. **What is committed, in flight,
or done lives in the issue tracker** — for the headless increment, the **Phase 1 —
headless operations** milestone. Commands are delivered one vertical slice at a time
(ADR-0000); this file is refined as we go.

Seeded from the `godot-mcp-pro` taxonomy (the reference whose grouping ADR-0005
adopts), re-expressed in `gda`'s grouped command form (`gda <group> <command>`) and
verb vocabulary (`create`/`delete`, `add`/`remove`, `get`/`list`, `set`, domain verbs).

## How phase is assigned here

`godot-mcp-pro` runs inside a live editor, so it marks many operations "editor" even
when they only touch a scene/resource *file*. `gda` classifies by CONTEXT.md instead:

- **Phase 1 (headless)** — fulfillable by a one-shot `godot --headless` process that
  loads a file from disk, mutates it, and saves it (or just reads it). No pre-existing
  engine state required. **This is the near-term increment.**
- **Phase 2 (live)** — requires an already-running engine to observe or control its
  runtime state (runtime scene tree, runtime properties, input simulation, viewport
  capture, performance/signal monitoring). Served by `gda-daemon` against a **running
  game**, not an attached editor; the editor context is out of scope (ADR-0017). Live
  commands are placed by their real domain object, not in a single "live" group
  (ADR-0019). **Mechanism decided (ADR-0017–0021); catalogue delivered incrementally.**

This catalog does **not** carry a per-command status column — that would duplicate, and
drift from, the issue tracker. For the **headless** backlog open the **Phase 1 —
headless operations** milestone; for the **live** backlog open the **Phase 2 — live
operations** milestone. Inline references to issues
in the prose below (e.g. "established by #53") cite the slice that defined a behavior;
they are provenance, not status markers.

---

## Meta commands (top-level, ungrouped — ADR-0005)

| Command | Description | Phase |
| --- | --- | --- |
| `gda info` | Report Godot engine version info | 1 |
| `gda version` | Report `gda`'s own version | — (local) |
| `gda help` | Usage help | — (local) |
| `gda schema` | Emit the whole command surface as one JSON manifest (ADR-0012) | — (local) |
| `gda skill` | Emit or install the bundled Agent Skill (ADR-0024) | — (local) |
| `gda <command> --schema` | Emit a command's input/output JSON Schema (ADR-0004) | — (local) |

> `--schema` is a per-command flag, not a command, and ships with **every** domain
> command as a hard gate (ADR-0004). It is local introspection — no Godot process.
> Alongside the schemas it emits `argv`: how each parameter is written on a command
> line (positional and its position, or its `--option` spelling, plus whether it is
> required, a valueless flag, or repeated), derived from the live command signature
> so an agent builds argv from the contract instead of from `--help`.

---

## Phase 1 — headless domain commands (near-term territory)

### `scene`

| Command | Description |
| --- | --- |
| `gda scene create` | Create a new `.tscn` with a given root node type |
| `gda scene delete` | Delete a scene file |
| `gda scene get` | Read a scene's structured tree from its file on disk |
| `gda scene list` | Enumerate scenes in the project |
| `gda scene get-exports` | List `@export` properties declared by a scene's nodes |
| `gda scene validate` | Check statically that a scene and the sub-scenes it references resolve their dependencies and compile their scripts |
| `gda scene preflight` | Boot a scene headless and report its startup verdict |

**Enumeration** (established by #54): `scene list` walks the project's `res://`
tree under the same exclusion rule `script list` states below, so the two see the
same directories and differ only in the extension they collect (#712).

**Static instance reporting** (established by #400): `scene get` reads the stored
`SceneState` without instantiating the host scene, but an instanced node is still
identifiable. Its `type` is resolved to the referenced scene's root node type
when the referenced `PackedScene` loads, and the node carries `instance_path`
plus `instance_status` (`resolved` or `missing`) so agents can distinguish an
instance from a plain typed node. `scene list` applies the same rule to an
inherited/instanced root through `root_type`, `root_instance_path`, and
`root_instance_status`. A missing referenced scene keeps the marker and reports
`missing` rather than silently appearing as only `type: ""`.

**Export reporting** (established by #58): `gda scene get-exports` loads a scene, instantiates
it, and reports — per node, keyed by the same canonical node path `node get`/`node set`
address by (`.` for the root) — the `@export` properties the node's attached script declares:
each a `{name, type, hint, hint_string, value}` entry, where `type` is the export's declared
Godot type name, `hint`/`hint_string` are the Godot `PropertyHint` enum value and its companion
string the `@export` annotation produced, and `value` is the export's current value in the same
JSON projection `node get` uses (its default on a freshly-loaded node) — the property-value
introspection is reused from `node get` (#55), not re-implemented. An export is detected by its
usage flags (`PROPERTY_USAGE_SCRIPT_VARIABLE` + `PROPERTY_USAGE_EDITOR`) on the script's own
property list, so a node's inherited engine properties and a script's plain (non-`@export`)
variables are excluded. A node with no script, or whose script declares no exports, is omitted;
a scene with no exported variables anywhere is a valid, empty listing (`nodes == []`). Like
`scene get`, get-exports reuses the shared load-failure ladder — a missing file is
`path_not_found`, a non-scene file `not_a_scene` (both exit 4). It reads but does not save, so
it skips the re-save mutation-integrity guard; instantiating still runs attached scripts'
`_init` (the trust boundary of ADR-0009).

**Two verdicts, neither replacing the other** (established by #664): `scene get` reports what a
scene DECLARES, and reporting it survives most breakage — Godot substitutes null for a NODE's
`[ext_resource]` it cannot resolve, prints an error to stderr, and still returns a usable
`PackedScene`, so a scene whose script and texture are both gone reads as a healthy tree
(dogfooding GDA-DF-040; a dependency broken from inside a `[sub_resource]` can instead fail the
whole load, measured on Godot 4.6.3). The two validating commands answer the questions that read cannot, and
they answer *different* ones:

- `gda scene validate PATH` is **static**. It loads the scene without instantiating it, so none of
  the scene's own node scripts run — no `_init`, no `_ready`, no frames (issue #30; the project's
  autoloads still start, as they do for every `--project` op, and compiling a script executes its
  static initializers). It resolves every dependency the `.tscn` declares, compiles every script
  it binds — the referenced `.gd` files and the embedded `[sub_resource type="GDScript"]`s the
  dependency walk never sees — and checks each script's native base against the node carrying it,
  reporting one problem per file: `missing_resource` (the file is gone), `unloadable_resource`
  (present on disk but no `ResourceLoader` opens it — typically an asset that was never imported,
  which a non-editor engine cannot load at all), `script_compile_failed` (the same verdict
  `script validate` gives that file; an embedded script is named by its `::id` sub-resource path)
  or `incompatible_script` (a binding the engine would refuse — a script on a node outside its
  native base, the same rule `node script attach` enforces asked statically, or a value bound to
  a `script` slot that is not a script at all). Each problem carries the declared `type` and
  the node paths referencing it, read from the file's own text because the engine drops an
  unresolvable reference from what it loads. A path declared twice — including twice under
  different spellings of one file, since every path is canonicalized the way the engine reports
  it — is one problem with every referencing node listed. The verdict is **staged**: unresolved
  dependencies suppress the load, so the compile and binding problems only the loaded scene can
  reveal appear after the dependencies are repaired and validate is rerun — the problem list is
  complete for the stage it reached, not across both stages at once. It is also **composed**, in
  the sense set out below.
- `gda scene preflight PATH` is **dynamic**. It instantiates the scene, adds it under a one-shot
  engine's tree root — which runs its `_ready` and the project's autoloads — keeps it alive for
  `--frames` idle frames so startup work landing after `_ready` still prints, and reports
  `status` (`ready` / `not_ready` / `timeout`) plus the script errors gda recognized in the
  engine's error stream. Read `started`: true only when the scene reached `_ready` AND nothing was
  recognized on stderr, which is the distinction the dogfooding note asks for (GDA-DF-030 —
  static validation passed while the first live launch rejected every assembly). Recognition is
  #651's closed set of engine failure sentences (a runtime error, a failed assertion, a script
  that could not load, a script binding the engine refused), so project prose written with
  `push_error()` is not among them.

**A composed verdict, not a single-file one** (established by #721): a scene that references a
broken one is broken too, and its own dependency walk can never see that — `res://child.tscn`
resolves and Godot hands back a usable `PackedScene` whatever is missing inside it. `scene
validate` therefore walks from the scene it was given through the scenes that one references,
validates each with the same two-stage check, and stamps every problem — the validated scene's
own included — with `scene`, the file it was found in. Read a problem's `path` and `nodes`
against that file, not against the scene the command was given: a missing script inside
`child.tscn` reports `nodes: ["."]` for the *child's* root. Each file is answered for once
however many sites reach it, so a broken scene instanced five times is one problem, not five.
Every path in the result — the validated scene's own `path` included — is the canonical
spelling, so `res://./main.tscn` and `res://main.tscn` are one file and one verdict.

**What counts as an edge is a UNION of two triggers**: the path a reference resolves to ends
in `.tscn`/`.scn`, or its `[ext_resource]` line declares `type="PackedScene"`. Neither trigger
alone is enough. Godot's text loader starts a load for every `[ext_resource]` line before it
parses a single node, and passes that line's `type` to `ResourceLoader` only as a hint — the
format handler is picked by extension and accepts every type (measured on Godot 4.6.3: a `.tscn`
referenced as ordinary `type="Resource"` metadata and never instanced emits the same errors for
its missing script as an instanced one), so the declared type can never be a *filter*. But
`ResourceSaver` will write a `PackedScene` into a plain `.res` — the binary saver accepts `res`
for any resource, while the text saver refuses, so `.tres` is not a form a PackedScene can be
saved in — and no extension test catches that, so the declared type earns its place as an extra
*trigger*.

A `.tscn` is read and composed into the verdict; anything else that loads as a `PackedScene` is
reported `unreadable_sub_scene`. What stays outside: a `PackedScene` stored under a non-scene
extension **and** declared as some other type. gda writes no such file, and it does not load
every reference to find out — that would load every texture and audio file a scene names.

**Three edges are reported instead of followed**, each with the target under `path`, the file
declaring it under `scene`, and the referencing nodes under `nodes`:

- `cyclic_instance` — the target is an ancestor in this scene's reference chain. Godot refuses
  the closing reference, drops it, and the nodes it would have contributed vanish from the
  composition it loads, so the cycle is a defect and not merely a traversal hazard. The walk
  stops at that edge; what lies beyond it is unreported until the cycle is broken.
- `unreadable_sub_scene` — the target loads as a `PackedScene`, but carries none of the
  `[gd_scene]` text the walk reads a dependency set out of: a binary `.scn`, or a `PackedScene`
  saved into a `.res`. This is the same limit that makes the command refuse such a file as its
  own target, met one level down. A target that does not load at all is *not* this kind: the
  referencing file's dependency walk already reports it as `unloadable_resource`, and one
  finding is not reported twice.
- `instance_depth_exceeded` — no route reaches the target within `16` levels of sub-scenes below
  the validated scene. The bound is on gda's own walk, whose per-file pass is superlinear in
  chain length; the engine loads the whole chain either way, and past roughly a thousand levels
  its own loader overflows and the run ends with no verdict at all, which no bound here changes.
  The bound applies to the SHORTEST route to each scene, not to the first route walked: a file
  reached again nearer the root is walked again from there, and these entries are settled only
  once every route has been walked, so they appear last. Together those two rules make the
  verdict independent of the order the `[ext_resource]` lines happen to appear in — for the
  target of a deep edge and for everything below it.

The last two are the only kinds that report a limit of *gda* rather than a defect of the
project, and both still yield `valid: false`. That is deliberate: a gate must not answer "sound"
about a subtree it never opened, so "not established" is reported as invalid and the messages
say `UNCHECKED` in as many words. Validate the named scene directly — or re-save it as `.tscn` —
for a verdict of its own.

`scene validate` takes a `.tscn` specifically, and refuses a binary `.scn` with `invalid_path`:
its dependency set comes from the scene's own TEXT (which is also what attributes each dependency
to the nodes using it), and a binary scene carries none — answering `valid: true` for a file it
could not read would be the worst thing a gate can do. `scene preflight` has no such restriction:
it boots whatever loads.

Both report an invalid/failed scene as a **successful operation** (exit `0`, verdict in the
result), including preflight's `timeout` — "the complete preflight did not finish within its
wall-clock bound" is the answer that command was asked for. A `_ready` that never returns is one
cause; a healthy, already-ready scene whose `--frames` window outruns the ceiling is another —
the params contract states the two bounds are not cross-checked. Only addressing and environment problems fail: `path_not_found`,
`invalid_path`, `not_a_scene`, preflight's `missing_dependency` for a scene the engine cannot
instantiate at all, and the shared binary/crash envelopes. One case that looks like a refusal but
is a verdict: an unresolvable `[ext_resource]` referenced from a `[sub_resource]` (an
`AtlasTexture`'s atlas, a script-backed `Resource`) makes Godot fail the WHOLE scene load, so
`scene validate` reports its own dependency finding rather than the `not_a_scene` the load alone
would suggest. Both carry `project_root`, the root the `res://`
dependencies resolved against — read it before trusting a bad verdict, since the wrong project
reports everything as missing (the #658 rule).

Neither command replaces the other, and the e2e suite pins why in both directions: a scene whose
dependencies all resolve can still fail on its first frame, and a scene referencing a
never-imported texture starts CLEAN — the engine builds the tree without it and says so in a
sentence the recognized set does not cover, so only static validation names that file and the
node holding it. (The two do overlap in between: a missing *script* produces sentences the parser
knows, so both commands flag it — validate additionally saying which node and which declared
type.) Preflight is a headless one-shot launch, not a live session —
it needs no daemon and does not drive the scene (`gda game`, behind `gda daemon start`, is what
does). It runs the project's code by construction, the widest such surface in the scene group,
inside the same trusted-project assumption (ADR-0009).

### `node`

Operates on nodes **within a scene file** (load → mutate → pack → save), so headless.

**Node-path addressing** (established by #53, tightened by #66): a node within a scene is
addressed by its node path **relative to the scene root** — `.` is the root itself,
`Player/Arm` a nested node. Addressing is strict: a path must be **canonical** — exactly `.`,
or `/`-joined node names. Non-canonical forms that Godot's own NodePath resolution would
silently accept — `..` or `.` segments (`A/..` resolves to the root, `./A` to `A`), trailing
or doubled slashes (`A/`, `A//B`), `:property` syntax (`A:position`) — are rejected with
`parent_not_found` rather than normalized, as are absolute paths (`/root/…`): the node must
land exactly where the literal path says or nowhere. `gda node list` reports every node's
path in canonical form, so a listed path can always be fed straight back into other node
commands (e.g. `node add --parent`).

**Mutation integrity boundary** (established by #64): mutating a scene instantiates it and
re-saves the re-packed tree. The round-trip preserves existing instanced sub-scenes and their
state — the `instance=` reference, `[editable ...]` markers, and node-path-keyed property
overrides on nodes inside an instance (verified on Godot 4.6.3, regression-pinned in the e2e
suite). When an instanced sub-scene cannot be resolved on load (a broken dependency, or
`res://` references without project context — pass `--project`), the engine instantiates the
scene *without* it, so a re-save would silently erase the instance and all its overrides;
likewise, a declared node class unavailable in the running engine (e.g. an absent
GDExtension) is silently substituted with a placeholder node, and a re-save would rewrite the
node under the substitute type. A GDScript attached to the scene whose `preload("res://...")`
target no longer exists is also refused before save with `missing_dependency`, naming the
missing `res://` path so the dependency can be created first. Mutating node commands detect
these cases and refuse with the registered `missing_dependency` error (exit 4), leaving the
file untouched. Related trust boundary: instantiating executes `_init`
of scripts already attached in the scene (#62) — treat headless mutation of an untrusted scene
as running its code.

Scene mutation writes also preserve existing `.tscn` `ext_resource` ids and matching
`ExtResource("...")` references after Godot's text saver re-serializes the file. Matching is by
the resource path's canonical `res://` form, so relative `path="..."` entries keep their old ids
after Godot writes them as `res://...`. Other text-saver canonicalization remains Godot-owned:
non-resource-id formatting may change, and duplicate `ext_resource` entries for the same path may
collapse to one canonical entry; when that happens, `gda` keeps the first old id for that path.

**Type resolution** (sharpened by #65): `node add --type` resolves a built-in `Node` class
first, then a `class_name` from the project's global class list (which exists only after a
project import — pass `--project`). A type that resolves to neither is refused with
`invalid_node_type`. A `class_name` that is still registered but whose script has broken since
the scan — it fails to load, no longer compiles, or its `_init` requires constructor
arguments — is a script problem, not an unknown type, and is refused with the distinct
`uninstantiable_script` error (exit 4) naming the script: repair the script (or re-import),
don't change the type name. Either way the scene file is left untouched.

**Scene instancing** (#399): `node add --instance <scene>` composes an existing scene as an
instanced child — Godot's standard composition primitive — instead of constructing a typed
node; `--type` and `--instance` are mutually exclusive (exactly one, enforced model-side so
argv and `--params-json` agree). The write produces the canonical serialization the editor
produces: an `ext_resource type="PackedScene"` entry plus an `instance=ExtResource(...)`
node stub with no `type=` attribute, the instance's internals referenced, never inlined
(pre-existing `ext_resource` ids stay byte-identical per the mutation-write rule above).
The default `--name` is the instanced scene's filename stem. The result echoes the composed
`res://` path as `instance` and reports `type` as the instanced scene's resolved root class.
Failures follow the dependency ladder: a missing scene file is `missing_dependency` naming
the path; a file not recognized as a PackedScene is `not_a_scene` (the wrong KIND of file);
a scene-typed file that fails to load, or whose declared nodes vanish/degrade on
instantiation because a nested dependency is missing (the #64 hazard, guarded for the
instanced scene too), is `missing_dependency` naming the instance path with diagnostics
carrying the nested culprit; instancing the host into itself is refused as `cyclic_target`
— all exit 4, file untouched. Instantiating the
composed scene runs the `_init` of scripts inside it: the same trust boundary as the
`class_name` path (#62).

**Sibling order authoring** (#415): `node add --index <n>` inserts the new child at a
0-based sibling index under `--parent`; omitting `--index` appends as before, and
`--index child_count` is the explicit append position. Valid `node add` indexes are
`0..child_count` before insertion. `node move --index <n>` places the moved node at its final
0-based sibling index under `--to`: for a same-parent move the range is `0..child_count-1`,
and for a different-parent move it is `0..target_child_count` before the move. Omitting
`--index` preserves existing behavior: a same-parent move is a successful no-op that leaves
the file untouched, while a cross-parent move appends under the destination. Negative or
out-of-range indexes fail with `invalid_child_index` (exit 4), leaving the file untouched.

**Property reporting and value coercion** (established by #55): `gda node get` instantiates the
scene and reports the addressed node's **storage** properties (the ones that serialize into the
`.tscn`) as typed JSON — each a `{name, type, value}` triple where `type` is the property's
declared Godot type name and `value` is its JSON projection. `gda node set` takes the property's
declared type as the coercion target and converts the CLI `--value` **string** to it; the value
the node ends up holding is reported back in the same JSON projection `node get` uses, so a `set`
round-trips through a `get`. An unknown property is `unknown_property`; a value that cannot be
coerced to the property's type is `uncoercible_value` (both exit 4, file untouched). `node get`
reads but does not save, so it skips the re-save guard; `node set` is a mutating op and honors the
mutation integrity boundary above. The supported target types and the string forms they accept:

| Godot type | Accepted CLI `--value` string | JSON projection (`get` / `set` result) |
| --- | --- | --- |
| `bool` | `true` / `false` (case-insensitive) | `true` / `false` |
| `int` | an integer literal (e.g. `7`, `-3`) | a JSON number |
| `float` | a number literal (e.g. `1.5`, `3`) | a JSON number |
| `String` | any string, verbatim | the string |
| `StringName` | any string, verbatim | the string |
| `Dictionary` | a JSON object string (e.g. `{"hp":7}`) | a JSON object |
| `Array` | a JSON array string (e.g. `["wine","key"]`) | a JSON array |
| `Vector2` | two comma-separated floats: `x,y` (e.g. `10,20`) | `[x, y]` |
| `Vector2i` | two comma-separated integers: `x,y` | `[x, y]` |
| `Color` | `#rrggbb` / `#rrggbbaa`, or 3–4 comma-separated floats in 0..1 (`r,g,b[,a]`) | `[r, g, b, a]` |

For `Dictionary` / `Array` JSON values, JSON integer literals stay Godot `int` and JSON float
literals stay `float` (for example, `{"a":2,"b":2.0}` keeps distinct `int` and `float` entries).
When the existing destination is a typed `Dictionary` or typed `Array`, assignment goes through that
typed container so Godot coerces keys, values, or elements through the declared container type
(for example, `Dictionary[String, int]` or `Array[int]`). The same JSON container rule is shared by
`node set`, `resource set`, `project set`, and live `game set`; Object `res://` assignment below is a
separate headless-only contract.

Whitespace around a value or a component is tolerated. A property of any other type is still
reported by `node get` — compound values arrive structured through the shared value projection
(ADR-0035): packed arrays project as JSON arrays, and an `Object` as a reference / texture / inline value
projection or the `str()` fallback (see [`project`](#project)) — but `node set` cannot coerce to
those remaining types yet and refuses with `uncoercible_value` unless a separate assignment contract
below applies.

**`Control.position` convenience assignment** (#464): `Control.position` is layout-derived from
offsets rather than a normal serialized storage field, but it is a common authoring target. For a
free-positioned `Control`, `gda node set --property position --value x,y` coerces `x,y` as a
`Vector2`, writes `offset_left` / `offset_top` / `offset_right` / `offset_bottom`, preserves the
current size, and echoes the resulting `position`. If the `Control` is a direct child of a
`Container`, the command refuses with `unknown_property` and names the four offset properties as the
actionable alternative; container-managed layout is not overridden. Live `gda game set` mirrors the
same policy with `live_unknown_property` for the container-managed case. `gda game rect` remains a
read-only rendered-geometry query and is not a setter.

**Object-typed property assignment by `res://` reference** (ADR-0033, #363): for an **Object-typed**
property that expects a Resource (sub)class — e.g. a `CollisionShape2D`'s `shape` (`Shape2D`) — `gda
node set` and `gda resource set` accept a **`res://….tres` resource path** as `--value`. The path is
`load()`ed, **type-checked** against the property's declared **engine** class, and assigned as an
**external reference** (`ext_resource`); the resource is **not inlined**. Combined with `resource
create` and `resource set` this completes the external sub-resource workflow with no new command
(`resource create res://box.tres --type RectangleShape2D` → `resource set … --property size --value
32,64` → `node set scene.tscn --node Col --property shape --value res://box.tres`). The result echoes
`type` `"Object"` and `value` the ADR-0035 **reference projection** (`{type, resource_path}`) of the assigned
resource — the same shape a subsequent `get` reads back (pass `--project` so `res://` resolves). This
is a **separate, headless-only** step from the shared coercion above — scalar coercion keys off the
Variant type and container coercion may use the current typed container value, but neither carries the
expected-class hint on the property-list entry — so
assigning a Resource on the live `gda game set` is **out of scope** and the coercion mirror is
unchanged for Object assignment. Its failure modes are **distinct structured codes**, never `uncoercible_value`: a non-`res://`
value is `expected_resource_path`; a path that does not load as a Resource is `not_a_resource`; a loaded
resource whose type is incompatible with the property's expected class is `resource_type_mismatch`. The
**`script` property is excluded** and routed to `script attach` (#118) — setting it returns the
actionable `use_script_attach` error, never a second script-binding entry. A property typed as a script
`class_name` (rather than an engine class) is **deferred** (its validation will reuse ADR-0032's
resolver) and refused with `unsupported_property_type`.

This coercion contract — the accepted string forms above, the declared-type target, and the
`unknown_property` / `uncoercible_value` failures — is **shared by other property-bearing
commands**, not specific to nodes. `gda resource set` (#120) applies the same #55 coercion to the
addressed `.tres` resource property's declared type and round-trips through `resource get`, exactly
as `node set` round-trips through `node get`; here `unknown_property` names a property absent on the
**resource** rather than a node. The live `gda game set` (#220) applies the same coercion table to a
**running** node's runtime property (the gda harness carries a verbatim copy of the coercion helpers,
kept in sync by a drift test). When a `game get` / `game set` property name is explicit, the harness
checks storage properties first, then attached-script variables; unfiltered `game get` keeps the
storage-property listing and does not dump plain script variables. Live set success results keep
`value` as the observed read-back value and add `verified`: `true` when that read-back equals the
coerced requested value, `false` when the set completed but the read-back differs. The harness does
not guess whether `verified:false` is a getter-only/no-op variable or a valid edge-triggered control;
callers can use a follow-up `game get` for domain-specific side effects. Its failures are the
LIVE-category `live_unknown_property` / `live_uncoercible_value` (the harness reports them in-band,
mapped by the live classifier — see
[Phase 2 — live domain commands](#phase-2--live-domain-commands-served-by-gda-daemon)).

**Structural edits** (established by #56): three commands restructure the node tree within a
scene file, each a `load → locate → restructure → pack → save` round-trip that reuses the
node-path addressing and the mutation-integrity boundary above. They share one rule for the
**scene root**: the root has no parent, so an edit that needs one is refused with the registered
`cannot_target_root` error (exit 4), leaving the file untouched, rather than emptying or
corrupting the scene.

- `gda node remove SCENE --node <node-path>` deletes a node **and its whole subtree**, echoing
  the removed node's path/name/type (captured before the re-save). A node path that resolves to
  nothing is `node_not_found`; removing the root (`--node .`) is `cannot_target_root` — delete
  the scene file instead.
- `gda node duplicate SCENE --node <node-path>` copies a node **and its whole subtree** under the
  source node's **own parent** (the copy is a sibling), assigning a **fresh, non-colliding name**:
  the source name with an incrementing integer appended, starting at `2` (`Hero` → `Hero2`, then
  `Hero3`, …), skipping any name already taken — including the engine's internal children. It
  returns the copy's new node path. Duplicating the root (`--node .`) is `cannot_target_root` —
  the root has no parent to host a sibling copy.
- `gda node move SCENE --node <node-path> --to <new-parent-path> [--index <n>]` reparents a node
  **and its whole subtree** under the target parent, returning the node's new node path. With
  `--index`, it also places the moved node at that 0-based destination sibling index; when
  `--to` is the node's existing parent, `--index` performs a same-parent reorder without
  remove+re-add churn. The target is addressed by node path like any other (`--to .` is the root).
  An invalid target (no such parent) is
  `parent_not_found`, and a target that already has a child with the moved node's name is
  `duplicate_node_name` — both the same codes `node add` reports. A **cyclic** target — the moved
  node itself or one of its **own descendants** — would detach the subtree from the scene and is
  refused with the registered `cyclic_target` code. Moving the root (`--node .`) is
  `cannot_target_root` — the root has no parent to be reparented out of. Moving a node to the
  parent it **already sits under** without `--index` is a successful **no-op** that leaves the
  file untouched. The
  reparent preserves the moved node's own **local transform** (a purely structural move, no
  transform churn) and the instance state of any instanced sub-scene it carries — its
  `instance=ExtResource(...)`, its `[editable ...]` marker, and its inherited/override children are
  not rewritten into local nodes (the #64 mutation-integrity boundary).

**Signal wiring** (established by #57): `gda node connect-signal SCENE --from <source-path> --signal
<name> --to <target-path> --method <name>` records a connection from a **source node's signal** to a
**target node's method**, persisted into the `.tscn` as a `[connection]`. `disconnect-signal` takes the
same four flags and removes an existing connection. The two node paths (`--from`, `--to`) reuse the
node group's **node-path addressing** (#53/#66): `.` is the scene root, `A/B` a descendant — exactly
the form `node list` reports. All four flags are required: a connection has no sensible default for
any of its parts. As a scene mutation, signal wiring instantiates the scene and honors the **mutation
integrity boundary** above (and its inherent trust boundary, ADR-0009).

The contract for the two endpoints' existence (#57's design decision):

- **The signal must exist on the source node.** A typo'd or absent signal is a clean
  `signal_not_found` — the agent fixes the signal name, not the wiring.
- **The target method need NOT exist.** A `.tscn` `[connection]` is persisted data, and Godot's own
  editor lets you wire a signal to a not-yet-written method (it can auto-generate the handler), so
  the handler may be authored *after* the wiring — a **dangling connection** is allowed and recorded
  as-is. (Verified on Godot 4.6.3: connecting to a missing method returns `OK` and serializes.)

Persistence mechanism: the connection is set up on the instantiated tree with Godot's
`Object.CONNECT_PERSIST` flag before the scene is re-packed — only a persisting connection is
serialized by `PackedScene.pack` into the `[connection ...]` line; a plain runtime connect is dropped.
A re-read of the saved scene shows the connection (`is_connected` is true), so `connect-signal` is
verifiable end-to-end. Connecting an already-wired signal→method is a clean `already_connected` error
(not a noisy engine failure or a silent re-apply); disconnecting a connection that does not exist is
`connection_not_found` (not a silent no-op). A node path that resolves to nothing is `node_not_found`
(the message names whether the *source* or *target* endpoint failed); a missing or non-scene file
reuses `path_not_found` / `not_a_scene`. All failures exit 4 and leave the file untouched.

| Command | Description |
| --- | --- |
| `gda node add` | Add a node (by type, `class_name` script, or `--instance` scene composition) into a scene, optionally at `--index` |
| `gda node remove` | Remove a node from a scene |
| `gda node get` | Read a node's properties (typed JSON) |
| `gda node list` | List nodes in a scene (optionally filtered by type/group) |
| `gda node set` | Set a node property (type-coerced) |
| `gda node move` | Reparent or reorder a node |
| `gda node duplicate` | Duplicate a node |
| `gda node connect-signal` / `disconnect-signal` | Wire / unwire a signal to a method |

### `script`

Operates on **GDScript files** (`.gd`) on disk — writing source text and reading it back —
so headless: `script create` writes raw text, `script get` reads raw text. Neither ever
`load()`s or compiles the script, so creating or reading a script never runs project code (the
read trust boundary of #30): a script's text is data, not something to execute.

> **C# (`.cs`) is out of scope for now.** It needs the .NET build of Godot, whereas ADR-0003
> targets the **standard** build (4.4+ / 4.6 baseline), and supporting it is a decision in its
> own right (class/base semantics differ from GDScript's leading `class_name`/`extends`). Until
> a `.NET`-build target and a dedicated decision exist, the `script` group is GDScript-only — a
> non-`.gd` path is refused as `invalid_path` rather than half-supported as opaque text. The
> deferral — whether/how to support the .NET build and C# — is tracked in #124.

**Script-file addressing** (established by #110): a script is addressed by its **file path** —
a `res://` or filesystem path ending in `.gd` — exactly the way a scene is addressed by its
`.tscn` path, *not* by its `class_name`. A `res://` path resolves against the project
(`--project`); a filesystem path is used as given (`~` is expanded). A path whose extension is
not `.gd` is refused with `invalid_path` rather than being treated as a script.

**Create: template or content** (established by #110): `gda script create PATH` writes a
minimal built-in template, `extends Node\n`; `--extends <Base>` parameterizes the template's
base class (e.g. `--extends Node2D` → `extends Node2D\n`), mirroring `scene create --root-type`.
`--content "<source>"` instead writes verbatim source and is **mutually exclusive** with
`--extends` (verbatim content is not templated, so a base class would have nowhere to go;
supplying both is a usage error). Create is **no-clobber**: an existing target is refused with
`already_exists`, leaving the file untouched (mirrors `scene create`). Missing parent
directories are created before the write (reported in `created_dirs`, outermost to innermost).

**Class metadata** (established by #110): both `script create` and `script get` report the
`class_name` and `extends` the source declares, as `{class_name, extends}` (each null when
absent), parsed by lightweight line scanning of the **raw text** — never by compiling the
script. The scan reads only the GDScript header (skipping leading `@tool`/`@icon(...)`
annotations) and stops at the first real statement, so declaration-shaped text deeper in the
body cannot be mistaken for the declaration. `script get` additionally returns the full
`source`, so a `create` is verifiable end-to-end: `create` then `get` returns the same source.

**Discovery and removal** (established by #117, mirrors `scene list` + `scene delete` #54):
`gda script list` walks the project's `res://` tree and enumerates every `.gd` script, each with
its `res://` path and the `class_name`/`extends` parsed from the **raw text** (no compilation,
issue #30) — null when the source declares neither, so the listing names every `.gd` it found.
Enumeration needs a project, so projectless it is refused with `project_not_found` (pass
`--project`); an empty project is a valid, empty listing, not an error. The walk excludes exactly
one directory — the engine's own cache at `res://.godot`, whose contents are import artefacts no
agent authored. The test is **lexical**: the child's `res://` PATH is compared against that one
path. Not the directory NAME, so a nested `.godot` is walked — it is usually authored content, and
excluding it hid real scripts from the listing and let `script validate --all` report a valid
aggregate for a project holding an invalid script (#663 review). Sometimes it is not authored
content — a vendored sub-project checked out under `res://` and opened once in an editor keeps an
engine cache of its own, whose import artefacts then count in `project statistics` and become
`find-unused-resources` candidates. That cost is accepted deliberately: gda cannot tell the two
apart from the directory alone, and a false-valid aggregate is the worse failure. And because the
test is lexical it compares the path as written, so it does **not** resolve filesystem targets: a
symlink or alias under another path that leads to `res://.godot` is walked, and the cache's contents
are then enumerated through that path. Symlink policy for the `res://` walk is undecided — #760 owns it, together with the symlink CYCLE the same walk descends until the OS path
limit stops it. Hidden entries are otherwise enumerated as promised (#54). **This rule governs the
four `res://` collectors in `operations.gd`** — the `script list` walk, the `scene list` walk, and
both static-analysis walks (the extension-filtered one behind `find-references`, `dependencies`,
`find-unused-resources` and the `class_name` index, and the unfiltered one `project statistics`
counts with) — so one project cannot answer two ways. It once did: three of the four compared the
directory NAME, so `script list` reported a script `project statistics` counted as zero (#712).
`gda script delete`
removes a script file and reports the removed script's `class_name`/`extends` (parsed before
deletion), so the result names the content, not just the path. Delete honors the same addressing
boundary as the rest of the group — only a `.gd` path is removed (a non-`.gd` target is refused
with `invalid_path`, never erasing an arbitrary file), and a missing target is `path_not_found`.
The lifecycle round-trips: `create` → `list` shows it → `delete` → `list` no longer shows it.

**Editing source** (established by #118): `gda script set PATH` edits an **existing** `.gd`
script as **raw text** — it never compiles or loads the script, so editing one never runs
project code (the read trust boundary of #30). It edits only a script that exists; a missing
target is `path_not_found`, never a silent create. Exactly one of three mutually-exclusive
modes must be selected — derived once by the params model, identically on argv and
`--params-json` (ADR-0015, #713); a missing or mixed mode is a usage error, exit 2, on argv,
and structured `invalid_params` on `--params-json`:

- **search-replace** — `--search <old> --replace <new>`: replace **every** literal (not regex)
  occurrence of `<old>` with `<new>`. A search string the source does not contain is refused
  with `no_search_match` (the edit landed nowhere; the file is left untouched). `--search` and
  `--replace` are required together and cannot be combined with the other modes' flags.
- **line-range** — `--start-line N [--end-line M] --content <text>`: replace lines `N..M`
  (1-based, **inclusive**; `M` defaults to `N`) with `<text>`. **Lines are the parts of the
  source split on `\n`**, so a trailing newline yields a final empty part — `"a\nb\n"` is **3**
  lines (`["a", "b", ""]`). The valid range is `1..N` where `N` is that part count; a range
  outside the bounds, or `end` before `start`, is refused with `invalid_line_range`.
- **full** — `--content <text>` with no `--start-line`: overwrite the entire file.

`script set` re-parses the **written** source's `class_name`/`extends` and returns them, so an
edit round-trips through `script get` (the verifier).

**Attaching to a node** (established by #118): `gda script attach SCENE --node <node-path>
--script <gd-path>` binds a `.gd` script to a node inside a `.tscn`. It reuses the node group's
**node-path addressing** (#53): `--node .` is the scene root, `--node A/B` a descendant — exactly
the form `node list` reports. Unlike the other script-file ops, `attach` is a **scene mutation**:
it loads and **instantiates** the scene (so it runs the `_init` of scripts already in the scene —
the inherent trust boundary of `node set`, ADR-0009), attaches the script via `set_script` (which,
for a script that compiles, constructs an instance of the newly-attached script, running *its*
`_init` too), and re-packs and saves. The attached script **must bind**: the headless engine
silently rejects a script `set_script` cannot bind (the node's script stays null and a re-pack saves
no script), so attach **refuses** rather than report a phantom success, distinguishing the two
rejection modes so an agent gets the right remediation — a script that does **not compile** is
`script_compile_failed` (fix the syntax; check it with `script validate`), while one that compiles
but whose native base is **incompatible** with the node (e.g. an `extends Node3D` script on a
`Node2D`) is `incompatible_script_type` (attach it to a compatible node, or change the script's
`extends`). If the script `preload("res://...")`s a target that does not exist, attach refuses
with `missing_dependency` and names the missing `res://` path; create preloaded assets before
attaching scripts that reference them. Other failures reuse existing codes: a missing script is `path_not_found`, a non-`.gd` script is
`invalid_path`, a node path that resolves to nothing is `node_not_found`, a missing or non-scene
file is `path_not_found`/`not_a_scene`, and a scene whose instances vanish or degrade on load is
`missing_dependency` (the mutation-integrity boundary, #64).

**Overwrite-and-report** (established by #132): `attach` is a **mutation verb** — it *is*
`node.set_script()` — so it **overwrites** an existing binding rather than refusing it. (Contrast
`script create`, a **create verb**: there the file is the entity and a silent overwrite is
destructive, so it **no-clobbers** with `already_exists`. `attach` does the opposite because there
is **no `script detach` command** — refusing an already-scripted node would strand it, unable to be
re-scripted, and re-scripting is a common, legitimate operation.) The overwrite is **not silent**:
the result's `replaced_script` field names the **displaced** script's `resource_path` **verbatim**
— including a built-in/embedded script's sub-resource ref (e.g. `res://scene.tscn::GDScript_xxx`),
so a displacement always reports a **non-null** signal. `replaced_script` is **null only** when the
node had no prior script. An agent reads it to detect a clobber from the result.

**Scene-before-script ordering** (established by #132): for this scene-mutating command the
**primary subject** (the scene loads + the addressed node exists) is validated **before** the
**secondary input** (the `--script` argument) — **one invariant, no exceptions**. Both the
script's `.gd`-shape check (`invalid_path`) and its existence check (`path_not_found`) run **after**
the scene load and node resolution, so with **both** the scene and the script missing the **scene**
problem is reported first. The accepted trade-off: a missing/malformed `--script` now pays the
scene load+instantiate on the error path — acceptable, since ADR-0009 makes the project trusted
(running `_init` is not a security concern) and the error path is rare.

The result echoes
the scene, node, script, the attached script's `class_name` (null when it declares none), and
`replaced_script` (the displaced script, or null), verifiable by reading the saved `.tscn` back: the
script now appears as an `ext_resource` the node references.

**Validating** (established by #118, batched by #663): `gda script validate PATH...`
syntax/compile-checks one or more `.gd` scripts, and `--all` checks every script in the resolved
project instead. **Mechanism**: for each script it reads the file text, sets it on a fresh
`GDScript`, and calls `reload()` — `OK` means the script compiles. It compiles the script
(`reload` parses and compiles), but never **instantiates** it, so it does not run the script's
instance code. Pass `--project` when a script `extends` a project `class_name` or preloads a
project resource and so needs project context to compile; a self-contained `extends Node` script
validates projectless.

**One launch per call, not per script** (#663): the whole batch is validated in a single headless
process, which is what makes checking the four to six related scripts a change touches affordable.
The result is `{valid, scripts, project_root}`: `valid` is the **aggregate** (false as soon as any
entry fails) and `scripts` carries one `{path, valid, error_string, diagnostics}` entry per
validated script, in requested order (under `--all`, in the engine's sorted enumeration order). A
single path is a batch of one, so the shape never varies with the batch size. A repeated path is
validated and reported once per occurrence — gda drops no input. `--all` needs a resolved project
(`project_not_found` otherwise, as `script list` does), and an empty project is a vacuously valid
empty batch. It enumerates through the same walk `script list` uses, so it sees the same set —
including a nested `.godot` directory, and never the engine's own `res://.godot` cache.

A **`valid=false` result is a successful operation** — `validate` exits `0` with the aggregate
`valid: false` for a batch in which any script does not compile. The op only *fails* (non-zero,
`invalid_path`/`path_not_found`) for op errors (a non-`.gd` path, a missing or unreadable file),
and such an error **refuses the whole batch** before anything is compiled rather than becoming one
script's verdict. `diagnostics` are **best-effort advisory** `{line, message}` pairs: the line and
message are not available from any bound API — only from the engine's stderr — so they are parsed
Python-side and may carry only the **first** error per script. Attribution across a batch works
because `operations.gd` writes a `gda: validating: <path>` marker to stderr before each compile
and the classifier splits the stream on it, which also drops engine startup noise (it precedes the
first marker). **`column` is always null** on the standard Godot build (the engine exposes no
column for a parse error). `validate` reuses existing codes only (no new ones).

**Project context** (#658): the result carries `project_root` — the project the script was
compiled against, i.e. the root its `res://` dependencies resolved to, absolute, and `null` when
gda ran projectless. It is **required and nullable**, and reported once per call rather than per
script (ADR-0006 resolves one project per call), so every verdict carries the key. It exists
because a script compiled against the wrong project reports every `res://` dependency as missing
plus the type errors derived from them, which reads as a broken script; `project_root` is what
tells the two apart. A target **outside** the resolved project is **refused before parsing** with
`project_not_found` naming both the file and the project, rather than emitting that false cascade.
The check applies to **every** path in a batch, and the first offender in requested order refuses
the whole call (#663): one call has one project, so one outsider makes the requested set
unservable. `--all` has nothing to check — the engine enumerates the resolved project's own tree.
Containment follows the engine's own addressing: a relative path is anchored at the resolved
project (not gda's cwd), an engine-virtual path (`res://`, `user://`, `uid://`) is inside by
construction, and a file reached through a symlink into the project counts as inside — except when
a `..` traversal could cross that symlink, where only the fully resolved location decides. gda
never derives the project from the target path (ADR-0006), so a script under a project **nested
inside** the resolved one is contained and not refused; `project_root` is what surfaces that
mismatch, pending the ADR-0006 amendment tracked in #697.

| Command | Description |
| --- | --- |
| `gda script create` | Create a `.gd` script (template or content) |
| `gda script delete` | Delete a script file |
| `gda script get` | Read script source |
| `gda script list` | Enumerate scripts (with `class_name`/`extends` metadata) |
| `gda script set` | Edit script (search-replace / line-range / full) |
| `gda script attach` | Attach a script to a node in a scene |
| `gda script validate` | Syntax/compile check (a batch of paths, or `--all`) |
| `gda script run` | Run a project script one-shot under a bounded wall clock (ADR-0031) |

**`script run`** (ADR-0031, #655) is the pass-through channel: its *success* result is the run
itself — the script's own `exit_status` (a deliberate non-zero `quit()` is data, not a gda
failure; `--strict` opts into a `script_failed` error for exit-code gates) plus the captured
`stdout`/`stderr`. `stderr` is verbatim; `stdout` is verbatim up to a 64 KiB cap (#665,
ADR-0031 amendment) — above it the result carries the stream's leading cap bytes while the
COMPLETE stream spills to a named file, disclosed by three always-present fields
(`stdout_bytes`, `stdout_truncated`, `stdout_file`), enforced as one model truth table. The
output schema publishes every Draft 2020-12-expressible projection and discloses the
remaining byte/length identities, so a production-scale inspector's linearly-growing output
bounds the envelope without losing a byte. A spill file gda cannot write is the typed
`stdout_spill_failed` (never an unbounded result and never a silently lost tail); read the
projection fields, not assumptions, when consuming `stdout`. Bounded, not summarized —
record semantics stay with the project tool. `--timeout <s>` bounds the wall clock; a run gda ends at that
ceiling reports `launch_timeout` carrying the captured partial output, the elapsed seconds and
a termination phase — `launched` (the engine wrote nothing at all) or `output_seen` (it was
alive and did not finish) — so a slow suite is distinguishable from a hang.
`--completion-marker <line>` declares a liveness contract — the script prints that line when
its work is done — and a run that hit a recognized error attributable to the entry script, has
not printed the marker, and then goes silent on both streams is ended in seconds and reported
as `script_aborted` with the captured error and phase `aborted_on_error`. The script executes in full, within
the trusted-project assumption (ADR-0009).

### `project`

Reads and writes the resolved project's `project.godot` / `ProjectSettings` headlessly. Every
project command runs against an **explicit project context** (`--project`/`$GDA_PROJECT`/cwd,
ADR-0006): `ProjectSettings` without a resolved project reports only the engine's bare defaults,
not the agent's project, so a projectless run is refused with `project_not_found` (exit 4) rather
than returning a misleading result.

> **Autoloads run on every `project` command (#61, ADR-0009).** `project info` and `project get` are
> **state-reads** at the operation level — they read `ProjectSettings` and never instantiate a scene;
> `project set` is a **`ProjectSettings` write** that persists to `project.godot`
> (`ProjectSettings.save()`) but still never instantiates a scene. Either way, every `project` command
> runs under `--project`, and the engine constructs the project's **autoload singletons** (running
> their `_init`/`_ready`) at startup, *before* the operation gets control, on `project info` / `get` /
> `set` alike. This is the documented **process-startup execution surface** of the trusted-project
> model (ADR-0009), not re-introduced silently: a `project` op is not zero-execution.

**Project metadata** (established by #111): `gda project info` reports the project's `name` and
`main_scene` (from `ProjectSettings`), its configured `viewport_width`/`viewport_height`, and the
`engine_version` the project runs on (the same shape `gda info` reports). `main_scene` is the empty
string for a project with no main scene set, and the viewport fields fall back to the engine's
built-in defaults when the project never set them — so a brand-new project still reports a complete,
valid result.

**Reading and writing settings** (established by #111): `gda project get SECTION/KEY` reads one
setting by its full `section/key` name (e.g. `application/config/name`) and reports it as a
`{setting, type, value}` triple — `type` is the setting's declared Godot type name and `value` its
JSON projection, the **same projection** `node get` reports for a node property. Compound values
arrive **structured** (ADR-0035): a `Dictionary` projects to a JSON object, an `Array` or packed
array to a JSON array, and an embedded `Object` renders as a **reference projection**
(`{type, resource_path}` for a Resource with a `res://` path), a **texture projection**
(`{type, width, height, object_string, digest}` for a PATH-LESS `Texture2D` — a runtime-created
`ImageTexture` the reference kind cannot name; `object_string` keeps the former `str()` form and
is the kind's discriminator, `digest` stays null unless a read opts in; ADR-0035 amendment,
#666), an **inline value projection**
(`{type, …storage properties}` for a whitelisted path-less value Object — `InputEvent` subclasses,
e.g. the `InputEventKey`s of an `input/*` action), or the `str()` fallback for any other Object. A
setting that does not exist is a clean `unknown_setting` error (exit 4), distinguishing a typo'd key
from a setting genuinely holding null. `gda project set SECTION/KEY --value <string>` writes a setting, **coercing**
the CLI value to the setting's **declared type** — read off the setting's current value, exactly as
`node set` reads it off the node's property list — using the **same coercion rules** the node group
established (#55; see "Property value coercion" under [`node`](#node)). It then persists
`project.godot` (`ProjectSettings.save()`) and reports the coerced value in the same JSON projection
`project get` uses, so a **`set` round-trips through a `get`**. `set` edits an **existing** setting —
an unknown key is `unknown_setting`, never a silent create, so the type to coerce to is always known.
A value that cannot be coerced to the setting's type is `uncoercible_value` (exit 4, the #55 code,
`project.godot` left untouched); a failed save is `save_failed`.

**Listing settings** (established by #312): `gda project list` enumerates the project's
`ProjectSettings` keys so an agent can **discover** which settings exist — the list half of the
`list → get → set` workflow (`get`/`set` both require you to already know the `section/key`). Each
entry reuses the **same** `{setting, type, value}` projection `project get` reports — so a listed
entry round-trips through `project get` — **plus** an `is_default` boolean: `false` when the key is
customized (written in `project.godot`), `true` when it is at the engine's built-in default. By
default the listing is only the project's **customized** settings (small and useful); `--all` widens
it to the engine's built-in defaults too, and `--section <prefix>` restricts it to keys whose name
begins with that `section/` prefix (e.g. `application/`, `display/`) — the two compose. Internal
engine-bookkeeping settings and the non-setting properties the engine's property list also returns
are filtered out, so only real `ProjectSettings` keys appear. Like the rest of the group it requires
a resolved project (`project_not_found`, exit 4, otherwise) and never instantiates a scene.

**Input actions** (established by #380): `gda project add-input-action NAME --key K...` registers an
InputMap action under `input/<name>` — the compound `{deadzone, events}` entry `project set` cannot
express — with **key events only** for this slice (mouse/joypad kinds may extend it later). `--key`
is repeatable and accepts a Godot key **name** (`J`, `Space`, `Escape`) or a raw base-10 **keycode**;
an unresolvable token is a clean `invalid_key` error (exit 4, nothing saved). `--deadzone` overrides
Godot's `0.5` default; `--physical` binds physical keycodes (keyboard position, layout-independent)
instead of layout keycodes. The action is built from real `InputEventKey` objects and persisted via
`ProjectSettings.save()`, so the serialization is exactly the engine's own `var_to_str` form — the
editor and a running game load it identically to a hand-authored entry, and the action is immediately
driveable by `gda input action NAME` in a live session started afterwards. Adding an existing action
name is `already_exists` (never a silent clobber — remove first to replace; note the engine registers
the built-in `ui_*` actions as defaults, so adding e.g. `ui_accept` reports `already_exists` by
design). `gda project remove-input-action NAME` unregisters the action and persists `project.godot`;
a missing action is `unknown_setting`, mirroring `remove-autoload`. A failed save is `save_failed`.

| Command | Description |
| --- | --- |
| `gda project info` | Project metadata (name, main scene, viewport, engine version) |
| `gda project get` | Read a project setting by section/key (typed JSON) |
| `gda project list` | List the project's settings keys (customized by default; `--all` adds defaults, `--section` filters) |
| `gda project set` | Modify a project setting (value coerced to its declared type) |
| `gda project add-autoload` / `remove-autoload` | Register / unregister an autoload singleton |
| `gda project add-input-action` / `remove-input-action` | Register / unregister an InputMap action (key events) |

### `resource`

| Command | Description |
| --- | --- |
| `gda resource create` | Create a `.tres` resource file |
| `gda resource delete` | Delete a resource file |
| `gda resource get` | Load and inspect a resource |
| `gda resource set` | Edit a resource file |
| `gda resource uid` | Resolve UID ↔ resource path (both directions) |
| `gda resource import` | Ensure assets are imported into the project cache (clean-worktree loading) |

**Scoped import surface** (shipped, #668, per the issue's revised contract): a clean
worktree carries the sources and their committed `.import` sidecars but not the gitignored
`.godot/` cache, so a one-shot run's `preload()` of e.g. a PNG fails with "no recognized
resource loader" (GDA-DF-010). `resource import ASSETS... [--dry-run] [--timeout S]` reads
each requested asset's EVIDENCE STATE from the same project artifacts the engine's own
reimport test reads: `cached` needs positive ARTIFACT-level evidence (a keep/skip
importer, or the PATH-derived `.md5` receipt present with `source_md5`/`dest_md5`
matching the bytes — any declared destinations also present — plus `source_file` naming
this asset and the UID-era format; a sidecar declaring no destinations but carrying a
matching receipt passes the same artifact checks — the engine's own pass leaves it
untouched when the engine-state remainder below is controlled — while one with no
importer line proves nothing and is conservatively `stale`); `missing` (no sidecar yet)
and `stale` (an artifact check fails) are what the engine would import; `invalid` (the
engine marked the last import `valid=false`, the sidecar does not parse, or the `.md5`
receipt falls outside gda's documented engine-written assignment subset) is not passed
automatically: the engine skips failed imports and parse errors, while gda conservatively
skips unsupported receipt syntax —
delete the sidecar to retry; that heals a malformed receipt too, because the pass
rewrites both. That receipt subset accepts quoted-string assignments, whitespace,
`;` comments, JSON-style escaped strings (lone UTF-16 surrogates excluded — the
engine's parser rejects them), and repeated assignments; as in the engine,
the final value wins. Broader Variant values take the conservative no-pass direction.
Artifact-level is the boundary, not a proof of the engine's
whole verdict: the checks the engine makes from its OWN state — whether the declared
importer still exists (an open registry: import plugins add names), its format version,
its project-settings validity, and the editor cache's expected sidecar MD5 — are not
readable from the project's artifacts, so a sidecar drifted in those dimensions can read
`cached` until any pass runs. The declared direction of that remainder: it can delay a
re-import until the next pass, never spend a pass the engine would not. The engine pass runs only when a request is `missing` or
`stale`; it is PROJECT-WIDE (the engine's one scriptable import primitive is
`godot --headless --import`; a per-file reimport exists only inside the editor process), so
gda's scoping is in the decision and the report. A real run settles each state
(`imported` / `not_importable` — the engine decided the type needs no import / `failed` —
every `invalid` request settles here without spending a pass) and lists every created
file, classified against the explicit cache root: `cache_owned` (under `res://.godot`) vs
`source_adjacent` (`.import` and `.uid` sidecars — the GDA-DF-038 noise, accounted file by
file). `--dry-run` writes nothing and reports the decidable inventory: the per-asset
states, the requested assets' sidecars-to-be, and `pass_will_also_import` — the OTHER
stale assets the project-wide pass will re-import (invalid ones excluded; assets with no
sidecar and generated `.uid` files are the engine's to decide, so the real run's `created`
list is the authoritative inventory). Plain `gda script run` never triggers an import
pass. The pass executes engine importer code over project content — within the `Trusted
project` assumption (ADR-0009), recorded on the Project-code execution surface (no new
trust axis, per the issue's triage decision).

### `export`

| Command | Description |
| --- | --- |
| `gda export list` | Enumerate export presets |
| `gda export run` | Run an export preset via headless CLI |
| `gda export get` | Export-template install status / preset info |

`gda export run` resolves its effective destination before the native export:
`--output` wins over the preset's `export_path`; a relative `--output` resolves
against the invoker's current working directory, while a preset `export_path`
keeps Godot's project-relative convention (including a literal `~` path
component; no shell-style home expansion). The JSON `output_path` is the
resolved absolute artifact path. Missing output parent directories are created
before the native export and reported in `created_dirs`, outermost to innermost;
an uncreatable parent is reported as `export_output_parent_failed` before Godot
runs.

### Asset-file groups (create/edit files; headless)

These create or edit resource files (`.gdshader`, `.tres`) and so are headless.
*Applying* them to a live node is Phase 2.

| Command | Description |
| --- | --- |
| `gda shader create` / `get` / `set` | Create / read / edit a `.gdshader` file |
| `gda theme create` | Create a `.tres` Theme resource |

### Static analysis (read-only, headless)

| Command | Description |
| --- | --- |
| `gda project find-unused-resources` | Find unreferenced resource files |
| `gda project find-references` | Find references to a script/class |
| `gda project dependencies` | Map scene → scene references |
| `gda project statistics` | File/line counts, autoloads, plugins |

Two static walks back these, over different file universes: `find-references`,
`dependencies`, `find-unused-resources` and the `class_name` index (which node/resource
creation resolves through) share the extension-filtered one, while `project statistics`
counts with an unfiltered one that also sees `.import` sidecars and `project.godot` — so
its file total does not reconcile with the others' candidate set. What is shared is the
directory exclusion, the rule `script list` states above (#712).

---

## Phase 2 — live domain commands (served by `gda-daemon`)

Listed coarsely; enumerated as slices when Phase 2 (PRD #6) is worked. All require a
running `Engine session` and so cannot be a one-shot headless call. Mechanism is fixed
by ADR-0017 (execution), ADR-0018 (harness), ADR-0019 (placement), ADR-0020
(consistency), and ADR-0021 (transport / discovery); scope is the **running game**, not
an attached editor. Live ops are distributed by their real domain object (ADR-0019), not
lumped into one "live" group. Because the daemon↔harness transport is a Unix domain
socket (ADR-0021), **Phase-2 live requires Godot 4.6+ and is macOS/Linux only**; Phase-1
headless is unaffected (4.4+, cross-platform).

- **`game` (the running game's scene graph):** `game tree` reads the runtime scene
  tree (shipped — the Phase-2 bootstrap tracer, #7); runtime node property `game get` /
  `game set` (shipped, #220, extended by #422/#473) read and mutate a running node's live
  properties — the live counterparts of headless `node get` / `node set`, applying the
  **same** value-coercion table and returning the observed read-back value plus
  `verified` to distinguish a matched read-back from a completed set whose value did not
  stick. When a property is explicitly named, storage properties are preferred and plain
  attached-script variables are addressable as a fallback; unfiltered `game get` keeps the
  storage-property listing. `game get --texture-digest` (shipped, #666) opts a read into
  the content digest of each PATH-LESS `Texture2D` value's **texture projection**
  (ADR-0035 amendment): the digest needs `Texture2D.get_image()`, a GPU-to-CPU readback,
  so without the flag the projection's `digest` field stays null.
  `game rect` (shipped, #419) reads a running
  `Control`'s rendered viewport-space rectangle via `Control.get_global_rect()`, returning
  `position` and `size` as the existing Vector2 projection. These commands address the
  node by its **runtime (absolute) path** as `game tree` reports it (e.g.
  `/root/Main/Player`), in contrast to the on-disk node group's **root-relative** path:
  the live tree has no `.tscn` scene root to be relative to, and the headless resolver
  rejects absolute paths, so the harness resolves off the running `SceneTree` root. A
  `set` applies at a frame boundary (ADR-0020) and is bound to the session, not persisted;
  a missing node is `live_node_not_found`, an absent property `live_unknown_property`, an
  uncoercible value `live_uncoercible_value`, and a `game rect` target that is not a
  `Control` is `live_not_control`. The on-disk counterparts stay under `scene` / `node`
  (ADR-0019).
  `game call <node> --method NAME [--args JSON]` (shipped, #673, ADR-0041) serves the
  read `game get` cannot: a debug or state contract the project exposes as a METHOD
  rather than a stored property (GDA-DF-033). The method must be named by the
  **`GDA_CALLABLE` declaration** resolved from the addressed node's attached script
  along its base chain — which gda reads STATICALLY from the script's constant
  map, so learning what may be called runs no project code. The allowlist is NOT a trust
  boundary (the project is trusted, ADR-0009, and `script run` already executes
  arbitrary project code): it keeps the live READ surface free of side effects gda did
  not ask for and bounds results to the value projection. gda cannot verify that a
  declared method has no side effects — the declaration records the DECLARER's
  assertion; what gda guarantees is that no UNDECLARED method is callable. Arguments are
  JSON values passed as the live parser's Variant forms, where every number is float
  (no string-coercion table — a call's
  arguments are typed by the method, not by a stored property). The return value goes
  through the shared value projection; a method returning nothing projects as null, and
  the `--texture-digest` opt-in is not part of this first version (a path-less
  `Texture2D` return projects with a null digest). Three distinguishable refusals: a
  method the node does not have is `live_unknown_method` (existence is checked FIRST, so
  a wrong name is diagnosed as one), one it has but never declared is
  `live_method_not_allowlisted` — whose message names the script chain's declared set, so
  discovery rides the failure — and arguments the declared method cannot take are
  `live_invalid_call_args`, refused BEFORE the call. That covers the count AND each
  argument's type: the check mirrors the engine's own `Variant::can_convert_strict`
  (not exposed to GDScript) over the six Variant types the live JSON parser produces.
  Every JSON number arrives as float; bool/float reach numeric parameters and null
  reaches an `Object` parameter, while a String into `int`,
  a Dictionary into an `Object` parameter, null into `int`, and any JSON array into a
  typed `Array[int]` are refused with the reason. Without the check `callv` pushes an
  engine error, returns null and writes to the Session log — a failure that would read
  as a successful null. Two reproduced unsafe argument classes are refused earlier
  still, in the params model both invocation paths share (recursively, so a nested
  value counts):
  non-finite numbers (`NaN`/`Infinity`, which JSON has no literals for but Python's
  decoder accepts) — left through they produced a frame the harness could not parse,
  costing the caller a `live_timeout` and the session its runtime state — and JSON
  integer values outside ±(2^53 − 1), since the harness reads JSON numbers as binary64
  and a larger integer can arrive as a DIFFERENT value (a call that then succeeds on
  something the caller never sent). Finite floats already are binary64 and do not
  inherit that integer bound; real-engine tests pin the reproduced high-range values
  `1e17`, `2.5e17`, and `1e300` unchanged. This is not a full-range preservation
  guarantee: Godot 4.6.3 parses some small-magnitude normal values, including
  `1.2345678901234567e-300` and `DBL_MIN`, as `0.0`, and its `JSON.stringify` can
  also lose small live-result values. [Issue #752](https://github.com/aigengame/godot-agent/issues/752)
  owns that cross-operation transport defect. Standard JSON Schema cannot distinguish
  an exponent-form float from the equal mathematical integer, so its recursive number
  branch stays broad and discloses that the params model enforces the integer-token
  bound at execution. RFC JSON excludes `NaN` and `Infinity`; some in-memory schema
  validators accept those extensions as numbers, but the params model refuses them and
  the model/schema corpus pins that deliberate over-acceptance. The type table itself is the
  engine's `Variant::can_convert_strict` closure over the six live JSON source types,
  pinned by a real-engine conformance matrix that first asserts the observed numeric
  type and then uses direct `callv` as its oracle.
  The constant is the inheritance CHAIN's declaration, not a per-class increment:
  GDScript forbids a subclass from redeclaring a base class's constant, so an opted-in
  chain has at most one declaration owner (a base owner covers its subclasses and need
  not define every method it names); a project that declares in both fails to parse with a message naming the
  member — loud, never a silently wrong allowlist.
- **`input` (input simulation):** runtime input injection into the running game
  (shipped, #221). Single-frame ops `input key <KEY> [--modifiers …] [--released]`,
  `input mouse-move <x> <y>`, and `input action <NAME> [--release] [--strength F]`
  each inject one event at a frame boundary (ADR-0020). The **activation
  gestures** (#652) are multi-frame: `input mouse-click <x> <y> [--button
  left|right|middle] [--double]` injects the COMPLETE click its name implies —
  the initial move, the press, and the release, one per process frame across a
  3-frame window — because Godot's UI activates on the release (a bare press
  never emits a default `Button`'s `pressed` and leaves it held down,
  GDA-DF-004); and `input tap (--key K [--modifiers …] | --action NAME
  [--strength F]) [--hold-frames N] [--settle-frames M]` performs the complete
  press-hold-release of one key or one InputMap action — press at window frame
  0, release after N (default 2, at least 1) process frames, then M (default 2)
  settle frames so the game observes the release before the op returns — because
  a press/release pair contained in one immediate frame reports success without
  advancing a focused UI (GDA-DF-034). Both gesture results report the injected
  `phases` (each phase's window frame) and the focused Control's runtime path
  before/after the gesture (`focus_before` / `focus_after`, null when nothing
  holds focus) — the activation evidence the engine exposes. Repeated injected
  mouse events add no harness-owned warnings to `diag errors` (#647): the
  harness notifies the viewport's mouse-enter state only on a real edge,
  mirroring it from the root Window's `mouse_entered`/`mouse_exited` signals.
  The multi-frame
  `input sequence --events <JSON>` applies a list of events across one selected
  clock and returns as one blocking payload, on the gda harness's time-windowed
  multi-frame base (the same base `perf monitor` uses, #223). A sequence
  `mouse_click` event is a whole click at ONE clock offset — the harness pushes
  the press and then the release on the same frame, which fully activates a
  default `Button` (mouse activation, unlike a focused-UI key tap, does not need
  the pair split across frames). Existing sequence
  event `frame` offsets are explicitly the harness/process-frame clock advanced by
  the harness `_process` loop; they are preserved for compatibility and are **not**
  Godot's fixed physics frames. For deterministic simulation-duration input, use
  `physics_frame` offsets instead: press an action at `physics_frame: 0` and release
  it at `physics_frame: N` to hold it for N Godot physics ticks (for the default
  60 Hz physics clock, N = 30 is 0.5 seconds of physics simulation). A sequence must
  use one clock throughout; mixing `frame` and `physics_frame` is rejected. For a
  mouse drag, use sequence-only `{"type":"mouse_button", "pressed":true, ...}` /
  `{"type":"mouse_button", "release":true, ...}` phase events around
  `mouse_move` events in the same sequence; those motion events carry the held
  mouse button mask for `_input(event)` drag handlers. The
  mouse ops are flat two-token commands (`mouse-click` / `mouse-move`), not a nested
  `mouse` sub-group, so each maps to a single `<group>_<command>` MCP tool name
  (ADR-0005/0011/0012). Key/mouse events ride the game's real input flow via the
  root viewport's `push_input` (scene-aware); actions go through
  `Input.action_press`/`action_release` against the running `InputMap`. For mouse
  ops and sequence mouse events, the reliable injected coordinate is
  `InputEventMouseButton.position` / `InputEventMouseMotion.position`; Godot may
  leave `Viewport.get_mouse_position()` and `Node2D.get_global_mouse_position()`
  stale in daemon sessions, so game code should read the injected coordinate from
  the input event. The modifier
  set, mouse-button enum, action strength range (0..1), per-event shape, the
  tap's exactly-one-target rule and window (`hold_frames + settle_frames + 1` ≤
  the per-window ceiling), and the
  sequence's selected-clock window (`max(frame)+1` or `max(physics_frame)+1` ≤ the
  per-window ceiling, the same bound `perf monitor` enforces, #223) are bounded
  **model-side** (ADR-0015), so an
  out-of-contract request is a structured `invalid_params` (or argv usage error)
  before it reaches the harness. The two failures that need the live engine
  to decide are deferred to the harness: a key name the engine cannot resolve to a
  keycode is `live_invalid_key`, an action absent from the running `InputMap` is
  `live_unknown_action`; a sequence event whose type the harness does not recognize
  is `live_invalid_event_spec`. The per-event shape is a **discriminated union** on
  `type`: each kind accepts only its own fields, so `--schema` publishes each kind's
  required and forbidden fields rather than one flat shape. The press/release
  spelling differs by kind — `pressed` belongs to `mouse_button` alone, an `action`
  releases with `release`, a `key` with `released` — and a field from another kind is
  refused with the spelling this kind uses instead.
- **`screen` / capture:** running-game viewport screenshot, multi-frame capture.
  `screen frames --summary` (#665, GDA-DF-021) keeps a large capture's completion
  envelope COMPACT: every frame is still captured and written exactly as the
  default form does, but the result replaces the per-frame `frames` list with the
  aggregate `summary` (`output_dir`, filename `pattern`, frame size,
  `total_bytes` — the frame dims are the uniform size, or null when a legal
  mid-window resize made the sequence non-uniform; exactly one of the two
  projections is non-null, required-but-nullable, and the exactly-one rule is
  published in the output schema), so the envelope does not grow with
  `--frames`. What is PROVEN about the dogfooding loss (GDA-DF-021): gda's own
  stack completes a 90-frame capture with the full envelope against a real
  engine — on the exact release under test (gda 0.8.0) and on the current head,
  up to ≈327 MB of PNG bytes (≈436 MB base64-expanded in the single IPC reply)
  — and the reported observation (all PNGs present, no final JSON) itself shows
  the reply had reached the CLI, which writes the files from it. The leading
  BOUNDED HYPOTHESIS for the residual loss, not reproduced (the original
  caller's automation was not re-run): a caller-side output-handling limit,
  suggested by the failure boundary tracking the result line's size (~226 B per
  frame entry: 30/36/48 frames ≤ ~11 KB reported good, 90 frames ≈ 20 KB lost)
  — though those observations vary frame count and line length together, so
  they establish correlation, not the specific cap. The compact envelope stays
  well under any such limit either way. The
  `--await-*` predicate (shipped, #661) holds a `screen capture` game-side until
  `node.property == value` first holds — checked once per PROCESS frame, up to
  `--await-frames` (default 60, ceiling 600) — then captures at that SAME frame
  boundary and reports the predicate evidence (`observed` value, absolute
  `engine_frame`, window-relative `frames_waited`); a predicate that never holds is
  the typed `live_predicate_unmet` carrying the last observed value. `--await-events`
  additionally applies input-sequence events (the same discriminated union `input
  sequence` takes) INSIDE the same window at their process-clock `frame` offsets — the
  atomic input-and-capture form, so a 3–8-frame transient triggered by the input
  cannot be missed by a second CLI round trip; physics-clock offsets are refused. An
  offset at or beyond the PREDICATE ceiling still fires — the reply waits for every
  declared event — but can no longer satisfy the predicate, whose scan ends at that
  ceiling. Every event offset is nevertheless at most 599, so the TOTAL drain stays
  within the shared 600-frame live-window ceiling; both limits and the modifier
  vocabulary are published in the schema, and the schema/model event sets agree
  (ADR-0015). Every
  declared event fires before the reply even when the predicate matches first, so no
  injected press is left held — and a declared event that FAILS makes the whole
  capture that typed failure (the capture payload is discarded, no file is written,
  later events still drain). The predicate compares JSON scalars (numbers
  numerically, strings against the String rendering). The coherence contract,
  verified live on both trigger paths (ADR-0020 amendment): each tick EVALUATES
  BEFORE it injects, so the observed property is always the state of the previously
  COMPLETED frame — exactly the frame the captured texture presents. A
  `_process`-driven flip is observed with its own presentation; a state written by an
  injected event's synchronous callback is observed one boundary later, together with
  its presentation. Consequences: the predicate sees frame-boundary state only (a
  value overwritten before its frame completes is never observable — the typed unmet
  error, never a capture of mismatched pixels); an event's effect is observable from
  the NEXT boundary (leave one frame between the last state-changing event and the
  ceiling); and a game that updates a visual one frame after the property it gates on
  trails by that game-side frame — gate on the visual's own property when exact
  pixels matter.
  Every `screen capture` result also carries an evidence **receipt** (shipped, #660;
  ADR-0017 amendment): `{session_id, scene_path, scene_uid, engine_frame, observed,
  sha256}`, every key always present (the nullable ones required-but-nullable in the
  published schema). `scene_path`/`scene_uid` are the LAUNCHED scene's identity —
  remembered at the session handshake, the same value the daemon verified; a launch
  fact, not a claim about what an individual frame presents — with the `uid://` read
  from the scene file's header (ADR-0036; gda-authored scenes report null).
  `engine_frame` is read at the SAME frame boundary as the pixels; `session_id` is
  the daemon-minted engine session identity that `gda daemon status` reports (a new
  session mints a new one, so a receipt from a stale session is detectable by the
  mismatch); `sha256` is computed CLI-side over exactly the bytes written to
  `--output`. A plain capture's receipt binds session, scene, and frame and removes
  the local hashing step; a gated capture's receipt additionally echoes the
  predicate's `observed` value at that same frame, and its COMPLETE evidence is the
  pair receipt + `predicate` report (which carries the node, property, and expected
  value). A reply whose receipt is missing, echoes an observation no predicate asked
  for, or disagrees with the predicate report beside it is refused as
  `contract_violation` before any file is written.
- **`perf` (runtime performance monitoring):** `perf monitors` snapshots the running
  game's instantaneous Performance counters in one frame (shipped, #223); `perf
  monitor --property … --frames N` / `--signal … --frames N` collects a per-frame
  property/signal timeline over N frames and returns it as one blocking payload
  (shipped, #223). The time-windowed collection runs on the gda harness's multi-frame
  base — per-frame accumulation, replied once (ADR-0017 one-shot RPC, ADR-0020
  multi-frame). The `--frames` count is bounded model-side (1..600, ADR-0015) and
  exactly one of `--property`/`--signal` is required, so an over-range or ambiguous
  request is a structured `invalid_params` before it reaches the harness. A missing
  node is `live_perf_node_not_found`, an absent property `live_perf_property_not_found`,
  an absent signal `live_perf_signal_not_found`; a genuinely stalled engine is caught
  by the daemon-level `live_timeout`.
  `perf monitors` also has a WINDOW mode (shipped, #662; the issue's triage
  decision put it on the existing command — no third near-homonym). With
  `--frames N`, the harness reads every selected engine monitor once per frame
  over the window. All monitors are read when no `--monitor` is given. The
  harness returns only the raw timestamped samples. The CLI computes the
  statistics — count, min, max, mean, p50, p95 per monitor; percentiles are
  nearest-rank — because the command is a recipe (ADR-0023, the `screen`
  pattern). With `--budget FILE`, the CLI also evaluates one pass/fail verdict
  per budgeted monitor, plus an overall `passed`. A failed budget is data: the
  command still exits 0. The budget file is a JSON object of
  `{monitor: {stat, min?, max?}}` entries. `stat` is required (one of min, max,
  mean, p50, p95) and at least one bound must be set. Admission is strict:
  UTF-8 only, unique keys at every depth, finite numbers only. The budget is
  validated before dispatch, so a bad file never costs a live window; a budget
  for a monitor outside the sampled selection is refused. Monitor names are
  bounded model-side against a CLI mirror of the harness's monitor table (a
  sync test holds the two identical). The reply is correlated with the request:
  a self-consistent reply for a different window or selection classifies as
  `contract_violation`. The `--frames` bound inherits the same 1..600
  per-window ceiling, stated in help and echoed as `max_frames` in the result.
  The result names its mode (`kind: snapshot | window`); `--monitor` and
  `--budget` require `--frames`, and the no-flag snapshot behavior is
  unchanged.
- **`diag` (diagnostics):** runtime errors of the running game (shipped, #224; callstacks #283). `gda diag errors`
  reads the running game's runtime errors as structured `{level, message, function?, file?, line?, callstack}`
  (warnings included, distinguished by `level`), with `--limit N`. `callstack` is an ordered
  `SourceFrame[]` of `{function, file, line}` frames parsed from the engine's `GDScript backtrace`
  block in the Session log — empty when the error logged none (#283). Daemon-served, not
  harness-relayed: the daemon reads the `Session log` it launched the engine with (`--log-file`),
  so it works even after the game has crashed — a remembered session with a missing log is
  `live_log_unavailable`, an empty log is an empty result (ADR-0022). (The raw `diag log` is
  **superseded by `gda logger tail`** below.)
- **`logger` (structured runtime log):** the running game's whole runtime log as structured
  records (shipped, #281, ADR-0026). `gda logger tail [--level <min>] [--limit <N>] [--raw]` parses
  the same daemon-owned `Session log` into typed `LogRecord`s — engine errors/warnings via the diag
  parser (carrying `source` + an `origin` sub-kind), **every other line a plain `info` record (the
  whole log, nothing dropped)** — so an un-instrumented project gets structured logs for free. The
  result is `LoggerTailResult { records: LogRecord[] }` (mirroring `diag errors`' `{errors: […]}`).
  `level` is the closed, ordered enum `debug < info < warning < error` (`--level` filters by minimum
  severity); `--limit N` tails the most-recent-N; `--raw` skips classification, returning every line
  as a verbatim `info` record (the superseded `diag log` view, still `LogRecord[]`). Daemon-served
  and crash-survivable like `diag` (ADR-0022). The opt-in rich `gda_log()` protocol layers on in a
  follow-up slice (#282).
- **lifecycle (the `daemon` command group):** `gda daemon start` / `stop` / `status` /
  `wait-ready`, and `gda daemon install` / `uninstall` for the `gda harness` (ADR-0018).
  `daemon wait-ready` (`kind = LIVE`, #657) establishes the lazily-launched engine session
  deterministically: a session launches on the first operation that REQUIRES one (ADR-0017),
  and the read-only diag/logger reads never do (ADR-0022), so a first `diag errors` right
  after start reports `engine_session_not_running` by design — `wait-ready` is the
  documented way to trigger that launch explicitly, with one daemon-side wait/commit budget.
  `--timeout` is ONE deadline over the whole
  daemon-side readiness attempt — retiring the session being replaced, the
  spawn, the harness connect, the token and scene-verification frames (each read against the
  deadline, not a per-chunk inactivity timeout), and the teardown of a failed launch (a finite
  number in (0, 50], under the live channel's 60s client-side round-trip bound). It is a budget
  for waiting and for committing to new work rather than a hard wall clock — no phase gets a
  fresh grace, every timed wait uses what remains, and once it is spent nothing further is
  launched — but a synchronous step already in flight (a filesystem write, the spawn itself)
  can delay when that expiry is observed. Success (`{pid, launched}`) means subsequent
  live reads serve, and a repeat while the session is alive is idempotent (`launched:
  false`, nothing relaunched). A session stops serving when its harness channel breaks OR
  when a relay hits `live_timeout` — the one-op-at-a-time RPC carries no request id, so a
  late reply can no longer be attributed — and the next operation that requires a session
  relaunches it, losing runtime state (ADR-0017 amendment, ADR-0020). `daemon status`
  also reports `session_id` (#660): the daemon-minted identity of the last session it
  SUCCESSFULLY established — stable for that session's lifetime, reported for a dead
  session too (mirroring how the log ops keep a crashed session diagnosable), and
  retained across a failed replacement launch (nothing replaced the session it names)
  until a new session is established. It is the value a `screen capture` receipt's
  `session_id` correlates with; null before the first established session this daemon
  lifetime. `daemon start --windowed` additionally
  requires the host's desktop session — an on-console GUI login on macOS, `$DISPLAY` /
  `$WAYLAND_DISPLAY` on Linux — because a windowed Godot aborts during `DisplayServer`
  registration without one; it is checked pre-launch (#345) and refused with one of two
  ENVIRONMENT codes (#667): `live_windowed_unavailable` when nothing refused the probe and no
  session is reachable (skip rendered QA here) and `live_windowed_permission_denied` when the
  window-server lookup itself was refused, e.g. a sandbox (re-run outside the restriction).
  The second code does NOT mean the host has a window server — macOS refuses the lookup
  before resolving the name, so a broadly-confined process is refused whether or not one
  exists; it means only that gda was not allowed to ask, and re-running outside the
  restriction is what settles it. Conversely a sandbox that hides the window server rather
  than refusing the lookup is indistinguishable from an absent session. A refusal that
  originates in `daemon start --windowed` carries the deciding host call as the envelope's
  `probe` `{name, platform}` (ADR-0004 amendment); a refusal relayed from an already-running
  daemon carries it too — the live wire's error payload gained an optional `probe` key, and
  `classify_live` preserves it into the public envelope.

Out of scope (editor context, ADR-0017): UndoRedo-aware mutation, the editor's
open-scene tree, saving the open scene, editor errors/screenshots, run-editor-script,
reload-plugin/project. Authoring that `godot-mcp-pro` does through a live editor, `gda`
does headless by editing files.

---

## Deferred / not yet triaged

Seeded from `godot-mcp-pro` but not yet placed into a phase or group above — revisit
when relevant: **animation** (AnimationPlayer / AnimationTree state machines),
**tilemap**, **physics/collision**, **audio buses**, **particles**, **3D scene**
(mesh/lighting/camera/environment/gridmap), **navigation** (regions/agents/baking),
**Android deploy**. Most mutate scene/resource files and are likely Phase-1-able, but
each needs its own slice-level design before it becomes a commitment.
