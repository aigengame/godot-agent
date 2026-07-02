---
status: accepted
---

# Stats: immutable config stat blocks vs in-memory runtime state

S2 introduces combat stats (HP/MP/EXP/Gold, attack, defense) and the damage
formula. gADR-0000 already fixes WHERE numbers live (JSON authoritative →
derived `Resource`); this decision fixes HOW live, mutating stats relate to
that immutable config, and where combat *decisions* live — because S3 (MP
spend), S4 (enemy taxonomy + enemy→Player damage), S6a (kill rewards), and the
offline Monte-Carlo balancing pipeline all build on the same split.

We split three ways:

- **Stat Block (`StatsConfig`)** — the per-actor-kind config: max HP/MP,
  attack, defense. A derived JSON→Resource artifact (gADR-0000), **immutable at
  runtime**. Player and every Enemy kind carry the SAME type, which is what
  makes the damage formula symmetric: enemy→Player damage (S4) is the same
  function with the roles swapped, no second formula.
- **StatsSystem** — the runtime holder of one actor's live HP/MP/EXP/Gold.
  Instantiated fresh per actor (`new()` + `init_from(stat block)`), mutated
  only in memory, **never `load()`ed from disk and never saved back** — the
  `.tres` stays a derived artifact with no runtime write path, so config can
  never drift from JSON via gameplay.
- **CombatSystem** — the pure combat decisions (damage formula with the
  defense/mitigation term, the i-frame window check, the death rule). Static,
  deterministic, node/physics/clock-free: time is a parameter, not a read.
  Controllers orchestrate (read the real clock, mutate their StatsSystem,
  tween, log); decisions live only here.

## Considered options

- **Three-way split: config Resource / runtime holder / pure decisions
  (chosen).** The offline Monte-Carlo balancing sim (gADR-0000) can call the
  identical decision functions with a simulated clock and in-memory stat
  blocks — no engine session, no divergence between the sim's rules and the
  game's. Runtime mutation can never corrupt config.
- **One mutable Resource loaded from the `.tres` (rejected).** Godot caches
  `load()`, so mutating a loaded Resource aliases every consumer and invites
  writing state back to disk; current-HP-in-config also makes a fresh run's
  state depend on the last run. Both break gADR-0000's derived-artifact
  guarantee.
- **A global stats autoload / game-state singleton (rejected for S2).**
  Nothing needs cross-scene state yet; per-actor ownership keeps the Enemy
  self-contained (S4 spawns many) and avoids an implicit global the logic
  seam would have to reset between cases. Revisit only when a slice needs
  cross-scene persistence (e.g. S6a rewards surviving a scene change).
- **Decisions as controller methods (rejected).** Instance methods on nodes
  drag the scene tree into the balancing sim and the logic seam; the S1
  precedent (`compute_velocity` as a pure static) already proved the
  static-decision shape.

## Consequences

- The Monte-Carlo balancing pipeline reuses `CombatSystem` + `StatsSystem`
  unchanged, supplying its own clock and stat blocks; TTK/TTD tuning happens
  against the real rules.
- Every new actor kind is config (a new stat-block `.tres` from JSON), not
  code — S4's taxonomy is more stat blocks, no restructure.
- The runtime clock is read only in controllers (`_now()`), never inside a
  decision — i-frame logic stays testable with plain floats.
- EXP/Gold start at 0 in `init_from` (an accumulation identity — structural,
  not a tunable); S6a adds accumulation without touching the split.
- In code the EXP field is `exp_points` (`exp` would shadow the built-in
  `exp()`); docs and the glossary keep saying EXP.
