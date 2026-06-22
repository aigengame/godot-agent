---
status: accepted
---

# Live operation execution: a gda-owned running game with an in-engine harness, routed by an invisible channel selector

ADR-0001 split delivery into Phase 1 (headless) and Phase 2 (live) and named
[gda-daemon](../../CONTEXT.md) the carrier of all live-engine capabilities.
ADR-0011 then fixed the Phase-2 *topology*: the daemon sits **below** the CLI, each
`gda` call is a one-shot stateless RPC to it, and every call — headless or live —
emits the **same** public `--json` / `GdaError` contract, so the live/headless
distinction stays invisible (as ADR-0005 keeps it invisible in the command tree)
and gda-mcp follows into Phase 2 with no per-phase work. What neither ADR settled
is *how* the daemon serves a [live operation](../../CONTEXT.md): which engine it
holds, how a `gda` invocation reaches it, and how the daemon is brought up.

This ADR fixes that **mechanism and its running-game scope**. It does not enumerate
the live command catalogue, which is delivered incrementally per ADR-0005 and
tracked by the Phase-2 PRD (#6) and the gda-daemon feature (#7).

> **Outcome (2026-06-21, #7 / PR #229) — two scoped narrowings in the bootstrap:**
> (1) **Session mode.** The bootstrap's only live op is `game tree`, which reads the
> runtime `SceneTree` and needs no viewport, so its engine session is launched
> **`--headless`**, not windowed. The "windowed by default" of decision 2 below is for
> viewport capture; the daemon switches to a **windowed** session when the first
> capturing op lands (#222), which carries that change. (2) **Launch timing.** The
> session is **launched lazily on the first live op**, not eagerly at `daemon start` —
> consistent with this ADR's "(re)launched per feedback-loop iteration"; `daemon start`
> brings up the persistent daemon and the harness install, and the session follows on
> demand.

> **Outcome (2026-06-22, #220) — live op-errors are minted LIVE-category,
> classifier-source codes, one family per live op.** When `game get` / `game set`
> added the first live ops that report *operation-level* failures (a missing node,
> an unknown or uncoercible property — distinct from the daemon-channel failures
> `daemon_not_running` / `engine_disconnected`), the routing forced the code shape.
> The gda harness reports its op-error as the same ADR-0002 error envelope a
> headless op does, but the daemon relays the harness reply verbatim with
> **`exit_code = 0`**; the live classifier maps *only* codes whose category is
> `LIVE` before falling back to the shared decision tree, which on exit 0 would try
> to validate the error envelope as the success model and misreport
> `contract_violation`. So each harness-reported op-error **must** be a registered
> `LIVE`-category, classifier-source code (`live_node_not_found`,
> `live_unknown_property`, `live_uncoercible_value`). They are minted per live
> op-family (mirroring the headless `node_not_found` / `unknown_property` /
> `uncoercible_value`) and, being classifier-source, do not enter the
> operations.gd OP_ERROR mirror; a separate test mirrors them against the harness
> consts.

> **Outcome (2026-06-22, #223) — the time-windowed multi-frame mechanism is now
> IMPLEMENTED in the gda harness, realizing this ADR's one-shot RPC contract for a
> multi-frame op.** Until now every live op replied on a single frame. `perf monitor`
> (over N frames) needed a handler that spans frames, so the harness `_process` loop
> gained a multi-frame base: a handler that cannot finish in one frame opens a
> *window* (a frame budget + a per-frame sampler + a finalizer) instead of returning
> a payload; the loop advances the window one frame per tick, accumulates one sample
> per frame (frame-coherent, ADR-0020), and replies **once** with the whole timeline
> when the budget is met. This keeps the **one-shot RPC** this ADR prescribes — the
> client still issues one request and blocks for one reply — while the collection
> itself is multi-frame. A bounded frame ceiling fails a stalled/crashed window with
> `live_perf_timeout` (the time-windowed analogue of the boot guard), so a hung
> engine cannot hang the RPC forever. The base is general: #222's viewport capture
> reuses it by supplying its own sampler/finalizer, with no `_process` change.

## Decision

**1. An execution-channel selector, chosen per command by a static `kind`.**
Today `gda` already has two execution channels behind one dispatch — the
`operations.gd` sentinel runner and the native-export runner (ADR-0010), the latter
identified by an identity special-case (`cmd is EXPORT_RUN_COMMAND`). Phase 2
generalises this: each command carries a static `kind` (`HEADLESS` / `EXPORT` /
`LIVE`) in its descriptor, decided at command-definition time, and the runner
factory selects the channel by `kind`. A `LIVE` command's runner is a **daemon IPC
client** that returns the same `RunResult` and — critically — the **same
sentinel-delimited result payload** (ADR-0002) a headless subprocess returns. So
classification (`classify_run`), sentinel parsing, output-model validation, and
`--json` / `GdaError` emission are **reused unchanged**; the dispatcher gains
exactly one new decision and the `export run` special-case folds into the uniform
`kind` switch.

**2. The held engine is a gda-owned running *game*, not an attached editor.**
The daemon launches and holds a Godot **game** process running the trusted project,
and serves the **running-game context**: the runtime scene tree, runtime property
get/set, input simulation, viewport capture, and performance/signal monitoring —
the capabilities a one-shot headless process fundamentally cannot provide. The
**editor context** (UndoRedo-aware mutation, the editor's open-scene tree) is
**out of scope**: `gda` already authors scenes, scripts, and resources headless by
editing files, so an editor-attached mutation path would largely duplicate Phase-1
capability. The game runs **windowed** by default because `--headless` uses the
dummy `DisplayServer` and cannot capture a viewport.

**3. Code runs inside the engine via a gda harness, over a direct IPC connection.**
Live operations execute inside the game through the [gda harness](../../CONTEXT.md)
— a game-side autoload whose install and safety lifecycle is decided in ADR-0018 —
reached by a **direct** daemon↔harness connection, not an editor→game relay.

**4. A two-level lifecycle: a persistent daemon over transient engine sessions.**
A persistent, per-project `gda-daemon` (supervisor + IPC broker) holds transient
[engine sessions](../../CONTEXT.md). Lifecycle is **explicit**:
`gda daemon start` / `stop` / `status` form a **`daemon` command group** — named
after gda's own daemon (an infrastructure object), a deliberate extension of
ADR-0005's domain-object grouping, not a top-level meta singleton like `gda info` — and a
live [domain command](../../CONTEXT.md) **attaches-or-fails** — with no running
daemon it returns a typed `daemon_not_running` error whose message names the
remediation, making the start *timing* self-revealing without upfront ceremony.
The daemon is **never auto-spawned** by a live call: launching an engine runs the
project's autoloads (the [project-code execution surface](../../CONTEXT.md),
ADR-0009), a deliberate effect that must not hide behind a command. A session is
**(re)launched per feedback-loop iteration**, because an externally edited
`.tscn` / `.gd` is not reloaded by an already-running game.

**5. One-shot RPC preserved; time-windowed ops collected daemon-side.**
Each live `gda` call stays a single stateless RPC returning one payload (ADR-0011).
Inherently time-windowed live ops (frame capture, property/signal monitoring over N
frames) are collected daemon/harness-side and returned as **one** result — no
streaming enters the public contract.

**6. Live failures are classifier-source codes.** They are classifier-source
`GdaError`s (possibly under a new `ErrorCategory.LIVE`); the daemon IPC client
surfaces typed launch/transport failures the way ADR-0010's native runner keys on a
typed reason rather than overloaded exit codes. The names used illustratively in this
ADR (`daemon_not_running`, `engine_disconnected`, `live_timeout`,
`engine_session_not_running`, …) are **candidate codes, not accepted ABI**: each is
added to the `src/gda/error_codes.py` registry and the ADR-0002 table by the slice
that implements it (ADR-0002), not by this ADR. The agent-facing contract (typed
models, `--json`, `--schema` gate, registered `GdaError.code`s) is identical to
headless.

## Considered options

- **Attach to a human-opened editor via an EditorPlugin (godot-mcp-pro's model)** —
  rejected: it assumes a human has the editor open, but `gda` is agent-facing and
  often has no editor at all; it needs a GUI/display; and its main yield
  (editor-context UndoRedo mutation) duplicates `gda`'s headless authoring.
- **One-level lifecycle (daemon lifetime == game lifetime)** — rejected: a game
  crash would take the whole live context with it. The two-level split gives crash
  resilience and matches the per-iteration session relaunch of the feedback loop.
- **Auto-spawn the daemon/engine on the first live call** — rejected: it hides a
  heavy, autoload-executing side effect behind a command. The attach-or-fail typed
  error makes the start timing self-revealing without that hidden effect.
- **Per-call one-shot headless for live ops** — impossible by definition: there is
  no persistent engine to observe or drive.
- **A separate live channel in gda-mcp** — already rejected by ADR-0011; gda-mcp
  reaches the daemon only transitively through the CLI.

## Consequences

- New code is **contained**: a `kind` field on the command descriptor, one branch in
  the runner factory, a `DaemonRunner` IPC client, the daemon itself, the
  `gda daemon` lifecycle commands, the harness (ADR-0018), and a few error codes.
  Everything downstream of `runner.run()` is reused.
- Per-call `gda` process-start latency is no longer amortised by a Godot spawn for
  live ops — accepted in ADR-0011 as a CLI/daemon-layer concern.
- Live requires code inside the engine, so Phase 2 carries a **one-time harness
  install** (ADR-0018), unlike Phase-1's zero-install headless ops.
- Viewport capture requires a **windowed** game, hence a display dependency (a
  virtual framebuffer on headless CI). Recorded as an environment constraint.
- "State consistency" (#5) is now concretely scoped: the property of a per-project
  daemon holding one engine session across one-shot CLI calls and across multiple
  clients — **defined in ADR-0020** (which closes #5).
