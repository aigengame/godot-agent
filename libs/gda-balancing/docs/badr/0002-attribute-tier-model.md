---
status: accepted
---

# Uniform three-tier attribute model, declared as data

The Standard Schema needs an attribute model expressive enough for layered RPG stat
systems and flat Roguelike survival stats without forking per genre. The demo's model is
the cautionary baseline: a flat symmetric `StatBlock {max_hp, max_mp, attack, defense}`
with no tiers, no derivation, and a fixed field vocabulary that let one game's mechanics
(the warp kit, time fields) leak into the "generic" model. This bADR fixes the tier
model for the `attributes` section (PRD #501 US2–US4; design gate #503).

## Decision

- **Three tiers, one uniform model.** Every attribute declaration names its
  `Attribute tier`:
  - **primary** — directly allocatable by the player; defines growth direction
    (precedent, tabletop: d20 ability scores; e.g. STR, AGI, VIT, INT).
  - **derived** — never directly allocatable; computed from primaries, level, and named
    parameters via a formula-as-data (bADR-0003) (precedent, tabletop: d20 derived
    values recompute automatically when the base score changes, via a published lookup
    table; multi-engine: the Godot Gameplay Attributes addon separates base attributes
    from derived attributes computed from other attributes; e.g. HP, physical attack,
    defense, move speed).
  - **modifier** — a percentage or probability correction applied to outcomes, with
    **mandatory bounds** (e.g. hit chance, crit chance, cooldown reduction). An unbounded
    percentage is the classic balance failure; the Schema makes the cap a declaration
    obligation, not a designer's memory (bounds are first-class fields — a recorded
    deviation from engine practice, adjudicated in bADR-0003).

- **Provenance note on the layering precedent.** The primary/derived split is attested
  across tabletop (d20 lookup tables), Godot community practice (base/derived
  attributes), and Unity community practice (ScriptableObject stat definitions with
  curve-typed values); modifiers-as-data is attested in Unreal GAS (modifier operations),
  Unity community (modifier data assets with add/subtract/multiply/divide operators), and
  d20 (per-type stacking metadata). Unreal GAS's own two-value layering (Base value vs
  Current value under active effects) is a **runtime state** layering — an adjacent
  precedent for permanent-vs-temporary values, deliberately *not* the same thing as this
  bADR's definition-time tiers; it is digested, not copied (#503 research, both
  comments).

- **Attributes are data, not vocabulary.** The Standard Schema defines the tier
  *mechanism*; the concrete attribute set is document/template data. The toolkit
  hardcodes **no** attribute names — game-agnosticism is structural (contrast the demo's
  fixed `StatBlock` fields and its warp-kit intrusion, gADR-0018's documented generality
  failure).

- **Per-tier declaration obligations.** Every attribute carries `id`, `tier`, and
  `default`. Per tier:
  - **primary** — may declare an allocation range (`min`/`max`); never carries a
    formula.
  - **derived** — must reference its formula (bADR-0003); may declare `cap`/`floor`
    clamping its computed result (e.g. a move-speed cap).
  - **modifier** — must declare bounds (`cap`, `floor`) and its domain (percentage vs
    probability); may reference a formula computing its base from primary/derived
    attributes (e.g. hit chance from AGI vs target evasion); contributions from modifier
    sources (equipment, buffs, build picks — pool mechanics owned by #506) apply within
    the declared bounds.
  - Bound semantics are uniform across tiers: a declared `cap`/`floor` clamps the
    attribute's final value (bADR-0003).

- **Genres are subsets, not forks.** A Roguelike's "few flat survival attributes" are
  primary-tier attributes with no derivation chain (a directly-set HP is simply primary);
  its "large randomized modifier pools" contribute to modifier-tier attributes — the pool
  mechanics themselves are the `builds` section's design (#506). One model; genre
  templates (#505, #506) express genre identity purely in data (PRD: genre templates are
  data, never code paths).

- **Categories are metadata.** Conventional groupings (resource / offensive / defensive /
  mobility) are an optional descriptive `category` field with no computational semantics
  — useful for reports and templates, never load-bearing.

## Considered options

- **Uniform three-tier model** (chosen) — covers the RPG layering (US2) and the Roguelike
  flat + pools shape (US4) as subsets of one mechanism.
- **Genre-forked attribute models** (rejected) — turns genre templates into code paths;
  contradicts PRD's "templates are data".
- **Two tiers (fold modifier into derived)** (rejected) — modifier-tier obligations are
  distinct in kind: bounded domains ([0,1] probabilities, capped percentages) and
  outcome-correction semantics; folding them makes caps optional-by-accident.
- **Fixed attribute vocabulary in the toolkit** (rejected) — the demo's approach;
  guarantees the next warp-kit-style leak the moment one consumer needs a field the
  vocabulary lacks.

## Consequences

- Cross-attribute references (derived ← primary, modifier ← primary/derived) must form an
  acyclic graph — an element-level semantic rule at the boundary funnel (bADR-0004).
- The tier model is the core the reserved sections build on: `builds` pools reference
  modifier attributes; `combat` consumes derived attributes (#520, #506).
- Forward research input for #506 (builds/modifier pools), recorded here so it is not
  lost — descriptive only, nothing is decided for that section here: d20 declares
  **stacking policy as per-type metadata** (~18 named bonus types, same-type resolves
  keep-best, per-type exceptions), and Unity community practice separates flat (additive)
  from percentage (multiplicative) modifier passes.
- "Attribute tier" (and the collision warning: the demo used *tier* for enemy difficulty
  classes — minion/elite/boss; the balancing domain reserves *tier* for attribute
  layering) enters the glossary.
