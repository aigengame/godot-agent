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
same directories and differ only in the extension they collect (#712). Since #764 they
run the same traversal too, and both match the extension **without regard to case**, as
the engine does — a `Level.TSCN` is a scene to `ResourceLoader`, so `scene list` reports
it. That case rule is new: the scene walk alone used to compare case-sensitively, which
made `project statistics` count a `Level.TSCN` as a scene that `scene list` could not
see.

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
JSON projection `node get` uses (its default on a freshly-loaded node), at the same full binary64
precision (#771) — the property-value introspection is reused from `node get` (#55), not
re-implemented. An export is detected by its usage flags
(`PROPERTY_USAGE_SCRIPT_VARIABLE` + `PROPERTY_USAGE_EDITOR`) on the script's own property list, so a node's inherited engine properties and a script's plain (non-`@export`)
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
  #651's closed set: the engine's own failure sentences (a runtime error, a failed assertion, a
  script that could not load, a script binding the engine refused) **and a project-raised
  `push_error()`** (#722), which is the most common way a Godot project reports exactly the
  invariant violation GDA-DF-030 describes. That one is recognized by its `at:` frame — which
  the engine fixes as `push_error` — never by its message, which is the project's own prose; its
  `kind` is `push_error` and its `path`/`line` are the call site named in the engine's GDScript
  backtrace, or null when it attached none. Everything else the engine prints stays
  unrecognized: a backtrace alone does not qualify a record, since the engine attaches one to
  any error raised while GDScript is on the stack, including engine-side failures a script only
  triggered indirectly.

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
  stops at that edge; what lies beyond it is unreported until the cycle is broken. A cycle
  outranks the depth bound on the same edge: an edge first declined because its target lay past
  the bound is reported as this kind the moment any route proves the cycle, so the bound can
  never hide one.
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
the params contract states the two bounds are not cross-checked. That verdict carries the
evidence the launch measured, the same two numbers the `launch_timeout` envelope reports on
every other channel: `elapsed_seconds`, how long the run actually took, beside `timeout_seconds`,
the `--timeout` it reached. The pair names the consumed ceiling and what raising it buys — it
does not name the cause: both causes read essentially the same numbers, so decide between a
larger `--timeout` and a smaller `--frames` window from what the scene is expected to do, and
rerun. Both keys appear on the `timeout` verdict only; every other verdict omits them
rather than reporting null, because nothing bounded that run (#787). Only addressing and environment problems fail: `path_not_found`,
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
round-trips through a `get` — with one measured exception, the scene packer's elision, recorded
under "Number coercion" below: a float value too close to the property's declared default is
omitted from the `.tscn` altogether, so the `set` echo reports what was written and the following
`get` reads the default. An unknown property is `unknown_property`; a value that cannot be
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

**Number reporting** (#771) — the READ half, shared by every headless command that projects a
value. `ops/operations.gd` frames each reply with Godot's **full-precision** JSON writer, so a
projected float is the exact binary64 the project holds: `node get`, `scene get-exports`,
`project get` / `project list`, `resource get`, and the value each `set` echoes all report
`1e-300` as `1e-300` and `3.141592653589793` as `3.141592653589793`. They did not before #771 —
the default writer formats fixed-point with at most 32 decimals, so it reported everything below
about `1e-32.6` as `0.0` and rounded ordinary values to ~15 significant digits, handing the caller
a number the project does not hold with nothing marking it approximate. The stored value was never
the problem: `project.godot` held `3.141592653589793` while the reply said `3.14159265358979`.
**One residual is disclosed rather than fixed**, and it is the same one the live replies carry: a
NEGATIVE ZERO reads back as `0.0`, which the engine decides (`JSON::_stringify` returns `"0.0"`
for anything equal to zero) before the precision argument applies. It is the same engine writer
the live harness uses, so it is measured against the same corpus and the same partition —
`gda.live_numbers` is the authority, and `tests/value_projection/test_e2e_headless_number_reads.py` re-derives the
verdict from a real engine.

**Number coercion** ([#772](https://github.com/aigengame/godot-agent/issues/772)) — the WRITE
half, shared by every `--value` a command coerces to a float: `node set`, `resource set`,
`project set` and the live `game set`. They coerce with the engine's own parser
(`String.to_float`, which is `built_in_strtod` — the same function `JSON.parse_string` calls for
a number), so the losses the live wire documents apply here too, and gda draws the same line,
in two clauses: a literal that parser turns into `0.0` is REFUSED **when the literal does not
denote zero**, and a literal it turns into `NaN` is REFUSED outright — `0e600` denotes zero and
still falls, by the second clause (`uncoercible_value`, exit 4, headless; `live_uncoercible_value`,
exit 6, live; target untouched); low-order drift is disclosed. Three classes are refused, each measured on a real engine: `2.2250738585072014e-308`
and `5e-324`, which no decimal spelling delivers (the −309 cliff the live wire refuses); a
FIXED-notation literal whose first 18 mantissa digits are leading zeros, because the parser's
18-digit cap counts them — `0.000000000000000001` reads as `0.0` while `1e-18` is exact; and
`0e600`, a zero mantissa scaled by an overflowed power, which reads as `NaN`. The refusal names
its remedy, which exists here and not on the wire, because on a write the CALLER spells the
literal: **scientific notation carrying only the digits the value needs** usually works. Not
refused is the parser's low-order drift — 1 ULP at ordinary magnitudes, up to 105 doubles for a
full-precision literal between `1e-4` and `1e-2`, where leading zeros spend that same 18-digit
budget. Refusing that would reject ordinary game values, so it is disclosed instead, and the
`set` echo reports at full binary64 precision what the target holds after the coercion (see
"Number reporting" above). Scientific notation removes the cap loss as well:
`1.2345678901234567e-3` stores exactly what `0.0012345678901234567` cannot.

The rule keys on what the parser PRODUCED, and the two edges it draws are separated by what
gets STORED, not by how loudly the result reads back — a stored `NaN` and a stored `inf` both
report as JSON `null`, so the reply cannot tell them apart. An **overflow is not refused**:
`1e400` reads as `inf`, the correctly-rounded IEEE-754 answer for a magnitude past binary64's
top, and the scene file records `inf` — the engine's number for "larger than it can hold", in
the direction the caller asked for, not a different number put in its place. `0e600` reads as
`NaN`, which is not the value, not near it and not in its direction, and that is the
substitution this rule exists to stop. The overflow carries a residual of its own, disclosed
here rather than refused: `inf` is stored but cannot be REPORTED, so the `set` echo and every
later `node get` / `project get` read it as JSON `null`. A literal **below binary64's reach is
refused** anyway — `1e-400` fails exactly as `1e-320` does, although zero is the
correctly-rounded answer there; the coercion cannot tell a true underflow from the engine's −309 cliff without modelling
the parser it asks instead, and a caller who means zero writes `0`. `gda.live_numbers` records the
measurement; `tests/value_projection/test_e2e_write_value_fidelity.py` re-derives it from a real engine on both
channels.

A number nested inside a **Dictionary or Array `--value`** is refused by the same rule, with the
same code and the same message ([#805](https://github.com/aigengame/godot-agent/issues/805)) —
`--value '{"a": 1e-320}'` fails as `uncoercible_value` naming `1e-320`, where before it succeeded
and stored `{"a": 0.0}`. It reaches the rule by a different route, because a container has no
per-element coercion to hook: `JSON.parse_string` gates the text and one atomic `str_to_var(raw)`
builds the value, so by the time a float exists its literal is gone. gda therefore reads the JSON
number literals out of the **raw `--value` text**, and only after the gate has accepted it. Four
consequences follow from that scanning rule, each a deliberate disposition:

- **A string value that looks numeric is NOT refused.** The scan skips the contents of every JSON
  string, honouring escapes, so `--value '{"a": "1e-320"}'` stores the six-character string it
  always did. Nothing is parsed as a float there, so nothing can be destroyed.
- **Keys are never scanned**, for the same reason — every JSON key is a string. `--value
  '{"1e-320": 1.0}'` writes that member unchanged.
- **A Variant constructor is unreachable, so it is not scanned for.** `str_to_var` accepts richer
  syntax than JSON and would build `Vector2(1e-320, 0)` as a zeroed vector — but that text is not
  JSON, so the gate refuses it first (measured: the parse fails with `Expected 'true', 'false', or
  'null', got 'Vector'`). It stays the plain `uncoercible_value` it has always been: the JSON gate
  refused it, not the float parser, so the fidelity note would name a false cause. The same
  attribution rule keeps the note off a `--value` that is not a container at all, and off JSON of
  the OTHER container type (`'[1e-320]'` on a `Dictionary` property fails on the type).
- **A repeated key OVER-refuses, and that is accepted rather than closed.** Godot's JSON keeps the
  LAST value of a duplicate key, so `--value '{"a": 1e-320, "a": 2.0}'` would have stored
  `{"a": 2.0}` faithfully (measured on 4.6.3) — but the scan reads the text, sees the discarded
  literal too, and refuses. Telling a discarded token from a kept one needs the key-and-position
  bookkeeping of a real parser, which is the second opinion about the engine's grammar this scan
  avoids by construction; the over-refusal is in the safe direction — nothing wrong is written —
  and the remedy is to spell the key once.

One caveat on the SCENE round-trip belongs to neither half and was measured while #772 was
written: Godot's scene packer omits a property whose value is not "different" from the property's
own default, and its difference test compares two floats **approximately, as float32**
(`PropertyUtils::is_property_value_different` → `Math::is_equal_approx`, `packed_scene.cpp`). So a
`node set` whose value lands within about `1e-5` of that default is elided from the `.tscn`: on a
property declared `@export var v: float = 0.0`, `--value 1e-6` echoes `1e-6` and a following
`node get` reads `0.0`. That is the packer's elision, not the parser's loss — no coercion refusal
can see it, and `project set` (measured) is unaffected, so it is recorded here rather than
folded into the rule above.

**This qualification is the contract, not a placeholder**
([#805](https://github.com/aigengame/godot-agent/issues/805)): the round-trip claim is published
with the exception named, and gda adds no mechanism to detect or disclose the elision per write.
Four reasons, in the order they bind. It is the ENGINE's serializer policy, applied to any write
the engine makes, and the value gda coerced was exact — so a gda-side refusal or annotation would
blame the wrong stage. gda also cannot ANSWER the question at coercion time without either a
write-then-read-back engine round-trip on every write — disproportionate to a band this narrow,
and out of scope by decision — or a re-implementation of
`PropertyUtils::is_property_value_different`, which would be a second opinion about an engine
function, exactly what the refusal rule above avoids by RUNNING the parser instead of modelling
it. The loss is also not the one the rule exists to stop: the file records nothing, so the
property keeps the default its own source declares, rather than holding a number nobody sent. And
the disclosure would not be free — a result-level field touches the result models, `--schema` and
the README family for a rare, engine-owned band. If that field is ever wanted, it is a separate
issue with its own trigger: a case where an agent acted on the `set` echo and the elision made the
action wrong. Until then the remedy is the one the round-trip claim already names — read it back
with `node get` when the exact stored value matters.

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
`--project`); an empty project is a valid, empty listing, not an error. The walk excludes the same
three kinds of directory `EditorFileSystem::_should_skip_directory` does (#804): the engine's cache
at `res://.godot`, a directory holding a **`project.godot`** — another project inside this one —
and a directory holding a **`.gdignore`**. That is the marker rule, not full parity with the
engine's scan: `_scan_new_dir` additionally drops every hidden entry and every dot-prefixed
directory before it consults that function, and gda deliberately keeps enumerating those (#54,
#712), so `res://.hidden/x.gd` is listed here where the engine never reaches it.

The **cache** test is **lexical**: the child's `res://` PATH is compared against that one path.
Not the directory NAME, so a nested `.godot` is walked — it is usually authored content, and
excluding it hid real scripts from the listing and let `script validate --all` report a valid
aggregate for a project holding an invalid script (#663 review). Sometimes it is not authored
content — a vendored sub-project checked out under `res://` and opened once in an editor keeps an
engine cache of its own, whose import artefacts then counted in `project statistics` and became
`find-unused-resources` candidates. #712 accepted that cost deliberately, because gda cannot tell
the two apart from the directory alone and a false-valid aggregate is the worse failure. **The
marker clause below now covers exactly that case, so the cost is retired** (#804, recorded in the
#808 review): every engine that creates a project data directory writes a `.gdignore` into it —
the editor (`EditorPaths::create`) and gda's own `resource import` pass, whose `created` list
names `res://.godot/.gdignore` — so a nested cache any engine produced holds the marker and is
skipped, and its artefacts leave `statistics`, `find-unused-resources` and the `class_name` index.
The tree AROUND that cache carries no marker and is still walked. What #712's rule was for is
unchanged too: a `.godot` no engine wrote — an addon vendoring a sample tree, a fixture tree —
holds no `.gdignore` and is still walked. One residual stays: the engine reads this location from
`application/config/project_data_dir_name` while gda hardcodes the default, so a project that
renames its data directory has gda walk the renamed cache and exclude a `res://.godot` that is
ordinary content (#804).

The **two markers** are probed on the child directory itself, so what decides is what the
directory HOLDS, not what it is called or how it was reached — a vendored checkout carrying its own
`project.godot` is skipped whether it sits in the tree or is symlinked into it, exactly as the
engine skips it. A `project.godot` is the distinction the cache rule above lacks: the sub-project
declares itself, and its files' own `res://` references mean ITS root, so enumerating them here
gave them the outer root — that is what made `script validate --all` compile a nested project's
scripts against the outer root and report every one of their `res://` preloads as missing (#804,
the gap ADR-0006 recorded). A `.gdignore` is the project's own instruction not to scan. Both probes
are FILE tests, so a sub-directory merely *called* `project.godot` marks nothing. The cost is
two `FileAccess.file_exists` per child DIRECTORY — the two probes the engine's scan pays, on the
same directories, never per file. Hidden entries are still enumerated as promised (#54), which is
the deliberate divergence from the engine's scan stated above.
**This rule governs the four `res://` collectors in
`operations.gd`** — the `script list` walk, the `scene list` walk, and both static-analysis walks
(the extension-filtered one behind `find-references`, `dependencies`, `find-unused-resources` and
the `class_name` index, and the unfiltered one `project statistics` counts with) — so one project
cannot answer two ways. It once did: three of the four compared the directory NAME, so `script
list` reported a script `project statistics` counted as zero (#712). Since #764 the four also
share ONE traversal. The scaffolding around the exclusion rule had been copied per collector, and
the copies drifted a second time — on the extension test, where the `scene list` walk alone
compared case-sensitively — so each collector is now a single line: the shared traversal plus the
acceptance test it passes. What they share is the traversal and the exclusion rule, **not** a file
universe; the two static-analysis walks below still range over different files.

The lexical cache test is the walk's first question, not its only one, because a link renames what
it points at (#760). Comparing the path as written let an alias re-admit exactly what the rule
excludes — `res://nested/.godot` pointing at the root cache made the cache's own scripts and
scenes visible under a second name — and let a cycle (`sub/loop` -> `sub`) be descended until the
OS refused another symlink hop, spelling one `.gd` 33 ways with a deepest path 174 characters
long. The walk therefore **follows a link, as the engine does** — `DirAccess` stats a link entry
so a linked directory lists as a directory, `ResourceLoader` loads through an alias, and gda's own
containment gate already counts a symlinked-in file as part of the project's `res://` namespace
(the containment rule under `script validate` below, implemented in `src/gda/project.py`) — but it
**identifies what it reaches by filesystem identity**, through the engine's own
`DirAccess.is_equivalent` (`st_dev`/`st_ino` on Unix, the volume+file id on Windows), rather than
by the spelling that reached it. Two rules follow:

- the **engine cache is excluded by identity**, so no symlink alias re-admits it: not a directory
  link AT `res://.godot`, not one INTO a subdirectory of it, not a FILE link at a file inside it,
  and not any of those three reached under a second spelling — a parent directory that is itself a
  link. That last shape is why the walk resolves **every component** of a path rather than only its
  last one: a link's target is read against the directory the kernel reads it from, never against
  the spelling the walk arrived by. The file link is a second touch point — it reaches the
  acceptance test without passing the descent decision — so both branches of the walk ask the same
  owner. A **hard** link is outside the rule by construction, not by oversight: the filesystem does
  not report one as a link, so a hard link at a file inside the cache is enumerated like any other
  file. The guarantee is about symlink aliases;
- a linked directory **already on the current descent chain is not re-entered**, so a cycle
  terminates by rule instead of at the OS symlink limit. What the listing enumerates is distinct
  `res://` **paths**, not distinct directories: a directory reachable through several link paths is
  reported under each of them, and mutually linked directories multiply the spellings quickly. The
  answer is a decided, finite one rather than the leftovers of an OS limit — that is the
  guarantee, and it is not "each real directory exactly once".

A refused descent is reported by **omission**: the cycle's paths are simply absent, and no result
field names the link the walk declined to follow. Adding one was considered and declined — it
would widen all four collectors' result contracts for a diagnostic the listing already carries,
and none of the four has a place for a per-path note.

Both rules are about **where** a link leads, not about links: a vendored checkout that physically
lives outside `res://` and is reached through a directory link inside it is walked and enumerated
exactly as an ordinary directory, and its scripts' `class_name`s resolve — including a checkout
that carries an engine cache of its own, which is that checkout's cache and not this project's.
One consequence is kept deliberately — content reachable under two `res://` paths is enumerated
under **both**, since both are real addresses the engine loads. That holds for a FILE link at an
authored script and equally for a DIRECTORY link at authored content already reachable in-tree,
which enumerates everything below it a second time; when a script so reached declares a
`class_name`, the two paths make it `ambiguous_class_name` (ADR-0032), the same report gda gives
any project that declares one name twice.

**Enumeration is not targeting.** Being reached by this walk says what the project can address; it
does not say gda will operate on the path once it is NAMED as an operation's target. That is the
separate question the containment rule under `script validate` below answers, and the two read
differently on purpose — this walk decides by filesystem identity, containment reads the caller's
own spelling. So a linked-in sub-project can be enumerated, counted and indexed here while whether
it may be named as a target is settled there.

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
including a nested `.godot` directory, and never the engine's own `res://.godot` cache, a nested
project's directory, or a `.gdignore`d one.

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
tells the two apart. A target the resolved project **does not own** is **refused before parsing**
with `target_outside_project`, naming both the file and the project, rather than emitting that
false cascade. The check applies to **every** path in a batch, and the first offender in requested
order refuses the whole call (#663): one call has one project, so one outsider makes the requested
set unservable. `--all` carries no paths to check, and needs none: it enumerates through gda's own
`res://` walk, which skips a directory holding a nested `project.godot` exactly as the engine's
editor scan does (`EditorFileSystem::_should_skip_directory`), so it never reaches a file this
gate would refuse by name and the two selectors give the same file the same answer (#804). Before
that, `--all` compiled a nested project's scripts against the outer root and reported the false
cascade for them, where naming the same file explicitly was refused. The two are still different
questions, and the layer boundary between them still stands: the walk decides what the project can
ADDRESS (see the exclusion passage above); this gate decides what a caller may NAME as a target,
from the caller's own spelling (ADR-0006 amendment, #697). What #804 removed is the case where
they disagreed.

"Does not own" is two questions (ADR-0006 amendment, #697). **Containment** follows the engine's
own addressing: a relative path is anchored at the resolved project (not gda's cwd), an
engine-virtual path (`res://`, `user://`, `uid://`) is inside by construction — except a `res://`
spelling that still climbs above the root once canonicalized, which is refused — and a file
reached through a symlink into the project counts as inside, except when a `..` traversal could
cross that symlink, where only the fully resolved location decides. **Ownership** asks whether the
resolved project is the *nearest* `project.godot` at or above the target: a script under a project
**nested inside** the resolved one is contained and still refused, because its own `res://`
references mean the nested root. The walk reads the caller's SPELLING, so a **directory**
symlink at a checkout that carries its own `project.godot` is refused (the marker is in the
spelling) while a **file** symlink at a file inside another project is accepted (the
directories above it are the resolved project's) — one rule, two cases, and only a directory
can carry a marker in. gda names the owner it found and does not adopt it — deriving the
project from the target stays rejected — so pass `--project <owner>` **with the target
respelled relative to that owner**; the refusal states both, because a relative path anchors
at the project and the caller's original spelling would not be found under the new one.
`resource import` asks the same question, for the engine's own reason: its editor scan skips
a nested project's directory, so an asset there cannot be imported into the outer project at
all.
Ownership is checked projectless too: a file that has an owner is refused rather than compiled against nothing, while a
standalone script no project claims is still validated by filesystem path. The refusal carries
`target_location`, `project_root` and `owning_project` as typed `evidence`, each present only when
that refusal knows it.

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
alive and did not finish) — so a slow suite is distinguishable from a hang. Two decisions
govern how to READ that envelope, taken once for every launch-backed channel and recorded
beside ADR-0002's `launch_timeout` registry row (#716 / #717). Its `environment` category
STANDS — the code also fires for a genuinely environmental hang — but it describes how the
run ended, not the host: the remediation reads caller-first, so raise `--timeout` and read
the capture before suspecting the binary or the machine. And the recognized script errors
the diagnostics carry are ADVISORY — they never re-verdict the timeout into an entry-load
code, because the capture is tail-capped and was cut mid-flight, so a recognized line can be
one the run survived. Those errors are delivered TYPED instead (#687, the ADR-0004
amendment), which is what makes the advisory rule workable: the honest verdict ships with
the precise cause attached rather than instead of it.
`--completion-marker <line>` declares a liveness contract — the script prints that line when
its work is done — and a run that hit a recognized error attributable to the entry script, has
not printed the marker, and then goes silent on both streams is ended in seconds and reported
as `script_aborted` with the captured error and phase `aborted_on_error`. A `push_error` never
arms that abort even though it is recognized (#722): it interrupts nothing — execution
continues at the next statement — so a script that reports an invariant and then computes
quietly is alive by construction. It does appear in the run's `diagnostics`, which are advisory:
a project that uses `push_error` as ordinary logging sees entries on runs that still succeed.
`script run` takes the two portable script-path forms — a `res://` address and a
project-relative path — and decides the whole path edge before any launch (ADR-0031). Six
shapes are `invalid_path`: an absolute path, another engine scheme, a leading `~`, a path
naming the project root, an address whose trailing code point Godot's `strip_edges`
removes, and one carrying an engine-log line boundary. A path **escaping above the root**
is the shared containment verdict instead, `target_outside_project` (ADR-0006 amendment,
#697/#763) — the code `script validate` and `resource import` report for the same
condition; it names no root, because this edge is decided ahead of the projectless check.
The resolved project must also OWN the script: a nearer `project.godot` between the two is
the same refusal, naming the owner to pass.

Every `script run` failure that computed evidence also carries it as DATA on the
envelope's optional `evidence` key (#687): the child's own `exit_status` on `--strict`'s
`script_failed`; `elapsed_seconds` / `termination_phase` on the two gda-ended envelopes,
with `timeout_seconds` — the reached ceiling — on the timeout one only (an abort stops
short of its ceiling, so its `--timeout` stays in the message as the caller's own
input); and the parsed `script_errors` on ALL of them — the never-ran
verdicts (`script_not_found` / `script_compile_failed` / `incompatible_script_type`),
`--strict`'s `script_failed`, and both gda-ended envelopes — as the WHOLE parsed list,
not only the error that decided the code. An entry carries the same four keys
(`kind` / `message` / `path` / `line`) it has on a successful run's `diagnostics`, and
the list distinguishes three states: absent (this channel does not parse stderr), `[]`
(parsed, recognized none) and populated. The key itself is omitted, never null, on a
failure that computed none, and the prose above is unchanged: `diagnostics` still
carries the same recognized-error lines and both labelled streams, rendered from the
same single parse.

A successful run also reports the launch's **`User-data placement`** (#850) — where its
`user://` actually was, so a failed persistence write is attributable to the environment
rather than read as a game regression. `engine_data_path` is always present (null only
when the platform's own variable is unset); `user_data_root` and `log_file` appear only
under the global `--user-data-root DIR` — which precedes the subcommand, `gda
--user-data-root DIR script run <path>` — since that is the one case in which the log
outlives the launch, the default being a private temporary file gda removes. Both are
omitted rather than null when they are not facts. The facts come off the shared launch
primitive's `Raw run`, and `script run` is the only channel that publishes them:
`scene preflight`, `export run`, `resource import` and the sentinel commands read the
same run and disclose none. So does a FAILURE of this command — `--strict`'s
`script_failed`, a `launch_timeout` — which keeps its pre-#850 shape: disclosing the
placement there means extending ADR-0004's `Failure evidence` producer set, which is
that ADR's decision and a follow-up, not this one.

The script executes in full, within the trusted-project assumption (ADR-0009).

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
JSON projection, the **same projection** `node get` reports for a node property, at the same full
binary64 precision (#771; see "Number reporting" under [`node`](#node)). Compound values
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
`project get` uses, so a **`set` round-trips through a `get`**: both report the value
`ProjectSettings` now holds, at full binary64 precision (#771). The round-trip is of the STORED
value — what the CLI string coerces to first is the engine's own parser, which lands a
many-digit literal up to 105 doubles away and refuses the literals it would turn into `0.0`
when they do not denote zero, or into `NaN` (#772); see "Number coercion" under [`node`](#node). `set` edits an **existing** setting —
an unknown key is `unknown_setting`, never a silent create, so the type to coerce to is always known.
A value that cannot be coerced to the setting's type is `uncoercible_value` (exit 4, the #55 code,
`project.godot` left untouched); a failed save is `save_failed`.

**Listing settings** (established by #312): `gda project list` enumerates the project's
`ProjectSettings` keys so an agent can **discover** which settings exist — the list half of the
`list → get → set` workflow (`get`/`set` both require you to already know the `section/key`). Each
entry reuses the **same** `{setting, type, value}` projection `project get` reports — so a listed
entry round-trips through `project get`, floats included (#771) — **plus** an `is_default`
boolean: `false` when the key is customized (written in `project.godot`), `true` when it is at
the engine's built-in default. By default the listing is only the project's **customized** settings (small and useful); `--all` widens
it to the engine's built-in defaults too, and `--section <prefix>` restricts it to keys whose name
begins with that `section/` prefix (e.g. `application/`, `display/`) — the two compose. Internal
engine-bookkeeping settings and the non-setting properties the engine's property list also returns
are filtered out, so only real `ProjectSettings` keys appear. Like the rest of the group it requires
a resolved project (`project_not_found`, exit 4, otherwise) and never instantiates a scene.

**Input actions** (established by #380, joypad kinds added by #842): `gda project add-input-action
NAME --key K... --joy-button B... --joy-axis A...` registers an InputMap action under `input/<name>`
— the compound `{deadzone, events}` entry `project set` cannot express — from keyboard and controller
bindings declared in ONE call. Each option is repeatable and **at least one binding of any kind** is
required (a call naming none is a usage error, exit 2). `--key` accepts a Godot key **name** (`J`,
`Space`, `Escape`) or a raw base-10 **keycode**; `--joy-button` a `JoyButton` name (`A`, `Start`,
`DPadLeft`, …) or index; `--joy-axis` an axis DIRECTION spelled `<axis>[:<sign>]` (`LeftX:-`,
`TriggerRight`), since an axis names a whole stick dimension and the sign is what makes it one
binding — an omitted sign is `+`. Joypad names are case- and separator-insensitive (`DPadLeft`,
`dpad_left`, `DPAD_LEFT` are one button), and `gda project add-input-action --help` / `--schema`
list the accepted set; an unresolvable joypad token is a clean `invalid_key` error naming that set
(exit 4, nothing saved), and an unresolvable key name is `invalid_key` naming the token alone.
`--device` pins this call's joypad events to one joypad, `-1`..`2147483647` (the engine's 32-bit
device field — a larger number is refused, since it would wrap to a different joypad); it defaults
to `-1` (`InputMap.ALL_DEVICES`, every joypad) and is set explicitly, because a script-constructed
event starts at device `0` — key events are always `-1` and `--device` never touches them. `--deadzone`
overrides Godot's `0.5` default; `--physical` binds physical keycodes (keyboard position,
layout-independent) instead of layout keycodes. The action is built from real `InputEventKey`,
`InputEventJoypadButton` and `InputEventJoypadMotion` objects — appended in that kind order — and
persisted via `ProjectSettings.save()`, so the serialization is exactly the engine's own `var_to_str`
form — the editor and a running game load it identically to a hand-authored entry, and the action is
immediately driveable by `gda input action NAME` in a live session started afterwards. Adding an existing action
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
| `gda project add-input-action` / `remove-input-action` | Register / unregister an InputMap action (key, joypad button and joypad axis events) |

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
resource loader" (GDA-DF-010). An asset is named as a `res://` address or a filesystem path
inside the project; both go through ADR-0006's one containment check, so a spelling that
still climbs above the root once canonicalized — `\` folded to `/` as the engine folds it —
is `target_outside_project` (#763), while one that collapses back inside (`res://foo/../a.png`)
is accepted, exactly as the script commands accept it. An asset a NESTED `project.godot`
owns gets the same refusal, because the engine's own scan skips that directory
(`EditorFileSystem::_should_skip_directory`) and would return `not_importable` after a
wasted pass. `user://`/`uid://` name no project asset and stay `invalid_params`. `resource import ASSETS... [--dry-run] [--timeout S]` reads
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
stale assets the project-wide pass will re-import (invalid ones excluded; assets under a
nested project's, a `.gdignore`d or a **dot-prefixed** directory excluded too, since the
engine's scan never reaches them, #804; assets with no
sidecar and generated `.uid` files are the engine's to decide, so the real run's `created`
list is the authoritative inventory). This prediction is a SECOND spelling of the walk's
rule, not the walk: it reads the project's files from Python (`Path.rglob`), so it can
never ask `operations.gd`, and the two are held together only by the marker names a test
compares across the seam. Two divergences follow and are stated rather than chased (#808
review): the prediction drops dot-prefixed directories where the walk enumerates them
(that is the engine being modelled, not a drift), and `rglob` does not descend a symlinked
directory where the walk does (#760) — so a stale asset behind a link is not predicted,
which under-promises rather than over-promises and is what the authoritative `created`
list is for. Its cost is unlike the walk's: the ancestors are re-probed per sidecar and
memoized nowhere (2000 sidecars at depth 4 ≈ 16k `stat` calls, 0.11 s measured), and a
cache was declined at that size. Plain `gda script run` never triggers an import
pass. A pass that outruns `--timeout` reports the shared `launch_timeout` envelope with
the pass's own captured output, the ceiling it reached and the elapsed clock — read it the
caller-first way [`script run`](#script) describes: this is the one channel on that shared
builder with a `--timeout` to raise (the sentinel's 60s and the export's 600s are gda's
own, fixed). The ceiling, the clock and the termination phase are also on the envelope's
typed `evidence` key (#687) — the reached bound, the duration and how far the run got, as
numbers rather than sentences; they support choosing the next bound, and do not by
themselves name the cause. The pass executes engine importer code over project content — within the `Trusted
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
directory exclusion, the rule `script list` states above (#712), and since #764 the
traversal itself: the two walks are one recursive walker asked two different acceptance
questions. A shared traversal is not a shared universe — `project statistics` keeps
counting the sidecars and the project file the other walk will never see.

**One graph node per file, whatever a declaration spells it (#774).** One file has many
spellings, and the three graph reads key on the file the engine resolves rather than on the
spelling. Two spellings reach the same file, and each needs its own fold:

- an **alias** of an absolute address — `res://sub/../leaf.tscn` for `res://leaf.tscn` —
  which the engine's `simplify_path` folds;
- a **relative** address, which the engine resolves against the directory of the file that
  DECLARES it. `path="../shared/leaf.tscn"` in `res://scenes/main.tscn` loads
  `res://shared/leaf.tscn`, and `preload("../shared/x.gd")` in `res://scripts/user.gd` loads
  `res://shared/x.gd`. Such a path is anchored to that directory first, then simplified.

Every harvested path is folded this way — an `[ext_resource]` line and a
`preload()`/`load()`/`extends` argument by the rule above; `project.godot`'s main scene and
autoload entries, and the `find-references` target, are absolute already and are only
simplified. So `dependencies` reports the resolved path (never a bare `../…` that names no
file), `find-references` matches whichever side is aliased or relative (a folded declaration
with a canonical query, and the reverse), and `find-unused-resources` never reports a
resource that something references under another spelling. `project statistics` reads
`project.godot` through the same accessor, so the autoload paths it lists are canonical too.

The echoed `target` keeps the caller's own spelling, and each reference's `context` keeps the
line as written — only the matching is folded, so an agent still sees the text it must edit.
A `class_name` target is no path at all. Keying on the raw spelling broke all three reads at
once: `find-unused-resources` listed an instanced scene, which is wrong advice with a
destructive follow-up.

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

**Live serving under `SceneTree.paused` vs `suspended` (#684).** Live operations keep
serving through a PAUSED tree: the `gda harness` sets `PROCESS_MODE_ALWAYS` on itself, so
its serving loop ticks while the game is frozen (#656). There is no equivalent escape for a
SUSPENDED tree — `Node::can_process()` is `is_inside_tree() && !tree->is_suspended() &&
_can_process(is_paused())` (engine `scene/main/node.cpp`), so no process mode ticks at all
while the tree is suspended, the harness included. That would be a dead end rather than a
degraded mode: every live operation stalls until `live_timeout`, input injection cannot
resume the game (it is served by the loop that is not ticking), and gda can neither detect
it from inside the session nor recover it from outside.

**But a project cannot reach that state**, which is what #684 assumed: `SceneTree`'s
`set_suspend`/`is_suspended` are bound to neither GDScript nor ClassDB — verified on Godot
4.6.3, where `get_tree().suspended = true` is an invalid assignment and
`ClassDB.class_has_method("SceneTree", "set_suspend", true)` is `false`. The engine's only
callers are the remote debugger's `scene:suspend_changed` and next-frame messages
(`scene/debugger/scene_debugger.cpp`), driven by the editor Game view's Suspend and step
buttons — an editor-launched game, never a daemon-launched `Engine session`. So this is a
documented engine limit, not a project-authoring hazard and not a `live_timeout` cause to
diagnose: that message names the causes a caller can act on (most often a game that stopped
returning to its main loop, and — leaving the loop running — a multi-frame window outrunning
the fixed bound, whose remedy is fewer frames) and rules out the wrong suspicion (a paused
tree, which the harness serves through). It states neither as fact: gda observed the
silence, not its cause.

**Live number transport (#752).** The live legs carry JSON (ADR-0021), and Godot 4.6.3's
JSON parser and its default writer both change some binary64 values — differently, so the
two directions have separate answers. A real-engine differential corpus
(`tests/live_number_corpus.py`, 96 rows carried to the engine as IEEE-754 bytes) measured
both and is what the policy rests on; `gda.live_numbers` is the authority, and the e2e
re-derives every verdict from a running engine.

- **Results carry full precision, with one residual.** The harness frames every reply
  with Godot's full-precision JSON writer, which preserved 95 of the 96 corpus rows. The
  default writer preserved 41 of
  the 96: it changed 15 and flattened 40 to `0.0`, because it formats
  fixed-point with at most 32 decimals. The one row full precision misses is the
  residual, disclosed rather than fixed — a NEGATIVE ZERO reads back as `0.0`, which the
  engine decides before the precision argument applies. Published in help and in
  `--schema` on every float-bearing live reply, and on which replies those are is
  DERIVED: a walk over the live result models fails a float-bearing field that publishes
  no contract, so a new live float cannot ship silent.
- **A live reply can also carry a number the engine never wrote, and it discloses
  separately.** `perf monitors --frames` computes its `mean` CLI-side and copies each
  budget bound out of the caller's own budget file, so those meet no Godot writer: they
  are exact, and the engine writer's negative-zero residual does not apply to them — a
  `-0.0` bound reads back as `-0.0`. Two published sentences therefore exist, one per
  writer, and which one a field carries is MEASURED rather than declared: a probe drives
  each result-assembling recipe with a reply whose floats are sentinels and sees which
  fields they reach, so a field disclosing the wrong writer fails the guard.
- **Requests are bounded, and the bound is cross-operation.** Godot's `built_in_strtod`
  applies a power of ten it computes as a double, so an applied exponent of −309 or below
  divides by `inf`: 18 of the 96 arrive as `0.0`, including `DBL_MIN`, every subnormal,
  and the ordinary normal `1.2345678901234567e-300`. No decimal spelling avoids it, so
  those values are REFUSED before the send — as is a JSON integer beyond ±(2^53 − 1). The
  rule belongs to the daemon-to-harness LEG, the one Godot's parser reads, so it is
  applied by the base every RELAYED live params model inherits
  (`gda.models.RelayedLiveParams`), covering nested values and both input paths: a usage
  error on argv, `invalid_params` on `--params-json`, decided without a running daemon.
  The ops the daemon answers ITSELF — `diag errors`, `logger tail`, `daemon wait-ready` —
  are deliberately outside it: their numbers cross one Python-to-Python leg and never
  meet that parser, so refusing them would report a loss on a leg the value never
  crosses.
- **The carried residual is disclosed, not refused.** A value the parser CAN construct
  still arrives changed in its low-order bits: 56 of the 96 crossed exactly and 22 changed.
  Ordinary game magnitudes land 1 ULP away; the scientific band reaches 2; and a
  full-precision literal between `1e-4` and `1e-2` is far worse, because the parser keeps
  at most 18 mantissa digits and Python writes fixed notation there — the corpus records
  `0.0012345678901234567` arriving 31 doubles away and `0.00014285714285714284` 105.
  Refusing that band would reject ordinary game values, and preserving it would mean not
  sending a JSON number at all, the bespoke transport ADR-0021 rejected.
- **The headless replies are framed by the same writer since #771.** `ops/operations.gd`
  made the one-argument change this section describes, so a headless `node get` /
  `scene get-exports` / `project list` / `resource get` reports the float the project
  holds and carries the same negative-zero residual (see "Number reporting" under
  [`node`](#node)). The two channels are still documented separately: the live sentences
  are published per-field in help and `--schema` and name the WIRE, a leg a headless
  reply never crosses, so they stay on the live commands rather than moving onto the
  property shape both share. The WRITE sides now agree in substance too: a `--value`
  string is coerced by that same parser, and a literal it turns into `0.0` when the
  literal does not denote zero, or into `NaN` at all, is REFUSED as `uncoercible_value`
  ([#772](https://github.com/aigengame/godot-agent/issues/772)). The two refusals ask the
  question differently for one reason — the wire PREDICTS the outcome because gda spells
  the literal, a write OBSERVES it because the caller does. See "Number coercion" under
  [`node`](#node).

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
  guarantee: Godot 4.6.3 parses some small-magnitude normal values as `0.0`, which is
  why they are refused — see **Live number transport** above for the decided
  cross-operation policy, which is not `game call`'s own
  ([#752](https://github.com/aigengame/godot-agent/issues/752)).
  Standard JSON Schema cannot distinguish
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
  `Input.action_press`/`action_release` against the running `InputMap`. Those are
  two DISJOINT routes and every result names the one it used (`injection_route`,
  #838): `viewport_event` for an `InputEvent` pushed through the viewport, and
  `action_state` for an action — a change to the POLLED action state that builds no
  `InputEvent` and so reaches no `_input` / `_gui_input` / `_unhandled_input`
  handler. gda derives the route CLI-side from the event kind; the phased ops
  (`input tap`, `input mouse-click`, `input sequence`) report it per phase, since
  one sequence can mix the two — a tap targets exactly one of `--key` / `--action`,
  and that target selects the route both its phases take. Drive event-driven UI
  with a key or mouse event and use an action where the game polls
  `Input.is_action_*`: a successful action injection is not evidence that the event
  path works (GDA-DF-048, GDA-DF-075). For mouse
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
  by the daemon-level `live_timeout`. That guard is a fixed 30s wall clock while the
  window is counted in ENGINE frames with no bound of its own, so a window is bounded
  in practice by the game's own frame rate too: a request for more than `30 x fps`
  frames reports `live_timeout` on a game that never stalled. Lower `--frames` rather
  than reading that as a hang — the message says so.
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
  lifetime. With no `--scene` selector, `daemon start` checks the project files for an empty
  `application/run/main_scene` — `live_main_scene_undefined` (LIVE, exit 6) — or a `uid://`
  main scene with no cache under the configured project data directory —
  `live_main_scene_unresolved`, remedy: run the import pass once. Refusal precedes daemon
  or session launch (the engine version probe is allowed), and the daemon repeats the
  check at its launch boundary. A determinate main-scene refusal precedes the
  `--windowed` display check at both sites. This is a conservative precheck: main-scene feature
  overrides, `override.cfg`, a nonempty custom `application/config/project_settings_override` path
  (including feature overrides of that path), or escaped application keys defer to the
  engine; a feature override or an unrecognized boolean value for
  `application/config/use_hidden_project_data_directory` defers only the UID-cache check.
  Deferred cases can still reach Godot's "no main scene" / "could not be resolved from
  UID" native alert on macOS even headless, until the readiness deadline tears down the
  session (#829). An explicit valid `--scene res://<scene>.tscn` avoids main-scene resolution.
  `daemon start --windowed` additionally
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
