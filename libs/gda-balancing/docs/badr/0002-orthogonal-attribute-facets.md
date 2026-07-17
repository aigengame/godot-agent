---
status: accepted
---

# Orthogonal attribute facets; tiers are template compositions, not schema law

The Standard Schema needs an attribute model that serves both long-progression RPGs
(which layer attributes two or three deep to control growth) and Roguelikes (which
flatten to one or two layers) without forcing dead structure on either. A fixed tier
taxonomy fails that bar: it bundles independent properties — allocatability, formula
derivation, boundedness, value domain — into closed packages, so a genre that doesn't
use a package inherits it anyway (maintainer review on PR #521). This bADR fixes the
attribute model for the `attributes` section (PRD #501 US2–US4; design gate #503),
superseding the fixed primary/derived/modifier taxonomy of its earlier draft.

## Decision

- **An attribute declaration is a composition of orthogonal facets.** Every attribute
  carries `id`, `default`, and independently composes:
  - **`domain`** — `number` | `percentage` | `probability` (the value space;
    `probability` implies [0,1]).
  - **`base`** — exactly one of `direct` (a configured value) or `formula` (a named
    form or expression tree, bADR-0003). How the base value is determined.
  - **`accepts`** — a subset of `{allocation, effects}`: which contribution channels
    may add to the attribute — player allocation (with an allocation range when
    present), and/or effect modifiers (bADR-0006).
  - **`bounds`** — optional `floor`/`cap`, **mandatory when `domain` is `percentage`
    or `probability`** (an unbounded percentage is the classic balance failure; the
    obligation attaches to the domain, not to a tier). For `probability` the domain
    already pins the representable space to [0,1]; the mandatory bounds declare the
    *design* limits narrowing within it (e.g. a crit-chance cap of 0.5), never a
    restatement of the domain. Bound semantics are uniform: a declared bound clamps
    the attribute's final value (bADR-0003).
  - **`category`** — optional descriptive grouping label (resource / offensive /
    defensive / mobility, …) with no computational semantics.

- **One uniform value pipeline.** For every attribute:
  `final = clamp( combine( base, allocation?, effect modifiers? ), bounds )`.
  The combine order and per-channel semantics (allocation adds to a direct base;
  effect modifiers apply per their operation and stacking policy, bADR-0006) are fixed
  as semantic rules in #504 — never left to implementations.

- **Cross-facet rule (conservative default).** `accepts: allocation` is legal only with
  `base: direct` — allocation onto a formula-computed base is refused as a semantic
  rule. If template development surfaces a real allocation-onto-formula pattern,
  relaxing the rule is additive (a minor bump, bADR-0001).

- **A tier is template vocabulary, not schema law.** A `tier` is a *named facet
  composition a genre template groups its attributes by*. The Schema enforces facet
  validity; it does not require any tier taxonomy to exist. The PRD's layered-attribute
  requirement is satisfied by composition:

  | Template concept | Facet composition |
  |---|---|
  | RPG "primary" (STR, AGI, VIT…) | `number` · `base: direct` · `accepts: {allocation, effects}` |
  | RPG "derived" (HP, ATK, move speed…) | `number` · `base: formula` · `accepts: {effects}` · optional cap |
  | RPG "tertiary" (crit%, CDR…) | `percentage`/`probability` · `base: direct` or `formula` · `accepts: {effects}` · mandatory bounds |
  | Roguelike flat stat (HP, DMG) | `number` · `base: direct` · `accepts: {effects}` — one layer, no dead tiers |

  An RPG template composes three named layers; a survivors-like composes one or two.
  No composition is mandatory; a directly-configured stat that *shapes like* a derived
  stat is simply `base: direct` — the single-layer Roguelike case that a fixed
  taxonomy could not express.

- **Attributes are data, not vocabulary.** The Schema defines the facet mechanism; the
  concrete attribute set is document/template data. The toolkit hardcodes no attribute
  names — game-agnosticism is structural.

- **Reserved hypothesis (registered, not asserted).** That facet composition suffices
  for the covered genre families without model forks is a hypothesis, verified against
  template development feedback (#505, #506). Fork pressure is watched along both
  dimensions — within a composition and between compositions — and the named-composition
  mechanism is itself the extension seam if a fork proves necessary.

- **Provenance note.** The facet ingredients are multi-party attested (#503 research):
  allocatable-base vs derived-value separation in tabletop d20 (lookup-table derivation,
  recomputed on base change) and in Godot community practice (base vs derived
  attributes); curve-typed stat values in Unity community practice; bounded modifier
  domains across RPG convention. Unreal GAS's base/current value pair is a *runtime*
  state layering — adjacent precedent, digested not copied: this bADR models
  definition-time declarations, and the runtime distinction maps onto base vs
  effect-modified final value.

## Considered options

- **Orthogonal facets, tiers as template compositions** (chosen) — RPG layering and
  Roguelike flatness are both plain compositions; no dead tiers; extension happens by
  new compositions, not new taxonomies.
- **Fixed three-tier taxonomy** (the superseded earlier draft of this bADR; rejected on
  review) — bundles orthogonal properties; "primary" misnames genres that lack
  allocatable stats; "derived is never directly configured" contradicts single-layer
  Roguelike practice.
- **Genre-forked attribute models** (rejected as the *starting* point) — turns genre
  templates into code paths (PRD: templates are data); revisited only if the reserved
  hypothesis above fails.
- **Fixed attribute vocabulary in the toolkit** (rejected) — a fixed field set rots the
  moment one consumer needs a field the vocabulary lacks; agnosticism must be
  structural.

## Consequences

- Formula-reference acyclicity (any `formula` base referencing attributes, bADR-0003;
  any effect magnitude referencing attributes, bADR-0006) is an element-level semantic
  rule at the boundary funnel (bADR-0004), as are the cross-facet rules (allocation
  legality, bounds obligation by domain).
- The facet model is the core the designed and reserved sections build on: `effects`
  modifiers target attributes (bADR-0006); `builds` pools offer effects (#506);
  `combat` consumes attribute values (#520).
- Genre templates (#505, #506) declare their tier vocabulary as named compositions in
  template data; template development is the verification point for the reserved
  hypothesis.
