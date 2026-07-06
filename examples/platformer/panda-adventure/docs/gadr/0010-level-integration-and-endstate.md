---
status: accepted
---

# Level integration: the Great-Wall blockout and the end-state loop

S9 closes Phase 1: the single demo level assembled as the GDD's Great-Wall
blockout, and the arc's end states — win (schedule cleared), lose (Player HP
0), retry — so the "one-more-try" loop the GDD names as the emotional goal
actually closes. Until now the level was one 800px slab authored inside the
*player* config, the only win signal was the `all_waves_cleared` log record
(gADR-0009 deliberately scoped the victory banner out as "a separate UI
story" — this is that story), and death just latched `player_died` with the
corpse still controllable.

We decide seven things:

- **The level gets its own authority: `level_config.json` → `LevelConfig`.**
  The platform blockout moves OUT of `player_config.json` (the S7
  wine-restore migration precedent, gADR-0008: one domain, one authority).
  The level authority carries the Great-Wall geometry (`platforms`, one
  shared `platform_color`), the backdrop (`background_color` — the
  black-hole-edge flavor, applied as the clear color), the explicit Arena
  (`arena_min_x`/`arena_max_x`), and the End screen's blockout numbers. The
  player config keeps only player-scoped fields.
- **The Great-Wall blockout is composed segments, runtime-instanced.** The
  `platforms` array — ordered `{name, position, size}` entries — is the
  geometry: one long rampart span, two flank towers, two parapet steps
  (GDD "Level & Blockout": long rampart-like spans, proportioned to the
  Player). `LevelController` instances `platform.tscn` per entry (the
  enemy.tscn / Spawn Roster precedent, gADR-0005); the static `Platform`
  node leaves `main.tscn`. The rampart keeps the S1 slab's top line
  (y = 476), so the Wave schedule's spawn line and every position-derived
  test stay valid — the wall extends around the fight, it does not move it.
- **The Arena is authored, not derived.** The Warp Blink's landing clamp
  (gADR-0009) read "the platform extent" off the PlayerConfig; a
  multi-segment wall has no single extent to derive, and the open span
  between the towers is a design choice. `arena_min_x`/`arena_max_x` become
  explicit config, and `EnemyController` reads them from `LevelConfig`.
- **End states resolve in a pure GameStateSystem.** States
  `playing → won | lost`, folded from the two existing edges: the schedule's
  `all_waves_cleared` decision wins, the Player's death loses. The FIRST
  transition latches (a post-win death or a post-loss clear changes
  nothing — same-frame races resolve by arrival order). Win means *schedule
  cleared*, not "Boss died": the Boss slot stays a property of the demo
  composition (gADR-0005/gADR-0009), so a reconfigured schedule wins on its
  own final wave. Static, node/clock-free decisions (the WaveSystem shape),
  so the logic seam pins the whole state machine headless.
- **The end-state world freeze must NOT pause the tree.** The gda harness
  autoload serves the live IPC channel from `_process` under the default
  pause mode, so `get_tree().paused = true` would sever `gda`'s live channel
  exactly when an e2e wants to observe the end state and press retry.
  Instead `LevelController` freezes gameplay by setting
  `PROCESS_MODE_DISABLED` on every non-CanvasLayer child of Main (deferred
  to the frame boundary — the freeze edge lands frame-coherently, never
  mid-physics-callback). Enemies, bolts, fields, and pickups halt where they
  are — the time-stopped tableau reads as the finale's own spacetime motif —
  while the HUD (CanvasLayer) keeps the final readout and the End screen
  (CanvasLayer) plays its fade. Static platforms stay solid; nothing moves.
- **Retry is a scene reload, not an in-place respawn.** A new `retry` input
  action (Enter — every other verb's key is taken), read by
  `LevelController` ONLY in an end state, logs `game_retried` and
  `reload_current_scene()`s. The whole level re-derives from config —
  stats, waves, drops, HUD — with zero reset code to drift; an in-place
  respawn would have to hand-unwind every subsystem. The gda session
  survives the reload (same process; the log accumulates), so retry stays
  observable live.
- **The End screen is a level-owned blockout overlay.** `end_screen.tscn`
  (CanvasLayer above the HUD): a full-screen dim rect + title + retry-hint
  labels, faded in by tween. Colors, font sizes, and fade duration are
  LevelConfig data; the copy ("VICTORY!", "GAME OVER", "Press Enter to
  retry") is structural code, like the weapon identifiers. It is NOT part of
  the HUD: gADR-0004's HUD reads live state every frame and its LINES
  contract stays untouched (gADR-0009's scope note honored); the End screen
  is the level announcing its own closure, shown once per run.

## Considered options

- **Tree pause for the end state.** The idiomatic Godot game-over; rejected
  because the committed harness polls IPC in `_process` (pause-inherit), so
  a paused tree kills `gda game get`/input/screenshot mid-session — the
  live channel this project's whole feedback loop rides on.
- **`Engine.time_scale = 0`.** Also freezes the harness's clock-driven
  monitor windows and reads as a global hack; same live-channel hazard
  class. Rejected.
- **Keep platform fields in the player config, add a second geometry list.**
  Splits the level authority across two files; rejected (one authority per
  domain, gADR-0008 precedent).
- **Win keyed to the Boss's death.** Promotes the demo composition into a
  system rule and breaks reconfigured schedules (the wave-count e2e runs
  bossless 3- and 5-wave schedules). Rejected — gADR-0005's stance.
- **In-place respawn (reset stats, respawn waves).** Every subsystem grows
  reset code that must mirror its init code forever; a reload gets the same
  result from the config path that already exists. Rejected.
- **End-screen numbers in `hud_config.json`.** The HUD is one specific
  surface (gADR-0004), not "all UI"; parking the closure overlay there
  muddies that term. Rejected.
- **A game-state autoload/singleton.** Outlives the scene reload, so retry
  would need manual state reset — the exact drift retry-as-reload avoids.
  Rejected.

## Consequences

- `data/json/level_config.json` + schema + `LevelConfig` Resource + a
  builder spec join the pipeline: a `platform_list` renderer, and
  `validate_level_semantics` enforcing the cross-field rules — platform
  names unique (they become sibling node names in Main, the gADR-0005
  addressability argument) and `arena_min_x < arena_max_x`.
- `player_config.json` loses `platform_color/size/position`; every test
  that derived the ground line from the player config reads the level
  authority's rampart instead.
- `PlayerController` gains a `died` signal (emitted once, on the S4 death
  latch — the EnemyController precedent); the latch's "still controllable"
  note retires: the world freeze now owns post-death.
- New pure decisions in `src/systems/game_state_system.gd`; new
  `end_screen_controller.gd` + `platform.tscn` + `end_screen.tscn`;
  `main.tscn` drops `Platform`, gains the `EndScreen` instance;
  `project.godot` gains the `retry` action.
- Logging, per the `gda logger tail` protocol: `level_ready` (platform
  count + arena), `game_won`, `game_lost`, `game_retried`,
  `end_screen_shown`. `all_waves_cleared` and `player_died` stay unchanged
  as the upstream edges.
- The End screen is a new player-visible visual → one new CHECKPOINT in
  `test_visual_smoke_e2e.py` (same single windowed session); the HUD's
  `_HUD_LINES` is untouched (no new HUD lines).
- `tests/test_level_e2e.py` closes the DoD's playthrough seam: a full
  Wave 1 → final-wave win → retry run, and a lose → retry run, both
  log-asserted end to end.
- The packaged macOS export is rebuilt at this (wave-closing) slice per
  gADR-0007's freshness rule and pty-smoked.
