# RPG and Roguelike Genre coverage matrix

This matrix is the open representational-adequacy contract required by bADR-0017. It defines what a
future support claim must prove; it is not evidence that Standard Schema 2.0 or a genre template is
implemented. Every row is currently `open`. A support claim becomes valid only when every inherited
row has an admitted operation, executable Golden scenario, executable negative/boundary vector, and
observable evidence field.

The ids below reserve the intended operation and fixture boundaries for review, but do not enter the
machine authority merely by appearing here. The Language Definition Bundle must admit or explicitly
revise them, provide their closed types and semantics, and carry executable fixture inputs plus
canonical expected artifacts/outcomes. Prose expectations do not close a row.
Research-corpus mappings likewise discover pressure on this contract but cannot close it. Closure
consumes only retrievable, rehashed, exactly bound public artifacts and authoritative judgments;
caller assertions, fixture labels, and expected-output records cannot authorize a claim.

`Tracer` rows are the first vertical implementation gate. `RPG` rows must close before a general
RPG template-release claim. `Roguelike` rows add to all `Tracer` and `RPG` rows before a Roguelike
template-release claim. `Variant` rows close only when a release selects their optional capability;
they are not inherited by every genre. CRPG/JRPG/ARPG and metroidvania-like/survivors-like/
deckbuilder-like releases may add rows but cannot waive inherited baseline rows.
`Extension` rows are permanent adversarial witnesses for Core Extension Invariance. They do not
claim a complete template for the witness genre, but they must close without changing Kernel
primitives, core constructors, runtime phases, compiler dispatch, or evaluator dispatch.

## Matrix

| Gate / requirement | Normative requirement | Capability and operation ids | Package boundary exercised | Golden scenario | Negative or boundary vector | Required observable |
|---|---|---|---|---|---|---|
| Tracer `RPG-STAT-01` | Compose explicitly typed base/parameter/state symbols into derived combat values through progression, build and effect contributions with declared kind, unit, rounding and cap laws. | `core.typed-symbols-v1`; `core.expression.derive@1`; `game.build.contribution@1`; `game.progression.contribution@1`; `game.effect.contribute@1` | Model Source owns named Formula declarations and exact Operation-slot bindings; core/LDB owns pure-expression typing/evaluation/context laws; packages own independently composable contribution sources and Formula-slot contracts | `rpg.stat.composition-v1` | `rpg.stat.dependency-cycle-refused-v1`; `rpg.stat.kind-unit-mismatch-refused-v1`; `rpg.stat.round-cap-boundary-v1` | resolved dependency graph, exact Formula/binding/context identities, Model explanation, contribution provenance, Numeric profile and final typed Quantity |
| Tracer `RPG-TARGET-01` | Resolve targets from the current dynamic entity set with declared filtering, cardinality, stable order, tie and empty behavior. | `game.entity.dynamic-sets-v1`; `game.query.dynamic-targets-v1`; `game.query.select@1` | entity owns membership; query owns selection; action consumes resolved refs | `rpg.combat.cast-v1` | `rpg.target.empty-outcome-v1`; `rpg.target.empty-policy-missing-refused-v1` | target ids/order and `target_count` Metric sample |
| Tracer `RPG-COST-01` | Reserve an action cost, commit it exactly once, and make insufficient funds an explicit typed outcome. | `game.resource.atomic-cost-v1`; `game.resource.reserve@1`; `game.resource.commit@1`; `game.action.begin@1` | resource owns quantity/reservation; action owns lifecycle | `rpg.combat.cast-v1` | `rpg.resource.insufficient-outcome-v1` | reservation/commit trace, before/after resource Quantity |
| RPG `RPG-RESOURCE-02` | Regenerate a typed resource by a declared rate/domain while action cooldown state gates reuse independently. | `game.resource.regeneration-v1`; `game.resource.regenerate@1`; `game.action.cooldown-v1`; `game.action.set-cooldown@1` | resource owns current/capacity/rate; action owns cooldown lifecycle | `rpg.resource.regeneration-cooldown-v1` | `rpg.resource.capacity-boundary-v1`; `rpg.action.cooldown-active-outcome-v1` | applied/clamped regeneration, cooldown deadline and next legal action time |
| Tracer `RPG-CHECK-01` | Resolve threshold or opposed hit checks with named randomness, explicit tie policy, and success degree. | `game.check.typed-resolution-v1`; `game.check.resolve@1` | check owns resolution; combat consumes the typed outcome | `rpg.combat.cast-v1` | `rpg.check.tie-policy-missing-refused-v1` | stream identity/draw index and `hit_degree` Metric sample |
| Tracer `RPG-DAMAGE-01` | Apply critical and an ordered vector of typed damage components through declared per-kind stages, then aggregate and round only after component resolution. | `game.combat.staged-damage-v1`; `game.combat.typed-damage-vector-v1`; `game.combat.resolve-damage@1` | check produces outcome; combat owns component/stage order and final aggregation; resource owns health-like current value; entity owns defeat state storage | `rpg.combat.cast-v1` | `rpg.combat.kind-mismatch-refused-v1`; `rpg.combat.split-component-order-boundary-v1` | ordered component kinds/inputs, matching defense identity, per-component stage trace, aggregation/rounding trace and final typed Quantity |
| RPG `RPG-HEAL-01` | Apply typed healing, amplification/reduction, caps and revival policy without treating healing as negative damage. | `game.combat.staged-healing-v1`; `game.combat.resolve-healing@1` | combat owns healing stages and revival transition policy; resource owns current/capacity; entity owns defeat/revival state storage | `rpg.combat.healing-v1` | `rpg.combat.revival-not-allowed-outcome-v1` | per-stage healing, cap/clamp result and defeat/revival transition |
| Tracer `RPG-DEFENSE-01` | Resolve each ordered damage component against its matching mitigation/resistance kind before final aggregation, then apply shields, health and defeat in one stable order. | `game.combat.staged-damage-v1`; `game.combat.typed-damage-vector-v1`; `game.combat.resolve-damage@1` | combat owns per-kind defense and stage order; resource owns shield/health quantities; entity owns target identity and defeat state storage | `rpg.combat.cast-v1` | `rpg.combat.defense-kind-missing-refused-v1`; `rpg.combat.defeat-order-boundary-v1` | ordered component/defense pairs, intermediate deltas, aggregation result, shield/health deltas and defeat transition |
| Tracer `RPG-EFFECT-01` | Apply an effect with immunity, stack identity/cap, and explicit reapplication policy. | `game.effect.lifecycle-v1`; `game.effect.apply@1` | effect owns lifecycle; combat/action only consume effect outcomes | `rpg.effect.stack-immunity-v1` | `rpg.effect.immunity-outcome-v1`; `rpg.effect.stack-cap-boundary-v1` | effect instance ids, stack count, immunity/reapply outcome |
| Tracer `RPG-EFFECT-02` | Select each captured value from its declared base/authored or resolved/derived source independently of whether it is snapshotted or read live, without hidden evaluator reads. | `game.effect.lifecycle-v1`; `game.effect.apply@1` | effect declares source layer and capture/read timing; entity/resource own fields and derivation provenance | `rpg.effect.stack-immunity-v1` | `rpg.effect.live-read-undeclared-refused-v1`; `rpg.effect.capture-source-mismatch-refused-v1` | source-layer identity, derivation/version identity, snapshot/live policy and captured/read value in the effect trace |
| Tracer `RPG-ACTION-01` | Interrupt an active action, cancel its resolution event, and apply declared refund policy. | `game.action.lifecycle-v1`; `game.action.begin@1`; `game.action.interrupt@1` | action owns interruption; resource owns refund/commit; runtime owns cancellation | `rpg.combat.cast-v1` | `rpg.action.interrupt-after-complete-outcome-v1` | action state, canceled event id and refund outcome |
| Tracer `RPG-ACTION-02` | Admit one immutable Action plan, then resolve and complete that exact identity once, committing its reservation and scheduling cooldown/declared child effects atomically. | `game.action.plan-v1`; `game.action.admit-plan@1`; `game.action.lifecycle-v1`; `game.action.resolve@1`; `game.action.complete@1`; `game.resource.commit@1` | action owns plan schema/admission/identity and exact execution; resource owns cost commit; runtime owns atomic event commit | `rpg.combat.cast-v1` | `rpg.action.plan-mutation-refused-v1`; `rpg.action.duplicate-completion-refused-v1` | admitted/executed plan identity, immutable bound execution inputs, action-state transitions, one cost commit, child-event ids and cooldown state |
| Tracer `RPG-REACTIVE-01` | Let a Model Source Package declare a passive/reactive subscription to a typed Signal, then execute all resolved subscribers in stable order inside the emitting Event transaction. | `core.signal-subscription-v1`; `game.combat.damage-resolved-signal-v1`; `game.effect.react@1`; `game.action.react@1` | packages own signal/handler contracts; model owns topology; RIR owns resolved table; runtime owns same-snapshot atomic delivery | `rpg.reactive.passive-v1` | `rpg.reactive.illegal-subscription-refused-v1`; `rpg.reactive.unbounded-cycle-refused-v1`; `rpg.reactive.order-boundary-v1` | authored/resolved subscriber ids, stable dispatch order, shared pre-event snapshot and commit/rollback trace |
| Tracer `RPG-EVIDENCE-01` | Finish the encounter and emit shared typed Metrics and evidence from the final committed snapshot. | `game.encounter.dynamic-waves-v1`; `game.encounter.advance@1`; `experiment.balance.metrics-v1`; `experiment.balance.observe@1` | encounter owns terminal condition; experiment owns Metric definition | `rpg.combat.cast-v1` | `rpg.metrics.missing-dimension-refused-v1` | Evaluation-run id, terminal snapshot, Metric dataset and assertion prerequisites |
| RPG `RPG-EFFECT-03` | Expire, remove, and dispel effects under declared legality and cleanup rules, preserving one typed removal cause and canceling the exact outstanding schedule owned by the removed instance. | `game.effect.lifecycle-v1`; `game.effect.remove@1` | effect owns removal and removal cause; runtime owns scheduled expiry/cancel | `rpg.effect.stack-immunity-v1` | `rpg.effect.illegal-dispel-outcome-v1` | removal cause, effect-instance identity, exact expiry/tick event cancellations and remaining stacks |
| RPG `RPG-EFFECT-04` | Accumulate typed buildup, activate exactly one instance at its declared threshold, and compute continuous/discrete contributions and state transitions without hidden write ordering. | `game.effect.contribution-v1`; `game.effect.buildup-activation-v1`; `game.effect.accumulate@1`; `game.effect.activate@1`; `game.effect.contribute@1`; `game.effect.transition@1` | effect owns buildup/activation/contribution/transition law; receiving package owns reduced target slot; runtime owns one-final-write/reducer and bounded-schedule rules | `rpg.effect.contribution-transition-v1` | `rpg.effect.buildup-threshold-boundary-v1`; `rpg.effect.missing-reducer-refused-v1` | buildup before/after, threshold comparison, activated instance/schedule, contributor order/identity, reducer result and old/new effect state |
| RPG `RPG-EFFECT-05` | Resolve coincident same-Event removal, tick/transition, immunity, buildup activation, stack-cap reapplication, contribution, and schedule requests under one complete observable request-set, precedence, and same-stage reduction policy; later child-Event requests observe the prior commit. | `game.effect.lifecycle-v1`; `game.effect.request-set-v1`; `game.effect.resolve-requests@1`; `game.effect.remove@1`; `game.effect.apply@1`; `game.effect.accumulate@1`; `game.effect.contribute@1`; `game.effect.transition@1` | effect owns canonical request-set boundary/origin keys, per-stage variant order, multiplicity reducers and cross-stage precedence; runtime owns Event total order and atomic commit; Signal subscribers may contribute only declared requests; receiving packages consume only the final declared contribution/transition | `rpg.effect.interaction-order-v1` | `rpg.effect.partial-precedence-policy-refused-v1`; `rpg.effect.duplicate-request-key-refused-v1`; `rpg.effect.removal-cause-order-refused-v1`; `rpg.effect.late-request-append-refused-v1`; `rpg.effect.remove-reapply-order-boundary-v1`; `rpg.effect.dispel-transition-order-boundary-v1`; `rpg.effect.child-event-snapshot-boundary-v1` | canonical EffectRequestSet and origin provenance, same-Event versus child-Event boundary, ordered precedence/reducer decisions, selected removal cause, suppressed/coalesced requests, exact cancellations, final instance/stack/contribution state and schedule delta |
| RPG `RPG-BUILD-01` | Enforce build prerequisites, exclusions, slots and explicit synergy declarations, and atomically replace one admitted selection without exposing an empty or double-filled intermediate build. | `game.build.constraints-v1`; `game.build.atomic-replacement-v1`; `game.build.select@1`; `game.build.replace@1` | build owns selection/replacement outcome and slot/cardinality invariants; economy or collection owns possession; action/effect own old/new behavior cancellation/activation | `rpg.build-progression-loot-v1` | `rpg.build.exclusion-outcome-v1`; `rpg.build.atomic-replacement-boundary-v1` | accepted/rejected choice, prerequisite path, active synergies, old/new identities, retained selections, slot count, cancellation ids and activation ids |
| RPG `RPG-PROGRESSION-01` | Award typed progression and emit all crossed unlocks in stable threshold order. | `game.progression.unlocks-v1`; `game.progression.award@1` | progression owns thresholds/unlocks; build may consume unlocks | `rpg.build-progression-loot-v1` | `rpg.progression.unlock-order-boundary-v1` | progression before/after and ordered unlock ids |
| RPG `RPG-LOOT-01` | Generate a constrained reward and exhaustively handle its typed disposition through the declared destination without fabricating economy state for a non-economic reward. | `game.generation.constrained-reward-v1`; `game.generation.reward-disposition-v1`; `game.generation.draw@1`; `game.collection.move@1`; `game.economy.transfer@1`; `game.effect.apply@1`; `game.build.select@1` | generation chooses and returns the disposition; collection/economy/effect/build performs only its declared destination step | `rpg.build-progression-loot-v1` | `rpg.loot.direct-collection-boundary-v1`; `rpg.loot.inventory-capacity-outcome-v1`; `rpg.loot.disposition-unhandled-refused-v1` | stream/draw, selected definition, disposition variant, destination operation/outcome, absence of undeclared ledger writes and applicable build result |
| RPG `RPG-ECONOMY-01` | Model typed currency/inventory sources, sinks and transfers with explicit conservation, capacity and overdraft policy. | `game.economy.ledger-v1`; `game.economy.issue@1`; `game.economy.retire@1`; `game.economy.transfer@1` | economy owns ledgers and flow legality; resource supplies typed quantities; generation/build only consume outcomes | `rpg.economy.flow-v1` | `rpg.economy.overdraft-outcome-v1`; `rpg.economy.unbalanced-transfer-refused-v1` | source/sink/transfer identities, before/after balances, conservation equation and disposition |
| RPG `RPG-ECONOMY-02` | Quote and execute typed exchange/pricing under exact rate, rounding, fee and price-policy identities without hidden market state. | `game.economy.exchange-pricing-v1`; `game.economy.quote@1`; `game.economy.exchange@1` | economy owns price/rate/fee law; resource owns asset quantities; experiment may bind market inputs | `rpg.economy.exchange-pricing-v1` | `rpg.economy.rate-missing-refused-v1`; `rpg.economy.insufficient-outcome-v1`; `rpg.economy.rounding-boundary-v1` | quote/policy identity, typed debits/credits/fees, rounding trace and conservation result |
| RPG `RPG-ENCOUNTER-01` | Compose party and enemy groups under explicit membership, role, budget and difficulty constraints before bounded wave/objective progression. | `game.encounter.composition-v1`; `game.encounter.compose@1`; `game.encounter.advance@1`; `game.entity.dynamic-sets-v1` | encounter owns composition/objectives; entity owns members; build/progression expose resolved capabilities | `rpg.encounter.composition-v1` | `rpg.encounter.party-constraint-refused-v1`; `rpg.encounter.budget-boundary-v1` | ordered party/enemy ids, constraint/budget contributions, wave/objective state and terminal condition |
| Variant `RPG-TURN-SPATIAL-01` | When selected, optional turn/spatial packages compose without changing core logical-time phases or target-query rules. | `game.turn.windows-v1`; `game.turn.advance@1`; `game.spatial.queries-v1`; `game.spatial.query@1`; `game.query.select@1` | turn owns windows; spatial owns geometry; query owns final selection; runtime owns phases | `rpg.turn-spatial-target-v1` | `rpg.turn.hidden-phase-refused-v1` | phase key, turn/window id, spatial candidates and final target order |
| Extension `GENRE-PRIORITY-WINDOW-01` | Represent a non-RPG nested proposal/response stack with counter, counter-to-counter, pass, cancellation/replacement, and final resolution across declared input boundaries without changing core semantics. | `game.turn.priority-windows-v1`; `game.turn.open-window@1`; `game.turn.respond@1`; `game.turn.pass@1`; `game.turn.close-window@1`; `game.action.propose@1`; `game.action.counter@1`; `game.action.resolve@1` | action owns pending proposal/plan and its final outcome; turn owns responder priority, pass/close state and bounded nesting; runtime owns only fixed input/transition/observation order | `genre.priority-stack-v1` | `genre.priority.hidden-phase-refused-v1`; `genre.priority.unbounded-depth-refused-v1`; `genre.priority.host-callback-refused-v1`; `genre.priority.incomplete-rename-refused-v1`; `genre.priority.omitted-token-class-refused-v1` | Extension Invariance Receipt binding exact unchanged Kernel/constructor/phase/build identities, a complete reachable-graph-derived Non-Kernel Authority Token Inventory, its exhaustive post-build rename bijection, and mutual artifacts/results; pending stack/order, priority holder, input boundary, pass/counter outcomes, cancellation/replacement ids and final resolved proposal |
| Variant `RPG-DECISION-INTENT-01` | When selected, choose one admitted immutable Action plan under declared bounds, project it under an explicit visibility policy, and execute that exact identity even when the projection is masked or partial. | `game.decision.plan-projection-v1`; `game.decision.plan@1`; `game.decision.project-intent@1`; `game.action.admit-plan@1`; `game.action.resolve@1` | encounter supplies actor/context/window; action owns plan admission/identity/execution; decision owns bounded selection and projection | `rpg.decision-intent-v1` | `rpg.decision.no-legal-plan-outcome-v1`; `rpg.intent.masked-projection-boundary-v1` | candidate order, admitted/selected/executed plan identity, projection-policy/result and action outcome |
| Roguelike `ROGUE-REWARD-01` | Draw seeded constrained rewards under one closed fixed-weight, stateful pity, or guarantee/fallback rarity-policy variant without interpreting a pity cap as a guarantee. | `game.generation.constrained-reward-v1`; `game.generation.rarity-policy-v1`; `game.generation.draw@1` | generation owns eligible pool, draw consumption, rarity-policy state and disposition; destination packages consume the result | `roguelike.reward-build-v1` | `roguelike.reward.pity-cap-boundary-v1`; `roguelike.reward.guarantee-exhaustion-outcome-v1`; `roguelike.reward.guarantee-policy-unsatisfiable-refused-v1` | stream/candidate/draw indexes, ordered eligible pool, selected policy variant, rarity state before/after, guarantee state and fallback disposition |
| Roguelike `ROGUE-EFFECT-POOL-01` | Draw a seeded constrained effect offering and apply the selected result through the ordinary Effect lifecycle without a generator-owned effect path. | `game.generation.constrained-reward-v1`; `game.generation.draw@1`; `game.effect.lifecycle-v1`; `game.effect.apply@1` | generation owns eligible-pool selection; effect owns application and lifecycle; build/run may consume the outcome | `roguelike.effect-pool-v1` | `roguelike.effect-pool.unsatisfiable-refused-v1`; `roguelike.effect-pool.immunity-outcome-v1` | stream/draw indexes, ordered eligible effect ids, selected definition/instance, apply outcome and lifecycle schedule |
| Roguelike `ROGUE-BUILD-01` | Apply run-time build conflicts, synergies and atomic replacement to generated rewards, then route the accepted/rejected result through its declared disposition. | `game.build.constraints-v1`; `game.build.atomic-replacement-v1`; `game.build.select@1`; `game.build.replace@1`; `game.generation.draw@1` | generation proposes; build admits/rejects/replaces; the declared destination package handles disposition without a mandatory economy step | `roguelike.reward-build-v1` | `roguelike.build.conflict-outcome-v1`; `roguelike.build.atomic-replacement-boundary-v1` | conflict ids, synergy changes, old/new selection and slot identities, and accepted/rejected reward disposition |
| Roguelike `ROGUE-ENCOUNTER-01` | Compose dynamic encounter/wave state with bounded deterministic spawning and terminal objectives. | `game.encounter.dynamic-waves-v1`; `game.encounter.advance@1`; `game.entity.spawn@1` | encounter owns schedule/objectives; entity owns spawned instances | `roguelike.encounter-waves-v1` | `roguelike.encounter.spawn-cap-refused-v1` | wave/objective trace, spawn order and terminal state |
| Roguelike `ROGUE-RESET-01` | Clear all Run-scoped state and retain only declared typed transfers into Meta scope. | `game.run.scope-reset-v1`; `game.run.reset@1` | packages declare slot scope; run owns teardown/retention transaction | `roguelike.run-reset-v1` | `roguelike.run.implicit-retention-refused-v1` | cleared Run-slot inventory, retained transfer list and post-reset snapshot |
| Roguelike `ROGUE-META-01` | Convert a declared run result into typed Meta-scope progression, then expose its unlock or parameter effect to a subsequent run without retaining unrelated Run state. | `game.run.scope-reset-v1`; `game.run.reset@1`; `game.progression.unlocks-v1`; `game.progression.award@1`; `core.expression.derive@1` | run owns the declared Run-to-Meta transfer boundary; progression owns thresholds/unlocks and Formula-slot contracts; Model Source owns the named Formula, exact slot binding, and typed derivation from Meta state to the next-run initial projection; core/LDB owns Formula typing/evaluation/context laws | `roguelike.meta-progression-v1` | `roguelike.meta.undeclared-transfer-refused-v1`; `roguelike.meta.projection-kind-mismatch-refused-v1` | run-result and transfer identities, Meta progression before/after, ordered unlocks, exact Formula/binding/context identities, Model explanation, derivation provenance and next-run initial projection |
| Roguelike `ROGUE-REPLAY-01` | Reproduce the same RIR outcomes, trace, Metrics and evidence under identical reproduction identities. | core replay contract; all operations exercised by the scenario | bundle/RIR/runtime/experiment identities jointly define replay | `roguelike.replay-v1` | `roguelike.replay.identity-mismatch-refused-v1` | reproduction key, ordered trace/Snapshot hashes, Metric/evidence identities |
| Variant `ROGUE-DECK-ZONE-01` | When selected, move unique card instances among ordered draw, hand, discard and exhaust zones, including one named-stream reshuffle handoff, without loss, duplication or host-container ordering. | `game.collection.ordered-zones-v1`; `game.collection.move@1`; `game.collection.shuffle@1`; `game.turn.advance@1`; `game.action.resolve@1` | collection owns zone order/moves/shuffle/conservation; turn owns windows; action owns play lifecycle; build owns deck admission | `roguelike.deck-zones-v1` | `roguelike.deck-zone.duplicate-instance-refused-v1`; `roguelike.deck-zone.reshuffle-boundary-v1` | exact per-zone instance order, move identities, named stream/draw trace, shuffle count and conservation proof |

## Golden scenario contracts

- `rpg.stat.composition-v1`: base and tunable typed symbols combine progression, equipment and
  effect contributions into a derived combat Quantity with explicit rounding/cap behavior.
- `rpg.combat.cast-v1`: a dynamic caster admits one immutable Action plan, targets one enemy,
  reserves mana, resolves that exact plan identity through a named-stream hit/critical check,
  resolves an ordered split-damage vector per kind before final aggregation,
  applies an effect, exercises interruption, terminates the encounter, and emits Metrics/evidence
  through `experiment run`.
- `rpg.effect.stack-immunity-v1`: base/resolved source selection and snapshot/live timing, immune
  target, stack cap, reapplication, expiry, dispel, and trace atomicity are exercised without
  action/combat owning effect lifecycle.
- `rpg.effect.contribution-transition-v1`: typed buildup crosses one activation threshold, creates
  one bounded effect schedule, and multiple contributions use a declared reducer before typed
  removal cancels the exact remaining schedule without hidden write order.
- `rpg.effect.interaction-order-v1`: at-cap reapplication, threshold activation, scheduled
  transition, expiry, and dispel are crossed in same-Event and adjacent equal-time Event cases; the
  trace proves the canonical EffectRequestSet boundary/origin, request ordering/reduction, the
  single selected removal cause, removal dominance, every suppressed/coalesced request, final state,
  exact schedule delta, and the post-commit Snapshot observed by a later child Event.
- `rpg.resource.regeneration-cooldown-v1`: regeneration reaches a typed capacity boundary while an
  independent action cooldown blocks and later admits reuse.
- `rpg.combat.healing-v1`: staged typed healing exercises caps, reduction/amplification and explicit
  no-revival/revival policy.
- `rpg.reactive.passive-v1`: a model-authored passive subscribes to a typed combat Signal; multiple
  resolved subscribers prove stable order, same-snapshot visibility and atomic rollback behavior.
- `rpg.build-progression-loot-v1`: progression unlocks a build choice; constrained generation
  yields both an economic reward and a direct collection reward; each closed disposition reaches
  only its declared destination; build validates prerequisites/exclusions/synergies and one atomic
  replacement preserves slot/cardinality invariants.
- `rpg.economy.flow-v1`: typed issuance, retirement, inventory transfer, capacity, overdraft and
  conservation policies produce explicit ledger entries and gameplay outcomes.
- `rpg.economy.exchange-pricing-v1`: an exact pricing policy quotes and executes a typed exchange
  with declared rates, fees and rounding while preserving the configured conservation law.
- `rpg.encounter.composition-v1`: resolved party/build/progression capabilities and enemy candidates
  satisfy explicit membership, role, budget and difficulty constraints before waves advance.
- `rpg.turn-spatial-target-v1`: optional turn windows and spatial candidates feed the unchanged
  typed target-query operation while the scheduler retains the three core phases.
- `genre.priority-stack-v1`: a non-RPG pending action receives a counter and nested counter, advances
  explicit responder/pass state across declared input boundaries, cancels or replaces only stable
  pending identities, and resolves after closure while Kernel, constructors, phases, and host
  dispatch remain unchanged.
- `rpg.decision-intent-v1`: one committed Action plan is projected normally and under a masking
  policy; both paths execute the same plan identity and action result.
- `roguelike.reward-build-v1`: fixed, pity, and guarantee/fallback rarity-policy vectors compose
  with run-local build conflicts, synergies, replacement, and typed destination dispositions.
- `roguelike.effect-pool-v1`: constrained generation selects from an ordered eligible effect pool,
  then the selected definition follows the same apply, immunity, stacking, transition, and removal
  contracts used outside procedural generation.
- `roguelike.encounter-waves-v1`: objectives advance bounded waves and dynamic spawns to a terminal
  encounter.
- `roguelike.run-reset-v1`: terminal run state is torn down and only declared typed rewards enter
  Meta scope.
- `roguelike.meta-progression-v1`: a declared retained run result advances typed Meta progression,
  emits ordered unlocks, and changes the next run's admitted initial projection through a Model
  Source derivation without leaking any undeclared Run-scoped slot.
- `roguelike.replay-v1`: the reward, encounter, and reset path runs twice under one reproduction
  key and produces byte-identical canonical observations.
- `roguelike.deck-zones-v1`: drawing across a non-empty draw pile into a discard reshuffle preserves
  exact instance order, performs one named-stream shuffle, and proves no card was lost or duplicated.

## Closure rules

A row is `closed` only when all referenced package/operation ids exist in the admitted bundle, the
Golden and negative/boundary vector ids are in its vector inventory, and the public CLI artifacts
contain every required observable. Each row applies bADR-0012's Claim closure law to those exact
row-specific inputs; this matrix does not redefine the generic artifact, graph, receipt,
independence, or Gate 2 dependency contract. Research mappings and caller-provided status, fixture,
or expected-output records remain non-authoritative. A refusal vector additionally applies
bADR-0015's complete terminal-audit member/binding contract and exact vector-result binding; this
matrix does not enumerate that contract. A typed gameplay outcome may satisfy a negative vector
when the model explicitly declares that branch; invalid language or runtime conditions must use the
bADR-0015 refusal path. Vector ids ending in `-refused-v1` are reserved for Schema typed refusals;
expected gameplay branches use `-outcome-v1`. A test that reaches private evaluator state or uses
an unregistered helper does not close the row.

Guarantee exhaustion is an outcome only when the authored reward policy declares an exhaustive
fallback such as no reward, currency, or a relaxed pool. A guarantee whose admitted constraints
cannot select any result and declare no fallback is an unsatisfiable-policy refusal; implementations
may not choose between those meanings implicitly.

A pity policy changes declared rarity state after named draws but never implies a finite guaranteed
transition unless its selected policy variant says so. Reaching a pity offset cap while another
rarity remains selectable is a boundary observation, not guarantee exhaustion.

Adding an ordinary game-specific attribute adds a nominal Quantity declaration or component field;
it changes neither the core type constructor set nor this matrix. A row changes only when a genre
support requirement or reusable mechanism changes. Adding that reusable mechanic requires a
versioned package capability/operation, rule semantics, diagnostics and vectors, then updates every
affected row. This is the extension test for consistency, orthogonality, and coverage.

An `Extension` row additionally compares the exact Kernel Specification, closed constructor set,
runtime phase table, compiler dispatch surface, and evaluator dispatch surface before and after the
witness package suite through a public Extension Invariance Receipt. Independent implementation
builds are fixed before the complete reachable witness artifact graph is traversed into a closed
Non-Kernel Authority Token Inventory. An independently validated exhaustive bijection then renames
every member, including package/capability, type/kind/unit/role, Operation/parameter/result variant,
Diagnostic, Signal/Event, effect/resource, profile/policy, Experiment/Metric/selector, vector, and
any other identity that affects resolution, dispatch, result decoding, or trace. Both
implementations mutually consume the renamed artifacts without rebuilding or adding host
capabilities. A difference in any core projection/build identity, an incomplete inventory,
omitted/duplicate/reserved/extra rename, or private helper path fails the row even when the gameplay
output looks correct; package/LDB additions and their generated projections are the only permitted
semantic growth.
