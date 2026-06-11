# gda command catalog

A **non-binding roadmap** of the `gda` command surface (ADR-0005). This is a *map, not
a commitment*: it shows the territory each command group will eventually cover so we
can prioritise and so agents can see the shape of the whole — but a command becomes a
commitment only when its slice is picked up as an issue. Commands are delivered one
vertical slice at a time (ADR-0000); this file is refined as we go.

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

Status legend: ✅ shipped · 🔜 Phase-1 candidate · ⏸ Phase-2 (parked). A trailing
issue ref (e.g. `🔜 (#53)`) marks a candidate already committed as an open slice issue.

---

## Meta commands (top-level, ungrouped — ADR-0005)

| Command | Description | Phase | Status |
| --- | --- | --- | --- |
| `gda info` | Report Godot engine version info | 1 | ✅ |
| `gda version` | Report `gda`'s own version | — (local) | 🔜 |
| `gda help` | Usage help | — (local) | ✅ (`--help`) |
| `gda <command> --schema` | Emit a command's input/output JSON Schema (ADR-0004) | — (local) | ✅ (`info` #4; `scene create`/`scene get` #18; `node add`/`node list` #53) |

> `--schema` is a per-command flag, not a command, and ships with **every** domain
> command as a hard gate (ADR-0004). It is local introspection — no Godot process.

---

## Phase 1 — headless domain commands (near-term territory)

### `scene`

| Command | Description | Status |
| --- | --- | --- |
| `gda scene create` | Create a new `.tscn` with a given root node type | ✅ (#18) |
| `gda scene delete` | Delete a scene file | 🔜 (#54) |
| `gda scene get` | Read a scene's structured tree from its file on disk | ✅ (#18) |
| `gda scene list` | Enumerate scenes in the project | 🔜 (#54) |
| `gda scene get-exports` | List `@export` properties declared by a scene's nodes | 🔜 (#58) |

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

| Command | Description | Status |
| --- | --- | --- |
| `gda node add` | Add a node (by type or `class_name` script) into a scene | ✅ (#53) |
| `gda node remove` | Remove a node from a scene | 🔜 (#56) |
| `gda node get` | Read a node's properties | 🔜 (#55) |
| `gda node list` | List nodes in a scene (optionally filtered by type/group) | ✅ (#53) |
| `gda node set` | Set a node property (type-coerced) | 🔜 (#55) |
| `gda node move` | Reparent a node | 🔜 (#56) |
| `gda node duplicate` | Duplicate a node | 🔜 (#56) |
| `gda node connect-signal` / `disconnect-signal` | Wire / unwire a signal to a method | 🔜 (#57) |

### `script`

| Command | Description | Status |
| --- | --- | --- |
| `gda script create` | Create a `.gd`/`.cs` script (template or content) | 🔜 |
| `gda script delete` | Delete a script file | 🔜 |
| `gda script get` | Read script source | 🔜 |
| `gda script list` | Enumerate scripts (with `class_name`/`extends` metadata) | 🔜 |
| `gda script set` | Edit script (search-replace / line-range / full) | 🔜 |
| `gda script attach` | Attach a script to a node in a scene | 🔜 |
| `gda script validate` | Syntax/compile check | 🔜 |

### `project`

| Command | Description | Status |
| --- | --- | --- |
| `gda project info` | Project metadata (name, viewport, Godot version) | 🔜 |
| `gda project get` | Read a project setting by section/key | 🔜 |
| `gda project set` | Modify a project setting (type-aware) | 🔜 |
| `gda project add-autoload` / `remove-autoload` | Register / unregister an autoload singleton | 🔜 |

### `resource`

| Command | Description | Status |
| --- | --- | --- |
| `gda resource create` | Create a `.tres` resource file | 🔜 |
| `gda resource delete` | Delete a resource file | 🔜 |
| `gda resource get` | Load and inspect a resource | 🔜 |
| `gda resource set` | Edit a resource file | 🔜 |
| `gda resource uid` | Resolve UID ↔ resource path (both directions) | 🔜 |

### `export`

| Command | Description | Status |
| --- | --- | --- |
| `gda export list` | Enumerate export presets | 🔜 |
| `gda export run` | Run an export preset via headless CLI | 🔜 |
| `gda export get` | Export-template install status / preset info | 🔜 |

### Asset-file groups (create/edit files; headless)

These create or edit resource files (`.gdshader`, `.tres`) and so are headless.
*Applying* them to a live node is Phase 2.

| Command | Description | Status |
| --- | --- | --- |
| `gda shader create` / `get` / `set` | Create / read / edit a `.gdshader` file | 🔜 |
| `gda theme create` | Create a `.tres` Theme resource | 🔜 |

### Static analysis (read-only, headless)

| Command | Description | Status |
| --- | --- | --- |
| `gda project find-unused-resources` | Find unreferenced resource files | 🔜 |
| `gda project find-references` | Find references to a script/class | 🔜 |
| `gda project dependencies` | Map scene → scene references | 🔜 |
| `gda project statistics` | File/line counts, autoloads, plugins | 🔜 |

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
