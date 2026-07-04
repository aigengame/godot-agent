---
status: accepted
---

# Enemy taxonomy: per-kind config resources and band-steering Archetype AI

S4 makes the Enemy real: a data-driven taxonomy along the three design-fixed
axes (Faction × Tier × Archetype, GDD) plus a stat block, and the Melee/Ranged
Archetype behaviors that let an enemy damage the Player. gADR-0000 fixes WHERE
numbers live (JSON → derived Resource) and gADR-0001 fixes the stats/combat
split; this decision fixes HOW an enemy *kind* is modeled as data, how the
Archetype AI decides, and how enemy→Player damage reuses the S2 machinery —
because the Wave slice, the enemy-taxonomy growth (more kinds), and S6a's kill
rewards all build on it.

The model:

- **Enemy Kind = one derived Resource, and it IS its stat block.** Each kind is
  a named sub-object of one authoritative `enemies_config.json` (axes + stat
  block + blockout + AI params), derived to one `EnemyConfig` `.tres` per kind
  via the builder's `json_root` mechanism (the `stats_player`/`stats_enemy`
  precedent). The per-kind derivation specs are themselves **derived by
  iterating the JSON's `kinds`** (a ranged kind picks up the projectile field
  layout by its archetype), so adding a kind is a JSON entry, full stop — no
  Python edit; the builder and the freshness gate follow the JSON (gADR-0001:
  a new actor kind is config, not code). `EnemyConfig` **extends
  `StatsConfig`**, so a kind feeds `CombatSystem.compute_damage` directly as
  attacker or defender — the symmetric formula is reused verbatim with the
  roles swapped (gADR-0001), no second formula and no per-kind stats sidecar.
- **The Spawn Roster is config.** Which kind spawns where, under what node
  name, is the `spawns` array of the same JSON, derived to an
  `EnemyRosterConfig` Resource the level consumes at boot. The Wave slice
  composes Waves as roster entries over time on this same mechanism.
- **Cross-field rules live in one semantic validator.** What JSON Schema
  cannot express, `build_config.validate_enemies_semantics` enforces before
  any resource derives (and the data seam exercises): the Steering Band is a
  real interval (`keep_range_min <= keep_range_max`); a **melee kind's
  `attack_range` must not exceed `keep_range_max`** — melee damage is contact
  damage, the attack gate cannot reach beyond the point-blank band the
  steering holds; every spawn references a defined kind; and roster names are
  unique for addressability.
- **Archetype AI = one pure band rule + a delivery branch.** `EnemyAI`
  (static, deterministic, clock-free — gADR-0001's decision shape) steers to
  hold the per-kind Steering Band `[keep_range_min, keep_range_max]`: close in
  beyond it, back off inside it, hold within it; gated by the Aggro Range and
  an attack range/cooldown check (the `-INF` never-yet sentinel, mirroring
  `is_invulnerable`). Melee (band ending point-blank, min 0) and Ranged (a
  standoff band) are the SAME steering rule with different data; what
  *branches* on the Archetype is the attack **delivery**, owned by the
  controller: Melee lands a contact `take_hit`, Ranged fires a bolt.
- **The Ranged bolt is the S2 Projectile, parameterized.** One
  `ProjectileController` serves both sides: blockout/motion defaults to the
  Laser Gun's CombatConfig params and a Ranged kind overrides them via
  `configure()`; the target side lives in the scene variant's collision mask
  (`projectile.tscn` masks terrain|enemy, `enemy_projectile.tscn` masks
  terrain|player) — the mask, not code, decides who can be hit. No new layers:
  both bolts are layer `projectile`.
- **Tank is deferred, in data but not in behavior.** The axis value, its enum,
  and a full kind (`alien_boss_tank`) exist — the data model represents it —
  but `EnemyAI` returns no move and no attack for it in Phase 1. Its soak/hold
  behavior lands with the Boss/Wave work.

## Considered options

- **Kind-as-Resource extending StatsConfig + pure band AI (chosen).** One
  load per spawn, one attacker/defender object, the sim-reusable decision
  shape already proven twice (S1 `compute_velocity`, S2 `CombatSystem`).
- **Per-archetype controller subclasses (rejected).** Three scripts whose
  differences are two `if` branches and otherwise data; multiplies scenes and
  breaks the one-scene spawner. Behavior differences here are parametric, not
  structural.
- **A distinct steering rule per archetype (rejected).** "Close in" and "keep
  away" are the same band rule with different edges; two functions would
  duplicate the aggro/hold logic and drift. The archetype string still gates
  delivery (and Tank's deferral) — it is not decorative.
- **Reusing combat_config's `enemy_stats`/`enemy_*` for the default kind
  (rejected for now).** The S2 data contract freezes that block and its tests;
  S4's kinds are additive in their own file. Cost: the shipped default kind
  duplicates those values; a data-seam guard pins the two together until a
  planned **follow-up consolidation** migrates the S2 surface onto the
  taxonomy and retires `enemy_stats`/`enemy_position`/`enemy_color`/
  `enemy_size` from combat_config.
- **A second projectile implementation for enemy bolts (rejected).** Flight,
  lifetime, first-hit resolution, and despawn are identical; only mask and
  params differ — exactly what a scene variant plus `configure()` expresses.

## Consequences

- Enemy→Player damage is `CombatSystem.compute_damage` with roles swapped;
  the Player's `take_hit` mirrors the Enemy's (i-frames, death rule) — the
  formula stays single-sourced.
- The enemy body becomes a `CharacterBody2D` (it moves); it keeps the public
  `take_hit(attacker)` + `died` surface, joins `gravity_affectable`, and
  implements `apply_gravity_field(field_velocity, delta)` (the S3 contract,
  documented in gADR-0002) as a buffered fold into its velocity integration.
- The default shipped roster spawns one dormant melee minion matching the S2
  expectations (same stats, position, and an Aggro Range short of the S1/S2
  flows' Player positions), so the existing player/combat e2e stay green
  by data, not by test edits.
- Balancing gets per-kind knobs (TTK/TTD per kind) with the sim reusing
  `EnemyAI` + `CombatSystem` unchanged, time and positions injected.
- The enums live in the schema (validation authority for shapes, with the
  semantic validator owning the cross-field rules); the glossary owns their
  meaning. A new kind is a JSON entry (ranged kinds include their projectile
  block) — the spec derivation and the freshness gate follow the JSON, so a
  kind missing its committed `.tres` (or violating a cross-field rule) fails
  the fast tier, not the runtime.
