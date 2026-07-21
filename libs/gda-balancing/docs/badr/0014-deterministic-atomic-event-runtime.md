---
status: accepted
---

# Execute deterministic atomic event transactions under an explicit runtime profile

RIR is the public semantic boundary (bADR-0013), but a model is not reproducible until execution
defines ordering, state visibility, conflicts, cancellation, rollback, external inputs, random
streams, and resource exhaustion. A tuple such as `(time, phase, priority, sequence)` is
insufficient unless direction, snapshot boundaries, and scheduling legality are normative. A seed
alone is likewise insufficient when numeric behavior, evaluator code, RNG algorithms, or event
policies can differ.

Standard Schema 2.x needs one deterministic state-transition model that is implementable by a
simple reference evaluator and optimizable by other evaluators without giving them observable
scheduling freedom. PRD #534 makes that runtime contract a human decision gate.

## Decision

- **The runtime is a sequential scheduler of atomic Event transactions.** It maintains immutable
  committed state at Snapshot boundaries and a totally ordered event queue. Exactly one event is
  dispatched at a time by the normative scheduler. Parallel evaluators may speculate internally,
  but their commits and observable trace must match the sequential semantics.

- **Runtime events carry a complete stable ordering key.** Events are ordered by:
  1. logical time, ascending;
  2. phase according to the versioned fixed order `input`, `transition`, `observation`;
  3. signed priority, descending — a larger value runs first;
  4. enqueue sequence, ascending — FIFO for otherwise equal keys.
  The enqueue sequence is assigned monotonically by the runtime when an event is admitted. Models
  and packages cannot supply it or reorder/extend the phase table.

- **The three phases have non-overlapping ownership.** `input` admits the externally supplied,
  source-sequenced facts for that logical time and cannot be scheduled by model operations.
  `transition` executes model actions, effects, resource changes, combat, generation, and other
  stateful events; domain packages express finer ordering through typed events and priority rather
  than new core phases. `observation` reads the final committed state after the transition queue for
  that time is drained and emits metrics/evidence only; it cannot mutate model state, consume model
  resources, or schedule another event at the same logical time. A later Domain package therefore
  cannot acquire a hidden scheduler slot.

- **Each event is one atomic transaction over the latest committed state.** Dispatch reads the
  snapshot produced by the previous successful event, including events at the same logical time.
  State writes, emitted Signals, child events, and cancellations are buffered. A successful handler
  commits them together and creates the next Snapshot boundary. An event cannot observe its own
  buffered writes unless an operation explicitly defines a local accumulator.

- **Signals are intra-transaction facts, not Runtime events.** An emitted Signal has a nominal
  type and payload. The Model Source Package authors game-specific subscriptions; static
  resolution validates each subscriber against Language Definition Bundle signal/effect laws and
  lowers the topology into the Resolved Model. Subscribers execute in ascending Resolved-symbol
  identity order against the same committed pre-event snapshot. Their declared, bounded writes and
  child events contribute to the active transaction buffers under the normal one-final-write rule.
  Signal emission and subscriber observations enter the ordered trace only when the transaction
  commits. A Signal is never queued, persisted, scheduled, or delivered through evaluator callbacks.

- **Every state slot has at most one final write per event.** Independent contributions to one slot
  must flow through a declared reducer or composition operation with specified ordering/algebraic
  properties. Multiple hidden assignments are a compile-time refusal where statically knowable and
  otherwise a Runtime refusal. Sequential event order resolves writes between different events;
  there is no implicit last-writer-wins merge inside one event.

- **Runtime refusal rolls back only the current event and terminates the run.** Its buffered writes,
  child events, and cancellations are discarded. Earlier committed snapshots remain valid and the
  terminal evidence identifies the last commit, refusing event, diagnostic, and Runtime profile.
  No package may convert a Runtime refusal into a skipped event or continue under partial state.
  Domain-level failures intended as gameplay branches must be modeled as typed outcomes, not
  refusals.

- **Scheduling cannot travel backward.** A transaction may schedule later logical time, a later
  phase at the same time, or a zero-time `transition` child whose complete ordering key is strictly
  after the active event's key. For the same time and phase, a child priority greater than the
  active priority is therefore refused; equal priority remains after the active event through the
  later runtime-assigned enqueue sequence. Only the runtime admits `input` events; `observation` is
  read-only and cannot schedule. A transaction may never enqueue into an already completed time,
  phase, or queue position. Illegal scheduling is a Runtime refusal. Deterministic caps on zero-time
  derivation depth, total events, and queue size bound cycles and denial-of-service behavior.

- **Cancellation is prospective and identity-based.** Every admitted event has a stable `event_id`.
  Cancellation may target only an event that has not begun dispatch; canceling an absent, completed,
  or active event follows the operation's declared typed outcome and never rewinds committed state.
  Undo is represented by an explicit compensating event or a higher-level rollback model, not by
  scheduler time travel.

- **External input enters only at declared boundaries.** Each input carries a stable source identity
  and monotonically increasing source sequence. At an input boundary, the runtime admits inputs in
  `(source identity, source sequence)` order into the fixed input phase. Duplicate, missing when the
  contract requires continuity, or decreasing sequence numbers are refusals. Wall-clock arrival
  order and thread scheduling are never semantic inputs.

- **A Snapshot boundary exists initially and after every successful event.** The semantic snapshot
  includes all persistent state and scheduler state required to resume deterministically. Evidence
  may record a canonical hash at every boundary and materialize full snapshots only at declared
  checkpoints; storage optimization cannot change the conceptual boundary or replay trace.

- **Fairness is explicit and bounded.** FIFO holds within equal time, phase, and priority. There is
  no promise that a lower priority event preempts a finite higher priority chain. Deterministic
  zero-time and total-event budgets prevent an unbounded chain from silently starving the queue;
  exhaustion is a Runtime refusal with the last committed snapshot preserved.

- **Randomness is stream-scoped.** Stochastic operations read only a Named random stream derived
  from the effective root seed and stable stream identity under the Runtime profile's versioned RNG
  algorithm and derivation contract. There is no ambient global RNG. An unrelated stream's
  insertion or consumption cannot perturb another stream. Exact algorithms and sampling mappings
  belong to the Language Definition Bundle/runtime-profile specification and normative vectors.

- **Determinism is Runtime-profile scoped.** The profile identifies the Language Definition Bundle,
  scheduler contract, evaluator build, platform/runtime scope, Numeric profile, RNG algorithm and
  derivation version, and deterministic budgets. Together with exact Resolved Model, Experiment
  Specification, external input, and effective seed identities, it forms the reproduction key.

- **Numeric promises are profile-specific.** A portable exact profile can promise cross-platform
  bit identity only for standardized exact/fixed operations and sampling mappings. A profile that
  admits platform-native floating operations promises replay only within its declared evaluator,
  runtime, platform, and ULP contract. Standard Schema 2.x makes no unconditional cross-platform
  byte-equality claim.

- **This decision supersedes bADR-0010's 2.x reproduction scope, not its current CLI convention.**
  Explicit stochastic seeds, fresh entropy when omitted, and unconditional effective-seed echo are
  retained. For 2.x, `(seed, input, toolkit version)` is no longer a sufficient reproduction key;
  the artifact and Runtime-profile identities above are required. bADR-0010's unsigned-32-bit CLI
  encoding and current envelopes remain binding until the 2.x CLI decision explicitly replaces
  them. Standard Schema 1.x continues under bADR-0010.

## Considered options

- **Sequential atomic events with a total order** (chosen) — gives one simple reference semantics,
  deterministic state visibility, and a comparison target for parallel evaluators.
- **Batch all simultaneous events against one snapshot** (rejected) — requires a universal merge
  algebra for arbitrary writes and makes order-sensitive game mechanics unnatural or implicit.
- **Implementation/thread order** (rejected) — cannot be replayed or compared across evaluators.
- **Implicit last-writer-wins inside one event** (rejected) — hides conflicts and makes declaration
  reordering semantic.
- **Continue after runtime failure** (rejected) — permits partial transactions and divergent traces;
  expected gameplay failure must be an explicit modeled outcome.
- **Ambient global RNG** (rejected) — unrelated changes perturb every downstream sample and destroy
  orthogonality.
- **Blanket cross-platform bit identity** (rejected) — contradicts native floating behavior and the
  existing numeric contract; portability must be an explicit Numeric profile property.

## Consequences

- The Language Definition Bundle must encode the fixed phase order and scheduling edges, runtime
  diagnostics, RNG algorithms/derivation, Numeric profiles, and canonical snapshot/hash rules.
- RIR operations and package extensions must declare state read/write sets, emitted event types,
  cancellation behavior, and reducers sufficiently for static and runtime enforcement.
- The reference evaluator and every optimizing evaluator must emit the same ordered trace under an
  identical Runtime profile, subject only to the profile's declared numeric tolerance.
- Experiment and evidence artifacts must bind external-input identity, effective seed, Runtime
  profile, terminal snapshot, and refusal details.
- The 2.x invocation-result decision must assign Runtime refusal an envelope, output channel, and
  exit status without overloading validation refusal or balance verdict.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0010 — Standard Schema 1.x seed surfacing and determinism scope.
- bADR-0012 — language and artifact authority domains.
- bADR-0013 — compiler stages and RIR semantic boundary.
