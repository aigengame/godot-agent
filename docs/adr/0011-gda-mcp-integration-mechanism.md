---
status: accepted
---

# gda-mcp integration mechanism: a subprocess adapter over the gda CLI

ADR-0000 fixes the component order `gda → gda-mcp → gda-daemon` and frames
[gda-mcp](../../CONTEXT.md) as "a thin protocol adapter that wraps `gda`". ADR-0001
makes gda-mcp orthogonal to the delivery phases — first delivered on Phase 1,
following `gda` into Phase 2 automatically via the `--schema` self-description
(ADR-0004), never itself a phase. ADR-0004 / ADR-0005 specify the mechanical mapping
that lets gda-mcp generate its tool surface rather than hand-write it:
`gda <group> <command>` → MCP tool `<group>_<command>`, and `--schema`'s
`input` / `output` → the tool's `inputSchema` / `outputSchema`, with the uniform
`error` envelope routed to MCP's `isError` channel.

What ADR-0000 leaves open is *how* gda-mcp wraps `gda`: by invoking the CLI as an
external process (consuming its public ABI), or by importing `gda` in-process and
calling its Python symbols. The choice fixes gda-mcp's coupling to `gda` and — once
gda-daemon exists in Phase 2 — the topology of {gda-mcp, gda, gda-daemon}.

## Decision

**gda-mcp wraps `gda` as a subprocess.** It shells out to `gda` — invoked as
`[sys.executable, "-m", "gda", …]`, the *same-distribution* binary paired with the
running gda-mcp (the `[mcp]` extra), which is deterministic and cannot resolve a
*wrong global* `gda`, rather than a PATH lookup of the console script (#193 Design
decision 3; an optional `$GDA_BIN` escape hatch overrides it, ADR-0013) — and
consumes only `gda`'s **public CLI ABI** — *not* the internal sentinel protocol
ADR-0002 defines **between** `gda` and its headless operation subprocesses (which
`gda` already parses away before emitting its public output, and which ADR-0010's
native-CLI-mode operations do not emit at all). That public ABI is: the `--json`
success output, the structured `GdaError` envelope on a non-zero exit (the uniform
`GdaErrorEnvelope` of ADR-0004), the exit-code categories, and the `--schema`
self-description (ADR-0004). Operations are invoked per-command as
`python -m gda <group> <command> --params-json - --json`, forwarding the tool's
input object **verbatim** on stdin (ADR-0015's structured params channel — so
gda-mcp reconstructs no argv); the **tool surface is enumerated from the aggregate
schema dump** (ADR-0012), *not* a per-command `--schema` fan-out. gda-mcp does **not**
import `gda`'s Python modules or depend on any internal symbol.

**Error mapping is part of this mechanism, and is lossless.** gda-mcp keys on `gda`'s
exit code: exit 0 is success — the `--json` result becomes the tool's
`structuredContent` (validated against its `outputSchema`); any non-zero exit becomes
`CallToolResult(is_error=True)` carrying the **full** `GdaError` envelope
`{code, category, message, diagnostics}` **losslessly** as JSON in the result content.
The envelope is **never** flattened to a prose string — the stable `code` exists
precisely so an agent branches on it without parsing prose — and the `error` schema
stays out of `outputSchema` (ADR-0004). All non-zero categories (environment /
version / operation / parse / contract_violation, including launch failures) map
uniformly to `isError`; `category` / `code` distinguish them.

**Phase-2 topology — gda-daemon sits *below* `gda`, not beside gda-mcp.** This ADR
records the load-bearing assumption that makes ADR-0001's "gda-mcp follows `gda` into
Phase 2 automatically" literally true:

- In Phase 2 the **CLI `gda`** gains [live operations](../../CONTEXT.md) and routes
  them, internally, to gda-daemon over its IPC channel; gda-daemon owns the
  persistent engine and therefore the cross-call state (the subject of #5).
- Each `gda` invocation stays a one-shot, stateless RPC to the daemon and emits the
  **same** public `--json` / `GdaError` contract a headless op does.
- **gda-mcp always wraps the CLI and never speaks to gda-daemon directly.** The
  headless/live distinction stays invisible to gda-mcp exactly as ADR-0005 keeps it
  invisible in the command tree. gda-mcp therefore needs no IPC client and no
  per-phase work to cover live operations — it is a client of the daemon only
  transitively, through the CLI.

> Refined by ADR-0017 / ADR-0020 / ADR-0021: the gda-daemon design referenced below as
> "still-parked (#5, #7)" is now decided — ADR-0017 fixes its live-execution mechanism,
> ADR-0020 defines the "state consistency" (#5) this ADR anticipates, and ADR-0021
> fixes the daemon transport / discovery (the remaining #7 item). #7 is no longer parked.

## Considered options

- **In-process import (rejected).** gda-mcp imports `gda` and calls its
  functions/models directly. Rejected because: (1) it couples gda-mcp to `gda`'s
  internals instead of the frozen public CLI ABI that `--schema` (ADR-0004) exists to
  expose; (2) its only real upside is per-call speed, which is illusory in Phase 1 —
  every call's latency is dominated by Godot's own `--headless` spawn (60 s / 600 s
  timeouts), beside which a `gda` process start is noise; (3) it gets *worse* under
  the daemon — serving live ops in-process would pull gda-daemon's IPC-client code
  and connection lifecycle into the gda-mcp process, splitting ownership of the live
  session between gda-mcp and the CLI.
- **gda-mcp as a direct gda-daemon client (rejected).** Keep subprocess for headless
  ops but open a private IPC channel to gda-daemon for live ops. Rejected: it
  duplicates the daemon-client the CLI already carries, and it contradicts ADR-0001's
  "never itself a phase" by forcing per-phase transport work into gda-mcp.
- **gda-mcp hosting/embedding gda-daemon (rejected).** The daemon must serve every
  client (the CLI, other automation, multiple mcp sessions); it cannot live inside one
  mcp process. gda-mcp is a *client* of the daemon, never its host.
- **Subprocess adapter over the gda CLI (chosen).**

## Consequences

- gda-mcp's only dependency on `gda` is the public ABI. `gda` internals can change
  freely; as long as the ABI holds, gda-mcp is unaffected. gda-mcp also becomes the
  first real consumer of `--schema`, surfacing any contract gaps while the Phase-1
  surface is still fresh.
- A live op in Phase 2 has no Godot spawn to amortise the `gda` process start, so
  subprocess per-call latency becomes visible there. Accepted: it is a CLI-layer
  concern (it affects all `gda` automation, not just gda-mcp), to be solved at the
  gda / daemon layer if it ever bites; and at the MCP layer the consumer is an LLM
  agent whose model-in-the-loop latency dwarfs a process start.
- The Phase-2 topology above becomes a constraint on the still-parked gda-daemon
  design (#5, #7): the daemon backs the CLI, and "state consistency" (#5) is a
  property of the daemon holding the engine across one-shot CLI calls — gda-mcp does
  not participate in it.
- This ADR owns the integration mechanism **and its error mapping**. gda-mcp's
  packaging, tool-generation strategy, and transport are downstream and decided
  separately (ADR-0013, ADR-0012, and the PRD respectively).
