---
status: accepted
---

# Make RIR the public semantic boundary and EIR an evaluator-specific lowering

Standard Schema 1.x validates and evaluates JSON-shaped formula data close to its authored form.
Standard Schema 2.x adds modules, packages, types, units, scoped names, domain operations, state,
events, and multiple evaluator implementations. Treating one tree as source syntax, linked model,
and execution plan would make source convenience features observable, force every evaluator to
repeat resolution, and leave no stable point at which two implementations can be compared.

Conversely, standardizing backend layouts and optimized kernels would expose evaluator internals
as language law and prevent safe optimization. PRD #534 therefore requires a staged compiler and
an explicit boundary for lowering equivalence.

## Decision

- **The Standard Schema 2.x compilation and execution pipeline is:**

  `Wire representation → Authoring AST → Typed HIR → RIR semantic payload → Resolved Model → Execution IR (EIR) → Runtime`

  The arrows are one-way transformations. An implementation may fuse stages internally for
  performance, but it must expose the same diagnostics and conform at the RIR boundary as though
  the stages were distinct.

- **Wire representation owns serialization, not independent semantics.** JSON is the first wire
  representation. The Language Definition Bundle defines its grammar, ingress limits, structural
  projection, and source-location mapping. A future serialization is conforming only when it
  produces the same Authoring AST meaning; wire-specific defaults or coercions cannot silently
  create a second language.

- **Authoring AST owns source fidelity.** It preserves module boundaries, source spans, unresolved
  names, and permitted authoring sugar. Parse diagnostics terminate before Typed HIR construction.
  The AST is not executable, content authority, or a stable interchange contract.

- **Typed HIR owns static semantics.** Construction completes name resolution, type inference or
  checking, unit checking, operation selection, and all other static legality rules. Every
  semantically relevant reference, conversion, versioned operation, Model entrypoint, Operation
  call site, and formal-to-actual operand binding is explicit. HIR rejects incomplete or duplicate
  port closure, unknown arguments, illegal writable aliases, incompatible types, and recursive call
  graphs. It may retain source-level structure and provenance for diagnostics, but no unresolved
  name, implicit same-name capture, or implicit semantic coercion survives it.

- **RIR semantic payload is the canonical public semantic boundary.** Lowering removes authoring
  sugar, closes the selected dependency graph, normalizes declarations and operations, and emits an
  immutable semantic normal form. Its identity is
  `H(canonical reachable semantic payload)` and contains only facts that can affect specified
  observable behavior. Source spans, module ordering, aliases, comments, AST/HIR identities,
  lowering traces, diagnostic provenance, and unselected bundle inventory are excluded.

- **Resolved Model is the exact-build execution-authority wrapper.** Its identity is
  `H(exact Kernel identity, exact whole-LDB identity, selected Package-Lock identity, RIR semantic
  payload identity)`. Compiler/tool identity remains non-semantic provenance in a separate Build
  receipt. Independent conforming evaluators consume the Resolved Model and its RIR payload rather
  than reinterpreting authored source. Two wrappers may therefore carry byte-identical semantic
  payloads without being the same exact build, runtime profile, Experiment binding, or Replay
  subject.

- **Runtime-required selected LDB semantics are embedded as one canonical RIR projection.** RIR
  carries the normalized operation bodies, signatures, effects, variants, and other admitted
  semantic fragments reachable from the model, together with exact entrypoint and call-site
  identities, canonical formal-to-actual bindings, result/outcome bindings, resolved
  effect/refusal/resource closure, and each entrypoint's Scenario Input Contract; an evaluator does
  not choose between embedding them and dynamically dereferencing alternate LDB representations.
  The exact whole LDB remains authority through the Resolved Model wrapper, while the selected
  Package Lock closes the reachable package/type/capability/profile/operation inputs to the
  projection. Runtime admission rehashes every wrapper member and rederives the invocation graph
  rather than trusting a consistently reidentified but tampered projection. Evaluator-specific
  projection choices, name lookup, ambient capture, partial Operation comparisons, or host
  fallbacks are non-conforming.

- **HIR-to-RIR lowering must preserve specified observable behavior.** For any well-typed model,
  the RIR preserves its exported typed values and units; initialization; readable state;
  transitions; emitted signals and events; event-ordering inputs; named random-stream identity;
  terminal outputs; and declared runtime refusals. Source spans, module layout, comments, aliases,
  eliminated sugar, and diagnostic provenance are non-semantic and cannot enter RIR semantic-
  payload identity.
  bADR-0022 makes these observations and the lowering relation structured Language rules in the
  Language Definition Bundle.

- **Diagnostic provenance is a separate Debug Map.** Every successful build emits one immutable,
  content-addressed Debug Map that binds the exact RIR semantic-payload identity to source spans,
  AST/HIR identities,
  lowering-rule applications, and diagnostic locations. The map is a build companion for tooling,
  not part of RIR, execution authority, semantic equivalence, or the Resolved Model identity. A
  source-only change may therefore change the Debug Map while leaving byte-identical RIR. A
  separately identified Build receipt binds source, compiler/tool, Resolved Model, Debug Map, Model
  explanation, and publication facts without entering either RIR or Resolved Model identity.

- **Human inspection uses a separate Model explanation.** Every successful build publishes one
  immutable, content-addressed `model-explanation` companion that binds the exact Model Source, RIR
  semantic payload, Debug Map, and projection schema/version. It contains separate closed
  `formula_explanations` and `operation_explanations` sections defined by bADR-0022; the latter
  references exact Formula bindings rather than restating their expression semantics. Omitted,
  extra, duplicate, or stale node bindings make the projection invalid. The artifact and any
  wording or presentation revision have their own identity and cannot affect RIR semantic-payload
  identity, Resolved Model identity, execution, or semantic equivalence. Model explanation
  generation, validation, or publication failure prevents the complete build-success artifact set
  from committing; invocation recovery restores that same complete set rather than regenerating
  the projection.

- **EIR is evaluator-specific and non-normative.** An evaluator may lower RIR into specialized
  layouts, schedules, kernels, bytecode, or other plans. EIR is not a stable Standard Schema
  interchange format and cannot add language operations or observable behavior. If persisted, it
  is an evaluator-versioned cache keyed by the exact Resolved Model and RIR semantic payload,
  evaluator build, target, and numeric
  profile; evidence remains anchored to the exact Resolved Model, Experiment, Resolved Runtime
  profile, and evaluator identities rather than EIR encoding.
  Every EIR call frame preserves the RIR's exact formal-to-actual binding, lexical caller-local
  scope, call-site identity, result/outcome identity, and trace/refusal provenance. Optimizations
  may erase representation overhead but cannot reintroduce ambient symbol capture.

- **Conformance, not a universal proof obligation, guards RIR-to-EIR lowering.** The specification
  provides a reference evaluator for RIR plus normative positive, negative, limit, replay, and
  migration vectors. Optimizing evaluators run differential tests against the reference behavior
  under the same runtime/numeric profile. A backend may additionally provide formal proofs, but
  Standard Schema conformance does not require proof of every optimization.

- **The proof boundary is stated honestly.** Parsing and static semantics are judged by normative
  rules and diagnostics; HIR-to-RIR is governed by a semantics-preservation contract; RIR-to-EIR is
  governed by reference and differential conformance. Claims such as progress or preservation are
  made only for the formally specified subset and never used as labels for unproved behavior.

- **This decision supersedes direct authored-tree execution for Standard Schema 2.x.** It replaces
  the 2.x applicability of bADR-0003's expression tree as the form directly consumed for
  evaluation, while retaining its closed-operator, pure data, no-infix-authority, and explicit
  parameter principles. Standard Schema 1.x behavior remains governed by its accepted bADRs and
  enters this pipeline only through a separately decided migration.

## Considered options

- **Typed HIR plus public RIR plus private EIR** (chosen) — gives language tooling a rich static
  form, implementations a stable comparison point, and evaluators freedom to optimize.
- **Evaluate the Authoring AST directly** (rejected) — repeats resolution in every consumer, makes
  sugar observable, and provides no canonical cross-implementation contract.
- **Make HIR the public execution artifact** (rejected) — exposes source organization and retains
  information execution does not need, weakening canonical identity.
- **Standardize EIR as portable bytecode** (rejected) — binds the language to current evaluator
  architecture and makes every optimization a Schema compatibility concern.
- **Require a formal proof for every lowering** (rejected as the baseline) — valuable where
  feasible but would block practical independent evaluators; a precise reference semantics plus
  normative and differential conformance is the enforceable minimum.
- **Allow evaluator-defined source extensions** (rejected) — bypasses the Language Definition
  Bundle and prevents a source package from having one meaning across evaluators.

## Consequences

- The bADR-0022 Kernel Specification carries irreducible interpreter/runtime semantics; the Language
  Definition Bundle carries parsing, name resolution, typing/effects, units, diagnostics, profiles,
  and HIR-to-RIR rules. A compiler must conform to both before claiming 2.x conformance.
- RIR semantic payload and Resolved Model each need a canonical encoding, distinct content-identity
  law, compatibility contract, and normative
  vectors. These are public Standard Schema surfaces.
- Debug Map needs its own closed schema and identity law; every build receipt binds it without
  making its provenance fields semantic or changing the Resolved Model identity.
- Model explanation needs one closed schema, exact RIR/Debug Map projection rules, and an identity
  law separate from RIR and Resolved Model; every build receipt binds it as a mandatory companion.
- Build receipt needs a closed non-semantic provenance schema and must never participate in the
  Resolved Model content-identity function.
- EIR may evolve with an evaluator without a Schema version bump, provided its behavior remains
  conforming and its cache identity prevents stale reuse.
- CLI and evidence artifacts report the Resolved Model identity and evaluator/numeric profile; they
  do not promise EIR portability.
- bADR-0014 defines event ordering, snapshots, conflicts, rollback, cancellation, external inputs,
  RNG derivation, and Numeric-profile boundaries that make RIR's observable behavior testable.

## Validation

- Two accepted sources that differ only in aliases, module/declaration ordering, source spans,
  comments, or eliminated authoring sugar must produce byte-identical canonical RIR even when their
  AST, HIR, and Debug Map identities differ.
- A change to a selected resolved type, operation, dependency, Runtime/Numeric profile-definition
  binding, or other semantic observation must change RIR semantic-payload identity.
- Add one unused package without changing candidate/capability ambiguity or selected transitive
  closure. The whole-LDB and Resolved Model identities must change; Package Lock and RIR semantic
  payload bytes must remain identical. Resolution/Build receipts and Resolved Runtime profile must
  rebind to the new exact build. Byte-identical RIR payloads establish only payload identity;
  executions under the different exact wrappers/profiles are not Replay and issue no comparison or
  Evidence claim unless a separately specified judgment authorizes one.
- Two independent lowerers must produce the same canonical RIR or the same closed lowering refusal
  for every positive, negative, limit, and semantic-equivalence vector.
- Independent compilers processing equivalent source with the same Kernel Specification, bundle,
  and lock must produce one Resolved Model identity even though their Build receipts identify
  different compiler/tool implementations.
- Mutate, omit, or reorder one embedded LDB semantic fragment; runtime admission must reject any RIR
  whose embedded projection is not canonical for its exact LDB/Package Lock, even when the artifact
  has been reidentified consistently.
- Reidentify a coherent but wrong Operation table, Runtime-profile definition, Diagnostic catalog,
  reason mapping, or comparison-policy projection. Runtime admission must reject it against the
  exact admitted LDB rather than trusting internal consistency or the new identity.
- Omit, mutate, or stale-bind the mandatory Debug Map or either closed Model explanation section.
  Model build must refuse before publishing a successful artifact set; no partial Resolved Model,
  Debug Map, Model explanation, manifest, or receipt may become visible.
- Inject failure before and after the atomic build publication boundary. Pre-commit failure exposes
  no successful member, while retry after a committed response-delivery failure recovers the same
  Debug Map and Model explanation identities and bytes without regenerating either projection.
- An evaluator that did not build the RIR must execute it using only the RIR and its exact public
  dependencies; deleting the Debug Map cannot change execution, Metrics, trace, or refusal behavior.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0003 — Standard Schema 1.x formula-as-data representation.
- bADR-0012 — language and artifact authority domains.
