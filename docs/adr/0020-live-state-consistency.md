---
status: accepted
---

# Live state consistency: single-writer serialization, frame-coherent, session-bound

ADR-0000 claimed "state consistency" as a headline advantage of `gda`; ADR-0001
scoped it to the Phase-2 live layer (Phase-1 headless calls are stateless); and #5
parked the precise definition until the daemon model was decided. With that model now
fixed — a per-project daemon holding a transient [engine session](../../CONTEXT.md)
(ADR-0017) under a single-driver trust boundary (ADR-0018) — this ADR defines the
guarantee and reconciles ADR-0000's blanket claim.

**Scope.** This is about the consistency of an *engine session's runtime state* only.
Disk↔runtime coherence is **out of scope**: an externally edited `.tscn` / `.gd` is
not reloaded by a running session, and the agent (re)launches the session to pick up
on-disk edits (ADR-0017). #5's question is only "within a session, what do live reads
and writes guarantee".

## Decision

`state consistency` is the property [gda-daemon](../../CONTEXT.md) provides over one
engine session's runtime state:

1. **Single-writer serialization.** The daemon serializes all live operations against
   the one engine session. Phase 2 supports a **single writer** (the driving agent),
   consistent with ADR-0018's single-driver boundary; any additional clients are
   **readers only**.
2. **Read-after-write within the driver's sequence.** Because calls are serialized and
   each returns only after it completes, a read issued after a write observes that
   write.
3. **Frame-coherent.** Each live op is applied/observed at a **frame boundary on the
   engine's main thread** (Godot requires scene-tree access on the main thread), so a
   single op is a coherent single-frame snapshot and a write applies atomically
   between frames. Time-windowed ops (monitor / capture over N frames) are explicitly
   multi-frame and return a per-frame timeline.
4. **Session-bound.** Runtime state lives in the engine session and does **not**
   survive its (re)launch (ADR-0017); consistency is scoped within one session.

**Reconciling ADR-0000.** Its blanket "state-consistent" advantage holds **only** for
this Phase-2 live layer under these scoped guarantees — not for the stateless Phase-1
headless CLI (ADR-0001). Recorded here and via a pointer on ADR-0000.

## Considered options

- **Multi-writer concurrent clients** — rejected for Phase 2: it contradicts the
  single-driver boundary (ADR-0018) and would need a full concurrency protocol
  (locking, ordering, cross-client visibility) disproportionate to an agent-facing
  tool. If multiple agents co-writing one live engine is ever required, it warrants
  its own ADR **superseding** this one.

## Consequences

- The guarantee is simple and testable: serialize live calls against one session and
  assert read-after-write and frame-coherent snapshots; no concurrency protocol to
  verify.
- `state consistency` becomes a defined CONTEXT.md glossary term, closing #5.
- **Multi-writer is the explicit no.** A future need supersedes this ADR rather than
  stretching it.
