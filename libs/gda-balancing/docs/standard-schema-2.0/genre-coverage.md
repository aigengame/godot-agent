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

`Tracer` rows are the first vertical implementation gate. `RPG` rows must close before a general
RPG template-release claim. `Roguelike` rows add to all `Tracer` and `RPG` rows before a Roguelike
template-release claim. `Variant` rows close only when a release selects their optional capability;
they are not inherited by every genre. CRPG/JRPG/ARPG and metroidvania-like/survivors-like/
deckbuilder-like releases may add rows but cannot waive inherited baseline rows.

## Matrix

| Gate / requirement | Normative requirement | Capability and operation ids | Package boundary exercised | Golden scenario | Negative or boundary vector | Required observable |
|---|---|---|---|---|---|---|
| Tracer `RPG-STAT-01` | Compose explicitly typed base/parameter/state symbols into derived combat values through progression, build and effect contributions with declared kind, unit, rounding and cap laws. | `core.typed-symbols-v1`; `core.expression.derive@1`; `game.build.contribution@1`; `game.progression.contribution@1`; `game.effect.contribute@1` | core owns nominal typing/formula evaluation; packages own independently composable contribution sources | `rpg.stat.composition-v1` | `rpg.stat.dependency-cycle-refused-v1`; `rpg.stat.kind-unit-mismatch-refused-v1`; `rpg.stat.round-cap-boundary-v1` | resolved dependency graph, contribution provenance, Numeric profile and final typed Quantity |
| Tracer `RPG-TARGET-01` | Resolve targets from the current dynamic entity set with declared filtering, cardinality, stable order, tie and empty behavior. | `game.entity.dynamic-sets-v1`; `game.query.dynamic-targets-v1`; `game.query.select@1` | entity owns membership; query owns selection; action consumes resolved refs | `rpg.combat.cast-v1` | `rpg.target.empty-refused-v1` | target ids/order and `target_count` Metric sample |
| Tracer `RPG-COST-01` | Reserve an action cost, commit it exactly once, and make insufficient funds an explicit typed outcome. | `game.resource.atomic-cost-v1`; `game.resource.reserve@1`; `game.resource.commit@1`; `game.action.begin@1` | resource owns quantity/reservation; action owns lifecycle | `rpg.combat.cast-v1` | `rpg.resource.insufficient-refused-v1` | reservation/commit trace, before/after resource Quantity |
| RPG `RPG-RESOURCE-02` | Regenerate a typed resource by a declared rate/domain while action cooldown state gates reuse independently. | `game.resource.regeneration-v1`; `game.resource.regenerate@1`; `game.action.cooldown-v1`; `game.action.set-cooldown@1` | resource owns current/capacity/rate; action owns cooldown lifecycle | `rpg.resource.regeneration-cooldown-v1` | `rpg.resource.capacity-boundary-v1`; `rpg.action.cooldown-active-outcome-v1` | applied/clamped regeneration, cooldown deadline and next legal action time |
| Tracer `RPG-CHECK-01` | Resolve threshold or opposed hit checks with named randomness, explicit tie policy, and success degree. | `game.check.typed-resolution-v1`; `game.check.resolve@1` | check owns resolution; combat consumes the typed outcome | `rpg.combat.cast-v1` | `rpg.check.tie-policy-missing-v1` | stream identity/draw index and `hit_degree` Metric sample |
| Tracer `RPG-DAMAGE-01` | Apply critical and typed damage through declared stages. | `game.combat.staged-damage-v1`; `game.combat.resolve-damage@1` | check produces outcome; combat owns stages; resource owns health-like current value | `rpg.combat.cast-v1` | `rpg.combat.kind-mismatch-v1` | per-stage trace and final typed Quantity |
| RPG `RPG-HEAL-01` | Apply typed healing, amplification/reduction, caps and revival policy without treating healing as negative damage. | `game.combat.staged-healing-v1`; `game.combat.resolve-healing@1` | combat owns healing stages; resource owns current/capacity; entity owns defeat/revival state | `rpg.combat.healing-v1` | `rpg.combat.revival-not-allowed-outcome-v1` | per-stage healing, cap/clamp result and defeat/revival transition |
| Tracer `RPG-DEFENSE-01` | Apply mitigation, resistance, shields, health and defeat in one stable order. | `game.combat.staged-damage-v1`; `game.combat.resolve-damage@1` | combat owns defense stages; entity owns target identity | `rpg.combat.cast-v1` | `rpg.combat.defeat-order-boundary-v1` | stage contributions, shield/health deltas and defeat transition |
| Tracer `RPG-EFFECT-01` | Apply an effect with immunity, stack identity/cap, and explicit reapplication policy. | `game.effect.lifecycle-v1`; `game.effect.apply@1` | effect owns lifecycle; combat/action only consume effect outcomes | `rpg.effect.stack-immunity-v1` | `rpg.effect.immunity-outcome-v1`; `rpg.effect.stack-cap-boundary-v1` | effect instance ids, stack count, immunity/reapply outcome |
| Tracer `RPG-EFFECT-02` | Capture declared fields at snapshot time and read declared live fields without hidden evaluator reads. | `game.effect.lifecycle-v1`; `game.effect.apply@1` | effect declares capture/read effects; entity/resource own fields | `rpg.effect.stack-immunity-v1` | `rpg.effect.live-read-undeclared-v1` | capture source/version and value in effect trace |
| Tracer `RPG-ACTION-01` | Interrupt an active action, cancel its resolution event, and apply declared refund policy. | `game.action.lifecycle-v1`; `game.action.begin@1`; `game.action.interrupt@1` | action owns interruption; resource owns refund/commit; runtime owns cancellation | `rpg.combat.cast-v1` | `rpg.action.interrupt-after-complete-v1` | action state, canceled event id and refund outcome |
| Tracer `RPG-ACTION-02` | Resolve and complete an admitted action exactly once, committing its reservation and scheduling cooldown/declared child effects atomically. | `game.action.lifecycle-v1`; `game.action.resolve@1`; `game.action.complete@1`; `game.resource.commit@1` | action owns resolution/completion; resource owns cost commit; runtime owns atomic event commit | `rpg.combat.cast-v1` | `rpg.action.duplicate-completion-refused-v1` | action-state transitions, one cost commit, child-event ids and cooldown state |
| Tracer `RPG-REACTIVE-01` | Let a Model Source Package declare a passive/reactive subscription to a typed Signal, then execute all resolved subscribers in stable order inside the emitting Event transaction. | `core.signal-subscription-v1`; `game.combat.damage-resolved-signal-v1`; `game.effect.react@1`; `game.action.react@1` | packages own signal/handler contracts; model owns topology; RIR owns resolved table; runtime owns same-snapshot atomic delivery | `rpg.reactive.passive-v1` | `rpg.reactive.illegal-subscription-refused-v1`; `rpg.reactive.unbounded-cycle-refused-v1`; `rpg.reactive.order-boundary-v1` | authored/resolved subscriber ids, stable dispatch order, shared pre-event snapshot and commit/rollback trace |
| Tracer `RPG-EVIDENCE-01` | Finish the encounter and emit shared typed Metrics and evidence from the final committed snapshot. | `game.encounter.dynamic-waves-v1`; `game.encounter.advance@1`; `experiment.balance.metrics-v1`; `experiment.balance.observe@1` | encounter owns terminal condition; experiment owns Metric definition | `rpg.combat.cast-v1` | `rpg.metrics.missing-dimension-refused-v1` | Evaluation-run id, terminal snapshot, Metric dataset and assertion prerequisites |
| RPG `RPG-EFFECT-03` | Expire, remove, and dispel effects under declared legality and cleanup rules. | `game.effect.lifecycle-v1`; `game.effect.remove@1` | effect owns removal; runtime owns scheduled expiry/cancel | `rpg.effect.stack-immunity-v1` | `rpg.effect.illegal-dispel-outcome-v1` | removal cause, expiry event/cancel identity and remaining stacks |
| RPG `RPG-EFFECT-04` | Compute declared continuous/discrete contributions and transition effect state without hidden write ordering. | `game.effect.contribution-v1`; `game.effect.contribute@1`; `game.effect.transition@1` | effect owns contribution/transition law; receiving package owns reduced target slot; runtime owns one-final-write/reducer rule | `rpg.effect.contribution-transition-v1` | `rpg.effect.missing-reducer-refused-v1` | contributor order/identity, reducer result, old/new effect state and scheduled transition |
| RPG `RPG-BUILD-01` | Enforce build prerequisites, exclusions, slots and explicit synergy declarations. | `game.build.constraints-v1`; `game.build.select@1` | build owns selection; economy owns item possession | `rpg.build-progression-loot-v1` | `rpg.build.exclusion-outcome-v1` | accepted/rejected choice, prerequisite path and active synergies |
| RPG `RPG-PROGRESSION-01` | Award typed progression and emit all crossed unlocks in stable threshold order. | `game.progression.unlocks-v1`; `game.progression.award@1` | progression owns thresholds/unlocks; build may consume unlocks | `rpg.build-progression-loot-v1` | `rpg.progression.unlock-order-boundary-v1` | progression before/after and ordered unlock ids |
| RPG `RPG-LOOT-01` | Generate constrained loot, transfer it through inventory/economy, then validate build eligibility. | `game.generation.constrained-reward-v1`; `game.generation.draw@1`; `game.economy.transfer-v1`; `game.economy.transfer@1`; `game.build.select@1` | generation chooses; economy transfers; build equips/selects | `rpg.build-progression-loot-v1` | `rpg.loot.inventory-capacity-outcome-v1` | stream/draw, generated asset, transfer result and build result |
| Variant `RPG-TURN-SPATIAL-01` | When selected, optional turn/spatial packages compose without changing core logical-time phases or target-query rules. | `game.turn.windows-v1`; `game.turn.advance@1`; `game.spatial.queries-v1`; `game.spatial.query@1`; `game.query.select@1` | turn owns windows; spatial owns geometry; query owns final selection; runtime owns phases | `rpg.turn-spatial-target-v1` | `rpg.turn.hidden-phase-refused-v1` | phase key, turn/window id, spatial candidates and final target order |
| Roguelike `ROGUE-REWARD-01` | Draw seeded constrained rewards with rarity and guarantee behavior. | `game.generation.constrained-reward-v1`; `game.generation.draw@1` | generation owns draw/guarantee; build/economy consume result | `roguelike.reward-build-v1` | `roguelike.reward.guarantee-exhaustion-refused-v1` | stream/draw indexes, eligible pool, rarity and guarantee state |
| Roguelike `ROGUE-BUILD-01` | Apply run-time build conflicts and synergies to generated rewards. | `game.build.constraints-v1`; `game.build.select@1`; `game.generation.draw@1` | generation proposes; build admits/rejects; economy transfers admitted result | `roguelike.reward-build-v1` | `roguelike.build.conflict-outcome-v1` | conflict ids, synergy changes and disposition of rejected reward |
| Roguelike `ROGUE-ENCOUNTER-01` | Compose dynamic encounter/wave state with bounded deterministic spawning and terminal objectives. | `game.encounter.dynamic-waves-v1`; `game.encounter.advance@1`; `game.entity.spawn@1` | encounter owns schedule/objectives; entity owns spawned instances | `roguelike.encounter-waves-v1` | `roguelike.encounter.spawn-cap-refused-v1` | wave/objective trace, spawn order and terminal state |
| Roguelike `ROGUE-RESET-01` | Clear all Run-scoped state and retain only declared typed transfers into Meta scope. | `game.run.scope-reset-v1`; `game.run.reset@1` | packages declare slot scope; run owns teardown/retention transaction | `roguelike.run-reset-v1` | `roguelike.run.implicit-retention-refused-v1` | cleared Run-slot inventory, retained transfer list and post-reset snapshot |
| Roguelike `ROGUE-REPLAY-01` | Reproduce the same RIR outcomes, trace, Metrics and evidence under identical reproduction identities. | core replay contract; all operations exercised by the scenario | bundle/RIR/runtime/experiment identities jointly define replay | `roguelike.replay-v1` | `roguelike.replay.identity-mismatch-refused-v1` | reproduction key, ordered trace/Snapshot hashes, Metric/evidence identities |

## Golden scenario contracts

- `rpg.stat.composition-v1`: base and tunable typed symbols combine progression, equipment and
  effect contributions into a derived combat Quantity with explicit rounding/cap behavior.
- `rpg.combat.cast-v1`: a dynamic caster targets one enemy, reserves mana, resolves a named-stream
  hit/critical check, applies staged typed damage and an effect, exercises interruption, terminates
  the encounter, and emits Metrics/evidence through `experiment run`.
- `rpg.effect.stack-immunity-v1`: snapshot/live capture, immune target, stack cap, reapplication,
  expiry, dispel, and trace atomicity are exercised without action/combat owning effect lifecycle.
- `rpg.effect.contribution-transition-v1`: multiple typed contributions use a declared reducer and
  one effect-state transition schedules its next legal boundary without hidden write order.
- `rpg.resource.regeneration-cooldown-v1`: regeneration reaches a typed capacity boundary while an
  independent action cooldown blocks and later admits reuse.
- `rpg.combat.healing-v1`: staged typed healing exercises caps, reduction/amplification and explicit
  no-revival/revival policy.
- `rpg.reactive.passive-v1`: a model-authored passive subscribes to a typed combat Signal; multiple
  resolved subscribers prove stable order, same-snapshot visibility and atomic rollback behavior.
- `rpg.build-progression-loot-v1`: progression unlocks a build choice; constrained generation
  yields loot; economy transfers it; build validates prerequisites/exclusions/synergies.
- `rpg.turn-spatial-target-v1`: optional turn windows and spatial candidates feed the unchanged
  typed target-query operation while the scheduler retains the three core phases.
- `roguelike.reward-build-v1`: seeded rarity/guarantee generation composes with run-local build
  conflicts, synergies, and inventory transfer.
- `roguelike.encounter-waves-v1`: objectives advance bounded waves and dynamic spawns to a terminal
  encounter.
- `roguelike.run-reset-v1`: terminal run state is torn down and only declared typed rewards enter
  Meta scope.
- `roguelike.replay-v1`: the reward, encounter, and reset path runs twice under one reproduction
  key and produces byte-identical canonical observations.

## Closure rules

A row is `closed` only when all referenced package/operation ids exist in the admitted bundle, the
Golden and negative/boundary vector ids are in its vector inventory, and the public CLI artifacts
contain every required observable. A typed gameplay outcome may satisfy a negative vector when the
model explicitly declares that branch; invalid language/runtime conditions must use the bADR-0015
refusal path. A test that reaches private evaluator state or uses an unregistered helper does not
close the row.

Adding an ordinary game-specific attribute adds a nominal Quantity declaration or component field;
it changes neither the core type constructor set nor this matrix. A row changes only when a genre
support requirement or reusable mechanism changes. Adding that reusable mechanic requires a
versioned package capability/operation, rule semantics, diagnostics and vectors, then updates every
affected row. This is the extension test for consistency, orthogonality, and coverage.
