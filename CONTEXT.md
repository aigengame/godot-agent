# godot-agent

The shared language of godot-agent: an agent-facing toolchain that lets AI agents
drive the Godot engine to build games, with structured output suitable for
programmatic consumption.

## Language

### Components

**gda**:
The agent-facing Godot CLI — the bottom layer that exposes Godot operations with
structured output. Other components build on it.
_Avoid_: the CLI, godot-cli

**gda-mcp**:
A thin protocol-adapter that exposes `gda` capabilities as an MCP server. It is
orthogonal to the delivery phases: first delivered on top of Phase 1, it follows
`gda` into Phase 2 automatically via `--schema` self-description (ADR-0004), and is
never itself a phase. Its order relative to other components follows ADR-0000.
_Avoid_: the server, mcp wrapper

**gda-daemon**:
A long-lived process that holds a persistent connection to a running Godot
engine, serving operations that require a live engine rather than a fresh
headless process per call.
_Avoid_: the service, background server

### Operations

**Headless operation**:
An operation that can be fulfilled by spawning a one-shot `godot --headless`
process — it needs no pre-existing engine state (e.g. create a scene, export,
run a test). The basis of Phase 1.
_Avoid_: batch op, offline op

**Live operation**:
An operation that requires an already-running engine/editor to observe or mutate
in-place state (e.g. inspect the live scene tree, runtime inspection, UndoRedo,
input simulation). Served through `gda-daemon`, not by a one-shot headless call.
_Avoid_: realtime op, online op

### Failure reporting

**Gda error code**:
A stable machine-readable code on a `GdaError`, used by agents to branch on a
specific failure mode without parsing prose.
_Avoid_: error string, status code

**Operation-reported error code**:
A `Gda error code` reported by a headless operation itself. It names a failure
the operation understood and chose to report.
_Avoid_: script error code, raw engine error

**Classifier error code**:
A `Gda error code` assigned by `gda` after classifying a runner, parser,
version, crash, or fallback operation failure.
_Avoid_: wrapper error code, Python error code

**Error envelope**:
The structured failure result that distinguishes a failed command from a
successful result.
_Avoid_: error blob, failure JSON

### Trust model

**Trusted project**:
The target project `gda` operates on — including its autoloads and scene
scripts — is assumed trustworthy; Phase 1 does not defend against a malicious or
untrusted project (ADR-0009).
_Avoid_: safe project, sandboxed project

**Project-code execution surface**:
The set of points where a single `gda` run triggers the target project's own
code to run: autoload constructors at engine startup (every `--project` op), and
the `_init` of scripts on nodes that an instantiating operation constructs.
_Avoid_: attack surface, code-execution risk

### Delivery phases

The order in which **capabilities** are delivered. This is distinct from ADR-0000's
bottom-up **component** order (`gda` → `gda-mcp` → `gda-daemon`): phases sequence
what `gda` can do, not which component is built.

**Phase 1**:
The first delivery — `gda` serves only headless operations, standalone with no
service dependency.
_Avoid_: MVP (broader), v1

**Phase 2**:
The later delivery — `gda` also serves live operations through `gda-daemon`'s
persistent engine connection.
_Avoid_: v2

### Command surface

**Command group**:
A top-level grouping of `gda` commands named after a Godot domain object
(`scene`, `node`, `script`, `project`, `resource`, `export`, …). Invoked as
`gda <group> <command>`.
_Avoid_: namespace, category, module

**Domain command**:
A grouped command that acts on a Godot domain object (e.g. `gda scene create`).
_Avoid_: tool, action

**Meta command**:
A top-level command about `gda` or the engine itself rather than a domain object
(`gda info`, `gda version`, `gda help`); exempt from grouping.
_Avoid_: global command, system command
