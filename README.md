# godot-agent (`gda`)

![godot-agent title image](assets/godot-agent-title.png)

> An agent-first **CLI and MCP server** that lets AI agents drive the [Godot Engine](https://godotengine.org) to build games — with **structured output** built for programmatic consumption.

[![Status](https://img.shields.io/badge/status-Phase%201%20headless%20surface%20complete-brightgreen?cacheSeconds=3600)](#project-status)
[![CI](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml?query=branch%3Amain+event%3Apush)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![Godot](https://img.shields.io/badge/godot-4.4%2B%20(tested%204.6)-478CBF)](https://godotengine.org)
[![Package manager](https://img.shields.io/badge/packaging-uv-DE5FE9)](https://github.com/astral-sh/uv)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

`godot-agent` lets AI agents drive the Godot engine through **structured, machine-readable
operations** rather than raw logs: an agent issues an operation and gets back a single clean
result it can act on, not prose it has to scrape.

It is designed as three layers: **`gda`**, the agent-facing CLI that exposes Godot operations
with structured `--json` output and self-describing schemas; **`gda-mcp`**, a thin
[Model Context Protocol](https://modelcontextprotocol.io) server that turns those same
capabilities into MCP tools, derived mechanically from `gda`'s schemas; and **`gda-daemon`**, a
long-lived process holding a persistent connection to a running engine to serve *live operations*
that a one-shot headless process cannot. `gda` lands first as a standalone headless CLI (Phase 1);
live operations follow through `gda-daemon` (Phase 2). See [Architecture](#architecture-at-a-glance)
for the full picture.

---

## Why `gda`?

- **🤖 Agent-first, structured output.** Every command supports `--json` and emits exactly one
  result object on stdout. Engine noise and diagnostics are routed to stderr, so an agent never
  has to scrape prose. See the [structured-output contract](#the-structured-output-contract).
- **📐 Model-driven & self-describing.** Each command's input and output are defined as typed
  models that back both `--json` and a machine-readable `--schema` (a JSON Schema contract). Carrying
  a valid `--schema` is a hard, no-exception merge gate on every command — so an MCP adapter can
  generate tool definitions mechanically instead of hand-maintaining them.
  *(See [ADR-0004](docs/adr/0004-schema-flag-self-description.md).)*
- **🧩 Godot-native command surface.** Commands are grouped by Godot domain object
  (`gda scene create`, `gda node add`, …) with a small, orthogonal verb vocabulary — zero learning
  cost if you already know Godot. *(See [ADR-0005](docs/adr/0005-cli-command-taxonomy.md).)*
- **📦 Standalone, no service required.** The first delivery fulfils *headless operations* by
  spawning one-shot `godot --headless` processes — nothing to install in the editor, no daemon to
  run. Live, stateful operations arrive later behind the same CLI. *(See [ADR-0001](docs/adr/0001-godot-integration-mechanism.md).)*
- **🛡️ Fails loudly, not silently.** A missing or hung engine is bounded by a timeout and mapped
  to a non-zero exit with a clear diagnostic — never an indefinite hang or a raw traceback.

---

## Project status

> **`gda`'s Phase-1 headless command surface is feature-complete.** The architecture and contracts
> are settled (see [`CONTEXT.md`](CONTEXT.md) and [`docs/adr/`](docs/adr/)), and every headless
> domain command group designed in
> [PRD #17](https://github.com/aigengame/godot-agent/issues/17) now ships end-to-end against a real
> engine. `gda` is still pre-1.0 and not yet published to a package index
> ([#207](https://github.com/aigengame/godot-agent/issues/207)); **`gda-mcp` now ships** alongside
> the CLI, and the next milestone is Phase 2 live operations.

**Working today — the full headless command surface**

- ✅ **Eight command groups, fulfilled headlessly:** `scene`, `node`, `script`, `project`,
  `resource`, `export`, `shader`, and `theme`, plus the `info` meta command — and the `project`
  static-analysis reads (`find-references`, `dependencies`, `find-unused-resources`, `statistics`).
  See the [command reference](#command-reference) for every command
  ([ADR-0005](docs/adr/0005-cli-command-taxonomy.md)).
- ✅ **The contract every command carries:** structured `--json` output, model-derived `--schema`
  self-description as a hard merge gate
  ([ADR-0004](docs/adr/0004-schema-flag-self-description.md)), and structured
  `{"error": {category, code, …}}` failures with category-distinguishing
  [exit codes](#exit-codes-the-cli-abi).
- ✅ **The engine plumbing underneath:** Godot binary resolution (flag / env var / default), the
  bounded one-shot `godot --headless` runner with its sentinel output contract
  ([ADR-0002](docs/adr/0002-headless-structured-output-contract.md)), command-agnostic failure
  classification, and project-context / `res://` path resolution
  ([ADR-0006](docs/adr/0006-project-context-and-path-resolution.md)).

**Also working today — the MCP adapter**

- ✅ `gda-mcp`, a thin [Model Context Protocol](https://modelcontextprotocol.io) stdio server that
  exposes the whole `gda` surface as MCP tools, generated mechanically from `--schema`. Register it
  with your agent using the [registration recipes](docs/gda-mcp-registration.md).

**On the roadmap** (designed, not yet implemented)

- 🔜 `gda-daemon` for *live operations* against a running engine (Phase 2): live scene tree,
  runtime inspection, input simulation, `scene play`/`stop`, screenshots.

**Out of scope for now**

- **C# / .NET scripts.** The `script` group operates on GDScript (`.gd`) only; whether and how to
  support the Godot .NET build and `.cs` scripts is deferred
  ([#124](https://github.com/aigengame/godot-agent/issues/124)).
- **The deferred catalog groups** — animation, tilemap, physics, audio, particles, 3D scene,
  navigation, Android deploy — each needs its own slice-level design before becoming a commitment.

The active backlog and per-command status live in the
[issue tracker](https://github.com/aigengame/godot-agent/issues) — the headless increment is
grouped under the [**Phase 1 — headless operations** milestone](https://github.com/aigengame/godot-agent/milestone/1).
The [command catalog](docs/command-catalog.md) maps the whole command surface (a non-binding
*feature map*, not a status tracker); this section deliberately duplicates neither. See also the
[roadmap](#roadmap).

---

## Architecture at a glance

`gda` is delivered bottom-up as three components and in two capability phases:

| Component     | Role                                                                                   | Phase |
| ------------- | -------------------------------------------------------------------------------------- | ----- |
| **`gda`**     | The agent-facing Godot CLI — the bottom layer that exposes Godot with structured output | 1     |
| **`gda-mcp`** | A thin MCP adapter that exposes `gda`'s capabilities as MCP tools, derived from `--schema` | 1+    |
| **`gda-daemon`** | A long-lived process holding a persistent connection to a running engine for *live operations* | 2     |

- **Headless operations** need no pre-existing engine state and are fulfilled by a one-shot
  `godot --headless` process (e.g. report version, create a scene, export). This is the basis of
  **Phase 1**.
- **Live operations** require an already-running engine (live scene tree, runtime inspection,
  UndoRedo, input simulation) and are served by `gda-daemon` in **Phase 2**.

The vocabulary above is defined precisely in [`CONTEXT.md`](CONTEXT.md); the decisions behind it live
in [`docs/adr/`](docs/adr/).

---

## Requirements

- **[uv](https://github.com/astral-sh/uv)** — the Python toolchain/package manager used by this project.
- **Python 3.13+** (uv can provision this for you).
- **Godot 4.4+** — `gda` targets Godot 4.x with a minimum of 4.4; 4.6 is the tested baseline.
  3.x is not supported. *(See [ADR-0003](docs/adr/0003-target-godot-version.md).)*

---

## Installation

`gda` is not yet published to a package index; install it from source with `uv`.

```bash
git clone https://github.com/aigengame/godot-agent.git
cd godot-agent
uv sync          # create the environment and install dependencies
uv run gda --help
```

To install `gda` as a standalone CLI on your `PATH`:

```bash
uv tool install .
gda --help
```

### MCP server (`gda-mcp`)

`gda` ships a stdio [MCP](https://modelcontextprotocol.io) server behind an optional `[mcp]` extra,
so any MCP-speaking agent can drive Godot through it. Try it with no install:

```bash
uvx --from "gda[mcp] @ git+https://github.com/aigengame/godot-agent" gda-mcp
```

Register it by dropping the matching config in place. `gda-mcp` picks your Godot project from the
client's workspace `roots` where available, otherwise from `GDA_PROJECT` (ADR-0014).

**Claude Code** — project scope: `.mcp.json` in the project root (committed; auto-detects the
workspace project):

```json
{
  "mcpServers": {
    "gda-mcp": {
      "command": "uvx",
      "args": ["--from", "gda[mcp] @ git+https://github.com/aigengame/godot-agent", "gda-mcp"]
    }
  }
}
```

…or user scope (available in every project), via the CLI — writes `~/.claude.json`:

```bash
claude mcp add --scope user gda-mcp -- \
  uvx --from "gda[mcp] @ git+https://github.com/aigengame/godot-agent" gda-mcp
```

**Codex** — `~/.codex/config.toml` (global) or `.codex/config.toml` (project; pin the project path):

```toml
[mcp_servers.gda-mcp]
command = "uvx"
args = ["--from", "gda[mcp] @ git+https://github.com/aigengame/godot-agent", "gda-mcp"]

[mcp_servers.gda-mcp.env]
GDA_PROJECT = "/absolute/path/to/your/godot/project"
```

**Cursor** — `.cursor/mcp.json` in the project root:

```json
{
  "mcpServers": {
    "gda-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "gda[mcp] @ git+https://github.com/aigengame/godot-agent", "gda-mcp"],
      "env": { "GDA_PROJECT": "${workspaceFolder}" }
    }
  }
}
```

> Cursor and Claude Desktop are GUI-launched with a minimal `PATH`, so a bare `uvx` may not resolve —
> use an absolute path (`which uvx`) for `command`. Full recipes — user vs project scope, Claude
> Desktop, the `PATH` fix, and per-agent project pinning — are in the
> [registration recipes](docs/gda-mcp-registration.md). Once `gda` is on PyPI
> ([#207](https://github.com/aigengame/godot-agent/issues/207)), the `@ git+…` part drops to just
> `"gda[mcp]"`.

---

## Quick start

Point `gda` at your Godot binary and ask for the engine version:

```bash
# Use the GDA_GODOT environment variable (or the --godot flag, or the default path)
export GDA_GODOT="/path/to/Godot"

gda info --json
```

```json
{"major":4,"minor":6,"patch":3,"hex":263683,"status":"stable","build":"official","hash":"7d41c59c457bd5a245092b4e7eb2d833e3b3f8c3","string":"4.6.3-stable (official)","timestamp":0}
```

Without `--json`, `gda info` prints the human-readable version string (`4.6.3-stable (official)`).
All engine and script diagnostics go to **stderr**, so stdout is always clean JSON you can pipe:

```bash
gda info --json | jq .major   # → 4
```

Create a scene headlessly and read its structured tree back:

```bash
gda scene create game/main.tscn --root-type Node2D --json
# {"path":"game/main.tscn","root_name":"main","root_type":"Node2D"}

gda scene get game/main.tscn --json
# {"path":"game/main.tscn","root":{"name":"main","type":"Node2D","children":[]}}
```

Add a node into that scene and verify it landed — nodes are addressed by their path relative to
the scene root (`.` is the root itself):

```bash
gda node add game/main.tscn --type Sprite2D --name Hero --json
# {"scene_path":"game/main.tscn","path":"Hero","name":"Hero","type":"Sprite2D","script_class":null}

gda node list game/main.tscn --json
# {"scene_path":"game/main.tscn","root":{"name":"main","type":"Node2D","path":".","children":[{"name":"Hero","type":"Sprite2D","path":"Hero","children":[]}]}}
```

Read a node's properties as typed JSON, set one (the CLI value is coerced to the property's declared
Godot type), and verify the change round-trips via `get`:

```bash
gda node set game/main.tscn --node Hero --property position --value 10,20 --json
# {"scene_path":"game/main.tscn","path":"Hero","property":"position","type":"Vector2","value":[10.0,20.0]}

gda node get game/main.tscn --node Hero --json
# {"scene_path":"game/main.tscn","path":"Hero","name":"Hero","type":"Sprite2D","properties":[…,{"name":"position","type":"Vector2","value":[10.0,20.0]},…]}
```

Enumerate a project's scenes, then delete one — `scene list` walks the project's `res://` tree, so it
needs a project context (`--project`, `$GDA_PROJECT`, or a cwd that is a project):

```bash
gda scene list --project game --json
# {"scenes":[{"path":"res://main.tscn","root_name":"main","root_type":"Node2D"}]}

gda scene delete res://main.tscn --project game --json
# {"path":"res://main.tscn","root_name":"main","root_type":"Node2D"}
```

---

## Usage

### Command surface

`gda` commands are **grouped by Godot domain object** and use a small, consistent verb vocabulary,
so the same verb means the same thing in every group:

```
gda <group> <command> [options]     # domain commands, e.g. gda scene create
gda <meta-command> [options]        # meta commands about gda/the engine, e.g. gda info
```

| Verb                     | Meaning                                                          |
| ------------------------ | ---------------------------------------------------------------- |
| `create` / `delete`      | Make / remove a **standalone** entity (scene, script, resource)  |
| `add` / `remove`         | Add / remove a **sub-entity** within a container (node → scene)  |
| `get` / `list`           | Read one entity / enumerate many                                 |
| `set`                    | Mutate a property                                                |
| domain verbs             | `play`, `run`, `export`, `import`, … kept with their natural meaning |

> The taxonomy and naming rules are specified in
> [ADR-0005](docs/adr/0005-cli-command-taxonomy.md). `gda --help` (and `gda <group> --help`) is the
> authoritative list of what is installed; the table below mirrors the shipped Phase-1 surface.

### Command reference

Every command supports `--json` and `--schema`; commands that read or mutate a `res://` path resolve
a [project context](#project-context), and mutating commands run that project's code
([project code execution](#project-code-execution)). Run `gda <group> <command> --help` for full
flags.

**Meta** — about `gda` / the engine itself

| Command | What it does |
| ------- | ------------ |
| `gda info` | Report the Godot engine version info. |

**`scene`** — scene files (`.tscn`)

| Command | What it does |
| ------- | ------------ |
| `scene create` | Create a new `.tscn` with the given root node type. |
| `scene get` | Read a scene and report its structured node tree. |
| `scene list` | Enumerate the `.tscn` scenes in the resolved project. |
| `scene get-exports` | List the `@export` properties a scene's nodes' scripts declare. |
| `scene delete` | Delete a scene file and report what was removed. |

**`node`** — nodes within a scene file

| Command | What it does |
| ------- | ------------ |
| `node add` | Add a node under a parent (built-in type or `class_name` script). |
| `node get` | Read a node's properties (by node path) as typed JSON. |
| `node list` | List a scene's node tree with each node's path relative to the root. |
| `node set` | Set a node property, coercing the value to its declared Godot type. |
| `node remove` | Remove a node (and its subtree) by node path. |
| `node duplicate` | Duplicate a node (and its subtree) under its parent. |
| `node move` | Reparent a node (and its subtree) under a new parent. |
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
| `script validate` | Syntax/compile-check a `.gd` script. |

**`project`** — the project as a whole (settings, autoloads, static analysis)

| Command | What it does |
| ------- | ------------ |
| `project info` | Report project metadata (name, main scene, viewport, engine version). |
| `project get` | Read a single project setting by section/key as typed JSON. |
| `project set` | Set a project setting, coercing the value to its declared type. |
| `project add-autoload` | Register an autoload singleton (name → script/scene). |
| `project remove-autoload` | Unregister an autoload singleton by name. |
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

### Global flags

| Flag       | Description                                                          |
| ---------- | ------------------------------------------------------------------- |
| `--json`    | Emit the result as a single JSON object on stdout. Without it, commands print a concise human-readable rendering. |
| `--schema`  | Emit the command's input/output JSON Schema contract (no Godot spawned). |
| `--godot`   | Path to the Godot binary (overrides `$GDA_GODOT` and the default). |
| `--project` | Godot project directory for `res://` resolution (overrides `$GDA_PROJECT`; defaults to the current directory if it is a project). Domain commands only. Resolving a project runs that project's code — see [Project code execution](#project-code-execution). |
| `--help`    | Show usage for `gda` or any command.                                |

---

## Configuration

`gda` resolves the Godot binary in this order (highest precedence first):

1. The **`--godot <path>`** flag.
2. The **`GDA_GODOT`** environment variable.
3. A **default development path** — `~/Applications/Godot.app/Contents/MacOS/Godot` (macOS).
   On other platforms, set `GDA_GODOT` or pass `--godot`.

```bash
gda info --godot "/Applications/Godot.app/Contents/MacOS/Godot" --json
```

### Project context

Domain commands resolve a **Godot project** so that `res://` paths and a scene's
inter-resource references resolve deterministically, in this order (highest precedence first):

1. The **`--project <dir>`** flag.
2. The **`GDA_PROJECT`** environment variable.
3. The **current directory**, when it is a Godot project (contains `project.godot`).

A named directory must be a project, or `gda` reports it as an error. When none resolves, `gda`
runs **projectless** — only filesystem paths (absolute or cwd-relative) resolve, not `res://`.
Path normalization happens once at the CLI layer: `res://` / `user://` / `uid://` pass through to
the engine; filesystem paths get `~` expanded. See
[ADR-0006](docs/adr/0006-project-context-and-path-resolution.md).

```bash
gda scene get res://main.tscn --project ~/game --json
```

### Project code execution

Resolving a project so `res://` paths work runs Godot against that project, and Godot runs
some of the project's own code as part of that. Concretely:

- **Autoloads run on every `--project` operation.** When a project is resolved, the engine
  constructs the project's autoload singletons at startup — before the command's own work runs —
  so their `_init` (and `_ready`) execute on **every** operation, including read-only ones like
  `scene get` and `node list`. Without a resolved project, no autoloads are registered, so they do
  not run.
- **Commands that instantiate a scene execute that scene's attached scripts' constructors.** A
  command that needs a live node tree — every mutating command (`node add`, `node set`,
  `node remove`, …), and `node get` (which reports runtime property defaults the stored data does
  not carry) — loads and instantiates the scene, which constructs each node and runs the `_init` of
  any script attached to a node in it. Commands that only read the stored scene data
  (`scene get`, `scene list`, `node list`) walk it without instantiating, so they do not run those
  scripts.

In short: pointing `gda` at a project executes that project's autoload code on every command, and
any command that instantiates a scene additionally executes that scene's attached scripts' `_init`.
The tracked decisions on this are [#61](https://github.com/aigengame/godot-agent/issues/61)
(autoloads) and [#62](https://github.com/aigengame/godot-agent/issues/62) (scene scripts on
instantiating operations); see also
[ADR-0009](docs/adr/0009-trust-boundary-trusted-project.md).

---

## The structured-output contract

Headless Godot interleaves its banner, warnings, and `print()` output into stdout. `gda` solves this
with a sentinel contract ([ADR-0002](docs/adr/0002-headless-structured-output-contract.md)):

- The GDScript payload emits **exactly one** result, wrapped in unique sentinels on stdout:

  ```
  <<<GDA:RESULT>>>{ ...json... }<<<GDA:END>>>
  ```

- It routes **all** of its own diagnostics to stderr; stdout carries nothing but the contract.
- `gda` extracts and parses only the bytes between the sentinels, ignoring the surrounding engine
  noise, and surfaces stderr for inspection.

This is what makes `gda`'s output safe to consume programmatically, and it generalizes to the
per-message protocol the daemon will use in Phase 2.

### Exit codes (the CLI ABI)

A failed `gda` run exits with a small, stable code so a shell or agent can branch on the failure
**category without parsing the JSON error**:

| Exit code | Category      | When                                                                  |
| --------- | ------------- | --------------------------------------------------------------------- |
| `0`       | —             | Success.                                                              |
| `127`     | `environment` | The Godot binary could not be launched (shell convention: not found). |
| `124`     | `environment` | Godot launched but did not return before the runner timeout (shell convention: timed out). |
| `3`       | `version`     | The detected Godot version is below the supported minimum.            |
| `4`       | `operation`   | The engine ran but the operation failed — a registered operation error, an engine crash, or an unstructured non-zero exit. |
| `5`       | `parse`       | The process claimed success but violated the structured-output contract. |

These values are the public ABI; their authoritative source is
[`src/gda/exit_codes.py`](src/gda/exit_codes.py) — that registry, not this table, defines them.
The `{"error": {category, code, …}}` envelope carries a **finer `code`** within each category
(e.g. `path_not_found`, `already_exists`, and `node_not_found` all sit under `operation` / exit `4`).
The full code → category → exit-code registry, kept in sync with the code by tests, lives in
[ADR-0002’s `GdaError.code` registry table](docs/adr/0002-headless-structured-output-contract.md#gdaerrorcode-registry).

---

## Development

```bash
uv sync                       # set up the environment

uv run pytest                 # run the full suite (includes e2e tests against a real Godot)
uv run pytest -m "not e2e"    # unit tests only (no Godot binary required)
uv run pytest -m e2e          # only the end-to-end tests (needs Godot 4.4+ on this machine)
```

The `e2e` tier runs by default with `uv run pytest`, and **fails loudly** — naming the
resolved path and how to fix it — if no Godot binary is found there, rather than skipping.
Deselect the whole tier with `-m "not e2e"` (CI's per-PR job uses exactly this) when you
have no engine; use `-m e2e` to run only the e2e tests.

### Project layout

```
src/gda/
  cli.py            # CLI entrypoint (Typer); command groups, --json/--schema, binary override
  binary.py         # Godot binary resolution (flag > $GDA_GODOT > default)
  runner.py         # GodotRunner seam (Protocol) + SubprocessGodotRunner (one-shot headless)
  parser.py         # sentinel-contract result parser (ADR-0002)
  models.py         # typed I/O models (Pydantic) backing --json and --schema (ADR-0004)
  errors.py         # failure classification: shared classify_run + per-command layers
  error_codes.py    # the registry of public GdaError.code values (ADR-0002 companion)
  exit_codes.py     # the single registry of process exit codes (the CLI ABI)
  ops/operations.gd # GDScript payload, dispatched by operation name
tests/              # unit tests + e2e tests against a real engine (shared fixtures in conftest.py)
docs/adr/           # architecture decision records
CONTEXT.md          # the project's shared domain language
```

The only external boundary — spawning a Godot process — sits behind the `GodotRunner` Protocol
(`runner.py`). Fast unit and CLI tests inject a canned result through that boundary; the e2e suite
drives a real engine. Everything between the CLI and the runner runs as real code in both tiers.

---

## Roadmap

| Phase / component | Delivers                                                                  | Status |
| ----------------- | ------------------------------------------------------------------------- | ------ |
| **Phase 1** | `gda` serving *headless operations* standalone: `info`, structured errors, `--schema`, and the domain command groups `scene`, `node`, `script`, `project` (incl. static-analysis), `resource`, `export`, `shader`, `theme`. | ✅ Surface complete |
| **`gda-mcp`** | A thin MCP adapter generated mechanically from `--schema` — first on top of Phase 1, following `gda` forward automatically. | ✅ Shipped |
| **Phase 2** | `gda` also serving *live operations* through `gda-daemon`'s persistent engine connection. | 🗓 Planned |

Track progress and proposals on the [issue tracker](https://github.com/aigengame/godot-agent/issues).

---

## Contributing

Contributions are welcome. Before starting:

- Read [`CONTEXT.md`](CONTEXT.md) to align with the project's shared language, and review the
  relevant [ADRs](docs/adr/) for the area you're touching.
- Issues and PRDs live as GitHub issues in [`aigengame/godot-agent`](https://github.com/aigengame/godot-agent/issues).

Commits follow the [Conventional Commits](https://www.conventionalcommits.org/) specification.

> **Working with an AI coding agent?** This project is built to be agent-navigable.
> [`AGENTS.md`](AGENTS.md) is the entry point for coding agents — it wires in the project's
> rules, domain docs, and skills.

---

## Acknowledgements

`gda`'s design draws on two reference implementations from the Godot + agent ecosystem: the
one-shot-headless approach of `godot-mcp` and the persistent editor-plugin approach of
`godot-mcp-pro`. `gda` deliberately adopts a **hybrid, phased** strategy that combines their
strengths (see [ADR-0001](docs/adr/0001-godot-integration-mechanism.md)).

---

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 aigengame.
