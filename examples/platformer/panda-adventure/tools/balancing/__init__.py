"""Balancing pipeline — twin Monte-Carlo + system-dynamics engines, game-agnostic.

A reusable numeric-design tool that tunes a game's numbers against design
intent WITHOUT importing any game code. It reads the game's authoritative
config through a per-game adapter, reimplements nothing game-specific, and
writes nothing back (both modes are pure reads).

Two engines share the framework:

- **Monte-Carlo encounter simulation** (``validate``) — micro fidelity: one
  encounter at a time, stochastic, aggregated to per-wave TTK/TTD
  distributions and checked against design targets.
- **System-dynamics model** (``predict``) — macro fidelity: a first-order
  nonlinear ODE over the whole run's growth/economy stocks and flows,
  integrated by a hand-rolled RK4, cross-validated against MC on their
  overlapping domain.

The public surface is deliberately small — everything else is internals:

- the **CLI**: ``python -m balancing {validate,predict} --targets <file>``
  (see ``cli`` for flags and the 0/1/2 exit contract);
- the **targets file**: one JSON document holding the whole per-game
  configuration — config location, adapter, protected write roots, player-model
  assumptions, sim controls, and design targets (schema in ``config``);
- the **adapter contract**: a game-side Python file, named by the targets
  file, exporting ``load_inputs(config_dir) -> model.GameInputs`` — it maps the
  game's on-disk config into the generic ``model`` dataclasses and is the only
  code a game contributes. The framework never imports a game; the adapter
  consumes only the public ``model`` types.

Internal layout (consumed through the surface above):

- ``model``      — the plain dataclasses both engines run on.
- ``rules``      — the reference ruleset: pure, deterministic decision
  functions (damage, gates, steering, warp kit, leveling). A host game is
  expected to pin its own engine-side implementation against these with golden
  parity fixtures, generated from the game side (that gate lives with the
  game, not here).
- ``encounter``  — the time-stepped Monte-Carlo encounter simulation; a fixed
  seed makes it deterministic.
- ``statistics`` — deterministic aggregation (mean/median/percentiles) over
  per-run TTK/TTD samples.
- ``report``     — validate mode: per-wave measured TTK/TTD vs targets.
- ``integrate``  — the hand-rolled fixed-step RK4 integrator (stdlib-only).
- ``dynamics``   — the system-dynamics stocks/flows model (generic currency +
  item stocks, a configurable heal-item loop).
- ``prediction`` — predict mode: the long-term SD trajectory vs design
  targets, plus the MC cross-validation.
- ``config``     — the targets-file schema, the adapter loader, and the
  protected-root resolution.
- ``cli``        — the entry point.

Guarantees: pure stdlib (no dependencies), deterministic under a fixed seed,
never writes into a protected config tree (refused before anything runs), and
no game imports or game vocabulary inside the package — the host project's
test suite is expected to pin that isolation.
"""
