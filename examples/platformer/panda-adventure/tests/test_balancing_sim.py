"""Unit tests for the Monte-Carlo encounter simulation (#437 AC1, AC6).

Covers determinism under a fixed seed, the hand-computable no-RNG cases (so the
sim's use of the parity-pinned rules is verified against arithmetic, not by
eyeball), the player-death path, bolt travel time (gADR-0003 delivery), the
Boss Warp kit's blink + Time Dilation Field (gADR-0009), the Spacesuit-composed
defender (gADR-0008), and that the sim reproduces encounter outcomes from the
JSON authority alone. Fast tier, no engine — the sim imports no game code
(AC6): it runs on the generic ``model`` dataclasses.
"""

from __future__ import annotations

import json
import math
from random import Random

import build_config
from balancing import game_config
from balancing.encounter import TimeField, run_wave, simulate_encounter
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
# from the start and the arithmetic stays trivial. Zero spawn offset and zero
# half-widths keep contact geometry exact (a bolt hits when its swept segment
# reaches the target's x).
_COMBAT = CombatParams(
    attack_scale=1.0,
    defense_scale=1.0,
    min_damage=1.0,
    iframe_duration=0.6,
    projectile_speed=1000.0,
    projectile_lifetime=10.0,
)

_PLAYER_MODEL_PARAMS = {
    "fire_interval": 0.3,
    "accuracy": 0.8,
    "dodge_chance": 0.2,
    "engagement_distance": 60.0,
}


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
    each, unit scale) — and each hit lands with the bolt's TRAVEL delay, not at
    fire time: shots fired at t=0 and t=0.5 from x=0 cross the 200px gap at
    1000px/s (dt 0.1 -> 100px/tick), arriving one tick later, so the kill
    lands at t=0.6. accuracy 1.0 removes the RNG: exact and hand-checkable."""
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
    assert math.isclose(outcome.wave_clear_time, 0.6, abs_tol=1e-6)
    assert math.isclose(outcome.ttk_per_enemy["E"], 0.6, abs_tol=1e-6)


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


def test_spacesuit_defender_composition_from_json() -> None:
    """Finding-2 pin (gADR-0008): the modeled defender's defense is the combat
    config's base defense PLUS the items config's ``spacesuit_defense`` —
    composed exactly like ``ItemSystem.effective_defender`` (other stats copied,
    the attacker side stays the BASE block)."""
    game = game_config.load_game_data(CONFIG_DIR)
    combat_doc = json.loads((CONFIG_DIR / "combat_config.json").read_text())
    items_doc = json.loads((CONFIG_DIR / "items_config.json").read_text())
    player = game_config.build_player_model(game, _PLAYER_MODEL_PARAMS)
    base_defense = combat_doc["player_stats"]["defense"]
    bonus = items_doc["spacesuit_defense"]
    assert player.defender is not None
    assert player.defender.defense == base_defense + bonus
    # The composition copies the rest of the block unchanged...
    assert player.defender.max_hp == player.stats.max_hp
    assert player.defender.max_mp == player.stats.max_mp
    assert player.defender.attack == player.stats.attack
    # ...and never touches the attacker-side base block.
    assert player.stats.defense == base_defense


def test_defender_mitigates_incoming_damage() -> None:
    """The composed defender feeds the mitigation term of enemy->player damage:
    a 10-attack contact hit deals 6 against a defense-4 defender (survivable at
    10 HP) but 10 against the bare block (lethal)."""
    kind = _kind(
        stats=StatBlock(max_hp=1000.0, max_mp=0.0, attack=10.0, defense=0.0),
        aggro_range=500.0,
        attack_range=500.0,
        attack_cooldown=5.0,
    )
    wave = Wave(index=1, spawns=(Spawn(kind="dummy", name="E", x=10.0, y=0.0),))
    stats = StatBlock(max_hp=10.0, max_mp=0.0, attack=10.0, defense=0.0)
    suited = simulate_encounter(
        _player(
            accuracy=0.0,
            stats=stats,
            defender=StatBlock(max_hp=10.0, max_mp=0.0, attack=10.0, defense=4.0),
        ),
        wave,
        {"dummy": kind},
        _COMBAT,
        dt=0.1,
        max_time=0.5,
        rng=Random(0),
    )
    bare = simulate_encounter(
        _player(accuracy=0.0, stats=stats),
        wave,
        {"dummy": kind},
        _COMBAT,
        dt=0.1,
        max_time=0.5,
        rng=Random(0),
    )
    assert suited.player_died is False  # 10 - 4 = 6 < 10 HP
    assert bare.player_died is True  # 10 - 0 = 10 >= 10 HP


def test_enemy_bolt_travel_delays_damage() -> None:
    """Ranged delivery (gADR-0003) is a traveling bolt, not an instant hit: a
    lethal bolt fired at t=0 from 200px at 100px/s reaches the player only at
    t=1.9 (the swept segment covers x=0 on the 20th advance), so a shorter run
    ends unhurt and a longer one records the death at the ARRIVAL time."""
    kind = _kind(
        archetype="ranged",
        stats=StatBlock(max_hp=100.0, max_mp=0.0, attack=20.0, defense=0.0),
        aggro_range=500.0,
        attack_range=500.0,
        attack_cooldown=100.0,  # exactly one bolt
        projectile_speed=100.0,
        projectile_lifetime=10.0,
    )
    wave = Wave(index=1, spawns=(Spawn(kind="dummy", name="R", x=200.0, y=0.0),))
    player = _player(
        accuracy=0.0,
        stats=StatBlock(max_hp=10.0, max_mp=0.0, attack=10.0, defense=0.0),
    )
    in_flight = simulate_encounter(
        player, wave, {"dummy": kind}, _COMBAT, dt=0.1, max_time=1.5, rng=Random(0)
    )
    assert in_flight.player_died is False  # the bolt is still traveling
    arrived = simulate_encounter(
        player, wave, {"dummy": kind}, _COMBAT, dt=0.1, max_time=3.0, rng=Random(0)
    )
    assert arrived.player_died is True
    assert arrived.player_death_time is not None
    assert math.isclose(arrived.player_death_time, 1.9, abs_tol=1e-6)


def _boss_kind(warp: bool) -> EnemyKind:
    """A tank Boss shape (contact hammer + the Warp kit when ``warp``)."""
    extra = (
        dict(
            warp_cooldown=8.0,
            warp_trigger_range=200.0,
            warp_offset_x=60.0,
            warp_tell_duration=0.5,
            warp_recovery_duration=0.4,
            time_field_radius=160.0,
            time_field_factor=0.5,
            time_field_duration=3.0,
        )
        if warp
        else {}
    )
    return _kind(
        tier="boss",
        archetype="tank",
        stats=StatBlock(max_hp=1000.0, max_mp=0.0, attack=40.0, defense=0.0),
        move_speed=60.0,
        aggro_range=400.0,
        attack_range=80.0,
        attack_cooldown=2.0,
        keep_range_min=0.0,
        keep_range_max=80.0,
        **extra,
    )


def test_warp_blink_engages_past_the_walk() -> None:
    """The Warp kit (gADR-0009) is the anti-kite engage tool: a Boss 300px out
    (inside Aggro, beyond the trigger range) blinks to the pure far-side
    landing after its tell instead of walking, so its first hammer lands right
    after the no-attack recovery (~t=1.0) — a kit-less twin walking at 60px/s
    cannot reach its 80px attack range within 2s."""
    wave = Wave(index=1, spawns=(Spawn(kind="boss", name="B", x=300.0, y=0.0),))
    player = _player(
        accuracy=0.0,
        stats=StatBlock(max_hp=10.0, max_mp=0.0, attack=10.0, defense=0.0),
    )
    with_kit = simulate_encounter(
        player,
        wave,
        {"boss": _boss_kind(warp=True)},
        _COMBAT,
        dt=0.1,
        max_time=2.0,
        rng=Random(0),
    )
    assert with_kit.player_died is True
    assert with_kit.player_death_time is not None
    # Never before the tell + recovery windows end (the fair-exchange rule);
    # the upper bound allows the one-tick jitter of float time accumulation.
    assert with_kit.player_death_time >= 0.9 - 1e-9
    assert with_kit.player_death_time <= 1.0 + 0.1 + 1e-9
    without_kit = simulate_encounter(
        player,
        wave,
        {"boss": _boss_kind(warp=False)},
        _COMBAT,
        dt=0.1,
        max_time=2.0,
        rng=Random(0),
    )
    assert without_kit.player_died is False


def test_warp_landing_clamped_to_arena() -> None:
    """The blink landing honors the Arena clamp: the unclamped far-side landing
    (player.x - 60 = -60) is outside this kind's 30px hammer, so it must walk
    back in (first hit ~t=1.4); an arena floor at -10 clamps the landing to
    10px from the player — inside the hammer, first hit right after recovery
    (~t=1.0). The earlier kill pins that the clamp was applied."""
    kind = _kind(
        tier="boss",
        archetype="tank",
        stats=StatBlock(max_hp=1000.0, max_mp=0.0, attack=40.0, defense=0.0),
        move_speed=60.0,
        aggro_range=400.0,
        attack_range=30.0,
        attack_cooldown=2.0,
        keep_range_min=0.0,
        keep_range_max=30.0,
        warp_cooldown=8.0,
        warp_trigger_range=200.0,
        warp_offset_x=60.0,
        warp_tell_duration=0.5,
        warp_recovery_duration=0.4,
        time_field_radius=160.0,
        time_field_factor=0.5,
        time_field_duration=3.0,
    )
    wave = Wave(index=1, spawns=(Spawn(kind="boss", name="B", x=300.0, y=0.0),))
    player = _player(
        accuracy=0.0,
        stats=StatBlock(max_hp=10.0, max_mp=0.0, attack=10.0, defense=0.0),
    )
    clamped = simulate_encounter(
        player,
        wave,
        {"boss": kind},
        _COMBAT,
        dt=0.1,
        max_time=3.0,
        rng=Random(0),
        arena_min_x=-10.0,
        arena_max_x=1000.0,
    )
    unclamped = simulate_encounter(
        player,
        wave,
        {"boss": kind},
        _COMBAT,
        dt=0.1,
        max_time=3.0,
        rng=Random(0),
    )
    assert clamped.player_died and unclamped.player_died
    assert clamped.player_death_time is not None
    assert unclamped.player_death_time is not None
    # ~1.0 with a one-tick float-accumulation allowance; the unclamped landing
    # costs an extra >= 0.25s walk back into hammer range.
    assert clamped.player_death_time <= 1.0 + 0.1 + 1e-9
    assert unclamped.player_death_time >= clamped.player_death_time + 0.25


def test_time_field_slows_player_movement() -> None:
    """Inside an active Time Dilation Field the modeled player's movement runs
    at the config factor: closing 350px to a dormant target takes twice as long
    under factor 0.5, and the (fast-bolt) kill time shifts with it."""
    target = _kind(stats=StatBlock(max_hp=10.0, max_mp=0.0, attack=0.0, defense=0.0))
    wave = Wave(index=1, spawns=(Spawn(kind="dummy", name="T", x=400.0, y=0.0),))
    combat = CombatParams(
        attack_scale=1.0,
        defense_scale=1.0,
        min_damage=1.0,
        iframe_duration=0.6,
        projectile_speed=1000.0,
        projectile_lifetime=0.05,  # weapon range 50: the player must walk in
    )
    player = _player(move_speed=100.0, engagement_distance=0.0)
    slowed = simulate_encounter(
        player,
        wave,
        {"dummy": target},
        combat,
        dt=0.1,
        max_time=30.0,
        rng=Random(0),
        initial_fields=[
            TimeField(center_x=0.0, radius=1e6, factor=0.5, expires_at=1e6)
        ],
    )
    free = simulate_encounter(
        player,
        wave,
        {"dummy": target},
        combat,
        dt=0.1,
        max_time=30.0,
        rng=Random(0),
    )
    assert free.cleared and slowed.cleared
    assert free.wave_clear_time is not None and slowed.wave_clear_time is not None
    assert slowed.wave_clear_time > 1.5 * free.wave_clear_time


def test_time_field_slows_player_bolts_despawn_on_real_clock() -> None:
    """A slowed player bolt flies SHORTER, it does not linger (gADR-0009): its
    despawn timer stays on the real clock, so a bolt that reaches a 30px target
    within its 0.4s lifetime at full speed expires short of it at factor 0.5."""
    target = _kind(stats=StatBlock(max_hp=10.0, max_mp=0.0, attack=0.0, defense=0.0))
    wave = Wave(index=1, spawns=(Spawn(kind="dummy", name="T", x=30.0, y=0.0),))
    combat = CombatParams(
        attack_scale=1.0,
        defense_scale=1.0,
        min_damage=1.0,
        iframe_duration=0.6,
        projectile_speed=100.0,
        projectile_lifetime=0.4,  # full-speed reach 40 > 30; slowed reach 20 < 30
    )
    player = _player()
    free = simulate_encounter(
        player, wave, {"dummy": target}, combat, dt=0.1, max_time=2.0, rng=Random(0)
    )
    slowed = simulate_encounter(
        player,
        wave,
        {"dummy": target},
        combat,
        dt=0.1,
        max_time=2.0,
        rng=Random(0),
        initial_fields=[
            TimeField(center_x=0.0, radius=1e6, factor=0.5, expires_at=1e6)
        ],
    )
    assert free.cleared is True
    assert slowed.cleared is False  # every slowed bolt despawns short


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
    player = game_config.build_player_model(game, _PLAYER_MODEL_PARAMS)
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
            arena_min_x=game.arena_min_x,
            arena_max_x=game.arena_max_x,
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
        projectile_speed=520.0,
        projectile_lifetime=2.0,
        projectile_spawn_offset_x=30.0,
        projectile_half_width=7.0,
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
    # The player survives 2s (its 100 HP shrugs two 8-attack bolts) and the
    # enemy holds its standoff band, never brawling to contact.
    assert outcome.player_died is False and outcome.cleared is False
