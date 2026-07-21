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
  `Record`, `Vector`, `List`, `Set`, `Map`, `EntityRef`, `Quantity`, and `Distribution`.
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
  create `CurrentNumber`, `CostNumber`, or other redundant type constructors.

- **`attribute` is not a 2.x language primitive.** A domain package may call a Quantity-typed symbol
  or component field an attribute in its own vocabulary, but the compiler sees the same typed
  declaration machinery used by resources, cooldowns, currencies, positions, counters, and rates.
  New attributes therefore require data declarations, not changes to the root schema or evaluator.

- **Entities compose through typed records/components and EntityRef.** A package defines nominal
  component contracts using core constructors. Entity references state the required nominal entity
  or capability contract; they are not untyped ids. A package cannot reopen another package's
  record or attach undeclared fields. Additional behavior composes as a separate component and
  explicit operations over imported contracts.

- **Every Domain package release is one complete, immutable artifact in the Language Definition
  Bundle.** Its content identity covers the namespaced package id; semantic version; required and
  optional dependency ranges;
  provided and required capabilities; exported types, components, operations, conversions, and
  diagnostics; supported Numeric/Runtime profiles; complete Operation specifications/bodies; and
  normative vectors. Splitting those facts across peer registries is prohibited. Package contents
  cannot exist in an evaluator registry without appearing under this exact release identity.
  Duplicate `(package id, version)` entries with different content are refused within one admitted
  bundle. Historical uniqueness across independently published bundles needs an explicit release-
  index/transparency authority; a semantic-version string alone does not prove it.

- **Dependency resolution is deterministic and single-version per package id.** A Resolved Model
  binds one exact version for every package identity. Incompatible majors coexist only under
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
  complete type signature, unit/kind rules, purity, deterministic resource bounds, permitted
  Numeric profiles, and runtime effects: state reads/writes, emitted signals, scheduled/canceled
  events, and Named random streams. Reducible domain semantics and diagnostic codes belong to the
  Language Definition Bundle; an irreducible primitive follows the Schema-major Kernel Specification
  amendment and conformance path in bADR-0022. Host evaluator code is a conforming implementation
  only.

- **Operation closure is checked before RIR and revalidated before execution.** Closed Kernel-node
  shapes reject even unknown fields on known nodes. Static judgments derive parameter use,
  reachable result tags/payload types, state reads/writes, signal/event/cancel/random effects, and
  resource counts, then require exact agreement with the selected release's declared signature,
  kind/unit/Numeric rules, purity, effects, and bounds. Runtime admission compares the complete RIR
  Operation projection to that exact selected release and rejects an LDB-present but Lock-unselected
  operation. Reidentifying a partial or inconsistent artifact cannot make it executable.

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
  the selected operation explicitly. Contextual literal typing may choose a literal's initial type,
  but no implicit coercion remains in HIR or RIR.

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

- **Every package ships executable conformance evidence.** Positive, negative, boundary,
  compatibility, deterministic replay, and declared-effect vectors are required before a package
  enters the Language Definition Bundle. The resolver and reference evaluator discover vectors
  through the manifest, not a parallel test registry.

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
- Add an unused package without changing the selected closure or introducing resolution ambiguity;
  assert byte-identical Package Lock and RIR semantic payload but changed whole-LDB and Resolved
  Model identities. An LDB-present operation absent from the Lock must refuse at runtime admission.
- Mutate every nested Operation surface: known-node extra fields, signature/parameters, result
  variants and payloads, kind/unit/Numeric rules, purity, effects, and resource-bound shape/type/
  value. Each malformed release must produce a typed refusal before RIR rather than a host
  exception, and a consistently reidentified RIR projection must still fail runtime admission.
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

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0001 — Standard Schema 1.x document and reserved sections.
- bADR-0002 — Standard Schema 1.x orthogonal attribute facets.
- bADR-0003 — Standard Schema 1.x formula and parameter representation.
- bADR-0012 — language and artifact authority domains.
- bADR-0013 — compiler stages and RIR semantic boundary.
- bADR-0014 — deterministic atomic event runtime.
- bADR-0022 — Kernel Specification and machine-readable language rules.
