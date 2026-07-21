---
status: accepted
---

# Make structured language rules and a small semantic kernel the executable specification

bADR-0012 makes the Language Definition Bundle the sole machine authority, and bADR-0013 fixes the
AST/HIR/RIR/EIR pipeline. Those boundaries are incomplete unless the bundle can state name
resolution, typing, effects, evaluation, and lowering without delegating meaning to one compiler's
source code. A JSON shape plus prose Operation descriptions would recreate the validator/catalog
split that 2.x was intended to close.

At the same time, making the rule language self-host every primitive produces an infinite regress,
and requiring a full theorem prover would block a practical reference implementation. PRD #534
therefore chooses a small bootstrapped meta-format, structured formal judgments, and an honest
proof/conformance boundary.

## Decision

- **The Language Definition Bundle is a canonical, content-addressed artifact.** Its manifest binds
  the exact Schema line, bundle format, Semantic-kernel version, grammar/AST definitions, core type
  constructors, Language rules, Operation specifications, Domain-package manifests, diagnostics,
  Runtime/Numeric profiles, lowering rules, external-standard mappings, and normative vectors.
  Canonical emission and hashing cover every normative member; changing normative content produces
  a new bundle identity and compatible or breaking version as applicable.

- **Language rules use one machine-readable meta-format.** Each rule has a stable id, phase,
  structured premises, structured conclusion, bound metavariables, applicability/priority where
  needed, and typed Diagnostic templates. The closed judgment families are:
  - module/import and name-resolution judgments;
  - type and Typed-effect-set judgments;
  - pure-expression evaluation and explicit sampling judgments;
  - event-runtime transition judgments;
  - HIR-to-RIR legality and lowering judgments.
  Human prose, generated docs, JSON Schemas, and reference code explain/project these records but
  cannot add exceptions or override their result.

- **The meta-format has a non-self-hosted bootstrap definition.** Its structural grammar,
  metavariable binding/substitution, premise satisfaction, deterministic rule selection, and
  diagnostic construction are fixed by the Schema-major bundle-format specification and normative
  vectors. Implementations may compile rules for speed, but the bootstrap interpreter's observable
  behavior is the conformance reference. Adding a judgment construct changes the bundle-format
  major rather than entering as an evaluator special case.

- **The Semantic kernel is intentionally small and closed.** It contains literals, typed reads,
  versioned calls, conditionals, non-shadowing local bindings, statically bounded aggregates,
  lookup, named-stream sampling, and the transition/event primitives required by bADR-0014.
  Recursion, user-defined loops, unbounded collection traversal, reflection, dynamic operation
  lookup, host callbacks, and ambient state are not kernel features.

- **Domain operations are machine-defined compositions whenever possible.** An Operation
  specification may give semantics as a typed kernel AST plus declared effects/resource bounds.
  An operation that cannot be reduced to existing kernel composition is an irreducible kernel
  operation: it requires a formal rule in the bundle, reference implementation, positive/negative/
  boundary vectors, Runtime/Numeric-profile law, and a Schema-major review. Merely registering a
  host-language function is never enough.

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
  returns one Named-random-stream state/value under the Runtime profile. Aggregate evaluation order
  and bounds are explicit rules, never host-container order.

- **Runtime behavior uses small-step transition semantics.** The runtime configuration contains the
  committed snapshot, ordered event queue, named RNG-stream states, Runtime profile, budgets, and
  trace. One step dispatches exactly one atomic Event transaction under bADR-0014, then commits a
  uniquely determined next configuration or terminal refusal. Lifecycle transitions in bADR-0020
  gate when initialization, event, step, termination, and reset judgments are legal.

- **HIR-to-RIR lowering is a terminating rule relation to a canonical normal form.** Rules declare
  legal source operation/type patterns, required capabilities, replacement RIR patterns, and
  preservation obligations. A deterministic ordering and decreasing measure prevent rewrite loops.
  The normal form has no unresolved name, implicit conversion, authoring sugar, or unbound optional
  capability. The compiler emits rule/provenance ids so a build can explain its lowering.

- **Observable preservation is tested and claimed narrowly.** For the kernel subset with written
  rules, the specification may state progress/preservation propositions and maintain their proof or
  mechanically checked argument. It does not label unproved Domain operations or optimizing
  backends “formally verified.” HIR-to-RIR is guarded by rule-level preservation vectors; RIR-to-EIR
  remains reference/differential conformance under bADR-0013.

- **All secondary language surfaces are projections or reverse-conformance targets.** Structural
  wire schemas, semantic Diagnostic catalogs, package/operation registries, evaluator dispatch
  tables, generated documentation, CLI `--schema`/manifest entries, and reference tables derive from
  the bundle where representable. If a target cannot be generated directly, a test enumerates it
  back against the bundle and fails on missing, extra, or changed meaning.

- **Resource safety is part of the rules.** Grammar depth/bytes, module/import graph, symbols,
  rule-match steps, type-instantiation depth, aggregate bounds, lowering rewrites, diagnostics, and
  generated artifact sizes have deterministic caps in the bundle/Runtime profile. Exhaustion is a
  stage-appropriate typed refusal, never partial RIR or an implementation timeout presented as
  semantics.

- **This decision supersedes bADR-0005's rejection of executable semantic-rule representation for
  2.x and bADR-0003's reference-evaluator authority.** In 1.x, a rule DSL would have duplicated a
  small validator. In 2.x, the language rules are the sole authority from which validators and
  evaluators are derived or checked. bADR-0005's anti-drift, honest structural/semantic split,
  canonical emission, and stable diagnostic identity are retained. Existing 1.x contracts remain
  historical under the clean break in bADR-0019.

## Considered options

- **Structured rules plus a closed bootstrap kernel** (chosen) — makes semantics machine-readable
  without making one compiler implementation normative.
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

- The first tracer must implement the bundle bootstrap parser/interpreter, not a parallel set of
  handwritten registries.
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

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- `docs/standard-schema-2.0/` — open specification gates and Genre coverage matrix.
- bADR-0003/0005 — 1.x evaluator/self-description authority choices superseded for 2.x only.
- bADR-0012 — Language Definition Bundle authority.
- bADR-0013 — compiler stages and semantic equivalence boundary.
- bADR-0014 — atomic event runtime.
- bADR-0016 — type and Operation/package contracts.
- bADR-0020 — explicit external-standard mappings.
- bADR-0021 — CLI projection and Command-descriptor surface.
