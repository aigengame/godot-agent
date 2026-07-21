# Standard Schema 2.0 dogfooding feedback

These findings come from implementing, exercising, and independently reviewing the throwaway
tracer. They are design feedback,
not hidden requirements and not closure evidence for the Genre coverage matrix.

## DF-01 — Language rules need a closed fact and premise ontology

- **stage:** LDB bootstrap, static semantics, and HIR-to-RIR lowering.
- **observed evidence:** The first compiler version used bundle rules only to retrieve diagnostic
  codes while Python conditionals decided validity. A mutated `type.equal` rule therefore had no
  semantic effect. The second iteration adds a small interpreter for `truthy`, `equal`,
  `set_equal`, and `contains`, but the host still defines the fact bindings, premise meanings,
  control flow, and all runtime semantics. A rule-mutation vector can demonstrate local admission
  influence; it cannot validate LDB authority.
- **expected contract:** bADR-0022 requires structured premises and conclusions to be the language
  authority rather than a diagnostic catalog around compiler code.
- **provisional choice:** Use a four-operator bootstrap interpreter for limited admission checks,
  describe it as a prototype correction rather than a complete rule system, and retain a mutation
  vector that must fail if a consulted rule is removed or changed.
- **classification:** Standard Schema design gap.
- **spec action:** Define the complete fact vocabulary, term types, premise operators, binding and
  substitution law, rule selection, missing-fact behavior, and canonical conclusion construction;
  add mutation and independent-interpreter vectors.
- **claim impact:** The tracer supports only local layer integration. It cannot claim that the LDB
  is the semantic authority, that the evaluator is non-fixture-specific, or that the rule ontology
  is exhaustive.

## DF-02 — Artifact identity is specified more clearly than artifact transport

- **stage:** `model build` to cross-process `experiment run`.
- **observed evidence:** A process-local RIR would have hidden the most important boundary. The
  tracer needed a new local store, identity-to-path mapping, collision checks, and read-time
  rehashing before a second process could execute by RIR identity. Per-file atomic replacement was
  initially mistaken for atomic publication of the build receipt and all of its artifacts.
- **expected contract:** bADR-0012/0013/0021 require immutable content identities and public build
  receipts, but do not yet fix storage, locator, transfer, retention, or garbage-collection shapes.
- **provisional choice:** A caller-supplied, prototype-only directory stores canonical artifacts as
  `<sha256>.json`; a staged batch becomes visible only when one committed index is atomically
  replaced. Deterministic pre-commit faults must leave that index and its visible files unchanged.
  Paths remain non-portable.
- **classification:** Standard Schema design gap.
- **spec action:** Specify artifact envelopes, locator/receipt types, the invocation-level commit
  boundary, atomic multi-artifact publish/read behavior, crash recovery, verification,
  missing-artifact refusal, transport independence, and lifecycle expectations.
- **claim impact:** Cross-process identity flow and one logical batch-visibility mechanism are
  exercised for one local filesystem store. Crash/concurrency semantics, a portable artifact ABI,
  and a production store are not validated.

## DF-03 — Exact experiment binding creates an intentional rebinding workflow

- **stage:** authoring and build/evaluation handoff.
- **observed evidence:** Adding a second target changed AST/HIR/RIR identities, so both Experiment
  Specification fixtures had to bind the new RIR identity before they could run.
- **expected contract:** The Experiment Specification owns evaluation intent and binds an exact
  Resolved Model identity or an explicit compatibility contract without redefining the model.
- **provisional choice:** Fixtures use exact identity; no compatibility selector or automatic
  rebinding is implemented.
- **classification:** Standard Schema workflow gap.
- **spec action:** Define the authoring/build/rebinding workflow, compatibility-binding syntax,
  final bound-identity receipt, and review semantics when a model rebuild changes identity.
- **claim impact:** Exact identity binding is explicit, but reproducibility, authoring ergonomics,
  and safe experiment reuse remain unproven.

## DF-04 — Gameplay outcomes need a closed discriminated-result contract

- **stage:** resource reservation and operation result typing.
- **observed evidence:** `game.resource.reserve@1` can return `status: insufficient` as a gameplay
  outcome, but the prototype's `Record:Reservation` signature does not formally close the status
  variants or require callers to branch before commit. The coverage id
  `rpg.resource.insufficient-refused-v1` also says “refused” while bADR-0014/0015 require expected
  gameplay failure to be a typed outcome, not a Runtime refusal.
- **expected contract:** Domain operations expose complete typed outcomes; refusal is reserved for
  inability to execute the declared semantics.
- **provisional choice:** Keep the insufficient status in the record and do not claim or exercise
  that negative vector.
- **classification:** Standard Schema design gap and Genre matrix terminology defect; not a
  template-default problem.
- **spec action:** Define discriminated Record/Enum outcome encoding and exhaustiveness rules, then
  rename the vector to `rpg.resource.insufficient-outcome-v1` and specify commit behavior.
- **claim impact:** `RPG-COST-01` is not closed by this prototype.

## DF-05 — The RNG mapping must be normative, including bias policy

- **stage:** named-stream sampling.
- **observed evidence:** The selected `SHA-256(seed, stream, counter)` algorithm can replay the same
  fixture draws, but mapping a 64-bit prefix with modulo 100 introduces a tiny deterministic bias
  and the algorithm itself is still defined by Python rather than an LDB semantic law.
- **expected contract:** bADR-0014 requires an exact algorithm, stream derivation, sampling mapping,
  Numeric-profile scope, and normative vectors.
- **provisional choice:** Use and report `sha256-counter-v1` plus `uint64-be-mod-100` without claiming
  statistical quality beyond this probe.
- **classification:** Standard Schema design gap.
- **spec action:** Decide rejection sampling versus accepted modulo bias, byte/domain separation,
  counter width/overflow, seed encoding, and vectors for every standardized Distribution mapping.
- **claim impact:** The prototype selects a deterministic algorithm; independent conformance and a
  production RNG/sampling contract are not validated.

## DF-06 — Runtime refusal evidence conflicts with no-partial-output expectations

- **stage:** atomic rollback and terminal evidence publication.
- **observed evidence:** Cursor refusal exposed two different atomicity boundaries. The runtime can
  discard an active event's buffered writes, RNG draws, and child event, but per-file store writes
  allowed an invocation to publish some artifacts before a later failure. A refusal can also name a
  terminal trace identity that is not retrievable when failed invocations publish no trace artifact.
- **expected contract:** bADR-0014/0015 allow a terminal-evidence receipt, while bADR-0021 retains
  failure-safe artifact behavior. The relationship between audit evidence and “no partial
  authoritative output” is not fixed.
- **provisional choice:** The tracer now combines event rollback with a staged invocation-level
  artifact transaction whose committed index is the visibility point. It returns bounded rollback
  facts inline and treats an unpublished trace identity as a receipt-only digest, not an artifact
  locator.
- **classification:** Standard Schema design gap.
- **spec action:** Define event atomicity separately from invocation publication; decide whether
  terminal evidence is committed atomically despite refusal, embedded with a bounded shape, or
  explicitly ephemeral; define multi-artifact receipt, retention, recovery, and verification laws.
- **claim impact:** The probe separately tests event rollback and one local no-partial-visibility
  mechanism; production atomic publication and post-refusal trace retrieval remain unvalidated.

## DF-07 — Replay equality is not itself a `reproducible` assertion

- **stage:** evidence emission and replay.
- **observed evidence:** Two subprocess runs produce byte-identical stdout and artifact identities.
  An early implementation emitted `reproducible` after only one run, which was an unsupported
  claim. The correction suppresses `reproducible`; the remaining positive assertions exercise
  prototype-local validators but are not normative until the Experiment, Metric, evaluator, and
  Evidence shapes are specified independently.
- **expected contract:** Evidence assertions bind exact subjects, policies, tools, and prerequisite
  assertions; `reproducible` needs comparison evidence rather than runtime intent.
- **provisional choice:** Keep replay equality as an E2E observation and emit no reproducibility
  assertion.
- **classification:** Standard Schema evidence-contract gap exposed by a prototype defect.
- **spec action:** Define a Replay/Comparison artifact, identity-equivalence fields, mismatch
  diagnostics, and the precise prerequisites for a positive `reproducible` assertion.
- **claim impact:** Determinism is observed for the fixture, but no durable reproducibility claim is
  produced.

## DF-08 — Evidence must not be issued for unvalidated experiment and metric inputs

- **stage:** Experiment Specification validation, Metrics, Evaluation Run, and Evidence issuance.
- **observed evidence:** The runtime accepted experiment and metric structures without validating a
  closed wire schema, then emitted positive Evidence assertions. Adding an evaluator identity to
  records improves provenance but does not prove that the Experiment Specification, metric
  dimensions, aggregation, evaluator inputs, or assertion prerequisites were valid.
- **expected contract:** bADR-0018 requires closed artifact shapes, exact evaluator/build
  provenance, validated metric dimensions and semantics, and justified Evidence prerequisites.
- **provisional choice:** The tracer validates the closed experiment subset and consumed Metric
  definitions, binds one evaluator/tool identity across samples, Evaluation Run, and assertions,
  and refuses type/unit/dimension mismatches before issuing Evidence. This remains a narrow
  prototype check.
- **classification:** Standard Schema wire-shape gap exposed by a prototype defect.
- **spec action:** Define closed Experiment, Metric, Evaluation Run, evaluator, and Evidence wire
  schemas; define metric dimension/aggregation validation, prerequisite truth conditions, binding
  requirements, and negative vectors that forbid unsupported assertion issuance.
- **claim impact:** No positive Evidence emitted by the current prototype establishes normative
  `well_typed`, `resolved`, or `evaluable` status until those contracts and validators exist.

## DF-09 — Dynamic targeting and Signal typing are only narrowly exercised

- **stage:** RPG target selection and reactive Signal delivery.
- **observed evidence:** Two active enemy entities exercise lexicographic selection of `goblin`,
  and a model-authored subscriber observes `damage-resolved` against the pre-event snapshot and
  atomically writes `marked`. The prototype does not cover empty behavior, cardinality ranges,
  ties, spatial capability, subscriber cycles, or compiler validation of every payload field.
- **expected contract:** `RPG-TARGET-01` and `RPG-REACTIVE-01` require the full query/subscription
  contracts and negative/boundary vectors.
- **provisional choice:** Keep the smallest two-candidate positive path and one statically resolved
  subscription.
- **classification:** Prototype limitation; no evidence of a template design defect.
- **spec action:** Supply the matrix's target and reactive negative/boundary vectors after the LDB
  closes query cardinality/tie/empty and Signal payload/effect/cycle rules.
- **claim impact:** The integrated mechanism is plausible, but neither Genre row is closed.

## DF-10 — One narrow tracer still carries substantial specification ceremony

- **stage:** whole vertical slice.
- **observed evidence:** One combat path requires distinct bundle, source, experiment, AST/HIR/RIR,
  lock, capability, runtime, metric, evaluation, evidence, CLI descriptor, store, and refusal shapes.
  The implementation is intentionally repetitive and fixture identities must stay synchronized.
- **expected contract:** The separation is meant to prevent authority drift and permit independent
  implementations, but authoring and conformance must remain tractable.
- **provisional choice:** Preserve the boundaries rather than hide them with process-local helpers;
  stop after the tracer instead of expanding packages horizontally.
- **classification:** Standard Schema complexity risk.
- **spec action:** Measure which projections can be generated from the LDB, define small canonical
  artifact envelopes, and test whether adding the next operation is additive without copying
  semantic declarations across layers.
- **claim impact:** The layers are locally connectable for one slice, but complete feasibility,
  scalability, and maintenance cost remain open design questions.

## DF-11 — Runtime primitive semantics remain host-language authority

- **stage:** LDB operation binding, numeric evaluation, runtime execution, and RNG sampling.
- **observed evidence:** The LDB names a primitive for each operation, but Python implements
  `exact.add`, every RPG runtime primitive, state transitions, and the SHA-256 counter RNG. The LDB
  selects those host implementations; it does not define their semantic law or provide enough data
  for an independent evaluator to reproduce them.
- **expected contract:** The canonical LDB must be sufficient authority for independently
  implemented compilers and runtimes to agree on operation, Numeric, effect, scheduling, and RNG
  behavior through normative executable laws and vectors.
- **provisional choice:** Keep host primitives for the throwaway tracer, name this boundary
  explicitly, and use the LDB only for primitive selection plus limited admission rules. Do not
  describe the result as a non-fixture-specific evaluator or as validated LDB authority.
- **classification:** Standard Schema runtime semantic-law and rule-ontology gap.
- **spec action:** Define the normative operation semantic representation, primitive conformance
  interface, exact Numeric laws, effect/state-transition laws, RNG derivation and sampling laws,
  failure behavior, and cross-implementation vectors. Decide which bootstrap semantics may remain
  outside the LDB without recreating split authority.
- **claim impact:** Local execution can demonstrate layer wiring only. Complete Standard Schema 2.0
  semantics and LDB authority remain unvalidated even if every prototype test passes.

## DF-12 — Public RIR identity must exclude AST and HIR provenance

- **stage:** AST and Typed HIR lowering to canonical public RIR.
- **observed evidence:** An earlier RIR embedded AST/HIR provenance identities, so semantically
  equivalent source spellings produced different public RIR identities. This made the supposedly
  canonical runtime contract sensitive to non-semantic authoring details.
- **expected contract:** Public RIR is a semantic normal form: equivalent accepted Model Source
  Packages lower to byte-identical RIR independent of AST shape, source ordering, aliases, or HIR
  diagnostic provenance. Debug provenance must not contaminate semantic identity.
- **provisional choice:** The second iteration removes AST/HIR provenance from identity-bearing RIR
  and requires a vector with two syntactically distinct but semantically equivalent sources. Any
  debug mapping must be a separately identified, non-semantic artifact.
- **classification:** Standard Schema canonicalization gap exposed by a prototype defect.
- **spec action:** Define semantic equivalence, normalization and ordering rules, excluded provenance
  fields, optional debug-map binding, and positive/negative semantic-normal-form vectors across
  independent lowerers.
- **claim impact:** Content addressing alone did not prove canonical RIR. The prototype can test one
  correction, but public RIR normal-form completeness remains unvalidated.

## DF-13 — CLI descriptors need closed schemas and one parameter authority

- **stage:** descriptor registry, `--schema`, parameter decoding, and command invocation.
- **observed evidence:** Descriptor input schemas declared an object without `properties`, while
  command code separately defined accepted parameters and defaults. This duplicated parameter
  authority and allowed descriptor projection to drift from execution. Malformed `--params-json`
  and malformed invocation also lacked a consistently specified usage/refusal channel.
- **expected contract:** One descriptor authority must project a closed machine-readable schema and
  drive decoding, defaults, unknown-field policy, conflict detection, diagnostics, channel, and exit
  status for every invocation shape.
- **provisional choice:** The tracer projects explicit schema properties and derives parameter
  admission from the descriptor registry, including malformed JSON and missing/unknown fields. It
  retains the prototype's stdout/stderr and exit-code mapping as a provisional choice.
- **classification:** Standard Schema public CLI and descriptor contract gap.
- **spec action:** Define the closed descriptor wire shape, JSON Schema dialect/profile, parameter
  precedence and exclusivity, default authority, malformed-invocation diagnostic envelope, output
  channel, and exit-status contract; add descriptor-versus-runtime drift vectors.
- **claim impact:** The local descriptor/binding drift vectors pass, but they do not establish a
  normative, versioned, or independently consumed 2.x CLI boundary.

## DF-14 — Diagnostic stages require a closed extensible vocabulary

- **stage:** parse, static analysis, package resolution, runtime, usage, and internal failure.
- **observed evidence:** Stage-aware diagnostics were emitted as strings, but the accepted stage set
  and the relationship between `usage`, `parse`, `static`, `resolution`, `runtime`, and `internal`
  were not closed. A producer could introduce or misspell a stage without schema rejection, and a
  consumer could not rely on exhaustive handling.
- **expected contract:** Diagnostic stage and refusal class are closed, versioned discriminants with
  an explicit extension policy, stable channel/exit mapping, and rules preventing gameplay outcomes
  from being mislabeled as Schema refusals.
- **provisional choice:** Bundle ingress validates a prototype-local refusal-stage enum before a
  rule can emit diagnostics. This catches the exercised local drift but is not a normative 2.0
  vocabulary or proof of every emission boundary.
- **classification:** Standard Schema diagnostic wire-contract gap.
- **spec action:** Define the diagnostic/refusal algebra, stage enum, extension/versioning rules,
  code ownership, source-location requirements, nested causes, output channel, and exit mapping;
  provide exhaustive and unknown-stage vectors.
- **claim impact:** Stage labels make failures easier to inspect, but stage-aware refusal
  conformance remains unvalidated.

## DF-15 — Runtime profiles must be executable conformance contracts

- **stage:** runtime-profile binding, scheduling, named RNG streams, and effect execution.
- **observed evidence:** The runtime consumed profile fields but did not initially validate event and
  child budgets, required named streams, operation effect sets, or primitive/profile compatibility
  before execution. Host code could therefore run behavior outside the declared profile while still
  producing apparently valid results.
- **expected contract:** A resolved Runtime Profile closes budgets, stream declarations and
  derivation, phase/scheduler policy, effect permissions, Numeric/RNG profiles, and operation
  conformance before the first event executes.
- **provisional choice:** The tracer enforces positive event/queue/zero-time-depth budgets and
  admitted named streams, with negative vectors for each boundary. Primitive/profile compatibility
  and declared-versus-observed effect conformance remain unimplemented and must not be inferred from
  those passing vectors.
- **classification:** Standard Schema runtime-profile and effect-conformance gap.
- **spec action:** Define closed Runtime Profile and effect-summary schemas, static versus runtime
  enforcement responsibilities, stream ownership, budget accounting units, child/event overflow
  semantics, primitive compatibility, and conformance vectors.
- **claim impact:** The exercised runtime is locally budget-bounded and rejects undeclared streams;
  effect conformance and cross-implementation profile compatibility remain unvalidated.

## DF-16 — Package Lock and Capability manifest are only minimal skeletons

- **stage:** package resolution, capability negotiation, type closure, and RIR build receipt.
- **observed evidence:** The tracer records selected package identities and a small capability list,
  but it does not resolve a complete dependency graph, transitive constraints, conflicts, capability
  providers, type definitions, conversions, operation versions, or closure proofs. The artifacts
  therefore resemble the proposed shapes without establishing their semantics.
- **expected contract:** Package Lock and Capability manifest deterministically close the full
  dependency/capability/type/conversion graph used to build RIR, with enough provenance and proofs
  for an independent consumer to reject missing, conflicting, or ambiguous resolution.
- **provisional choice:** Retain the minimal skeleton to exercise identity flow and label it
  explicitly non-conformant; exercise at most one missing-capability refusal without claiming graph
  closure.
- **classification:** Standard Schema package-resolution and capability-contract gap.
- **spec action:** Define package identity and dependency constraint laws, deterministic graph
  resolution, conflict/ambiguity diagnostics, capability provider selection, type and conversion
  closure, operation-version binding, lock/manifest wire schemas, and independent resolver vectors.
- **claim impact:** Persisting these two artifacts does not validate package resolution,
  capabilities, types, conversions, or package conformance.
