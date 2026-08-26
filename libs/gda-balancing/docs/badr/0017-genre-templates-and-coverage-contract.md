---
status: accepted
---

# Prove RPG and Roguelike support through template releases and executable coverage

The closed package system in bADR-0016 makes extension possible, but a list of package names does
not prove that Standard Schema 2.x can represent a production RPG or Roguelike. The rejected RPG
template PR attempted to encode one genre baseline directly in the 1.x shape; review found missing
target selection, dynamic entities, damage stages, immunity, interruption, build conflicts, loot
constraints, and run/meta reset semantics. Adding fields would neither close those gaps nor show
that independently designed packages compose into one executable model.

A template also cannot become a fourth authority domain. Its model starter, experiments, and
support evidence have different owners under bADR-0012. PRD #534 therefore needs a template
distribution contract and a falsifiable definition of genre completeness.

> **Amendment (2026-08-12, #640):** The #585 Roguelike product-feedback slice falsified the
> provisional claim that the current Kernel could express every required bounded selection path.
> Under bADR-0022's provisional-baseline rule, #640 admits three generic primitives: `is-empty`,
> `require`, and `guard-block`. It replaces the exact provisional Kernel identity. All later Core
> Extension Invariance evidence must bind the replacement identity; evidence for the superseded
> baseline does not carry forward.

> **Amendment (2026-08-26, #546):** The `RPG-STAT-01` tracer found one more irreducible gap in the
> unreleased Schema 2.0 baseline: exact integer percentage rules cannot round down without integer
> division. Under bADR-0022's provisional-baseline rule, the Kernel adds only an exact-int64
> `integer-floor-divide` primitive. `core.quantity@2.2.0` exposes its typed wrapper and the other
> existing primitive wrappers needed by the tracer. This replacement happens before the 2.0
> baseline is fixed. Later Core Extension Invariance evidence binds the replacement Kernel
> identity; it cannot treat the superseded identity as evidence for the completed baseline.
>
> The Golden Model Source requires `core.quantity@2.2.0`, `game.progression@1.0.0`,
> `game.build@1.1.0`, `game.effect@1.1.0`, and `game.combat@2.2.0`. Their exact selected dependency
> edges are:
>
> - `core.quantity@2.2.0` → `standard.compiler@1.1.0`;
> - `game.progression@1.0.0` → `core.quantity@2.2.0`;
> - `game.check@1.1.0` → `core.quantity@2.2.0`, `standard.runtime@1.1.0`;
> - `game.resource@1.1.0` → `core.quantity@2.2.0`, `standard.runtime@1.1.0`;
> - `game.generation@1.1.0` → `core.quantity@2.2.0`, `standard.runtime@1.1.0`,
>   `standard.schema@2.4.0`;
> - `game.build@1.1.0` → `core.quantity@2.2.0`, `game.generation@1.1.0`,
>   `standard.runtime@1.1.0`, `standard.schema@2.4.0`;
> - `game.effect@1.1.0` → `core.quantity@2.2.0`, `standard.runtime@1.1.0`; and
> - `game.combat@2.2.0` → `core.quantity@2.2.0`, `game.check@1.1.0`,
>   `game.resource@1.1.0`, `standard.runtime@1.1.0`.
>
> The new check, resource, and generation releases preserve their earlier exports and behavior;
> their manifest change is limited to selecting `core.quantity@2.2.0`. The new combat release also
> preserves its earlier Operations and behavior. All earlier releases remain available unchanged.
> Package Lock generation must prove this complete single-version graph before RIR. Changed
> manifests, dependency vectors, Package Lock/RIR identities, examples, receipts, and production
> and independent conformance evidence are rebuilt and revalidated together.

> **Amendment (2026-08-18, #708):** `game.combat` owns explicit defeat transition policy and
> combat-action eligibility. `game.combat.eligible-cast-v1` checks the authored actor-health and
> non-negative defeat-threshold ports before it delegates to the ordinary cast. A negative
> threshold produces a typed refusal before `actor_resource` spending, RNG, or gameplay state
> mutation; execution still records three `event-steps` units. An ineligible actor completes with
> `actor-ineligible` without `actor_resource` spending, RNG, or gameplay state change; execution
> still records five `event-steps` units. An eligible cast applies no more damage than the target's
> current health. If transaction-local post-cast target health is at or below the authored
> threshold, the wrapper completes with `target-defeated`; that outcome's commit policy then
> commits the resulting Event state. Otherwise, it completes with `cast-resolved`. The raw
> `game.combat.cast-v1` Operation remains available and continues to carry no implicit defeat or
> eligibility policy. Runtime evaluates these authored Operations and outcomes; it never infers
> combat status from a health-like value.
> This slice defines actor eligibility, not target eligibility, and it does not distinguish a new
> threshold crossing from a target condition that was already satisfied. A caller stops subsequent
> duel actions after it receives the explicit `target-defeated` outcome.

> **Amendment (2026-08-13, #640):** `game.generation` owns one ordered eligible `RewardOption`
> pool. Each option pairs its candidate and selection data. Its primary `RarityPolicyKind` remains
> a selection-policy axis. The
> independent `no_reward_on_empty: List<RewardSelection, max=1>` field declares the exhaustion
> fallback: an empty list declares none, and one value declares the exact no-reward selection.
> Empty selection without that value raises `selection-exhausted`. Empty selection with it validates
> the no-reward disposition, commits the selection and its score to the declared state ports,
> preserves policy state and draw count, consumes no RNG, completes as the `no-reward`
> `gameplay-alternative`, and produces no Operation result. Contradictory option or fallback data is
> a typed configuration refusal. The former `relaxed-pool` claim is removed until a package declares
> an actual excluded pool, eligibility predicate, and relaxation order. A subsequent `game.build`
> Event observes the no-reward disposition, completes with its own rollback
> `gameplay-alternative`, produces no Operation result, and does not change build state or consume
> RNG.
> On the ordinary build path, `game.build` validates the selected reward, current state, next state,
> decision, and score before it commits. Contradictory authored plan data is a typed configuration
> refusal. A valid plan with the declared `conflict` constraint remains the `build-conflict`
> gameplay outcome.

> One illustrative, non-normative lowering uses `is-empty` and a top-level `guard-block` to complete
> the empty selection and no-reward build paths before the outer authored sequence can draw, look
> up a plan, or write ordinary success state. This sketch demonstrates the observable contract
> above; it does not define either Operation body. Issue #640 owns the exact implementation target
> until the accepted Package Release manifests and their bound vectors become machine authority.

## Decision

- **A Genre template is a versioned template release, not a Standard Schema instance or runtime
  profile.** A release contains:
  - an instantiable starter Model Source Package with default declarations and formulas;
  - companion pre-build Experiment templates with scenarios, metrics, and targets;
  - a Genre coverage matrix and its Golden scenarios/negative vectors;
  - a manifest binding template version, compatible Language Definition Bundle/package ranges, and
    the content identities of those members.
  The release is a distribution container, not a semantic authority: each member retains its
  bADR-0012 authority domain.

- **Pre-build Experiment intent and executable Experiment binding are distinct artifact kinds.**
  A template release carries `experiment-template`: editable scenario/Metric/target intent that
  cannot yet name a build receipt, Resolved Model, Package Lock, or RIR. After build, authoring
  produces an exact `experiment-specification` binding those identities. Template admission,
  runtime admission, and public command schemas reject either kind in the other's role; sharing a
  logical display name does not make their identities or lifecycle interchangeable.

- **Instantiation creates a new authored model identity.** It copies/materializes the starter under
  a new package identity and records template id/version/content provenance. The game owns all
  subsequent edits. Installing a later template cannot mutate, rebase, or reinterpret an existing
  Model Source Package. Initial 2.0 defines no template-upgrade converter: adopt later content only
  by re-instantiating or making explicit authored changes. A future 2.x upgrade decision may add a
  separately versioned migration/report contract without retroactively changing existing models.

- **Templates contain no evaluator code and define no alternate language.** Defaults, formulas,
  package requirements, and example experiments are Standard Schema source. Genre-specific
  behavior exists only through Language Definition Bundle operations and Domain packages. The term
  `profile` remains reserved away from Genre template because Runtime/Numeric profile definitions have
  different authority and compatibility semantics.

- **Template Formula defaults are ordinary starter-source bindings.** When a selected Operation
  declares an exactly-one Formula slot under bADR-0022, an instantiable starter Model Source must
  provide one compatible Formula declaration and binding for that slot. Instantiation materializes
  both into the game-owned Model Source; the package, template machinery, compiler, and evaluator
  provide no fallback if a required binding is absent or invalid.

- **Template-release admission is Kernel-defined and LDB-selected.** The Kernel owns the closed
  Schema-major artifact-graph primitive specification: typed arguments and result effects,
  evaluation law and order, failure behavior, canonical comparison/identity consequences, and
  resource-charge events. Stable operations bind LDB-facing names to those primitives; the LDB owns
  one versioned admission program. That program maps release-member kinds to role collections with
  explicit cardinality and
  required-operation obligations, derives named graph facts through declared selectors/bindings,
  and runs under a bounded per-release step budget. A consumer must admit the starter through the
  ordinary Model Source path, close authority/source/package/default/Experiment-template/coverage
  bindings, and execute every declared negative and boundary vector. Multiple Experiment templates,
  Golden scenarios, and vectors remain ordered members rather than host-selected singletons.
  Metric identifiers are unique within their owning Experiment template, not globally across
  independent templates. The Kernel owns only a generic role identifier/cardinality contract;
  concrete role names and member kinds stay in the LDB, allowing a genre to add them without a core
  change. JSON Schema validation, a named host primitive without its complete machine law, or
  host-selected companion checks alone cannot admit a release. The admission program does not make
  the template a language authority: it defines how the existing authorities judge the
  distribution container.

- **The initial game-domain package boundaries are:**

  | Package | Owns | Does not own |
  |---|---|---|
  | `game.entity` | entity identity, components, defeat/revival state storage, faction/team/relationship, dynamic entity sets | combat resolution, defeat/revival transition policy, targeting, or action lifecycle |
  | `game.resource` | typed current/capacity storage including health/shield-like quantities, cost, regeneration, reservation and transfer | action timing, damage/healing stages, or lifecycle transition policy |
  | `game.query` | typed target filters, ordering, cardinality, tie-break and empty behavior | target-side effects |
  | `game.check` | threshold/opposed checks, hit resolution, dice/pools, advantage and success degree | damage application |
  | `game.action` | closed immutable Action-plan schema, admission and identity; requirements, resource commitment, pending proposal identity, wind-up/channel, cooldown, completion, interruption, execution, cancellation and replacement | target enumeration, candidate/plan selection, Intent projection, response-window priority, or damage math |
  | `game.effect` | application and capture-source/timing policy, buildup/activation, effect contribution sources and Formula-slot contracts, transitions, schedule, stacking/reapply/remove and immunity contracts | action lifecycle, final derived-stat composition, or combat pipeline |
  | `game.combat` | ordered typed damage-component and healing stages, criticals, per-kind mitigation/resistance, shield resolution, aggregation/rounding, defeat/revival transition policy, and the Formula-slot signature/context/refusal/budget plus Operation integration for the committed combat-damage path | entity/resource state storage, generic effect lifetime or inventory |
  | `game.build` | equipment/skill/perk selection and atomic replacement, prerequisites, exclusivity, slots, synergy declarations, and build contribution sources and Formula-slot contracts | item ownership, reward sampling, final derived-stat composition, or old-action/effect cancellation semantics |
  | `game.progression` | XP, levels, growth, unlocks, progression gates, and progression contribution sources and Formula-slot contracts | final derived-stat composition, currency exchange, or run reset |
  | `game.economy` | currency, inventory, sources/sinks, transfer, exchange and pricing | stochastic reward selection |
  | `game.collection` | typed ordered instance collections, stable order, zone membership, legal moves, shuffle handoff and no-duplicate/no-loss conservation | turn windows, action lifecycle, build admission, economic ledgers, or Run/Meta retention |
  | `game.generation` | seeded weighted/constrained pools, closed fixed-weight/pity/guarantee rarity policies, separately declared exhaustion fallbacks, explicit selection exhaustion, and typed reward disposition results | destination collection/economy/effect mutation or meta retention |
  | `game.encounter` | party/enemy composition, spawn/wave schedule, objectives and terminal conditions | entity internals, action-plan choice/projection, or scheduler law |
  | `game.decision` | optional bounded candidate evaluation, selection of one admitted immutable Action plan, and policy-governed observable Intent projection | Action-plan schema/admission/identity, encounter composition, action execution, or evaluator callbacks |
  | `game.run` | Run/Meta scope declarations, start/end/reset and explicit retained transfers | progression formulas themselves |
  | `game.turn` | optional rounds, initiative, action economy, reaction/priority windows, responder order, pass/close policy and bounded nesting | action-plan semantics or core logical-time scheduler |
  | `game.spatial` | optional positions, ranges, shapes, movement and spatial queries | generic target-query semantics |

  bADR-0022 owns generic Formula-language package responsibility. This genre map adds only the
  mechanic assignment: `game.combat` owns the committed combat-damage Formula slot and Operation
  integration, while `game.resource` and `game.check` remain separate dependencies and do not
  become a reconstructed RPG umbrella.

  The `RPG-STAT-01` slice follows the same boundary. Progression, build, and effect packages each
  own one pure contribution Operation and its Formula-slot contract. Model Source owns the
  concrete bound Formulas and the named Formula graph that combines those contributions, applies
  rounding and the final cap, and exposes read-only derived Symbols. No package owns a dynamic
  contribution registry or the game's final stat policy. `game.combat` consumes the final derived
  Quantity without taking ownership of its composition.

  Package names are stable conceptual namespaces; final operation/type inventories live only in the
  manifests of complete sealed Package Releases, and normative vectors live in their bound
  package-owned conformance-vector children (bADR-0023). A broad `game.rpg` package is not an alias
  for this map: integrated examples compose the mechanic packages without transferring their state,
  transition, or observation ownership to a genre umbrella.

- **Target selection is its own typed contract.** A Target query operates over a dynamic entity set
  and declares filters, stable ordering, cardinality, tie-breaking, empty-result behavior, and any
  spatial capability required. Action, combat, and effect packages consume the resolved targets;
  none may hide target selection inside evaluator code. Executable coverage distinguishes a legal
  empty typed outcome from a source that omitted its empty policy, and includes zero/one/many
  cardinalities, equal-key ties, stable-order perturbations, and missing/incompatible spatial
  capability vectors.

- **Effects decompose instead of growing a universal object.** `game.effect` composes distinct
  contracts for application requirements; capture source (`base`/authored or `resolved`/derived)
  independently of capture timing (snapshot or declared live read); buildup accumulation and
  threshold activation; continuous contributions; state transitions; scheduling; stacking
  identity/reducer/cap; reapplication lifetime; typed removal/expiry/dispel causes; and immunity.
  Threshold activation creates one effect instance with its bounded schedule; removal cancels the
  exact outstanding events owned by that instance. Action owns interruption; combat owns
  damage/healing stages; resource owns current/capacity transfer. Cross-package operations declare
  their reads, writes, events, closed gameplay outcomes, and possible typed refusals under
  bADR-0016. An unqualified value field cannot choose either capture axis in host code.

- **The initial Effect lifecycle has one observable interaction order.** Runtime Events resolve
  sequentially by bADR-0014's total order; a later Event observes the earlier Event's commit, and an
  active Event is never interrupted “mid-transition.” Inside one Event, the primary Operation and
  its statically resolved Signal subscribers may emit typed `EffectRequest` facts into the declared
  transaction reducer buffer. Each request carries a canonical **Effect lifecycle key**:
  `(effect-definition identity, resolved subject/target identity, stack-partition key)`. The selected
  effect definition owns a closed, pre-instance partition projection over typed request inputs—for
  example source identity, slot, or channel—so new application and buildup requests derive the same
  key before an instance exists. An existing-instance request also carries its instance identity,
  whose recorded lifecycle key must match. A multi-target operation expands into one request per
  resolved target using canonical target order; no request spans keys.

  After all handlers finish, `game.effect.resolve-requests@1` closes one Event-wide canonical
  **Effect request envelope**, sorts it by lifecycle key and origin key, partitions it into exactly
  one `EffectRequestSet` per lifecycle key, and reduces those sets in lifecycle-key order against
  the same pre-event Snapshot before final writes/schedules commit. A request scheduled as a child
  Event is not in that envelope and resolves later against the post-commit Snapshot; no host
  callback or late buffer append may cross this boundary. Missing/ambiguous partition input,
  instance-key mismatch, duplicate membership, or inconsistent grouping is a typed refusal. Each
  canonical request set is reduced in this order:
  1. validate instance/definition identities and declared request variants;
  2. apply typed removal/expiry/dispel requests, which dominate same-instance tick, transition,
     contribution, and reapplication requests and cancel the exact outstanding schedule;
  3. for surviving/new candidates, evaluate application requirements and immunity;
  4. accumulate buildup and perform at most one threshold activation;
  5. resolve stack identity/cap and the closed reapplication policy;
  6. capture declared values, then compute contributions and state transitions; and
  7. derive the final bounded schedule/cancellation delta for the single atomic commit.
  Every request also carries a canonical origin key derived from the emitting Operation identity,
  Resolved source-symbol identity, and declared emission ordinal or canonical bounded-iteration
  index. The selected lifecycle policy closes each stage with a total request-variant order and a
  complete multiplicity reducer. For example, coincident expiry and dispel select exactly one typed
  removal cause by the policy's declared cause order; multiple buildup requests use the declared
  Quantity reducer; and multiple reapplications fold in canonical origin-key order. Duplicate origin
  keys, an unordered request variant, or a missing reducer are static/Runtime refusals as applicable.
  Every losing/coalesced request and the winning reduction enter the trace; host arrival, map, or
  subscriber iteration order is never consulted. The Event envelope, lifecycle-key derivation and
  partition, per-set payload, origin provenance, reduction order, and boundary between same-Event
  requests and later child Events are public trace observations.
  At cap, reapplication must return one declared outcome such as unchanged, refresh, replace, or
  reduce-into-existing; it cannot silently exceed the cap. Atomic replacement is an explicit
  operation that removes and creates under its own closed outcome, never an inference from
  coincident requests. The trace records every suppressed request and precedence decision. A later
  package version may select a different complete precedence policy only by giving it a new
  operation/policy identity and vectors; host iteration order and partial policy overrides are
  forbidden.

- **Interactive reactions use explicit windows over the ordinary Event scheduler.** `game.action`
  creates a stable pending proposal/plan identity. `game.turn` owns the eligible-responder order,
  priority holder, pass state, close rule, and bounded nesting for the reaction window. Choices such
  as counter, replace, cancel, or pass arrive through declared `input` boundaries and advance the
  window through ordinary `transition` Events; only a closed window schedules final Action
  resolution. Advancing scheduler logical time for another input boundary does not advance
  package-owned turn or game-world time. A readied action is the same protocol with a declared
  trigger that opens or advances
  a window. No action package may pause an active Event for a host callback, deliver a reaction as a
  Signal, or introduce a hidden resolve-before-transition phase.

- **Ordered collections are Domain behavior, not `List` semantics or inventory.**
  `game.collection` composes core collection values into typed collections whose instance identity,
  stable order, zone membership, legal moves, named-stream shuffle handoff, and conservation law
  are observable. `game.turn` owns windows, `game.action` owns card/action lifecycle, `game.build`
  owns deck/build admission, `game.economy` owns economic inventory and ledgers, and `game.run` owns
  scope/reset. None may inherit order from a host container or duplicate this transition contract.

- **An Action plan, its Intent projection, and its execution are separate facts.**
  `game.action` owns the closed immutable plan schema, admission, identity, and exact execution. A
  declared external input may submit a plan for admission directly. When the optional `game.decision`
  capability is selected, `game.encounter` supplies the acting entity, context, and decision window;
  `game.decision` deterministically selects one admitted plan under declared bounds and projects it
  through an explicit visibility policy. `game.action` executes that exact identity in either path.
  A masked or partial Intent changes only the observable projection, never plan identity or
  execution. Evaluator-owned AI callbacks, ambient candidate order, post-admission plan mutation,
  and treating a projection as executable authority are prohibited.

- **Build replacement is not an in-place attribute edit.** `game.build` returns a closed atomic
  replacement outcome binding old/new definition identities, prerequisite disposition, retained
  selections, slot and cardinality invariants, and the required action/effect cancellation and
  activation effects. Action/effect packages own the canceled and installed behavior; the Runtime
  commits their declared cancellation, collection/build writes, and new scheduling in one Event
  transaction. A replacement cannot expose an intermediate empty or double-filled build.

- **Loot is a composition, not another monolith.** `game.generation` selects a reward under seeded
  weights, constraints, and one closed rarity-policy variant, then returns a typed Reward
  disposition. The declared destination package performs the handoff: `game.economy` for
  item/currency inventory, `game.collection` for a direct ordered-collection insertion,
  `game.effect` for an effect offering, or `game.build` for eligibility/selection as applicable.
  Generation never mutates the destination, and economy is not fabricated for a non-economic
  reward. Golden scenarios exercise both an economic transfer and a direct collection handoff so
  no package silently owns or skips the disposition.

- **Run and Meta scopes are explicit state lifecycle contracts.** Every relevant state declaration
  names its scope. A run-end transaction clears Run-scoped state and performs only declared
  transfers to Meta-scoped state. Build state, encounter state, transient effects, and run currency
  cannot survive by naming convention or evaluator accident. Replay observes the reset and retained
  transfers as ordinary ordered events.

- **Every support claim is backed by a Genre coverage matrix.** Each normative row records:
  requirement id and statement; owning capability/operation identities; involved package boundary;
  positive Golden scenario; at least one typed-outcome, refusal, or boundary vector as applicable;
  and the metric/evidence field that makes the behavior observable. Vector ids ending in
  `-outcome-v1` denote successfully executed gameplay branches; `-refused-v1` is reserved for
  inability to accept or execute declared Schema semantics. A row is incomplete if any column is
  absent. Package inventory, prose examples, or unit tests alone do not establish representational
  adequacy. Row closure applies bADR-0012's Claim closure law to the exact admitted operations,
  Golden scenario, vectors, and public observations named by the row. bADR-0012 exclusively owns
  the generic artifact, graph, Verifier-receipt, independence, and Gate 2 dependency requirements;
  this bADR adds only row-specific inputs. Research mappings, caller assertions, fixture names,
  expected-output records, and status labels remain non-authoritative inputs. A refusal vector also
  applies bADR-0015's complete terminal-audit contract and exact vector-result binding; bADR-0015
  exclusively owns that set's members and bindings.

- **The RPG minimum coverage includes:** typed base/parameter/derived-stat composition across
  progression, build, and effect contributions; dynamic target selection; resource
  reservation/payment/regeneration plus action cooldown; action admission/resolution/completion/
  interruption; threshold/opposed hit checks; critical and staged ordered typed damage components
  resolved against matching defenses before final aggregation/rounding, plus typed healing;
  mitigation, resistance, shields, defeat, and revival policy; immunity; snapshot/live capture;
  independent base/resolved capture source; buildup/activation; stacking, reapplication,
  contribution, transition, expiration, and dispel; model-authored passive/reactive Signal
  subscriptions; build prerequisite/exclusion/synergy and atomic replacement; progression and
  unlock; generated rewards plus a typed disposition to their declared destination; typed economy
  sources, sinks, exchange and pricing; party/enemy encounter composition; and final
  Metrics/evidence emission.
  CRPG/JRPG/ARPG variants may select `game.turn` and/or `game.spatial` capabilities without changing
  core logical-time or language semantics; those optional capabilities are not inherited by every
  RPG/Roguelike support claim.

- **The Roguelike minimum coverage adds:** seeded constrained reward generation; closed fixed,
  pity, and guarantee rarity-policy behavior with separately declared exhaustion fallbacks;
  generated effect pools that compose generation with the ordinary Effect lifecycle;
  build conflict and synergy; dynamic encounter/wave composition; Run-scope teardown; explicit
  typed transfer into Meta-scope progression and its Model Source-derived projection into a
  subsequent run; and replay equality under identical model, experiment, Resolved Runtime profile,
  external input, and seed identities. Metroidvania-like, survivors-like, and deckbuilder-like
  templates may specialize package selection while satisfying the shared lifecycle rows.

- **Every later Genre template must preserve Core Extension Invariance.** The release may add
  Model Source, Domain package releases, template members, Experiments, rows, and vectors, but its
  complete support path must run under the unchanged Kernel primitives, core constructors,
  three-phase scheduler, compiler dispatch, and evaluator dispatch. The permanent conformance suite
  includes a non-RPG nested priority/response witness specifically because it pressures scheduler
  abstraction differently from the RPG/Roguelike tracers. Passing that witness does not claim every
  genre is already covered; it makes the architectural promise falsifiable. If any later bounded,
  deterministic genre requirement needs a core semantic exception, Schema 2.0 fails this invariant
  and the architecture gate reopens rather than weakening the promise.
  Closure requires bADR-0016's public Extension Invariance Receipt: independent builds are frozen
  before the witness graph and its closed Non-Kernel Authority Token Inventory are derived. That
  inventory traverses every reachable artifact and includes every package/capability,
  type/kind/unit/role, Operation/parameter/result variant, Diagnostic, Signal/Event,
  effect/resource, profile/policy, Experiment/Metric/selector, vector, and other non-Kernel identity
  that can affect resolution, dispatch, result decoding, or trace. An independently validated
  bijection renames every member consistently; both implementations consume each other's artifacts
  without rebuild, and the exact core projections remain identical. Source-diff assertions,
  representative rename samples, or private helper inspection cannot close the invariant.
  Deckbuilder-like releases select the ordered-zone Variant row; releases that expose planned
  opponent behavior select the decision/Intent Variant row. Those optional rows are not inherited
  by a release that does not select their capabilities.

- **Validation and implementation proofs remain ordered vertical slices.** The disposable
  layer-connectivity, semantic-authority, and orthogonality probes on PRD #534 are not conformance or
  Genre-closure results. The semantic probe implementation passed its narrow vectors, but the design
  gate remains open because Kernel/LDB laws still require independent execution rather than
  coordinated host interpretation. The orthogonality mechanism probe also passed its selected
  slice: one admitted generic Quantity attribute used a Model Source-only edit, while selected
  resource/interruption/effect mechanics entered through complete package-release authorities and
  generic core paths. It did not cover complete Effect semantics, executable language authority,
  general solving, normative Evidence, or any Genre row. Only after
  the remaining design gates pass may a
  production tracer claim the full source-to-RIR, target, cost, check/damage, effect, encounter,
  Metrics, Evidence, and public-CLI path. Supporting Golden scenarios isolate outcome, refusal,
  limit, and boundary cases; implementation does not build every package horizontally before a
  vertical path runs.

- **This decision supersedes conflicting 2.x template/effect portions of bADR-0001, bADR-0002, and
  bADR-0006.** It replaces “template as one Design-document instance”, root reserved genre sections,
  fixed template attribute-tier assumptions, and the monolithic Effect/Modifier shape for 2.x. It
  retains data-defined genre baselines, orthogonal attribute composition, formula-capable values,
  explicit duration/stacking/reapplication concepts, and hard refusal. Their complete 1.x behavior
  remains normative for 1.x and migration.

## Considered options

- **Template release plus executable coverage matrix** (chosen) — preserves authority boundaries
  and makes genre-support claims independently testable.
- **One large RPG/Roguelike root schema** (rejected) — couples unrelated mechanics and forces every
  genre extension into core.
- **Package list as the support definition** (rejected) — says where concepts might live but not
  whether their operations compose or cover production cases.
- **Genre-specific evaluator profiles** (rejected) — forks semantics in runtime code and conflicts
  with Runtime/Numeric profile-definition terminology.
- **Template dependency that updates instantiated games automatically** (rejected) — makes template
  releases hidden model authority and invalidates evidence without an authored change.
- **Monolithic Effect and Loot objects** (rejected) — combine selection, lifecycle, math, inventory,
  and build policy into shapes that cannot evolve orthogonally.
- **One enormous golden battle only** (rejected) — demonstrates a happy path but cannot localize
  negative, limit, or cross-package boundary failures; the matrix requires both integrated and
  focused vectors.

## Consequences

- RPG/Roguelike package work begins from the matrix and tracer, not from serializing defaults into
  the 1.x Design-document shape.
- Adding a new attribute is normally a Quantity-typed model declaration; adding a reusable mechanic
  is a package operation/capability with conformance vectors, not a root-schema edit.
- Template releases, instantiated models, Experiment Specifications, and approval/evidence records
  retain separate identities and migration histories.
- Metrics/evidence semantics must be decided before the tracer can close every required row.
- The old RPG/Roguelike template implementation issues require re-triage against #534 and this
  coverage contract before work resumes.

## Validation

- For target selection, run empty, singleton, many-candidate, equal-key tie, reordered-source,
  cardinality-under/overflow, and missing-spatial-capability vectors. Assert canonical target ids
  and order, and distinguish a declared empty outcome from a missing-policy refusal.
- For Signals, run payload kind/unit mismatch, undeclared subscriber effect, missing capability,
  duplicate/ambiguous subscription, bounded and unbounded cycle, multiple-subscriber order,
  same-snapshot visibility, and subscriber-fault rollback vectors. Source topology must lower to one
  canonical RIR table; an evaluator registry cannot add or reorder subscribers.
- For Effect interactions, cross reapplication-at-cap with immunity, buildup-threshold activation,
  scheduled tick/transition, expiry, and dispel. Cross removal with transition/contribution in one
  transaction and in adjacent equal-time Events. Assert the declared precedence outcome, suppressed
  requests, exact cancellations, final stack/instance identity, contribution state, and schedule;
  no host order or partially declared policy may affect the result. Permute source declaration and
  host-container order while preserving canonical request keys and require byte-identical outcomes;
  refuse duplicate keys, an unordered removal cause, a missing same-stage reducer, or a late append
  after request-set closure. Move the same request from the current Event buffer to a declared child
  Event and assert that it observes the prior commit rather than joining the original Snapshot/reducer.
  Mutate a new-application partition input, existing-instance lifecycle key, multi-target expansion,
  envelope order, or request-to-set membership and require identical canonical grouping or a typed
  refusal; no implementation may use instance existence or host grouping order to choose a bucket.
- Run a non-RPG nested priority-window scenario with proposal, counter, counter-to-counter, pass,
  cancellation/replacement, and final resolution across declared input boundaries. The scenario may
  add only package/LDB content and Model Source; changing a Kernel law, constructor, runtime phase,
  compiler branch, or evaluator branch fails Core Extension Invariance.
- Freeze independent compiler/evaluator builds before deriving the witness graph and its complete
  Non-Kernel Authority Token Inventory, then rename every inventory member through an independently
  validated bijection and repeat mutual artifact consumption. The inventory must include
  Capability, Diagnostic, profile/policy, result-variant, Signal, Event, and every other reachable
  non-Kernel identity, not only package/type/operation tokens. Validate a public Extension
  Invariance Receipt binding the unchanged core projections/build identities, inventory, complete
  rename mapping, exact inputs, and public outputs; an incomplete inventory, omitted or invalid
  rename, rebuild, host capability addition, or private helper path refuses closure.
- For every matrix row, execute its Golden scenario plus each outcome/refusal/boundary vector only
  through public build/run artifacts. Private evaluator state, helper-only behavior, or prose
  expected results cannot close a row. Delete or mutate one exact prerequisite artifact while
  retaining a caller-provided `closed` assertion; the row must remain open or refuse.
- Apply bADR-0012's Verifier-receipt mutations to a row closure judgment; every omitted, forged, or
  ineligible required receipt keeps the aggregation `candidate`/open.
- Present a refusal artifact with the expected kind, fixture label, and observable pointer but omit
  or mismatch any terminal-audit member or binding required by bADR-0015, including its exact
  vector-result binding. The row remains open and every independently observable defect is reported
  within the deterministic cap.
- Add one ordinary attribute and one reusable package mechanic, then rerun all previously closed
  rows. The attribute must require only model declarations; the mechanic must require only versioned
  package/language/vector additions and must not change unrelated core semantics.

## References

- PRD #501 — balancing toolkit product requirements.
- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- Issue #540 — bounded RPG combat product-feedback slice.
- Issue #590 — accepted Formula authoring and evaluation contract.
- `docs/standard-schema-2.0/genre-coverage.md` — normative RPG/Roguelike rows, scenarios,
  negative vectors, and tracer gate.
- bADR-0001/0002/0006 — Standard Schema 1.x document, attribute, and effect contracts.
- bADR-0012 — authored authority domains.
- bADR-0014 — deterministic atomic event runtime.
- bADR-0016 — closed type core and versioned package extensions.
