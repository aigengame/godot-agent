"""Balancing pipeline — the Monte-Carlo encounter-simulation half (gADR-0011).

A `Tool Script` (GAME-CONTEXT.md) that validates the game's encounter-level
tuning numbers against design intent, WITHOUT importing any game code. Per
gADR-0011 the pipeline is deliberately isolated from the game's GDScript: it
reads the same authoritative JSON configs the game derives its Resources from,
reimplements the combat/AI rules in Python, and pins that reimplementation
against the shipped GDScript logic seams with golden parity fixtures (so a rule
change on either side goes red). It writes nothing back to config — this slice
is validate-only (#437).

Two layers:

- **Game-agnostic core** — the reusable pipeline structure, decoupled from any
  one game's engine or code:
  - `model` — plain dataclasses the sim runs on (stat blocks, enemy kinds,
    waves, the player model, sim config, design targets).
  - `encounter` — the time-stepped Monte-Carlo encounter simulation; a fixed
    seed makes it deterministic.
  - `statistics` — the deterministic aggregation stages (distributions:
    mean/median/percentiles) over the per-run TTK/TTD samples.
  - `report` — validate mode: per-wave measured TTK/TTD vs targets, within a
    configurable tolerance. Pure read; emits a report object, never config.
  - `cli` — the `python -m balancing validate ...` entry point.

- **Per-game plug-ins** (Panda Adventure's instantiation) — no game *code*, only
  Python reimplementation and JSON reading:
  - `rules` — the pure Python reimplementation of the `CombatSystem`/`EnemyAI`
    logic seams (GAME-CONTEXT.md), the functions the parity fixtures pin.
  - `game_config` — the adapter that maps this game's JSON authority
    (`data/json/*.json`) into the generic `model`. Reads JSON only; imports no
    game code.
  - `panda_adventure.targets.json` — the design TTK/TTD targets, tolerance,
    player-model assumptions, and simulation controls (per-game configuration).
"""
