---
status: accepted
---

# Leveling curve as a pure function of EXP, and per-Tier drop tables collected as Pickups

S6b closes the progression loop the GDD's "Stats & Economy" intends
("fight enemies, earn EXP/Gold and drops, grow stronger"): accumulating EXP
levels the Player up along a data-driven Leveling curve, and defeated
Enemies drop Gold/items as world Pickups per a data-driven Drop table.
gADR-0000 fixes WHERE numbers live, gADR-0004 fixed the Kill-reward
authority per Tier and predicted "S6b's leveling curve will be that pure
decision when it lands"; this decision fixes the SHAPE of that decision,
WHERE the drop authority lives, and HOW a drop reaches the Player — because
S7's Consumable supply and the balancing pipeline's economy tuning both
build on these seams.

The model:

- **The Leveling curve is a cumulative-threshold array; the level is a pure
  FUNCTION of the EXP total.** A new authoritative `progression_config.json`
  carries `level_curve` — strictly increasing cumulative EXP thresholds
  (a builder semantic gate, `validate_progression_semantics`) — and
  `GrowthSystem.resolve_level(exp_points, level_curve)` returns
  1 + thresholds reached. The max level is `level_curve.size() + 1` — the
  gADR-0005 `waves.size()` idiom: count is config, never code. Deriving
  from the TOTAL (not folding per gain) makes one Boss-sized reward worth
  every threshold it crosses (a multi-level-up for free) and re-resolution
  idempotent. The Player re-resolves after each Kill reward, caches the
  level ONLY to detect the rising edge (one `level_up {from, to,
  exp_total}` record + a flash tween), and surfaces it as the HUD's LV line
  (`hud_state().level`, the gADR-0004 snapshot grown by one key).
- **Leveling is readout-only in Phase 1.** A level-up changes no stat: the
  issue's contract is "accumulating EXP levels the Player up", and any
  stat-growth-per-level numbers are balancing-pipeline data that would also
  rework the S2 damage-formula seam (the attacker stat block is today the
  immutable derived config). When growth lands (a later slice, with the
  balancing pipeline), it hooks the same `_level` edge.
- **The drop authority is the same per-Tier table as the Kill reward.** Each
  `tiers` entry in `enemies_config.json` gains a required `drops` array —
  `{item, amount, chance}` entries — and `resolve_enemy_rewards` (the
  gADR-0004 resolver, extended) copies it into a per-kind derived
  `drop_table` field: the runtime stays a dumb `kind.<field>` read, one
  edit retunes a whole Tier, a kind cannot drift off its Tier's budget.
- **Drop resolution is pure; the rolls are parameters.** `EconomySystem.
  resolve_drops(drop_table, rolls)` includes entry i iff
  `rolls[i] <= chance` — INCLUSIVE, so `chance: 1.0` is guaranteed against
  Godot's 1.0-inclusive `randf()` (a guaranteed entry is what makes the
  e2e deterministic on shipped data). The spawner (LevelController — it
  already owns the death edge, gADR-0004) supplies one `randf()` per entry:
  randomness is orchestration, like the clock (gADR-0001), so the logic
  seam pins chance boundaries headless. `drop_offset` scatters the drops on
  a deterministic row centered on the death position — no scatter RNG.
- **A drop is a world Pickup, not a direct award.** Each resolved drop
  instances `pickup.tscn` (an Area2D block ON the new `pickup` layer 6,
  masking ONLY the `player` layer — nothing else can touch it and it blocks
  nothing) at the death spot; the Player walks into it to collect. This is
  the GDD's "light exploration and collection" beat, and it is what makes a
  drop DIFFERENT from the S6a Kill reward: guaranteed instant EXP/Gold per
  kill, versus loot that must be picked up. The Pickup self-applies its
  blockout from `drop_items` (per-item color/size in the progression
  config; the schema REQUIRES a style for the whole item vocabulary, so a
  drop can never reference an unstyled item — coverage by construction, no
  cross-source validator) and hands the drop to the Player's
  `collect_drop(item, amount)` exactly once.
- **Gold accumulates; items land in the S6b item-count hook.** Collected
  gold is `StatsSystem.gain_gold` — Gold's second source next to
  `gain_reward`, logged `gold_collected {amount, gold_total}`. Any other
  item increments the Player's `_items` count Dictionary, logged
  `item_collected {item, amount, count}` — the S3 Wine-hook pattern applied
  to supply: S6b owns drop→acquire, S7 owns the Consumable use-effects that
  will consume these counts. The item vocabulary is CLOSED for Phase 1
  ({gold, bun, wine}, a schema enum on both sources): the demo's items are
  exactly the GDD's.

## Considered options

- **Cumulative thresholds, level derived from the total (chosen).** One
  array, level a pure function — idempotent, multi-level-safe, and the max
  level is the array length: the waves.size() precedent.
- **Per-level increment costs (rejected).** Needs a running fold (level +
  leftover EXP as state), so the level stops being derivable from the
  total; nothing gained over thresholds authored cumulatively.
- **Level stored in StatsSystem (rejected).** The level is DERIVED state —
  storing it beside `exp_points` invites drift between the two; the holder
  keeps only independent live stats (gADR-0001), the Player caches the edge.
- **Stat growth on level-up now (rejected).** Out of the S6b contract;
  growth numbers are balancing-phase data, and the attacker/defender stat
  blocks are immutable derived config today — growing them is its own
  slice against the S2 formula seam, hooked on the same level edge later.
- **Per-kind drop fields in the JSON (rejected).** The gADR-0004 argument
  verbatim: kinds triplicate a Tier's table and drift silently; the per-Tier
  authority already exists — drops extend it.
- **Direct-award drops, no world Pickups (rejected).** Indistinguishable
  from a second Kill reward with randomness — no collection verb, no
  exploration beat; the GDD's economy loop expects loot on the ground.
- **RNG inside EconomySystem (rejected).** An unpinnable logic seam and an
  unusable balancing-sim core; rolls are parameters exactly as time is to
  CombatSystem/EnemyAI.
- **Drop styles inside enemies_config (rejected).** The pickup blockout
  belongs to the drop/pickup system, not the enemy taxonomy; keeping it in
  the progression source with all-items-required styling removes the need
  for any cross-source coverage validator.
- **An open item vocabulary (rejected for Phase 1).** A free-form item id
  would push style coverage into a cross-source semantic rule and buys
  nothing: the demo's items are exactly Bun/Wine (+ gold).

## Consequences

- Retuning the curve (or its length — the max level), a Tier's drop mix,
  chances, amounts, or the pickup blockout is a JSON-only change; a
  non-increasing curve, an unstyled/off-vocabulary item, a 0 chance, or a
  fractional amount fails the fast tier, not the runtime.
- Gold now has two observable sources: `reward_gained` (instant, per kill)
  and `gold_collected` (per Pickup walked over). The full kill flow reads
  end-to-end in the log: `enemy_died` → `reward_gained` → `level_up` →
  `pickup_spawned`(×n, one per resolved drop) → `gold_collected` /
  `item_collected` — and the HUD LV/EXP/GOLD readouts agree (the e2e seam
  asserts all of it against the authoritative JSON).
- e2e determinism on a probabilistic system: guaranteed (chance 1.0)
  entries assert on shipped data; probabilistic entries are retuned to 1.0
  in the throwaway project copy (the waves-e2e reconfiguration precedent) —
  never a sleep-and-hope roll.
- S7 (Consumables) inherits its supply side: Bun/Wine drops already land as
  `_items` counts; S7 wires `drink_wine`/eat-bun to CONSUME them (replacing
  the S3 hook's free restore) without touching the drop path. The Boss
  (S8) inherits a drop table by Tier automatically.
- Uncollected Pickups persist (no lifetime): a cleared Wave's loot stays
  collectible at leisure; nothing else can consume or destroy it by
  construction (the mask).
- gda gap (dogfooding): `gda node add` appends only — inserting the HUD's
  LV line between existing Labels took remove+re-add of the trailing three;
  a child-index/reorder option is filed as a gda feature request.
