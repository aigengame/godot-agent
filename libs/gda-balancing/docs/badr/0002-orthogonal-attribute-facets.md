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

- **An attribute declaration is a composition of orthogonal facets.** Attribute
  declarations live in the `attributes` section's `items` — a **map keyed by attribute
  id** (declarations carry no separate `id` field; the map key is the single id
  authority). Each declaration independently composes:
  - **`domain`** — `number` | `percentage` | `probability` (the value space;
    `probability` implies [0,1]). A `percentage` value is expressed as a **fraction**
    (`0.3` = 30%, `1.5` = +150%) — one convention everywhere; the 0–100 scale never
    appears in a Design document.
  - **`base`** — exactly one of `direct` (a configured value) or `formula` (a named
    form or expression tree, bADR-0003). **The `base` is the single scalar authority
    for the attribute** — there is no separate `default` field; what a genre template
    ships as an attribute's "default" *is* the `direct` base value (or formula
    parameters) in the template instance.
  - **`accepts`** — a subset of `{allocation, effects}`: which contribution channels
    may add to the attribute — player allocation (with an allocation range when
    present), and/or effect modifiers (bADR-0006). Optional, **default `[]`** (a
    defined default per bADR-0005's round-trip contract): an attribute that declares
    nothing accepts nothing.
  - **`bounds`** — optional `floor`/`cap`, **mandatory when `domain` is `percentage`
    or `probability`** (an unbounded percentage is the classic balance failure; the
    obligation attaches to the domain, not to a tier). For `probability` the domain
    already pins the representable space to [0,1]; the mandatory bounds declare the
    *design* limits narrowing within it (e.g. a crit-chance cap of 0.5), never a
    restatement of the domain. Bound semantics are uniform: a declared bound clamps
    the attribute's final value (bADR-0003).
  - **`category`** — optional descriptive grouping label (resource / offensive /
    defensive / mobility, …) with no computational semantics.

- **One uniform value pipeline, with a fixed combine order.** For every attribute:
  `final = clamp( combine( base, allocation?, effect modifiers? ), bounds )`, where
  `combine` is normative:
  1. evaluate `base` (direct value, or formula per bADR-0003);
  2. add the allocation contribution (legal only on a `direct` base — cross-facet rule
     below);
  3. apply **continuous** effect modifiers in two stages (normative interaction in
     bADR-0006): stacking *selection* first (per stacking type — `stack` keeps every
     instance, `keep_best` keeps the strongest bonus and penalty per group), then
     operation *combination* — surviving `add` magnitudes sum, surviving `multiply`
     factors compose multiplicatively, a surviving `override` replaces the result;
  4. clamp to `bounds`.
  This pipeline defines the attribute's **definition-time final value**. Simulation
  seeds per-entity *current* values from it; **one-shot and periodic effect modifiers
  are deltas to those simulated current values** (bADR-0006) and never alter the
  declarations or this pipeline. **Per-instant composition:** the observed current
  value at any simulation instant is `clamp( P + L, bounds )`, where `P` — the
  pipeline component — is the pipeline value recomputed with the currently-active
  continuous modifiers **including the pipeline's own clamp** (so a continuous
  contribution alone can never carry `P` past a *declared* bound: `P ≤ cap` when a
  cap exists, `P ≥ floor` when a floor exists, unbounded on absent sides), and `L` is
  the accumulated delta ledger (bADR-0006's ledger equation uses this same clamped
  `P`). Continuous contributions are a recomputed component, deltas are a ledger; the
  evaluator realizing exactly this formula lands with the first simulation slice
  (#510, milestone #9 — vector ownership in bADR-0004).

- **Cross-facet rule (conservative default).** `accepts: allocation` is legal only with
  `base: direct` — allocation onto a formula-computed base is refused as a semantic
  rule. If template development surfaces a real allocation-onto-formula pattern,
  relaxing the rule is additive (a minor bump, bADR-0001).

- **Identifiers and namespaces.** Every id in a Design document matches
  `^[a-z][a-z0-9_]*$`. Ids are the **map keys** of their declaring collection —
  attributes (`items`), effects (bADR-0006), parameters (bADR-0003), stacking types
  (bADR-0006), and tier names each form one document-wide namespace. Uniqueness within
  a namespace is structural (map keys), backed by the funnel's preflight refusal of
  duplicate JSON keys (bADR-0004) so a lenient parser can never silently drop a
  duplicate declaration; the same id may legally appear in different namespaces
  (references are typed, bADR-0003). References (formula `attr`/`param` nodes, effect
  targets, tier assignments) resolve within the declaring document only — never across
  documents.

- **Tier compositions are declared data, with defined pattern satisfaction.** The
  `attributes` section carries two parts: `tiers` — an optional map of tier name →
  **facet pattern** — and `items` — the attribute declarations, each optionally labeled
  `tier: <name>`. A facet pattern may constrain any subset of `domain`, `base`, and
  `accepts`; **satisfaction is normative**: an omitted facet is unconstrained; `domain`
  matches by equality; `base` matches by declared *kind* (`direct` | `formula`);
  `accepts` matches by **exact set equality** (a pattern `{"accepts": ["allocation"]}`
  is satisfied only by attributes accepting exactly `{allocation}` — a tier that admits
  both channels writes both). A labeled attribute violating its tier's pattern is an
  element-level typed refusal. This is the data representation of "a tier is a named
  facet composition": genre templates ship their tier vocabulary as `tiers` entries,
  and the extension seam is adding or changing compositions — plain data, no schema
  fork.

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

- **Formula-reference acyclicity is defined over base formulas only.** The dependency
  graph's nodes are the declared attributes; there is an edge A → B iff A's **base
  formula** references B (`attr` nodes, bADR-0003; parameters are constants and add no
  edges). That graph must be acyclic — an element-level semantic rule at the boundary
  funnel (bADR-0004), as are the cross-facet rules (allocation legality, bounds
  obligation by domain, tier-pattern satisfaction). **Effect magnitudes are exempt from
  the static graph**: they evaluate against snapshots (bADR-0006), so a magnitude may
  reference its own target — the read observes the pre-instant state, never the value
  being written.
- The facet model is the core the designed and reserved sections build on: `effects`
  modifiers target attributes (bADR-0006); `builds` pools offer effects (#506);
  `combat` consumes attribute values (#520).
- Genre templates (#505, #506) declare their tier vocabulary as named compositions in
  template data; template development is the verification point for the reserved
  hypothesis.
