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

> **Amendment (2026-08-02, bADR-0024):** Formula language content includes a closed canonical
> notation grammar and package-owned pure-Operation notation declarations. `standard.schema` owns
> their wire/parse contracts and required `body`/`expression` pair; `standard.compiler` owns
> contextual resolution, local result inference, exact pair equivalence, and normalization. Every
> Package Release exporting a pure Operation owns that Operation's notation declaration; mechanic
> releases continue to own only their additional Formula-slot and Operation-integration contracts.
> The anonymous/inline Authoring-AST sugar retained below is unchanged. Model Source, RIR, and Model
> explanation carry the pair without making expression text an alternative semantic authority.

> **Amendment (2026-08-03, #594):** The Experiment judgment admits one closed discriminated Event
> plan, derives one-time initialization and observation members, and resolves Runtime-owned Event
> identities/order before dispatch. The small-step Runtime judgment dispatches one Event, while the
> public `step` judgment advances to the next observation or logical boundary.

> **Amendment (2026-08-04, #595):** A Resolved Model may contain lifecycle sites reachable from
> different entrypoints. Each Scenario evaluates only the closed site subset reachable from its
> selected entrypoints and admitted explicit inputs. A site reachable only from an unselected
> entrypoint neither executes nor creates an ambient Scenario-input requirement; selecting multiple
> entrypoints evaluates their union. Closed cycles remain invariant violations rather than being
> silently pruned as unavailable input branches.

> **Amendment (2026-08-12, #640):** The unreleased Standard Schema 2.0 Kernel replaces the
> provisional `runtime-scenario` package-vector kind with `operation-execution`. The vector executes
> one exact admitted Operation; it is a Kernel-owned bootstrap conformance form, not a public
> Runtime primitive or a generic scenario language. Its inputs exactly cover the Operation ports,
> and `read-write` access derives the initial and expected state inventory without a duplicate
> `state_names` list. Exact typed envelopes carry nominal structured values; numeric scalars retain
> their declared scalar encoding. A closed completion distinguishes a declared outcome from a
> declared typed refusal, while a closed result distinguishes a produced value from
> `not-produced`. Kernel Unit is a produced `null` value, not `not-produced`. Expected values compare
> their exact type contract and canonical value. The stable
> RNG projection remains stream, index, `candidate_hex`, and value; full Event Trace and
> resource-report fields are not copied into package evidence.

> The three additions are irreducible under the provisional node vocabulary. Lookup cannot observe
> an empty List without attempting an element access and raising the existing out-of-range refusal.
> Value selection chooses between already produced values and cannot suppress a draw, lookup, write,
> or effect. A typed requirement can stop execution but cannot express the successful empty and
> nonempty paths by itself. Host collection inspection or host control flow would bypass Kernel/LDB
> authority, so #640 adds the smallest closed nodes that express these demonstrated behaviors.

> This amendment also adds three generic primitives demonstrated by #585. The `is-empty` node has
> `family=expression`, exact required members `node`, `target`, and `value`, no fixed operand
> constraint, `result.kind=local`, and
> `result.typing={"kind": "declared-result", "members": ["value"]}`. Its fixed refusal set is
> empty, its resource charge is one `event-steps` unit, and
> `semantics.operator=collection-is-empty`. The selected structured-operation law must resolve the
> operand as one exact admitted List and the result as Kernel Boolean. The operator returns true
> only when the canonical List length is zero. The Kernel owns this node and operator law. LDB
> `standard.schema@2.4.0` exports the
> `standard.schema.list-empty-v1` structured-operation law. That record binds
> `owner_constructor=standard.schema.list`, `law.operator=collection-is-empty`,
> `law.result_contract=kernel-boolean`, and `resource_bounds.max_steps=1`. It is the LDB-owned
> applicability contract for using the generic node with the package-owned List constructor.

> The `require` node has `family=control`; exact required members `node`, `condition`, `expected`,
> and `reason`; and one `fixed-value-contract` operand constraint that requires `condition` to use
> `kernel-boolean`. `expected` is a Kernel Boolean literal. Its fixed refusal set is empty,
> `result.kind=refusal`, its resource charge is one `event-steps` unit, and
> `semantics.operator=typed-require`. The semantics record binds
> `semantics.refusal_reference.instruction_member=reason` and
> `semantics.refusal_reference.source=enclosing-operation.refusals`. Admission resolves the `reason`
> instruction member to one refusal in the enclosing Operation's declared refusal set. The node
> produces no value. Equality between the referenced condition and `expected` continues with the
> next authored node. Inequality raises the resolved typed refusal and enters the bADR-0014
> Event-refusal rollback boundary.

> The `guard-block` node has `family=control`; exact required members `node`, `condition`, `body`,
> and `outcome`; and one `fixed-value-contract` operand constraint that requires `condition` to use
> `kernel-boolean`. Its fixed refusal set is empty, `result.kind=outcome`, its resource charge is one
> `event-steps` unit, and `semantics.operator=guarded-outcome-block`. The node is allowed only in an
> Operation's top-level body and produces no local. Its `body` is a possibly empty ordered list that
> uses the closed Runtime-node grammar except `guard-block`; `outcome` resolves to one outcome in the
> enclosing Operation. False skips the body and continues the outer authored sequence. True executes
> the body in authored order and, unless a node refuses, completes the Operation with `outcome`.
> The guard costs one step. A false condition charges no body steps, RNG, writes, or effects. A true
> condition adds the actual body charge. Static resource closure includes the guard plus the complete
> admitted body bound. Admission closes the body's effects and refusals, the terminal outcome, and
> the maximum charge. Unknown members, a non-Boolean condition, a nested guard, an undeclared
> outcome, or an unbound body reference is a static refusal.

> Runtime executes the outer Operation body and a selected guard body in their authored array order.
> Node families do not reorder instructions. The replacement Kernel removes the unused
> `runtime_program.evaluation_order` phase list. `operation-body-order` remains an alias policy for
> writable operands and does not define instruction phases.

> These primitives contain no reward, fallback, package, field, or genre dispatch. The neutral
> `standard.conformance.structured@1.1.0` release proves them before mechanic packages consume
> them. Standard Schema 2.0 remains provisional until Gate 5 and Gate 6 complete and a maintainer
> records `Kernel baseline frozen` in PRD #534. The demonstrated failure therefore reopens the
> architecture gate and replaces the exact provisional Kernel identity. All affected authority and
> evidence must be rebuilt against that identity. After the recorded freeze event, another
> irreducible primitive, fact kind, term type, premise operator, or judgment construct requires the
> next Schema major.

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
  bundle format, resources, and closed ordered Package Release descriptors. Each complete release
  is a sealed one-level aggregate: its manifest owns grammar/AST definitions, core type
  constructors, Language rules, Operation specifications, post-admission diagnostics,
  Runtime/Numeric profile definitions, lowering rules, and external-standard mappings, while one
  bound package-owned conformance-vector child closes its normative vectors. Canonical vector-set,
  Package Release, and root identities cover every normative member; changing normative content
  produces the corresponding new identities and compatible or breaking version as applicable.
  Admission-derived flat indexes are not a serialized or independently hashed language authority.

- **Formula language content follows sealed Package responsibility.** The `standard.schema`
  Package Release owns generic module-level Formula declaration/binding wire grammar, Model Source
  schema and Authoring-AST definitions, typed evaluation-context and result-contract shapes, and
  their applicable `parse` and structural `static` Diagnostics. The `standard.compiler` release
  owns generic Formula name/call
  resolution, total parameter-to-operand binding, mixed Formula/pure-Operation closure,
  refusal/resource/termination judgments, HIR/RIR lowering, and their applicable semantic `static`
  and `resolution` Diagnostics. Each release's normative Formula vectors live only in its bound
  package-owned conformance-vector child. A mechanic release owns its concrete Formula-slot
  signature, context, refusal/budget contract, and Operation integration; bADR-0017 owns the
  mechanic-to-package assignment. No flat peer registry, reconstructed RPG umbrella, compiler
  table, or host callback may duplicate those authorities.

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
  refusals. The Standard Schema 2.0 Kernel remains provisional until Gate 5 and Gate 6 complete and
  a maintainer records `Kernel baseline frozen` in PRD #534. Before that event, an explicitly
  reopened architecture gate may refine the unreleased baseline, reidentify it, and invalidate
  evidence for its superseded provisional Kernel. After that event, adding a fact kind, term type,
  premise operator, or judgment construct changes the Kernel Specification and Schema major rather
  than entering as an evaluator special case.
  “Bundle admission” does not rename the bADR-0015 pipeline stages: identity/version/Kernel-binding
  and safe format admission are `ingress`, while rule/fact structural or semantic illegality after
  safe format admission is `static`; the exact admission meta-diagnostic code-to-stage mapping is
  normative Kernel content, never content of the not-yet-admitted bundle.

- **The Semantic kernel is intentionally small and closed.** Its operation set and observable laws
  are fixed by the Kernel Specification. It contains literals, typed reads,
  versioned calls with exact named port-to-operand bindings, value selection, single-level guarded
  outcome blocks, non-shadowing lexical local bindings, statically bounded aggregates,
  lookup, named-stream sampling, and the transition/event primitives required by bADR-0014.
  Recursion, user-defined loops, unbounded collection traversal, reflection, dynamic operation
  lookup, host callbacks, ambient state, and same-name argument capture are not kernel features.

- **Runtime-program node families are closed and exhaustive.** The Kernel classifies every admitted
  node as an expression, effect, or control node and fixes its fields, evaluation position, result
  or transition effect, refusal behavior, and resource charge. Named-stream `draw` and a
  gameplay-outcome precondition, `require`, and `guard-block` are control nodes: none is a pure
  expression or an implementation callback. A guard body is a single-level terminal outcome block,
  not an Operation lookup, second arm, label jump, loop, or new Runtime phase. Runtime executes the
  outer body and selected guard body in authored array order. An LDB Operation body may use only
  listed nodes, and runtime admission rejects an evaluator that does not implement the complete
  requested set before dispatch. The Kernel also fixes the exact Numeric bounds and RNG
  state/stream derivation, transition constants, sampling/bias policy, trace representation, and
  positive/multi-draw/cross-stream/boundary vectors. The LDB Operation declares one exhaustive
  typed outcome algebra with a default outcome and an explicit commit/rollback policy for every
  alternative; an evaluator may not invent outcome ids.

- **Model Source formulas enter Operations only through static typed bindings.** A Formula
  declaration is a Model Source-owned pure expression with explicit named inputs and one annotated
  result. An Operation specification may expose typed formula call sites while retaining ownership
  of its control, effects, RNG, outcomes, and commit/rollback policy. For each call site, resolution
  binds one exact Formula declaration and constructs one total named parameter-to-actual-operand
  mapping. Every declared parameter binds exactly once; missing, extra, duplicate, or unknown
  arguments refuse before Typed HIR, and parameter order, container iteration, and same-name capture
  have no semantic force. Resolution validates every mapped operand and the result for type, kind,
  unit, Numeric profile, and purity. Typed HIR and canonical RIR carry the binding identity, the
  canonical parameter map, and the resolved contracts. Runtime dispatch evaluates only that
  resolved binding with those explicit operands; it cannot perform dynamic formula lookup, invoke a
  host callback, or reinterpret the Formula as a user-authored Event program.

- **Formula declarations are module-level named language declarations, not first-class values.**
  Each declaration has a stable source name, explicit typed parameters, one result contract, and a
  structured pure-expression body. A `derived` Symbol or Operation formula call site selects it
  through ordinary static name resolution. Formula-to-Formula calls form one statically resolved
  acyclic dependency graph; recursion and dynamic selection are refused before HIR. Anonymous or
  inline expressions may exist only as Authoring-AST sugar that resolution expands into the same
  named Formula/binding model before Typed HIR. They create no alternative typing, identity,
  evaluation, or explanation rules.

- **Every declared Operation Formula slot has exactly-one binding.** An Operation may declare zero
  or more named slots, each with one explicit Formula signature and evaluation context. Selecting
  that Operation requires the Model Source to bind exactly one compatible Formula declaration to
  every slot. Missing, duplicate, type, kind, unit, Numeric-profile, purity, or context-incompatible
  bindings refuse before Typed HIR. A package-owned computation that is not a declared slot remains
  part of the immutable Operation body and requires a new package release to change. A declared
  slot has no optional cardinality, package Formula fallback, evaluator default, or host behavior;
  templates express defaults only as ordinary starter Model Source declarations and bindings.

- **Formula closure spans Formula and pure-Operation edges.** LDB rules derive one finite reachable
  graph from each Formula evaluation site, including Formula-to-Formula calls, calls to pure
  Operations, and every selected Operation-slot edge back to its bound Formula. The same judgment
  derives the closed refusal set, deterministic resource-charge upper bound, and a decreasing
  termination measure. A mixed Formula/Operation cycle, undeclared or widened refusal, or charge
  exceeding the surrounding Formula slot/Operation/context budget refuses before Typed HIR. Typed
  HIR and canonical RIR carry the exact closure; Runtime admission recomputes or
  reverse-conformance-checks it against the selected LDB/package release before execution.

- **Formula evaluation timing belongs to the evaluation-site context, never the Formula
  declaration.**
  Every Formula **evaluation site** fixes one Formula declaration binding, total typed
  parameter-to-operand mapping, lifecycle boundary, and transitive contract. Its identity includes
  the declaration, call-site identity, canonical parameter map, evaluation context, and complete
  closure. A `derived` Symbol is a read-only computed Symbol, not a stored or
  build-time-materialized value. Each read lowers to an explicit evaluation site; sites in
  different lifecycle contexts remain distinct even when they reference one declaration.
  Initialization reads the immutable pre-Snapshot Initialization frame built from admitted exact
  Experiment inputs and declared initial base values. Successful initialization atomically commits
  Snapshot 0; refusal before that commit follows bADR-0014/0015's pre-Event Runtime path with no
  fabricated Event, Snapshot, rollback, or terminal audit. An Event site reads that Event's
  committed pre-event Snapshot and cannot observe buffered writes. Observation reads the committed
  Snapshot after the transition queue for that logical time is drained. Effect `snapshot` capture
  evaluates once at its declared capture Event and retains the result; Effect `live` reevaluates at
  each declared lifecycle Event against that Event's pre-event Snapshot. `live` never means
  visibility of uncommitted writes.

  Repeating the same evaluation-site identity with the same Initialization-frame or Snapshot
  identity, canonical explicit operand values, and Numeric profile derives the same pure semantic
  value or non-resource refusal and the same deterministic charge vector. Each dynamic evaluation,
  including a cache hit, applies that charge vector to the current Runtime resource ledger before
  returning the semantic result. Insufficient remaining budget produces resource exhaustion at that
  exact evaluation boundary. A cache may reuse only the pure result under the complete semantic key;
  it cannot cache the mutable ledger or a resource-exhaustion outcome independently of that ledger.
  A different Snapshot identity is a distinct semantic evaluation even when an optimization reuses
  a proven-equivalent internal result. Constant folding, caching, and inlining are non-semantic
  optimizations and must preserve both result and charge observations.

- **Model explanation preserves the expression/control/effect boundary.** Its closed
  `formula_explanations` section projects each selected, reachable Formula declaration, evaluation
  site/binding identity, context, total parameter-to-operand mapping, mixed call-graph dependency,
  transitive refusal/resource contract, type, kind, unit, Numeric profile, expression node, and
  result contract/type. Its
  closed `operation_explanations` section projects selected, reachable control and
  effect nodes, RNG streams/draws, guards, exhaustive outcomes, and commit/rollback policy, and
  refers to Formula binding identities when an Operation calls one. The projection rules and schema
  are generated from or reverse-conformance-checked against the exact LDB language content. Human
  wording may explain those facts but cannot merge node families, add semantics, or replace the
  RIR/Debug Map bindings required by bADR-0013.

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

- **Call resolution is total and lexical.** Every Operation call site binds every required callee
  formal port exactly once and binds no unknown or duplicate port. Actual operands are caller ports,
  lexical caller locals, literals, or Kernel-admitted expressions; caller-local scope does not leak
  across sibling calls or into the host. Static admission checks type/access compatibility,
  result/outcome handling, acyclic bounded nesting, callee effect/refusal containment, and
  transitive resource closure under the selected LDB composition policy. Model entrypoints apply
  the LDB's total Symbol assignment policy to resolved Model symbols: the policy owns legal
  role/access/result combinations, value ownership, required/optional Experiment modes, and
  actual-target collapse. Each role row classifies its binding as `operand`, `result`, or
  `internal`; admission rejects an operand mode without either an Experiment value or Model
  initializer, and rejects a result mode not produced by execution. Successful lowering gives every
  actual operand and call site a stable identity and emits Model initializers and Experiment targets
  in each entrypoint's Scenario Input Contract plus a separately derived Event-local payload
  contract. Each assignment mode also owns its Event-payload cardinality: this slice permits an
  optional Event-local override only for read-only `parameter` and `input` operands initialized by
  the Experiment, while fixed, writable, derived, result, and internal values remain forbidden.
  External-fact cardinality is a separate member of that same assignment mode rather than a host
  inference from Symbol role: only read-only, Experiment-initialized operands may be exposed, and
  result, writable, fixed, derived, and internal modes remain forbidden.
  Literal typing is a separate package-owned LDB authority: a root or nested literal must select
  exactly one reachable Literal Typing Profile. A numeric profile matches source kind, type,
  representation, kind, unit, domain, Numeric policy, and bounds. A structured profile matches an
  explicit `{type, value}` envelope and validates its value against the referenced nominal
  definition. The exporting package owns the exact Type release, referenced value inventories and
  an Operation formal close the profile, and overlapping profiles for one match contract are
  invalid. Zero or multiple matches refuse before HIR; RIR preserves the selected profile and
  canonical typed value as part of the actual-operand identity. A declared writable
  alias denotes one location for the whole invocation, so a child write is visible through every
  later sibling alias and operation rollback restores the entry snapshot.

- **Experiment selection and acceptance semantics are language judgments.** The LDB supplies closed
  typing/evaluation laws for a discriminated `external-input | transition-invocation | observation`
  Event plan; unique stable root references; exact Model-entrypoint selection; total assignment of
  the canonical union of generated Scenario Input Contracts; separate Event-local payload and
  external-fact admission; derived observation members; Metric selectors; empty/missing behavior;
  terminal conditions; and acceptance expressions. An Experiment cannot select a raw LDB Operation,
  assign an undeclared symbol, author an observation phase, or add a scheduler phase.
  Implementations may optimize those judgments but cannot replace them with name matching,
  scenario conditionals, host-container iteration, or post-hoc host decisions.

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

- **Structured values use closed authority-owned laws.** `standard.schema@2.3.0` defines generic
  Enum, Record, List, and Ref constructors; the #640 `2.4.0` baseline retains those constructors
  and adds generic List emptiness. Record fields are exact, Lists are invariant and bounded, and
  each Ref owns a nominal target plus a canonical key pattern. The Kernel Runtime-node vocabulary
  admits typed literals, bounded Record/List lookup, List emptiness, exact-type canonical equality,
  typed requirements, and single-level guard blocks.
  Each constructor carries a machine-readable value rule. The selected typed-envelope profile owns
  recursive resource charging and exact type resolution. Record lookup always uses a static field
  literal; List lookup always uses a resolved integer local. RIR closes recursive nominal type and
  constructor references before Runtime, so Runtime does not consult ambient authority. Hosts do
  not own parallel constructors, Ref key rules, lookup behavior, or equality rules.

- **Runtime behavior uses small-step transition semantics.** The runtime configuration contains the
  committed snapshot, ordered event queue, named RNG-stream states, Resolved Runtime profile,
  independent budgets, admitted root-reference map, and trace. One internal scheduler transition
  dispatches exactly one atomic Event transaction under bADR-0014, then commits a uniquely
  determined next configuration or terminal refusal. The public `step` judgment applies internal
  transitions until the next declared observation or logical boundary. Lifecycle transitions in
  bADR-0020 gate when initialization, event, step, termination, and reset judgments are legal.

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
  versioned manifests and their bound conformance-vector children without changing the core
  grammar.
- Permanent RPG-slice dogfooding found that a host integer had been admitted for a Boolean formal,
  the first repair coupled Literal Typing Profiles to one Symbol assignment policy, and parent
  aliases could retain stale values across sibling calls. Literal typing is now independently
  package-owned, reference-closed, ambiguity-refusing, runtime-selected, and identity-bearing;
  `operation-body-order` aliasing spans the complete invocation rather than one child frame.
- The 2026-08-11 structured-value amendment replaces the integer-only literal path with typed
  integer and structured envelopes. Its #640 follow-up adds generic List emptiness, typed
  requirements, single-level guard blocks, and structured Operation execution evidence through
  `standard.schema@2.4.0` and the neutral `standard.conformance.structured@1.1.0` package. Neither
  amendment adds game or reward semantics.
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
- Create a Formula/pure-Operation mixed cycle, widen one derived refusal set, overflow one
  Formula-slot resource budget, or truncate/reidentify the RIR Formula closure. Independent
  consumers must issue the same pre-HIR or Runtime-admission refusal. Read one derived Symbol before
  and after a state-changing Event and again during post-transition observation; same-site reads
  under one Snapshot agree, while the same site/context is reevaluated under the distinct new
  Snapshot identity.
- Execute repeated reads at a budget boundary with Formula-result caching forced on and off. The
  value/non-resource-refusal sequence, charge events, and exact resource-exhaustion site must be
  identical; cached evaluation cannot skip, defer, or double-apply the derived charge vector.
- Execute at least one expression, effect, and control node, including named draw and a typed
  precondition outcome. Delete, move between families, or reidentify-mutate each selected node and
  require the same admission/refusal behavior across independent consumers; host support alone
  cannot keep the Operation executable.
- Execute `is-empty`, `require`, and `guard-block` through both consumers. Cover true and false
  `expected` values; true and false guard conditions; an empty guard body; an early refusal; a
  terminal outcome; malformed and non-Boolean conditions; an undeclared outcome; a nested guard;
  and exact step, RNG, state, effect, rollback, and terminal-audit observations. Reordering an
  Operation body or selected guard body must reorder execution. The removed
  `runtime_program.evaluation_order` phase list cannot change or preserve behavior.
- Execute authority-owned positive, boundary, and refusal vectors for Enum, Record, List, and Ref
  admission; bounded lookup; exact-type equality; invalid Ref keys; unknown Enum members; exact
  Record fields; list bounds; and resource exhaustion in production and independent consumers.
  Carry one neutral structured Model through public build, inspect, Experiment check/run, Snapshot,
  trace, Metric, and rollback paths without host-owned type or selection tables.
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
- Issue #590 — accepted Formula authoring and evaluation contract.
- `docs/standard-schema-2.0/` — open specification gates and Genre coverage matrix.
- bADR-0003/0005 — 1.x evaluator/self-description authority choices superseded for 2.x only.
- bADR-0012 — layered machine and authored authority domains.
- bADR-0013 — compiler stages and semantic equivalence boundary.
- bADR-0014 — atomic event runtime.
- bADR-0016 — type and Operation/package contracts.
- bADR-0017 — mechanic-to-package ownership and Genre template contracts.
- bADR-0020 — explicit external-standard mappings.
- bADR-0021 — CLI projection and Command-descriptor surface.
