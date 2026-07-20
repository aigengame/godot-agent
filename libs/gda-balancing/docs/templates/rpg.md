# The RPG family Genre template

The `rpg` Genre template (`template get rpg`) is the RPG family's numeric design
baseline: an instance of the Standard Schema you instantiate and adjust, never a code
path (bADR-0002/0012). This document explains its tier vocabulary, defaults, and
formulas, with provenance; the packaged JSON is the numeric authority — this page
explains, never redefines.

**Provenance method (non-normative).** Every default below is labeled either
**consensus** — attested by at least two independent recognized sources (published
SRD/OGL system references, game-design literature, established design writeups of
major titles) — or **judgment call** — a deliberate choice where the industry
genuinely disagrees or the evidence is thin, with the disagreement stated rather than
averaged away. No single game, engine, or framework is treated as "the industry
standard". Sources name systems, not vendors-as-authorities.

## Tier vocabulary (named facet compositions, bADR-0002)

| Tier | Facet pattern | Meaning |
|---|---|---|
| `primary` | `number` · `direct` · exactly `{allocation, effects}` | Directly allocatable base stats |
| `derived` | `number` · `formula` · exactly `{effects}` | Computed from primaries/progression; never allocated |
| `tertiary` | any domain/base · exactly `{effects}` | Bounded rates — percentage/probability attributes carry **mandatory caps** (the bounds obligation attaches to the domain, bADR-0002) |

`level`, `experience_to_next_level`, and `movement_speed` deliberately carry no tier
label: tier labels are optional per attribute, and these follow conventions the three
compositions don't express (see below).

## Primary stats

`strength`, `dexterity`, `vitality`, `intelligence` — each `direct: 10`, allocatable.

- **Strength** — physical power. **Consensus**: universal across all 14 systems
  surveyed (D&D 5e SRD, Pathfinder, GURPS, Fallout SPECIAL, Elder Scrolls, WoW,
  Diablo II/III, Path of Exile, Dark Souls, WFRP, Fantasy AGE, …).
- **Dexterity** — finesse. **Consensus name choice**: 9/14 systems and the broadest
  cross-genre spread (tabletop SRDs *and* Diablo II/III, PoE, Dark Souls); the
  alternative *Agility* (6/14) concentrates in open-world CRPG/MMO lineages
  (Fallout, Elder Scrolls, WoW).
- **Intelligence** — mental/magic power. **Consensus**: 13/14 systems; the
  alternative *Intellect* is WoW-only. *Wisdom*, despite the D&D "big six", does not
  generalize (2/14, D&D lineage only) and is omitted from the family baseline.
- **Vitality** — toughness. **Judgment call**: the toughness slot has no name
  consensus (Vitality 4 — Diablo II/III, Dark Souls; Constitution 3 — D&D,
  Pathfinder, Fantasy AGE; Endurance 3). Vitality is chosen for its semantic
  directness (vitality → life) and action-RPG recognizability; Constitution is the
  tabletop-leaning alternative a game may rename to.
- Base value 10: **consensus** center of creation ranges (GURPS attributes start at
  10; D&D point-buy range 8–15 centers near 10).

Point-buy conventions (budget 27, per-stat 8–15, after D&D 5e as the most-mirrored
scheme) are **fixture-level parameters**, not template law — budget size is a
documented tuning knob (Fallout's SPECIAL pool shifted 40 → 28 across the franchise).
The CRPG Reference fixture exercises them.

## Progression

- `level` — an ordinary `direct` attribute formulas reference (bADR-0003's sanctioned
  progression variable). Untiered: progression is neither allocated nor buffed here.
- `experience_to_next_level` — `polynomial` on `level`, coefficients `[0, 50, 50]`
  (i.e. `50·L + 50·L²`, the triangular-number family scaled ×100). **Shape is
  consensus**: the recognized authority (Ian Schreiber, *Game Balance Concepts*)
  classifies RPG level-up cost curves as triangular/quadratic, and the D&D 5e and
  Pathfinder XP tables decelerate in ratio exactly as a quadratic does — while
  calling true constant-ratio exponential curves "rare in balanced games". The
  coefficients are literals by schema law (collection elements are non-knobs,
  bADR-0003): re-shape the curve by editing the polynomial, not by tuning.

## Derived stats

All `linear` named forms; every coefficient is a `parameters` entry — the template's
tuning knobs (bADR-0003: parameters are the sole knobs, literals are deliberate
non-knobs).

| Attribute | Default formula | Shape status | Coefficient status |
|---|---|---|---|
| `health` (resource) | `health_base(100) + health_per_vitality(10)·vitality` | **Consensus** — base + k·toughness recurs across Diablo II/III, PoE, WoW Classic, GURPS | Judgment: per-game spread is huge (0.5–100/pt); 10/pt matches the WoW-Classic / early-Diablo-III scale |
| `mana` (resource) | `mana_base(50) + mana_per_intelligence(15)·intelligence` | Consensus shape (mirrors health) | 15/pt attested (WoW Classic: 1 INT = 15 mana); base is a scale knob. The D&D lineage's spell-slot lookup table is the attested alternative to a mana pool |
| `attack_power` (offensive) | `attack_power_base(10) + attack_power_per_strength(2)·strength` | Attested (two patterns exist: decoupled attack power vs direct %-damage) | 2/pt attested (WoW Classic: 1 STR = 2 AP) |
| `armor` (defensive) | `armor_base(5) + armor_per_dexterity(2)·dexterity` | Attested (Diablo II defense rating scales from Dexterity) | Judgment: coefficient is a scale knob |
| `initiative` (mobility) | `initiative_per_dexterity(1)·dexterity` | **Consensus** — finesse-derived action order (D&D 5e initiative is the Dexterity check; JRPG Speed/Agility governs turn order) | 1/pt is the D&D-modifier-style identity choice |

## Tertiary stats (bounded rates)

The Standard Schema **mandates** bounds on every percentage/probability attribute (an
unbounded percentage is the classic balance failure, bADR-0002) — so even where the
industry leaves a magnitude open, the template must cap it; such caps are flagged.

| Attribute | Base | Cap | Status |
|---|---|---|---|
| `damage_reduction` | `armor / (armor + armor_pivot(100))` | 0.75 | **Shape consensus**: the diminishing rational curve `Armor/(Armor+K)` recurs across two unrelated franchises (Diablo III, WoW); the 75% ceiling is WoW's own DR cap and matches the resistance-cap convention. `armor_pivot` sets the 50%-reduction breakpoint — a tuning knob. Expressed as an expression tree: no named form fits a rational curve (bADR-0003's sanctioned fallback). Attested alternatives a game may adopt instead: roll-target armor class (D&D lineage) and flat-subtractive reduction |
| `elemental_resistance` | 0 | 0.75 | **Consensus cap**: 75% dominant across PoE, Diablo II, Last Epoch (Grim Dawn's 80% is the outlier); raised hard caps (~90–95%) are the attested extension mechanism |
| `crit_chance` | 0.05 | 1.0 | **Base consensus**: ~5% across D&D 5e (natural 20), WoW, Diablo III, PoE. Cap is a judgment call between two attested philosophies: a 100% hard cap (PoE) — chosen as the neutral default — vs per-class soft caps (Diablo III, 56–60%) |
| `crit_damage` | 0.5 (+50%) | 3.0 | **Contested base**: +50% (PoE, Diablo III) vs +100% (D&D 5e double dice, WoW melee); +50% chosen as the conservative camp. The cap is **schema-mandated**: the industry pattern is "chance bounded, magnitude open", so 3.0 is a deliberately generous bound, not an attested number |
| `cooldown_reduction` | 0 | 0.4 | Judgment between two attested designs: a flat 40% cap (classic League of Legends) — chosen for a *direct* attribute — vs uncapped-but-multiplicatively-diminishing stacking (Diablo III, Dota 2, and League's own post-2021 Ability Haste redesign, the documented modern trend) |

Hit/evasion-style probabilities are left to fixtures; the attested principle is a
residual-failure clamp (never 0%, never 100% — Diablo II clamps to 5–95%, PoE caps
evasion at 95%, WoW floors spell miss at 1%); exact bounds vary by title.

## Mobility

- `movement_speed` — `direct: 100`, the percentage-of-baseline convention (a flat
  base the game interprets, with haste/slow arriving as effects). **Attested**: D&D
  5e's flat 30-ft base, ARPG 100%-baseline speed. It is deliberately **not** a
  derived stat: no surveyed system derives movement from a primary stat, and caps
  diverge into four incompatible philosophies (Diablo III +25% cap, PoE uncapped,
  WoW mount tiers, GW2 highest-bonus-wins) — a per-game decision, not family law.
- `initiative` carries the derived-mobility slot instead (see above).

## Effects

One legal configuration ships as a worked example: `regeneration` — a periodic,
timed, refresh-stacking heal targeting `health`, its magnitude the
`regeneration_per_tick` parameter. It exercises the effect legality surface
(stacking-type catalog, period-with-periodic, tick budget) so an instantiated
document starts with a known-valid effect to copy from.

## Instantiating

```bash
gda-balancing template get rpg --out my_design.json
```

Then name your game in `meta`, adjust `parameters`, and keep `design validate` green
while iterating. Extending or overriding template attributes through declared Schema
means is #508's mechanism; until then, edits to the instantiated document are plain
document authoring.
