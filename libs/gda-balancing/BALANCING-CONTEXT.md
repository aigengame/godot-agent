# gda-balancing

The shared language of gda-balancing: a standalone, engine- and game-agnostic toolkit for
designing a game's numerics before development and validating balance quantitatively during
it, with structured output suitable for programmatic consumption. (Requirements: PRD #501.)

## Language

### Product

**gda-balancing**:
The toolkit itself. The `gda-` prefix is the **product-family brand** — this is a sibling
product of `gda`, not a `gda` component (contrast `gda-mcp` / `gda-daemon`, which are gda's
own components). It neither depends on nor extends `gda`; its CLI *interface style* follows
gda's conventions (PRD #501 addendum). bADR-0007…0011 describe the transitional 1.x surface;
bADR-0015/0021 are the forward Standard Schema 2.x invocation and taxonomy contract.
_Avoid_: gda balancing module, balancing plugin

**Standard Schema**:
The versioned language, runtime, artifact, and evidence specification for game numeric systems
(character attributes, combat, builds, encounters, growth, economy). In Standard Schema 2.x,
authority is deliberately scoped: the `Schema-major Kernel Specification` defines how a
`Language Definition Bundle` is interpreted, the bundle is the sole language-content authority
under that kernel, and authored model, experiment, and approval facts belong to separate
`Authority domains` (bADR-0012/0022). [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) is the
human-readable macro architecture authority; it consolidates topology and subsystem boundaries
without replacing the machine authority or detailed bADRs. The pipeline designs and configures
numbers before game development; a game is then developed consuming its resolved output.
Non-standard game configs are not adapted or imported.
_Avoid_: config format, data model, descriptor

**Authority domain**:
A boundary inside which exactly one artifact owns a class of authored facts. Standard Schema 2.x
has three authored domains: the `Model Source Package` owns model definitions, the `Experiment
Specification` owns scenario/evaluation intent, and the `Approval Record` owns the governance
decision. “Single authority” is always stated with its domain; none of the three artifacts is the
global authority for the others (bADR-0012).
_Avoid_: global source of truth, authority layer

**Language Definition Bundle**:
The sole immutable language-content authority under one exact `Schema-major Kernel Specification`:
grammar, type constructors and rules, operation specifications, post-admission diagnostic codes,
package manifests, version/capability compatibility, Runtime/Numeric profile definitions, and
normative vectors. It
must carry structured laws sufficient for two independent conforming implementations to derive the
same observable operation, Numeric, effect, scheduling, refusal, and RNG behavior. Selecting or
naming host-language primitives is not sufficient. Structural language schemas, semantic catalogs,
registries, evaluator tables, documentation projections, and the language-bound members referenced
by Command descriptors are generated from it or guarded by reverse conformance; command-surface
shape remains descriptor-owned. No hand-maintained peer language-content authority is allowed
(bADR-0012/0021/0022).
_Avoid_: schema registry, implementation registry, language manifest (partial)

**Schema-major Kernel Specification**:
The versioned, non-self-hosted authority that defines bundle structure and interpretation,
judgment execution, the irreducible Semantic kernel, exact Numeric and RNG sampling laws,
event-transition primitives, resource accounting, Kernel/LDB-admission meta-diagnostics, and their
conformance interface. Every Language Definition Bundle binds one exact kernel-specification
identity. Host implementations conform to the kernel and bundle; a Python function, reference
evaluator, or implementation table is never semantic authority (bADR-0012/0022).
_Avoid_: reference implementation as authority, host semantic kernel, implicit bootstrap

**Semantic kernel**:
The closed bootstrap operation set whose laws are fixed by the Schema-major Kernel Specification:
literals, reads, calls, conditionals, local bindings, bounded aggregation, lookup, sampling, and
transition/event primitives. Language Definition Bundle rules compose those primitives into
language and domain behavior. An irreducible addition is a Schema-major kernel change with formal
laws, independent conforming implementations, and normative vectors (bADR-0022).
_Avoid_: standard library, evaluator built-ins, host functions

**Language rule**:
A stable-id, machine-readable rule in the Language Definition Bundle, represented as structured
premises, conclusion, phase, and refusal diagnostics. Rules define name resolution, typing/effects,
evaluation, and HIR-to-RIR lowering; prose explains them but cannot override their structured
meaning (bADR-0022).
_Avoid_: validator rule (implementation), prose requirement, compiler special case

**Typed effect set**:
The statically inferred or checked set attached to an expression/operation judgment, including
state read/write, signal emission, event schedule/cancel, and Named-random-stream sampling.
Effect-free expressions are pure; effectful operations are legal only in contexts whose Operation
specification declares and bounds the same effects (bADR-0016/0022).
_Avoid_: Effect specification (gameplay concept), side-effect flag, purity hint

**Resolved symbol identity**:
The exact package-version, module, and declaration identity produced by explicit name resolution.
Source uses explicit imports/aliases and no wildcard imports or shadowing; Typed HIR/RIR carry the
resolved identity rather than source spelling or lookup order (bADR-0022).
_Avoid_: string reference, qualified name (before resolution), registry key

**Model Source Package**:
The sole editable authority for one game's numeric model definitions in Standard Schema 2.x. It
contains an authored manifest and model modules, including dependency requirements, but not an
authored resolution result. It may be compiled into a `Resolved Model`; experiment or approval
facts never become hidden model definitions (bADR-0012).
_Avoid_: Source Package (unqualified), design bundle, model config

**Experiment Specification**:
The authored authority for scenarios, Metric definitions, targets, sampling/replication design,
observation and discrepancy models, calibration policy, train/holdout partition, acceptance rule,
and drift policy. It references an exact `Resolved Model` identity or a declared compatibility
contract and may bind inputs, but it cannot redefine the model. Exact Resolved-Model binding is
immutable; compatibility binding may compare RIR semantic payloads but must resolve to one exact
Resolved Model before execution and produce an identified
final-binding receipt. Changing RIR semantics therefore creates a new Experiment Specification
identity or an explicit, reviewable compatibility-resolution result, never a silent rebind. The
specification is versioned and hashed independently so evidence identifies both model and
experiment (bADR-0012/0018).
_Avoid_: experiment config, model overrides, scenario package

**Approval Record**:
The immutable governance authority for an approval decision. It identifies the exact model,
experiment, Metric datasets, Evaluation runs, Calibration reports, Evidence assertions, evaluator,
and applicable policy by content identity and carries the human or organizational attestation; it
does not copy or mutate those artifacts. A boolean flag without that evidence chain is not an
Approval Record (bADR-0012/0018).
_Avoid_: approval flag, approved model, sign-off note

**RIR semantic payload**:
The immutable canonical semantic normal form produced after Typed HIR. It contains only selected,
reachable facts that can affect specified observable behavior: resolved symbols and types,
operation bodies/signatures/effects/results, state and event semantics, and other admitted runtime
fragments. Source order, aliases, comments, spans, AST/HIR identities, lowering traces, diagnostic
provenance, and unselected Language Definition Bundle inventory are excluded. If an unused package
is added to the bundle without changing resolution ambiguity or the selected closure, this payload
and its content identity remain byte-identical (bADR-0013/0016).
_Avoid_: Resolved Model (the authority wrapper), compiled source tree, evaluator plan

**Resolved Model**:
The immutable, content-addressed public execution-authority artifact for one exact build. Its
identity binds the exact Schema-major Kernel Specification, exact whole `Language Definition
Bundle`, canonical selected-closure `Package Lock`, and one `RIR semantic payload`. The wrapper
therefore changes when the exact bundle changes even when an unused-package edit leaves the Lock
and RIR payload byte-identical. It is the normative cross-evaluator boundary for that exact build,
not an authored authority or editable interchange format (bADR-0012/0013).
_Avoid_: RIR semantic payload (unqualified), authored model, normalized source

**Debug Map**:
A separately content-addressed, non-semantic artifact that binds one exact RIR semantic-payload
identity to source
spans, AST/HIR identities, lowering traces, and diagnostic provenance. It may change without
changing an equivalent RIR and cannot affect compilation or runtime behavior (bADR-0013/0022).
_Avoid_: RIR metadata, semantic provenance, embedded source map

**Build receipt**:
A separately identified, non-semantic provenance artifact binding the Model Source Package,
Schema-major Kernel Specification, Language Definition Bundle, Package Lock, Resolved Model,
compiler/tool identity, Resolution receipt, optional Debug Map, and publication facts for one build.
Compiler and resolver implementation identities belong in provenance receipts and never
participate in RIR or Resolved Model content identity, so independent conforming tools can produce
the same semantic artifacts (bADR-0013).
_Avoid_: compiler identity in RIR, semantic build id, Resolved Model provenance field

**Package Lock**:
The generated, content-addressed proof of the exact **selected transitive closure**: dependency
graph and constraints, exact package-release identities, capability-provider bindings,
type/conversion closure,
operation-version bindings, normative resolution-algorithm/profile identity, and deterministic
conflict disposition used to build a `Resolved Model`. It projects the Model Source Package's
requirements through the
Language Definition Bundle's compatibility rules; it is reproducibility evidence, not an
independently authored authority. One package id resolves to one exact version; incompatible majors
require distinct namespaces or an explicit adapter package. It does not copy the whole bundle
inventory: adding an unselected package must leave Lock bytes unchanged when it introduces no
candidate/capability ambiguity and the selected closure is otherwise identical (bADR-0012/0016).
_Avoid_: dependency config, package manifest, lock authority

**Domain package release**:
One immutable, content-addressed, namespaced package artifact admitted by a Language Definition
Bundle. It closes metadata and semantic version, dependencies/capabilities, exported Quantity
kinds/units/profiles/types, complete Operation contracts and bodies, Diagnostics, and normative
vectors under one release identity; Package Lock binds that exact identity. Reusing one package
id/version for different content is refused within an admitted bundle. Historical uniqueness
across independently published bundles requires an explicit release-index/transparency authority
and is not established by a content hash or semantic-version string alone (bADR-0016).
_Avoid_: package registry entry, evaluator plugin, split operation registry

**Resolution receipt**:
A separately identified, non-semantic provenance artifact binding the source requirements,
Schema-major Kernel Specification, Language Definition Bundle, canonical Package Lock, resolver
tool/build identity, diagnostics, and publication facts for one resolution attempt. Resolver
implementation provenance belongs here and never participates in Package Lock or Resolved Model
content identity (bADR-0012/0016).
_Avoid_: resolver identity in Package Lock, semantic resolver build, dependency authority

**Genre template**:
A versioned template release for a genre's numeric design baseline, never an evaluator code path.
In Standard Schema 2.x it distributes an instantiable starter Model Source Package, companion
Experiment Specifications, and a `Genre coverage matrix` while preserving their separate authority
domains. Instantiation creates a new model identity with template provenance; later template
releases never mutate an instantiated game silently. First families: RPG (CRPG/JRPG/ARPG) and
Roguelike (metroidvania-like, survivors-like, deckbuilder-like) (bADR-0017).
_Avoid_: preset, profile

**Reference fixture**:
A paper-game source/experiment pair for a supported genre, living in the conformance suite as an
executable consumer. In 2.x each fixture participates in one or more `Golden scenarios` and traces
back to rows in the Genre coverage matrix, including paths no live game exercises yet
(bADR-0017).
_Avoid_: sample project, demo config, template itself

**Genre coverage matrix**:
The normative proof behind an RPG or Roguelike support claim. Each requirement row identifies its
owning package capabilities and operations, cross-package boundary, positive Golden scenario,
negative vector, and observable metric/evidence. A package list or prose example without a closed
matrix is not representational-adequacy evidence (bADR-0017).
_Avoid_: feature checklist, roadmap, package inventory

**Golden scenario**:
A canonical Model Source Package plus Experiment Specification and expected compiled/runtime/
evidence observations that exercises one or more coverage-matrix requirements end to end. Golden
scenarios test package composition and public artifacts, not private evaluator functions
(bADR-0017).
_Avoid_: unit fixture, demo battle, snapshot test (too narrow)

### Standard Schema design

**Core type constructor**:
One of the closed Standard Schema 2.x language-level constructors: `Bool`, `Int`, `Fixed`,
`Decimal`, `Float`, `Enum`, `Record`, `Vector`, `List`, `Set`, `Map`, `EntityRef`, `Quantity`, or
`Distribution`. Domain packages instantiate and compose these constructors but cannot add grammar
or primitive representation semantics; changing this set requires a Schema major decision
(bADR-0016).
_Avoid_: package type, attribute type, custom primitive

**Quantity**:
A typed numeric value whose concerns are explicit and orthogonal: numeric representation, nominal
kind, unit/dimension, support/domain, and Numeric profile policy. Nominal kind prevents accidental
mixing of numerically similar concepts such as health and mana; unit conversion and cross-kind
conversion require explicit registered operations (bADR-0016).
_Avoid_: number with metadata, stat value, unit scalar

**Symbol role**:
The declared use of a typed symbol or component field — including `constant`, `parameter`, `input`,
`state`, `derived`, `output`, and `random`, with domain roles such as `current`, `capacity`, `cost`,
or `rate` composed separately. A role constrains ownership and lifecycle; it never creates another
numeric type (bADR-0016).
_Avoid_: attribute type, variable kind (ambiguous), numeric subtype

**Domain package**:
A versioned, namespaced Standard Schema extension that composes core types into nominal types,
records/components, operations, capabilities, diagnostics, conversions, and declared runtime
effects. Its manifest declares dependencies and compatibility; it cannot mutate another package's
types, add implicit syntax, or bypass the Language Definition Bundle (bADR-0016).
_Avoid_: plugin (implies host code), schema fragment, profile

**Capability**:
A versioned, namespaced contract a Domain package provides or requires. Dependency resolution binds
required capabilities and explicitly selected optional ones, then records the exact set in Package
Lock and Resolved Model. Missing or incompatible capability is a `resolution` refusal; capability
presence never enables undeclared fallback behavior (bADR-0016).
_Avoid_: feature flag, optional behavior, duck-typed extension

**Operation specification**:
The Language Definition Bundle entry that gives a versioned operation its complete static and
runtime contract: type signature, unit rules, purity, resource bounds, Numeric profiles, and
declared reads, writes, emitted signals, scheduled events, and Named random streams. An evaluator
implements this contract; its host-language function is not the authority (bADR-0012/0016).
_Avoid_: function registration, evaluator hook, opcode documentation

**Discriminated gameplay outcome**:
A closed Enum/Record result returned when declared game semantics complete with one expected
branch, such as `reserved`, `insufficient`, `immune`, or `interrupted`. Every admitted variant has
one stable tag and variant-specific payload, and Typed HIR consumers must handle variants
exhaustively before invoking dependent operations. It is neither a Typed refusal nor an internal
error (bADR-0014/0016).
_Avoid_: gameplay refusal, expected error, success flag

**Conversion operation**:
A versioned operation explicitly converting representation, Quantity kind, or unit under declared
legality and loss behavior. Source must request it and Typed HIR records it; no implicit coercion
survives name/type resolution (bADR-0016).
_Avoid_: automatic cast, unit normalization (when implicit), compatibility shim

**Capability manifest**:
The generated inventory of exact packages, operations, types, conversions, Numeric profiles, and
runtime capabilities available in one Resolved Model. Its inventory payload is a complete
projection of the selected Package Lock plus RIR semantic payload for negotiation and evidence and
cannot invent or omit inventory. That inventory remains equal under an unused-package edit, while a
published manifest artifact that binds the exact Resolved Model wrapper receives a new artifact
identity. It is never authored independently (bADR-0013/0016).
_Avoid_: feature list, plugin registry, package manifest

**Reference-standard mapping**:
An explicit record of one mechanism adopted from an external standard, the Standard Schema concept
it maps to, what is deliberately not adopted, and the conformance evidence required. The external
standard supplies design provenance; the Schema-major Kernel Specification and Language Definition
Bundle restate the binding local contract within their authority domains and remain the local
authorities (bADR-0020).
_Avoid_: standards compliance (unless fully implemented), inspiration, compatible with (unscoped)

**Physical unit code**:
A UCUM 2.2 case-sensitive unit expression used for a physical Quantity's unit/dimension semantics,
including semantic equality and commensurability rather than literal-string comparison. Game-only
health, mana, currency, and similar nominal kinds use package namespaces outside UCUM and never use
UCUM annotations as semantic extensions (bADR-0016/0020).
_Avoid_: display unit, arbitrary UCUM annotation, game stat code

**Equation package**:
The reserved `math.equation` Domain-package identity for a future restricted declarative
algebraic/ODE subset. It is not admitted by the initial 2.0 Language Definition Bundle. A later
decision must fix integrator/version, tolerances, continuous state snapshots, zero-crossing and
event coupling, determinism scope, and normative vectors before equations can lower to RIR. It is
not the full Modelica language or a general DAE solver contract (bADR-0020).
_Avoid_: Modelica support, equation script, symbolic escape hatch

**Design document (Standard Schema 1.x)**:
The legacy single root JSON document holding one game's complete numeric design — an instance of
Standard Schema 1.x declaring the `schema_version` it targets. Subsystems are sections within it;
there is no multi-file document set (bADR-0001). Standard Schema 2.x supersedes this authoring
granularity with the `Model Source Package`. Because no 1.x artifact was published, migration is a
best-effort source conversion only: semantics-preserving constructs migrate and unsupported ones
are explicitly deprecated and must be re-authored (bADR-0012/0019). The document names its game;
the toolkit stays game-agnostic.
_Avoid_: config file, numbers file, design config

**Migration report**:
The deterministic result of attempting the limited Standard Schema 1.x source conversion. It binds
the original Design-document identity, converter/Language Definition Bundle identity, every
successfully mapped construct, and every explicitly deprecated construct. A report with any
deprecated construct has no 2.x Model Source Package output; partial or lossy migration is never
presented as success (bADR-0019).
_Avoid_: upgrade log, compatibility report, converted file

**Deprecated 1.x construct**:
A Standard Schema 1.x source concept with no semantics-preserving 2.x mapping. The converter emits
a `migration` refusal and records it in the Migration report; the construct must be re-authored or
removed. There is no runtime compatibility adapter or best-effort reinterpretation (bADR-0019).
_Avoid_: legacy fallback, unsupported warning, lossy migration

**Wire representation**:
The serialization accepted at the Standard Schema 2.x ingress boundary — JSON first — whose
grammar, resource limits, and source-location mapping are defined by the `Language Definition
Bundle`. It carries source text/data into parsing; serialization details do not create language
semantics independent of the parsed `Authoring AST` (bADR-0013).
_Avoid_: canonical model, source semantics, JSON schema (the structural projection)

**Authoring AST**:
The parsed source representation of a `Model Source Package`, preserving modules, source spans,
unresolved names, and permitted authoring sugar so diagnostics can point back to authored input.
It is not executable and is not the cross-implementation semantic boundary (bADR-0013).
_Avoid_: runtime AST, resolved tree, executable model

**Typed HIR**:
The high-level intermediate representation after complete name resolution, type checking, unit
checking, and static legality checks. It retains source-level structure and provenance useful for
diagnostics, but every semantically relevant reference and operation is explicit. Its lowering to
the `RIR semantic payload` must preserve the specified observable behavior (bADR-0013).
_Avoid_: typed AST (when resolution is incomplete), runtime model, execution plan

**Execution IR (EIR)**:
An evaluator-specific lowering of one `RIR semantic payload` into layouts, schedules, kernels, or
other execution details. EIR is neither a stable Standard Schema interchange contract nor a
language authority; an evaluator proves its behavior against RIR through the reference evaluator,
normative vectors, and differential tests. Persisted EIR is only a versioned evaluator cache
(bADR-0013).
_Avoid_: Resolved Model, portable bytecode, Standard Schema artifact

**Attribute facet (Standard Schema 1.x)**:
One of the orthogonal properties an attribute declaration composes: `domain`
(number / percentage / probability), `base` (direct vs formula — the single scalar
authority), `accepts` (contribution channels: allocation, effects), `bounds` (mandatory
for percentage/probability domains), and descriptive `category`. Facets combine subject
to the cross-facet validity rules enforced at the boundary funnel; no *named tier
composition* is ever mandatory (bADR-0002).
_Avoid_: attribute type, tier (different concept)

**Attribute tier (Standard Schema 1.x template vocabulary)**:
A genre template's **named facet composition** — the vocabulary a template groups its
attributes by (e.g. an RPG template's primary/derived/tertiary layers; a survivors-like's
single flat layer). Template data, not schema law: the Standard Schema requires no tier
taxonomy to exist (bADR-0002).
_Avoid_: stat level, attribute class, schema-enforced tier

**Effect (Standard Schema 1.x)**:
A first-class, time-scoped carrier of numeric influence — the numerical core of a
buff/debuff, status effect, or over-time effect: a list of modifiers, a duration
(instant / timed / infinite), a tick period (its legality governed by the modifier mix),
and — for persistent timed/infinite effects — a reference to a declared stacking type
plus its own re-application `lifetime` (independent / refresh) (bADR-0006). Builds offer effects; combat applies them; simulation consumes their
numbers.
_Avoid_: buff (as the generic term), status (alone), proc

**Modifier (Standard Schema 1.x)**:
One numeric operation inside an `Effect`: a target attribute, an operation
(add / multiply / override), an application kind — continuous (contributes to the value
pipeline while active) or one_shot/periodic (a delta to the simulated current value) —
and a formula-capable magnitude (per-tick amount when periodic). Not an attribute tier
and not a bounded correction coefficient (bADR-0006).
_Avoid_: modifier tier, correction coefficient, stat bonus (vague)

**Stacking policy (Standard Schema 1.x)**:
How same-type effect magnitudes combine — `aggregation` (stack / keep_best), declared
**once per stacking type** in the document's stacking-type catalog, the single authority
no individual effect can override. Orthogonal to an effect's re-application `lifetime`.
Declared data, never formula logic (bADR-0006).
_Avoid_: stacking rule (as a per-effect property), stack behavior

**Effect specification (Standard Schema 2.x)**:
A composition of independently typed contracts for application requirements, value capture,
continuous contributions, state transitions, scheduling, stacking identity/reducer, reapplication,
removal/expiry/dispel, and immunity. Action, combat, resource, and runtime packages consume these
contracts through declared operations; no single Effect object owns every mechanic
(bADR-0016/0017).
_Avoid_: modifier list, buff object, monolithic status schema

**Target query**:
A deterministic, typed selection expression over a dynamic entity set, with filters, ordering,
cardinality, tie-breaking, and empty-result behavior. Action and effect operations receive its
resolved targets; they do not implement private target-selection rules (bADR-0017).
_Avoid_: target list (when dynamically selected), selector callback, implicit area target

**Run scope**:
The lifecycle boundary for state created for one Roguelike run and cleared by an explicit run-reset
transition. It is orthogonal to `Meta scope`, which survives that reset; every state declaration
names its scope so reset cannot depend on naming conventions (bADR-0017).
_Avoid_: session data, temporary state, run flag

**Meta scope**:
The lifecycle boundary for progression intentionally retained across Roguelike run resets. Transfer
between Run and Meta scopes requires declared operations and appears in the event/evidence trace
(bADR-0017).
_Avoid_: permanent state (ambiguous), account state, global progression

**Named form (Standard Schema 1.x)**:
A parameterized formula shape — a form id plus named parameters (e.g. linear, piecewise
linear, lookup table). The preferred formula representation: its parameters are explicit,
named tuning knobs for Phase-2 sensitivity analysis and search (bADR-0003).
_Avoid_: formula preset, curve type (as a term of art)

**Expression tree (Standard Schema 1.x)**:
The JSON-structured formula AST over a closed operator set — the general fallback when no
named form fits a per-game formula. Operator closure and reference integrity are validated
at the boundary funnel; infix strings are never authoritative (bADR-0003).
_Avoid_: formula script, expression DSL, infix formula

**Reserved section (Standard Schema 1.x)**:
A top-level Design-document section whose name is fixed but whose shape is not yet designed
(`combat`, `encounters`, `builds`, `growth`, `economy`, `targets`). A document using one is
refused until the owning issue lands its shape as a minor schema bump — never
accepted-and-ignored (bADR-0001).
_Avoid_: placeholder section, stub, TODO section

### Validation & self-description

**Boundary funnel (Standard Schema 1.x)**:
The single validation boundary every 1.x Design document crosses before any use — three phases,
each gating the next: preflight (ingress caps + version dispatch), structural (against the
structural schema), semantic (the rules the semantic rule catalog indexes). Validity is a property
of a document *state*: any mutation re-enters the funnel before evaluation or emission. Standard
Schema 2.x replaces this three-phase limit with compiler and artifact `Refusal stages` while
retaining gated execution, ingress caps, report-all diagnostics, and typed refusal (bADR-0004/0015).
_Avoid_: input guard, validation pass (as something repeatable downstream)

**Typed refusal**:
An expected, machine-actionable inability to accept or complete the requested domain operation.
In 1.x it rejects invalid input through bounded JSON-Pointer entries (bADR-0004). In 2.x it may
stop ingress, parsing, static analysis, resolution, runtime, evaluation, migration, or approval and
carries bounded, stably ordered `Diagnostic` entries in the `Error envelope` (bADR-0015). It never
represents a negative but successfully computed `Verdict`, a malformed invocation, or an internal
exception.
_Avoid_: validation error (too narrow), failed verdict, exception

**Refusal stage**:
The one pipeline boundary at which a Standard Schema 2.x typed refusal stopped an invocation:
`ingress`, `parse`, `static`, `resolution`, `runtime`, `evaluation`, `migration`, or `approval`.
Stages gate later work and are stable machine vocabulary; they classify diagnostics without
creating new exit codes (bADR-0015).
_Avoid_: error type, compiler pass (implementation-specific), exit code

**Diagnostic**:
One machine-actionable reason inside a 2.x typed-refusal envelope: stable code, human message,
tagged primary location, and optional related locations. A location identifies an invocation,
source span, artifact pointer, symbol, or runtime event/snapshot; it is not forced into a JSON
Pointer when the failure is not a JSON element. Codes and location identities are normative;
message prose is explanatory. The Schema-major Kernel Specification owns the closed meta-diagnostic
family needed to admit or reject a Kernel/LDB; an unadmitted bundle cannot authorize its own
refusal. After admission, language/compiler/runtime/evaluation implementations may emit only codes
whose exact meaning and `Refusal stage` membership are present in that bundle. The closed
command-surface usage/internal families remain descriptor/CLI concerns; a host-coded diagnostic
list is never semantic authority (bADR-0012/0015/0022).
_Avoid_: log message, exception, validation warning

**Structural schema**:
The published JSON Schema 2020-12 projection for a Standard Schema wire artifact, `$id` versioned
with that artifact contract. Its 2.x dialect/profile and any semantic default are owned by the
Schema-major Kernel Specification or Language Definition Bundle and projected here; JSON Schema's
`default` keyword remains annotation only. Passing it means structurally well-formed — not valid;
the semantic layer closes the gap. In 1.x it accompanies the required validator (bADR-0005); in 2.x
it is generated from or conformance-checked against the Language Definition Bundle and cannot
define language semantics independently (bADR-0012/0022). A Command descriptor may reference this
artifact schema but cannot redefine its fields or defaults. Ecosystem validators can run it without
the toolkit installed.
_Avoid_: meta-schema (JSON Schema term of art for schemas-of-schemas), the JSON file

**Semantic rule catalog**:
The machine-readable **index** of semantic-phase rules — rule id (identical to the refusal code),
scope, description, since-version. Together with the structural schema it answers “what is
structurally well-formed and which semantic rules exist”; full validity additionally requires a
conforming compiler/validator. In 1.x it is derived from the validator or conformance-guarded
(bADR-0005). In 2.x both are projections or implementations of the `Language Definition Bundle`;
the catalog is never a peer semantic authority (bADR-0012).
_Avoid_: rules doc, validation spec (as a prose document)

### Command surface

**Command descriptor**:
The single per-command registration object naming everything the surface needs to run, describe,
and conformance-test a command: tree position, description, one closed typed input model (possibly
zero-field), every reachable success/verdict/refusal model, argument presentation, typed handler,
execution markings, and conformance fixtures. A command with no exit-0 result declares no success
model. The only path into the command surface; dispatch, schema and
manifest projection, structured-params binding, artifact receipts, and the conformance harness all
derive from it (bADR-0011/0015/0021).
_Avoid_: command spec, command config, registry entry

**Command schema profile**:
The immutable, content-addressed cross-command authority for schema dialect, reference, closure, and
annotation/default-binding rules, referenced by every 2.x Command descriptor. It exhaustively lists
the JSON Schema Draft 2020-12 meta-schema URI and admitted keyword and format sets. Each Command
descriptor remains the sole per-command authority for input, outcome, CLI defaults, and artifact
behavior under those shared rules. The Surface manifest identifies the profile's exact version;
artifact Structural schemas remain Language Definition Bundle projections and are only referenced,
never redefined (bADR-0021).
_Avoid_: artifact schema, validator defaults, implicit JSON Schema dialect

**Surface manifest**:
The aggregate machine-readable projection of every registered 2.x Command descriptor: command
identity/description, one closed input schema, each reachable success/verdict/error schema,
execution markings, and artifact behavior. A zero-parameter command still publishes an empty closed
input schema; a gate-only command omits an unreachable success schema. The ungrouped `manifest`
command emits it from the live descriptor registry; it is not maintained as another command list
(bADR-0021).
_Avoid_: command catalog, CLI docs, schema manifest (ambiguous)

**Structured params input**:
The `--params-json <json | ->` adapter that binds one command's published input model directly,
with `-` reading stdin. It is mutually exclusive with individual argv fields and cannot introduce
parameters absent from the Command descriptor; `--schema` takes precedence without executing the
command (bADR-0021).
_Avoid_: config file, JSON flags, alternate command API

**Invocation key**:
A caller-supplied idempotency key of 64 lowercase hexadecimal digits encoding 32 octets, required by
every artifact-producing 2.x command and exposed identically as `--invocation-key` and
`invocation_key` in structured params. The publication index binds it to one Command descriptor
identity, canonical command-input identity, and committed outcome receipt. The canonical input
identity excludes the Invocation key and presentation-only output locator. The key is
command-delivery metadata, never model/RIR semantics; recovery retries the original command with
the same key and input (bADR-0021).
_Avoid_: artifact identity, random run id, generated-only recovery token

**Error envelope**:
The single closed top-level-`error` JSON object a failed invocation emits. Categories remain
`refusal` (stdout, exit 2), `usage` (stderr, exit 3), and `internal` (stderr, exit 4). A 2.x refusal
variant carries one `Refusal stage`, non-empty bounded `Diagnostic` entries, a truncation marker,
an optional reproduction receipt, and a required terminal-audit receipt when runtime dispatch has
begun; usage/internal variants carry their own single codes and never masquerade as domain
diagnostics (bADR-0008/0015/0021).
_Avoid_: error blob, failure JSON, exception dump

**Verdict**:
The negative answer from a successfully completed domain judgment — for example valid evidence
showing balance targets were not met, or governance declining approval. It is never conflated with
a refusal, which means the judgment could not be completed. A negative verdict emits its typed
report on stdout with exit 1; a positive judgment is a success result on stdout with exit 0
(bADR-0008/0015).
_Avoid_: validation result, balance error, failure (vague)

**Usage error**:
An invocation-surface failure before a command can admit its artifact input: missing/unknown
command or argument, argument conflicts, invalid scalar argument syntax, or unreadable/unwritable
paths. It emits its own stable code on stderr with exit 3. Once bytes or referenced artifacts enter
the command's ingress stage, every expected domain failure is a typed refusal, never a usage error
(bADR-0008/0015).
_Avoid_: refusal (the domain word), invalid input (ambiguous)

**Effective seed**:
The seed that actually drove a stochastic run — supplied via `--seed` (unsigned
32-bit) or drawn fresh — always echoed in the structured result together with the
toolkit version, and carried by any failure envelope once drawn, so every stochastic
outcome keeps its own reproduction key (bADR-0008/0010). For Standard Schema 2.x it is
the root of named streams and is reproducible only together with the exact Resolved Model,
Experiment Specification, Resolved Runtime profile, and external-input identities (bADR-0014); the
Resolved Runtime profile already closes evaluator, platform, Numeric, RNG, scheduler, effect, and
budget choices. The current CLI encoding remains in force until the 2.x CLI contract supersedes it.
_Avoid_: random seed (ambiguous), default seed

### Runtime

**Runtime lifecycle**:
The explicit state machine for one RIR execution instance: `instantiated`, `initializing`, `event`,
`step`, `terminated`, and reset to a new instance. The states adapt FMI's lifecycle discipline to
Standard Schema artifacts and the atomic-event runtime without adopting FMU, C API, or
co-simulation compatibility (bADR-0014/0020).
_Avoid_: FMI runtime, process lifecycle, implicit evaluator state

**Runtime profile definition**:
The Language Definition Bundle-owned, immutable contract for one admitted execution policy:
scheduler/phase semantics, budget vocabulary and accounting units, Named-stream derivation,
`Numeric profile`, complete RNG sampling law, permitted effect sets, primitive requirements,
overflow behavior, and portability constraints. It contains no bundle identity, evaluator build,
host platform, or deployment fact, so it cannot form an identity cycle with its owning bundle
(bADR-0014/0022).
_Avoid_: environment, evaluator configuration, resolved execution identity

**Resolved Runtime profile**:
The generated, content-addressed admission artifact that resolves one Runtime profile definition
against an exact Schema-major Kernel Specification, Language Definition Bundle, Package Lock,
Resolved Model/RIR semantic payload,
evaluator build, platform/runtime scope, and concrete deterministic budgets. It is validated before
initialization; execution refuses an undeclared or incompatible stream, effect, primitive, profile,
or budget. An exact replay identity claim requires this profile and every other reproduction input
identity to match. Comparing two different evaluator-bound profiles is a `Cross-evaluator
comparison`, not a replay (bADR-0014/0018).
_Avoid_: Runtime profile definition, ambient environment, runtime config

**Cross-evaluator comparison**:
An immutable conformance artifact comparing observations from independent evaluator realizations
whose Resolved Runtime profiles intentionally differ. It binds both profiles plus the exact common
Kernel Specification, Language Definition Bundle, Package Lock, Resolved Model/RIR semantic
payload, Runtime profile definition,
Experiment Specification, external inputs, seed, declared portable-observation policy, and every
match/mismatch. A positive result may support a `cross_evaluator_conformant` Evidence assertion; it
is never a `Replay comparison` and cannot satisfy `reproducible` (bADR-0014/0018/0022).
_Avoid_: replay comparison, same semantic profile (insufficient), evaluator agreement flag

**Numeric profile**:
The named, versioned arithmetic contract selected by a Runtime profile definition: supported numeric
representations and operations, rounding, overflow and non-finite behavior, comparison tolerance,
and portability scope. A portable exact profile may promise cross-platform bit identity; a profile
admitting native floating operations is scoped to its declared evaluator/runtime/platform and ULP
contract (bADR-0014).
_Avoid_: precision setting, float mode, tolerance flag

**Runtime event**:
An immutable, uniquely identified queued transaction carrying logical time, phase, priority, enqueue
sequence, operation, and typed payload. The scheduler orders events by logical time ascending,
fixed `input → transition → observation` phase order, priority descending, then enqueue sequence
ascending. Input admits ordered external facts, transition owns model mutation, and observation is
read-only evidence collection (bADR-0014).
_Avoid_: callback, message (unqualified), async task

**Signal**:
An ephemeral typed fact emitted during one Event transaction to subscribers declared statically in
the Model Source Package and compiled into the Resolved Model's static subscription table. The
Language Definition Bundle owns signal types plus validation, effect, ordering, and execution laws,
not game-specific topology. Subscribers read the same committed pre-event snapshot and run in stable
Resolved-symbol order; their bounded writes and child events join the transaction buffers. The
signal and subscriber observations enter the trace only if the event commits. A signal is never
persistent state, a queued Runtime event, or a hidden callback (bADR-0012/0014/0016).
_Avoid_: scheduled signal, event alias, broadcast callback

**Event transaction**:
The atomic execution of one Runtime event. It reads the latest committed snapshot, buffers its one
final write per state slot plus child events and cancellations, and commits all effects together.
Multiple contributors must use an explicit reducer/composition operation; an event may not depend
on hidden write order (bADR-0014).
_Avoid_: event handler (implementation term), tick mutation, transaction batch

**Artifact publication transaction**:
The invocation-level atomic boundary that makes one immutable receipt and every artifact it
identifies visible together, or none visible. It is distinct from Event-transaction atomicity and
from any filesystem, object-store, or transport implementation; stdout/stderr delivery is ordered
after commit and is not a participant. A runtime refusal after dispatch begins must publish a
separately typed terminal-audit artifact set through this boundary, but never a partial
Evaluation/Metric/Evidence success set (bADR-0015/0021).
_Avoid_: atomic file write, output directory, event transaction

**Snapshot boundary**:
The semantic state boundary before the first event and after every committed Event transaction.
The full state exists conceptually at each boundary; traces may store a canonical state hash and
materialize full state only at declared checkpoints without changing semantics (bADR-0014).
_Avoid_: save point, frame snapshot, periodic dump

**Runtime refusal**:
The deterministic terminal result when execution cannot legally continue after successful static
validation — for example an event targets a past phase, an event budget is exhausted, or a runtime
operation violates its declared domain. The current Event transaction is rolled back, its children
are discarded, prior commits remain represented by the terminal audit, and the run stops
(bADR-0014). It is a `runtime`-stage typed refusal: exit 2 on stdout. Once runtime dispatch begins,
it must carry a
receipt for one complete, separately typed terminal-audit artifact set that committed atomically
and is retrievable and verifiable. A Resolved Runtime profile admission refusal before dispatch
carries no terminal audit. Failure to publish the required set before commit is an `internal`
command outcome, not a Runtime-refusal envelope with a fake receipt; failure after commit leaves the
set recoverable by its durable invocation identity (bADR-0015/0021).
_Avoid_: crash, validation refusal, skipped event

**Named random stream**:
A stable logical random source derived from the effective root seed and a declared stream identity
under the selected definition recorded by the Resolved Runtime profile. Sampling never consumes an
ambient global RNG; reordering an unrelated stream cannot perturb this stream (bADR-0014).
_Avoid_: global RNG, random state, implicit seed

### Simulation

**Metric definition**:
An Experiment-Specification declaration giving one metric its stable identity, Quantity type/unit,
dimensions, observation window, aggregation, missing/censoring behavior, and replication semantics.
The same definition governs simulated and observed samples; source kind cannot change its meaning
(bADR-0018).
_Avoid_: report field, telemetry name, evaluator counter

**Metric sample**:
One typed observation under a Metric definition: value, logical time/window, declared dimensions
(such as entity, encounter, or run), replication identity, source kind, and provenance. Missing and
censored observations are explicit states, never sentinel numeric values (bADR-0018).
_Avoid_: result number, measurement row (without schema identity), aggregate report

**Metric dataset**:
An immutable, content-addressed collection of Metric samples with exact Metric-definition,
experiment, source/build, partition, and data-version provenance. `simulated` and `observed` are
source kinds in this one schema, not separate result formats (bADR-0018).
_Avoid_: simulation report, telemetry dump, CSV result

**Evaluation run**:
The immutable evidence artifact binding exact Resolved Model, Experiment Specification, Resolved
Runtime profile, evaluator, external inputs, effective seed/streams, ordered trace, and produced
Metric dataset. It records what ran and what was observed; it does not itself decide acceptance
(bADR-0018).
_Avoid_: simulation result, run log, benchmark

**Replay comparison**:
An immutable artifact comparing declared observable fields across two or more Evaluation runs that
share the same complete reproduction identity, including one identical Resolved Runtime profile.
It binds the compared runs, replay policy, identity checks, observation checks, and any closed
mismatch diagnostics. A successful comparison, not replay intent or a single successful run, is a
prerequisite for a `reproducible` Evidence assertion. Runs under different evaluator-bound profiles
require a `Cross-evaluator comparison` instead (bADR-0014/0018).
_Avoid_: replay succeeded, deterministic flag, matching logs

**Observation model**:
The Experiment-Specification contract mapping latent model metrics to observed playtest data,
including measurement noise, censoring/missing assumptions, replication unit, correlation
structure, and model discrepancy. Calibration cannot infer these choices from a dataset after the
fact (bADR-0018).
_Avoid_: telemetry adapter, error bars, noise setting

**Calibration report**:
The immutable result of applying a declared estimator and policy to exact model, experiment,
training datasets, and Evaluation runs. It records parameter identifiability, constraints/priors,
observation noise, model discrepancy, correlation handling, uncertainty, sensitivity, objectives,
and candidate selection without erasing unsuccessful or inconclusive results. Holdout verification
is a separate post-calibration evidence step (bADR-0018).
_Avoid_: tuned config, best parameters, optimizer output

**Evidence assertion**:
A small immutable, content-addressed claim that a specific artifact set passed one declared gate,
such as `well_typed`, `resolved`, `evaluable`, `reproducible`, `cross_evaluator_conformant`,
`calibrated`, or `holdout_verified`. Each assertion references exact schema-valid subjects, issuer,
policy/tool/evaluator identities, successful semantic validators, and satisfied prerequisite
assertions;
artifact presence or command success alone proves none of these claims. In particular,
`reproducible` requires an identified successful `Replay comparison`, while
`cross_evaluator_conformant` requires an independently validated `Cross-evaluator comparison` and
never upgrades to replay identity. Progress is an evidence graph, never a mutable status field
(bADR-0018).
_Avoid_: workflow status, passed flag, maturity level

**Holdout verification**:
Evaluation of a calibrated candidate against an immutable partition frozen before calibration and
excluded from fitting or model selection. New data versions or a drift assessment beyond policy do
not mutate historical evidence, but make that verification ineligible for a later approval
(bADR-0018).
_Avoid_: final test (ambiguous), validation set (often used during tuning), post-hoc sample

**Drift assessment**:
An `Evidence assertion` subtype that applies one predeclared drift policy to exact baseline and new
Metric-dataset identities. It records compared measures, windows, statistical results, decision,
and eligibility effect. It never edits a Calibration report or Holdout-verification assertion;
beyond-policy drift blocks those assertions from satisfying a later approval (bADR-0018).
_Avoid_: stale flag, mutable data status, automatic recalibration

**Evaluation method (legacy planning term)**:
A method that *estimates* balance metrics from a config — Monte-Carlo encounter estimation
and system-dynamics (first-order nonlinear ODE) long-horizon prediction. Distinct from a
`Tuning method`; Monte-Carlo is an estimation method, never an "exact algorithm".
_Avoid_: exact algorithm, precise algorithm

**Tuning method (legacy planning term)**:
A method that *searches* config space toward balance targets — parameter sensitivity
analysis first, then simple (greedy) search; stronger optimizers later. Delivery ordering is
simple-to-hard.
_Avoid_: approximation algorithm, auto-balancer

**Metrics schema**:
The one round-trip shape shared by simulated and observed playtest Metric samples/datasets. It
preserves typed values, dimensions, replication identity, provenance, missing/censoring state, and
partition without source-specific reinterpretation. Live ingestion wiring is deferred, but future
observed data must enter this same contract (bADR-0018).
_Avoid_: report format (as a separate shape)
