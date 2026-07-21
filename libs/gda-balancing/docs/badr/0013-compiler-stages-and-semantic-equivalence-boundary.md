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

  `Wire representation → Authoring AST → Typed HIR → Resolved Model IR (RIR) → Execution IR (EIR) → Runtime`

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
  semantically relevant reference, conversion, and versioned operation is explicit. HIR may retain
  source-level structure and provenance for diagnostics, but no unresolved name or implicit
  semantic coercion survives it.

- **RIR is the canonical public semantic boundary.** Lowering removes authoring sugar, closes the
  dependency graph, normalizes declarations and operations, and emits an immutable canonical
  representation. A serialized RIR plus its Language Definition Bundle, Package Lock, and compiler
  identity is content-addressed as the Resolved Model. Independent conforming evaluators accept
  RIR rather than reinterpreting authored source.

- **HIR-to-RIR lowering must preserve specified observable behavior.** For any well-typed model,
  the RIR preserves its exported typed values and units; initialization; readable state;
  transitions; emitted signals and events; event-ordering inputs; named random-stream identity;
  terminal outputs; and declared runtime refusals. Source spans, module layout, comments, aliases,
  and eliminated sugar are non-semantic except where retained as explicit provenance metadata.
  bADR-0022 makes these observations and the lowering relation structured Language rules in the
  Language Definition Bundle.

- **EIR is evaluator-specific and non-normative.** An evaluator may lower RIR into specialized
  layouts, schedules, kernels, bytecode, or other plans. EIR is not a stable Standard Schema
  interchange format and cannot add language operations or observable behavior. If persisted, it
  is an evaluator-versioned cache keyed by the exact RIR, evaluator build, target, and numeric
  profile; evidence remains anchored to the RIR and evaluator identities rather than EIR encoding.

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

- The bADR-0022 Language Definition Bundle carries parsing, name resolution, typing/effects, units,
  diagnostics, observable runtime behavior, and HIR-to-RIR lowering rules; a compiler must conform
  to all of them before claiming 2.x conformance.
- RIR needs a canonical encoding, content-identity law, compatibility contract, and normative
  vectors. These are public Standard Schema surfaces.
- EIR may evolve with an evaluator without a Schema version bump, provided its behavior remains
  conforming and its cache identity prevents stale reuse.
- CLI and evidence artifacts report the Resolved Model identity and evaluator/numeric profile; they
  do not promise EIR portability.
- bADR-0014 defines event ordering, snapshots, conflicts, rollback, cancellation, external inputs,
  RNG derivation, and Numeric-profile boundaries that make RIR's observable behavior testable.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0003 — Standard Schema 1.x formula-as-data representation.
- bADR-0012 — language and artifact authority domains.
