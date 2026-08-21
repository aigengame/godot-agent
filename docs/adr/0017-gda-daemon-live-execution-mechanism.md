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
> demand. (Since #224 not every live op needs a session; the 2026-08-21 amendment below
> restates the trigger precisely.)

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
> itself is multi-frame. The window finalizes on its sample count and the requested
> frame count is bounded model-side (`PerfMonitorParams`, ADR-0015), so the window
> has no timeout of its own; a genuinely stalled engine — which never advances the
> window at all — is caught by the daemon-level `live_timeout`, the real
> stalled-engine guard. The base is general: #222's viewport capture reuses it by
> supplying its own sampler/finalizer, with no `_process` change.

> **Outcome (2026-06-22, #222 / PR #248) — the windowed session is a start-time
> declared mode, refining the #7 note above.** #222 adds `screen capture` / `screen
> frames` (viewport capture), the first ops needing a real `DisplayServer`. The #7 note
> anticipated the daemon "switches to a windowed session when the first capturing op
> lands"; #222 does **not** switch mid-session. A relaunch would discard the session's
> accumulated runtime state and silently re-run autoloads, breaking ADR-0020's
> session-bound consistency and this ADR's "deliberate, declared effect". Instead the
> display mode is declared once at `gda daemon start --windowed`; the `--headless`
> session stays the cheap default (decision 2's "windowed by default" becomes an
> explicit per-session opt-in), and a capture op on a headless session fails with the
> typed `live_display_unavailable` naming the remediation. The capture handlers reuse
> the #223 time-windowed base — a 1-frame window for a single shot, an N-frame window
> for a sequence — so the one-shot RPC contract holds.

> **Amendment (2026-06-24, #278) — the session may run a *chosen scene*, not only the project's
> `main_scene`.** Decision 2 holds the running *game* but never fixed *which* scene it boots; the
> session has so far run the project's configured `main_scene`. To serve "run a specific scene" —
> the F6-equivalent the engine exposes natively as `godot --scene <path|UID>` (verified to run that
> scene without mutating `main_scene`) — the session launch gains an **optional scene selector**.
>
> **Public surface — `gda daemon start --scene <path|UID>`.** It is a **start-time daemon option**:
> the daemon holds the value and passes it to the engine as `--scene <path|UID>` (an engine option,
> before `--path`) when the session is **lazily launched** (the #7 note above, restated precisely by
> the 2026-08-21 amendment: on the first operation that requires a session).
> With no `--scene`, behaviour is unchanged (runs `main_scene`). The selector accepts a scene **path
> or UID** (per Godot's `--scene`). Any `scene play` / `game run` ergonomic wrapper is a **separate
> follow-up**, not part of this amendment.
>
> **Failure semantics — typed error, never a silent fallback.** A missing or non-existent scene
> selector **must** surface a typed `GdaError` (a `LIVE` classifier-source code minted by the slice,
> per decision 6 below); it must **not** silently fall back to `main_scene`. A typed failure beats a
> wrong positive path the agent cannot detect.
>
> **Trust boundary unchanged.** Launching a chosen scene runs that scene's `_ready` and game code —
> the **same trusted-project / project-code execution surface** that running `main_scene` and every
> mutating op already cross (ADR-0009, ADR-0018), not a new boundary. It does **not** reach the
> out-of-scope editor context (there is no editor "current scene").
>
> This is a deliberate **extension** of Decision 2's running-game scope, not a reversal: still a
> gda-owned game, headless by default, same harness and live surface (ADR-0019 / 0020), only with a
> chosen entry scene. The selector-less default is unchanged. Realized by the run-a-scene slice
> (#278); the surface-inclusion rationale (why `run` is in scope at all) is recorded in ADR-0025.

> **Amendment (2026-08-21, #657) — when a session is launched, and when it is still serving.**
> Two clarifications; the lazy-launch decision itself is unchanged.
>
> **Launch trigger — say "requires", not "live op".** The #7 note above reads "launched lazily on
> the first live op", true when every live op needed a session. It no longer is: `gda diag errors`
> and `gda logger tail` are live operations the daemon serves from the Session log it owns, and they
> deliberately launch nothing (ADR-0022). The precise rule, and the wording every public surface
> uses, is that a session launches on **the first operation that REQUIRES an Engine session**.
> `gda daemon wait-ready` is the explicit, bounded way to BE that operation — the documented
> alternative to firing a throwaway read — so an agent can establish the session up front and have
> its first real read serve, including a first `diag errors`. It is one command in the `daemon`
> group carried on the live channel (`kind = LIVE`, the `diag errors` precedent); the group-module
> consequence is recorded on ADR-0040.
>
> **Serving state — the process AND the channel.** A session is serving only while its harness
> channel can still answer the operation that asked. The daemon therefore marks the channel stale
> on a dropped or closed connection AND on a relay that timed out: this ADR's one-op-at-a-time RPC
> carries no request id and a timed-out frame is not drained, so a late reply would be read as the
> NEXT operation's reply — a validly-framed, semantically wrong answer (reproduced in #725's
> re-review). A stale session is rebuilt through the same lazy-launch boundary, so `live_timeout`
> costs a relaunch and, per ADR-0020, the runtime state does not survive it. Correlating replies
> instead would change the cross-language harness protocol and is left to its own decision.
>
> **One deadline, owned by the launch boundary.** Everything that boundary does on a caller's
> clock draws from a single deadline: retiring the session being replaced, the spawn, the
> connect, each handshake frame, and the teardown of a failed launch. It travels as an
> **absolute instant**, never as a duration — a duration restarts whatever clock receives it,
> which is how an exhausted budget came back whole for a replacement launch. When the instant
> has passed, the boundary REFUSES rather than launching past it.
>
> Four consequences are not obvious. A socket timeout bounds *inactivity*, so a frame read in
> chunks must recompute the remaining budget per read or a trickling peer holds the reader
> indefinitely — the daemon serves one request at a time, so that is every later request too.
> Retirement is not free: an engine that ignores `SIGTERM` is escalated with what the deadline
> has left, not with a fresh grace. Collecting a killed child is a duty but not the caller's
> time, so it happens in the background — best-effort, since SIGKILL cannot be caught and the
> cost of a rare miss is one process-table entry the daemon's own exit clears. And the spawn is
> the one step that cannot be interrupted once begun: the deadline is checked before it and
> governs everything after, so a spawn that outruns the budget ends in a refusal rather than in
> a session that came up late.
>
> The same rule applies to the op relay's own `live_timeout` ceiling, which had the same
> inactivity shape. Accepted deliberately, and beyond what the `wait-ready` slice needed: a
> trickled reply now reaches that ceiling where before it completed, and since a timed-out relay
> marks the channel stale, the consequence is a relaunch and the loss of runtime state. The
> alternative was to keep publishing a bound that was not one.

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
