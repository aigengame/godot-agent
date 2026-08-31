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

**Startup preflight**:
A `Headless operation` that BOOTS a scene to find out whether it comes up: it
instantiates the scene into a one-shot engine's tree, observes it for a bounded
number of frames, and reports a startup verdict (`gda scene preflight`, #664). It is
the dynamic counterpart of static scene validation, which checks a scene without
instantiating or running the TARGET scene — the project's autoloads still start and
script compilation still runs static initializers, as on every `--project` op
(ADR-0009) — so a scene can pass that and still fail on its first frame. Despite booting the game's code it is NOT a `Live operation`: nothing
drives or observes the scene from outside, there is no `Engine session` and no
`gda-daemon`, and the process ends with the verdict.
_Avoid_: smoke test, dry run, live check

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
the sentinel op-dispatch runner, the native-export runner, the `gda resource
import` engine pass, the `gda script run` user-script runner (ADR-0031), and the
`gda scene preflight` runner, which dispatches an ordinary sentinel op but calls
the primitive itself because it bifurcates on the launch's own outcome, a timeout
being its verdict rather than a failure to classify (#664). Given the binary, an
argv tail, an optional working directory, and a timeout, it builds `[binary,
--headless, --log-file <gda-owned path>, *args]`, captures bytes with the timeout,
and normalizes the outcome into a `Raw run` (the single home of the spawn /
timeout / launch-failure / UTF-8-decode handling). Each channel contributes only
its argv tail and the export-only cwd. It also owns the launch's `User-data
placement` — resolved and preflighted here, once, so no channel plumbs it (#653).
Every launch **streams**: both pipes are read as they arrive, so whatever the run
produced before gda ended it survives, and the launch is timed. #655 introduced
that beside a **buffered** strategy which discarded the child's output at the
timeout and reported the wait instead, keeping the other channels on it while the
mechanism was proven; #714 moved the last three across and deleted it, so there is
ONE strategy and no channel can be left on the discard. What a channel may still
choose is a `LaunchWatch` — POLICY, not strategy: a rule for ending a run EARLY
that only that channel can state (`gda script run`'s `Completion marker`).
_Avoid_: spawn helper, subprocess wrapper

**User-data placement**:
Where one `Headless launch` puts the engine's log and, when redirected, `user://`.
gda always owns the **log** target and passes it as `--log-file`, because Godot
builds its file logger before any project code runs and dies with signal 11 if it
cannot open the log — and because the engine default is one per-project rotated
file that concurrent invocations contend over. By default the target is a private
temporary file, so a read-only application-data directory is not fatal; the
per-invocation `--user-data-root` (env `GDA_USER_DATA_ROOT`) instead places the log
*and* `user://` under a caller-chosen directory, since Godot has no
`--user-data-dir` flag and the platform data variable is the only lever. The
placement is **created, not inspected**, before the spawn — that creation IS the
preflight — and a placement gda cannot make usable is a typed refusal
(`user_data_unwritable`) rather than an engine crash. Headless only: a live
`Engine session`'s log is daemon-owned (ADR-0022).
_Avoid_: log redirect, user dir, sandbox

**Raw run**:
The normalized outcome a `Headless launch` returns — `{stdout, stderr, exit_code,
launch_failure, elapsed_seconds, timeout_bound}`, unparsed — before any
classification. `launch_failure` is set only when the primitive synthesized the
result (binary missing, timed out, the `User-data placement` was refused, or a
watch ended the run) rather than the engine returning one, so the classifier keys
environment failures on that typed reason, not on the overloaded exit code. The
streams hold **what the run had already produced** rather than a gda notice, and
`elapsed_seconds` carries the wall clock — on every channel (#655, #714).
`timeout_bound` is the pair a timed-out run cannot state for itself: WHICH launch
gave up (its channel label) and the ceiling it reached. It is set only on a
`TIMEOUT` result and it rides the result because it is the only thing that crosses
the runner seam — the shared `launch_timeout` classifier has the raw run and
nothing else, so without it two of the three channels could not name their own
ceiling (#714). Those launch-backed channels all return the one `RunResult` shape.
Normally internal, it is **promoted to a public result by `gda script run`** — the
one operation whose success result *is* a Raw run (minus `launch_failure`,
`elapsed_seconds`, `timeout_bound`, and the streams' timeout semantics, all of
which are lifted out into an `Error envelope`; since #665 the
promoted `stdout` is additionally a BOUNDED projection — verbatim up to a cap,
above it the leading cap bytes with the complete stream spilled to a file the
result names), so its `exit_status` can be non-zero on success (ADR-0031).
_Avoid_: run output, export output

**Completion marker**:
The line a `gda script run` caller **declares** its own script prints when the
script's work is done (`--completion-marker`). A declared **liveness contract**, not a
death detector: whether a run that printed an error can still finish is not observable
from outside the process, so declaring the marker is the caller asserting the script
keeps producing output until the marker line says it finished. With one declared, gda
ends a run early — reporting `script_aborted` with the captured error, in seconds
instead of at `--timeout`, identically on every platform — when **all three** hold:
stderr shows a recognized error *attributable to the entry script*, the marker has not
appeared, and neither stream then produces output for a fixed window (#655). The
contract cuts both ways: a script that goes silent past the window after such an error
is ended by declaration even if it would have finished — print progress during quiet
stretches, or omit the marker and wait the ceiling out. Matched by **whole-line
equality**, not as a substring. Opt-in and never imposed: gda requires nothing of the
script and injects nothing into it (ADR-0031 rejected a gda-owned sentinel wrapper).
**Not** the ADR-0002 op-dispatch sentinel, which is gda's own contract with its own
`operations.gd` payload; a marker is an arbitrary caller line read for one boolean.
_Avoid_: sentinel, done marker, quit marker

**Session log**:
The per-`Engine session` capture of the running game's output and error stream,
written by the engine to a daemon-owned path (via `--log-file`) and read by
`gda-daemon` to serve runtime diagnostics; bound to the session (truncated each
launch), survives the session process so a crash stays diagnosable until relaunch
(ADR-0022).
_Avoid_: console output, stdout dump

### Structured output

**Value projection**:
The read-side contract for rendering a Godot value into the structured JSON a
successful result carries. Scalars and the small fixed-shape value types pass
through directly; a `Dictionary`/`Array` (and the packed-array family) projects
recursively; and an `Object` is rendered by one of four **projection kinds** — a
**reference projection** for a `Resource` that has a `res://` path (named by type
and path, never inlined — the read-side mirror of ADR-0033's write-side
reference), a **texture projection** for a PATH-LESS `Texture2D` (named by type
and dimensions, with the former `str()` form under `object_string` — its
discriminator — and an opt-in content `digest`; ADR-0035 amendment, #666), an
**inline value projection** for a whitelisted path-less value
`Object` (named by type plus its projected fields), or a plain **string
fallback** for anything else. One projection shared across **every value gda
emits** — the `get` reads (`project`/`node`/`resource get`), the value echoed by
`node set`/`resource set`, the per-entry value of `project list` and `scene
get-exports`, and the live `game get` read — so a value reads the same
everywhere. That sameness is of SHAPE; numeric FIDELITY is not yet uniform.
The harness frames every reply with Godot's full-precision JSON writer, so a
LIVE projected float crosses exactly — the one residual being that a negative
zero reads back as `0.0` — while the headless writer still flattens small
floats to `0.0` and rounds ordinary ones (#771). The write-side mirror on the
live wire is a refusal: a float Godot's parser would read as `0.0` is rejected
before a request is relayed to the harness, no decimal literal being able to
deliver it (#752). Two controls keep the shared projection safe on the live
side: the whitelist bounds the Object classes whose storage properties the
inline kind emits, and the texture kind is safe by construction — a fixed
getter shape with its one expensive readback behind the explicit digest opt-in
(ADR-0035).
_Avoid_: value rendering, str dump, serialization, descriptor

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
A `Gda error code` assigned by `gda` itself rather than reported by an operation —
after classifying a runner, parser, version, crash, or fallback operation failure,
or before any operation is identified at all, when the invocation names no command
or option gda has (#670).
_Avoid_: wrapper error code, Python error code

**Error envelope**:
The structured failure result that distinguishes a failed command from a
successful result.
_Avoid_: error blob, failure JSON

**Near-miss hint**:
The corrected invocation gda returns when it RECOGNIZES a wrong one — an unknown
command or option it holds a curated entry for (`gda scene inspect` → `gda scene
get`, `gda --schema` → `gda schema`). It rides the `Error envelope` as the optional
`hint` key, so an agent re-issues the corrected command without parsing prose; the
human error carries the same correction in its message. Curated, never a
string-similarity guess: similarity is silent whenever the spelling is not close
and the nearest string can be a different — even opposite — operation. One table
(`src/gda/hints.py`) is the authority, kept honest by a test that re-resolves every
hint against the live command tree (#670).
_Avoid_: did-you-mean, suggestion, autocorrect

### Trust model

**Trusted project**:
The target project `gda` operates on — including its autoloads and scene
scripts — is assumed trustworthy; Phase 1 does not defend against a malicious or
untrusted project (ADR-0009).
_Avoid_: safe project, sandboxed project

**Project-code execution surface**:
The set of points where a single `gda` run triggers the target project's own
code to run: autoload constructors at engine startup (every `--project` op
that boots the game-facing engine — see the import-pass point below for the
one that does not), the
`_init` of scripts on nodes *or resources* that an instantiating operation
constructs (a `class_name` node via `node add`, a script-backed `class_name`
Resource via `resource create`, or every script inside a **scene composed as an
instanced child** via `node add --instance`, #399), the `_init` of a
**script-backed Resource loaded as a value** assigned to an Object-typed
property (`node set` / `resource set --value res://…`, ADR-0033), the **full
execution of a named project script** via `gda script run` (ADR-0031), and — via
`gda scene preflight` (#664) — the **startup of a whole scene**: every script it
carries runs its `_init` and `_ready` and keeps running for a bounded number of
frames, beside the autoloads — that preflight point is the widest on this
list. `gda resource import` (#668) contributes two DISTINCT points: a fully
cached request starts no engine at all (nothing on this surface runs), while
a missing or stale cache runs the **engine import pass** — importer code (and
any import plugins the project registers) over project content, WITHOUT the
autoloads: the pass boots the editor importer path, not the game's scene
stack.
`gda scene validate` (#664) is a point too, and a narrow one: it compiles
every script the scene binds — which runs their static initializers — while
instantiating nothing, so none of the scene's own nodes reach `_init` or
`_ready`; composing the verdict over referenced sub-scenes (#721) widened that
set from the validated scene's own scripts to every script reachable through
the scenes it references, without adding a point.
`gda game call` (#673) contributes ONE narrow point: the single method the
addressed node's attached-script chain named in its `GDA_CALLABLE` declaration
runs, once, per request. Reading that declaration adds no point at all — the
constant map is served by the compiled script, so learning what may be called
executes nothing (ADR-0041).
All stay within the `Trusted project` assumption (ADR-0009); `script run`, the
loaded-value assignment (ADR-0033), the startup preflight, the import pass, the
declared method call, and the composed static validate widen this surface without
adding a new trust axis.
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
(`gda info`, `gda version`, `gda help`, `gda schema`, `gda skill`); exempt from
grouping.
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
