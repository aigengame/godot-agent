---
status: accepted
---

# Consumable use and equipment mitigation: one items authority, composed defense

S7 closes the two item stories the earlier slices left half-built: the
**Consumable system** (the Bun restores HP, the Wine restores MP) on top of
S6b's supply side (drops land in the Player's `_items` count hook), and the
**Spacesuit** as the defensive Equipment feeding the S2 damage formula's
mitigation term. gADR-0001 fixed the stat split (immutable `StatsConfig` /
runtime `StatsSystem` / pure `CombatSystem`), gADR-0006 fixed the supply seam
("S7 wires `drink_wine`/eat-bun to CONSUME these counts"); this decision fixes
WHERE the item numbers live, HOW a use verb consumes the hook, and HOW worn
Equipment reaches the mitigation term without touching the formula.

We decide four things:

- **Items get their own authoritative source.** A new `items_config.json` →
  `ItemsConfig` Resource carries every item number: the consumable restore
  amounts (`bun_hp_restore`, `wine_mp_restore`), the use juice (per-item flash
  colors + one shared `consume_flash_duration`), and the Spacesuit's
  protective value (`spacesuit_defense`). `wine_mp_restore` **migrates out of
  `gravity_config.json`**: it lived there only because S3's minimal Wine hook
  rode the MP-economy slice, and leaving it would split the Consumable
  authority across two sources. Gravity config keeps only the MP *sink*
  (`mp_cost`); every item *effect* reads from the one items source.
- **A use verb consumes the Item count hook, gated on supply, not need.**
  Each Consumable keeps its own InputMap action (`drink_wine`, new `eat_bun`)
  and the same shape: refuse when the count is 0 (log `consumable_blocked
  {item, count}` — the `gravity_blocked` pattern), else decrement the count,
  apply the capped restore (`StatsSystem.restore_hp`/`restore_mp` — the cap
  stays a parameter from the immutable stat block), play the consume flash,
  and log the use (`bun_eaten`/`wine_drunk` with before/after + the remaining
  count). Using a Consumable at full HP/MP still consumes it: the gate is
  one-input (supply), the cap already bounds the effect, and the S3 hook set
  the restore-at-cap semantics — a "need" gate would be a second decision
  axis the GDD never asked for.
- **The Spacesuit composes an effective defender; the formula is untouched.**
  `ItemSystem.effective_defender(base, defense_bonus)` (pure, static) builds
  a FRESH `StatsConfig` copying the base stat block with `defense` raised by
  the bonus. The Player's `take_hit` feeds that composed block to
  `CombatSystem.compute_damage` as the defender — the formula, its scales,
  and the cached base `.tres` (load()-aliased, gADR-0001) all stay untouched.
  The Spacesuit is worn from spawn (persistent Equipment, GDD), so the
  composed block is built once at ready and logged (`spacesuit_equipped
  {defense_bonus, defense_total}`).
- **The HUD surfaces the Consumable counts.** Two Labels (`BUN n` / `WINE n`)
  extend the S6a Stats column via the same pull/format/pulse machinery. The
  GDD's HUD contract is "read live state without leaving the action" — a
  Consumable the player cannot see the supply of is not usable in the moment;
  the full inventory *menu* stays a later concern (GDD "HUD & UI").

## Considered options

- **Items config as its own source with the Wine migration (chosen).** One
  authority for every item number; the balancing pipeline tunes consumables
  and armor in one file; gravity config stops carrying a non-gravity value.
  Costs a one-time migration touch on the S3 seams (schema, resource, data
  seam, e2e derivations) — paid once, here.
- **Extend existing configs instead (rejected).** `bun_hp_restore` into
  combat config, `spacesuit_defense` into combat config, Wine staying in
  gravity config keeps every file stable but scatters the Items & Equipment
  domain across three sources with no single authority — exactly the drift
  shape gADR-0004/0006 removed for rewards and drops.
- **Spacesuit as a defense-bonus parameter on `compute_damage` (rejected).**
  Widens the pure formula's signature for one caller and leaks Equipment into
  a seam every existing test and the balancing sim pin; the composed-defender
  shape keeps the formula's symmetric stat-block contract byte-identical.
- **Spacesuit by raising `player_stats.defense` in JSON (rejected).** Bakes
  worn Equipment into the actor's base stat block: no un-equipped baseline
  exists, and a later equip/unequip slice would have to un-bake it. The
  composition keeps base and bonus separately authored.
- **Mutating the cached StatsConfig at runtime (rejected).** `load()` aliases
  every consumer of the `.tres` (gADR-0001's one-mutable-Resource rejection);
  raising defense in place would silently harden every OTHER consumer of the
  player stat block.
- **A generic `use_item` action with a selector (rejected for Phase 1).** Two
  Consumables do not need an inventory cursor; per-item actions keep the
  input surface flat and the e2e deterministic. A selector belongs to the
  inventory-menu story, out of Phase-1 scope.

## Consequences

- Retuning any item number (restores, armor, flash juice) is a JSON-only
  change in one file; a non-positive restore or a negative defense fails the
  fast tier, not the runtime.
- The enemy→Player damage derivations in the e2e seams gain the Spacesuit
  term: expected contact damage reads
  `attack * attack_scale - (player defense + spacesuit_defense) *
  defense_scale` (floored at `min_damage`) — every expectation still derives
  from the authoritative JSON.
- Wine beats in existing e2es need supply: `drink_wine` no longer restores
  from thin air, so tests seed `_items` through the live seam (`gda game
  set`, runtime state injection — config data stays shipped) or collect a
  retuned-to-certain drop (the gADR-0006 chance-retune precedent).
- `ItemSystem` is pure/static like its siblings, so the offline balancing
  sim can consume counts and compose defenders with the real rules.
- The Wine hook and Item count hook glossary entries close their "until S7"
  clauses: supply (S6b) → use (S7) is now one observable loop —
  `item_collected` → `bun_eaten`/`wine_drunk`/`consumable_blocked` — and the
  HUD BUN/WINE readouts agree with the log trail.
