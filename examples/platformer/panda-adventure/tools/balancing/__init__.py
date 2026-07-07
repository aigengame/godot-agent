"""Balancing pipeline — the twin Monte-Carlo + system-dynamics engines (gADR-0011).

A `Tool Script` (GAME-CONTEXT.md) that tunes the game's numbers against design
intent, WITHOUT importing any game code. Per gADR-0011 the pipeline is
deliberately isolated from the game's GDScript: it reads the same authoritative
JSON configs the game derives its Resources from, reimplements the combat/AI
rules in Python, and pins that reimplementation against the shipped GDScript
logic seams with golden parity fixtures (so a rule change on either side goes
red). It writes nothing back to config (both modes are pure reads).

Two engines share the framework:

- **Monte-Carlo encounter simulation** (`validate`, #437) — micro fidelity: one
  encounter at a time, stochastic, aggregated to per-Wave TTK/TTD distributions.
- **System-dynamics model** (`predict`, #440) — macro fidelity: a first-order
  nonlinear ODE over the whole run's growth/economy stocks and flows, integrated
  by a hand-rolled RK4, cross-validated against MC on their overlapping domain.

Two layers:

- **Game-agnostic core** — the reusable pipeline structure, decoupled from any
  one game's engine or code:
  - `model` — plain dataclasses both engines run on (stat blocks, enemy kinds,
    waves, the player model, sim config, design targets, the growth/economy
    reward + Leveling data).
  - `encounter` — the time-stepped Monte-Carlo encounter simulation; a fixed
    seed makes it deterministic.
  - `statistics` — the deterministic aggregation stages (distributions:
    mean/median/percentiles) over the per-run TTK/TTD samples.
  - `report` — validate mode: per-wave measured TTK/TTD vs targets, within a
    configurable tolerance. Pure read; emits a report object, never config.
  - `integrate` — the hand-rolled fixed-step RK4 integrator (stdlib-only).
  - `dynamics` — the system-dynamics state model: the run's growth/economy
    stocks + flows as a first-order nonlinear ODE system.
  - `prediction` — predict mode: the long-term SD trajectory vs difficulty/growth
    design targets, plus the MC cross-validation. Pure read; emits a report object.
  - `cli` — the `python -m balancing {validate,predict} ...` entry point.

- **Per-game plug-ins** (Panda Adventure's instantiation) — no game *code*, only
  Python reimplementation and JSON reading:
  - `rules` — the pure Python reimplementation of the `CombatSystem`/`EnemyAI`
    logic seams (GAME-CONTEXT.md), the functions the parity fixtures pin.
  - `game_config` — the adapter that maps this game's JSON authority
    (`data/json/*.json`) into the generic `model`. Reads JSON only; imports no
    game code.
  - `panda_adventure.targets.json` — the design targets, tolerances, player-model
    assumptions, simulation controls, and the SD model params/levers (per-game
    configuration).
"""
