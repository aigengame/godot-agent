"""Unit tests for the system-dynamics state model (#440 AC1, AC4, AC5).

Covers, deterministically (no RNG, no engine, no game code):

- **Conservation** — clearing a Wave accrues EXACTLY its EXP/Gold/Wine reward
  (the coflow's exact first integral), and Level reads off the accrued EXP.
- **Boundary** — HP stays within ``[0, max]`` (the heal never overfills the cap),
  Bun count never goes negative, and the reward stocks are monotonic.
- **The two feedback loops** — the reinforcing growth loop (higher Level → faster
  clears) and the balancing consumable loop (Bun healing turns a Boss loss into a
  win) — the nonlinearities that make this a first-order NONLINEAR ODE system.
- **From the JSON authority alone** — the per-Wave projection produces sane
  aggregates and a Boss-peaked difficulty ramp (AC1), importing no game code.
"""

from __future__ import annotations

import math

import build_config
from balancing import dynamics, game_config
from balancing.dynamics import (
    SdParams,
    WaveDynamics,
    build_wave_dynamics,
    run_scenario,
    run_wave_overlap,
)
from balancing.model import GrowthEconomy

CONFIG_DIR = build_config.GAME_DIR / "data" / "json"

_PLAYER_MODEL_PARAMS = {
    "fire_interval": 0.3,
    "accuracy": 0.8,
    "dodge_chance": 0.2,
    "engagement_distance": 60.0,
}


def _econ(**over) -> GrowthEconomy:
    base = dict(
        level_curve=(10.0, 50.0, 150.0, 280.0),
        tier_rewards={},
        bun_hp_restore=25.0,
        wine_mp_restore=15.0,
        player_max_hp=100.0,
        player_max_mp=50.0,
    )
    base.update(over)
    return GrowthEconomy(**base)  # type: ignore[arg-type]


def _wd(**over) -> WaveDynamics:
    base = dict(
        index=1,
        wave_hp=100.0,
        player_dps=50.0,
        enemy_dps=0.0,
        exp_reward=25.0,
        gold_reward=10.0,
        bun_drops=0.0,
        wine_drops=0.0,
    )
    base.update(over)
    return WaveDynamics(**base)  # type: ignore[arg-type]


def _params(**over) -> SdParams:
    base = dict(
        dt=1.0 / 60.0,
        max_wave_time=200.0,
        growth_gain=0.0,
        heal_threshold_frac=0.5,
        bun_consume_rate=0.0,
    )
    base.update(over)
    return SdParams(**base)  # type: ignore[arg-type]


def _authority():
    game = game_config.load_game_data(CONFIG_DIR)
    econ = game_config.load_growth_economy(CONFIG_DIR)
    player = game_config.build_player_model(game, _PLAYER_MODEL_PARAMS)
    return game, econ, player, build_wave_dynamics(game, econ, player)


# --- Conservation ------------------------------------------------------------ #


def test_reward_conservation_on_clear() -> None:
    """Clearing a Wave accrues EXACTLY its EXP/Gold/Wine reward — the kill flow's
    coflow integrates to the design total, and the clear time is the analytic
    wave_hp / player_dps."""
    econ = _econ()
    wd = _wd(exp_reward=25.0, gold_reward=10.0, wine_drops=3.0)
    outcome = run_wave_overlap(wd, _params(), econ)
    assert outcome.cleared and not outcome.died
    assert math.isclose(outcome.exp_gained, 25.0, abs_tol=1e-9)
    assert math.isclose(outcome.gold_end, 10.0, abs_tol=1e-9)
    assert math.isclose(outcome.wine_end, 3.0, abs_tol=1e-9)
    assert outcome.clear_time is not None
    assert math.isclose(outcome.clear_time, wd.wave_hp / wd.player_dps, abs_tol=2e-3)


def test_level_reads_off_accrued_exp() -> None:
    """The Level readout tracks the accrued EXP against the Leveling curve — an
    exact-threshold total (EXP 50 == curve[1]) reaches the next Level."""
    econ = _econ(level_curve=(10.0, 50.0))
    outcome = run_wave_overlap(_wd(exp_reward=50.0), _params(), econ)
    assert math.isclose(outcome.exp_end, 50.0, abs_tol=1e-9)
    assert outcome.level_end == 3  # 1 + 2 thresholds reached


def test_reward_conservation_across_the_run() -> None:
    """Chaining the real Wave schedule, the cumulative EXP after each cleared Wave
    is the running sum of the per-Wave rewards (no drift, no double count)."""
    _game, econ, _player, wds = _authority()
    run = run_scenario(wds, _params(bun_consume_rate=2.0), econ)
    running = 0.0
    for outcome, wd in zip(run.waves, wds):
        if not outcome.cleared:
            break
        running += wd.exp_reward
        assert math.isclose(outcome.exp_end, running, abs_tol=1e-9)


# --- Boundary ---------------------------------------------------------------- #


def test_heal_never_overfills_hp() -> None:
    """The Bun heal saturates at max HP — a long, damage-free Wave with Buns in
    hand recovers HP to the cap and no further."""
    econ = _econ(player_max_hp=100.0, bun_hp_restore=25.0)
    wd = _wd(wave_hp=2000.0, player_dps=10.0, enemy_dps=0.0)
    params = _params(heal_threshold_frac=0.9, bun_consume_rate=2.0)
    y0 = (wd.wave_hp, 50.0, 0.0, 0.0, 20.0, 0.0)  # start at 50 HP, 20 Buns
    outcome, _ = dynamics._run_one_wave(wd, params, econ, y0)
    assert outcome.hp_end <= econ.player_max_hp + 1e-9
    assert math.isclose(outcome.hp_end, econ.player_max_hp, abs_tol=1e-6)


def test_hp_and_bun_stay_in_bounds() -> None:
    """HP never leaves ``[0, max]`` and the Bun count never goes negative, even as
    consumption drains the last Bun under fire."""
    econ = _econ()
    wd = _wd(wave_hp=2000.0, player_dps=8.0, enemy_dps=6.0)
    params = _params(heal_threshold_frac=0.9, bun_consume_rate=3.0)
    y0 = (wd.wave_hp, 60.0, 0.0, 0.0, 1.0, 0.0)  # one Bun, then empty
    outcome, end = dynamics._run_one_wave(wd, params, econ, y0)
    assert 0.0 <= outcome.hp_min
    assert outcome.hp_end <= econ.player_max_hp + 1e-9
    assert end[dynamics.BUN] >= 0.0


def test_reward_stocks_are_monotonic() -> None:
    """EXP and Gold are inflow-only — they never decrease across the run."""
    _game, econ, _player, wds = _authority()
    run = run_scenario(wds, _params(bun_consume_rate=2.0), econ)
    exps = [o.exp_end for o in run.waves]
    golds = [o.gold_end for o in run.waves]
    assert exps == sorted(exps)
    assert golds == sorted(golds)


# --- Determinism ------------------------------------------------------------- #


def test_deterministic_no_rng() -> None:
    """The SD model has no randomness — two runs of the same inputs are identical
    (the determinism the pipeline needs)."""
    _game, econ, _player, wds = _authority()
    params = _params(bun_consume_rate=2.0)
    a = run_scenario(wds, params, econ)
    b = run_scenario(wds, params, econ)
    assert a == b


# --- The feedback loops (the nonlinearities) --------------------------------- #


def test_growth_feedback_speeds_clears() -> None:
    """The reinforcing growth loop: with ``growth_gain`` > 0 a higher Level feeds
    back into the kill rate, so the Boss clears strictly faster than at gain 0."""
    _game, econ, _player, wds = _authority()
    base = run_scenario(wds, _params(bun_consume_rate=2.0, growth_gain=0.0), econ)
    fast = run_scenario(wds, _params(bun_consume_rate=2.0, growth_gain=0.5), econ)
    assert base.waves[-1].clear_time is not None
    assert fast.waves[-1].clear_time is not None
    assert fast.waves[-1].clear_time < base.waves[-1].clear_time


def test_consumable_loop_turns_a_boss_loss_into_a_win() -> None:
    """The balancing consumable loop: with Bun healing OFF the accumulated
    laser-brawl kills the Player at the Boss; turning it ON lets the designed Bun
    economy clear the schedule — the macro prediction MC cannot make."""
    _game, econ, _player, wds = _authority()
    no_heal = run_scenario(wds, _params(bun_consume_rate=0.0), econ)
    with_heal = run_scenario(wds, _params(bun_consume_rate=2.0), econ)
    assert no_heal.died_at_wave == wds[-1].index  # bare brawl loses the Boss
    assert with_heal.cleared_schedule  # the consumable economy saves the run


def test_death_stops_the_chained_run() -> None:
    """A lethal Wave ends the run there — later Waves are not attempted."""
    econ = _econ()
    lethal = _wd(index=1, wave_hp=5000.0, player_dps=1.0, enemy_dps=50.0)
    trailing = _wd(index=2, wave_hp=10.0, player_dps=50.0)
    run = run_scenario((lethal, trailing), _params(), econ)
    assert run.died_at_wave == 1
    assert len(run.waves) == 1  # the run stopped; wave 2 never ran
    assert not run.cleared_schedule


# --- From the JSON authority alone (AC1) ------------------------------------- #


def test_build_wave_dynamics_from_authority() -> None:
    """The per-Wave projection reads only already-parsed authority data and
    produces one sane coefficient set per Wave (positive HP/DPS/reward)."""
    game, econ, _player, wds = _authority()
    assert len(wds) == len(game.waves)
    for wd in wds:
        assert wd.wave_hp > 0.0
        assert wd.player_dps > 0.0
        assert wd.enemy_dps > 0.0
        assert wd.exp_reward > 0.0
        assert wd.gold_reward > 0.0


def test_difficulty_ramp_peaks_at_the_boss() -> None:
    """The difficulty index (HP-cost to clear) peaks on the final (Boss) Wave —
    the ramp's design intent (AC2's difficulty target)."""
    _game, econ, _player, wds = _authority()
    diffs = [wd.difficulty(econ.player_max_hp) for wd in wds]
    assert diffs[-1] == max(diffs)
    assert diffs[-1] > 1.0  # the Boss is lethal to the bare laser-brawl
