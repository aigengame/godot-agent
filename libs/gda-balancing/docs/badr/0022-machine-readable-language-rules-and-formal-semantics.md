---
status: accepted
---

# Make structured language rules and a small semantic kernel the executable specification

bADR-0012 fixes a layered machine-authority chain: a non-self-hosted, Schema-major Kernel
Specification defines bundle interpretation and irreducible semantics; one exact Language
Definition Bundle is the language-content authority under that kernel. bADR-0013 fixes the
AST/HIR/RIR/EIR pipeline. Those boundaries are incomplete unless the bundle can state name
resolution, typing, effects, evaluation, and lowering without delegating meaning to one compiler's
source code. A JSON shape plus prose Operation descriptions would recreate the validator/catalog
split that 2.x was intended to close.

At the same time, making the rule language self-host every primitive produces an infinite regress,
and requiring a full theorem prover would block a practical reference implementation. PRD #534
therefore chooses a small non-self-hosted Kernel Specification, a closed bootstrapped meta-format,
structured formal judgments, and an honest proof/conformance boundary.

## Decision

- **The Kernel Specification is the non-self-hosted root of machine semantics.** It fixes the bundle
  structural grammar and admission, rule-interpreter semantics, irreducible Semantic-kernel
  primitives, exact Numeric laws, RNG derivation/sampling primitives, and atomic transition
  primitives that cannot be defined by rules without regress. It is versioned only with the Schema
  major. Reference implementations and host-language primitives conform to it; they never define or
  extend it. For every admitted kernel node or judgment, it supplies a closed machine encoding of
  input/result shapes, scope and binding, evaluation order, effects, transitions, refusals, resource
  accounting, and canonical identity consequences. Admission validates those contracts and every
  invocation enforces them; effects and resource obligations close transitively through nested
  Kernel-law calls. An inventory of node names plus prose-like law
  strings is not an executable Kernel Specification.

  Template release admission applies the same rule at the distribution boundary: its Schema-major
  primitive specification fixes typed arguments/result effects, evaluation and failure laws,
  canonical comparison/identity behavior, and charge events. LDB-facing operation names only bind
  to those primitives; they do not authorize a host `if` branch with undeclared semantics.

- **The Language Definition Bundle is one canonical, content-addressed language-content graph.**
  Under bADR-0023, its root manifest binds the exact Schema line, Kernel-Specification identity,
  bundle format, resources, and closed ordered child descriptors. Complete package-release children
  own grammar/AST definitions, core type constructors, Language rules, Operation specifications,
  post-admission diagnostics, Runtime/Numeric profile definitions, lowering rules,
  external-standard mappings, and normative vectors. Canonical child identities and the root graph
  identity cover every normative member; changing normative content produces a new bundle identity
  and compatible or breaking version as applicable. Admission-derived flat indexes are not a
  serialized or independently hashed language authority.

- **Canonical wire identity is a Kernel contract.** The Kernel Specification binds the exact
  domain-separated identity algorithm and canonical encoding rules for strings/Unicode, map and list
  order, integers and any admitted numeric representation, optional/default members, artifact-kind
  separation, and identity-field exclusion. Positive, ordering, Unicode, numeric-boundary, and
  malleability vectors apply to Kernel, LDB, RIR, locks, profiles, receipts, and command-input
  identities. A shared helper-library convention is not a normative identity profile.

- **Language rules use one closed, machine-readable meta-format.** The Kernel Specification defines
  a versioned ontology of fact schemas, term types, premise operators, metavariable binding and
  substitution, applicability and priority, deterministic rule selection, missing-fact behavior,
  conclusion construction, and typed Diagnostic templates. Each rule has a stable id and phase and
  may use only that ontology. The closed judgment families are:
  - module/import and name-resolution judgments;
  - type and Typed-effect-set judgments;
  - pure-expression evaluation and explicit sampling judgments;
  - event-runtime transition judgments;
  - HIR-to-RIR legality and lowering judgments.
  Human prose, generated docs, JSON Schemas, and reference code explain/project these records but
  cannot add exceptions or override their result.

- **The meta-format has a non-self-hosted bootstrap definition.** Its structural grammar,
  metavariable binding/substitution, premise satisfaction, deterministic rule selection, and
  diagnostic construction are fixed by the Kernel Specification and normative vectors.
  Implementations may compile rules for speed, but independently implemented bootstrap interpreters
  must have the same observable behavior. Unknown facts or premise operators, ill-typed terms or
  substitutions, missing required facts, and ambiguous rule selection are bundle-admission
  refusals. Adding a fact kind, term type, premise operator, or judgment construct changes the
  Kernel Specification and Schema major rather than entering as an evaluator special case.
  “Bundle admission” does not rename the bADR-0015 pipeline stages: identity/version/Kernel-binding
  and safe format admission are `ingress`, while rule/fact structural or semantic illegality after
  safe format admission is `static`; the exact admission meta-diagnostic code-to-stage mapping is
  normative Kernel content, never content of the not-yet-admitted bundle.

- **The Semantic kernel is intentionally small and closed.** Its operation set and observable laws
  are fixed by the Kernel Specification. It contains literals, typed reads,
  versioned calls, conditionals, non-shadowing local bindings, statically bounded aggregates,
  lookup, named-stream sampling, and the transition/event primitives required by bADR-0014.
  Recursion, user-defined loops, unbounded collection traversal, reflection, dynamic operation
  lookup, host callbacks, and ambient state are not kernel features.

- **Runtime-program node families are closed and exhaustive.** The Kernel classifies every admitted
  node as an expression, effect, or control node and fixes its fields, evaluation position, result
  or transition effect, refusal behavior, and resource charge. Named-stream `draw` and a
  gameplay-outcome precondition are control nodes: neither is a pure expression nor an
  implementation callback. An LDB Operation body may use only listed nodes, and runtime admission
  rejects an evaluator that does not implement the complete requested set before dispatch. The
  Kernel also fixes the exact Numeric bounds and RNG state/stream derivation, transition constants,
  sampling/bias policy, trace representation, and positive/multi-draw/cross-stream/boundary vectors.
  The LDB Operation declares one exhaustive typed outcome algebra with a default outcome and an
  explicit commit/rollback policy for every alternative; an evaluator may not invent outcome ids.

- **Domain operations are machine-defined compositions whenever possible.** An Operation
  specification may give semantics as a typed kernel AST plus declared effects/resource bounds.
  An operation that cannot be reduced to existing kernel composition is an irreducible kernel
  operation: it requires a Kernel-Specification amendment, a machine-readable signature exposed by
  the bundle, independent conforming implementations, positive/negative/boundary vectors,
  Runtime/Numeric-profile laws, and a Schema-major review. Merely registering or naming a
  host-language function is never enough.

- **Operation admission is one closed judgment, not a collection of trusted declarations.** The
  Kernel closes every known node's exact fields. LDB rules validate signature and parameter use,
  result variants/payload types, kind/unit/Numeric-profile references, purity, and the complete
  signal/event/cancel/random/state effect surface; they derive effects and resource counts from the
  program and require exact agreement with declared bounds. Malformed support/domain data or bound
  types produce typed static Diagnostics, never host exceptions. HIR-to-RIR projects the complete
  selected Operation, and runtime admission revalidates that projection against the exact selected
  package release and Lock.

- **Experiment selection and acceptance semantics are language judgments.** The LDB supplies closed
  typing/evaluation laws for exact-model input overrides, event-sequence references, Metric
  selectors, empty/missing behavior, and acceptance expressions. Implementations may optimize
  those judgments but cannot replace them with scenario conditionals or post-hoc host decisions.

- **Name resolution is explicit and deterministic.** Packages contain named modules. Imports are
  selective or explicitly aliased; wildcard imports are forbidden. A declaration or local binding
  cannot shadow another visible binding. Duplicate declarations, unresolved names, and ambiguous
  aliases are `static` refusals. Successful resolution replaces every source reference with a
  Resolved symbol identity containing exact Package-Lock version, module, and declaration identity;
  HIR/RIR never repeat lookup heuristics.

- **Public type contracts are annotated; inference is deliberately local.** Exported declarations,
  state, parameters, inputs, outputs, random symbols, component fields, and Operation inputs/results
  require explicit types and roles. Inference is limited to local bindings and contextually typed
  literals. Records and Quantity kinds are nominal; generic containers are invariant; there is no
  implicit subtyping, unit conversion, kind conversion, or numeric coercion. Every accepted
  conversion is an explicit selected operation in Typed HIR.

- **Typing includes effects.** The central static form is conceptually
  `Γ ⊢ expression : type ! effects`, where effects include state reads/writes, signal emission,
  event schedule/cancel, and named-stream sampling. An empty set denotes a pure expression. Calls
  compose declared effects; effectful operations are legal only in event/experiment contexts whose
  Operation specifications declare compatible, statically bounded effects. Hidden evaluator I/O is
  non-conforming.

- **Pure expressions use deterministic big-step semantics.** Given typed values and no effects,
  evaluation returns exactly one typed value or a declared Runtime/evaluation refusal under the
  selected Numeric profile. Sampling is not mislabeled pure: its separate judgment consumes and
  returns one Named-random-stream state/value under the selected Runtime profile definition.
  Aggregate evaluation order and bounds are explicit rules, never host-container order.

- **Runtime behavior uses small-step transition semantics.** The runtime configuration contains the
  committed snapshot, ordered event queue, named RNG-stream states, Resolved Runtime profile,
  budgets, and trace. One step dispatches exactly one atomic Event transaction under bADR-0014,
  then commits a uniquely determined next configuration or terminal refusal. Lifecycle transitions
  in bADR-0020 gate when initialization, event, step, termination, and reset judgments are legal.

- **HIR-to-RIR lowering is a terminating rule relation to a canonical normal form.** Rules declare
  legal source operation/type patterns, required capabilities, replacement RIR patterns, and
  preservation obligations. A deterministic ordering and decreasing measure prevent rewrite loops.
  The normal form has no unresolved name, implicit conversion, authoring sugar, or unbound optional
  capability. Identity-bearing RIR excludes source, AST/HIR, and diagnostic provenance. A compiler
  may emit lowering-rule applications and source mappings only in bADR-0013's separately identified,
  non-semantic Debug Map.

- **Observable preservation is tested and claimed narrowly.** For the kernel subset with written
  rules, the specification may state progress/preservation propositions and maintain their proof or
  mechanically checked argument. It does not label unproved Domain operations or optimizing
  backends “formally verified.” HIR-to-RIR is guarded by rule-level preservation vectors; RIR-to-EIR
  remains reference/differential conformance under bADR-0013.

- **All secondary language surfaces are projections or reverse-conformance targets.** Structural
  wire schemas, semantic Diagnostic catalogs, package/operation registries, evaluator dispatch
  tables, generated documentation, language-bound fields referenced by CLI `--schema`/manifest, and
  reference tables derive from the bundle where representable. bADR-0021's Command descriptors own
  the surrounding command-surface schemas. If a target cannot be generated directly, a test
  enumerates it back against the bundle and fails on missing, extra, or changed meaning.

- **Diagnostic semantics have no host-owned peer.** The Kernel Specification exhaustively owns the
  meta-diagnostic codes, payload shapes, precedence, and bADR-0015 stage membership required before
  a Kernel/LDB can be admitted; an LDB cannot authorize rejection of itself. The admitted LDB then
  owns every typed-refusal code, message-template input, and stage membership used by source,
  compiler, runtime, and evaluation operations. Implementations generate each diagnostic table from
  the authority that precedes it or reverse-enumerate every emitted code/stage against that
  authority. The reachable reason set and Diagnostic catalog are exact, and conformance vectors
  trigger every authoritative code/stage including direct host-boundary exits. A
  host-coded diagnostic absent from its Kernel/LDB authority is non-conforming even
  when two implementations use the same string.

- **Resource safety is part of the rules.** Grammar depth/bytes, module/import graph, symbols,
  rule-match steps, type-instantiation depth, aggregate bounds, lowering rewrites, diagnostics, and
  generated artifact sizes have deterministic caps in the bundle, Runtime profile definition, or
  Resolved Runtime profile. Exhaustion is a stage-appropriate typed refusal, never partial RIR or an
  implementation timeout presented as semantics.

- **This decision supersedes bADR-0005's rejection of executable semantic-rule representation for
  2.x and bADR-0003's reference-evaluator authority.** In 1.x, a rule DSL would have duplicated a
  small validator. In 2.x, the Kernel Specification plus exact Language Definition Bundle is the
  authority chain from which validators and evaluators are derived or checked. bADR-0005's
  anti-drift, honest structural/semantic split, canonical emission, and stable diagnostic identity
  are retained. Existing 1.x contracts remain historical under the clean break in bADR-0019.

## Considered options

- **A non-self-hosted Kernel Specification plus structured bundle rules** (chosen) — makes semantics
  machine-readable without making one compiler implementation normative or pretending the
  meta-language can interpret itself.
- **Prose specification plus reference interpreter** (rejected) — leaves ambiguity when prose and
  code disagree and cannot generate or exhaustively check projections.
- **Reference implementation source as authority** (rejected) — prevents independent evaluator
  conformance and hides semantic changes in ordinary refactors.
- **Self-host every rule including the rule meta-language** (rejected) — creates an unnecessary
  bootstrap regress and makes bundle admission impossible to validate independently.
- **General-purpose executable rule scripts** (rejected) — reintroduce unbounded execution, host
  effects, and evaluator-specific meaning.
- **Global type inference, structural records, or implicit coercions** (rejected) — make public
  contracts unstable under extension and obscure HIR/RIR semantics.
- **Require machine-checked proofs for every package operation** (rejected as the baseline) — the
  enforceable contract is structured semantics plus vectors/differential conformance; stronger
  proofs remain allowed and accurately scoped.

## Consequences

- The disposable semantic-authority probe demonstrated source-level independent bootstrap/evaluator
  paths and removal of RPG host dispatch, but its shared handwritten interpretation of kernel nodes
  does not satisfy this decision. A passing conformance implementation must independently implement
  the Kernel Specification's complete bundle bootstrap and node/judgment laws, not parallel
  handwritten registries or coordinated host-semantic dispatch tables.
- The disposable orthogonality probe demonstrated that closed generic nodes can carry one selected
  package slice through static projection and runtime admission without RPG-specific dispatch. Its
  checker, Diagnostic construction, selector, acceptance, and evaluator remain one handwritten
  Python interpretation; the result refines the required judgments above but does not satisfy this
  decision or close the Semantic-authority gate.
- The final executable-authority probe on closed, unmerged PR #537 satisfied the bounded mechanism
  gate with two independent Kernel/LDB bootstrap/lowerer/evaluator stacks, mutual artifact
  consumption, complete mutation witnesses for every consulted law/rule, and no RPG host dispatch
  in the selected slice. It confirms this authority shape, but disposable code does not supply the
  permanent Kernel/LDB, exhaustive ontology/vectors, complete Genre breadth, publication system, or
  Evidence validator required by #534.
- `docs/standard-schema-2.0/` records the open Genre coverage contract and executable-specification
  gates. It deliberately contains no placeholder bundle: #534 remains open until a closed bootstrap
  schema, exhaustive rules, artifact shapes, profiles, and executable vectors are supplied together.
- A minimal bundle can start with only the kernel and RPG-tracer packages, then add packages through
  versioned manifests and conformance vectors without changing the core grammar.
- Compiler diagnostics can identify the exact Language rule and source/artifact locations that
  caused a refusal or lowering.
- Formal-spec work now has bounded deliverables: resolution rules, type/effect rules, pure/sample
  evaluation, atomic runtime steps, lowering rules, and their declared proof/conformance boundary.
- Global consistency review must verify that every 2.x glossary term and bADR uses this authority
  chain and does not introduce a hand-maintained semantic peer.

## Validation

- At least two independently implemented bootstrap interpreters consume the same bundles and agree
  on admission, rule selection, substitutions, conclusions, diagnostics, and canonical identity.
- Bootstrap interpreters and evaluators independently rehash the exact Kernel Specification and LDB
  before use. Mutating a Numeric/RNG/node/transition law while retaining its old claimed identity
  must produce the same pre-execution refusal in every consumer rather than changed behavior under
  the old identity.
- Fact/premise ontology vectors cover every fact and term type, premise operator, missing-fact rule,
  binding/substitution edge, priority tie, ambiguous selection, and unknown/ill-typed construct.
- For every consulted Kernel law and Language rule: retain the old identity after tamper and require
  pre-use refusal; delete and reidentify it and require refusal with no fallback; then reidentify a
  behavior mutation and require corresponding RIR/trace/observation change or the same closed
  refusal in each implementation. Renaming authority-owned rule, Operation, Diagnostic, and Source
  tokens must not require host changes. A host conditional cannot preserve old behavior behind the
  changed authority.
- Mutate known-node extra fields, Operation signatures/parameters/results/kind-unit-profile rules,
  purity/effects/resource bounds, Quantity support shapes, Experiment selectors, and acceptance.
  Independent consumers must produce the same typed Diagnostic before partial HIR/RIR/Evaluation;
  a reidentified but semantically inconsistent RIR projection must fail runtime admission.
- Execute at least one expression, effect, and control node, including named draw and a typed
  precondition outcome. Delete, move between families, or reidentify-mutate each selected node and
  require the same admission/refusal behavior across independent consumers; host support alone
  cannot keep the Operation executable.
- At least two evaluators that share no host primitive implementation execute each other's RIR and
  agree on operation, Numeric, RNG, scheduler, effect, trace, Metric, and refusal vectors under the
  same Runtime profile definition and their honestly distinct evaluator-bound Resolved Runtime
  profiles. A named host primitive without a complete Kernel Specification law fails this gate;
  cross-evaluator agreement uses bADR-0014/0018's separate comparison and never masquerades as exact
  Replay.
- Reverse-enumerate every admission Diagnostic code/stage against the Kernel and every
  post-admission source/compiler/runtime/evaluation Diagnostic against the admitted LDB; missing,
  extra, duplicate, or moved codes fail conformance before the related path can be claimed covered.
  Delete/reidentify each mapping and behavior-trigger every authoritative code/stage, including
  direct host-boundary exits.
- Semantic-equivalence vectors produce byte-identical RIR across independent lowerers while Debug
  Map changes remain non-semantic; resource-limit vectors terminate with stage-appropriate refusal
  and never partial RIR.
- Add one reducible operation or package feature and inventory every changed surface. Exactly one
  LDB/package entry may own its normative semantics; schemas, registries, dispatch inventories,
  documentation, and conformance inventories must be generated or reverse-enumerated from it. Any
  second hand-maintained semantic declaration fails the authority-drift gate.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- `docs/standard-schema-2.0/` — open specification gates and Genre coverage matrix.
- bADR-0003/0005 — 1.x evaluator/self-description authority choices superseded for 2.x only.
- bADR-0012 — layered machine and authored authority domains.
- bADR-0013 — compiler stages and semantic equivalence boundary.
- bADR-0014 — atomic event runtime.
- bADR-0016 — type and Operation/package contracts.
- bADR-0020 — explicit external-standard mappings.
- bADR-0021 — CLI projection and Command-descriptor surface.
