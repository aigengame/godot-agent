---
status: accepted
---

# Structured runtime log protocol: `gda logger` over the session log

A live `Engine session` produces runtime output an agent needs to analyse. Today `gda`
surfaces it two ways: `diag log` returns the **raw** verbatim lines, and `diag errors` returns
**structured engine errors** (`{level, message, function, file, line}`) parsed from the
[Session log](../../CONTEXT.md) (ADR-0022). What is missing is a **structured channel for the
game's own logging** — info/debug/custom records, with levels and fields — and `diag log` itself
is unstructured. This ADR adds `gda logger`: a structured runtime-log channel and the protocol
that backs it. It is in scope under ADR-0025 (read-only observability is in; interactive debugging
is out) and deliberately does **not** tap Godot's remote-debug protocol.

## Decision

**1. `LogRecord` — the structured unit.** One typed model (backing `--json` / `--schema`):
`{seq, level, message, source?, fields?}`, where `level ∈ {error, warning, script_error,
shader_error, info, debug, …}`, `source` carries `{function, file, line}` when known, and
`fields` is an optional object for app-supplied structure.

**2. A two-layer log protocol, overlaid.** Both feed the same `LogRecord` stream:

- **Passive (always on, non-invasive).** The daemon parses the *whole* Session log into
  `LogRecord`s: engine errors/warnings via the existing `diag` parser (carrying `source`), and
  every other line as a plain `info` record. An un-instrumented project gets structured logs for
  free.
- **Active (opt-in, rich).** The [gda harness](../../CONTEXT.md) exposes `gda_log(level, message,
  fields = {})`, which emits **one sentinel-delimited JSON line** into the engine log using a
  **distinct `<<<GDA:LOG>>>{…}` marker** (a separate marker family from ADR-0002's single
  `<<<GDA:RESULT>>>` so a log line can never be mistaken for an op result). The daemon recognises
  these lines and parses them into field-carrying `LogRecord`s. A game that opts in gets fully
  structured, typed logs.

The two compose per line: a `<<<GDA:LOG>>>` line → rich record; an engine error/warning prefix →
typed error record; otherwise → plain `info` record.

**3. Built on the Session log, not a new IPC channel.** The protocol writes into the engine
`--log-file` the daemon already owns (ADR-0022). This reuses existing capture, **survives a session
crash** (records persist with the rest of the log), needs **no stateful per-call buffer**, and keeps
the **one-shot RPC** model (the daemon reads the file on demand). Retrieval is a **batch**, never a
stream: `gda logger [--level <min>] [--limit <N>] --json` → `LogRecord[]` (most-recent-N, session-
bound, truncated per launch like the log).

**4. Surface (taxonomy).** A new **`logger`** live command group — the running game's structured
log stream as a domain object, placed by domain object and marked `LIVE` by `kind` (ADR-0019). The
old **`diag log` (raw) is folded into `gda logger`**, whose default output is structured
`LogRecord`s; a `--raw` option preserves the verbatim view. **`diag` retains `errors` only** (engine
errors, gaining callstacks in a sibling slice). Errors therefore appear in both surfaces by design:
`gda logger` is the full stream; `diag errors` is the focused, callstack-enriched error view. This is
a pre-1.0 CLI change (ADR-0008 versioning applies).

## Considered options

- **A harness→daemon IPC log sink (rejected for now).** A structured channel over the live IPC.
  Rejected: needs a stateful per-session buffer, does **not** survive a crash, and duplicates the
  Session-log capture the daemon already owns (ADR-0022). The sentinel-in-log reuses it.
- **A custom engine `Logger` via `OS.add_logger` (rejected).** Would structure *all* output at the
  sink, but is not reliably reachable from GDScript (needs C++/GDExtension) — too heavy for the
  harness.
- **Passive-only (rejected).** Cannot carry app-level levels/fields; the opt-in protocol adds the
  rich structure.
- **Opt-in-only (rejected).** Un-instrumented games would get nothing structured; passive parse is
  the non-invasive floor.

## Consequences

- New `logger` group + `LogRecord` model + harness `gda_log()` + the `<<<GDA:LOG>>>` marker + a
  daemon log-parser extension. Reuses Session log (ADR-0022), the sentinel idea (ADR-0002), and the
  one-shot RPC contract (ADR-0011 / 0017).
- `diag log` is superseded by `gda logger`; `diag errors` stays (and gains callstacks separately).
- The `<<<GDA:LOG>>>` marker must be distinct from `<<<GDA:RESULT>>>` and is documented alongside the
  ADR-0002 contract; live op results travel over IPC, app logs travel in the Session log — different
  streams, no collision.
- Frame-coherence (ADR-0020) is not required: the log is append-only and read on demand.
- Realized by the `gda logger` slices in the **Live run & debug** milestone (#5).
