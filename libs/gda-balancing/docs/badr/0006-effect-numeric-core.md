---
status: proposed
---

# Effects are first-class: the numeric core of buffs, debuffs, and over-time influence

A modifier is not a bounded correction coefficient — it is the numerical core of a
buff/debuff, status effect, or over-time effect: a feature with magnitude, duration,
periodic ticks, and cross-effect interplay (maintainer review on PR #521). Builds offer
them, combat applies them, and balance simulation must consume their numbers from the
Design document — so their numeric core belongs to the Schema core, not to a reserved
section. This bADR fixes that core (PRD #501 US2/US5; design gate #503) and separates
two concepts an earlier draft conflated: an **attribute** is a stat (bADR-0002); an
**effect** is a time-scoped numeric influence on attributes.

## Decision

- **Effect and Modifier are first-class schema citizens.** An **Effect** is a declared,
  time-scoped carrier of numeric influence. A **Modifier** is one numeric operation
  inside an effect. **The v1 shape is normative here** (ids per bADR-0002's namespace
  rules; the `effects` section holds `stacking_types` and `items`, and `items` is a
  **map keyed by effect id** — declarations carry no separate `id` field, the key is
  the single id authority):

  - `modifiers`: a list of `{ target: <attribute id>, operation: add | multiply |
    override, application: continuous | one_shot | periodic, magnitude: <value | named
    form | expression tree> }` (`one_shot` names the apply-once delta so it can never
    be confused with the `instant` *duration*)
  - `duration`: `instant` | `timed` (with a duration in seconds) | `infinite`
  - `period`: tick interval in seconds. **Required** when any modifier declares
    `application: periodic` (its magnitude is the per-tick amount); **permitted** when
    any modifier is `continuous` (opting that effect's continuous magnitudes into
    per-tick re-evaluation); **forbidden** when every modifier is `one_shot` (nothing
    ticks) — each an element-level semantic rule
  - `stacking`: `{ type: <stacking-type id>, lifetime: independent | refresh }` —
    required for `timed`/`infinite` effects, **forbidden on `duration: instant`**
    (an instant effect leaves no persistent instance to stack or refresh)
  - **Temporal validity (element-level semantic rules):** a `timed` duration and any
    `period` must be positive and finite; `period ≥ 0.05` seconds (v1 minimum
    granularity); for **any `timed` effect declaring `period`** — whether its ticks
    drive `periodic` deltas or `continuous` re-evaluation — `duration / period ≤
    10 000`: the per-instance tick budget is bounded at the funnel, not discovered in
    simulation. (Infinite effects with a `period` are bounded by the simulation
    horizon, a Phase-2 parameter — the per-horizon tick count inherits the same
    budget.)

- **Three application values, two state models — never mixed.**
  - A **continuous** modifier contributes to its target's computed final value for as
    long as the effect is active, through the uniform value pipeline (bADR-0002); when
    the effect ends, the contribution ends.
  - A **one_shot** or **periodic** modifier is a **delta applied to the simulated
    current value** of its target (the per-entity state simulation seeds from the
    pipeline's definition-time value) — damage, healing, resource drain. Deltas never
    alter declarations and never flow through the pipeline. `override` is illegal on
    one_shot/periodic modifiers (element-level refusal): replacing a current value is a
    set, not a delta, and belongs to no v1 use case.
  - **Multiplicative deltas lower to additive realized deltas at the event snapshot.**
    The delta ledger (bADR-0002) is additive; a `multiply` delta realizes as
    `snapshot observed value × (magnitude − 1)` — evaluated against the same
    pre-instant snapshot as its magnitude — and that realized amount is written through
    the ordered, per-delta-clamped ledger like any `add`. An event's effect is fixed at
    its instant: later pipeline changes never retroactively re-scale already-applied
    deltas (a separate multiplicative ledger, which would re-scale history, is
    rejected).
  - **Saturation is persisted — the ledger-update equation is normative.** With `P` =
    the pipeline component at the write instant (**constant across all writes of one
    instant** — the pipeline recomputes only against the pre-instant snapshot, so no
    same-instant write can change it), `L` = the ledger value before the write, and
    `d` = the realized delta, each ordered write updates the ledger as
    `L ← clamp(P + L + d, bounds) − P`. The persisted state after a bound-crossing
    write is the **saturated effective change**: overflow past a cap or floor is lost
    at write time, never banked — a later pipeline change re-exposes no clipped
    remainder (the alternative, storing the full realized delta and clamping only the
    observed value, is rejected: it silently banks invisible overflow).
  - **Application × duration legality (element-level semantic rule):** a
    `duration: instant` effect admits only `one_shot` modifiers; `continuous` and
    `periodic` modifiers require `duration: timed | infinite`; `one_shot` modifiers are
    legal on any duration (they apply once, at application).

- **Deterministic temporal semantics.**
  - **Evaluation moments.** A `one_shot` magnitude evaluates once, at application. A
    `periodic` magnitude evaluates at each tick boundary. A `continuous` magnitude
    evaluates **once at application and holds constant** while the effect is active —
    unless its effect declares a `period`, in which case it re-evaluates at each tick
    boundary. There is no implicit tick: no `period`, no re-evaluation.
  - **Snapshot-consistent instants.** All magnitudes evaluated at one instant read a
    **common pre-instant snapshot** of attribute state — a read never observes a write
    made in the same instant. The **stable order** (application time, then effect id,
    then modifier position within the effect) governs only the sequence of *writes*:
    one_shot/periodic deltas apply to the simulated current value in stable order,
    **clamping to the target's bounds after each delta** (bounded pools never
    transiently escape their bounds).
  - **Boundaries.** An effect declaring `period` has its first tick one full `period`
    after application; a `timed` effect's modifiers cease exactly at expiry (no
    partial final tick), and **a tick due exactly at expiry does not fire** — expiry
    (phase 1) precedes writes (phase 4), so a timed effect with
    `duration = N × period` fires `N − 1` ticks (V15).
  - **Instant phase order (normative).** Within one simulation instant, four phases
    run in fixed order: **(1) expiry** — effects ending at this instant deactivate and
    their continuous contributions leave the active set; **(2) activation** — effects
    applied at this instant activate; their continuous magnitudes evaluate against the
    pre-instant snapshot and join the active set; **(3) pipeline recomputation**, in a
    fixed suborder: **(3a)** active continuous magnitudes whose effect declares a
    `period` with a tick boundary at this instant re-evaluate against the pre-instant
    snapshot; **(3b)** stacking selection runs over the **updated** magnitudes;
    **(3c)** operation combination and the pipeline clamp produce this instant's `P`
    (selection judges current magnitudes — a survivor is never chosen on a stale
    value; V17 discriminates); **(4) delta writes** — one_shot deltas and
    periodic-delta ticks due at this instant apply in the stable order through the
    ledger equation, all against this phase-3 `P`. Consequence: an effect carrying both a continuous and a
    one_shot modifier activates its continuous contribution **before** its delta
    writes — the delta lands on the already-buffed pipeline — and expiry alone never
    touches the ledger (V14 discriminates this from the rejected write-first order).
  These rules make interacting-effect vectors reproducible; encounter-level scheduling
  (who applies what when) remains #520's design.

- **Stacking types are a single-authority catalog.** The `effects` section declares a
  document-level `stacking_types` map: stacking-type id → `{ aggregation: stack |
  keep_best }`. Each **persistent** (`timed`/`infinite`) effect references exactly one
  declared stacking type (`instant` effects declare none — the scope rule above);
  referencing an undeclared type is a typed refusal. Same-type resolution is therefore
  defined **once per type** — two effects can never assign conflicting rules to one
  type.

- **Stacking selection precedes operation combination — two stages, never one.** This
  is the normative interaction between the stacking catalog and the value pipeline's
  step 3 (bADR-0002). Stacking operates on **persistent effect instances**
  (`timed`/`infinite`); modifiers from every effect participate in the *global*
  grouping below — an effect's own modifier list has no private combination order.
  1. **Selection.** Active continuous modifiers are grouped by (stacking type, target
     attribute, operation). `stack` keeps every instance. `keep_best` keeps, per group,
     the strongest bonus **and** the strongest penalty — for `add`, the largest
     positive and the most negative magnitude; for `multiply`, the factor furthest
     above 1 and the factor furthest below 1; for `override`, the latest-applied
     instance by the stable order. (The per-type keep-best-bonus/worst-penalty rule is
     the verified tabletop precedent.)
  2. **Combination.** Survivors combine by operation: `add` magnitudes sum, `multiply`
     factors compose multiplicatively; if overrides from **different** stacking types
     survive selection, the **latest-applied by the stable order** wins globally and
     replaces the result.
  "Stacking policy" names stage 1's per-type selection only — the operation order of
  stage 2 is the pipeline's, not the stacking type's.
  - **Delta-emitting instances stack too:** for `periodic` modifiers, selection applies
    at the instance level per (stacking type, target, operation) — under `keep_best`
    only the instance with the largest-magnitude per-tick delta (evaluated at its own
    application snapshot; largest bonus and harshest penalty each survive) emits ticks;
    under `stack`, all instances emit. **`one_shot` deltas are never subject to
    stacking selection**: they apply exactly once, at application, whatever the
    effect's duration — an already-applied delta cannot be retroactively unselected.

- **Aggregation and lifetime are orthogonal**: `aggregation` (on the type) governs
  stage-1 selection; `lifetime` (on the effect) governs what a re-application does to
  the effect's own remaining duration (`independent` instances vs `refresh`).
  Precedent, provenance-labeled (#503 research): tabletop d20 declares stacking per
  named bonus type (~18 types, same-type keep-best, per-type exceptions) as rule
  *data*; Unity community practice separates additive from multiplicative passes and
  ships modifiers as data assets carrying their operation.

- **Magnitudes are formula-capable** (bADR-0003): per-second benefits or penalties are
  `period` plus a formula magnitude; a magnitude may reference attributes and declared
  parameters, so interplay through shared targets (one effect scaling with a stat
  another effect raised) is expressible now under the snapshot rule. Richer synergy
  composition — explicit effect-to-effect terms — is a **named extension point**,
  reserved rather than designed, expected to land with `builds` (#506) evidence.

- **Operation and duration vocabulary follows verified engine practice**: modifier
  operations add/multiply/override, and the three effect durations
  (instant / timed / infinite) plus periodic application, are the shapes attested in
  the #503 research (engine framework provenance). What that framework computes in
  code — arbitrary multi-attribute magnitudes — this Schema expresses as formula
  magnitudes, per bADR-0003's recorded deviation.

- **Boundary against the reserved sections.** This bADR owns only the numeric core.
  Which effects a build pool offers, pool sizes, and selection pressure belong to
  `builds` (#506); when combat applies effects and how encounters schedule them belong
  to `combat`/`encounters` (#520). Those sections *reference* effect ids; they do not
  redefine effect numerics.

- **Envelope change.** `effects` joins `attributes` as a designed v1 top-level section
  (alongside the required `meta` key; bADR-0001 amended accordingly). The section holds
  `stacking_types` and `items` (the effect declarations).

## Considered options

- **Effects as first-class citizens beside attributes** (chosen) — simulation consumes
  effect numbers directly from the document; builds/combat compose by reference.
- **Modifier as an attribute tier** (the superseded earlier framing; rejected on
  review) — narrows a feature to a bounded coefficient and leaves buff/debuff numerics,
  durations, and ticks with no home in the core.
- **Per-effect stacking rules** (rejected) — lets two effects assign conflicting rules
  to one stacking type; the type catalog is the single authority, matching the
  per-type precedent.
- **One `rule` field mixing aggregation and lifetime** (rejected) — `refresh` is not an
  alternative to `stack`/`keep_best`; conflating them makes common combinations
  (keep-best magnitude + refreshed duration) inexpressible.
- **Effects deferred wholesale to `builds` (#506)** (rejected) — build pools are one
  *acquirer* of effects; combat and encounters apply them too. Parking the numeric core
  in one consumer's section would couple the others to it.
- **Full synergy algebra now** (deferred) — explicit effect-to-effect composition terms
  need template and build-pool evidence; designing them speculatively violates the
  known-requirements bar. The extension point is named instead.

## Consequences

- #504 implements effect **validation** — target integrity (every modifier's `target`
  names a declared attribute), stacking-type reference integrity,
  `period`/`application` consistency, the `override`-on-delta refusal, and magnitude
  formula rules (bADR-0003). The **evaluator contract** — the continuous-modifier arm
  of the value pipeline (bADR-0002), the snapshot/ordering semantics, the instant
  phase order, and the ledger equation — is implemented by the first simulation slice
  (#510, milestone #9), which executes the runtime vectors (bADR-0004's ownership
  split); the Phase-2 design gate (#509) treats those semantics as fixed contract.
- Formulas gain a second consumer class (magnitudes) beyond attribute bases — recorded
  in bADR-0003.
- The `builds` section design (#506) starts from effect references plus the
  stacking-type catalog this bADR fixes, rather than inventing its own modifier
  concept.
