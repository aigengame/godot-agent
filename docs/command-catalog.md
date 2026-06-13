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
- **Phase 2 (live)** — requires an already-running engine/editor to observe or mutate
  in-place state (runtime scene tree, runtime properties, input simulation, play/stop,
  screenshots of a running game, editor diagnostics). Served by `gda-daemon`. **Parked.**

This catalog does **not** carry a per-command status column — that would duplicate, and
drift from, the issue tracker. For the live backlog (what is committed, in flight, and
done) open the **Phase 1 — headless operations** milestone. Inline references to issues
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
node under the substitute type. Mutating node commands detect both and refuse with the
registered `missing_dependency` error (exit 4), leaving the file untouched. Related trust boundary: instantiating executes `_init`
of scripts already attached in the scene (#62) — treat headless mutation of an untrusted scene
as running its code.

**Type resolution** (sharpened by #65): `node add --type` resolves a built-in `Node` class
first, then a `class_name` from the project's global class list (which exists only after a
project import — pass `--project`). A type that resolves to neither is refused with
`invalid_node_type`. A `class_name` that is still registered but whose script has broken since
the scan — it fails to load, no longer compiles, or its `_init` requires constructor
arguments — is a script problem, not an unknown type, and is refused with the distinct
`uninstantiable_script` error (exit 4) naming the script: repair the script (or re-import),
don't change the type name. Either way the scene file is left untouched.

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
| `Vector2` | two comma-separated floats: `x,y` (e.g. `10,20`) | `[x, y]` |
| `Vector2i` | two comma-separated integers: `x,y` | `[x, y]` |
| `Color` | `#rrggbb` / `#rrggbbaa`, or 3–4 comma-separated floats in 0..1 (`r,g,b[,a]`) | `[r, g, b, a]` |

Whitespace around a value or a component is tolerated. A property of any other type is still
reported by `node get` (its value degrades to a string projection), but `node set` cannot coerce
to it yet and refuses with `uncoercible_value` — the coercible set grows as later slices need it.

| Command | Description |
| --- | --- |
| `gda node add` | Add a node (by type or `class_name` script) into a scene |
| `gda node remove` | Remove a node from a scene |
| `gda node get` | Read a node's properties (typed JSON) |
| `gda node list` | List nodes in a scene (optionally filtered by type/group) |
| `gda node set` | Set a node property (type-coerced) |
| `gda node move` | Reparent a node |
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
> non-`.gd` path is refused as `invalid_path` rather than half-supported as opaque text.

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

| Command | Description |
| --- | --- |
| `gda project info` | Project metadata (name, viewport, Godot version) |
| `gda project get` | Read a project setting by section/key |
| `gda project set` | Modify a project setting (type-aware) |
| `gda project add-autoload` / `remove-autoload` | Register / unregister an autoload singleton |

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

## Phase 2 — live domain commands (parked, served by `gda-daemon`)

Listed coarsely; enumerated when Phase 2 (PRD #6) is unparked. All require a running
engine/editor and so cannot be a one-shot headless call.

- **`scene` (live):** `play`, `stop`, live `get` of the running/edited scene tree, `save` the open scene, instance a packed scene into the open scene.
- **`node` (live):** runtime property `get`/`set`, anchor presets, group membership on the live tree.
- **runtime introspection:** running-game scene tree, performance monitors, autoload state, frame capture, property monitoring.
- **input simulation:** key / mouse / action / sequence injection into a running game.
- **diagnostics & capture:** editor errors, output log, editor & game screenshots, screenshot diff.
- **editor utilities:** run editor script, reload plugin/project, list signals.
- **testing harness:** run scenario, assert node/screen state, stress test, recording/replay.
- **`input-map` (live):** `get`/`set` InputMap actions on a running engine.

---

## Deferred / not yet triaged

Seeded from `godot-mcp-pro` but not yet placed into a phase or group above — revisit
when relevant: **animation** (AnimationPlayer / AnimationTree state machines),
**tilemap**, **physics/collision**, **audio buses**, **particles**, **3D scene**
(mesh/lighting/camera/environment/gridmap), **navigation** (regions/agents/baking),
**Android deploy**. Most mutate scene/resource files and are likely Phase-1-able, but
each needs its own slice-level design before it becomes a commitment.
