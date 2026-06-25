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

> **Outcome (2026-06-25, #283) — `diag errors` gained the `callstack`.** The baseline shape above
> (`{level, message, function, file, line}`) is the pre-#283 state; `diag errors` now additionally
> carries an ordered `callstack: SourceFrame[]` of `{function, file, line}` frames (decision 4's
> "callstack-enriched view"), parsed from the Session-log `GDScript backtrace`. Realized by the
> error-callstack slice #283; see ADR-0022's #283 outcome note.

> **Amendment (2026-06-25, #281) — the read result is `LoggerTailResult { records: LogRecord[] }`,
> the passive parse is whole-log lossless, and `--raw` returns info records.** Decision 3 wrote the
> read contract as "→ `LogRecord[]`"; it is delivered as a single-field result object
> `LoggerTailResult` whose `records` **is** that `LogRecord[]` — mirroring how `diag errors` delivers
> `DiagError[]` as `DiagErrorsResult.errors` (the established wrapper convention; one output model
> keeps the `--schema` projection well-defined). There is **no** second `lines` field. `--raw` returns
> the **same** shape with every captured line as an unclassified `info` record carrying its verbatim
> text (not a separate `{lines: str[]}` shape), so the channel is uniformly typed `LogRecord[]`.
> Honouring decision 2's "the daemon parses the **whole** Session log … every other line as a plain
> `info` record", the passive parse is **lossless**: an engine error/warning becomes a typed record
> (its `at:` folded into `source`), and **every other line — including the `GDScript backtrace`
> continuation lines after an error — becomes a plain `info` record** (a first implementation that
> dropped those continuation lines was corrected). Errors thus still appear in both surfaces by
> design: `logger tail` is the full stream; `diag errors` is the focused, callstack-enriched view.

## Decision

**1. `LogRecord` — the structured unit.** One typed model (backing `--json` / `--schema`):
`{seq, level, message, source?, origin?, fields?}`. `level` is a **closed, ordered severity enum**
— `debug < info < warning < error` — so `--level <min>` filtering is a well-defined contract
(ADR-0004); the engine's finer kinds map onto it (`WARNING` → `warning`; `ERROR` / `SCRIPT ERROR` /
`SHADER ERROR` → `error`), with the sub-kind preserved in the optional `origin` field
(`engine | script | shader | gda_log`). `source` carries `{function, file, line}` when known, and
`fields` is an optional object for app-supplied structure (opt-in records only).

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
stream — the read command is **`gda logger tail`** (group `logger` + verb `tail`, conforming to
ADR-0005's `gda <group> <command>` shape): `gda logger tail [--level <min>] [--limit <N>] [--raw]
--json` → `LogRecord[]` (most-recent-N, session-bound, truncated per launch like the log; `--raw`
yields the verbatim lines `diag log` returned).

**4. Surface (taxonomy).** A new **`logger`** live command group — the running game's structured
log stream as a domain object, placed by domain object and marked `LIVE` by `kind` (ADR-0019), with
the read verb **`gda logger tail`** (ADR-0005 `<group> <command>` shape). The old **`diag log` (raw)
is superseded by `gda logger tail`**, whose default output is structured `LogRecord`s; `--raw`
preserves the verbatim view. **`diag` retains `errors` only** (engine errors, gaining callstacks in a
sibling slice). Errors therefore appear in both surfaces by design: `gda logger tail` is the full
stream; `diag errors` is the focused, callstack-enriched error view. This is a pre-1.0 CLI change
(ADR-0008 versioning applies); the public-doc reconciliation lands with the implementation slice (see
Consequences).

## Considered options

- **A harness→daemon IPC log sink (rejected for now).** A structured channel over the live IPC.
  Rejected: needs a stateful per-session buffer, does **not** survive a crash, and duplicates the
  Session-log capture the daemon already owns (ADR-0022). The sentinel-in-log reuses it.
- **A custom engine `Logger` via `OS.add_logger` (rejected as the channel sink).** Godot *does*
  expose this to GDScript — `OS.add_logger(Logger)` is bound (`core_bind.cpp`) and `Logger` has
  script-overridable `_log_message(message, error)` / `_log_error(…, TypedArray[ScriptBacktrace])` —
  so the earlier "needs native code" worry was wrong. It is rejected here for real tradeoffs: a custom
  in-process sink **duplicates** the Session-log file capture the daemon already owns (ADR-0022), is
  **not crash-survivable** (its buffer dies with the process, unlike the file), and `_log_message`
  sees only the final formatted string (no app fields) — so it would *not* replace the opt-in
  `gda_log()` for rich records anyway. (Its `_log_error` `ScriptBacktrace` payload is a separate,
  legitimate route for the error-callstack slice #283 — a different decision from this channel sink.)
- **Passive-only (rejected).** Cannot carry app-level levels/fields; the opt-in protocol adds the
  rich structure.
- **Opt-in-only (rejected).** Un-instrumented games would get nothing structured; passive parse is
  the non-invasive floor.

## Consequences

- New `logger` group + `LogRecord` model + harness `gda_log()` + the `<<<GDA:LOG>>>` marker + a
  daemon log-parser extension. Reuses Session log (ADR-0022), the sentinel idea (ADR-0002), and the
  one-shot RPC contract (ADR-0011 / 0017).
- `diag log` is superseded by `gda logger tail`; `diag errors` stays (and gains callstacks
  separately). This ADR *records* that supersession; the reconciling public-doc edits — a dated
  outcome note on **ADR-0022**, and the `docs/command-catalog.md` / README updates that still list
  `diag log` — are made by the implementation slice **#281**, not pre-emptively here (the catalog
  tracks the surface as it ships; committed status lives in the issue tracker).
- The `<<<GDA:LOG>>>` marker must be distinct from `<<<GDA:RESULT>>>` and is documented alongside the
  ADR-0002 contract; live op results travel over IPC, app logs travel in the Session log — different
  streams, no collision.
- Frame-coherence (ADR-0020) is not required: the log is append-only and read on demand.
- Realized by the `gda logger` slices in the **Live run & debug** milestone — issues **#281** (passive
  channel) and **#282** (the `gda_log()` opt-in protocol). (Referenced by name, not as bare `#5`,
  which would mis-link to the unrelated issue #5.)
