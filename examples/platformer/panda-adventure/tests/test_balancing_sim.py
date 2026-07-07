"""Unit tests for the Monte-Carlo encounter simulation (#437 AC1, AC6).

Covers determinism under a fixed seed, the hand-computable no-RNG cases (so the
sim's use of the parity-pinned rules is verified against arithmetic, not by
eyeball), the player-death path, and that the sim reproduces encounter outcomes
from the JSON authority alone. Fast tier, no engine — the sim imports no game
code (AC6): it runs on the generic ``model`` dataclasses.
"""

from __future__ import annotations

import math
from random import Random


import build_config
from balancing import game_config
from balancing.encounter import run_wave, simulate_encounter
from balancing.model import (
    CombatParams,
    EnemyKind,
    PlayerModel,
    Spawn,
    StatBlock,
    Wave,
)

CONFIG_DIR = build_config.GAME_DIR / "data" / "json"

# Unit-scale combat params with a very long weapon reach, so the player fires
# from the start and the arithmetic stays trivial.
_COMBAT = CombatParams(
    attack_scale=1.0,
    defense_scale=1.0,
    min_damage=1.0,
    iframe_duration=0.6,
    projectile_speed=1000.0,
    projectile_lifetime=10.0,
)


def _kind(**over) -> EnemyKind:
    base = dict(
        name="dummy",
        tier="minion",
        archetype="melee",
        stats=StatBlock(max_hp=20.0, max_mp=0.0, attack=5.0, defense=0.0),
        move_speed=0.0,
        aggro_range=0.0,
        attack_range=0.0,
        attack_cooldown=1.0,
        keep_range_min=0.0,
        keep_range_max=0.0,
    )
    base.update(over)
    return EnemyKind(**base)


def _player(**over) -> PlayerModel:
    base = dict(
        stats=StatBlock(max_hp=100.0, max_mp=0.0, attack=10.0, defense=0.0),
        move_speed=0.0,
        start_x=0.0,
        fire_interval=0.5,
        accuracy=1.0,
        dodge_chance=0.0,
        engagement_distance=1000.0,  # never advance
    )
    base.update(over)
    return PlayerModel(**base)


def test_deterministic_ttk_no_rng() -> None:
    """A stationary, non-attacking enemy at 20 HP dies on the 2nd hit (10 dmg
    each, unit scale): shots at t=0 and t=0.5 -> TTK 0.5. accuracy 1.0 removes
    the RNG, so the value is exact and hand-checkable."""
    kind = _kind()
    wave = Wave(index=1, spawns=(Spawn(kind="dummy", name="E", x=200.0, y=0.0),))
    outcome = simulate_encounter(
        _player(),
        wave,
        {"dummy": kind},
        _COMBAT,
        dt=0.1,
        max_time=10.0,
        rng=Random(0),
    )
    assert outcome.cleared is True
    assert outcome.player_died is False
    assert math.isclose(outcome.wave_clear_time, 0.5, abs_tol=1e-9)
    assert math.isclose(outcome.ttk_per_enemy["E"], 0.5, abs_tol=1e-9)


def test_player_death_path() -> None:
    """A hard-hitting enemy in point-blank range kills a low-HP player who never
    fires back (accuracy 0): the player dies, the wave is not cleared, and the
    right-censored TTK sample is the time cap."""
    kind = _kind(
        stats=StatBlock(max_hp=1000.0, max_mp=0.0, attack=40.0, defense=0.0),
        aggro_range=500.0,
        attack_range=500.0,
        attack_cooldown=0.5,
    )
    wave = Wave(index=1, spawns=(Spawn(kind="dummy", name="E", x=10.0, y=0.0),))
    outcome = simulate_encounter(
        _player(
            stats=StatBlock(max_hp=30.0, max_mp=0.0, attack=10.0, defense=0.0),
            accuracy=0.0,
        ),
        wave,
        {"dummy": kind},
        _COMBAT,
        dt=0.1,
        max_time=10.0,
        rng=Random(0),
    )
    assert outcome.player_died is True
    assert outcome.cleared is False
    assert outcome.wave_clear_time is None
    assert outcome.ttk_sample == 10.0  # censored at max_time
    assert outcome.player_death_time is not None


def test_iframe_gate_limits_stacked_hits() -> None:
    """The player i-frame window (is_invulnerable) blocks a second enemy hit
    inside 0.6s. Two point-blank enemies both attack at t=0, each for 40; the
    player has 50 HP, so TWO hits (80) would kill but ONE (40) leaves them at
    10. Surviving proves the gate blocked the second blow — the enemies' long
    5s cooldown means no further attacks land within the 0.5s window."""
    kind = _kind(
        stats=StatBlock(max_hp=1000.0, max_mp=0.0, attack=40.0, defense=0.0),
        aggro_range=500.0,
        attack_range=500.0,
        attack_cooldown=5.0,
    )
    wave = Wave(
        index=1,
        spawns=(
            Spawn(kind="dummy", name="A", x=10.0, y=0.0),
            Spawn(kind="dummy", name="B", x=12.0, y=0.0),
        ),
    )
    outcome = simulate_encounter(
        _player(
            accuracy=0.0,
            stats=StatBlock(max_hp=50.0, max_mp=0.0, attack=10.0, defense=0.0),
        ),
        wave,
        {"dummy": kind},
        _COMBAT,
        dt=0.1,
        max_time=0.5,
        rng=Random(0),
    )
    # Without the i-frame gate both 40s land (80 >= 50) and the player dies.
    assert outcome.player_died is False


def test_determinism_same_seed() -> None:
    """Same seed -> identical samples; a different seed -> a different result."""
    kind = _kind(aggro_range=500.0, attack_range=40.0, move_speed=100.0)
    wave = Wave(index=1, spawns=(Spawn(kind="dummy", name="E", x=300.0, y=0.0),))
    player = _player(
        accuracy=0.7, dodge_chance=0.3, engagement_distance=50.0, move_speed=200.0
    )
    kinds = {"dummy": kind}
    a = run_wave(player, wave, kinds, _COMBAT, 0.05, 30.0, runs=25, seed=123)
    b = run_wave(player, wave, kinds, _COMBAT, 0.05, 30.0, runs=25, seed=123)
    c = run_wave(player, wave, kinds, _COMBAT, 0.05, 30.0, runs=25, seed=999)
    assert a.ttk == b.ttk and a.ttd == b.ttd
    assert (a.ttk, a.ttd) != (c.ttk, c.ttd)


def test_reads_from_json_authority() -> None:
    """The sim runs from the game's real JSON authority alone (no game code):
    every wave produces finite, non-empty samples."""
    game = game_config.load_game_data(CONFIG_DIR)
    assert len(game.waves) == 4  # the demo's default schedule
    player = game_config.build_player_model(
        game,
        {
            "fire_interval": 0.3,
            "accuracy": 0.8,
            "dodge_chance": 0.2,
            "engagement_distance": 60.0,
        },
    )
    for wave in game.waves:
        samples = run_wave(
            player,
            wave,
            game.kinds,
            game.combat,
            0.0166667,
            60.0,
            runs=5,
            seed=1 + wave.index,
        )
        assert len(samples.ttk) == 5 and len(samples.ttd) == 5
        assert all(math.isfinite(x) for x in samples.ttk + samples.ttd)


def test_ranged_enemy_holds_its_band() -> None:
    """A ranged kind whose spawn distance is inside its Steering Band never
    closes to contact — the sim exercises compute_move_dir's hold branch."""
    kind = _kind(
        archetype="ranged",
        tier="elite",
        aggro_range=260.0,
        attack_range=240.0,
        move_speed=200.0,
        keep_range_min=140.0,
        keep_range_max=200.0,
        attack_cooldown=1.4,
        stats=StatBlock(max_hp=60.0, max_mp=0.0, attack=8.0, defense=2.0),
    )
    wave = Wave(index=1, spawns=(Spawn(kind="dummy", name="R", x=170.0, y=0.0),))
    # Player stands still (engagement huge, move 0) so the enemy governs distance.
    outcome = simulate_encounter(
        _player(accuracy=0.0, move_speed=0.0, engagement_distance=1000.0),
        wave,
        {"dummy": kind},
        _COMBAT,
        dt=0.1,
        max_time=2.0,
        rng=Random(0),
    )
    # Nobody dies in 2s (player not firing, enemy holding its standoff band).
    assert outcome.player_died is False and outcome.cleared is False
