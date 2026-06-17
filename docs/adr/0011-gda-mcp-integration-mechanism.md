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

**gda-mcp wraps `gda` as a subprocess.** It shells out to the installed `gda`
console script (`gda <group> <command> --json …`, and `gda <group> <command>
--schema` for tool generation) and consumes only `gda`'s **public ABI**: the
ADR-0002 sentinel-delimited JSON result / error envelope on stdout, the ADR-0002
exit-code categories, and the ADR-0004 `--schema` self-description. It does **not**
import `gda`'s Python modules or depend on any internal symbol.

**Phase-2 topology — gda-daemon sits *below* `gda`, not beside gda-mcp.** This ADR
records the load-bearing assumption that makes ADR-0001's "gda-mcp follows `gda` into
Phase 2 automatically" literally true:

- In Phase 2 the **CLI `gda`** gains [live operations](../../CONTEXT.md) and routes
  them, internally, to gda-daemon over its IPC channel; gda-daemon owns the
  persistent engine and therefore the cross-call state (the subject of #5).
- Each `gda` invocation stays a one-shot, stateless RPC to the daemon and emits the
  **same** ADR-0002 contract a headless op does.
- **gda-mcp always wraps the CLI and never speaks to gda-daemon directly.** The
  headless/live distinction stays invisible to gda-mcp exactly as ADR-0005 keeps it
  invisible in the command tree. gda-mcp therefore needs no IPC client and no
  per-phase work to cover live operations — it is a client of the daemon only
  transitively, through the CLI.

## Considered options

- **In-process import (rejected).** gda-mcp imports `gda` and calls its
  functions/models directly. Rejected because: (1) it couples gda-mcp to `gda`'s
  internals instead of the frozen public ABI that `--schema` / ADR-0002 exist to
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
- gda-mcp's packaging, tool-generation strategy, transport, and error-mapping
  fidelity are deliberately out of scope here; they are downstream of this mechanism
  and decided separately.
