# godot-agent (`gda`): Godot AI Agent CLI, Skill, and MCP Server

![godot-agent title image](https://raw.githubusercontent.com/aigengame/godot-agent/main/assets/godot-agent-title.png)

**Read this in:** [简体中文](docs/README.zh-CN.md) · [Español](docs/README.es.md) · [日本語](docs/README.ja.md)

> **`gda` gives your AI coding agent — or your shell scripts and CI — structured, machine-readable
> control of the [Godot Engine](https://godotengine.org).** Create scenes, edit nodes & scripts,
> and export builds headlessly, then drive a *running* game live: runtime tree, input,
> screenshots, performance — one command surface, three ways in.

[![pre-1.0](https://img.shields.io/badge/status-pre--1.0-orange)](https://pypi.org/project/gda/)
[![CI](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml?query=branch%3Amain+event%3Apush)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![Godot](https://img.shields.io/badge/godot-4.4%2B%20(live%204.6%2B)-478CBF)](https://godotengine.org)
[![Platform](https://img.shields.io/badge/platform-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-lightgrey)](#how-it-works)
[![MCP](https://img.shields.io/badge/MCP-server-000)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

AI agents are great at writing GDScript and terrible at *seeing what happened*. `gda`
closes that loop: your agent issues one operation and gets back a single clean JSON
result it can act on — never engine logs it has to scrape. It runs in **two modes**:

- **Headless** — one-shot and stateless, zero setup. No editor plugin, no daemon,
  nothing to install in your project. Create and edit scenes, nodes, scripts, resources,
  shaders and themes; analyze the project; export builds.
- **Live** — drive a *running* game through a background daemon for everything only a
  live engine can do: read the runtime scene tree, get/set runtime properties, simulate
  input, capture screenshots, and sample performance.

> `gda` is **pre-1.0**: every command works end-to-end today, but the CLI surface may
> still change before 1.0.

---

## Contents

- [Why `gda`?](#why-gda)
- [Capabilities at a glance](#capabilities-at-a-glance)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Choose your integration](#choose-your-integration)
- [How it works](#how-it-works)
- [Command reference](#command-reference)
- [Configuration](#configuration)
- [Contributing](#contributing)
- [License](#license)

---

## Why `gda`?

- **🤖 Structured output, built for agents.** Every command emits **exactly one** JSON
  object on stdout (`--json`); engine banners, warnings and `print()` go to stderr. Your
  agent parses one result, not a wall of logs.
- **📐 Typed & self-describing.** Every command's input and output are typed models that
  also back a machine-readable `--schema` (a JSON-Schema contract), so an agent can
  discover and validate the whole surface programmatically instead of guessing.
- **🔀 CLI, Skill, and MCP — your agent's choice.** Drive Godot from a terminal or CI with the
  raw `gda` CLI, hand your agent a bundled **Skill** (`gda skill`) that teaches it how and when
  to use the CLI, or expose the same operations as **MCP** tools (`gda-mcp`, generated from the
  CLI's own schemas). One command surface, three ways in — pick whatever your agent supports.
- **🧩 Godot-native commands.** Grouped by Godot object (`gda scene create`,
  `gda node add`, `gda game set`) with a tiny, consistent verb vocabulary — zero learning
  curve if you already know Godot.
- **⚡ Headless by default, live when you need it.** Headless operations need no daemon
  and no editor — just a Godot binary. Live operations add real-time control of a running
  game over a Unix-domain-socket daemon, addressed by the same CLI grammar.
- **🛡️ Fails loudly, never silently.** A missing engine fails at once and a hung one at a
  timeout; both map to a **stable non-zero exit code** plus an Error envelope carrying the
  failure's category, code, and any typed evidence it computed — so a shell or agent branches
  on the failure instead of parsing prose. A command `gda` does not recognize is refused the
  same way, with a `hint` naming the invocation to use instead.

---

## Capabilities at a glance

| What you need | Reach for |
| --- | --- |
| Build project files from an agent or script | `scene` / `node` / `script` / `resource` / `shader` / `theme` — create & edit headlessly |
| Parse results instead of scraping engine logs | `--json` (one clean object) and `--schema` (a JSON-Schema contract) |
| Hand an agent Godot tools | the bundled **Skill** (`gda skill`) or the **`gda-mcp`** server |
| Automate CI, exports, and project analysis | headless commands — no editor, no plugin, just a Godot binary |
| Debug a *running* game's runtime behavior | `gda daemon start`, then `game` / `diag` / `logger` / `perf` / `input` / `screen` |

---

## Installation

**Requirements:** Python 3.13+, and a [Godot](https://godotengine.org) binary — 4.4+ for
headless commands, 4.6+ on macOS/Linux for live (daemon) commands.

Install the CLI from PyPI onto your `PATH`:

```bash
uv tool install gda      # or: pipx install gda
gda --help
```

<details>
<summary>Other ways to install (pip, from source)</summary>

Into an existing environment:

```bash
pip install gda
```

From source (for development or unreleased changes):

```bash
git clone https://github.com/aigengame/godot-agent.git
cd godot-agent
uv sync                  # create the environment + install dependencies
uv run gda --help
```
</details>

---

## Quick start

**Point `gda` at your Godot binary**, then ask the engine its version — no project needed:

```bash
export GDA_GODOT="/path/to/Godot"   # or pass --godot to any command
gda info --json
# {"major":4,"minor":6,"patch":3,"status":"stable","string":"4.6.3-stable (official)",…}
```

stdout is always clean JSON you can pipe; all engine and script diagnostics go to stderr:

```bash
gda info --json | jq .major   # → 4
```

**Build a scene headlessly.** Point `gda` at a Godot project (a directory with `project.godot`)
once; relative paths then resolve *inside* it, and nodes are addressed by their path relative to
the scene root:

```bash
export GDA_PROJECT="/path/to/your/godot-project"   # or pass --project to any command
gda scene create scenes/main.tscn --root-type Node2D --json
gda node add  scenes/main.tscn --type Sprite2D --name Hero --json
gda node set  scenes/main.tscn --node Hero --property position --value 10,20 --json
gda scene get scenes/main.tscn --json
# {"path":"scenes/main.tscn","root":{"name":"main","type":"Node2D","children":[{"name":"Hero",…}]}}
```

> No project? `gda` still runs **projectless** on plain filesystem paths (relative to your current
> directory) — only `res://` resolution needs a project. See [Configuration](#configuration).

**Drive a *running* game live.** Live ops run the project's **main scene**, so point it at the
one you just built via Godot's `application/run/main_scene` project setting (the editor's
*Application → Run → Main Scene*), then start the daemon (macOS/Linux, Godot 4.6+):

```bash
gda project set application/run/main_scene --value res://scenes/main.tscn --json  # a Godot project setting key
gda daemon start             # start the daemon for $GDA_PROJECT (installs the in-game harness)
gda game tree --json         # the runtime scene tree, after _ready
gda perf monitors --json     # live engine counters: fps, memory, node count
gda daemon stop
```

(`gda screen capture` works live too, but needs a windowed session — start the daemon
with `gda daemon start --windowed`.)

---

## Choose your integration

`gda` exposes the **same command surface** three ways — pick whichever your agent (or you) supports:

| Entry point | Best for | How |
| --- | --- | --- |
| **CLI** (`gda`) | humans, shell scripts, CI, and agents that can run commands | `gda <group> <command> --json` |
| **Skill** (`gda skill`) | coding agents that support Agent Skills and prefer a token-light CLI workflow | print/install `SKILL.md` (below) |
| **MCP** (`gda-mcp`) | agents that call tools over the Model Context Protocol | run the stdio server (below) |

### Use it as a Skill

`gda` ships an agent **Skill** — a `SKILL.md` that teaches an AI agent *how and when* to drive
Godot from the CLI. It's the lightest way in (no server to register), bundled in the package and
version-locked to your install. Print it, or install it into your agent's skills directory:

```bash
gda skill                                              # print SKILL.md (redirect it anywhere)
gda skill --install --provider claude --scope user     # resolve a known agent's skills dir
gda skill --install --dir ~/.claude/skills/gda         # …or give the directory yourself
```

The [skill recipes](docs/gda-skill.md) list each agent's skills directory. Or fetch the same
file straight from the repo — you still install `gda`, since the Skill drives it:

```bash
curl --create-dirs -o ~/.claude/skills/gda/SKILL.md \
  https://raw.githubusercontent.com/aigengame/godot-agent/main/src/gda/skill/SKILL.md
```

### Use it as an MCP server

`gda` ships a stdio [MCP](https://modelcontextprotocol.io) server behind a `[mcp]` extra,
so any MCP agent (Claude Code, Codex, Cursor, …) can drive Godot. Try it with no install:

```bash
uvx --from "gda[mcp]" gda-mcp
```

The server resolves two pieces of context — which Godot **project** to drive and which Godot
**binary** to run (MCP can't pass per-call flags):

- **Project** — set `GDA_PROJECT`. Without it, `gda-mcp` uses the workspace **roots** the client
  sends (the folder you have open) — but the MCP 2026-07-28 revision deprecates roots, so pinning
  `GDA_PROJECT` is the setup that keeps working. See [Configuration](#configuration).
- **Engine** — set `GDA_GODOT` to your Godot binary, e.g. `"GDA_GODOT": "/path/to/Godot"`.

`gda-mcp` accepts both protocol eras — the pre-2026 MCP protocol and the **2026-07-28 revision** —
but not with the same project resolution: a pre-2026 client still sends roots, a client on the new
revision does not, so it resolves from `GDA_PROJECT` or the server's cwd. Pin `GDA_PROJECT` before
your client moves. On the new revision `gda-mcp` also marks `tools/list` cacheable (1-hour TTL).

#### Register with Coding Agents

<details>
<summary>Claude Code</summary>

Project scope, `.mcp.json` at the repo root (auto-detects the project via `roots`):

```json
{
  "mcpServers": {
    "gda-mcp": {
      "command": "uvx",
      "args": ["--from", "gda[mcp]", "gda-mcp"]
    }
  }
}
```

User scope (every project) — the CLI, which writes `~/.claude.json`:

```bash
claude mcp add --scope user gda-mcp -- uvx --from "gda[mcp]" gda-mcp
```

</details>

<details>
<summary>Codex</summary>

Project scope, `.codex/config.toml` at the repo root (the project must be trusted):

```toml
[mcp_servers.gda-mcp]
command = "uvx"
args = ["--from", "gda[mcp]", "gda-mcp"]

[mcp_servers.gda-mcp.env]
GDA_PROJECT = "/absolute/path/to/your/godot/project"
```

User scope (available everywhere, but pinned to one project) — the same table in
`~/.codex/config.toml`, or add it with the CLI. Codex has no workspace variable, so
`GDA_PROJECT` is an absolute path; use project scope if you work across several projects:

```bash
codex mcp add gda-mcp --env GDA_PROJECT=/absolute/path/to/your/godot/project -- \
  uvx --from "gda[mcp]" gda-mcp
```

</details>

<details>
<summary>Cursor</summary>

Project scope, `.cursor/mcp.json` at the repo root (`${workspaceFolder}`
tracks the open project):

```json
{
  "mcpServers": {
    "gda-mcp": {
      "type": "stdio",
      "command": "/path/to/uvx",
      "args": ["--from", "gda[mcp]", "gda-mcp"],
      "env": {
        "GDA_PROJECT": "${workspaceFolder}"
      }
    }
  }
}
```

User scope (available everywhere, but pinned to one project) — the same config in
`~/.cursor/mcp.json` with `GDA_PROJECT` set to an absolute path (`${workspaceFolder}` only
works in project scope; use project scope for several projects). Cursor has no `mcp add`
command — register via the JSON above or the Settings → MCP UI.

> Cursor is GUI-launched with a minimal `PATH`, so a bare `uvx` may not resolve — hence the
> absolute `command` above; fill it with the output of `which uvx`. Full recipes — PATH
> injection, Claude Desktop, user vs project scope, per-agent project pinning — are in the
> [registration recipes](docs/gda-mcp-registration.md).
</details>

---

## How it works

`gda` is three components serving operations in two modes:

| Component        | Role                                                                  |
| ---------------- | --------------------------------------------------------------------- |
| **`gda`**        | The agent-facing CLI — exposes Godot with structured `--json` output. |
| **`gda-mcp`**    | An MCP server exposing the same operations as tools, from `--schema`. |
| **`gda-daemon`** | A per-project process supervising a running game for live operations. |

- **Headless operations** run one-shot — no daemon, nothing to install (create a scene, edit
  a script, export, analyze).
- **Live operations** require a running game — `gda-daemon` launches it, injects an inert
  in-game harness, and brokers requests over a Unix domain socket (runtime tree, input,
  screenshots, performance, diagnostics).

The in-game harness `gda-daemon` injects is **dev-only**: `gda export run` strips it from the
artifact entirely, and built any other way (editor GUI, raw `godot --export`) it still
self-disables in the exported game — so a shipped game never *runs* anything daemon-related
(and via `gda export run`, doesn't even carry it).

**Platform & version support:**

| Mode | Godot | Platforms |
| ---- | ----- | --------- |
| **Headless** | 4.4+ | macOS · Linux · Windows¹ |
| **Live** (via `gda-daemon`) | 4.6+ | macOS · Linux² |

¹ Headless is cross-platform by design (one-shot processes, no platform-specific
  dependency) — Windows keeps the full headless surface, though CI does not exercise it yet.
² Live operations use Unix domain sockets, so Windows is not supported yet.

---

## Command reference

`gda` commands are **grouped by Godot domain object** and use a small, consistent verb
vocabulary, so the same verb means the same thing in every group:

| Verb                | Meaning                                                           |
| ------------------- | ----------------------------------------------------------------- |
| `create` / `delete` | Make / remove a **standalone** entity (scene, script, resource).  |
| `add` / `remove`    | Add / remove a **sub-entity** within a container (node → scene).  |
| `get` / `list`      | Read one entity / enumerate many.                                 |
| `set`               | Mutate a property.                                                |
| domain verbs        | `play`, `run`, `export`, `import`, … kept with their natural meaning. |

Every command supports `--json` and `--schema`. Commands that read or mutate a `res://` path
resolve a [project context](#configuration). Run `gda <group> <command> --help` for full
flags — `gda --help` is the authoritative list of what is installed.

**New here?** A good first path: `gda info` → `gda scene create` → `gda node add` →
`gda script validate` → `gda export run`; then go live with `gda daemon start` → `gda game tree`.

**Meta** — about `gda` / the engine itself

| Command | What it does |
| ------- | ------------ |
| `gda info`   | Report the Godot engine version. |
| `gda version` | Report which `gda` is installed and where it came from (`--json` adds the install provenance). |
| `gda help`   | Show a command's help (`gda help scene get`) or the whole CLI's. |
| `gda schema` | Emit the whole command surface as one machine-readable JSON manifest. |
| `gda skill`  | Emit or install the bundled Agent Skill (`SKILL.md`) that teaches an agent how to drive `gda`. |

### Headless commands — Godot 4.4+, all platforms

**`scene`** — scene files (`.tscn`)

| Command | What it does |
| ------- | ------------ |
| `scene create` | Create a new `.tscn` with the given root node type. |
| `scene get` | Read a scene and report its structured node tree. |
| `scene list` | Enumerate the `.tscn` scenes in the resolved project. |
| `scene get-exports` | List the `@export` properties a scene's nodes' scripts declare. |
| `scene delete` | Delete a scene file and report what was removed. |
| `scene validate` | Check a scene **statically** — dependencies resolve and bound scripts compile, sub-scenes included — without instantiating it (the project's autoloads still start, as on every `--project` command); a broken scene is a verdict (`valid: false`, exit `0`), not an error. |
| `scene preflight` | Check a scene **dynamically** — boot it headless, run `_ready`, and report `started` plus the script errors seen; a failed start is a verdict, not an error. |

Run both — `scene get` reads a scene with its script missing as healthy, only `validate`
names the file, and only `preflight` catches a first-frame failure.

**`node`** — nodes within a scene file

| Command | What it does |
| ------- | ------------ |
| `node add` | Add a node under a parent, optionally at `--index`: a built-in type, a `class_name` script, or `--instance` to compose another scene as an instanced child. |
| `node get` | Read a node's properties (by node path) as typed JSON. |
| `node list` | List a scene's node tree with each node's path relative to the root. |
| `node set` | Set a node property, coercing the value to its declared Godot type. On a `Control`, `position` writes the four offsets; a `Container`'s children are layout-managed, so set their offsets directly. |
| `node remove` | Remove a node (and its subtree) by node path. |
| `node duplicate` | Duplicate a node (and its subtree) under its parent. |
| `node move` | Reparent a node (and its subtree) under a new parent, or reorder it with `--index`. |
| `node connect-signal` | Wire a source node's signal to a target node's method. |
| `node disconnect-signal` | Unwire an existing signal→method connection. |

**`script`** — GDScript files (`.gd`)

| Command | What it does |
| ------- | ------------ |
| `script create` | Create a new `.gd` script from a template or verbatim `--content`. |
| `script get` | Read a script's source plus its `class_name` / `extends` metadata. |
| `script list` | Enumerate the `.gd` scripts in the resolved project. |
| `script set` | Edit a script via search-replace, line-range, or full overwrite. |
| `script delete` | Delete a script file and report what was removed. |
| `script attach` | Attach a `.gd` script to a node (by node path) in a scene. |
| `script validate` | Compile-check `.gd` scripts — several PATHs in one engine launch, or `--all` for the whole project — reporting one aggregate `valid` plus a per-script entry under `scripts`; a failing script is a verdict (`valid: false`, exit `0`), not an error. |
| `script run` | Run a project script headless as a one-shot entry point, under `--timeout`. Its `exit_status` and `stderr` pass straight through; `stdout` is inline up to 64 KiB and, when truncated, the complete stdout is written to the file the result names — and a non-zero `quit()` is data, not a failure, unless you pass `--strict`. |

**`project`** — the project as a whole (settings, autoloads, static analysis)

| Command | What it does |
| ------- | ------------ |
| `project info` | Report project metadata (name, main scene, viewport, engine version). |
| `project get` | Read a single project setting by section/key as typed JSON. |
| `project list` | List the project's settings keys (customized by default; `--all` adds engine defaults, `--section` filters by prefix). |
| `project set` | Set a project setting, coercing the value to its declared type. |
| `project add-autoload` | Register an autoload singleton (name → script/scene). |
| `project remove-autoload` | Unregister an autoload singleton by name. |
| `project add-input-action` | Register an InputMap action bound to keys (`--key` name or keycode, `--deadzone`, `--physical`). |
| `project remove-input-action` | Unregister an InputMap action by name. |
| `project find-references` | Find every project file that references a given resource. |
| `project dependencies` | Map each scene/resource to the resources it depends on. |
| `project find-unused-resources` | Find resource files that nothing references. |
| `project statistics` | Report the project's file/line counts, autoloads, and more. |

**`resource`** — resource files (`.tres`) and the project's imported assets

| Command | What it does |
| ------- | ------------ |
| `resource create` | Create a new `.tres` resource of the given type. |
| `resource get` | Read a `.tres` resource's properties as typed JSON. |
| `resource set` | Set a `.tres` property, coercing the value to its declared type. |
| `resource delete` | Delete a `.tres` resource file and report what was removed. |
| `resource uid` | Resolve a resource UID ↔ its `res://` path in both directions. |
| `resource import` | Ensure assets are imported into the project cache (clean-worktree loading). |

**`export`** — export presets and artifacts

| Command | What it does |
| ------- | ------------ |
| `export list` | Enumerate the project's export presets (name, platform, …). |
| `export get` | Report one preset's details plus export-template install status. |
| `export run` | Export a named preset (`release` / `debug` / `pack`) to a destination. |

**`shader`** — shader files (`.gdshader`)

| Command | What it does |
| ------- | ------------ |
| `shader create` | Create a new `.gdshader` from a template or verbatim `--content`. |
| `shader get` | Read a shader's source plus its `shader_type`. |
| `shader set` | Edit a `.gdshader` via search-replace, line-range, or full overwrite. |

**`theme`** — theme resources (`.tres`)

| Command | What it does |
| ------- | ------------ |
| `theme create` | Create a new, loadable `.tres` Theme resource (no-clobber). |

### Live commands — via `gda-daemon`; Godot 4.6+, macOS/Linux

**`daemon`** — the live runtime lifecycle

| Command | What it does |
| ------- | ------------ |
| `daemon start` | Start the per-project daemon and install the in-game harness; the engine session launches lazily, on the first operation that needs one (`--windowed` for `screen` capture). |
| `daemon wait-ready` | Launch the engine session now and wait for it; `--timeout` is the daemon's budget for that launch, not a hard ceiling on the call. Read-only `diag` / `logger` tails never launch a session, so run this first when such a read is your first live command. |
| `daemon stop` | Stop the project's daemon and any running engine session. |
| `daemon status` | Report the daemon's state (running, windowed mode, session). |
| `daemon install` | Install the in-game harness without starting a daemon, and report what it wrote. Idempotent; `daemon start` does this itself, so use it only to review or commit the `project.godot` change on its own. |
| `daemon uninstall` | Remove the in-game harness — autoload entry, harness files, `.uid` sidecar — restoring `project.godot`, and report what was removed. Dev-tooling teardown only: `gda export run` already strips the harness from exported builds. |

**`game`** — the running game's runtime scene graph

| Command | What it does |
| ------- | ------------ |
| `game tree` | Read the running game's runtime scene tree (after `_ready`). |
| `game get` | Read a runtime node's live properties by node path; explicit names can address attached-script variables. |
| `game rect` | Read a runtime Control's rendered viewport rect by node path. |
| `game set` | Set a runtime node property, or an explicitly named attached-script variable, on the running game; `verified` reports whether the read-back matched. |
| `game call` | Invoke one method the node's script declares in `GDA_CALLABLE` — the project's own read-only promise, which gda cannot verify — and project what it returns; nothing undeclared is ever called. |

`game call` reads what `game get` cannot: state your project exposes as a method.
`game set --property position` follows the same `Control` rule as `node set`.

**`diag`** — runtime diagnostics

| Command | What it does |
| ------- | ------------ |
| `diag errors` | Tail the running game's runtime errors (categorized). |

**`logger`** — structured runtime log

| Command | What it does |
| ------- | ------------ |
| `logger tail` | Tail the running game's whole runtime log as structured records (`--level`, `--limit`, `--raw`). |

**`perf`** — performance monitoring

| Command | What it does |
| ------- | ------------ |
| `perf monitors` | Snapshot the engine's counters — or, with `--frames`, sample a window with statistics and budget verdicts. |
| `perf monitor` | Sample a node property or signal over a frame window (timeline). |

**`input`** — input simulation

| Command | What it does |
| ------- | ------------ |
| `input key` | Inject a key event (with modifiers). |
| `input mouse-click` | Inject a complete click gesture (move, press, release) at `(x, y)`. |
| `input mouse-move` | Inject mouse motion to `(x, y)`. |
| `input action` | Press/release a mapped input action. |
| `input tap` | Tap one key or action: press, hold, release across frames. |
| `input sequence` | Inject a multi-frame event timeline. |

Read injected mouse coordinates from `event.position` — in a daemon session
`get_mouse_position()` / `get_global_mouse_position()` can stay stale.

**`screen`** — viewport capture

| Command | What it does |
| ------- | ------------ |
| `screen capture` | Capture one viewport frame to a PNG. |
| `screen frames` | Capture an N-frame PNG sequence (`--summary` for a compact aggregate result). |

### Global flags

| Flag       | Description                                                          |
| ---------- | ------------------------------------------------------------------- |
| `--json`    | Emit the outcome as a single JSON object on stdout — the result on success, the `{"error": {…}}` envelope on failure. Without it, both are printed as a concise human-readable rendering instead. Accepted before the command as well. |
| `--schema`  | Emit the command's input/output JSON Schema contract (no Godot spawned). |
| `--godot`   | Path to the Godot binary (overrides `$GDA_GODOT` and the default). |
| `--project` | Godot project directory for `res://` resolution (overrides `$GDA_PROJECT`; defaults to the current directory if it is a project). Domain commands only. Resolving a project runs that project's code — see [Project code execution](#configuration). |
| `--version` | Print the installed `gda` version. With `--json`, also where it came from — install kind (`wheel`, `editable`, or `unknown`) and, for an editable install, the source checkout's Git revision. |
| `--help`    | Show usage for `gda` or any command.                                |

---

## Configuration

`gda` finds the Godot binary from the **`--godot <path>`** flag, otherwise the
**`GDA_GODOT`** environment variable — set one of these so `gda` can locate your engine.

Domain commands resolve a **Godot project** so that `res://` paths resolve. A named
directory must be a project, or `gda` reports an error; when nothing resolves, `gda` runs
**projectless** — plain filesystem paths work, `res://` does not.

| Context | Project resolution order |
| --- | --- |
| **CLI** | `--project` → `GDA_PROJECT` (both strict: an invalid one is an error) → the current directory, if it holds `project.godot` → projectless |
| **MCP** (`gda-mcp`) | `GDA_PROJECT` (strict) → the client's workspace `root`, if it sends a valid one (pre-2026 clients) → the server's cwd, if it is a project → projectless |

<details>
<summary>Project code execution — what runs when you point at a project</summary>

Pointing `gda` at a project runs some of that project's own code — by design, since the
project is trusted ([ADR-0009](docs/adr/0009-trust-boundary-trusted-project.md)):

- **Autoloads** start on every `--project` operation that boots the engine, read-only ones
  included (a cached `resource import` boots nothing).
- **Scene scripts' `_init`** runs wherever a scene is instantiated: every mutating `node`
  command and `node get`; `scene get` / `scene list` / `node list` read without instantiating.
- **`script run`** executes the named script in full; **`scene preflight`** boots the scene
  and runs its `_ready`.
- **`resource import`** runs the engine's importers (and the project's import plugins) on a
  cache miss, without autoloads.
- **`game call`** runs the one method the node's `GDA_CALLABLE` declaration names; nothing
  undeclared is ever called.

</details>

---

<details>
<summary><strong>Under the hood</strong> — the structured-output contract & exit codes</summary>

Headless Godot interleaves its banner, warnings, and `print()` output into stdout. `gda`
solves this with a sentinel contract
([ADR-0002](docs/adr/0002-headless-structured-output-contract.md)):

- The GDScript payload emits **exactly one** result, wrapped in unique sentinels on stdout:

  ```
  <<<GDA:RESULT>>>{ …json… }<<<GDA:END>>>
  ```

- It routes **all** of its own diagnostics to stderr; stdout carries nothing but the contract.
- `gda` extracts and parses only the bytes between the sentinels, ignoring the surrounding
  engine noise, and surfaces stderr for inspection.

This is what makes `gda`'s output safe to consume programmatically, and it generalizes to
the per-message protocol the daemon uses for live operations.

**Exit codes (the CLI ABI).** A failed `gda` run exits with a small, stable code so a shell
or agent can branch on the failure **category without parsing the JSON error**:

| Exit code | Category      | When                                                                  |
| --------- | ------------- | --------------------------------------------------------------------- |
| `0`       | —             | Success.                                                              |
| `2`       | `usage`       | `gda` could not resolve what was asked for — an unrecognized command or option. A recognized near miss carries the invocation to use instead in the envelope's `hint`. |
| `127`     | `environment` | The Godot binary could not be launched (shell convention: not found). |
| `124`     | `environment` | Godot launched but did not return before the timeout (shell convention: timed out); the envelope carries the partial output captured so far. |
| `3`       | `version`     | The detected Godot version is below the supported minimum.            |
| `4`       | `operation`   | The engine ran but the operation failed — a registered operation error, an engine crash, or an unstructured non-zero exit. |
| `5`       | `parse`       | The process claimed success but violated the structured-output contract. |
| `6`       | `live`        | A live operation failed — e.g. no running daemon/session, or a live timeout. |

These values are the public ABI; their authoritative source is
[`src/gda/exit_codes.py`](src/gda/exit_codes.py). The `{"error": {category, code, …}}`
envelope carries a **finer `code`** within each category (e.g. `path_not_found`,
`already_exists`, `node_not_found` all sit under `operation` / exit `4`). The full
registry lives in
[ADR-0002's `GdaError.code` table](docs/adr/0002-headless-structured-output-contract.md#gdaerrorcode-registry).
</details>

<details>
<summary><strong>Development</strong></summary>

```bash
uv sync                       # set up the environment

uv run pytest                 # run the full suite (includes e2e tests against a real Godot)
uv run pytest -m "not e2e"    # unit tests only (no Godot binary required)
uv run pytest -m e2e          # only the end-to-end tests (needs Godot 4.4+ on this machine)
uv run pytest -n 4 --dist loadgroup   # any tier above on four workers, as CI runs each

uv run ruff check .           # lint
uv run ruff format .          # auto-format (append --check to verify without writing)
uv run pyright                # type-check (src/ + tests/, basic mode)
```

The `e2e` tier runs by default with `uv run pytest`, and **fails loudly** — naming the
resolved path and how to fix it — if no Godot binary is found there, rather than skipping.
Deselect the whole tier with `-m "not e2e"` (CI's per-PR job uses exactly this).

Linting and formatting are enforced by [ruff](https://docs.astral.sh/ruff/) — one tool in
place of flake8 + black + isort, configured under `[tool.ruff]` in `pyproject.toml` and
pinned via `uv.lock` so local and CI agree. CI's `lint` job runs `ruff check .` and
`ruff format --check .` on every PR; run `uv run ruff format .` before committing to stay
green.

Types are checked by [pyright](https://microsoft.github.io/pyright/) in `basic` mode, covering
`src/` and `tests/` and configured under `[tool.pyright]` in `pyproject.toml` (also pinned via
`uv.lock`). CI's `type-check` job runs `uv run --frozen pyright` on every PR.

```
src/gda/
  cli.py            # composition root (Typer): mounts every command group
  commands/         # one module per command group: its models, renderers, commands
  dispatch.py       # the CLI dispatch tails + the runner seams the groups call
  surface.py        # walks the live Typer tree → the `gda schema` manifest
  headless.py       # the per-command descriptor (one HeadlessCommand per command)
  binary.py         # Godot binary resolution (flag > $GDA_GODOT > default)
  runner.py         # the one-shot headless spawn seam (Protocol + subprocess impl)
  live_runner.py    # the live-operation client that talks to gda-daemon
  models.py         # the shared typed I/O core (Pydantic) backing --json and --schema
  errors.py / error_codes.py / exit_codes.py   # failure classification + the CLI ABI
  render.py         # the shared human-readable (non-JSON) render helpers
  ops/operations.gd # the headless GDScript payload, dispatched by operation name
  daemon/           # gda-daemon: server, session supervision, IPC protocol, discovery
  harness/          # the inert in-game `gda` autoload injected into a live session
  mcp/              # gda-mcp: the schema → MCP-tool server
tests/              # unit + e2e tests against a real engine (shared fixtures in conftest.py)
docs/adr/           # architecture decision records
CONTEXT.md          # the project's shared domain language
```

`gda` has two external boundaries, each behind a seam fast tests inject through: spawning a
one-shot headless process (`runner.py`) and talking to a running game via the daemon
(`live_runner.py`). The e2e suite drives a real engine across both.
</details>

---

## Contributing

Contributions are welcome. Read [`CONTEXT.md`](CONTEXT.md) to align with the project's
shared language, and review the relevant [ADRs](docs/adr/) for the area you're touching.
Issues and PRDs live as [GitHub issues](https://github.com/aigengame/godot-agent/issues).
Commits follow the [Conventional Commits](https://www.conventionalcommits.org/) specification.
Python code is linted and formatted with [ruff](https://docs.astral.sh/ruff/) and type-checked
with [pyright](https://microsoft.github.io/pyright/), both enforced in CI — run
`uv run ruff format .` and `uv run pyright` before committing (see **Development** above).

> **Working with an AI coding agent?** This project is built to be agent-navigable —
> [`AGENTS.md`](AGENTS.md) is the entry point for coding agents, wiring in the project's
> rules, domain docs, and skills.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 aigengame.
