---
status: accepted
---

# Runtime diagnostics via a daemon-owned session log

> Outcome (2026-06-24, #281): the raw **`diag log`** described below is
> **superseded by `gda logger tail`** — the structured runtime-log channel
> (ADR-0026). `gda logger tail` parses the *same* daemon-owned Session log into
> typed `LogRecord`s by default (and preserves the verbatim lines under `--raw`),
> while **`diag` retains `errors` only**. The daemon-side read path this ADR
> established is unchanged — `logger tail` is a second daemon-served log op
> reading `session.log_file`, exactly like `diag errors`; only the surface and the
> default output shape changed. References below to `diag log` / the `diag-log` op
> name describe the original `diag`-only state and are kept point-in-time.

`gda diag` reads the running game's runtime diagnostics — its errors and its
output log — over the live channel (story group, #224). This needs the running
game's error stream and its `print()` output, but Godot exposes neither to
GDScript in memory: there is no in-process hook for the engine's error handler or
for stdout. The only place the engine collects BOTH streams together is the file
its logger writes. An earlier instinct — point the session at the shared
`user://logs/godot.log` — is exactly the path that caused the #180 contention
crash: `user://` resolves to one per-project log dir, and overlapping launches
(parallel agents, a CI matrix) race in `RotatedFileLogger::rotate_file()` and
abort with what looks like `engine_crashed`. So the capture must be isolated, and
something other than the (possibly hung or crashed) game must read it.

## Decision

`gda diag` is a **daemon-served** [live operation](../../CONTEXT.md): it is a
`kind = LIVE` command routed to [gda-daemon](../../CONTEXT.md) like any other, but
the daemon serves it **directly from a log file it owns**, never relaying it to
the [gda harness](../../CONTEXT.md).

1. **The daemon launches each [engine session](../../CONTEXT.md) with Godot's
   `--log-file <session path>`**, where the path is under the daemon's own private
   runtime directory (keyed by the same project slug as its sockets/pidfile), NOT
   `user://logs`. Verified against the engine (`main/main.cpp`, `core/io/logger.cpp`):
   `--log-file` forces file logging ON even when the project disables it, and the
   `RotatedFileLogger(path, max_files=1)` it installs writes BOTH output and errors
   to that exact path and TRUNCATES it (`FileAccess::WRITE`) on each launch.

2. **The daemon remembers that path** for its whole lifetime (on the session
   object), so it can read the file even after the session process has exited.

3. **The daemon serves `diag` by reading and parsing that file** in Python
   (`gda.daemon.diag`), recognizing the `diag-errors` / `diag-log` op names in its
   request handler and short-circuiting to the log read rather than relaying to the
   harness. It serves `diag` **even when the session process has died** — it
   requires only that a session was launched this daemon lifetime; with none it is
   `engine_session_not_running`, and with a remembered session whose log file is
   missing/unreadable it is the new `live_log_unavailable`. An empty log is an
   empty result, not an error. v1 returns the current session's log with no
   incremental offset; `--limit N` tails the most recent N entries.

The error parser reads Godot's two-line format — `<TYPE>: <message>` then
`   at: <function> (<file>:<line>)` — normalizing `<TYPE>` (ERROR / WARNING /
SCRIPT ERROR / SHADER ERROR) to a machine-stable `level` (warnings included, told
apart by `level`). It is best-effort: an unrecognized or continuation line (a
multi-line backtrace, interleaved print output) is skipped and never fails the
parse.

## Considered options

- **Daemon launches with `--log-file` and reads the file daemon-side** (chosen) —
  captures errors AND output in one file; isolates per session so it sidesteps the
  #180 `user://logs` contention by isolation (not by disabling logging — disabling
  would lose the data); truncate-per-launch makes the capture session-bound
  (ADR-0020); the reader is the daemon, which survives the game, so a crash stays
  diagnosable.
- **The harness reads the file and replies over IPC** (rejected) — fragile exactly
  when it matters: if the game has hung or crashed, the harness cannot reply, so
  the most valuable diagnostic (the crash) becomes unreadable.
- **A custom GDScript logger that captures errors/print in memory** (rejected) —
  the engine exposes no such hook to GDScript; there is nothing to subscribe to.
- **The shared `user://logs/godot.log`** (rejected) — reintroduces the #180
  rotate-file race under overlapping launches.

## Consequences

- One file captures both the running game's errors and its output, read back by
  the daemon to serve `diag errors` and `diag log`.
- The #180 shared-log contention is sidestepped by per-session isolation, with file
  logging left ON (the data is the point) rather than disabled.
- The capture is bound to the session: it is truncated on each (re)launch, so `diag`
  reports the current session's state and a relaunch (to pick up on-disk edits,
  ADR-0017) starts a fresh log. Reads are best-effort at the engine's flush
  boundary — a diagnostic written but not yet flushed when `diag` reads may be
  missed; the daemon does not force a flush.
- The daemon reads a log file IT created and owns — engine infrastructure, not the
  project's own semantics — so the ADR-0009 / ADR-0017 trust and editor-context
  boundaries are unchanged: `diag` introspects the running game's reported output,
  not the editor.
