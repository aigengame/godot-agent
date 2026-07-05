---
status: accepted
---

# Boss Warp kit: space-warp blink and time-dilation field

S8 closes the demo's finale: the Wave-4 Alien Boss whose "signature time-warp
ability" the GDD names but deliberately leaves undesigned ("its concrete
behavior is owned and detailed by the Phase 1 PRD"), and whose Archetype —
Tank — gADR-0003 left representable-but-deferred (no movement, no attack).
Issue #338 gates implementation on a HITL design decision; this record is that
decision, settled in the 2026-07-05 interview.

We decide six things:

- **Warp is ONE signature with two expressions.** The Boss bends spacetime at
  the black-hole's edge: the space half is the **Warp Blink** (instant
  translocation), the time half is the **Time Dilation Field** (a local slow
  zone). They are one narrative hook, not two stapled-on abilities — and the
  deliberate mirror of the Player's own pillar: the Player bends gravity, the
  Boss bends time. "Portal" is rejected as a term (it implies a persistent
  traversable gate); the glossary carries Warp / Warp Blink / Time Dilation
  Field.
- **Tank AI un-defers minimally: same rule, tank data.** The two Tank
  special-cases in `EnemyAI` (`compute_move_dir` → 0, `can_attack` → false)
  are removed; the Tank runs the SAME Steering Band + contact-attack rule as
  Melee/Ranged, differentiated purely by its stat data (move_speed 60 slow
  advance, keep_range 0–80 point-blank band, attack 15 / cooldown 2.0 heavy
  hits). No Tank-specific AI branch exists. The finale's base threat is the
  melee hammer; the Warp kit is its rhythm, not its only damage source.
- **Abilities are per-kind optional data, presence-gated.** The `warp_*` /
  `time_field_*` params are optional flat fields on an Enemy Kind (the
  `projectile_*` precedent) — configured on `alien_boss_tank`, absent
  elsewhere. They are keyed to NEITHER Tier nor Archetype: no fourth axis, no
  "Boss implies Warp" system rule (the Boss slot stays a property of the demo
  composition, gADR-0005), and gADR-0003's three-axis orthogonality survives
  intact.
- **The rotation couples the field to the blink as its wake.** When the warp
  cooldown is ready AND the Player is farther than `warp_trigger_range`, the
  Boss casts: charge-up tell → blink to the landing point, where the Time
  Dilation Field drops at the SAME instant (the zone is the warp's own
  spacetime ripple) → a short no-attack recovery (the Player is slowed but
  un-punished: the fair-exchange window) → normal Tank AI resumes. The field
  is unconditional per warp — no "only if the Player is inside" branch — and
  at most one exists (duration < cooldown). In a point-blank brawl the Boss
  never warps: the Blink is the anti-kite engage tool, so a Player who stands
  and trades meets the melee hammer instead.
- **The landing rule is deterministic and cuts off the retreat.** Landing x =
  `player.x + sign(player.x - boss.x) * warp_offset.x` (the far side of the
  Player from the Boss — the Boss appears AHEAD of the fleeing Player), y =
  `player.y + warp_offset.y`, clamped to the arena bounds. Never random: the
  same inputs land the same spot, for readability and for e2e determinism.
- **The field slows the Player's whole body simulation and the Player's laser
  Projectiles — nothing else.** Inside the zone, the Player's movement, jump,
  AND gravity scale by `time_field_factor` (full slow motion — the floaty
  slow-mo jump is the visual selling point), and laser bolts inside fly
  slowed. Input registration stays instant (slowed, not stunned), and the
  Gravity Gun / Gravity Field / MP pipeline runs at FULL speed by design: the
  field suppresses the two instinctive answers (run, shoot) precisely so the
  finale demands the taught control pillar — MP spent on fields, Wine
  sustaining it. Mechanically this is the opt-in mirror of gADR-0002's
  gravity-affectable contract: members of a `time_dilatable` group implement
  `set_time_dilation(factor)`, applied on overlap and reset to 1.0 on exit or
  expiry; the Player is a member here (and never gravity-affectable), the
  Boss is not.

## Considered options

- **A global time pulse (no zone).** Everything but the Boss slows for N
  seconds. Simplest, but the counterplay collapses to "wait it out" — a soft
  stun with no spatial decision. Rejected.
- **Boss self-acceleration ("enrage").** Warp speeds the Boss up instead.
  Enemy-side-only (cheapest), but it reads as rage, not time, and gives the
  kiting hole no answer. Rejected.
- **Projectile-time warp only.** Player bolts slow near the Boss; movement
  untouched. Interesting counterplay but visually subtle and hard to read in
  a blockout. Rejected.
- **An aura following the Boss** instead of a static zone. Escaping a
  slow-aura glued to a pursuer (who can also blink to you) degrades
  counterplay into permanent kiting frustration; a static zone keeps the
  read the Gravity Field already taught: local, timed, leave-it. Rejected.
- **Keying the kit to Tier or Archetype.** "Boss ⇒ Warp" would promote a demo
  composition into a system rule and bend the three-axis orthogonality;
  presence-gated per-kind data costs nothing and follows the ranged
  `projectile_*` precedent. Rejected.
- **Conditional field cast (only if the Player is within radius).** One more
  branch for marginal value; unconditional "every warp leaves a wake" is more
  readable and more testable. Rejected.
- **Random or anchor-point landings.** Random is untestable and unreadable;
  fixed anchors are level data orphaned inside kind config and read as
  patrol-teleport, not pursuit. Rejected.

## Consequences

- `enemies_config.json` gains on `alien_boss_tank` (initial values, tuned by
  TTK/TTD later): `warp_cooldown` 8.0, `warp_trigger_range` 200.0,
  `warp_offset` [60, 0], `warp_tell_duration` 0.5, `warp_recovery_duration`
  0.4, `time_field_radius` 160.0, `time_field_factor` 0.5,
  `time_field_duration` 3.0. `EnemyConfig` and the builder derive them as
  optional fields.
- `EnemyAI` loses its Tank special-cases; new pure decisions (warp gate,
  landing point, in-field membership) live beside it, node/clock-free, so the
  logic seam covers them headless.
- A `time_field` scene/controller joins the blockout (the Gravity Field
  pattern: Area2D + timed lifetime + tween); the Player and the laser
  Projectile join `time_dilatable` and implement `set_time_dilation`.
- Logging: `warp_tell`, `warp_blink` (from → to), `time_field_spawned`,
  `time_field_expired`, per the `gda logger tail` protocol.
- The Time Dilation Field is a new player-visible visual → one new CHECKPOINT
  in `test_visual_smoke_e2e.py` (same single windowed session).
- Scope exclusions, decided: NO victory banner (the final clear keeps logging
  `all_waves_cleared` only — a separate UI story) and NO Boss-HP HUD line
  (observability via `gda game get` on the live Boss and the existing hit
  flash); the HUD's LINES contract is untouched.
- e2e determinism follows the waves-e2e precedent: reconfigure the throwaway
  copy's enemies JSON wholesale (shrink cooldowns/ranges), assert landings by
  the deterministic formula, and read live state via `gda game get` (the
  #422 capability).
