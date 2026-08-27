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
debugging. `info` / `version` / `help` / `schema` / `skill` are top-level meta
commands (no group).

## Setup

- **Engine** — set `GDA_GODOT` to your Godot binary (or pass `--godot PATH`).
- **Project** — resolved by `--project DIR` → `$GDA_PROJECT` → the current
  directory; the directory must contain `project.godot`. Resolving a project runs
  that project's autoloads at engine startup.
- **Projectless** — file-path-only operations run with no project; they resolve
  filesystem paths but not `res://`. Meta commands never *inherit* a project
  (`$GDA_PROJECT`/cwd is ignored, so an invalid one cannot break them); `gda
  info` still accepts an explicit `--project`, validated as anywhere else, while
  the other meta commands take none.
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
| `2`   | gda could not resolve what you asked for: `unknown_command`, `unknown_option` |
| `127` | environment unusable: `binary_not_found`, `user_data_unwritable`, `live_unsupported_platform`, `live_windowed_unavailable`, `live_windowed_permission_denied` |
| `124` | engine timed out |
| `3`   | engine version too old |
| `4`   | operation-reported failure |
| `5`   | could not parse the engine's output |
| `6`   | live operation failed (e.g. `daemon_not_running`) |

A command or option gda does not recognize is reported the same way — an
`unknown_command` / `unknown_option` envelope at exit `2` — and when gda recognizes
the mistake the envelope carries a `hint` naming the invocation to run instead
(`{"error": {"code": "unknown_command", "hint": "gda scene get", …}}`). Re-issue the
`hint`; when there is none, `gda schema` lists every command and
`gda help <command>` describes one.

Some commands carry a verdict inside a successful result. For
`gda script validate --json`, read the result's `valid` field: it is the AGGREGATE
verdict over every script the call validated, `false` as soon as one of them fails.
Each script's own verdict is an entry under `scripts` (`path`, `valid`,
`error_string`, `diagnostics`). A script that does not compile exits `0` with no
top-level `error`, so do not treat exit `0` or the absence of an Error envelope as a
pass for this command. Validate the whole set you changed in ONE call —
`gda script validate a.gd b.gd c.gd --json` uses a single engine launch, and
`--all` validates every script in the project. Check the result's `project_root`
before you act on a `valid=false`: it names the project the scripts were compiled
against, and a verdict full of missing-`res://` errors (plus the type errors derived
from them) usually means the wrong project, not a broken script — `null` means no
project was resolved at all. Pass `--project` for the project that owns the files
and re-read the verdict.

## Discovery

- `gda --help` — every group.
- `gda <group> --help` — a group's commands.
- `gda help <group> <command>` — the same help from the command form; with `--json` it
  comes back as `{command, text}`.
- `gda <group> <command> --schema` — one command's input/output/error JSON Schema
  (no Godot spawned), plus `argv`: how each parameter is written on a command line
  (`kind` positional or option, its `position` or `--option` spelling, whether it is
  `required`, a valueless `flag`, `multiple` — repeat it per value — or a
  `json_value` — one token carrying the value's JSON). Build the command line from
  `argv`; `input_property` links each binding to the input property it fills.
- `gda schema` — the **whole** surface as one JSON manifest, `argv` included.
- `gda version --json` — which `gda` is installed and where from; `gda info` — the
  engine's version.

**`--json` placement.** `gda --json <group> <command>` and `gda <group> <command> --json` mean the
same thing — a root `--json` applies to the command it invokes — so either spelling works, as does
both at once. `gda schema --json` is accepted too, and idempotent: the manifest is already JSON.
Two limits: the `--help` FLAG always renders TEXT (`gda --json --help` returns the same help, never
JSON — use `gda help <command> --json` for a structured payload), and two spellings are still usage
errors (exit `2`) — `gda <group> --json` (a group's parser takes only `--help`; the structured
refusal hints the command form) and a bare `gda --json` with no command (`Missing command.`).

## Headless commands (Godot 4.4+, all platforms)

| Group | Commands |
| ----- | -------- |
| `scene` | `create`, `get`, `list`, `get-exports`, `delete`, `validate`, `preflight` (`.tscn` files; `validate` is the STATIC verdict `get` does not give — a scene loads fine with its script and texture missing, so check dependencies resolve and attached scripts compile before trusting it; invalid exits 0 with `valid: false` plus one problem per problem file — staged: unresolved dependencies suppress the script compile/binding pass, so repair them and rerun for the rest. `preflight` is the DYNAMIC one: it boots the scene headless, waits for `_ready`, and reports `status` (`ready`/`not_ready`/`timeout`) plus the script errors seen during startup — read `started`. Passing `validate` is not "it works": check both) |
| `node` | `add`, `get`, `list`, `set`, `remove`, `duplicate`, `move`, `connect-signal`, `disconnect-signal` (nodes within a scene) |
| `script` | `create`, `get`, `list`, `set`, `delete`, `attach`, `validate`, `run` (`.gd` files; `validate` takes SEVERAL paths at once — one engine launch for the whole batch, one aggregate `valid` plus a per-file entry under `scripts` — or `--all` for every script in the project; `run` executes a project script one-shot (address it project-relative or as `res://` — the two portable forms, which `script validate` takes too; `run` alone refuses absolute paths) and passes its `exit_status`/`stdout`/`stderr` through — `stdout` above 64 KiB is truncated to its leading bytes with the COMPLETE stream spilled to the file named in `stdout_file` (`stdout_bytes`/`stdout_truncated` disclose it; a spill gda cannot write is the typed `stdout_spill_failed`, never an unbounded result), and a non-zero `quit()` is still success, so read `exit_status`, or pass `--strict` to get a `script_failed` failure (exit 4) whose `diagnostics` carries the script's own stdout and stderr; a script that never ran — missing, or a failed parse/compile — always fails; `--timeout <s>` sets the ceiling (default 120) and a run that reaches it fails with `launch_timeout` carrying the captured partial output, the elapsed seconds and a termination phase; add `--completion-marker <line>` naming a line your script prints when its work is done — a caller-declared liveness contract, not a death detector: gda ends the run once it observes a recognized error attributable to the entry script, no marker line yet, and then silence on both streams — `script_aborted` (exit 4) with the captured error, in seconds rather than at the ceiling; declaring the marker asserts the script keeps printing until that line, so have it print progress during quiet stretches longer than ~3s, or omit the marker) |
| `project` | `info`, `get`, `set`, `list`, `add-autoload`, `remove-autoload`, `add-input-action`, `remove-input-action`, `find-references`, `dependencies`, `find-unused-resources`, `statistics` |
| `resource` | `create`, `get`, `set`, `delete`, `uid`, `import` (`.tres` files and project assets; `import` ensures importable assets — PNGs and other files the engine imports — are in the project cache: clean-worktree loading; a script needs no import and reports `not_importable`) |
| `export` | `list`, `get`, `run` (export a preset by name; `--mode` release/debug/pack) |
| `shader` | `create`, `get`, `set` (`.gdshader` files) |
| `theme` | `create` (a loadable `.tres` Theme) |

## Live operations (via the daemon; Godot 4.6+, macOS/Linux)

Prerequisites: run `gda daemon start` first (optionally `--scene <res://...>` to boot a
specific scene instead of the project's main scene); the engine session launches lazily on
the first operation that requires one. To establish the session deterministically, run
`gda daemon wait-ready` (`--timeout` budgets daemon waits and new-work decisions;
a synchronous launch call can delay expiry observation; idempotent while the session is
alive) — success means live reads serve. This matters for the read-only diagnostics: `diag errors` /
`logger tail` never launch a session themselves, so right after `daemon start` they report
`engine_session_not_running` by design — expected, not a defect; run `wait-ready` first.
A `live_timeout` discards the session (its late reply can no longer be attributed), so the
next operation starts a fresh game and the runtime state you had set is gone.
`screen capture` needs a windowed session
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
| `daemon` | `start`, `wait-ready`, `stop`, `status`, `install`, `uninstall` (lifecycle; `start` installs the in-game harness itself, so `install` is only for doing that step deliberately — e.g. to review or commit the `project.godot` change — and `uninstall` reverses it; `wait-ready` establishes the lazily-launched engine session, with `--timeout` shared by its waits and new-work decisions, so a first `diag errors` serves instead of reporting `engine_session_not_running`; `status` reports the last successfully established engine session's `session_id` — the identity a `screen capture` receipt correlates with, minted anew per established session and retained across a failed replacement launch) |
| `game` | `tree`, `get`, `rect`, `set`, `call` (the running game's runtime scene graph; `get --texture-digest` opts a read into content digests for path-less `Texture2D` values. `call --method NAME [--args JSON]` invokes a method named by the `GDA_CALLABLE` declaration resolved from the node's attached script along its base chain — use it for a debug/state contract exposed as a method rather than a property. gda calls nothing undeclared, so an undeclared-but-present method is `live_method_not_allowlisted` and its message names the declared set; a missing one is `live_unknown_method`, and arguments the declared parameters cannot take (wrong count, a type the engine would not convert, a typed `Array[int]` parameter) are `live_invalid_call_args`, refused before the call. The live parser materializes every JSON number as float. `NaN`/`Infinity` are refused; RFC JSON excludes them, although some in-memory schema validators accept them as numbers. Finite floats do not inherit the integer bound, but Godot 4.6.3 can change some small-magnitude normal or subnormal values to `0.0` on input or result serialization (#752). JSON integer values beyond ±(2^53−1) are refused CLI-side because the wire can change them. Standard JSON Schema cannot distinguish an exponent-form float from the equal integer, so the params model enforces the integer-token limit at execution. LIMIT: gda CANNOT verify a declared method has no side effects — the constant records the project's own read-only assertion, and what gda guarantees is only that no undeclared method is called. GDScript forbids redeclaring a base class's constant, so an opted-in inheritance chain has at most one declaration owner; a base owner covers its subclasses and need not define every method it names) |
| `diag` | `errors` (structured runtime errors with callstacks; survive a crash) |
| `logger` | `tail` (the running game's structured log stream; `--raw` for verbatim lines, `--level <min>` to filter by severity, `--limit N`) |
| `perf` | `monitors`, `monitor` (counters: a one-frame snapshot, or with `--frames` a bounded window with statistics and optional `--budget` verdicts / a per-node timeline) |
| `input` | `key`, `mouse-click`, `mouse-move`, `action`, `tap`, `sequence` |
| `screen` | `capture`, `frames` (viewport PNGs; needs `--windowed`. `frames --summary` returns the compact aggregate — directory, filename pattern, frame size, total bytes — instead of the per-frame list, so a large capture's envelope stays small; every frame is still written. `capture --await-node/--await-property/--await-value [--await-frames] [--await-events]` is the predicate-gated form: it fires on the first frame boundary where the property equals the value, optionally injecting input inside the same window — use it for short transients instead of a separate input + capture. The observed property and the pixels belong to the same COMPLETED frame; a value overwritten before its frame completes is never observable, an injected event's effect is observable from the next boundary, and a declared event that fails makes the capture that typed failure. Every `capture` result carries a `receipt` binding the image to its capture event — `session_id` correlating with `daemon status`, the LAUNCHED scene's path and header uid (uid null for gda-authored scenes), the engine frame, the gated capture's observed echo, and the written file's SHA-256 — so a plain capture needs no local hashing, and a gated capture's complete evidence is the receipt plus the sibling `predicate` report) |

For a UI activation, use the gesture commands, not a lone event. Godot activates a
`Button` on the RELEASE, so a bare press never emits `pressed`; and a focused UI
does not advance when the press and the release land on the same process frame.
`gda input mouse-click` injects the whole gesture — the initial move, the press,
and the release, one per process frame — and `gda input tap --key K` /
`gda input tap --action NAME` presses at frame 0, holds `--hold-frames` (default 2)
process frames, releases, then runs `--settle-frames` (default 2) more frames so
the game observes the release before the op returns. Both report the injected
`phases` and the focused Control before/after as activation evidence. Reach for
`gda input key <KEY> --released` or a `mouse_button` sequence phase only when a
single edge is the point (a hold, a drag).

`gda input sequence` events are a discriminated union on `type`: each kind accepts
only its own fields, and `gda input sequence --schema` publishes them per kind. The
press/release spelling differs by kind — `pressed` belongs to `mouse_button` alone,
an `action` releases with `release`, a `key` with `released` — so read the kind's
variant rather than assuming a shared shape.

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
gda daemon start --project game --json     # the session launches on the first op that needs one
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
