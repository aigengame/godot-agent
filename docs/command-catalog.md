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
| `gda <command> --schema` | Emit a command's input/output JSON Schema (ADR-0004) | — (local) |

> `--schema` is a per-command flag, not a command, and ships with **every** domain
> command as a hard gate (ADR-0004). It is local introspection — no Godot process.

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
(ADR-0035): packed arrays project as JSON arrays, and an `Object` as a reference / inline value
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
storage-property listing and does not dump plain script variables. Live set round-trips through
`game get`; its failures are the LIVE-category `live_unknown_property` / `live_uncoercible_value`
(the harness reports them in-band, mapped by the live classifier — see
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
`--project`); an empty project is a valid, empty listing, not an error. `gda script delete`
removes a script file and reports the removed script's `class_name`/`extends` (parsed before
deletion), so the result names the content, not just the path. Delete honors the same addressing
boundary as the rest of the group — only a `.gd` path is removed (a non-`.gd` target is refused
with `invalid_path`, never erasing an arbitrary file), and a missing target is `path_not_found`.
The lifecycle round-trips: `create` → `list` shows it → `delete` → `list` no longer shows it.

**Editing source** (established by #118): `gda script set PATH` edits an **existing** `.gd`
script as **raw text** — it never compiles or loads the script, so editing one never runs
project code (the read trust boundary of #30). It edits only a script that exists; a missing
target is `path_not_found`, never a silent create. Exactly one of three mutually-exclusive
modes is selected at the CLI (a missing or mixed mode is a usage error, exit 2):

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

**Validating** (established by #118): `gda script validate PATH` syntax/compile-checks a `.gd`
script. **Mechanism**: it reads the file text, sets it on a fresh `GDScript`, and calls
`reload()` — `OK` means the script compiles. It compiles the script (`reload` parses and
compiles), but never **instantiates** it, so it does not run the script's instance code. Pass
`--project` when the script `extends` a project `class_name` or preloads a project resource and so
needs project context to compile; a self-contained `extends Node` script validates projectless.

A **`valid=false` result is a successful operation** — `validate` exits `0` with
`{valid: false, error_string, diagnostics}` for a script that does not compile. The op only
*fails* (non-zero, `invalid_path`/`path_not_found`) for op errors (empty/non-`.gd` path, missing
or unreadable file). `diagnostics` are **best-effort advisory** `{line, message}` pairs: the line
and message are not available from any bound API — only from the engine's stderr — so they are
parsed Python-side and may carry only the **first** error. **`column` is always null** on the
standard Godot build (the engine exposes no column for a parse error). `validate` reuses existing
codes only (no new ones).

| Command | Description |
| --- | --- |
| `gda script create` | Create a `.gd` script (template or content) |
| `gda script delete` | Delete a script file |
| `gda script get` | Read script source |
| `gda script list` | Enumerate scripts (with `class_name`/`extends` metadata) |
| `gda script set` | Edit script (search-replace / line-range / full) |
| `gda script attach` | Attach a script to a node in a scene |
| `gda script validate` | Syntax/compile check |

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
(`{type, resource_path}` for a Resource with a `res://` path), an **inline value projection**
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
  `game set` (shipped, #220, extended by #422) read and mutate a running node's live
  properties — the live counterparts of headless `node get` / `node set`, applying the
  **same** value-coercion table and round-tripping `set`→`get`. When a property is
  explicitly named, storage properties are preferred and plain attached-script variables
  are addressable as a fallback; unfiltered `game get` keeps the storage-property listing.
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
- **`input` (input simulation):** runtime input injection into the running game
  (shipped, #221). Single-frame ops `input key <KEY> [--modifiers …] [--released]`,
  `input mouse-click <x> <y> [--button left|right|middle] [--double]` /
  `input mouse-move <x> <y>`, and `input action <NAME> [--release] [--strength F]`
  each inject one event at a frame boundary (ADR-0020); the multi-frame
  `input sequence --events <JSON>` applies a list of events across one selected
  clock and returns as one blocking payload, on the gda harness's time-windowed
  multi-frame base (the same base `perf monitor` uses, #223). Existing sequence
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
  set, mouse-button enum, action strength range (0..1), per-event shape, and the
  sequence's selected-clock window (`max(frame)+1` or `max(physics_frame)+1` ≤ the
  per-window ceiling, the same bound `perf monitor` enforces, #223) are bounded
  **model-side** (ADR-0015), so an
  out-of-contract request is a structured `invalid_params` (or argv usage error)
  before it reaches the harness. The two failures that need the live engine
  to decide are deferred to the harness: a key name the engine cannot resolve to a
  keycode is `live_invalid_key`, an action absent from the running `InputMap` is
  `live_unknown_action`; a sequence event whose type the harness does not recognize
  is `live_invalid_event_spec`.
- **`screen` / capture:** running-game viewport screenshot, multi-frame capture.
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
- **lifecycle (the `daemon` command group):** `gda daemon start` / `stop` / `status`, and `gda daemon
  install` / `uninstall` for the `gda harness` (ADR-0018).

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
