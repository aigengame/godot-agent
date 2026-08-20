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
- **🛡️ Fails loudly, never silently.** A missing or hung engine is bounded by a timeout
  and mapped to a **stable non-zero exit code** plus a structured `{"error": {…}}`
  envelope — so a shell or agent can branch on the failure category without parsing prose.
  A command or option `gda` does not recognize is refused the same structured way, with a
  `hint` naming the invocation to use instead.

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

`--install --provider <claude|codex> --scope <project|user>` resolves a known agent's skills
directory (`--scope` defaults to `user`); `--dir` is the neutral fallback for any other agent —
there's no built-in default. The [skill recipes](docs/gda-skill.md) list each agent's directory
(Claude Code's `~/.claude/skills/`, Codex's `~/.agents/skills/`, …). Or fetch the same file straight
from the repo, if you'd rather not go through `gda skill` — you still install `gda`, since the Skill
drives it:

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

- **Project** — set `GDA_PROJECT` when your client can't advertise workspace **roots**; otherwise
  `gda-mcp` auto-detects the project from the roots the client sends (the folder you have open). A
  *set-but-invalid* `GDA_PROJECT` is a reported error, not a silent fallback. Note the MCP
  2026-07-28 spec revision deprecates the roots capability: today's clients keep working unchanged,
  but pinning `GDA_PROJECT` is the future-proof setup (a client on the new stateless protocol has no
  roots to advertise). See [Configuration](#configuration) for the full CLI-vs-MCP resolution order.
- **Engine** — set `GDA_GODOT` to your Godot binary, e.g. `"GDA_GODOT": "/path/to/Godot"`.

For clients on the MCP 2026-07-28 revision, `gda-mcp` marks its `tools/list` response cacheable
(1-hour TTL, public scope) — the generated tool surface is fixed for a server's lifetime, so
upgraded clients can skip re-fetching it; pre-2026 clients see identical traffic.


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

Every command supports `--json` and `--schema` — `gda schema` accepts `--json` too, where
it changes nothing because the aggregate manifest is already JSON. Commands that read or mutate a `res://` path
resolve a [project context](#configuration). Run `gda <group> <command> --help` for full
flags — `gda --help` is the authoritative list of what is installed.

**New here?** A good first path: `gda info` → `gda scene create` → `gda node add` →
`gda script validate` → `gda export run`; then go live with `gda daemon start` → `gda game tree`.

**Meta** — about `gda` / the engine itself

| Command | What it does |
| ------- | ------------ |
| `gda info`   | Report the Godot engine version info. Accepts an explicit, validated `--project` (the other meta commands do not); the version does not depend on it. |
| `gda version` | Report which `gda` is installed and where it came from — with `--json`, the full install provenance (the same payload as `gda --version --json`). No Godot is spawned. |
| `gda help`   | Show a command's help (`gda help scene get`) or the whole CLI's; `--json` returns it as `{command, text}`. |
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
| `scene validate` | Check statically that a scene's dependencies resolve and its attached scripts compile. |
| `scene preflight` | Boot a scene headless, wait for `_ready`, and report its startup verdict. |

Reading a scene survives most breakage: Godot substitutes null for a node's reference it
cannot resolve and still returns a usable tree, so `scene get` shows a healthy scene whose
script and texture are both gone (a dependency broken from inside a sub-resource can still
fail the whole load). The two checks answer different questions.
`scene validate` is **static** — it resolves every dependency, compiles every bound script
(referenced or embedded), and checks every binding the engine would refuse, all without
instantiating anything — reporting one problem per problem file (`missing_resource`,
`unloadable_resource` for an asset that was never imported, `script_compile_failed`, or
`incompatible_script` for a binding the engine would refuse: a script on a node outside its
base, or a bound value that is not a script) with the nodes that reference it. The check is
**staged**: when dependencies fail to resolve, the scene is not loaded, so the compile and
binding problems of the loaded scene can only appear after the dependencies are repaired and
validate is rerun — the problem list is complete for the stage it reached, not across both
stages at once. `scene preflight` is **dynamic** —
it boots the scene, runs its `_ready` and the project's autoloads, watches it for a few frames,
and reports `status` (`ready` / `not_ready` / `timeout`) plus the script errors seen while it
started; read `started` for the one-boolean gate. Run both: a scene whose dependencies all
resolve can still fail on its first frame, and a scene referencing a never-imported texture
starts perfectly cleanly — only the static check names that file. Both report a bad scene as a
**successful operation** (exit `0`,
verdict in the result) — only a missing file, a non-scene file, or an environment failure uses
the Error envelope.

**`node`** — nodes within a scene file

| Command | What it does |
| ------- | ------------ |
| `node add` | Add a node under a parent, optionally at `--index`: a built-in type, a `class_name` script, or `--instance` to compose another scene as an instanced child. |
| `node get` | Read a node's properties (by node path) as typed JSON. |
| `node list` | List a scene's node tree with each node's path relative to the root. |
| `node set` | Set a node property, coercing the value to its declared Godot type. |
| `node remove` | Remove a node (and its subtree) by node path. |
| `node duplicate` | Duplicate a node (and its subtree) under its parent. |
| `node move` | Reparent a node (and its subtree) under a new parent, or reorder it with `--index`. |
| `node connect-signal` | Wire a source node's signal to a target node's method. |
| `node disconnect-signal` | Unwire an existing signal→method connection. |

For `Control` nodes, `node set --property position` writes the underlying
`offset_left` / `offset_top` / `offset_right` / `offset_bottom` values while
preserving size. Direct children of a `Container` are layout-managed, so set the
offset properties explicitly instead.

**`script`** — GDScript files (`.gd`)

| Command | What it does |
| ------- | ------------ |
| `script create` | Create a new `.gd` script from a template or verbatim `--content`. |
| `script get` | Read a script's source plus its `class_name` / `extends` metadata. |
| `script list` | Enumerate the `.gd` scripts in the resolved project. |
| `script set` | Edit a script via search-replace, line-range, or full overwrite. |
| `script delete` | Delete a script file and report what was removed. |
| `script attach` | Attach a `.gd` script to a node (by node path) in a scene. |
| `script validate` | Syntax/compile-check `.gd` scripts — several PATHs at once, or `--all` for every script in the project. |
| `script run` | Run a project script headless as a one-shot entry point, under a bounded wall clock. |

`script validate` takes a **batch**: pass several PATHs and they are all validated in
one engine launch, so the four to six related scripts a change touches cost one
process instead of one each. `--all` validates every `.gd` script in the resolved
project the same way.

For `script validate --json`, read the result object's `valid` field — the **aggregate**
verdict, `false` when any one script fails. Each script's own verdict is an entry under
`scripts`, carrying its `path`, `valid`, `error_string` and `diagnostics`. A single
PATH is simply a batch of one, so the shape never varies. A script that does not compile
is still a successful operation: exit `0`, no top-level `error`, and `valid: false`.
Operation problems such as a missing file still use the normal Error envelope, and they
refuse the whole batch rather than becoming a verdict.

The result also reports `project_root`: the project the scripts were compiled against,
which is the root their `res://` dependencies resolved to (`null` when no project was
resolved). Read it before acting on a `valid: false` — a verdict full of missing
`res://` dependencies, plus the type errors derived from them, usually means the wrong
project rather than a broken script. A path *outside* the resolved project refuses the
whole batch up front with `project_not_found`, naming both the file and the project,
instead of reporting those false errors; pass `--project` for the project that owns the
files.

`script run` executes a named project script one-shot and **passes its run through**: the
success result carries the script's own `exit_status` (a deliberate non-zero `quit()` is
data, not a gda failure — pass `--strict` to turn it into a `script_failed` error for shell
`&&` chains) plus its captured `stdout` and `stderr` verbatim. `--timeout <s>` bounds the
run's wall clock; a run gda has to end reports `launch_timeout` **with the partial output
captured so far**, the elapsed seconds and a termination phase. Declare
`--completion-marker <line>` — a line your script prints when its work is done — and a run
that hit a recognized error attributable to the entry script, has not printed the marker,
and then goes silent on both streams is ended in seconds rather than at the ceiling,
reported as `script_aborted` with the captured error.

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

**`resource`** — resource files (`.tres`)

| Command | What it does |
| ------- | ------------ |
| `resource create` | Create a new `.tres` resource of the given type. |
| `resource get` | Read a `.tres` resource's properties as typed JSON. |
| `resource set` | Set a `.tres` property, coercing the value to its declared type. |
| `resource delete` | Delete a `.tres` resource file and report what was removed. |
| `resource uid` | Resolve a resource UID ↔ its `res://` path in both directions. |

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
| `daemon start` | Start the per-project daemon and install the in-game harness; the engine session launches on the first live op (`--windowed` for `screen` capture). |
| `daemon stop` | Stop the project's daemon and any running engine session. |
| `daemon status` | Report the daemon's state (running, windowed mode, session). |
| `daemon install` | Install the in-game `gda` harness into the project without starting a daemon, reporting every path and section it created. Idempotent, and re-syncs a harness from an older `gda`. `daemon start` does this itself, so run it only to make that `project.godot` change deliberately — to review or commit it. |
| `daemon uninstall` | Remove the in-game `gda` harness from the project — the autoload entry, the harness files and its `.uid` sidecar, plus an `[autoload]` section left with no keys, so `project.godot` returns to its pre-install bytes (for files Godot's own writer produces); the result enumerates every path and section removed. An explicit dev-tooling teardown; `gda export run` already strips the harness from exported artifacts automatically. |

**`game`** — the running game's runtime scene graph

| Command | What it does |
| ------- | ------------ |
| `game tree` | Read the running game's runtime scene tree (after `_ready`). |
| `game get` | Read a runtime node's live properties by node path; explicit names can address attached-script variables. |
| `game rect` | Read a runtime Control's rendered viewport rect by node path. |
| `game set` | Set a runtime node property, or an explicitly named attached-script variable, on the running game. |

Live `game set --property position` follows the same `Control` policy as
`node set`; `game rect` remains a read-only rendered-geometry query. `game set`
success results include `verified`: `true` when the observed read-back value
matches the coerced requested value, and `false` when the set completed but the
observed value differs, such as getter-only/no-op script variables or
edge-triggered controls.

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
| `perf monitors` | Snapshot the engine's performance counters (fps, memory, nodes, …). |
| `perf monitor` | Sample a node property or signal over a frame window (timeline). |

**`input`** — input simulation

| Command | What it does |
| ------- | ------------ |
| `input key` | Inject a key event (with modifiers). |
| `input mouse-click` | Inject a mouse click at `(x, y)`. |
| `input mouse-move` | Inject mouse motion to `(x, y)`. |
| `input action` | Press/release a mapped input action. |
| `input sequence` | Inject a multi-frame event timeline. |

Mouse events report the injected viewport coordinate through `event.position`.
Godot may leave `get_mouse_position()` / `get_global_mouse_position()` stale in
daemon sessions, so game code should read injected mouse coordinates from the
input event.

**`screen`** — viewport capture

| Command | What it does |
| ------- | ------------ |
| `screen capture` | Capture one viewport frame to a PNG. |
| `screen frames` | Capture an N-frame PNG sequence. |

### Global flags

| Flag       | Description                                                          |
| ---------- | ------------------------------------------------------------------- |
| `--json`    | Emit the result as a single JSON object on stdout. Without it, commands print a concise human-readable rendering. Also accepted at the root: `gda --json <group> <command>` means the same as passing it after the command. |
| `--schema`  | Emit the command's input/output JSON Schema contract (no Godot spawned). |
| `--godot`   | Path to the Godot binary (overrides `$GDA_GODOT` and the default). |
| `--project` | Godot project directory for `res://` resolution (overrides `$GDA_PROJECT`; defaults to the current directory if it is a project). Domain commands only. Resolving a project runs that project's code — see [Project code execution](#configuration). |
| `--version` | Print the installed `gda` version. With `--json`, emit structured install provenance instead — version, executable, interpreter and imported-package paths, install kind (`wheel`, `editable`, or `unknown` when the install metadata cannot be read), and an editable install's source checkout with its Git revision and dirty state (no Godot spawned). Useful as a preflight before a long run: an editable install can change revision while the run is in progress. |
| `--help`    | Show usage for `gda` or any command.                                |

---

## Configuration

`gda` finds the Godot binary from the **`--godot <path>`** flag, otherwise the
**`GDA_GODOT`** environment variable — set one of these so `gda` can locate your engine.

Domain commands resolve a **Godot project** (so `res://` paths and a scene's inter-resource
references resolve deterministically) in this order:

1. The **`--project <dir>`** flag.
2. The **`GDA_PROJECT`** environment variable.
3. The **current directory**, when it is a Godot project (contains `project.godot`).

A named directory must be a project, or `gda` reports it as an error. When none resolves,
`gda` runs **projectless** — only filesystem paths (absolute or cwd-relative) resolve, not
`res://`. The **MCP server** has no flags, so it resolves a project a little differently:

| Context | Project resolution order |
| --- | --- |
| **CLI** | `--project` → `GDA_PROJECT` (both strict — invalid is reported) → cwd if it holds `project.godot`, else projectless |
| **MCP** (`gda-mcp`) | `GDA_PROJECT` (strict — set-but-invalid is reported, not skipped) → a *valid* client workspace `root` (clients on the pre-2026 MCP protocol; the 2026-07-28 revision has no roots, so those clients skip straight on) → a *valid* server cwd, else projectless |

<details>
<summary>Project code execution — what runs when you point at a project</summary>

Resolving a project so `res://` paths work runs Godot against that project, and Godot runs
some of the project's own code as part of that. Concretely:

- **Autoloads run on every `--project` operation.** When a project is resolved, the engine
  constructs the project's autoload singletons at startup — before the command's own work
  runs — so their `_init` (and `_ready`) execute on **every** operation, including read-only
  ones like `scene get` and `node list`. Without a resolved project, no autoloads are
  registered, so they do not run.
- **Commands that instantiate a scene execute that scene's attached scripts' constructors.**
  A command that needs a live node tree — every mutating command (`node add`, `node set`,
  `node remove`, …), and `node get` (which reports runtime property defaults the stored data
  does not carry) — loads and instantiates the scene, which constructs each node and runs the
  `_init` of any script attached to a node in it. Commands that only read the stored scene
  data (`scene get`, `scene list`, `node list`) walk it without instantiating, so they do not
  run those scripts.
- **`gda script run` executes the named script in full.** That is the command's purpose: the
  script's top-level code and everything it calls run to completion under the declared
  bounds.
- **`gda scene preflight` boots the scene.** It instantiates the scene and runs its `_ready`
  plus the observation frames, so every script in the scene — and the project's autoloads —
  execute their startup code.

`gda` treats the target project as trusted, so this is by design — see
[ADR-0009](docs/adr/0009-trust-boundary-trusted-project.md) for the trust model.
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
| `124`     | `environment` | Godot launched but did not return before the runner timeout (shell convention: timed out). |
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
