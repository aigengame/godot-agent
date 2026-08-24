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

> **Amendment (2026-07-31, #590):** Initialization is an atomic pre-Event phase over one immutable
> Initialization frame assembled from admitted Experiment inputs, constants, parameters, and
> declared initial base state. Formula sites read only that frame and explicit operands. Successful
> initialization validates all initial values and atomically commits Snapshot 0; refusal or resource
> exhaustion discards the frame and publishes no Snapshot, Event, trace, Evaluation, Metric, or
> terminal audit. The original “Snapshot boundary exists initially” and broad Runtime-refusal
> wording retained below therefore apply only after successful initialization and Event dispatch.
> bADR-0022 separately owns Formula-result caching semantics and its conformance vector.

> **Amendment (2026-08-03, #594):** Runtime admission resolves one closed Experiment Event plan,
> assigns every authored root Event a stable Runtime identity before dispatch, and exposes the
> complete `root_event_ref → event_id` map. An internal scheduler transition dispatches one Event;
> public `step` advances to the next declared observation or logical boundary. These are not a
> universal tick or a second Experiment timeline.

> **Amendment (2026-08-04, #595):** A Model entrypoint may declare a typed Event-reference operand.
> Its Experiment transition binds the operand's role to one authored `root_event_ref` in the same
> Scenario, and Runtime resolves it to the target's already admitted `event_id` before dispatch.
> The Kernel `cancel` target therefore admits either a scheduled-Event local produced in the active
> transaction or an exact Event-reference port; it never admits ambient queue lookup. Same-time
> roots remain sequential atomic transactions, and Runtime infers no defeat, interruption, or
> eligibility policy from health-like state.

> **Amendment (2026-08-04, #596):** A Domain-package Operation may implement one bounded periodic
> lifecycle only by scheduling ordinary child Events through this same queue. The selected package
> owns duration/period, tick/expiry times, capture/read policy, contribution and outcomes; Runtime
> owns generic schedule admission, total order, budgets, atomicity and Snapshot visibility.
> Snapshot magnitude evaluates once in apply's pre-Event committed frame and is carried as a typed
> scheduled argument; live magnitude evaluates in each tick's own pre-Event committed frame. An
> apply transaction buffers its state writes, Named-stream draw and every scheduled child together,
> so Formula, Numeric or schedule refusal publishes none of them. A tick sharing logical time with
> an ordinary Event observes only the latest previously committed Snapshot under the existing
> phase/priority/enqueue order. No Effect loop or repeated Scenario becomes a second time authority.

> **Amendment (2026-08-12, #640):** The Kernel `guard-block` node is allowed only in a top-level
> Operation body. It reads one already produced Kernel Boolean. False charges only the guard step,
> skips the body without RNG, writes, or effects, and continues the enclosing body. True executes
> its non-nested body in authored order and, unless a node refuses, completes the Operation with one
> declared outcome. bADR-0022 defines and closes the body grammar, including the rule that only a
> typed refusal can stop the selected body early. The Kernel `require` node
> compares an already produced Kernel Boolean with its
> Boolean `expected` member. A mismatch raises one Operation-declared, LDB-resolved typed refusal;
> a match continues. The refusal terminates the run and reuses the existing Event-refusal boundary:
> state writes, RNG continuation, buffered child Events, Metrics, and Snapshot publication are
> rolled back, and later nodes do not execute. Executed node steps and the terminal audit remain
> execution facts. bADR-0015 defines the terminal audit's guard-expanded `instruction_index`. This
> differs from a completed `gameplay-alternative`; that outcome follows its
> declared state policy and retains any RNG draws that led to the completed Event. An
> `operation-execution` refusal vector observes the post-rollback state and committed RNG projection,
> not discarded attempt logs.

> **Amendment (2026-08-24, #545):** Exact Replay uses one closed, LDB-owned Replay comparison
> policy. The first policy, `exact-replay-v1`, requires equality for every reproduction identity and
> a fixed, ordered set of observation checks. The caller cannot select fields, omit checks, or
> override a tolerance. Runtime preparation produces the Evaluator Capability Manifest, Resolved
> Runtime profile, and Reproduction receipt without Event dispatch. Replay compares these prepared
> values with the authenticated original Evaluation run and dispatches only after all preconditions
> match. `standard.experiment@1.1.0` owns the policy under
> `language.replay_comparison_policies`. Domain Comparison semantics consumes the admitted policy and
> the complete original and Replay observations; it performs no implicit store lookup. The prepared
> values and comparison inputs are internal. They are not new authorities or public artifacts.

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

- **Root Event admission is deterministic and identity-bearing.** Every authored root member has a
  unique stable `root_event_ref`. The Runtime admits root members in their canonical authored-array
  order, allocates each Runtime-owned `event_id`, and assigns initial enqueue sequence in that order
  before dispatch. Equal logical time is legal; Event identity, object-map iteration, wall clock,
  threads, and evaluator parallelism never break ties. The admission result exposes the exact root
  reference map, while later schedule operations return and trace their Runtime-owned child
  `event_id`.

- **Root kind fixes phase through the Kernel contract.** The Kernel scheduler maps authored
  `external-input` roots to `input` and `transition-invocation` roots to `transition`; the host
  neither repeats that map nor assigns a phase from local conditionals. Observation phase and
  priority are likewise Kernel-owned derived values.

- **The three phases have non-overlapping ownership.** `input` admits the externally supplied,
  source-sequenced facts for that logical time and cannot be scheduled by model operations.
  `transition` executes model actions, effects, resource changes, combat, generation, and other
  stateful events; domain packages express finer ordering through typed events and priority rather
  than new core phases. `observation` reads the final committed state after the transition queue for
  that time is drained and emits metrics/evidence only; it cannot mutate model state, consume model
  resources, or schedule another event at the same logical time. A later Domain package therefore
  cannot acquire a hidden scheduler slot.

- **Public `step` is boundary-directed.** One internal scheduler transition dispatches exactly one
  atomic Event. A public `step` repeatedly applies those transitions until the next declared
  observation or logical boundary, then returns the newly committed boundary. Queue drain and the
  Experiment's declared multi-step terminal condition end a run. An `event-count.maximum` is the
  first eligible termination count, not permission to cut a phase in half: after reaching it, the
  Runtime drains the active logical-time transition phase and terminates at the next `step`
  boundary, so the reported Event count can exceed that threshold but cannot advance into the next
  logical time. `event-steps` is an Operation resource counter, not logical time; there is no fixed
  tick.

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

- **Event atomicity and invocation publication atomicity are distinct contracts.** An Event
  transaction decides whether one runtime transition changes the committed Snapshot, RNG streams,
  and event queue. It does not by itself decide when a command's RIR, trace, Metric, Evaluation, or
  Evidence artifacts become visible. bADR-0021 owns that invocation-level multi-artifact commit
  boundary; neither a successful Event nor an atomic file rename proves an atomically published
  command result.

- **Runtime refusal rolls back only the current event and terminates the run.** Its buffered writes,
  RNG draws, emitted Signals, child events, and cancellations are discarded. Earlier committed
  snapshots remain valid. The refusal produces a separately typed **terminal-audit artifact set**
  identifying the ordered committed trace prefix, last committed Snapshot, refusing event,
  rollback facts,
  Diagnostic, Resolved Runtime profile, and exact reproduction identities. The invocation publishes
  that set
  and its receipt atomically under bADR-0015/0021; it never publishes a completed Evaluation run,
  Metric dataset, positive Evidence assertion, or another partial success artifact. No package may
  convert a Runtime refusal into a skipped event or continue under partial state. Domain-level
  failures intended as gameplay branches must be modeled as closed typed outcomes, not refusals.

- **Scheduling cannot travel backward.** A transaction may schedule later logical time, a later
  phase at the same time, or a zero-time `transition` child whose complete ordering key is strictly
  after the active event's key. For the same time and phase, a child priority greater than the
  active priority is therefore refused; equal priority remains after the active event through the
  later runtime-assigned enqueue sequence. Only the runtime admits `input` events; `observation` is
  read-only and cannot schedule. A transaction may never enqueue into an already completed time,
  phase, or queue position. Illegal scheduling is a Runtime refusal. Deterministic caps on zero-time
  derivation depth, total events, and queue size bound cycles and denial-of-service behavior.
  A successful schedule provisionally admits a stable child `event_id` immediately and buffers its
  queue visibility; later operations in the same transaction may address that pending identity.
  Commit makes each uncanceled child visible under the same queue law, while refusal discards the
  provisional admission with the other Event buffers. The trace binds the scheduling call site,
  parent Event, child Event, complete ordering key, and commit outcome.

- **Cancellation is prospective and identity-based.** Every admitted event has a stable `event_id`.
  The Kernel `schedule` node produces a scheduled-Event reference, and `cancel` consumes that
  reference through its declared target-reference shape; the generic invocation operand inventory
  does not broaden cancellation targets.
  Cancellation may target only an event that has not begun dispatch; canceling an absent, completed,
  or active event produces the LDB-owned Runtime refusal for that exact target state and never
  rewinds committed state. A Domain operation may expose a typed alternative only where its declared
  contract explicitly maps that refusal before the scheduler boundary. Undo is represented by an
  explicit compensating event or a higher-level rollback model, not by scheduler time travel.
  Cancellation is buffered with the active transaction and traces the canceling Event/call site,
  target identity, and typed result. A successful commit removes only an admitted pending target;
  refusal restores both the queue and cancellation state.

- **Reaction and priority windows are bounded Domain protocols, not hidden scheduler phases.** A
  package may represent a proposed action, eligible responders, pass state, nested responses, and a
  pending resolution stack as ordinary nominal state. External choices enter only through declared
  later `input` boundaries; advancing scheduler logical time to such a boundary does not by itself
  advance a package-owned round, turn, cooldown, or game-world clock. `transition` Events open,
  advance, or close the window and schedule final resolution only after the package's closed
  pass/priority rule completes. Counter, replacement, or
  cancellation targets stable pending-action/event identities and remains prospective. The package
  declares maximum response depth, pass count, candidate count, and event budget. It cannot enqueue
  a backward `input`, create a fourth phase, suspend an active Event while calling host code, or
  reinterpret Signal delivery as an interactive callback. This protocol lets card-style priority,
  counterspells, and readied actions compose over the fixed scheduler without changing core
  semantics.

- **Gameplay compensation is not Event rollback.** Package outcomes such as refund, release,
  reversal, or compensation are ordinary committed domain transitions and may occur in a later
  Event. `rollback` never erases an earlier Snapshot. For a refusing Event, it discards every
  uncommitted buffer at the Event-refusal boundary. For a completed outcome whose state policy is
  `rollback`, it discards the current Event's state writes but retains the declared outcome and any
  RNG draws that led to it. A terminal audit must distinguish prior committed state from the
  refusing Event's discarded writes, events, cancellations, and RNG draws.

- **External input enters only at declared boundaries.** Each input carries a stable source identity
  and monotonically increasing source sequence. At an input boundary, the runtime admits inputs in
  `(source identity, source sequence)` order into the fixed input phase. Duplicate, missing when the
  contract requires continuity, or decreasing sequence numbers are refusals. Wall-clock arrival
  order and thread scheduling are never semantic inputs.

- **A Snapshot boundary exists initially and after every successful event.** The semantic snapshot
  includes all persistent state and scheduler state required to resume deterministically. Evidence
  may record a canonical hash at every boundary and materialize full snapshots only at declared
  checkpoints; storage optimization cannot change the conceptual boundary or replay trace. The
  Snapshot identity therefore projects both the committed state values and the complete resumable
  Runtime continuation: lifecycle and `step` boundary, Scenario cursor, admitted/pending Event
  catalog, committed trace, current Snapshot coordinate, Named RNG state, resource ledger, next
  enqueue sequence, root-Event map, and Resolved Runtime profile identity. Materialized Snapshot
  Series encode every complete normalized admitted Event specification once, with its independently
  recomputable identity, and bind each boundary to append-only catalog/trace prefix identities and
  counts. Recovery replays those prefixes and cancellation provenance against the cross-bound Event
  Trace to reconstruct the exact pending queue. It also re-derives root entries from the checked
  Experiment, observations from their Metrics, and scheduled entries from the committed parent's
  schedule provenance plus the exact RIR call path/site, scheduling Operation, ordering, normalized
  actual arguments, and state references. This provenance covers schedule nodes in a root Operation
  or any admitted nested Operation and preserves `port`, `local`, and literal operand execution.
  Recovery boundedly replays that admitted RIR path from the committed parent inputs and state to
  recompute the schedule operands. A Named-RNG-derived local is recomputed from the checked seed and
  independently verified committed draw prefix; the draw trace is evidence to check, not its own
  value authority.
  Self-consistent fresh hashes are not Event admission. A growing queue or committed
  prefix is never copied into every Snapshot.

- **Fairness is explicit and bounded.** FIFO holds within equal time, phase, and priority. There is
  no promise that a lower priority event preempts a finite higher priority chain. Deterministic
  zero-time and total-event budgets prevent an unbounded chain from silently starving the queue;
  exhaustion is a Runtime refusal with the last committed snapshot preserved.

- **Budgets are independent and observable.** Runtime node-step, per-Event operation-step, queue,
  zero-time-depth, total-Event, and logical-time limits have distinct authority paths and counters.
  Exhausting one cannot be reported as another or reset outside its declared scope: node steps are
  per run, Event steps per Event transaction, total Events per Scenario, and queue/logical/depth
  counters follow their declared queue or Event scope. The Resolved Runtime profile and terminal
  audit expose the selected limits and consumed boundary.

- **Randomness is stream-scoped and normatively mapped.** Stochastic operations read only a Named
  random stream derived from the effective root seed and stable stream identity under the selected
  Runtime profile definition. There is no ambient global RNG. An unrelated stream's insertion
  or consumption cannot perturb another stream. The Schema-major Kernel Specification fixes the
  irreducible seed/stream encoding, domain separation, derivation, counter/state, bit extraction,
  and sampling primitives. The exact Runtime profile definition carried by the Language Definition
  Bundle selects their admitted parameters and the mapping to each Distribution result, including
  rejection sampling or an explicitly accepted bias policy. Host-library defaults and modulo
  mappings not named by that authority chain are non-conforming. Normative first-draw, multi-draw,
  cross-stream, exhaustion, and distribution-boundary vectors make the law independently
  implementable. A draw budget counts every generated candidate, including candidates rejected by
  an unbiased mapping, rather than only accepted samples; the trace records candidate counter,
  value, and acceptance so resource accounting and replay remain observable.

- **Profile definition and execution admission are separate artifacts.** The Language Definition
  Bundle owns each immutable Runtime profile definition: scheduler/phase semantics, budget names and
  accounting units, Named-stream derivation, Numeric/RNG policy, permitted effects, primitive
  requirements, overflow, and portability constraints. It contains no owning-bundle identity,
  evaluator build, host platform, or deployment fact. Before the first event, tooling generates and
  validates a **Resolved Runtime profile** binding one selected definition to the exact Kernel
  Specification, Language Definition Bundle, selected Package Lock, Resolved Model/RIR semantic
  payload, evaluator/platform scope, and
  concrete deterministic budgets. A missing, incompatible, or out-of-profile primitive/effect is a
  stage-appropriate refusal; host code may not execute behavior merely because it implements it.
  During execution, budget and declared-effect accounting is deterministic and observable.
  The Kernel owns the definition identity domain and its complete-definition projection. Runtime
  admission derives that identity from the selected LDB definition and binds it into the Resolved
  Runtime profile alongside the Evaluator Capability Manifest identity. Neither authority artifact
  refers back to the generated profile, so the three identities are distinct and acyclic. The
  Kernel also declares the active-definition member/binding shape and positive-bound contract;
  concrete bound values remain LDB content and are never duplicated as host constants.
  Its Runtime-program component contract names the complete scheduler, Runtime-configuration,
  transition, and step role set; closes every nested object consumed by execution; and relates
  lifecycle, boundary, and scheduler-phase inventories. Hosts implement this abstract role
  meta-protocol but do not own the declared paths or concrete tokens. The complete role-to-path,
  member-shape, and relation mapping is content-addressed separately; an evaluator admits only a
  mapping identity it explicitly implements, so structural changes require a matching evaluator
  capability update. That component-contract identity does not separately pin concrete behavioral
  token values: exact Kernel identity plus the complete scheduler conformance-vector suite protects
  them, so every Kernel identity rotation must rerun both consumers before their support identity is
  updated.

- **Evaluator capability is explicit implementation provenance, not semantic authority.** Each
  evaluator build publishes an immutable **Evaluator Capability Manifest** naming the exact Kernel
  law versions, closed constructors, Numeric/RNG policies, scheduler/effect features, artifact
  schemas, and resource-accounting contracts it implements. Runtime admission validates that
  manifest against the exact Kernel/LDB, selected Package Lock/RIR projection, Runtime profile
  definition, and requested comparison policy, then binds its identity and validation receipt into
  the Resolved Runtime profile. The manifest cannot admit an operation absent from the LDB, weaken a
  law, or authorize host behavior; it only makes unsupported implementation surface fail before
  dispatch. Such a mismatch is a plain `resolution` refusal: no Resolved Runtime profile, Event, or
  terminal-audit artifact exists yet. It is distinct from bADR-0016's generated Capability
  manifest, which describes the selected model/package graph rather than evaluator support.

- **Determinism is scoped by the Resolved Runtime profile.** That artifact plus exact
  Resolved Model, Experiment Specification, external input, and effective seed identities forms the
  reproduction key. The LDB-owned definition and generated resolved artifact cannot identify each
  other recursively.

- **Exact replay and cross-evaluator conformance are different judgments.** A Replay comparison
  requires one identical Resolved Runtime profile and every other reproduction-key identity to
  match. Independent evaluators truthfully produce different evaluator/platform-bound Resolved
  Runtime profiles, so their observations are compared only through a separately typed
  **Cross-evaluator comparison**. That comparison binds both profiles, the exact common Kernel
  Specification/LDB/Package Lock/Resolved-Model/RIR-semantic-payload/Runtime-profile-definition/
  Experiment/input/seed identities,
  an exact LDB-owned Portable Observation Policy, and its generated Resolved Portable Observation
  Plan. It may support `cross_evaluator_conformant` Evidence under bADR-0018, but it is not replay
  and cannot issue `reproducible`.

- **Portable observations are derived by one closed, non-vacuous LDB policy.** A
  **Portable Observation Policy** has its own stable id, version, content identity, applicable
  Runtime/Numeric profile definitions, closed selector grammar, mandatory observation classes,
  canonical projection/comparator mapping, and deterministic closure/order algorithm. Before
  comparison, that algorithm produces a generated **Resolved Portable Observation Plan** binding
  the exact policy, common Runtime profile definition, selected Package Lock/RIR, Experiment
  Specification, and selected vectors. The plan enumerates every required observation contract;
  each names a semantic selector, observation kind, canonical projection, and comparator. It is a
  validated projection, never an authored authority or a copy of Experiment intent.

  The closure includes every observation required by the common profile, reachable selected
  package-release contracts, exact Experiment, and selected vectors: applicable operation outcomes,
  state/Snapshot projections, Event and Signal order, logical Named-stream samples, Effect lifecycle
  transitions, Metrics, typed refusals, and terminal-audit facts. Exact values, nominal identities,
  kinds, units, discriminators, order, and Diagnostic codes use exact comparison; admitted inexact
  Numeric values use only the tolerance law fixed by the common Runtime/Numeric profile definition.
  Evaluator build ids, platform-specific receipt fields, Locators, and EIR are bound provenance but
  are not portable semantic observations.

  A comparison binds the exact plan, retrieves both complete observation sets, and reports every
  missing, unexpected, or mismatched contract in plan order. Empty policies/plans; optional omission
  of a required observation; unknown or duplicate selectors; evaluator-specific selectors; and
  tolerance widening beyond the common profile are typed `evaluation` refusals. An observed value
  mismatch is a completed negative Verdict. Policy and plan identities enter the prerequisite graph,
  so neither the caller nor the comparison tool can select only fields that happened to agree.

- **Numeric promises are profile-specific.** A portable exact profile can promise cross-platform
  bit identity only for standardized exact/fixed operations and sampling mappings. A profile that
  admits platform-native floating operations promises replay only within its declared evaluator,
  runtime, platform, and ULP contract recorded by its Resolved Runtime profile. Standard Schema 2.x
  makes no unconditional cross-platform byte-equality claim.

- **This decision supersedes bADR-0010's 2.x reproduction scope, not its current CLI convention.**
  Explicit stochastic seeds, fresh entropy when omitted, and unconditional effective-seed echo are
  retained. For 2.x, `(seed, input, toolkit version)` is no longer a sufficient reproduction key;
  the artifact and Resolved Runtime profile identities above are required. bADR-0010's
  unsigned-32-bit CLI
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

- The Schema-major Kernel Specification fixes irreducible transition, Numeric, and RNG/sampling
  primitives; the Language Definition Bundle carries the exact scheduler/profile parameters,
  runtime diagnostics, canonical snapshot/hash rules, and conformance vectors admitted under them.
- RIR operations and package extensions must declare state read/write sets, emitted event types,
  cancellation behavior, and reducers sufficiently for static and runtime enforcement.
- Repeated execution inside one evaluator/platform scope must emit the same ordered trace under an
  identical Resolved Runtime profile, subject only to the selected definition's numeric tolerance.
- Independent evaluators run under their own Resolved Runtime profiles and must agree on the
  complete required portable observations selected by one exact LDB-owned Portable Observation
  Policy and its Resolved Portable Observation Plan; their
  agreement is conformance evidence, not an exact replay identity claim.
- Experiment and evidence artifacts must bind external-input identity, effective seed, Runtime
  profile, terminal snapshot, and refusal details.
- The 2.x invocation-result decision must assign Runtime refusal an envelope, output channel, and
  exit status without overloading validation refusal or balance verdict.

## Validation

- Repeat one run under the same exact Resolved Model wrapper/RIR semantic payload, Experiment
  Specification, Resolved Runtime profile, external
  inputs, and effective seed; compare ordered events, committed Snapshot hashes, Named-stream draws,
  Metric observations, terminal status, and terminal-audit artifacts through a Replay comparison.
- Run the same exact Resolved Model wrapper/RIR semantic payload, Experiment Specification, Runtime
  profile definition, external inputs, and seed
  through independent evaluators under their distinct Resolved Runtime profiles; require a
  separately typed Cross-evaluator comparison to bind both profiles and evaluate the exact declared
  portable observations under the exact Portable Observation Policy and Resolved Portable
  Observation Plan. It must neither masquerade as Replay nor issue `reproducible`.
- Reject empty, under-covering, duplicate-selector, unknown-selector, evaluator-specific, and
  tolerance-widening Portable Observation Policies or Resolved Portable Observation Plans. Mutate
  or omit one required outcome,
  Snapshot field, event/signal order item, RNG sample, Effect transition, Metric, refusal, or
  terminal-audit fact and require a deterministic refusal or negative comparison rather than a
  vacuous positive claim.
- Exercise proposal, response, nested counter, pass, cancellation/replacement, and final-resolution
  windows across declared input boundaries. Assert bounded Domain state and ordinary transition
  Events preserve the fixed three phases and prospective cancellation; hidden phases, backward
  inputs, host callbacks, and unbounded response depth must refuse.
- Remove one required entry from an Evaluator Capability Manifest or add an unsupported host-only
  feature. Runtime admission must refuse before dispatch; changing only the manifest/build
  provenance must rebind the Resolved Runtime profile without changing Kernel/LDB semantics.
- Cover every scheduler edge and budget with positive and refusal vectors: phase/priority/FIFO
  order, backward scheduling, cancellation, queue/event/zero-time exhaustion, undeclared streams,
  and primitive/effect-profile incompatibility.
- Apply bADR-0022's Formula-cache conformance vector to the Runtime ledger and require its
  cache-on/cache-off result, charge, and exhaustion observations to remain identical.
- Inject a fault after an event has buffered writes, RNG draws, Signals, cancellations, and
  children; assert all are rolled back, prior commits remain, and exactly one retrievable
  terminal-audit artifact set becomes visible with no completed success artifact.
- Trigger one initialization Formula refusal before Snapshot 0 commits. Assert a `runtime`-stage
  refusal with exact Initialization-frame and Formula-site provenance, no Event/rollback claim, no
  Snapshot/trace/terminal audit, and no completed Evaluation/Metric artifact.
- Commit a resource reservation, then execute a later compensating interruption whose current
  Event exceeds a deterministic budget. Assert the prior reservation Snapshot and trace remain,
  only the current buffers are rolled back, and the terminal audit identifies the first refusing
  Event plus a complete Diagnostic. Profile or Experiment admission refusal before dispatch must
  produce no terminal audit.
- Supply first-draw, stream-independence, mapping-boundary, bias-policy, counter-exhaustion, and
  Numeric overflow/rounding vectors whose canonical observations agree across implementations.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0010 — Standard Schema 1.x seed surfacing and determinism scope.
- bADR-0012 — language and artifact authority domains.
- bADR-0013 — compiler stages and RIR semantic boundary.
- bADR-0015 — refusal envelopes and terminal-audit receipts.
- bADR-0021 — invocation-level artifact-set publication.
- bADR-0022 — Kernel Specification and machine-readable language rules.
