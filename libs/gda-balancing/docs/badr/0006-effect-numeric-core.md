---
status: accepted
---

# Effects are first-class: the numeric core of buffs, debuffs, and over-time influence

A modifier is not a bounded correction coefficient — it is the numerical core of a
buff/debuff, status effect, or over-time effect: a feature with magnitude, duration,
periodic ticks, and cross-effect interplay (maintainer review on PR #521). Builds offer
them, combat applies them, and balance simulation must consume their numbers from the
Design document — so their numeric core belongs to the Schema core, not to a reserved
section. This bADR fixes that core (PRD #501 US2/US5; design gate #503) and separates
two concepts the earlier draft conflated: an **attribute** is a stat (bADR-0002); an
**effect** is a time-scoped numeric influence on attributes.

## Decision

- **Effect and Modifier are first-class schema citizens.** An **Effect** is a declared,
  time-scoped carrier of numeric influence. A **Modifier** is one numeric operation
  inside an effect. Design-level shape (field details fixed in #504):

  - `id`
  - `modifiers`: a list of `{ target: <attribute id>, operation: add | multiply |
    override, magnitude: <value | named form | expression tree> }`
  - `duration`: `instant` | `timed` (with a duration) | `infinite`
  - `period`: optional tick interval — a periodic (over-time) effect applies its
    modifiers per tick; `magnitude` is then the per-tick amount
  - `stacking`: `{ type: <named stacking type>, rule: <same-type resolution> }`

- **Magnitudes are formula-capable** (bADR-0003): per-second benefits or penalties are
  `period` plus a formula magnitude; a magnitude may reference attributes and named
  parameters, so interplay through shared targets (one effect scaling with a stat
  another effect raised) is expressible now. Richer synergy composition — explicit
  effect-to-effect terms — is a **named extension point**, reserved rather than
  designed, expected to land with `builds` (#506) evidence.

- **Stacking policy is per-type declared data, never formula logic.** Every effect
  names its stacking `type`; same-type resolution is a declared `rule`. The v1 rule
  vocabulary (`stack`, `keep_best`, `refresh`, …) is fixed in #504 from what the genre
  templates need. Precedent, provenance-labeled (#503 research): tabletop d20 declares
  stacking per named bonus type (~18 types, same-type keep-best, per-type exceptions)
  as rule *data*; Unity community practice separates additive from multiplicative
  modifier passes and ships modifiers as data assets carrying their operation.

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
  (alongside the required `meta` key; bADR-0001 amended accordingly).

## Considered options

- **Effects as first-class citizens beside attributes** (chosen) — simulation consumes
  effect numbers directly from the document; builds/combat compose by reference.
- **Modifier as an attribute tier** (the superseded earlier framing; rejected on
  review) — narrows a feature to a bounded coefficient and leaves buff/debuff numerics,
  durations, and ticks with no home in the core.
- **Effects deferred wholesale to `builds` (#506)** (rejected) — build pools are one
  *acquirer* of effects; combat and encounters apply them too. Parking the numeric core
  in one consumer's section would couple the others to it.
- **Full synergy algebra now** (deferred) — explicit effect-to-effect composition terms
  need template and build-pool evidence; designing them speculatively violates the
  known-requirements bar. The extension point is named instead.

## Consequences

- #504 implements effect validation (target integrity: every modifier's `target` names
  a declared attribute; magnitude formula rules per bADR-0003; duration/period and
  stacking-declaration validity per bADR-0004's rule list) and the combine step of the
  attribute value pipeline (bADR-0002) that applies effect modifiers per operation and
  stacking policy.
- Formulas gain a second consumer class (magnitudes) beyond attribute bases — recorded
  in bADR-0003.
- The `builds` section design (#506) starts from effect references plus the per-type
  stacking data this bADR fixes, rather than inventing its own modifier concept.
