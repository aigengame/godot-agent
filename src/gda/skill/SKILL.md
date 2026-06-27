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

## Structured output & errors

Always pass `--json`. A success is the operation's result object. A failure is

```json
{"error": {"category": "...", "code": "...", "message": "..."}}
```

Branch on the stable `category`/`code` and the **exit code**, never on prose:

| Exit | Meaning |
| ---- | ------- |
| `0`   | success |
| `127` | Godot binary not found |
| `124` | engine timed out |
| `3`   | engine version too old |
| `4`   | operation-reported failure |
| `5`   | could not parse the engine's output |
| `6`   | live operation failed (e.g. `daemon_not_running`) |

## Discovery

- `gda --help` — every group.
- `gda <group> --help` — a group's commands.
- `gda <group> <command> --schema` — one command's input/output/error JSON Schema
  (no Godot spawned).
- `gda schema` — the **whole** surface as one JSON manifest.

## Headless commands (Godot 4.4+, all platforms)

| Group | Commands |
| ----- | -------- |
| `scene` | `create`, `get`, `list`, `get-exports`, `delete` (`.tscn` files) |
| `node` | `add`, `get`, `list`, `set`, `remove`, `duplicate`, `move`, `connect-signal`, `disconnect-signal` (nodes within a scene) |
| `script` | `create`, `get`, `list`, `set`, `delete`, `attach`, `validate` (`.gd` files) |
| `project` | `info`, `get`, `set`, `list`, `add-autoload`, `remove-autoload`, `find-references`, `dependencies`, `find-unused-resources`, `statistics` |
| `resource` | `create`, `get`, `set`, `delete`, `uid` (`.tres` files) |
| `export` | `list`, `get`, `run` (export a preset by name; `--mode` release/debug/pack) |
| `shader` | `create`, `get`, `set` (`.gdshader` files) |
| `theme` | `create` (a loadable `.tres` Theme) |

## Live operations (via the daemon; Godot 4.6+, macOS/Linux)

Prerequisites: run `gda daemon start` first (optionally `--scene <res://...>` to boot a
specific scene instead of the project's main scene); the engine session launches lazily on
the first live op. `screen capture` needs a windowed session
(`gda daemon start --windowed`).

| Group | Commands |
| ----- | -------- |
| `daemon` | `start`, `stop`, `status`, `uninstall` (lifecycle; installs the in-game harness) |
| `game` | `tree`, `get`, `set` (the running game's runtime scene graph) |
| `diag` | `errors` (structured runtime errors with callstacks; survive a crash) |
| `logger` | `tail` (the running game's structured log stream; `--raw` for verbatim lines, `--level <min>` to filter by severity, `--limit N`) |
| `perf` | `monitors`, `monitor` (counters now / a property-or-signal timeline) |
| `input` | `key`, `mouse-click`, `mouse-move`, `action`, `sequence` |
| `screen` | `capture`, `frames` (viewport PNGs; needs `--windowed`) |

## Worked example

Headless: build and export a scene.

```bash
export GDA_GODOT="/path/to/Godot"
gda scene create game/main.tscn --root-type Node2D --project game --json
gda node add  game/main.tscn --type Sprite2D --name Hero --project game --json
gda node set  game/main.tscn --node Hero --property position --value "100,50" --project game --json
gda export run --preset "Linux/X11" --output build/game.zip --project game --json  # --preset: a name from 'gda export list'
```

Live: observe the running game, then tear down.

```bash
gda daemon start --project game --json     # launches the session on the first live op
gda game tree --project game --json        # the runtime scene tree, after _ready
gda daemon stop --project game --json
```

## Tips

- Node paths are relative to the scene root; `.` is the root itself.
- `--value` is coerced to the property's declared Godot type — the same coercion
  for `node set`, `resource set`, `project set`, and live `game set`.
- For large or scripted input, pass one JSON object with `--params-json '{...}'`
  (or `--params-json -` to read it from stdin) instead of individual flags.
- Live ops with no daemon report `daemon_not_running` (exit `6`) and name the
  remedy — start the daemon and retry.
