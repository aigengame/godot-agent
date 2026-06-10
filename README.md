# godot-agent (`gda`)

![godot-agent title image](assets/godot-agent-title.png)

> An agent-first **CLI and MCP server** that lets AI agents drive the [Godot Engine](https://godotengine.org) to build games — with **structured output** built for programmatic consumption.

[![Status](https://img.shields.io/badge/status-Phase%201%20(in%20development)-orange)](#project-status)
[![CI](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml?query=branch%3Amain+event%3Apush)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![Godot](https://img.shields.io/badge/godot-4.4%2B%20(tested%204.6)-478CBF)](https://godotengine.org)
[![Package manager](https://img.shields.io/badge/packaging-uv-DE5FE9)](https://github.com/astral-sh/uv)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

`godot-agent` lets AI agents drive the Godot engine through **structured, machine-readable
operations** rather than raw logs: an agent issues an operation and gets back a single clean
result it can act on, not prose it has to scrape.

It is delivered as three layers: **`gda`**, the agent-facing CLI that exposes Godot operations
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
  models. The same model serializes `--json` today and will emit a machine-readable `--schema`
  (a JSON Schema contract) — so an MCP adapter can generate tool definitions mechanically instead
  of hand-maintaining them. *(See [ADR-0004](docs/adr/0004-schema-flag-self-description.md).)*
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

> **`gda` is in active early development (Phase 1).** The architecture and contracts are settled
> (see [`CONTEXT.md`](CONTEXT.md) and [`docs/adr/`](docs/adr/)), and the headless pipeline is live
> end-to-end. This README documents the working surface *and* the roadmap, and is explicit about
> which is which.

**Working today**

- ✅ A first working command surface: the `info` meta command and the first domain command groups —
  `gda scene create` / `gda scene get` and `gda node add` / `gda node list`
  ([ADR-0005](docs/adr/0005-cli-command-taxonomy.md)).
- ✅ The contract every shipped command carries: structured `--json` output, model-derived
  `--schema` self-description ([ADR-0004](docs/adr/0004-schema-flag-self-description.md)), and
  structured `{"error": {category, code, …}}` failures with category-distinguishing exit codes.
- ✅ The engine plumbing underneath: Godot binary resolution (flag / env var / default) and the
  bounded one-shot `godot --headless` runner with its sentinel output contract
  ([ADR-0002](docs/adr/0002-headless-structured-output-contract.md)).

**On the roadmap** (designed, not yet implemented)

- 🔜 The remaining domain command groups and commands: the rest of `node`, `script`, `project`,
  `resource`, `export`, …
- 🔜 `gda-mcp`, a thin [Model Context Protocol](https://modelcontextprotocol.io) adapter generated
  from `--schema`.
- 🔜 `gda-daemon` for *live operations* against a running engine (Phase 2).

Per-command status (shipped / Phase-1 candidate / parked) is tracked in the
[command catalog](docs/command-catalog.md) — the single source of truth this section deliberately
does not duplicate. See also the [roadmap](#roadmap) and the
[issue tracker](https://github.com/aigengame/godot-agent/issues).

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

> The surface grows one vertical slice at a time; `gda --help` lists what is installed, and
> per-command status is tracked in the [command catalog](docs/command-catalog.md). The taxonomy
> and naming rules are specified in [ADR-0005](docs/adr/0005-cli-command-taxonomy.md).

### Global flags

| Flag       | Description                                                          |
| ---------- | ------------------------------------------------------------------- |
| `--json`    | Emit the result as a single JSON object on stdout. Without it, commands print a concise human-readable rendering. |
| `--schema`  | Emit the command's input/output JSON Schema contract (no Godot spawned). |
| `--godot`   | Path to the Godot binary (overrides `$GDA_GODOT` and the default). |
| `--project` | Godot project directory for `res://` resolution (overrides `$GDA_PROJECT`; defaults to the current directory if it is a project). Domain commands only. |
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

---

## Development

```bash
uv sync                       # set up the environment

uv run pytest                 # run the full suite (includes e2e tests against a real Godot)
uv run pytest -m "not e2e"    # unit tests only (no Godot binary required)
uv run pytest -m e2e          # only the end-to-end tests (needs Godot 4.4+ on this machine)
```

The `e2e` tests auto-skip if no Godot binary is found at the resolved path.

### Project layout

```
src/gda/
  cli.py            # CLI entrypoint (Typer); command groups, --json/--schema, binary override
  binary.py         # Godot binary resolution (flag > $GDA_GODOT > default)
  runner.py         # GodotRunner seam (Protocol) + SubprocessGodotRunner (one-shot headless)
  parser.py         # sentinel-contract result parser (ADR-0002)
  models.py         # typed I/O models (Pydantic) backing --json and --schema (ADR-0004)
  errors.py         # failure classification: shared classify_run + per-command layers
  exit_codes.py     # the single registry of process exit codes (the CLI ABI)
  ops/operations.gd # GDScript payload, dispatched by operation name
tests/              # unit tests + e2e tests against a real engine (shared fixtures in conftest.py)
docs/adr/           # architecture decision records
CONTEXT.md          # the project's shared domain language
```

The codebase is intentionally built around **fakeable seams** (e.g. the `GodotRunner` Protocol) so
commands can be tested without launching a real engine.

---

## Roadmap

| Phase       | Delivers                                                                            |
| ----------- | ----------------------------------------------------------------------------------- |
| **Phase 1** | `gda` serving *headless operations* standalone: `info`, structured errors, `--schema`, and domain command groups (`scene`, `node`, `script`, `project`, `resource`, `export`, …). |
| **`gda-mcp`** | A thin MCP adapter generated mechanically from `--schema` — first on top of Phase 1, following `gda` forward automatically. |
| **Phase 2** | `gda` also serving *live operations* through `gda-daemon`'s persistent engine connection. |

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
