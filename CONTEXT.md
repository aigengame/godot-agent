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

**gda skill**:
The Agent Skill (a `SKILL.md`) that teaches an AI agent how and when to drive `gda`
through the CLI — a third agent-facing channel alongside `gda-mcp`. Where `gda-mcp`
exposes the surface as generated tools, the skill points the agent at the CLI itself plus
the guidance to use it; an agent uses whichever channel its runtime supports. It ships
in-package and is emitted by the `gda skill` command, so its guidance stays version-locked
to the installed CLI (ADR-0024).
_Avoid_: plugin, addon, the SKILL.md file

**gda-daemon**:
A long-lived, per-project process that supervises transient `Engine session`s and
brokers IPC to them, serving operations that require a live engine rather than a
fresh headless process per call. The daemon is persistent; the engine it connects to
is not — the connection lasts only as long as an `Engine session` (ADR-0017).
_Avoid_: the service, background server

**gda harness**:
The game-side autoload `gda` installs into a `Trusted project` so that `gda-daemon`
can run live operations inside an `Engine session` over IPC. It is inert — opening no
connection — unless the daemon launched the session, so it stays dormant in a human
editor run, a plain run, and a shipped build (ADR-0018).
_Avoid_: plugin, addon, agent

### Operations

**Headless operation**:
An operation that can be fulfilled by spawning a one-shot `godot --headless`
process — it needs no pre-existing engine state (e.g. create a scene, export,
run a test). The basis of Phase 1.
_Avoid_: batch op, offline op

**Live operation**:
An operation that requires an already-running engine to observe or control its
in-place runtime state (e.g. the runtime scene tree, runtime property get/set, input
simulation, viewport capture, performance/signal monitoring). Served through
`gda-daemon` against a running game, not by a one-shot headless call; the editor
context (UndoRedo, the editor's open-scene tree) is out of scope (ADR-0017).
_Avoid_: realtime op, online op

**Engine session**:
A single transient run of a gda-owned Godot game, launched and held by `gda-daemon`
with the `gda harness` injected, against which `Live operation`s are served. The
daemon outlives individual sessions; a session is (re)launched per feedback-loop
iteration to observe the project's current on-disk state (ADR-0017).
_Avoid_: game run, live session, play session

**State consistency**:
The guarantee `gda-daemon` provides over an `Engine session`'s runtime state: live
operations are serialized through a single writer, so a read observes the preceding
write; each operation is frame-coherent (applied/observed at a frame boundary); and
the state is bound to the session, not surviving its relaunch. A Phase-2 live-layer
property only — Phase-1 headless calls are stateless (ADR-0020).
_Avoid_: consistency, coherence, sync

**Headless launch**:
The one-shot `godot --headless` spawn primitive that the Phase-1 channels share —
the sentinel op-dispatch runner, the native-export runner, and the `gda script run`
user-script runner (ADR-0031). Given the binary, an argv tail, an optional working
directory, and a timeout, it builds `[binary, --headless, *args]`, captures bytes
with the timeout, and normalizes the outcome into a `Raw run` (the single home of
the spawn / timeout / launch-failure / UTF-8-decode handling). Each channel
contributes only its argv tail and the export-only cwd.
_Avoid_: spawn helper, subprocess wrapper

**Raw run**:
The normalized outcome a `Headless launch` returns — `{stdout, stderr, exit_code,
launch_failure}`, unparsed — before any classification. `launch_failure` is set
only when the primitive synthesized the result (binary missing, timed out) rather
than the engine returning one, so the classifier keys environment failures on
that typed reason, not on the overloaded exit code. Those launch-backed channels
all return the one `RunResult` shape. Normally internal, it is **promoted to a
public result by `gda script run`** — the one operation whose success result *is*
a Raw run (minus `launch_failure`, which is lifted out into an `Error envelope`),
so its `exit_status` can be non-zero on success (ADR-0031).
_Avoid_: run output, export output

**Session log**:
The per-`Engine session` capture of the running game's output and error stream,
written by the engine to a daemon-owned path (via `--log-file`) and read by
`gda-daemon` to serve runtime diagnostics; bound to the session (truncated each
launch), survives the session process so a crash stays diagnosable until relaunch
(ADR-0022).
_Avoid_: console output, stdout dump

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
code to run: autoload constructors at engine startup (every `--project` op), the
`_init` of scripts on nodes that an instantiating operation constructs, and — via
`gda script run` (ADR-0031) — the **full execution of a named project script**.
All stay within the `Trusted project` assumption (ADR-0009); `script run` widens
this surface without adding a new trust axis.
_Avoid_: attack surface, code-execution risk

**Concurrent external editor**:
A human-opened Godot editor on the same project while `gda` is driving it (e.g. to
view, run, or verify agent output). Phase 2 assumes `gda` is the project's sole
driver and does not defend against a concurrent external editor's writes (ADR-0018,
extending ADR-0009).
_Avoid_: second instance, shared editor

### Delivery phases

The order in which **capabilities** are delivered. This is distinct from ADR-0000's
bottom-up **component** order (`gda` → `gda-mcp` → `gda-daemon`): phases sequence
what `gda` can do, not which component is built.

**Phase 1**:
The first delivery — `gda` serves only headless operations, standalone with no
service dependency.
_Avoid_: MVP (broader), v1

**Phase 2**:
The later delivery — `gda` also serves live operations through `gda-daemon` and a
live `Engine session`.
_Avoid_: v2

### Command surface

**Command group**:
A top-level grouping of `gda` commands named after an object the user acts on —
usually a Godot domain object (`scene`, `node`, `script`, `project`, `resource`,
`export`, the running-game `game`, …), plus gda's own `daemon` lifecycle group
(ADR-0017). Invoked as `gda <group> <command>`. Live operations are placed under
their real domain-object group too — marked live by their `kind`, not by a separate
group (ADR-0019).
_Avoid_: namespace, category, module

**Domain command**:
A grouped command that acts on a Godot domain object (e.g. `gda scene create`).
_Avoid_: tool, action

**Meta command**:
A top-level command about `gda` or the engine itself rather than a domain object
(`gda info`, `gda version`, `gda help`); exempt from grouping.
_Avoid_: global command, system command

**Command descriptor**:
The single per-command registration object (`HeadlessCommand`) naming everything
`gda` needs to run, render, and self-describe one command: its `operation` name,
input/params and result models, execution `kind`, failure `classify`r, human
`render`er, and optional `recipe` channel. The render map, dispatch routing, and
`--schema` are **projections derived from it** — read off the descriptor on the
dispatch path, or built by walking the live Typer tree (ADR-0012) for a
whole-surface view — never parallel registries to keep in sync (ADR-0023).
_Avoid_: command spec, command config, command registry entry

### Public-facing copy

**Positioning descriptor**:
The single authoritative one-line phrase naming what `gda` *is* — currently "Godot AI
agent CLI, Skill, and MCP server" — front-loading the primary search terms (Godot · AI
agent · CLI/Skill/MCP). One positioning source, mirrored across three surfaces that change
together and must not drift: the README **H1** (Title Case), the `pyproject` `description`,
and the GitHub repository `description` (the metadata pair in sentence case, optionally
extended with "… with structured JSON/schema output, headless automation, and live runtime
control"). Its head noun stays "CLI, Skill, and MCP server", so it names a *tool* — not a
claim that `gda` is itself an agent.
_Avoid_: tagline, slogan, hero, the value sentence

**Hero**:
The README's opening *value* statement — what `gda` does for you ("`gda` gives your AI
coding agent … structured, machine-readable control of the Godot Engine", headless then
live). README-only and free to evolve there; it does **not** mirror the `Positioning
descriptor` and is never replicated into `pyproject` or the repo metadata.
_Avoid_: tagline, subtitle, positioning descriptor
