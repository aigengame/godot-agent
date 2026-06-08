---
status: accepted
---

# Godot integration: headless CLI first, live engine via daemon later

`gda` needs a mechanism to drive Godot. The two reference implementations sit at
opposite poles: `godot-mcp` spawns a one-shot `godot --headless --script` process
per command (standalone, stateless, but limited and slow, and blind to a running
editor), while `godot-mcp-pro` runs a Godot editor plugin and talks to it over a
persistent WebSocket (rich, real-time, UndoRedo-aware, but requires a running
editor with the plugin installed).

We adopt a **hybrid, delivered in two phases**:

- **Phase 1 — Headless operations.** `gda` fulfils [headless operations](../../CONTEXT.md)
  by spawning one-shot `godot --headless` processes. It is standalone and depends
  on no service. This is the first delivery and matches the "bottom-up, simple-first"
  goal in ADR-0000.
- **Phase 2 — Live operations.** Operations that require an already-running engine
  (live scene tree, runtime inspection, UndoRedo, input simulation) are served over
  an IPC channel to a persistent engine, owned by `gda-daemon`.

This reframes `gda-daemon`: it is not merely an optional performance layer (as
ADR-0000 implies), but the **necessary carrier of all live-engine capabilities**.

## Considered options

- **Pure headless** (like `godot-mcp`) — simplest, but permanently incapable of
  live introspection, UndoRedo, or input simulation.
- **Pure plugin/IPC** (like `godot-mcp-pro`) — most capable, but every operation
  then requires a running editor + installed plugin, contradicting the "standalone"
  goal and raising the cost of the first usable slice.
- **Hybrid, phased** (chosen) — ship the standalone headless CLI first, unlock live
  capabilities later through the daemon channel.

## Consequences

- The "high-performance / state-consistent" advantages claimed for the eventual
  system in ADR-0000 do **not** apply to the Phase-1 headless CLI: spawning a
  process per call is slow, and each call is stateless. Those properties arrive
  with `gda-daemon` in Phase 2.
- `gda-mcp` is orthogonal to these phases: it is a thin adapter first delivered on
  top of Phase 1, and it follows `gda` into Phase 2 automatically via the `--schema`
  self-description (ADR-0004) rather than needing per-phase work. It is never itself a
  phase; its order relative to other components follows ADR-0000 (after `gda`).
