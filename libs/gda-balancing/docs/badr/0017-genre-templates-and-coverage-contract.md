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

## Decision

- **A Genre template is a versioned template release, not a Standard Schema instance or runtime
  profile.** A release contains:
  - an instantiable starter Model Source Package with default declarations and formulas;
  - companion Experiment Specifications with scenarios, metrics, and targets;
  - a Genre coverage matrix and its Golden scenarios/negative vectors;
  - a manifest binding template version, compatible Language Definition Bundle/package ranges, and
    the content identities of those members.
  The release is a distribution container, not a semantic authority: each member retains its
  bADR-0012 authority domain.

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

- **The initial game-domain package boundaries are:**

  | Package | Owns | Does not own |
  |---|---|---|
  | `game.entity` | entity identity, components, defeat/revival state storage, faction/team/relationship, dynamic entity sets | combat resolution, defeat/revival transition policy, targeting, or action lifecycle |
  | `game.resource` | typed current/capacity storage including health/shield-like quantities, cost, regeneration, reservation and transfer | action timing, damage/healing stages, or lifecycle transition policy |
  | `game.query` | typed target filters, ordering, cardinality, tie-break and empty behavior | target-side effects |
  | `game.check` | threshold/opposed checks, hit resolution, dice/pools, advantage and success degree | damage application |
  | `game.action` | requirements, resource commitment, wind-up/channel, cooldown, completion and interruption; execution of an already resolved Action plan | target enumeration, plan selection/projection, or damage math |
  | `game.effect` | application and capture-source/timing policy, buildup/activation, contributions, transitions, schedule, stacking/reapply/remove and immunity contracts | action lifecycle or combat pipeline |
  | `game.combat` | ordered typed damage-component and healing stages, criticals, per-kind mitigation/resistance, shield resolution, aggregation/rounding, and defeat/revival transition policy | entity/resource state storage, generic effect lifetime or inventory |
  | `game.build` | equipment/skill/perk selection and atomic replacement, prerequisites, exclusivity, slots and synergy declarations | item ownership, reward sampling, or old-action/effect cancellation semantics |
  | `game.progression` | XP, levels, growth, unlocks and progression gates | currency exchange or run reset |
  | `game.economy` | currency, inventory, sources/sinks, transfer, exchange and pricing | stochastic reward selection |
  | `game.collection` | typed ordered instance collections, stable order, zone membership, legal moves, shuffle handoff and no-duplicate/no-loss conservation | turn windows, action lifecycle, build admission, economic ledgers, or Run/Meta retention |
  | `game.generation` | seeded weighted/constrained pools, closed fixed-weight/pity/guarantee/fallback rarity policies, and typed reward disposition results | destination collection/economy/effect mutation or meta retention |
  | `game.encounter` | party/enemy composition, spawn/wave schedule, objectives and terminal conditions | entity internals, action-plan choice/projection, or scheduler law |
  | `game.decision` | bounded candidate evaluation, immutable Action-plan selection, and policy-governed observable Intent projection | encounter composition, action execution, or evaluator callbacks |
  | `game.run` | Run/Meta scope declarations, start/end/reset and explicit retained transfers | progression formulas themselves |
  | `game.turn` | optional rounds, initiative, action economy and turn windows | core logical-time scheduler |
  | `game.spatial` | optional positions, ranges, shapes, movement and spatial queries | generic target-query semantics |

  Package names are stable conceptual namespaces; final operation/type inventories live only in the
  Language Definition Bundle.

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

- **Ordered collections are Domain behavior, not `List` semantics or inventory.**
  `game.collection` composes core collection values into typed collections whose instance identity,
  stable order, zone membership, legal moves, named-stream shuffle handoff, and conservation law
  are observable. `game.turn` owns windows, `game.action` owns card/action lifecycle, `game.build`
  owns deck/build admission, `game.economy` owns economic inventory and ledgers, and `game.run` owns
  scope/reset. None may inherit order from a host container or duplicate this transition contract.

- **An Action plan, its Intent projection, and its execution are separate facts.**
  `game.encounter` supplies the acting entity, context, and decision window; `game.decision`
  deterministically selects one immutable Action plan under declared bounds and projects it through
  an explicit visibility policy; `game.action` executes that exact plan. A masked or partial Intent
  changes only the observable projection, never plan identity or execution. Evaluator-owned AI
  callbacks, ambient candidate order, and treating a projection as executable authority are
  prohibited.

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
  adequacy. Claim closure consumes only retrievable, rehashed, exactly bound artifacts whose
  authoritative judgments and prerequisite graph validate. Research mappings, caller assertions,
  fixture names, expected-output records, or status labels cannot close a row. Rehashing proves
  integrity, not independent verification; when the row policy requires independence, bADR-0012's
  authenticated Verifier receipt and trust preconditions also apply or the row remains open.
  Digest strings do not replace complete envelopes, set manifests/receipts, or graph validation.
  A refusal vector closes only from a complete bADR-0015 terminal-audit set whose stage, typed
  Diagnostic, committed trace, last Snapshot, refusing Event, rollback, Resolved Runtime profile,
  and reproduction bindings agree with its exact vector result. Gate 2's Kernel/LDB/schema
  authorities and bounded validators precede verifier receipts and aggregation; an earlier
  aggregator is research-only.

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
  pity, and guarantee/fallback rarity-policy behavior; generated effect pools that compose
  generation with the ordinary Effect lifecycle;
  build conflict and synergy; dynamic encounter/wave composition; Run-scope teardown; explicit
  typed transfer into Meta-scope progression and its Model Source-derived projection into a
  subsequent run; and replay equality under identical model, experiment, Resolved Runtime profile,
  external input, and seed identities. Metroidvania-like, survivors-like, and deckbuilder-like
  templates may specialize package selection while satisfying the shared lifecycle rows.
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
  historical package identity, general solving, normative Evidence, or any Genre row. Only after
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
- For every matrix row, execute its Golden scenario plus each outcome/refusal/boundary vector only
  through public build/run artifacts. Private evaluator state, helper-only behavior, or prose
  expected results cannot close a row. Delete or mutate one exact prerequisite artifact while
  retaining a caller-provided `closed` assertion; the row must remain open or refuse.
- Rehash all row artifacts but omit, forge, or self-issue a policy-required Verifier receipt; the
  aggregation must remain `candidate`/open until receipt identity/bindings, authenticity,
  independence, and verifier eligibility are established.
- Present a refusal artifact with the expected kind, fixture label, and observable pointer but omit
  or mismatch its terminal-audit set manifest/receipt, stage, Diagnostic, committed trace, last
  Snapshot, refusing Event, rollback, Resolved Runtime profile, reproduction, or vector-result
  binding. The row remains open and every independently observable defect is reported within the
  deterministic cap.
- Add one ordinary attribute and one reusable package mechanic, then rerun all previously closed
  rows. The attribute must require only model declarations; the mechanic must require only versioned
  package/language/vector additions and must not change unrelated core semantics.

## References

- PRD #501 — balancing toolkit product requirements.
- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- `docs/standard-schema-2.0/genre-coverage.md` — normative RPG/Roguelike rows, scenarios,
  negative vectors, and tracer gate.
- bADR-0001/0002/0006 — Standard Schema 1.x document, attribute, and effect contracts.
- bADR-0012 — authored authority domains.
- bADR-0014 — deterministic atomic event runtime.
- bADR-0016 — closed type core and versioned package extensions.
