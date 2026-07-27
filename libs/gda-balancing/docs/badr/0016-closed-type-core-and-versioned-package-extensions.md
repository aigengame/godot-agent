---
status: accepted
---

# Keep the type core closed and extend game domains through versioned packages

Standard Schema 1.x made attributes, float parameters, formula references, effects, and reserved
sections the central schema vocabulary. The RPG template review showed that extending those shapes
field by field would make every game concept compete for a place in the root schema. It would also
conflate unrelated concerns: numeric representation, game meaning, units, legal domains, lifecycle,
and tuning role.

Standard Schema 2.x needs to represent RPG and Roguelike systems without turning their current
mechanics into universal primitives. At the same time, an “open extension map” or evaluator plugin
would sacrifice static typing, deterministic execution, and cross-implementation meaning. PRD #534
therefore requires a small closed type language and a constrained package extension contract.

## Decision

- **The core type-constructor set is closed:** `Bool`, `Int`, `Fixed`, `Decimal`, `Float`, `Enum`,
  `Record`, `Vector`, `List`, `Set`, `Map`, `Ref<T>`, `Quantity`, and `Distribution`.
  Domain packages compose and instantiate these constructors. They cannot add primitive wire
  syntax, host-language objects, or new representation semantics. Adding or changing a constructor
  is a Standard Schema major decision in the Language Definition Bundle.

- **One closed type interpretation serves every boundary.** Kernel-law parameter/result checks,
  Language-rule terms, Operation arguments/results, package contracts, HIR/RIR fields, and runtime
  admission must recognize the same admitted constructors and recursively validate the same nested
  shapes. A host cannot implement a smaller private matcher for one call path or accept a larger
  host-native value set at another boundary.

- **Quantity separates five orthogonal concerns:**
  1. numeric representation (`Int`, `Fixed`, `Decimal`, or `Float`);
  2. nominal kind — package-defined semantic identity such as health, mana, damage, or currency;
  3. unit and dimension;
  4. support/domain — intervals, discreteness, allowed exceptional values, and other value-set law;
  5. Numeric-profile policy — rounding, overflow, non-finite, tolerance, and portability behavior.
  Equal representation or dimension does not erase nominal kind. Packages may define kind
  relationships only through explicit operation/conversion contracts.

- **Lifecycle and domain uses are Symbol roles, not numeric types.** Core symbol roles include
  `constant`, `parameter`, `input`, `state`, `derived`, `output`, and `random`. Domain roles such as
  `current`, `capacity`, `cost`, and `rate` compose separately on typed symbols or component fields.
  Roles constrain who may initialize, tune, read, write, sample, or export a value; they do not
  create `CurrentNumber`, `CostNumber`, or other redundant type constructors. Domain roles are
  versioned nominal terms owned by their exporting package and may be added without changing the
  core role set. They never infer or override representation, nominal kind, unit/dimension,
  support, or Numeric policy. In particular, `rate` describes a domain use; its denominator and
  dimensional legality still come only from the Quantity unit and operation contract.

- **`attribute` is not a 2.x language primitive.** A domain package may call a Quantity-typed symbol
  or component field an attribute in its own vocabulary, but the compiler sees the same typed
  declaration machinery used by resources, cooldowns, currencies, positions, counters, and rates.
  New attributes therefore require data declarations, not changes to the root schema or evaluator.

- **References are generic and nominal; entities are a package specialization.** `Ref<T>` denotes a
  stable reference to a nominal target contract and carries no traversal, lifecycle, or game-object
  semantics. Its canonical value is the pair of the statically known nominal target identity `T`
  and one canonical package-defined reference key; equality requires both to match. Referential
  existence, creation, lifetime, and missing-target outcomes belong to the exporting package's
  declared operations, so the core never dereferences a host object or assumes compile-time
  existence. `game.entity` defines `EntityRef` as its admitted `Ref<game.entity.Entity>` alias and
  owns the referenced entity/component contract. Entity references are therefore not untyped ids,
  while non-game packages may reference their own nominal artifacts without pretending they are
  entities. A package cannot reopen another package's record or attach undeclared fields.
  Additional behavior composes as a separate component and explicit operations over imported
  contracts.

- **Every Domain package release is one complete, immutable one-level aggregate in the Language
  Definition Bundle.** Its manifest content identity covers the namespaced package id; semantic
  version; required and
  optional dependency coordinates, each with an exact package id and version in the current 2.0
  contract;
  provided and required capabilities; exported types, components, operations, conversions, and
  diagnostics; supported Numeric/Runtime profiles; complete Operation specifications/bodies; and
  one exact conformance-vector child descriptor. That child binds the owning coordinate and closes
  the package's normative vectors. Both JSON members live in one package-specific directory and are
  jointly required; splitting them into peer registries or independently publishable artifacts is
  prohibited. Package contents cannot exist in an evaluator registry without appearing under this
  exact release identity.
  Duplicate `(package id, version)` entries with different content are refused within one admitted
  bundle. Across different LDB identities, `(package id, version)` is only a logical coordinate:
  package-release content identity plus the owning LDB identity determines the exact release.
  Two bundles that bind that coordinate to different content are distinct, non-interchangeable
  language worlds; neither claims global historical uniqueness, and no release-index or
  transparency service is part of Standard Schema 2.0.
  Under bADR-0023, each release manifest is a root-declared content-addressed child of one sealed
  LDB graph and binds exactly one package-owned conformance-vector child. The root descriptor binds
  the logical coordinate, manifest identity, and manifest byte size; the manifest binds the vector
  child's kind, identity, and byte size. A loader cannot discover packages or vector children by
  scanning ambient files, and a post-admission flat index is a derived non-authority.

- **Dependency resolution is deterministic and single-version per package id.** A Resolved Model
  binds one exact version for every package identity. Each package-release dependency names an
  exact `{id, version}` coordinate; unresolved coordinates refuse rather than floating to another
  release. Incompatible majors coexist only under
  distinct namespaces or through an explicit adapter package; the resolver never selects two
  ambiguous versions of one id. The generated Package Lock records the exact graph, capabilities,
  and resolver contract. Empty, conflicting, or cyclic invalid solutions are `resolution` refusals
  with the bounded conflict set.

- **Package Lock and Capability manifest close the complete selected graph, not a shallow selected-
  name list or the whole bundle inventory.** The lock records every selected transitive dependency
  edge and constraint, exact selected package-release content identity and
  operation version, required/optional capability branch, provider selection, exported nominal type,
  explicit Conversion operation, supported Numeric/Runtime profile definition, and normative
  resolution-algorithm/profile identity needed by RIR. The generated Capability manifest is a
  deterministic projection of the exact Package Lock and RIR, including every selected package,
  operation, type, conversion, Numeric/Runtime profile definition, capability provider, and semantic
  provenance; it is never independently authored or completed from a broader evaluator registry.
  Missing closure, multiple providers without a declared deterministic choice, incompatible type or
  conversion graphs, or an operation/profile mismatch is a `resolution` refusal. Persisting skeleton
  artifacts with package names does not establish resolution conformance. Adding an unselected
  package leaves Lock bytes unchanged only when it creates no candidate/capability ambiguity and
  every selected closure member is identical; the exact whole LDB still rebinds the Resolved Model
  under bADR-0013.

- **Runtime projection is a declared join over the selected graph.** Each seed and edge states
  independently whether a match must remain inside one package (`same_package`) or may resolve a
  shared definition supplied by the selected closure. This prevents both hard-coded package
  exceptions and accidental cross-package capture. A selected package may legitimately have no
  semantic-closure entry for one requested collection; that absence contributes no row. Multiple
  matching entries or definitions remain an ambiguity and refuse rather than relying on package or
  host iteration order.

- **Resolver implementation provenance is separate.** Package Lock contains the normative
  resolution algorithm/profile identity and semantic result only. A separately identified
  Resolution receipt binds the resolver tool/build, exact inputs, resulting lock, diagnostics, and
  publication facts. Different conforming resolver implementations must therefore emit
  byte-identical canonical locks for the same inputs while retaining distinct provenance receipts.

- **Optional dependencies are explicit capability branches, not ambient behavior.** Source may use
  an optional package only inside a construct that declares the corresponding capability
  requirement. Resolution either binds that capability and makes the chosen branch explicit in RIR
  or refuses the construct. Absence cannot silently select evaluator-specific fallback semantics.

- **Unknown language elements fail closed.** An unknown package, capability, type, field,
  operation, conversion, diagnostic, or attribute is a typed refusal at `static` or `resolution`
  according to whether name lookup or version/capability binding failed. No wire field is preserved
  as an opaque extension for a later evaluator to reinterpret.

- **Operation specifications close the extension's semantic surface.** Every operation declares a
  complete named formal-port signature and result, unit/kind rules, purity, declared refusals,
  deterministic resource
  bounds, permitted Numeric profiles, and runtime effects: state reads/writes, emitted signals,
  scheduled/canceled events, and Named random streams. Every nested invocation has one stable call
  site and binds the callee's exact formal-port set once to caller ports, lexical locals, literals,
  or another Kernel-admitted expression. Reducible domain semantics and diagnostic codes belong to
  the Language Definition Bundle; an irreducible primitive follows the Schema-major Kernel
  Specification amendment and conformance path in bADR-0022. Host evaluator code is a conforming
  implementation only.

- **Formula slots make game-owned numeric policy explicit.** An Operation may declare zero or more
  named Formula slots, each with one closed typed parameter/result contract and one declared
  evaluation context, permitted refusal set, and deterministic resource-charge budget. A selected
  Operation requires its Model Source to bind exactly one compatible named Formula to every declared
  slot. LDB rules derive the complete reachable Formula/pure-Operation call graph, refusal closure,
  charge bound, and termination measure for that binding; the closure must be a subset of the
  slot's permitted refusals and budget. Missing or duplicate bindings, incompatible signatures,
  widened refusals, resource overflow, mixed-graph cycles, and bindings to effectful or unreachable
  declarations refuse before HIR. An Operation, package, template, compiler, or evaluator cannot
  supply an optional fallback or host default. Template defaults are ordinary Formula declarations
  and bindings in the editable starter Model Source.

- **Operation closure is checked before RIR and revalidated before execution.** Closed Kernel-node
  shapes reject even unknown fields on known nodes. Static judgments derive parameter use,
  reachable result tags/payload types, state reads/writes, signal/event/cancel/random effects, and
  resource counts, plus every Formula/pure-Operation transitive refusal, charge, and termination
  edge, then require exact agreement with the selected release's declared signature,
  kind/unit/Numeric rules, purity, effects, refusals, and bounds. Runtime admission compares the
  complete RIR Operation and Formula-closure projection to that exact selected release and rejects
  an LDB-present but Lock-unselected operation. Reidentifying a partial or inconsistent artifact
  cannot make it executable.

- **Model invocation closes the reusable Operation interface without duplicating it.** Model Source
  owns named, typed symbols and value policies plus entrypoints that explicitly bind those symbols
  to exact Operation formal ports and bind or discard results. RIR resolves each actual operand and
  call site to canonical identities and derives the Scenario Input Contract from reachable symbols.
  Experiment scenarios select an entrypoint and assign that contract exactly once per member; they
  cannot select a raw Operation or repeat its port declarations. Equal source names are never a
  binding rule. Read-only aliasing is explicit; writable aliasing is refused unless the Operation
  contract explicitly admits it.

- **Expected gameplay branches use closed discriminated outcomes.** An operation whose declared
  game semantics can complete as `reserved`, `insufficient`, `immune`, `interrupted`, or another
  expected branch returns a nominal Enum or tagged Record union whose discriminator, payload, and
  version are closed by its Operation specification. Static analysis requires exhaustive handling
  before a dependent operation such as resource commit can proceed. A gameplay outcome is neither a
  Typed refusal nor a Verdict: refusal means the declared semantics could not be executed, while a
  Verdict is a completed judgment about evidence. Adding/removing a variant is governed by package
  compatibility rules, and host code cannot invent an unlisted status string.

- **Signal types belong to packages; subscription topology belongs to authored models.** A Domain
  package exports a nominal signal payload and the effects/capabilities a subscriber may declare.
  A Model Source Package declares game-specific subscriptions using resolved handler identities.
  Static resolution rejects incompatible, cyclic-unbounded, or undeclared effects and lowers the
  closed subscriber table into RIR. An evaluator registry cannot add subscribers.

- **Conversions are explicit operations.** Cross-kind, cross-unit, and representation conversions
  exist only as versioned Conversion operations with declared legality, exact/lossy status,
  rounding, domain mapping, and refusal behavior. Source requests the conversion; Typed HIR records
  the selected operation explicitly. Contextual literal typing selects exactly one independently
  exported, package-owned LDB Literal Typing Profile against the consuming formal's complete value
  contract and retains that resolved context in RIR identity. The profile owner must own the exact
  Type release, its value references must close, and overlapping profiles for one match contract
  are invalid; it is not a host-default integer type, a Symbol-assignment concern, or an implicit
  coercion.

- **Package compatibility follows strict semantic versioning.** Minor versions may add optional
  types, operations, capabilities, or fields whose absence preserves every existing program's
  meaning. Changing/removing existing structure, diagnostics, operation behavior, defaults,
  effects, or numeric results requires a major version. Patch versions may correct prose,
  projection, or implementation defects only when observable semantics and valid-program sets are
  unchanged. Exact versions remain locked for replay even when a change is compatible.

- **Cross-package identity is nominal and exact.** Type and operation identity includes package
  namespace, compatible major line, and exported symbol; Package Lock supplies the exact version.
  Structural similarity does not make records or Quantity kinds interchangeable. Adapter packages
  and Conversion operations make interoperability reviewable.

- **Future genres are an extension invariant, not a request for new core semantics.** A candidate
  genre may add Model Source declarations, complete Domain package releases, template releases,
  Experiment Specifications, coverage rows, and vectors. It may not require a new Kernel primitive,
  core constructor, runtime phase, host dispatch branch, ambient callback, or evaluator-owned
  fallback. Package operations may encode domain protocols and state machines over the existing
  closed types, atomic Events, explicit inputs, and bounded resources. If a bounded deterministic
  mechanic cannot be represented that way, the Standard Schema 2.0 architecture—not the candidate
  template—has failed its extensibility requirement and the relevant design gate must reopen. This
  invariant does not claim that every genre template ships in 2.0; it requires every later genre
  addition to preserve the same core semantics.

- **Core Extension Invariance produces a public proof artifact.** An independently validated
  **Extension Invariance Receipt** binds the identical pre/post Kernel identity, core-constructor and
  runtime-phase projections, compiler/evaluator build identities, base and extended LDB identities,
  exact added package releases, Model/Experiment/vector identities, mutually produced RIR/results,
  and a complete authority-token rename mapping. A Kernel/LDB-owned traversal law derives a closed
  **Non-Kernel Authority Token Inventory** from the complete reachable witness artifact graph. It
  includes every package/capability, type/kind/unit/role, Operation/parameter/result variant,
  Diagnostic, Signal/Event, effect/resource, profile/policy, Experiment/Metric/selector, vector, and
  other non-Kernel identity that can affect resolution, dispatch, result decoding, or trace. An
  independently validated bijection must rename every inventory member consistently; omitted,
  duplicate, reserved-Kernel, or extra mappings refuse.

  The witness graph and its complete rename inventory are derived after the implementation builds
  are fixed; the same unmodified builds must admit,
  lower, mutually consume, and execute both the original and consistently renamed forms through
  generic Kernel/LDB paths. Comparison inverse-maps renamed semantic observations only for the
  declared equivalence judgment while preserving the distinct exact artifact identities. Rebuilding
  either implementation, declaring any inventory member as a host capability, omitting a rename, or
  changing a core projection makes the receipt ineligible. The
  receipt is conformance evidence, not a new semantic authority; its exact inputs and independent
  verifier are checked through the ordinary claim-closure path.

- **Every package ships executable conformance evidence.** Positive, negative, boundary,
  compatibility, deterministic replay, and declared-effect vectors are required before a package
  enters the Language Definition Bundle. The Package Release manifest binds exactly one
  package-owned conformance-vector set, including a closed empty set when no vectors are currently
  required. The resolver and reference evaluator derive vectors from admitted vector children, not
  from inline manifest fields or a parallel test registry.

- **This decision supersedes the conflicting 2.x portions of bADR-0001, bADR-0002, and
  bADR-0003.** It replaces the fixed root/reserved-section extension model, attribute-specific core
  facets, float-only parameter surface, and untyped reference assumptions for 2.x. It retains the
  principles of closed input, orthogonal composition, explicit named tuning controls, closed
  operations, bounded formulas, and hard refusal. Their 1.x contracts remain normative for 1.x and
  migration. Effect-domain semantics in bADR-0006 require a separate 2.x package decision.

## Considered options

- **Closed type constructors plus constrained packages** (chosen) — permits new game concepts
  without allowing extensions to fork grammar, typing, or runtime semantics.
- **Add every RPG concept to the root schema** (rejected) — creates a non-orthogonal taxonomy that
  cannot represent new genres without core changes.
- **Open attribute/property maps** (rejected) — make unknown content silently valid and move typing
  into individual evaluators.
- **Host-language plugins** (rejected) — bypass deterministic semantics, capability negotiation,
  resource bounds, and cross-implementation conformance.
- **Structural/duck typing across packages** (rejected) — permits accidental compatibility when two
  records or numeric kinds happen to share a shape.
- **Multiple versions of one package id in one model** (rejected) — makes type and operation
  identity ambiguous; explicit namespaces/adapters expose the compatibility boundary.
- **Implicit numeric and unit coercions** (rejected) — hide loss, make overload resolution unstable,
  and prevent HIR/RIR from being semantically explicit.

## Consequences

- The Language Definition Bundle owns each core constructor, type relation, literal rule, role
  constraint, manifest field, resolver algorithm, compatibility rule, and conversion law through
  bADR-0022's structured Language rules.
- Package authors gain an additive route for new attributes, resources, actions, economies, and
  game-specific components without root-schema changes.
- The RIR serializer and Capability manifest expose exact package/type/operation identities; every
  evidence artifact binds them through the Resolved Model hash.
- RPG/Roguelike completeness must now be demonstrated as package operations and golden scenarios,
  not as a long list of special root fields.
- bADR-0017 establishes the coverage matrix and splits effect, combat, build, progression, economy,
  generation, and reset behavior across orthogonal packages.

## Validation

- Resolve positive, missing, conflicting, cyclic, ambiguous-provider, incompatible-profile,
  type/conversion-closure, and operation-version fixtures; canonical Package Lock and Capability
  manifest bytes must agree across independent resolvers or produce the same bounded refusal set.
- Assert two resolver tool builds produce one canonical Package Lock identity and distinct
  Resolution receipts; changing only resolver implementation provenance must not change RIR or
  Resolved Model identity.
- Mutate one transitive constraint, capability provider, type, conversion, or operation version and
  assert the lock/manifest/RIR identity changes or resolution refuses; no hidden evaluator registry
  may keep the old build working.
- Require only a package whose declared dependency supplies a capability and assert provider
  selection considers the complete selected transitive closure, not only Model Source root
  requirements. Adding the dependency redundantly as a root must not be necessary to obtain the
  same provider binding.
- Exercise runtime-projection seeds and edges with both `same_package` settings, a selected package
  that contributes no entry for one collection, and duplicate matching definitions. Independent
  lowerers must agree on the projection or the same ambiguity refusal.
- Add an unused package without changing the selected closure or introducing resolution ambiguity;
  assert byte-identical Package Lock and RIR semantic payload but changed whole-LDB and Resolved
  Model identities. An LDB-present operation absent from the Lock must refuse at runtime admission.
- Mutate every nested Operation surface: known-node extra fields, signature/parameters, result
  variants and payloads, kind/unit/Numeric rules, purity, effects, and resource-bound shape/type/
  value. Each malformed release must produce a typed refusal before RIR rather than a host
  exception, and a consistently reidentified RIR projection must still fail runtime admission.
- Exercise missing, extra, duplicate, unknown, aliased, and type-incompatible formal bindings at
  nested Operation call sites and Model entrypoints. Exercise Scenario Input under-supply,
  over-supply, duplicate assignment, raw-Operation selection, and symbol renaming. Both independent
  consumers must derive the same call graph and identities or the same bounded refusal before
  execution.
- Mutate a selected Operation's Formula-slot name, signature, evaluation context, or cardinality;
  omit or duplicate one Model Source binding; bind an incompatible, effectful, cyclic, or
  unreachable Formula; widen the transitive refusal set; exceed a declared resource-charge bound;
  create a Formula → pure Operation → Formula cycle; and attempt a package/evaluator fallback.
  Independent compilers must emit the same pre-HIR refusal, while a valid exact-one binding and its
  complete closure must be explicit in HIR and RIR. Reidentify a widened or truncated RIR closure
  and require Runtime admission refusal.
- Exercise every admitted constructor, including nested Record/List/Map/Quantity/Distribution
  shapes, at Kernel-law and Operation boundaries. Both must accept or refuse identically; an
  unknown, partially checked, or host-native value cannot cross either boundary.
- Exercise every declared gameplay-outcome variant and reject unknown discriminators, missing
  payloads, and non-exhaustive dependent branches before execution. Resource insufficiency,
  immunity, and legal interruption remain typed outcomes rather than Runtime refusals.
- Add an ordinary Quantity-typed attribute by changing only the Model Source declaration; the LDB,
  package manifests, core constructors, compiler, and evaluator remain unchanged. Separately add one
  reusable mechanic/operation through one versioned package/LDB authority edit plus its normative
  vectors; every other projection is generated or reverse-conformance-checked, and unrelated
  compiler/runtime dispatch remains unchanged.
- Admit a non-RPG priority/reaction-window package suite that represents proposal, response, pass,
  nested response, cancellation/replacement, and final resolution as bounded Domain state and
  ordinary Events. The suite may add packages and vectors but must leave the Kernel, constructor
  set, three runtime phases, compiler dispatch, and evaluator dispatch unchanged. Any required core
  edit fails the genre-extension invariant rather than being waived as a special case.
- Freeze two independent compiler/evaluator build identities, then derive the complete reachable
  Non-Kernel Authority Token Inventory and consistently rename every member after those builds are
  fixed. Require both
  builds to admit, lower, mutually consume, and execute the renamed suite without rebuild or host
  capability changes, and publish one Extension Invariance Receipt binding identical core
  projections plus the inventory and complete bijection. Mutate or omit each token class—including
  Capability, Diagnostic, profile/policy, result variant, Signal, and Event—and require refusal. A
  missing token, private helper, or changed build identity cannot close the witness.
- Admit two LDBs that bind the same logical `(package id, version)` coordinate to different release
  content. Assert that each resolves only inside its own exact LDB, produces distinct package-release
  and Resolved Model identities, and cannot reuse the other bundle's Lock, RIR projection, Runtime
  profile, Experiment binding, or Evidence. Within one LDB, the duplicate remains a refusal.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0001 — Standard Schema 1.x document and reserved sections.
- bADR-0002 — Standard Schema 1.x orthogonal attribute facets.
- bADR-0003 — Standard Schema 1.x formula and parameter representation.
- bADR-0012 — language and artifact authority domains.
- bADR-0013 — compiler stages and RIR semantic boundary.
- bADR-0014 — deterministic atomic event runtime.
- bADR-0022 — Kernel Specification and machine-readable language rules.
