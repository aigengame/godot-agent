---
status: accepted
---

# Kill reward: per-Tier budget resolved to per-kind fields, and a pull-based HUD

> **Outcome (2026-08-05, gADR-0020).** The modular runtime refactor moved the
> HUD to `ui/hud.tscn`, instanced it from `ui/game_shell.tscn`, and replaced
> Player group discovery with an explicit Game Shell binding. The pull-based
> snapshot contract is unchanged; the body below preserves S6a's original
> placement and decision history.

S6a delivers the reward half of the death/reward story plus the first UI
surface: defeating an Enemy awards EXP and Gold scaled by its Tier, feeding
the S2 StatsSystem, and a HUD surfaces the Player's live HP/MP/EXP/Gold and
Current weapon (GDD "Stats & Economy" + "HUD & UI"). gADR-0000 fixes WHERE
numbers live, gADR-0001 fixes the config/runtime-state split, and gADR-0003
fixes how a kind is modeled; this decision fixes WHERE the reward authority
lives, WHO wires death to award, and HOW the HUD reads the Player — because
S6b's leveling curve, S7's Gold sinks, and the Wave/Boss rewards all build on
these seams.

The model:

- **The reward authority is per-Tier data.** The GDD says "Tier sets an
  enemy's reward budget", so the authoritative `enemies_config.json` gains a
  top-level `tiers` table (minion/elite/boss → `{exp_reward, gold_reward}`) —
  NOT per-kind reward fields: retuning a Tier's budget is one edit that
  reaches every kind of that Tier, and a kind cannot silently drift off its
  Tier's budget. The builder **resolves** the table into per-kind derived
  `exp_reward`/`gold_reward` fields on each `EnemyConfig` .tres
  (`resolve_enemy_rewards`), so the runtime stays a dumb `kind.<field>` read
  with no table lookup and no second load. A new cross-field rule in
  `validate_enemies_semantics` guards the resolution: every Tier a kind uses
  must have a reward entry (a kill that could award nothing is a config bug,
  caught before any resource derives).
- **The spawner owns the death→reward wiring.** `LevelController` — already
  the Spawn Roster consumer — connects each spawned enemy's `died` to an
  award handler, binding the spawned kind. `EnemyController` stays
  reward-agnostic (it only emits `died`, its S4 contract, unchanged), and the
  Wave slice inherits the wiring for free: a Wave is roster entries, and
  every roster spawn is wired at spawn time.
- **The Player is the one reward receiver.** A single public
  `gain_reward(exp, gold, tier)` accumulates onto the Player's own
  StatsSystem (`StatsSystem.gain_reward` — pure addition from the gADR-0001
  accumulation identity) and logs `reward_gained {exp, gold, exp_total,
  gold_total, tier}`. Amounts arrive as parameters read by the caller from
  the defeated kind's derived config — no decision beyond addition exists,
  so there is nothing to split into a decision system yet; S6b's leveling
  curve will be that pure decision when it lands.
- **The HUD pulls a public snapshot each frame.** The HUD (its own
  gda-authored `hud.tscn`: a CanvasLayer — screen-space, untouched by the S1
  follow-camera — with a Label column, instanced in `main.tscn`) reads one
  new public `PlayerController.hud_state()` Dictionary (live HP/MP/EXP/Gold,
  their config caps, and the Current weapon) instead of reaching into
  privates. **Pull-per-frame over signals**: at five values a frame the poll
  costs nothing, needs no signal plumbing across every stat-mutation site
  (take_hit, spend_mp, restore_mp, gain_reward, switch_weapon — five emitters
  today, more later), and keeps the Player the single owner of its state
  while the HUD holds none. A Label rewrites only when its formatted value
  changes, and that change plays the config-driven pulse tween (the
  landing-squash idiom) — the GDD's "accumulating feedback on success".
- **HUD numbers are config; format decisions are pure.** A new
  `hud_config.json` → `HudConfig` .tres carries the blockout numbers (margin,
  pulse scale/duration) through the gADR-0000 pipeline; the readout
  formatting (`format_bar`'s never-0-while-alive ceili, `format_amount`'s
  never-overstate floori, `format_weapon`, `format_lines`) is static and
  node-free so the logic seam pins it headless.

## Considered options

- **Per-Tier table resolved to per-kind derived fields (chosen).** One
  authority, one edit per retune, dumb runtime reads, and the coverage rule
  makes a missing budget a build failure — the `stats_player`/`stats_enemy`
  resolution precedent applied to rewards.
- **Per-kind reward fields in the JSON (rejected).** Three kinds already
  triplicate the minion budget the moment a second minion kind lands; kinds
  can drift off their Tier's budget silently — exactly the "second, drifting
  source" gADR-0000 exists to prevent.
- **A runtime tiers-table lookup (rejected).** A second Resource load and a
  Dictionary lookup in the death path buy nothing over builder-time
  resolution; the freshness gate already proves derived fields cheaply.
- **EnemyController self-awards on death (rejected).** The dying enemy would
  need to find the Player and know reward semantics; death→reward is level
  orchestration, and the spawner already holds both the kind and the wiring
  point. The enemy's public surface stays the S4 `take_hit`/`died` contract.
- **Signal-driven HUD updates (rejected for now).** Every stat-mutation site
  would grow an emit (and every future one must remember to); the HUD would
  hold mirrored state. Pull-per-frame is O(5 reads) and self-healing; revisit
  only if the HUD grows enough consumers for a real observer pattern to pay.
- **HUD reads the StatsSystem object directly (rejected).** Handing out the
  live mutable holder invites writes from the view; the snapshot is
  read-only by construction and also carries the weapon, which StatsSystem
  rightly knows nothing about.

## Consequences

- Retuning reward pacing is a `tiers` edit; adding an Enemy Kind stays a
  JSON-only change (the kind inherits its Tier's budget automatically); a
  used Tier without a budget fails the fast tier, not the runtime.
- The kill flow is observable end-to-end: `died` → `reward_gained {exp,
  gold, exp_total, gold_total, tier}` → the EXP/Gold readouts — the e2e seam
  asserts all three against the same authoritative JSON.
- S6b (leveling) hooks the accumulated `exp_points` and will own the curve
  as a pure decision; S7 (shop/consumables) hooks `gold` the same way. The
  Wave slice's spawns are wired for rewards by construction.
- The HUD is blockout-only (default-theme Labels, data-driven placement and
  pulse); the GDD's layout/styling stays a later asset concern, swapped in
  without touching the read surface.
- `hud_state()` is the Player's public read contract: future UI (menus,
  game-over) reads the same snapshot rather than new privates; new
  HUD-visible state means one new snapshot key.
- gda gap (dogfooding): gda cannot author a scene-instance node (`node add`
  builds type nodes only), so `main.tscn`'s one `instance=` line was
  hand-added — the sanctioned fallback for this file (see
  `docs/project-manifest-notes.md`).
