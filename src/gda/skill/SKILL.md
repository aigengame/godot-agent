---
name: gda
description: Drive the Godot game engine from the command line with `gda`, an agent-first CLI with structured JSON output. Use when building, editing, or inspecting a Godot project — create/edit scenes, nodes, GDScript, resources, shaders, themes; run static analysis; export builds (all headless, no editor) — or to control a running game live (runtime scene tree, input simulation, screenshots, performance, runtime logs/errors) via the gda daemon. Use when the user mentions gda, Godot automation, headless Godot, or asks an agent to make/modify a Godot game. Always pass `--json` and read the single result object; run `gda --help` or `gda schema` to discover the full command surface.
---

`gda` is an agent-first CLI for the Godot engine: every operation is one command
with structured JSON output, so you build and inspect a game without opening the
editor. Two kinds of operation: **headless** (a one-shot `godot --headless` per
call — scenes, scripts, exports) and **live** (against a running game via the
`gda-daemon`).

## Grammar

```
gda <group> <command> [options] --json
```

Exactly one JSON result is printed to **stdout**; all engine noise (warnings,
progress, the engine banner) goes to **stderr**. Read stdout, ignore stderr unless
debugging. `info` / `schema` / `skill` are top-level meta commands (no group).

## Setup

- **Engine** — set `GDA_GODOT` to your Godot binary (or pass `--godot PATH`).
- **Project** — resolved by `--project DIR` → `$GDA_PROJECT` → the current
  directory; the directory must contain `project.godot`. Resolving a project runs
  that project's autoloads at engine startup.
- **Projectless** — meta commands and file-path-only operations run with no
  project; they resolve filesystem paths but not `res://`.
- **Provenance** — `gda --version --json` reports which `gda` is running: its
  version, the executable and interpreter paths, `package_path` (the directory the
  running code was imported from), `install_kind` (`wheel`, `editable`, or
  `unknown` when the install metadata cannot be read — gda will not guess), and,
  for an editable install, the `source` checkout with its Git `revision` and
  `dirty` flag. No Godot is spawned, so it also works where an engine spawn
  fails. Run it first in a long session and keep the output: an editable install
  can change revision under you mid-run, so this is what ties your results to the
  code that produced them. Bare `gda --version` stays one human-readable line.
- **User data (headless runs)** — each headless run's engine log goes to a private
  temporary file, so a read-only Godot application-data directory is not fatal and
  concurrent runs never contend. If a script needs a writable `user://`, pass
  `gda --user-data-root DIR <group> <command>` (or set `$GDA_USER_DATA_ROOT`) to
  place the log and `user://` under `DIR`; a target `gda` cannot create is refused
  as `user_data_unwritable` before the engine starts. Two limits: Godot reads the
  **export templates** from that same directory, so a `release`/`debug`
  `export run` under it reports none installed unless you put templates there —
  `--mode pack` needs no templates and works normally; and Engine sessions are
  unaffected either way — the daemon owns their log.

## Structured output & errors

Always pass `--json`. A success is the operation's result object. A failure is

```json
{"error": {"category": "...", "code": "...", "message": "..."}}
```

Branch on the stable `category`/`code` and the **exit code**, never on prose:

| Exit | Meaning |
| ---- | ------- |
| `0`   | success |
| `127` | environment unusable: `binary_not_found`, `user_data_unwritable`, `live_unsupported_platform`, `live_windowed_unavailable`, `live_windowed_permission_denied` |
| `124` | engine timed out |
| `3`   | engine version too old |
| `4`   | operation-reported failure |
| `5`   | could not parse the engine's output |
| `6`   | live operation failed (e.g. `daemon_not_running`) |

Some commands carry a verdict inside a successful result. For
`gda script validate --json`, read the result's `valid` field: a script that does
not compile exits `0` with no top-level `error`, and reports `valid=false` plus
`error_string` / `diagnostics`. Do not treat exit `0` or the absence of an Error
envelope as a pass for this command. Check the result's `project_root` before you
act on a `valid=false`: it names the project the script was compiled against, and
a verdict full of missing-`res://` errors (plus the type errors derived from them)
usually means the wrong project, not a broken script — `null` means no project was
resolved at all. Pass `--project` for the project that owns the file and re-read
the verdict.

## Discovery

- `gda --help` — every group.
- `gda <group> --help` — a group's commands.
- `gda <group> <command> --schema` — one command's input/output/error JSON Schema
  (no Godot spawned).
- `gda schema` — the **whole** surface as one JSON manifest.

**`--json` placement.** `gda --json <group> <command>` and `gda <group> <command> --json` mean the
same thing — a root `--json` applies to the command it invokes — so either spelling works, as does
both at once. `gda schema --json` is accepted too, and idempotent: the manifest is already JSON.
Two limits: help output is always TEXT (`gda --json --help` returns the same help, never JSON), and
two spellings are still usage errors (exit `2`) — `gda <group> --json` (a group's parser takes only
`--help`; pass the flag to the command) and a bare `gda --json` with no command
(`Missing command.`).

## Headless commands (Godot 4.4+, all platforms)

| Group | Commands |
| ----- | -------- |
| `scene` | `create`, `get`, `list`, `get-exports`, `delete` (`.tscn` files) |
| `node` | `add`, `get`, `list`, `set`, `remove`, `duplicate`, `move`, `connect-signal`, `disconnect-signal` (nodes within a scene) |
| `script` | `create`, `get`, `list`, `set`, `delete`, `attach`, `validate`, `run` (`.gd` files; `run` executes a project script one-shot (address it project-relative or as `res://` — the two portable forms, which `script validate` takes too; `run` alone refuses absolute paths) and passes its `exit_status`/`stdout`/`stderr` through — a non-zero `quit()` is still success, so read `exit_status`, or pass `--strict` to get a `script_failed` failure (exit 4) whose `diagnostics` carries the script's own stdout and stderr; a script that never ran — missing, or a failed parse/compile — always fails) |
| `project` | `info`, `get`, `set`, `list`, `add-autoload`, `remove-autoload`, `add-input-action`, `remove-input-action`, `find-references`, `dependencies`, `find-unused-resources`, `statistics` |
| `resource` | `create`, `get`, `set`, `delete`, `uid` (`.tres` files) |
| `export` | `list`, `get`, `run` (export a preset by name; `--mode` release/debug/pack) |
| `shader` | `create`, `get`, `set` (`.gdshader` files) |
| `theme` | `create` (a loadable `.tres` Theme) |

## Live operations (via the daemon; Godot 4.6+, macOS/Linux)

Prerequisites: run `gda daemon start` first (optionally `--scene <res://...>` to boot a
specific scene instead of the project's main scene); the engine session launches lazily on
the first live op. `screen capture` needs a windowed session
(`gda daemon start --windowed`).

A windowed session needs the host's real desktop session — an on-console GUI login on
macOS, `$DISPLAY` / `$WAYLAND_DISPLAY` on Linux. Over SSH, on a headless CI box, or from
a sandbox that blocks the window server, `daemon start --windowed` refuses before
spawning Godot. Branch on the code, not the sentence:

- `live_windowed_unavailable` — nothing refused the probe and no session is reachable, so
  this host cannot show a window. Skip the rendered check; headless live ops (`game`,
  `perf`, `input`, `diag`, `logger`) still work.
- `live_windowed_permission_denied` — this process is not allowed to even look up the
  window server (e.g. a sandbox). It does NOT mean the host has one: macOS refuses the
  lookup before resolving it, so a broadly-confined process is refused either way. Re-run
  outside the restriction to find out; do not record the machine as display-less on this
  code alone.

A refusal from `gda daemon start --windowed` carries `error.probe` `{name, platform}`
naming the OS call that decided — including when the refusal is relayed from an
already-running daemon's lazy Engine-session launch; only the outer
`{stdout, stderr, exit_code}` transport shape is probe-less.

| Group | Commands |
| ----- | -------- |
| `daemon` | `start`, `stop`, `status`, `uninstall` (lifecycle; installs the in-game harness) |
| `game` | `tree`, `get`, `rect`, `set` (the running game's runtime scene graph) |
| `diag` | `errors` (structured runtime errors with callstacks; survive a crash) |
| `logger` | `tail` (the running game's structured log stream; `--raw` for verbatim lines, `--level <min>` to filter by severity, `--limit N`) |
| `perf` | `monitors`, `monitor` (counters now / a property-or-signal timeline) |
| `input` | `key`, `mouse-click`, `mouse-move`, `action`, `sequence` |
| `screen` | `capture`, `frames` (viewport PNGs; needs `--windowed`) |

For `gda input sequence`, event `frame` offsets are the original
harness/process-frame clock from the harness `_process` loop; they are not Godot's
fixed physics frames. When input timing must map to physics simulation, use
`physics_frame` offsets instead. To hold an action for N physics frames, press at
`{"type":"action","action":"move_right","physics_frame":0}` and release at
`{"type":"action","action":"move_right","release":true,"physics_frame":N}` in the
same sequence. At Godot's default 60 Hz physics clock, N=30 is 0.5 seconds of
physics simulation. Do not mix `frame` and `physics_frame` in one sequence.
For a drag, use a sequence-only mouse-button phase event followed by motion and
release events in the same request, for example
`{"type":"mouse_button","x":10,"y":10,"pressed":true}`, then
`{"type":"mouse_move","x":40,"y":20,"frame":1}`, then
`{"type":"mouse_button","x":40,"y":20,"release":true,"frame":2}`. Motion events
between the press and release carry the held mouse button mask for `_input(event)`
drag handlers.

For `gda input mouse-click`, `gda input mouse-move`, and mouse events inside
`gda input sequence`, the reliable injected coordinate is the mouse event's
`position` (`InputEventMouseButton.position` / `InputEventMouseMotion.position`).
Godot may leave `Viewport.get_mouse_position()` and
`Node2D.get_global_mouse_position()` stale in daemon sessions, so game code that
needs the injected coordinate should read it from the input event.

Live operations keep serving even while `SceneTree.paused` is true, but injected
input still only reaches nodes whose process mode is `PROCESS_MODE_ALWAYS` or
`PROCESS_MODE_WHEN_PAUSED` — a paused game's ordinary handlers will not see it, so
drive resume through a pause-menu-style always-processing handler.

### Structured logging from game code

To emit a record `gda logger tail` reads back as a rich, field-carrying `LogRecord`,
call the harness autoload from your GDScript — but **gate it on the daemon-launched
predicate, not on harness presence**. The harness is present only where it was
installed, and a supported `gda export run` artifact omits it entirely (ADR-0028), so
resolve it by node path and null-check it — never the `GdaHarness` global, which fails
to *parse* when the autoload is absent (a stripped export build, a project before
`gda daemon start`, or after `gda daemon uninstall`), taking the whole script down with
it. Even where it is present, it only captures logs when `gda-daemon` launched the
session. Resolve the node, then gate on `is_daemon_launched()` (a pure read), falling
back to `print()` when it is absent or dormant so no record is lost:

```gdscript
var harness := get_node_or_null("/root/GdaHarness")
if harness != null and harness.is_daemon_launched():
    harness.gda_log("info", "player spawned", {"hp": 100})
else:
    print("player spawned")  # absent or dormant: gda_log() would be a silent no-op
```

## Worked example

Headless: build and export a scene.

```bash
export GDA_GODOT="/path/to/Godot"
gda scene create game/main.tscn --root-type Node2D --project game --json
gda node add  game/main.tscn --type Sprite2D --name Hero --project game --json
gda node set  game/main.tscn --node Hero --property position --value "100,50" --project game --json
gda export run --preset "Linux/X11" --output "$PWD/game/build/game.zip" --project game --json  # --preset: a name from 'gda export list'
```

Live: observe the running game, then tear down.

```bash
gda daemon start --project game --json     # launches the session on the first live op
gda game tree --project game --json        # the runtime scene tree, after _ready
gda daemon stop --project game --json
```

## Scene authoring

Wiring a functional scene means binding scripts, authoring Resources, and setting
typed properties. Reach for the right command — the generic `node set` does **not**
cover scripts, and Resource-typed fields take a `res://` path, not a coerced literal.

For `Control` layout, `node set --property position --value "x,y"` is supported on
free-positioned Controls: gda writes the underlying `offset_left`, `offset_top`,
`offset_right`, and `offset_bottom` while preserving the current size. Direct
children of a `Container` are layout-managed; use those offset properties
explicitly instead. Live `game set --property position` mirrors this policy, while
`game rect` remains a read-only rendered-geometry query.

`scene create` with a `Control-derived` `--root-type` writes a root with zero
anchors and zero offsets, so it does not fill the viewport. A root class with
no intrinsic minimum size (plain `Control`, `Panel`, an empty container)
renders as a zero-size rect at the origin; a class with an intrinsic minimum
(e.g. `Button`, `Label`) renders at that minimum instead — still not the
viewport. Container minimum sizes can keep descendants visible and mask a
zero-size root until `game rect` reports the root, and its child layers, at
their true (possibly zero) size. Fix it by setting the root's `anchor_right`
and `anchor_bottom` to `1` with `node set` (offsets stay `0`); confirm with
`game rect`.

**Attach a script — `script attach`, never `node set --property script`.**
`script attach` is the one authoritative way to bind a `.gd` script to a node: it
verifies the script compiles, checks its base type against the node, and reports any
script it displaced. Setting the `script` property with `node set` is refused with an
actionable `use_script_attach` error that points you back here.
Create any assets a script `preload("res://...")` references before attaching that
script; missing preload targets fail as `missing_dependency` and name the missing path.

```bash
gda script attach game/main.tscn --node Player --script res://player.gd --project game --json
```

**Author and populate a Resource — `resource create` / `resource set`.**
Create a `.tres` (a built-in type, or a project-local `class_name` — resolved without
opening the editor), then set its properties with the same `--value` coercion below:

```bash
gda resource create res://shapes/box.tres --type RectangleShape2D --project game --json
gda resource set    res://shapes/box.tres --property size --value "32,64" --project game --json
```

**Assign a Resource to an Object-typed property — `--value res://….tres`.**
For a property that expects a Resource (sub)class — e.g. a `CollisionShape2D`'s
`shape` — pass the `.tres` path as `--value` to `node set` (or `resource set`). The
path is loaded, type-checked against the property's expected class, and stored as an
external `ext_resource` (not inlined). Pass `--project` so `res://` resolves:

```bash
gda node set game/main.tscn --node Col --property shape --value res://shapes/box.tres --project game --json
```

Its failures are distinct structured codes, never `uncoercible_value`: a non-`res://`
value → `expected_resource_path`; a path that is not a Resource → `not_a_resource`; a
type mismatch → `resource_type_mismatch`; a `class_name`-typed target (not yet
supported) → `unsupported_property_type`.

### `--value` string forms

`--value` is a **string** coerced to the property's declared Godot type. The accepted
forms — several of which are not obvious from `--help`:

- `bool` — `true` / `false` (case-insensitive).
- `int` / `float` — a numeric literal (`7`, `-3`, `1.5`).
- `String` / `StringName` — the string, verbatim.
- `Vector2` / `Vector2i` — **comma-separated** components: `--value "48,72"` →
  `Vector2(48, 72)`. A JSON array (`"[48,72]"`) or a constructor literal
  (`"Vector2(48,72)"`) is **rejected** (`uncoercible_value`).
- `Color` — `#rrggbb` / `#rrggbbaa`, or 3–4 **comma-separated** floats in 0..1:
  `--value "0.2,0.6,1,1"`.
- `Dictionary` — a JSON object string: `--value '{"wine":2}'`. In Dictionary/Array
  JSON values, JSON integer literals stay int and JSON float literals stay float;
  typed containers assign entries through their declared container type.
- `Array` — a JSON array string: `--value '["wine","key"]'`. The same JSON
  integer/float preservation rule applies to array elements.
- An **Object-typed** (Resource) property — a `res://….tres` path, as above.

Whitespace is trimmed for the numeric forms — `bool`, `int` / `float`, the
`Vector2` / `Vector2i` components, and `Color` (hex or list) — but **not** for
`String` / `StringName` (taken verbatim) or the `res://` path (matched literally, so a
leading space fails as `expected_resource_path`). The value-typed forms are shared by
`node set`, `resource set`, `project set`, and live `game set`; the `res://` Resource
assignment is headless-only (`node set` / `resource set`). For live `game get` /
`game set`, an explicitly named attached-script variable is addressable after storage
properties are checked; unfiltered `game get` still lists only storage properties.
Inspect live `game set --json` results' `verified` field: `true` means the observed
read-back value equals the coerced requested value, while `false` means the set
completed but the value read back differently. Treat `verified:false` as a diagnostic
signal for getter-only/no-op variables or edge-triggered/self-consuming controls; use a
domain-specific follow-up `game get` when the side effect matters.

## Tips

- Node paths are relative to the scene root; `.` is the root itself.
- `--value` is coerced to the property's declared Godot type — the same coercion
  for `node set`, `resource set`, `project set`, and live `game set`.
- Create preloaded assets before attaching scripts that reference them; a missing
  `preload("res://...")` target is reported as `missing_dependency`.
- For large or scripted input, pass one JSON object with `--params-json '{...}'`
  (or `--params-json -` to read it from stdin) instead of individual flags.
- Live ops with no daemon report `daemon_not_running` (exit `6`) and name the
  remedy — start the daemon and retry.
