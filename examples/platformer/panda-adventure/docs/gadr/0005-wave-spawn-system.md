---
status: accepted
---

# Wave spawn system: a config Wave schedule folded by a pure advance-on-clear rule

S5 makes the encounter arc real: the demo's four-Wave escalation (GDD "The
four-Wave demo arc") becomes a running system that spawns each Wave's
composition and advances to the next when the current one is cleared. The
issue (#334) fixes the hard requirement: the **wave count is config, never
code** — four is the demo's data, and 3 or 5 must work with no code change.
gADR-0000 fixes where numbers live (JSON → derived Resource), gADR-0003 fixed
how a Wave would arrive ("the Wave slice composes Waves as roster entries over
time on this same mechanism"); this decision fixes the schedule's data shape,
the advance rule, and how the default data keeps every pre-S5 flow green.

The model:

- **The Wave schedule replaces the top-level roster.** The authoritative
  `enemies_config.json` carries a `waves` array — each Wave one object whose
  `spawns` is a Spawn Roster (the unchanged gADR-0003 entry shape: kind, node
  name, position) — derived to one `WaveScheduleConfig` Resource
  (`wave_schedule.tres`) the level consumes. `EnemyRosterConfig` /
  `enemy_roster.tres` are retired: a lone boot roster and a one-wave schedule
  would be the same thing under two names, and the S4 default roster IS
  Wave 1 of the demo arc. The wave count is `waves.size()` — no count field
  to drift, nothing hardcoded.
- **Advance-on-clear is one pure fold.** `WaveSystem.resolve_death(alive_before,
  wave_index, wave_count)` — static, deterministic, clock-free (the
  CombatSystem/EnemyAI decision shape, gADR-0001/0003) — maps one enemy death
  to `{alive, cleared, advance, all_cleared}`. The LevelController (already
  the spawner and the death→reward hub, gADR-0004) orchestrates: it counts
  the wave's live spawns, folds each death through the rule, spawns the next
  Wave on `advance`, and logs `wave_started` / `wave_cleared` /
  `all_waves_cleared` (1-based indices, `gda logger tail` protocol) — the
  monotonic per-episode records an observer needs (#406 lesson: transient
  runtime states are asserted from the log, not position polls).
- **The final Wave is the Boss slot by data, not by rule.** The demo's fourth
  Wave composes the `alien_boss_tank` kind — representable since gADR-0003,
  AI still deferred — so the Boss's arrival point exists the day S8 gives it
  behavior. The validator does NOT require a boss-tier final wave: that is
  the demo's composition, not a schedule invariant (a 3-wave reconfig proves
  the count is free precisely by not ending on a Boss).
- **Spawn names are unique across the whole schedule.** The gADR-0003
  per-roster uniqueness rule widens to all waves: `queue_free` on the last
  corpse is deferred, so wave N+1 can spawn while wave N's dying node is
  still in the tree — a same-name spawn would be silently renamed by Godot
  and break addressability (`/root/Main/<name>`) for the live e2e.
  Cross-wave referential integrity (every spawn names a defined kind) rides
  the same validator walk.
- **Pre-S5 flows stay green by DATA (the gADR-0003 move, applied twice).**
  Wave 1 of the default schedule is byte-for-byte the S4 default roster (the
  dormant melee minion named `Enemy` at the S2 position), so every flow that
  observes the boot state is untouched. What is NEW is that killing that
  minion now spawns Wave 2 — so the default `robot_elite_ranged` profile is
  retuned compact (aggro 260 / attack 240 / band [140, 200]): the Elite must
  stay dormant at its spawn point against a Player standing where the S2/S6a
  kill flows leave them (the old aggro 700 covered the whole 800-px
  platform). The S4 ranged e2e keeps its hot long-range scenario by setting
  those params in its throwaway copy — the same explicit-scenario-data move
  its melee sibling already made. A data-seam guard pins the dormancy gap so
  drift fails fast, not deep inside a live e2e.
- **The spawn telegraph is the slice's tween.** Each spawned enemy punches
  its Visual scale from the schedule's `spawn_squash` and recovers over
  `spawn_tween_duration` (the attack-squash shape, gADR-0003) — numbers on
  the schedule config (they belong to the spawn system, not to any one
  kind), delivered through a public `EnemyController.play_spawn_tween` the
  spawner invokes.

## Considered options

- **`waves` replacing `spawns`, advance-on-clear fold (chosen).** One
  authority for who-spawns-when, the count implicit in the data, the
  decision pure and seam-testable at any count.
- **Keeping `spawns` as a boot roster beside `waves` (rejected).** Two spawn
  authorities with an ordering question between them; the boot roster is
  just Wave 1 wearing its old name.
- **Timer-driven waves (rejected for Phase 1).** The GDD's durations are
  explicitly non-authoritative pacing targets, and #334 fixes advance on
  *cleared*. A timed or hybrid trigger can layer onto the same schedule
  later without reshaping the data.
- **A WaveController node between level and enemies (rejected).** The
  LevelController already owns spawn + death wiring (gADR-0004); a second
  orchestrator adds a hop on the same signals with no new decision. The
  decision that IS new lives in the pure WaveSystem instead.
- **Enforcing a boss-tier final wave in the validator (rejected).** It would
  make every non-default count invalid unless it also recomposes a Boss —
  the count requirement and the demo composition are separate facts.

## Consequences

- `enemies_config.json`'s schema drops `spawns` for `waves` (+
  `spawn_squash`, `spawn_tween_duration`); `build_config` renders
  `wave_schedule.tres` and walks all waves in `validate_enemies_semantics`.
- The demo data adds the Wave-3 swarm kinds (`xenomorph_minion_melee`,
  `xenomorph_minion_ranged`) — JSON-only additions, as gADR-0003 promised.
- Reconfiguring the count is a JSON edit: the builder, the freshness gate,
  the runtime, and the seams all follow `waves.size()`. The three seams
  prove it at non-default counts (logic at 3/4/5, e2e at 3 and 5).
- The S4 ranged e2e owns its scenario numbers explicitly; the shipped Elite
  profile now reads as the demo's Wave-2 encounter, not as the e2e fixture.
- S8 (Boss) inherits a live arrival point: give `alien_boss_tank` behavior
  and the existing fourth Wave delivers it; S7's drops and any inter-wave
  pacing attach to the same schedule without a data reshape.
