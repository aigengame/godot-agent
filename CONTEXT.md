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

**Import evidence**:
The read-side verdict gda takes on one asset's import cache before deciding to run
the engine's project-wide pass — `cached` / `missing` / `stale` / `invalid`, read
from the same artifacts `EditorFileSystem::_test_for_reimport` reads, in the
engine's own order, with the engine-state checks it cannot read declared as a
one-way remainder (delay a re-import, never spend a pass the engine would not).
An `invalid` verdict also names the check that decided it (`reason`, with the
offending line or path in `detail`), because that is the one verdict the pass
will not change and the caller's next move depends on which check refused it
(#853). Owned by the core `import_evidence` module; settlements are the
command's post-pass verdicts, not evidence — the command carries an `invalid`
reason into the `failed` it settles, and decides on its own the one reason no
artifact check can state, `dest_missing_after_pass`.
_Avoid_: cache check, freshness probe, validity scan

**Project tree inventory**:
The Python-side enumeration of a project's files and the two-capture settlement
over it — the fact behind `gda export run`'s `Project-tree mutation report` and
`gda resource import`'s `created` list, which read it from one core module rather
than under two different walks, one per command (#985). It walks under the rules
the module states: a directory link is followed as the engine reads it, once each
by filesystem identity (`st_dev`, `st_ino`); a cycle is not re-entered and is not
counted; only a regular file is opened; an unlistable or unreadable entry is
counted once per filesystem identity, or once per spelling where `stat` cannot
answer for it; a top-level `.git` is excluded; and
the cache root is walked like anything else, so its files are what both commands
classify as `cache_owned`. It then settles two captures — one before the engine
runs, one after — into what the run CREATED, what it REWROTE, and how much
neither capture could account for. A caller says only what the asking command
must: which project to inventory, which artifact to keep out of the answer, and
whether rewrites are detected at all. The module states that interface;
`resource import` passes no artifact and asks for no rewrite detection.
It is NOT the engine-side `res://` walk in `operations.gd` — which this
repository calls the project walk, and which since #804 skips a directory holding
a nested `project.godot` or a `.gdignore` while it still enumerates dot-prefixed
directories (ADR-0032, amended by #760 and #804; the dot-prefix half is #54's and
#712's). The inventory's walk takes neither marker, because the engine writes its
OWN `.gdignore` into the project data directory (ADR-0032's #804 amendment
carries that fact and the engine source): the two markers alone would prune the
cache root and empty the `cache_owned` half of both `created` lists, which is
what would make "anywhere under the project" untrue. It is not `Import
evidence`'s reachability prediction either, which keeps its own sidecar scan for
that different question.
And it is neither a filesystem library nor a file-set configuration: the project,
the artifact and the rewrite gate are the two commands' questions, not options a
caller tunes (#985's scope guard).
_Avoid_: project walk, file scan, tree diff, walker

**Project-tree mutation report**:
What `gda export run` reports about the PROJECT it exported, beside the artifact
it produced. The native export runs the editor import pass, so it can create a
whole cache tree and the sidecars beside the sources, and rewrite generated
resources that are tracked. The report names the files the export CREATED
anywhere under the project — each classified `cache_owned` / `source_adjacent`,
the same verdict `gda resource import` reports for the files its own pass
creates, from the shared `import_evidence` module, against the cache root the
report names, so the cache half can be cleaned as one unit — and the pre-existing
files OUTSIDE that root it REWROTE, decided by content rather than by timestamp:
only a file whose size or timestamp moved is compared, so a rewrite that
preserves both is not seen. Both are attributed to the export under the
`Concurrent external editor` assumption. A count of what neither walk could
account for rides along — an entry that is not a regular file, or one that could
not be read — because such a corner of the tree must not fail an export that
succeeded. It is NOT a deletion list, and it says nothing about rewrites INSIDE
the cache root — a warm export rewrites its own bookkeeping there on every run —
so an unchanged `modified` is not a statement about the cache. Disclosure only:
the export deletes and restores nothing, and a failed export carries no report at
all (#839).
_Avoid_: inventory, diff, changeset

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

**Injection route**:
The door a live input injection takes into the running game, and there are exactly
two: `action_state` drives `Input.action_press` / `action_release`, changing the
polled state `Input.is_action_*` reads and reaching no `_input` / `_gui_input` /
`_unhandled_input` handler; `viewport_event` pushes an `InputEvent` through the root
viewport's `push_input`, reaching those handlers and changing no polled state. The
two are disjoint by construction — a state change is not an event — so a successful
action injection is not evidence the event path works, which twice read as one in
dogfooding. Every `input` result names the route it used (`injection_route`,
top-level on the single-event commands and per phase on the phased ones), derived
CLI-side from the event kind (#838) plus ONE opt-in: `--as-event` (`as_event` on a
sequence `action` event) asks for an action to be delivered as an
`InputEventAction` through the same `push_input`, so it takes the `viewport_event`
route and reaches those handlers while the polled state stays untouched (#854).
The opt-in changes which door an action takes, never the disjointness — which is
why it is `push_input` and not `Input.parse_input_event`, whose state update would
put one injection on both routes at once. The default stays the state route:
changing it would silently alter what every existing call means.
The route reports the injection mechanism, not proof that a particular handler ran
or a UI action succeeded. Normal event propagation and consumption still apply.
Action/tap routes are projected from decoded harness replies; sequence phases are
derived from the accepted request after its event count is confirmed (ADR-0023).
_Avoid_: input mode, injection method, path

**Render frame**:
The drawn frame a captured image IS: the engine's drawn-frame counter
(`Engine.get_frames_drawn()`) read at the capture boundary, and the second of the
two frame counters every `screen capture` receipt carries. The first is
`engine_frame`, the PROCESS-frame index at that boundary — on a gated capture the
predicate's evaluation frame plus the request's settle frames. The two are
different counters because the engine draws a frame AFTER each process frame's
callbacks: a read taken during them returns the frame the PRECEDING iteration
drew, so on a session that draws every frame the two counters read the SAME
number, and that number names the frame the preceding iteration drew, not the
one this boundary will draw. They also come apart without bound, because that draw is
conditional — a window that is not visible, or low-processor-usage mode with
nothing changed, skips it, and `engine_frame` then advances while the render frame
stands still. That is how two captures come back byte-identical with no game
change (the GDA-DF-065 shape), and why only the render frame tells such a pair
from two captures that really do present different frames (#847).
_Avoid_: frame number, frame id, presented frame

**Headless launch**:
The one-shot Godot-process primitive that the Phase-1 channels share, in fixed
headless mode. Existing channels use the configured editor executable: the sentinel
op-dispatch runner, the native-export runner, the `gda resource import` engine pass,
the `gda script run` user-script runner (ADR-0031), and the `gda scene preflight`
runner, which dispatches an ordinary sentinel op but calls the primitive itself
because a timeout is its verdict (#664). ADR-0042's `Artifact smoke` is the second
explicit executable source: the resolved Godot executable inside a caller-selected
`Export artifact`. Given that Godot executable, an argv tail, an optional working
directory, and a timeout, the primitive builds `[executable, --headless, --log-file
<gda-owned path>, *args]`, captures bytes, and normalizes the outcome into a `Raw
run`. This remains the single home of spawn, timeout, launch-failure, UTF-8-decode,
and `User-data placement` handling. It is not an arbitrary-process runner and has
no mode or platform strategy registry.
Every launch **streams**: both pipes are read as they arrive, so whatever the run
produced before gda ended it survives, and the launch is timed. #655 introduced
that beside a **buffered** strategy which discarded the child's output at the
timeout and reported the wait instead, keeping the other channels on it while the
mechanism was proven; #714 moved the last three across and deleted it, so there is
ONE strategy and no channel can be left on the discard. What a channel may still
choose is a `LaunchWatch` — POLICY, not strategy: a rule for ending a run early
that only that channel can state (`gda script run` applies its `Completion marker`
rule; Artifact smoke does not have one).
_Avoid_: spawn helper, subprocess wrapper, process runner

**User-data placement**:
Where one `Headless launch` puts the engine's log and, when redirected, `user://`.
gda always owns the **log** target and passes it as `--log-file`, because Godot
builds its file logger before any project code runs and dies with signal 11 if it
cannot open the log — and because the engine default is one per-project rotated
file that concurrent invocations contend over. Normally the target is a private
temporary file, so a read-only application-data directory is not fatal; the
per-invocation `--user-data-root`, which overrides `GDA_USER_DATA_ROOT`, instead
places the log *and* `user://` under a caller-chosen directory, since Godot has no
`--user-data-dir` flag and the platform data variable is the only lever. After it
resolves the artifact, Artifact smoke creates and owns a fresh private root when
neither existing override names one, then supplies that root through the narrow
internal placement input so a caller-selected exported game cannot write the real
user directory. It attempts to remove only that owned root in `finally` after every
outcome. Cleanup is best-effort internal hygiene: failure does not replace the
command outcome or add a result field, error code, or `Failure evidence`. Existing
callers keep their current placement resolution. The placement is **created, not
inspected**, before the spawn — that creation IS the
preflight — and a placement gda cannot make usable is a typed refusal
(`user_data_unwritable`) rather than an engine crash. It is also REPORTED, not only
prepared: the placement rides the `Raw run` out of the launch that dropped it, and
`gda script run` publishes it on a SUCCESSFUL result, so a failed `user://` write
is attributable to the environment instead of read as a game regression (#850).
Three of that channel's failure envelopes carry it too, on `Failure evidence` —
`script_failed`, `launch_timeout` and `script_aborted` — since that same
misdiagnosis is exactly what a `--strict` failure and a timeout report. Those three
codes and no others: every other `script run` verdict carries no placement, whether
or not the script ran (`engine_crashed` and `stdout_spill_failed` did run and carry
none), and so does every other channel's envelope (#862). The presence rules are the
success result's, with the one difference that object imposes: a field that is not a
fact is omitted, never null.
Artifact smoke uses the placement internally and does not publish transient
placement paths or extend `Failure evidence`. The
engine's export-template lookup follows the same placement, so a
redirected export can miss templates the host holds — `export run` says so and
`export get` reports both roots (#840). Headless only: a live `Engine session`'s log
is daemon-owned (ADR-0022).
_Avoid_: log redirect, user dir, sandbox

**Raw run**:
The normalized outcome a `Headless launch` returns — `{stdout, stderr, exit_code,
launch_failure, elapsed_seconds, timeout_bound, user_data}`, unparsed — before any
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
ceiling (#714). `user_data` is the other thing the run cannot state for itself and
the placement no longer exists to be asked: where THIS launch put Godot's user data
— the root, the platform-derived data path, and the log file, that last one only
when a root made it outlive the launch. It is the `User-data placement` minus its
child environment, attached on every outcome of a prepared placement and absent on
one that was refused (#850). Those launch-backed channels all return the one
`RunResult` shape.
Normally internal, part of it is **promoted to public completed-run results by
`gda script run` and Artifact smoke**. Both results carry `exit_status`, stderr,
diagnostics, and the BOUNDED stdout projection from #665 — verbatim up to a cap,
then the leading cap bytes with the complete stream in the named spill file —
each declaring those fields itself. Their fieldless shared result base supplies
the projection validator and the schema rule that publishes its truth table.
The `gda.completed_run` module owns the stdout cap, bounded projection and
spill handling, shared default timeout, and human rendering after each
command's own opening line. `script run` adds its canonical script path and its
existing flattened placement fields (#850). Artifact smoke instead adds only
the caller's artifact path and the resolved executable path. Its private
placement remains an internal safety mechanism. Launch failures, elapsed time,
timeout bounds, and stream timeout semantics are lifted into an `Error envelope`,
so neither public result exposes the internal Raw run. The other channels
disclose none of these facts.
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

**Export artifact**:
What `gda export run` produces for a selected preset and names in its `output_path`.
Its format and contents remain Godot- and preset-owned; gda defines no
artifact-level content identity, manifest, provenance, or platform-format
classification (ADR-0042). Artifact smoke accepts only a direct host-runnable file,
plus a resolved `.app` executable on macOS; it does not infer or publish a broader
format model.
_Avoid_: build, bundle (macOS only), binary, release, receipt

**Artifact smoke**:
The bounded headless run of a caller-selected `Export artifact` that `gda export
smoke` performs. It is projectless: its descriptor does not inherit the cwd or
`GDA_PROJECT`, its command signature has no `--project`, and a relative filesystem
artifact path resolves against the invocation cwd. It runs the resolved Godot
executable unsandboxed with ordered caller arguments through the shared one-shot
launch mechanics (streaming capture, timeout, private `user://`, and diagnostics),
but owns its small public policy: normal completion returns exit status as data,
while `--strict` reports `smoke_failed` for a non-zero status or `shutdown_leak`.
The two artifact refusals and `smoke_failed` are classifier-source `operation`
codes with process exit 4; `smoke_failed` reuses `FailureEvidence.exit_status` and
`FailureEvidence.script_errors` (ADR-0042). Optional
`--quit-after FRAMES`, placed before Godot's `--`, asks the engine to exit normally
after that many process frames so shutdown diagnostics can run; omission or zero
disables it, and the wall-clock `--timeout` remains the external hard bound. This
engine flag asserts no project-specific completion. The result adds only the caller
artifact path and resolved executable path to the shared completed-run fields. It
has no completion marker, windowed mode, artifact identity, platform-format model,
provenance, or release-policy contract. This is a separate caller-artifact
execution point, outside the `Project-code execution surface` because gda cannot
tie the artifact to the resolved project. NOT a `Startup preflight`, which boots
one scene under the editor binary, and not a `Live operation`, which needs an
`Engine session`. Its trust subject is the caller-selected artifact, distinct from
the resolved `Trusted project` (ADR-0042).
_Avoid_: post-export test, launch check, release verify, smoke test (the project's
own tests are its own)

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
everywhere. That sameness covers numeric FIDELITY as well as shape: both of
gda's engine-side payloads frame their reply with Godot's full-precision JSON
writer — the harness since #752, the headless operations payload since #771 —
so a projected float is the exact binary64 the subject holds, on either
channel, with one shared residual the engine decides before the writer is
consulted: a negative zero reads back as `0.0`. The WRITE sides answer alike
from one principle, in two clauses — a literal the engine's parser reads as `0.0`
when the literal does not denote zero, or as `NaN` at all, is REFUSED, never
stored — but ask the question differently,
because the two know the literal at different times: on the live wire gda spells it,
so the refusal PREDICTS the outcome before the request is relayed (#752), while a
`--value` string is spelled by the CALLER, so `node set` / `resource set` /
`project set` and the live `game set` OBSERVE what that parser did (#772). Observing
covers every literal a `--value` spells, a CONTAINER's included: a `Dictionary` or
`Array` value has no per-element parse to observe — the coercion is
`JSON.parse_string` as a gate plus one atomic `str_to_var` — so its JSON numbers are
read from the RAW text, once the gate has accepted it, with string contents skipped so
that a numeric-looking VALUE or KEY is not mistaken for a number (#805). What the
parser produces bounds the rule on both sides: the low-order drift is disclosed
rather than refused, which the full-precision echo shows, and so is an OVERFLOW — a
`--value` of `1e400` is stored as the `inf` the parser saturates it to, since that
is the engine's number for the magnitude asked, not a different one put in its
place. Two controls keep the shared projection safe on the live side: the
whitelist bounds the Object classes whose storage properties the inline kind
emits, and the texture kind is safe by construction — a fixed getter shape with
its one expensive readback behind the explicit digest opt-in (ADR-0035).
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
successful result. It is what `--json` emits; without that flag the same failure
is RENDERED for a human instead — the code and its category on a head line, the
message, each optional typed key as a labelled line, then `diagnostics` verbatim
as real lines. Two renderings of ONE outcome, at one exit code, from one renderer
that keys on no `Gda error code` — the `usage` refusals included, since they answer
through this channel rather than through the parser's own error (#685). One case falls
outside it, by that channel's own rule: where gda has no correction to add AND no JSON
was asked for, it says nothing and the parser's message stands — silence rather than a
second gda layout.
_Avoid_: error blob, failure JSON

**Failure evidence**:
The typed facts BEHIND a verdict, carried on the `Error envelope`'s optional
`evidence` key (ADR-0004 amendment, #687) — never a substitute for branching on the
`Gda error code`, which stays the verdict. One fixed shape shared by every command,
because ADR-0004 fixes the `error` half as one schema identical for all; the
per-operation variability lives INSIDE it, every field individually optional and
omitted rather than null, so a timeout populates the clocks (`elapsed_seconds`,
`timeout_seconds`, `termination_phase`) while a `script run --strict` failure
populates the child's `exit_status`, and both carry the parsed `script_errors` where
the channel has them. The omitted-never-null rule governs the key and this object's
own fields, and stops there: a model NESTED inside it that is also published on a
success result keeps its full key set, so one record reads the same on both halves of
the contract. **Not** the free-form `diagnostics` string beside it — the two ship
together and say different things: `diagnostics` is the prose a human reads (the
recognized-error lines and the captured streams), evidence is the same facts typed
for a machine. That is why the streams are NOT duplicated here. ADR-0004's #687
amendment is the authority for what may enter the object and for the producer set
that carries it today; the short form is that a fact must already be computed on the
failure path, be unrecoverable without parsing prose, and change what the caller does
next. Third key on the axis that `probe` and `hint` established, and CLI-side like
`hint`: neither the GDScript sentinel's `OperationError` nor the harness's `LiveError`
emits or reads it.
_Avoid_: diagnostics, error context, error details

**Near-miss hint**:
The corrected invocation gda returns when it RECOGNIZES a wrong one — an unknown
command or option it holds a curated entry for (`gda scene inspect` → `gda scene
get`, `gda --schema` → `gda schema`). It rides the `Error envelope` as the optional
`hint` key, so an agent re-issues the corrected command without parsing prose; both
of that envelope's renderings carry it — the human one as its own `hint:` line,
beside the same correction in the message. Curated, never a
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
frames, beside the autoloads — the widest point on this surface. `gda resource
import` (#668) contributes two DISTINCT points: a fully
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
`gda game rect` (#852) contributes ONE narrow point too, and the caller does not
name it: the command reads the addressed Control's intrinsic minimum, and
`Control::get_minimum_size()` is the `_get_minimum_size` virtual with no cache,
so where a class leaves that getter to `Control` the node's script override of it
runs once per request, and twice where the combined read finds the minimum-size
cache stale. `get_combined_minimum_size()`, the other minimum the same result
reports, reads that cache first; where it is stale the read recomputes through
the SAME virtual, so it adds no point of its own.
All stay within the `Trusted project` assumption (ADR-0009); `script run`, the
loaded-value assignment (ADR-0033), the startup preflight, the import pass, the
declared method call, the minimum-size read, and the composed static validate
widen this surface without adding a new trust axis. Artifact smoke is outside this
surface: it is the separate caller-artifact execution point, with the second trust
subject stated in ADR-0042's Decision trust paragraph.
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
The single authoritative core phrase naming what `gda` *is* — "Godot automation for AI
agents" — front-loading the product category, engine, and audience. The README **H1** uses
that phrase in Title Case. The `pyproject` and GitHub repository descriptions lead with the
same phrase and extend it with the primary user outcome, three access paths, structured results,
and the two operation modes: "Godot automation for AI agents to build and verify projects through
a CLI, Agent Skill, or MCP server, with structured results, headless operations, and live runtime
control." These three surfaces change together and must not drift. The phrase names an automation
toolchain, not an agent.
_Avoid_: tagline, slogan, hero, the value sentence

**Brand slogan**:
The website-only brand promise — "The game dev arsenal built for AI agents." It leads
campaign and website hero copy, where the surrounding text supplies the literal product
category. It complements the `Positioning descriptor`; it never replaces the README H1,
package description, or GitHub repository description.
_Avoid_: positioning descriptor, product category, README title

**Verification message**:
The public evidence hierarchy for the verified agent workflow: Headless validation confirms
project readiness; Live operations return runtime evidence about actual behavior. Use both
parts when explaining how `gda` closes the loop beyond a file edit.
_Avoid_: treating a file edit as a verified game change, treating Headless and Live as rivals

**Access-path message**:
The public relationship among the three agent-facing channels — one `gda` operation surface,
three complementary access paths. The CLI executes operations directly, the Agent Skill gives
reusable guidance for choosing and running CLI commands, and `gda-mcp` maps the same public
Schema to MCP tools. The access path changes; the operations and structured results do not.
_Avoid_: three products, feature tiers, independent operation surfaces

**Hero**:
The README's opening *value* statement — what `gda` does for you ("Build and verify Godot
projects with AI coding agents, shell scripts, and CI"), followed by its shared operation
surface and structured-result proof. README-only and free to evolve there; it does **not**
mirror the extended metadata description and is never replicated into `pyproject` or the
repo metadata.
_Avoid_: tagline, subtitle, positioning descriptor
