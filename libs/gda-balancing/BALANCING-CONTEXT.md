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
gda's conventions (PRD #501 addendum). bADR-0007…0011 preserve the historical 1.x surface contract
used only to define migration input; bADR-0015/0021 are the forward Standard Schema 2.x invocation
and taxonomy contract.
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
The sole immutable language-content authority under one exact `Schema-major Kernel Specification`.
It is one sealed artifact graph: a canonical root manifest owns the exact ordered package
membership, and each root-declared descriptor binds one complete `Domain package release`. A
release is a sealed one-level aggregate whose manifest owns runtime language semantics and binds
exactly one package-owned `Package conformance vector set`; both JSON members live in one
package-specific directory. Together the releases own grammar, type constructors and rules,
operation specifications, post-admission diagnostic codes, version/capability compatibility,
Runtime/Numeric profile definitions, and normative vectors. It must carry structured laws
sufficient for two independent conforming implementations to derive the same observable operation,
Numeric, effect, scheduling, refusal, and RNG behavior. Selecting or naming host-language
primitives is not sufficient: the bundle owns Source-package and collection selection plus the
ordered parse, resolution, type/effect, Diagnostic, and HIR-to-RIR judgments.
Its admitted package/profile/Operation/Diagnostic graph is closed before use; missing content cannot
fall back to host behavior. Structural language schemas, semantic catalogs,
registries, evaluator tables, documentation projections, and the language-bound members referenced
by Command descriptors are generated from it or guarded by reverse conformance; command-surface
shape remains descriptor-owned. Admission constructs read-only flat indexes only after it verifies
the complete graph; those indexes are not packaged or independently edited. No directory scan,
remote lookup, or hand-maintained peer language-content authority may add a member
(bADR-0012/0021/0022/0023).
_Avoid_: schema registry, implementation registry, package directory as authority

**LDB root manifest**:
The canonical root member of one `Language Definition Bundle`. It binds the exact Kernel identity,
graph resources, and canonical descriptors for every Package Release manifest. Each descriptor
binds artifact kind, logical package id/version, canonical content identity, and byte size; the
Package Release manifest then binds its exact conformance-vector child. The root manifest is the
only package-membership authority. Descriptor transport order is normalized by the Kernel-declared
`id`, then `version` order; physical paths, package-directory names, and Locators are packaging
metadata and do not enter semantic identity. Package id/version grammar and the identity domains
for the root, Package Release collection, and package-vector collection are Kernel-owned contracts
projected by loaders, admission, public schemas, and rebuild tooling (bADR-0023).
_Avoid_: package index (if independently editable), directory listing, remote registry

**Package conformance vector set**:
The one immutable evidence child owned and bound by a `Domain package release`. It binds the exact
owning package id/version and closes the ordered ids and definitions of that package's normative
vectors, including a closed empty set when the package currently owns none. Its own canonical
identity and byte size are bound by the Package Release manifest; it is not independently
versioned, selected, published, discovered, or treated as a peer language authority. A vector-only
change reidentifies this child, the owning Package Release content identity, the whole LDB, and
downstream exact wrappers, but does not change the Package Release semantic identity when runtime
semantics are byte-identical. Its packaged bytes must be the Kernel-canonical encoding of the
decoded value, and its public schema closes every admitted top-level vector variant
(bADR-0016/0023).
_Avoid_: test fixture registry, vector package, independently publishable evidence package

**Operation execution vector**:
A Kernel-owned Package conformance vector that executes one exact admitted Operation. Its input
values exactly cover the Operation ports; `read-write` ports derive the state inventory. Its closed
expectation records an outcome or typed refusal, a produced value or `not-produced`, the stable
Named-stream RNG projection, and final state. Nominal structured values use exact typed envelopes;
scalar values follow their declared contracts. LDB admission closes its structure, identities,
types, and bindings. During LDB maintenance, bADR-0016's development conformance harness compares
all manifest-bound vectors in one complete candidate graph before replacement authority is
published. Public Runtime, the package resolver, and the identity rebuild tool do not execute
vectors (bADR-0016/0022).
_Avoid_: runtime scenario, Experiment scenario, package test script, full Event Trace

**Admitted language index**:
A read-only in-memory projection constructed only after the complete LDB graph is admitted. It
provides efficient lookup of package-owned types, operations, Diagnostics, profiles, rules, schemas,
and vectors without serializing a second semantic authority. Its contents are recomputed from the
exact admitted children and cannot be edited or consumed independently (bADR-0023).
_Avoid_: language registry, generated authority, cached peer catalog

**Schema-major Kernel Specification**:
The versioned, non-self-hosted authority that defines bundle structure and interpretation,
judgment execution, the irreducible Semantic kernel, exact Numeric and RNG sampling laws,
event-transition primitives, resource accounting, Kernel/LDB-admission meta-diagnostics, and their
conformance interface. Each executable Kernel law closes its parameters, result, transitive
effects, refusals, resource units, and canonical behavior. The Standard Schema 2.0 Kernel remains a
provisional baseline until Gate 5 and Gate 6 complete and a maintainer records `Kernel baseline
frozen` in PRD #534. Before that event, demonstrated gaps may reopen the architecture gate and
replace the exact baseline. After it, another irreducible Kernel addition requires the next Schema
major (bADR-0022).
Its identity law also names every authority-artifact identity domain; package meta-format contracts
own package id/version grammar. Every Language Definition Bundle binds one exact
kernel-specification identity. Host implementations conform to the kernel and bundle; a Python function, reference
evaluator, or implementation table is never semantic authority (bADR-0012/0022).
_Avoid_: reference implementation as authority, host semantic kernel, implicit bootstrap

**Semantic kernel**:
The closed bootstrap operation set whose laws are fixed by the Schema-major Kernel Specification:
literals, reads, calls, value selection, typed requirements, single-level guard blocks, local
bindings, bounded aggregation, lookup, sampling, and transition/event primitives. Language
Definition Bundle rules compose those primitives into language and domain behavior. Each addition
requires formal laws, independent conforming implementations, normative vectors, and a replacement
Kernel identity; the frozen-baseline rule determines whether it enters the current or next Schema
major (bADR-0022).
_Avoid_: standard library, evaluator built-ins, host functions

**Guard block**:
The Kernel `guard-block` control node with exact members `node`, `condition`, `body`, and `outcome`.
Its condition refers to an already produced Kernel Boolean. False skips its body and continues the
enclosing Operation body. True executes its body in authored order and, unless a node refuses,
completes the Operation with the declared outcome. A guard block is allowed only in a top-level
Operation body and cannot contain another guard block. Only a typed refusal can stop its selected
body early under the closed grammar in bADR-0022. A guard block produces no local value and is not
a general two-arm branch, expression
conditional, label jump, or loop (bADR-0022).
_Avoid_: two-arm branch node, if statement, nested control block, conditional expression

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

**Experiment template**:
Editable pre-build scenario, Metric, target, seed, and acceptance intent distributed inside a
Template release. Its member kind is `experiment-template`; it cannot bind a build receipt,
Resolved Model, Package Lock, or RIR before those artifacts exist. After build it informs creation
of a separate exact `Experiment Specification`, but it is never executable under its own identity
(bADR-0017).
_Avoid_: Experiment Specification (after build), executable experiment, experiment config

**Experiment Specification**:
The authored authority for scenarios, Metric definitions, targets, sampling/replication design,
observation and discrepancy models, calibration policy, train/holdout partition, acceptance rule,
and drift policy. Each scenario authors one bounded `Executable Event plan` and assigns the
canonical union of every selected entrypoint's generated `Scenario Input Contract` exactly once.
Each transition-invocation member selects one exact `Model entrypoint` and carries a separately
derived Event-local payload; external-input members carry typed source-sequenced facts and select no
entrypoint; observation members are derived from exact Observation/Metric contracts. It cannot
select a raw LDB Operation, invent an input name, author another Runtime phase, or redefine a formal
port or model symbol. It references an exact `Resolved Model` identity or a declared compatibility
contract. Exact Resolved-Model binding is immutable; compatibility binding may compare RIR semantic
payloads but must resolve to one exact Resolved Model before execution and produce an identified
final-binding receipt. Changing RIR semantics therefore creates a new Experiment Specification
identity or an explicit, reviewable compatibility-resolution result, never a silent rebind. The
specification is versioned and hashed independently so evidence identifies both model and
experiment (bADR-0012/0018).
_Avoid_: experiment config, model overrides, scenario package

**Experiment revision**:
An immutable `Execution session` binding to one complete admitted Experiment Specification and its
exact content identity. Its revision identifier is the Experiment Specification content identity,
not a new identity family. It is not an in-place patch, session override, or separate authority kind
(bADR-0026).
_Avoid_: Experiment patch, mutable Experiment, session configuration

**Executable Event plan**:
The closed, bounded Experiment-owned plan for one scenario. Its authored root members are exactly
`external-input` or `transition-invocation`; its `observation` members are derived from the exact
Observation/Metric contracts. Every authored root has a unique `Root Event reference`, logical
time, Kernel-mapped phase for its root kind, priority, and typed payload/facts contract. Runtime
admission resolves the plan, assigns Event identities and enqueue sequence, and cannot add a
scenario timeline, choose another phase, or call a host callback (bADR-0012/0014/0018/0022).
_Avoid_: scenario loop, tick list, evaluator callback plan

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
operation bodies/signatures/effects/results, resolved Model entrypoints, exact Operation call sites,
formal-to-actual operand identities, the generated Scenario Input Contract, state and event
semantics, and other admitted runtime fragments. Source order, aliases, comments, spans, AST/HIR
identities, lowering traces, diagnostic provenance, and unselected Language Definition Bundle
inventory are excluded. Its `semantic_identity` hashes that executable semantic projection and
excludes Formula `expression` text. The separate RIR `content_identity` hashes the complete
canonical RIR JSON, including validated expressions, for exact wire integrity. If an unused package
is added to the bundle without changing resolution ambiguity, the selected closure, or the RIR JSON,
both identities remain unchanged (bADR-0013/0016/0024).
_Avoid_: Resolved Model (the authority wrapper), compiled source tree, evaluator plan

**Resolved Model**:
The immutable, content-addressed public execution-authority artifact for one exact build. Its
identity binds the exact Schema-major Kernel Specification, exact whole `Language Definition
Bundle`, canonical selected-closure `Package Lock`, RIR `semantic_identity`, and exact RIR
`content_identity`. The wrapper therefore changes when the exact bundle changes even when an
unused-package edit leaves the Lock and both RIR identities unchanged. It is the normative
cross-evaluator boundary for that exact build, not an authored authority or editable interchange
format (bADR-0012/0013/0024).
_Avoid_: RIR semantic payload (unqualified), authored model, normalized source

**Debug Map**:
A mandatory, separately content-addressed, non-semantic artifact published with every successful
Model build. It binds one exact RIR semantic-payload identity to source spans, AST/HIR identities,
lowering traces, and diagnostic provenance. It may change without changing an equivalent RIR and
cannot affect compilation or runtime behavior (bADR-0013/0022).
_Avoid_: RIR metadata, semantic provenance, embedded source map

**Model explanation**:
A mandatory, separately identified, non-semantic JSON companion published with every successful
Model build and bound to one exact Model Source, RIR semantic payload, and Debug Map. Its closed
Formula and Operation sections make the resolved model inspectable without becoming executable
authority or an editable substitute for Model Source (bADR-0013/0021/0022).
_Avoid_: decompiled model, executable explanation, generated source

**Build receipt**:
A separately identified, non-semantic provenance artifact binding the Model Source Package,
Schema-major Kernel Specification, Language Definition Bundle, Package Lock, Resolved Model,
compiler/tool identity, Resolution receipt, Debug Map, and Model explanation for one build. The
compiler produces it before publication. A separate Artifact-set receipt owns publication facts.
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
One immutable, content-addressed, namespaced, one-level aggregate admitted by a Language Definition
Bundle. Its package-specific directory contains exactly two authority JSON members: one Package
Release manifest and one bound `Package conformance vector set`. The manifest closes metadata and
semantic version, dependencies/capabilities, exported Quantity kinds/units/profiles/types, complete
Operation contracts and bodies, Diagnostics, and the vector-child descriptor; the child closes the
package's normative vectors. Package Lock binds the exact manifest content identity. Reusing one
package id/version for different content is refused within an admitted bundle. Across different LDB
identities, that logical coordinate may bind different release content; the package-release content
identity plus owning LDB identity distinguishes those non-interchangeable language worlds. Standard
Schema 2.0 claims no global release-history registry (bADR-0016/0023).
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
Experiment templates, and a `Genre coverage matrix` while preserving their separate authority
domains. Instantiation creates a new model identity with template provenance; later template
releases never mutate an instantiated game silently. First families: RPG (CRPG/JRPG/ARPG) and
Roguelike (metroidvania-like, survivors-like, deckbuilder-like) (bADR-0017).
_Avoid_: preset, profile

**Template admission profile**:
An LDB-owned, versioned artifact-graph program over Kernel-defined Schema-major primitives. The
Kernel machine specification closes each primitive's typed arguments and result effect, evaluation
law and order, failure mode, canonical comparison, and resource-charge events; operations bind
stable LDB-facing names to those primitives. The profile maps
member kinds to ordered role collections with explicit cardinality and role-operation obligations,
derives named graph facts through declared selectors and bindings, and runs under a bounded
per-release step budget. Role names and member kinds are LDB content rather than a Kernel
inventory, so a genre can add them without changing core. The program requires the starter to pass
the ordinary Model Source path and every declared negative/boundary vector to execute; it does not
grant language authority to the Template (bADR-0017).
_Avoid_: template validator callback, host companion checks, genre runtime profile

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
matrix is not representational-adequacy evidence. Research mappings may discover or refine rows,
but they are not conformance evidence and cannot close one (bADR-0017).
_Avoid_: feature checklist, roadmap, package inventory

**Golden scenario**:
A canonical Model Source Package plus Experiment Specification and expected compiled/runtime/
evidence observations that exercises one or more coverage-matrix requirements end to end. Golden
scenarios test package composition and public artifacts, not private evaluator functions
(bADR-0017).
_Avoid_: unit fixture, demo battle, snapshot test (too narrow)

**Claim closure**:
The bADR-0012-owned transition from an open requirement, coverage row, or evidence assertion to a
justified claim. bADR-0012 exclusively defines its artifact, graph, Verifier-receipt, independence,
and Gate 2 dependency law; other documents may add only domain-specific prerequisite inputs. A
Runtime-refusal prerequisite additionally applies bADR-0015's exclusively owned terminal-audit
member and binding contract. This glossary names the concept but does not redefine either law
(bADR-0012/0015).
_Avoid_: self-attestation, passed flag, expected-result closure, digest checklist

**Verifier receipt**:
An immutable claim-verification artifact whose identity binds the verifier identity, verifier
implementation and judgment-policy identities, exact prerequisite artifact identities/graph, and
resulting judgment artifact identity. It is issued only after the exact authority, envelope,
artifact-set/receipt, graph, and applicable terminal-audit validators succeed; it never repairs or
replaces a missing prerequisite. A consumer authenticates it and establishes verifier eligibility,
independence, and trust before closure. Its signature, credential mechanism, and deployment trust
topology remain later policy choices (bADR-0012).
_Avoid_: checksum, self-signed passed flag, verifier log, validator substitute

### Standard Schema design

**Core type constructor**:
One of the closed Standard Schema 2.x language-level constructors: `Bool`, `Int`, `Fixed`,
`Decimal`, `Float`, `Enum`, `Record`, `Vector`, `List`, `Set`, `Map`, `Ref<T>`, `Quantity`, or
`Distribution`. Domain packages instantiate and compose these constructors but cannot add grammar
or primitive representation semantics; changing this set requires a Schema major decision
(bADR-0016).
_Avoid_: package type, attribute type, custom primitive

**Nominal reference**:
A core `Ref<T>` value that identifies one stable target under a nominal target contract without
granting traversal, lifecycle, or object semantics. Its canonical identity pairs the statically
known target identity with a package-defined canonical reference key. The Ref definition carries
the key pattern, so a host cannot substitute its own identifier rule. The exporting package owns
existence, lifetime, and missing-target outcomes. `game.entity` defines `EntityRef` as its
`Ref<game.entity.Entity>` specialization; other packages may specialize references for their own
nominal artifacts without pretending they are game entities (bADR-0016).
_Avoid_: untyped id, host object reference, EntityRef as core primitive

**Typed value envelope**:
The public `{type, value}` form for a structured literal, Experiment assignment, Runtime fact, or
generated artifact member. `type` names one exact nominal type or closed generic type expression.
`value` must satisfy that type's admitted Enum, Record, List, or Ref contract. The envelope does not
add a second type authority; it carries the LDB-selected type across public boundaries. Numeric
values keep their existing enclosing Quantity contract (bADR-0016/0022).
_Avoid_: tagged host object, untyped JSON payload, evaluator-specific value wrapper

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
numeric type. Domain roles are versioned package terms and never infer representation, nominal kind,
unit/dimension, support, or Numeric policy; `rate` does not define its own denominator (bADR-0016).
_Avoid_: attribute type, variable kind (ambiguous), numeric subtype

**Formula declaration**:
A module-level, Model Source-owned named pure computation with explicitly typed parameters, one
result contract, and a structured expression body. It is statically resolved rather than passed,
stored, or selected as a Runtime value, and never owns Event control, state transition, RNG,
gameplay outcome, or commit/rollback behavior (bADR-0022).
_Avoid_: formula script, anonymous callback, first-class function, Event program

**Formula notation**:
The canonical human-readable mathematical `expression` paired with a Formula's structured `body`.
It preserves the body's ordered `let` bindings, local identities, sharing, and final result while
using package-owned conventional Operation spelling. The body remains the pair's authoritative
source member; the expression is a contextual, reversible projection under the exact Kernel/LDB.
`standard.schema` owns the lexical patterns and grouping/token bounds; the selected
`standard.compiler` Resolution profile owns contextual contract matching, local-result transfer
rules, and infix normalization. Package Release content identity binds notation, while the
Kernel-declared runtime-semantic projection excludes each release's explicitly inventoried
non-runtime notation extensions.
bADR-0024 owns its grammar, exact pair validation, identity effects, and conformance requirements.
_Avoid_: host expression dialect, display-only operation table, fully qualified call dump

**Formula conversion**:
The public, non-executing transformation exposed by `formula parse` and `formula render`. `parse`
binds notation to one exact Formula context and returns canonical `body`/`expression`; `render`
validates a body under the same context and returns the same pair. Conversion publishes no semantic
artifact. Cross-module coordinates require the request's model-wide `modules` resolution closure;
imports remain bound to exact declared requirements and exported types. Production paths share one
implementation; an independent conformance consumer derives
the contract separately from sealed Kernel/LDB authority (bADR-0024).
_Avoid_: formula evaluation, context-free expression conversion, model inspection alias

**Formula binding**:
The exact, statically resolved association between a Model Source Formula declaration and a typed
formula call site used by a `derived` Symbol or an Operation Formula slot. It fixes the selected
formula and a total named parameter-to-actual-operand mapping before Runtime, and carries the
LDB-derived transitive refusal/resource/termination contract for the complete reachable Formula and
pure-Operation call graph. It cannot depend on parameter order, same-name capture, dynamic formula
lookup, or host callback semantics (bADR-0013/0022).
_Avoid_: function pointer, runtime formula selection, evaluator hook

**Formula slot**:
A named, exactly-one customization point in an Operation specification with an explicit Formula
signature, evaluation context, permitted refusal set, and deterministic resource budget. A selected
Operation requires exactly one compatible Model Source Formula binding for each declared slot; each
binding's complete transitive contract must fit its owning slot, and neither the package nor
evaluator supplies a fallback (bADR-0022).
_Avoid_: optional callback, formula hook, package default

**Formula evaluation site**:
One statically resolved read or call of a Formula binding with a stable identity, explicit operand
sources, one lifecycle context, and its complete transitive refusal/resource contract. Every
dynamic evaluation, including a cache hit, replays the site's deterministic charge vector against
the current Runtime resource ledger; a cache can reuse the pure result but never skip accounting or
cache resource exhaustion independently of that ledger. Multiple sites may reference one Formula
declaration; a `derived` Symbol read from different lifecycle contexts lowers to distinct sites
rather than one ambient evaluation mode (bADR-0022).
_Avoid_: dynamic call, formula invocation hook, implicit read context

**Formula evaluation context**:
The exact lifecycle boundary and typed value environment in which a Formula binding is evaluated.
Initialization, Event, observation, and Effect capture/re-evaluation contexts select committed
Snapshots or the pre-Snapshot Initialization frame plus explicit operands without giving the
Formula ambient state or timing authority (bADR-0014/0017/0022).
_Avoid_: formula mode, ambient evaluation environment, live formula

**Core Extension Invariance**:
The Standard Schema 2.0 promise that a later game genre can add Model Source, complete Domain
package releases, templates, Experiments, coverage rows, and vectors without changing Kernel
primitives, core constructors, runtime phases, compiler dispatch, or evaluator dispatch. A bounded
deterministic mechanic that cannot pass this test falsifies and reopens the 2.0 architecture; it is
not handled through a genre exception or host plugin. The invariant does not claim every genre's
support artifacts already ship (bADR-0016/0017).
_Avoid_: universal genre coverage, genre-specific core, best-effort extensibility

**Extension Invariance Receipt**:
The immutable conformance artifact proving one Core Extension Invariance witness ran through the
same fixed independent compiler/evaluator builds before and after an LDB/package addition. It binds
identical Kernel, core-constructor, runtime-phase, and implementation-build identities; base/extended
LDBs; added packages; exact Source/Experiment/vectors; mutually produced artifacts/results; and a
complete post-build Non-Kernel Authority Token Inventory plus its exhaustive rename bijection.
Rebuilds, host capability additions, omitted renames, private helpers, or changed core projections
make it ineligible. It is independently validated evidence, never semantic authority
(bADR-0016/0017).
_Avoid_: unchanged-code assertion, source diff, extension passed flag

**Non-Kernel Authority Token Inventory**:
The closed, generated traversal of the complete reachable witness artifact graph used by an
Extension Invariance Receipt. It contains every non-Kernel identity that can affect resolution,
dispatch, result decoding, or trace, including package/capability, type/kind/unit/role,
Operation/parameter/result variant, Diagnostic, Signal/Event, effect/resource, profile/policy,
Experiment/Metric/selector, and vector identities. Its independent rename mapping is an exhaustive
bijection: an omitted, duplicate, reserved-Kernel, or extra member refuses the witness
(bADR-0016/0017).
_Avoid_: representative token sample, package-name-only rename, implementation symbol list

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
runtime contract: named `Formal port`s and result, unit rules, purity, resource bounds, Numeric
profiles, declared reads, writes, emitted signals, scheduled events, Named random streams, and a
body whose nested calls use explicit port-to-operand bindings. An evaluator implements this
contract; its host-language function is not the authority (bADR-0012/0016).
_Avoid_: function registration, evaluator hook, opcode documentation

**Formal port**:
A named, typed input declared once by an LDB `Operation specification`. The formal port is the sole
authority for that Operation's reusable consumption interface. Model symbols, caller locals, and
literals do not redefine it; a `Model entrypoint` or nested `Operation call site` binds each
required formal port exactly once to one compatible `Actual operand` (bADR-0016/0022).
_Avoid_: model input name, scenario variable, argument copied into every consumer

**Actual operand**:
The explicit value source bound to one `Formal port` by either a `Model entrypoint` or nested
`Operation call site`: a resolved Model symbol, a caller-local result, a contextually typed literal,
or another Kernel-admitted expression. Its identity is derived from the owning authority and
binding position. Equal display names are never binding proof, and one actual may intentionally
feed multiple compatible ports. A package-owned `Literal Typing Profile`, not the Symbol assignment
policy or host integer type, types a literal; admission requires exactly one selected profile to
match the formal port's complete value contract and records that context in RIR identity
(bADR-0013/0016/0022).
_Avoid_: implicit same-name lookup, ambient variable, parameter declaration

**Literal Typing Profile**:
An independently exported LDB definition that lets one package map a source-literal kind and
value shape to an exact type/value contract. Numeric profiles own bounded integer ranges and their
representation, kind, unit, domain, and Numeric policy. A structured profile admits an explicit
typed value envelope and validates its value against the referenced nominal definition. The
exporting package must own that exact Type release. The profile must close against the LDB value
inventories and match at least one Operation formal value contract. Overlapping profiles for the
same match contract are refused. Selected profiles enter RIR runtime semantics, while the Symbol
assignment policy remains limited to Symbol roles, access, initialization ownership, and
Experiment cardinality (bADR-0016/0022).
_Avoid_: host literal default, lowering-owned literal table, Symbol assignment rule

**Operation call site**:
One statically bounded nested invocation of an exact versioned Operation owned by another LDB
`Operation specification` body. It owns a stable site id, exact formal-to-actual bindings,
result/outcome binding, and resolved effect/refusal/resource closure. Typed HIR resolves it before
RIR; RIR identifies it; an EIR may optimize it but must preserve the same bindings and observable
provenance. It is distinct from a root `Model entrypoint`, and from the Formula evaluation site
owned by issue #590. That accepted contract introduces a statically resolved expression-shaped
actual operand without changing this call contract (bADR-0013/0016/0022).
_Avoid_: dynamic dispatch, operation name alone, evaluator callback

**Model entrypoint**:
An authored Model Source declaration that binds one exact LDB Operation's formal ports to the
model's resolved symbols and binds or explicitly discards its result. It is the only Experiment-
selectable execution root. Its identity changes when the selected Operation, any formal-to-symbol
binding, result binding, or reachable semantic closure changes (bADR-0012/0013).
_Avoid_: raw operation selector, scenario operation, implicit main

**Scenario Input Contract**:
The generated, ordered initialization contract for one `Model entrypoint`, derived from its
reachable Model-symbol operands and the LDB-owned total Symbol assignment policy. It records exact
resolved Model-symbol identities, Model-owned value-policy initializers, Experiment-owned required
inputs, and optional Experiment overrides of explicit Model defaults. An Experiment scenario must
assign every required member exactly once, may assign an exported optional member at most once, and
cannot assign anything else. It references identities and supplies values but does not own or
duplicate symbol declarations or Operation formal ports. Each policy role is machine-classified as
an Operation operand, Operation result, or internal generated value; authority admission rejects an
operand mode that has neither an Experiment assignment nor a Model initializer, and rejects a
result mode not produced by execution (bADR-0012/0013/0022).
When one scenario selects several entrypoints, initialization is the canonical union of their
targets: equal targets with equal contracts collapse, while conflicting contracts or assignments
refuse. This union is a derived projection, not a second Scenario Input Contract. Event-local
payloads and external facts never become initialization members. The LDB assignment mode derives a
separate payload contract for each entrypoint: an admitted read-only, Experiment-initialized
parameter or input may be overridden for one Event, while state and every other forbidden target
cannot appear in that payload. The same mode independently declares external-fact cardinality;
only an admitted read-only, Experiment-initialized operand may be exposed to an external-input
root, and every other mode is forbidden.
_Avoid_: scenario values by name, operation parameter list, Experiment-owned model schema

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
successfully mapped construct, explicit default, warning, and every explicitly deprecated
construct. On success, the `migration-report` and new 2.x Model Source Package are one atomic
success artifact set. On refusal, an LDB-validated `migration-refusal-report` is carried inside the
typed exit-2 envelope; it is not a command success artifact and no 2.x Model Source Package is
published. Partial or lossy migration is never presented as success (bADR-0019/0021).
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
A composition of independently typed contracts for application requirements, value source
(`base`/authored or `resolved`/derived), capture timing (`snapshot` or `live`), continuous
contributions, buildup and threshold activation, state transitions, scheduling, stacking
identity/reducer, reapplication, removal/expiry/dispel, and immunity. Source and capture timing are
orthogonal. Buildup activation creates one effect instance with a bounded schedule; typed removal
cancels that instance's exact outstanding events. Requests follow Event order. Each active Event
forms one canonical request envelope from its declared Operation and resolved Signal-subscriber
request buffer, then partitions that envelope by canonical effect lifecycle key into exactly one
`EffectRequestSet` per key; child-Event requests are excluded and resolve later. Typed removal
dominates same-key tick/transition/contribution/reapplication, followed by
application/immunity, buildup/activation, stack/cap/reapplication, capture/contribution/transition,
and the final schedule delta under one complete versioned policy. Within each stage, canonical
request origin keys plus the policy's total variant order and multiplicity reducer select one
deterministic result and typed removal cause; every losing/coalesced request is traced. Action,
combat, resource, and runtime packages
consume these contracts through declared operations; no single Effect object owns every mechanic
(bADR-0016/0017).
_Avoid_: modifier list, buff object, monolithic status schema

**Reaction window**:
A bounded `game.turn` Domain protocol over a stable pending `game.action` proposal. It owns eligible
responder order, priority holder, pass/close policy, and nesting bound. Counter, replacement,
cancellation, and pass choices enter at declared Runtime input boundaries and advance through
ordinary transition Events; only a closed window schedules final Action resolution. It never adds a
runtime phase, pauses an active Event for a host callback, or uses a Signal as interactive delivery
(bADR-0014/0017).
_Avoid_: interrupt callback, hidden reaction phase, Signal response

**Ordered collection**:
A `game.collection`-owned typed sequence of stable instance identities with explicit zone
membership, stable order, legal moves, and named-stream shuffle handoff. Core `List` supplies
representation only; build admission, run reset, and economic ownership stay with their own
packages (bADR-0017).
_Avoid_: generic inventory, host card array, unordered deck

**Reward disposition**:
The typed destination instruction returned with a generated or selected reward definition. It
names which owning package performs the mutation—such as collection movement, economic transfer,
effect application, or build admission—without forcing every reward through an economy ledger
(bADR-0017).
_Avoid_: reward grant (without destination semantics), universal inventory transfer

**Reward rarity policy**:
A `game.generation`-owned closed selection policy whose declared variant is fixed, pity, or
guarantee. Each variant specifies its state, reset, eligibility, and refusal laws. Selection
exhaustion behavior is a separate declared fallback; a pity bound does not silently imply a
guarantee or fallback (bADR-0017).
_Avoid_: luck curve, implicit pity, rarity callback

**Rarity-policy state**:
The `game.generation` state that records the selected `RarityPolicyKind` and its draw count at an
Event boundary. A reward selection carries the state before and after the draw. A declared
no-reward fallback preserves both values because it consumes no draw. Later policy variants may add
state only through a new package contract; Runtime does not infer pity or guarantee progress
(bADR-0017).
_Avoid_: RNG state, implicit pity counter, evaluator policy state

**Reward score**:
The typed Quantity paired with one `RewardOption` and copied to the `reward_score` state port when
that option or the declared no-reward fallback is selected. It is an explicit result observation,
not an implicit weight, probability, or evaluator ranking rule (bADR-0017).
_Avoid_: draw weight, hidden fitness, evaluator score

**Selection exhaustion**:
Selection exhaustion occurs when an already ordered eligible pool is empty. It is not a nonempty
but unselectable pool, contradictory option data, an invalid fallback value, or a later build
conflict.
Without a declared fallback it is a typed refusal; with the declared no-reward fallback it enters
that fallback's gameplay outcome (bADR-0017).
_Avoid_: empty candidate selected, invalid pool, build conflict

**Declared fallback**:
A `game.generation` exhaustion declaration that names its trigger and exact bounded fallback value
before Runtime execution. The zero-or-one `no_reward_on_empty` field is independent of the primary rarity
policy. When it applies, the Operation commits the exact fallback selection and its score to the
declared `selected_reward` and `reward_score` state ports, completes with the `no-reward` gameplay
outcome, produces no Operation result, preserves policy state and draw count, and consumes no RNG.
A normally selectable no-reward option is not fallback. Relaxed-pool behavior requires an actual
excluded pool, eligibility predicate, and relaxation order; the term alone declares no semantics
(bADR-0017).
_Avoid_: sentinel candidate, evaluator default, implicit retry, relaxed-pool label without a pool

**Action plan**:
An immutable, fully bound `game.action` input containing the selected action and execution inputs.
`game.action` owns its closed schema, admission, identity, and exact execution. It may enter through
a declared external input or be selected from admitted candidates by optional `game.decision`,
which owns only bounded selection and Intent projection policy (bADR-0017).
_Avoid_: AI callback, mutable command, projected intent

**Intent projection**:
A `game.decision`-owned observation derived from an Action plan for player-facing or evaluator
inspection. It cannot authorize, mutate, or replace the plan, while encounter owns only the actor,
context, and decision window (bADR-0017).
_Avoid_: executable intent, encounter AI, action preview as authority

**Atomic build replacement**:
One `game.build` transition that removes an exact existing admission and installs an exact
replacement or refuses with neither change visible. It is not modeled as two separately observable
remove/add mutations (bADR-0017).
_Avoid_: unequip then equip, best-effort replacement, compensating add

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
list is never semantic authority. Conformance reverse-enumerates every reachable emission against
the applicable Kernel/LDB catalog, rejects missing or extra mappings before use, and uses behavior
vectors to trigger every authoritative code and confirm its stage; forward lookup alone is
insufficient (bADR-0012/0015/0022).
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
The seed that actually drove a stochastic run. In Standard Schema 1.x it is supplied through the
legacy `--seed` surface or drawn fresh (bADR-0008/0010). In Standard Schema 2.x it is owned by the
exact Experiment Specification; no free CLI flag or evaluator default may override it. It is the
root of named streams and is reproducible only together with the exact Resolved Model, Experiment
Specification, Resolved Runtime profile, and external-input identities (bADR-0014/0021). The
reproduction receipt records that complete binding; the Resolved Runtime profile closes evaluator,
platform, Numeric, RNG, scheduler, effect, and budget choices.
_Avoid_: random seed (ambiguous), default seed

### Runtime

**Execution session**:
A host-scoped coordination handle that binds one exact Resolved Model and admitted immutable
Experiment revisions for later execution. It is not a Standard Schema authority, Runtime instance,
gameplay `Run scope`, or HTTP transport session (bADR-0026).
_Avoid_: Runtime session, playtest session, HTTP session, Experiment session

**Runtime lifecycle**:
The explicit state machine for one RIR execution instance: `instantiated`, `initializing`, `event`,
`step`, `terminated`, and reset to a new instance. The states adapt FMI's lifecycle discipline to
Standard Schema artifacts and the atomic-event runtime without adopting FMU, C API, or
co-simulation compatibility (bADR-0014/0020).
_Avoid_: FMI runtime, process lifecycle, implicit evaluator state

**Runtime step**:
The public boundary-directed advance that dispatches as many totally ordered atomic Events as
needed to reach the next declared observation or logical boundary. An internal scheduler transition
dispatches one Event; `event-steps` counts Operation work and is neither a Runtime step nor logical
time. Reaching an Event-count terminal threshold drains the active logical-time transition phase
before terminating at the next Runtime-step boundary; the threshold cannot introduce an
observation ahead of a pending same-time transition. There is no universal tick
(bADR-0014/0020/0022).
_Avoid_: tick, one Event dispatch, scenario step

**Runtime profile definition**:
The Language Definition Bundle-owned, immutable contract for one admitted execution policy:
scheduler/phase semantics, budget vocabulary and accounting units, Named-stream derivation,
`Numeric profile`, complete RNG sampling law, permitted effect sets, primitive requirements,
overflow behavior, and portability constraints. It contains no bundle identity, evaluator build,
host platform, or deployment fact, so it cannot form an identity cycle with its owning bundle
(bADR-0014/0022). Its required shape and Runtime/RNG bindings come from the Kernel's
active-definition contract, while its concrete positive resource-bound values remain LDB content;
host constants are not a peer profile authority.
_Avoid_: environment, evaluator configuration, resolved execution identity

**Runtime program contract**:
The Schema-major Kernel-owned, closed machine contract for irreducible runtime nodes and laws. It
enumerates each node's exact fields, operator, result/transition kind, refusals, and resource charge,
plus Numeric bounds, Named-stream RNG derivation/state/sampling/bias/trace laws, Event atomicity,
typed outcome requirements, normative vectors, and a complete abstract-role contract for every
evaluator-consumed scheduler, Runtime-configuration, transition, and step object and relationship.
LDB Operations compose these nodes and own their domain-specific typed outcome algebra; evaluator
code implements the role meta-protocol and contract but does not add fields, outcomes, constants,
paths, or behavior. The complete role-to-structure mapping is content-addressed, and an evaluator
admits only a mapping identity it explicitly implements; concrete Kernel values remain outside
that implementation capability identity (bADR-0014/0022).
_Avoid_: node-name registry, evaluator dispatch table, host runtime semantics

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

**Runtime profile definition identity**:
The Kernel-domain-separated content identity of one complete LDB-owned Runtime profile definition.
The Resolved Runtime profile binds it together with the Evaluator Capability Manifest identity;
the definition and evaluator manifest never refer back to that generated artifact, keeping runtime
admission identities acyclic (bADR-0014).
_Avoid_: Resolved Runtime profile identity, profile id alone, host runtime preset

**Evaluator Capability Manifest**:
An immutable implementation-provenance artifact published by one evaluator build. It declares the
exact Kernel law versions, constructors, Numeric/RNG policies, scheduler/effect features, artifact
schemas, and resource-accounting contracts that build implements. Runtime admission validates and
binds it into the Resolved Runtime profile; it cannot admit LDB-absent behavior or weaken semantic
law. It is distinct from the generated model/package Capability manifest (bADR-0014).
_Avoid_: evaluator plugin registry, semantic authority manifest, Package Capability manifest

**Portable Observation Policy**:
The closed, versioned LDB artifact that makes Cross-evaluator comparison non-vacuous. It binds an
applicable Runtime/Numeric profile scope, closed selector grammar, mandatory observation classes,
canonical projection/comparator mapping, and deterministic closure/order algorithm. It derives a
`Resolved Portable Observation Plan`; it does not own or copy Experiment intent.
Exact semantic values use exact comparison; inexact Numeric values may use only the common
profile's fixed tolerance. Empty or under-covering policies, caller-filtered subsets, unknown
selectors, evaluator-specific fields, and widened tolerances are refusals (bADR-0014/0018).
_Avoid_: comparison field list, best-effort diff, caller-selected observations

**Resolved Portable Observation Plan**:
The generated, validated projection of one Portable Observation Policy for an exact common Runtime
profile definition, selected Package Lock/RIR, Experiment Specification, and selected vectors. It
enumerates the complete ordered semantic selectors, observation kinds, projections, and comparators
required by that comparison and has its own bound identity. It is neither authored intent nor LDB
authority; empty, incomplete, duplicated, unknown, evaluator-specific, or tolerance-widened plans
are refusals (bADR-0014/0018).
_Avoid_: authored comparison plan, Experiment copy, caller field selection

**Cross-evaluator comparison**:
An immutable conformance artifact comparing observations from independent evaluator realizations
whose Resolved Runtime profiles intentionally differ. It binds both profiles plus the exact common
Kernel Specification, Language Definition Bundle, Package Lock, Resolved Model/RIR semantic
payload, Runtime profile definition,
Experiment Specification, external inputs, seed, exact Portable Observation Policy, generated
Resolved Portable Observation Plan, and every match/mismatch. It is not an Evidence assertion and
carries no embedded
`cross_evaluator_conformant` claim. A separately validated positive result may support that Evidence
assertion; it is never a `Replay comparison` and cannot satisfy `reproducible`
(bADR-0014/0018/0022).
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

**Defeat transition**:
An authored `game.combat` transition that compares the committed result of damage resolution with
an explicit non-negative defeat threshold and publishes the typed `target-defeated` outcome. The
combat package owns this transition policy and refuses a negative threshold before resource use,
RNG, or state change. Health storage remains a resource concern, and defeat/revival state storage
remains an entity concern. Runtime does not infer defeat from a health-like value (bADR-0014/0017).
_Avoid_: HP check (unqualified), Runtime defeat inference, host-side death rule

**Combat action eligibility**:
The authored `game.combat` predicate that decides whether one combatant may execute a combat
Operation. The current eligible-cast contract compares actor health with the explicit defeat
threshold before resource spending, RNG, or damage. The threshold must be non-negative. An
ineligible actor returns the typed `actor-ineligible` outcome with no state change. This predicate
does not define turn order or the eligible-responder order owned by `game.turn` (bADR-0017).
_Avoid_: UI can-act flag, host eligibility check, turn eligibility (when combat eligibility is meant)

**Periodic Effect**:
A gameplay Effect whose selected Domain package closes one bounded apply/tick/expire lifecycle:
duration and period, scheduled logical times, magnitude capture/read policy, contribution, expiry,
typed outcomes/refusals, Numeric behavior and resource bounds. Its lifecycle Operations schedule
ordinary Runtime events and use the same atomic transaction, ordering and Snapshot laws as every
other transition. It is not a Kernel primitive or a second time-advancement system
(bADR-0014/0016).
_Avoid_: Effect loop, fixed tick loop, repeated Experiment scenarios

**Effect instance**:
One package-defined occurrence of a Periodic Effect, identified at apply by the package's declared
bounded Named-stream draw and carried through every scheduled tick and expiry Event. The instance
value correlates one lifecycle; Runtime still owns each Event identity and does not infer stacking,
dispel, contributor or defeat policy from the value. This periodic slice creates one directly at
apply; buildup-based Effects create one at threshold activation under the broader Effect
specification (bADR-0014/0016).
_Avoid_: Effect Event identity, ambient effect object, host timer handle

**Magnitude timing policy**:
The Domain-package contract that determines when one exact bound Formula is evaluated and when its
result is read. `snapshot` evaluates once against apply's pre-Event committed Snapshot and carries
the captured result into scheduled ticks; `live` evaluates at each tick against that tick Event's
pre-Event committed Snapshot. Both use ordinary Formula bindings/evaluation sites and never read
another Event's buffered writes. This policy specializes the Effect specification's capture-timing
axis by binding it to a Formula evaluation context (bADR-0014/0016/0022).
_Avoid_: evaluator callback timing, host-side magnitude mode, second Effect expression

**Root Event reference**:
The unique stable authored identity of one external-input or transition-invocation root member in
an Executable Event plan. Runtime admission maps canonical root order to Runtime-owned `event_id`
and enqueue sequence before dispatch and exposes the complete reference map. Scheduled children
have Runtime Event identities and parent/call-site provenance but no invented root reference
(bADR-0014/0018/0022).
_Avoid_: Event id, array index, host object identity

**Event reference**:
A typed Runtime-Event value passed through an explicit Model entrypoint operand. Model Source names
the operand's role, such as `counterattack`; the Experiment binds that role to one authored Root
Event reference in the same Scenario; and Runtime resolves the binding to the already admitted
Event's stable `event_id` before dispatch. It is neither ambient queue lookup nor permission to
infer a target from time, ordering, combatant name, or game state. A Kernel node such as `cancel`
may consume it only through its declared Event-reference port contract (bADR-0014/0022).
_Avoid_: next Event, queue cursor, Root Event reference (the authored name), raw Event id

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
after commit and is not a participant. A runtime refusal after Event dispatch begins must publish a
separately typed terminal-audit artifact set through this boundary, but never a partial
Evaluation/Metric/Evidence success set (bADR-0015/0021).
_Avoid_: atomic file write, output directory, event transaction

**Artifact set manifest**:
The canonical member map for one producing outcome. It binds each typed logical member name to its
artifact kind, wire-schema identity, and content identity, and its own identity covers that framed
map. A list of anonymous digests or a digest over unframed concatenated member bytes does not bind
member names or boundaries and is non-conforming. Publication receipts and retrieval revalidate the
complete manifest and every member (bADR-0012/0015/0018).
_Avoid_: file list, concatenated checksum, output directory manifest

**Initialization frame**:
The immutable pre-Snapshot value environment assembled from the exact Experiment inputs, constants,
parameters, and declared initial base state after Runtime admission. Initialization Formula sites
read this frame to derive and validate Snapshot 0. It is discarded on refusal and never
misidentified as a committed Snapshot, Event, or terminal-audit member (bADR-0014/0022).
_Avoid_: initial Snapshot, initialization Event, mutable setup state

**Snapshot boundary**:
The semantic state boundary committed after successful initialization and after every committed
Event transaction. The pre-Snapshot Initialization frame is not a Snapshot. The full state exists
conceptually at each boundary; traces may store a canonical state hash and materialize full state
only at declared checkpoints without changing semantics. A materialized Snapshot continuation
binds the selected Runtime profile plus append-only admitted-Event and committed-trace prefix
identities; the Snapshot Series stores each complete normalized admitted Event specification once,
and recovery revalidates its identity plus catalog, commit, and cancellation prefixes to reconstruct
the exact pending queue. Root, scheduled, and observation catalog entries must also rebind to their
checked Experiment, committed parent plus exact RIR scheduling Operation/call path/site and
normalized actual operands, or Metric authority respectively. Scheduled operands are independently
recomputed by boundedly replaying that RIR path from committed parent inputs and state; a
Named-RNG-derived local also replays from the checked seed through the verified committed draw
prefix rather than trusting a traced draw value;
self-consistent fresh hashes do not prove admission (bADR-0014).
_Avoid_: save point, frame snapshot, periodic dump

**Runtime refusal**:
The deterministic terminal result when execution cannot legally continue after successful static
validation — for example initialization cannot lawfully create Snapshot 0, an Event targets a past
phase, an Event budget is exhausted, or a Runtime Operation violates its declared domain. A refusal
during atomic initialization discards the Initialization frame and publishes no Snapshot, Event,
trace, or terminal audit. After Event dispatch begins, the current Event transaction is rolled
back, its children are discarded, prior commits remain represented by one complete, atomically
committed terminal-audit artifact set, and the run stops (bADR-0014). Both are `runtime`-stage typed
refusals with exit 2 on stdout; only the post-dispatch variant carries the retrievable terminal-audit
receipt. Failure to publish a required post-dispatch set before commit is an `internal` command
outcome, while failure after commit leaves the set recoverable by its durable invocation identity
(bADR-0015/0021). Recovery admits the terminal audit only when its admitted-Event catalog and
committed-trace prefixes, complete last Snapshot, rollback equality, complete refusing Event
specification, terminal condition, exact catalog/trace/resource coordinates, Diagnostic, and
reproduction receipt close against checked authority. A not-yet-admitted observation must be the
next Metric at the last Snapshot's logical boundary and enqueue cursor, while attempted Event/node
steps must close against that Snapshot's resource ledger and applicable Formula charges plus the
current Event charge derived, without rerunning the evaluator, by walking admitted RIR resource
transitions to the first budget-breaching instruction and completed nested-call prefix.
Member-level wire validity and coordinated
fresh hashes are insufficient.
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
prerequisite for a separately issued `reproducible` Evidence assertion; the comparison is not that
assertion and carries no embedded `reproducible` claim. Runs under different evaluator-bound profiles
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

**Evidence claim kind**:
A closed, versioned LDB registry entry defining one Evidence assertion label's subject types,
required prerequisite graph, eligibility judgment, issuer/verifier class, and vectors. Domain
packages may provide subjects and policies but cannot mint claim labels; an unknown or incomplete
claim kind is an `evaluation` refusal. `approved` is deliberately excluded because it belongs only
to Approval Record authority (bADR-0018).
_Avoid_: free-form evidence label, package claim alias, approved assertion

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
