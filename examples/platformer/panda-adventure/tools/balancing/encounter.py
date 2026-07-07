"""The Monte-Carlo encounter simulation (game-agnostic structure, gADR-0011).

One encounter pits the modeled Player against one Wave and runs a fixed-timestep
simulation to an outcome — per-enemy Time-To-Kill, whether/when the Player died
(Time-To-Die), and whether the Wave was cleared. The gameplay rules are the
parity-pinned pure functions in ``rules`` (the ``CombatSystem``/``EnemyAI``
seams); this module owns only the orchestration a controller would own in-engine
(the clock, movement integration, RNG, mutation) — never a second copy of a
rule.

Spatial model (deliberately 1D): actors live on a single horizontal ground line,
matching the grounded-platformer steering, which is horizontal. Verticality is a
platformer detail irrelevant to encounter pacing, so ``y`` is pinned to 0 and the
seam's full-2D distance reduces to the horizontal gap. This keeps the sim honest
about what it models (the closing/attack/damage loop) without pretending to
reproduce jump arcs.

The Monte-Carlo variability is the modeled human: the Player's shots land with
probability ``accuracy`` and the Player evades an otherwise-landing enemy blow
with probability ``dodge_chance``. Everything else is deterministic, so a fixed
RNG seed yields an identical outcome (the determinism the pipeline needs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

from . import rules
from .model import CombatParams, EnemyKind, PlayerModel, Wave


@dataclass
class _EnemyState:
    """One enemy instance's live sim state."""

    kind: EnemyKind
    name: str
    x: float
    hp: float
    last_attack_time: float = rules.NEVER
    ttk: float | None = None  # when it died (None while alive)


@dataclass
class _PlayerState:
    """The Player's live sim state."""

    x: float
    hp: float
    last_fire_time: float = rules.NEVER
    last_hit_time: float = rules.NEVER


@dataclass(frozen=True)
class EncounterOutcome:
    """The result of one encounter run.

    ``ttk_per_enemy`` maps each spawn name to its kill time (None if it outlived
    the run). ``wave_clear_time`` is set iff every enemy died. ``player_died`` /
    ``player_death_time`` record the Player's fate. ``ttk_sample`` and
    ``ttd_sample`` are the right-censored scalars the statistics stage
    aggregates: TTK is the clear time (or the time cap if never cleared), TTD is
    the death time (or the time cap if the Player survived).
    """

    ttk_per_enemy: dict[str, float | None]
    wave_clear_time: float | None
    player_died: bool
    player_death_time: float | None
    ttk_sample: float
    ttd_sample: float
    cleared: bool


def _nearest(player_x: float, living: list[_EnemyState]) -> _EnemyState:
    return min(living, key=lambda e: abs(e.x - player_x))


def simulate_encounter(
    player: PlayerModel,
    wave: Wave,
    kinds: dict[str, EnemyKind],
    combat: CombatParams,
    dt: float,
    max_time: float,
    rng: Random,
) -> EncounterOutcome:
    """Run one encounter to its outcome (see :class:`EncounterOutcome`).

    Each tick, in order: the Player closes toward the nearest living enemy
    (holding ``engagement_distance``) and fires on cadence at the nearest enemy
    in weapon range; then each enemy steers by ``EnemyAI.compute_move_dir`` and,
    when ``EnemyAI.can_attack`` allows, strikes the Player through the i-frame
    gate. Damage is ``CombatSystem.compute_damage`` in both directions; death is
    ``CombatSystem.is_dead``.
    """
    enemies = [
        _EnemyState(
            kind=kinds[s.kind],
            name=s.name,
            x=s.x,
            hp=kinds[s.kind].stats.max_hp,
        )
        for s in wave.spawns
    ]
    ps = _PlayerState(x=player.start_x, hp=player.stats.max_hp)
    weapon_range = combat.player_weapon_range

    t = 0.0
    player_death_time: float | None = None
    # Step until the wave is cleared, the Player dies, or the cap is reached.
    while t < max_time:
        living = [e for e in enemies if not rules.is_dead(e.hp)]
        if not living:
            break

        # --- Player: close to the engagement distance, then fire on cadence ---
        target = _nearest(ps.x, living)
        gap = target.x - ps.x
        advance = abs(gap) - player.engagement_distance
        if advance > 0.0:
            step = min(player.move_speed * dt, advance)
            ps.x += step if gap > 0.0 else -step

        if rules.is_attack_ready(ps.last_fire_time, t, player.fire_interval):
            in_range = [e for e in living if abs(e.x - ps.x) <= weapon_range]
            if in_range:
                shot_target = _nearest(ps.x, in_range)
                ps.last_fire_time = t
                if rng.random() < player.accuracy:
                    dmg = rules.compute_damage(
                        player.stats.attack,
                        shot_target.kind.stats.defense,
                        combat.attack_scale,
                        combat.defense_scale,
                        combat.min_damage,
                    )
                    shot_target.hp = max(0.0, shot_target.hp - dmg)
                    if rules.is_dead(shot_target.hp) and shot_target.ttk is None:
                        shot_target.ttk = t

        # --- Enemies: steer, then strike through the Player's i-frame gate ---
        for e in living:
            if rules.is_dead(e.hp):  # killed by this tick's shot
                continue
            direction = rules.compute_move_dir(
                e.x,
                0.0,
                ps.x,
                0.0,
                e.kind.aggro_range,
                e.kind.keep_range_min,
                e.kind.keep_range_max,
            )
            e.x += direction * e.kind.move_speed * dt
            if rules.can_attack(
                e.x,
                0.0,
                ps.x,
                0.0,
                e.kind.aggro_range,
                e.kind.attack_range,
                e.kind.attack_cooldown,
                e.last_attack_time,
                t,
            ):
                e.last_attack_time = t
                if not rules.is_invulnerable(
                    ps.last_hit_time, t, combat.iframe_duration
                ):
                    if rng.random() >= player.dodge_chance:
                        dmg = rules.compute_damage(
                            e.kind.stats.attack,
                            player.stats.defense,
                            combat.attack_scale,
                            combat.defense_scale,
                            combat.min_damage,
                        )
                        ps.hp = max(0.0, ps.hp - dmg)
                        ps.last_hit_time = t
        if rules.is_dead(ps.hp):
            player_death_time = t
            break

        t += dt

    ttk_per_enemy = {e.name: e.ttk for e in enemies}
    cleared = all(rules.is_dead(e.hp) for e in enemies)
    wave_clear_time = (
        max(e.ttk for e in enemies if e.ttk is not None) if cleared else None
    )
    player_died = player_death_time is not None
    ttk_sample = wave_clear_time if wave_clear_time is not None else max_time
    ttd_sample = player_death_time if player_death_time is not None else max_time
    return EncounterOutcome(
        ttk_per_enemy=ttk_per_enemy,
        wave_clear_time=wave_clear_time,
        player_died=player_died,
        player_death_time=player_death_time,
        ttk_sample=ttk_sample,
        ttd_sample=ttd_sample,
        cleared=cleared,
    )


@dataclass(frozen=True)
class WaveSamples:
    """The per-run scalars collected across a wave's Monte-Carlo runs."""

    wave: int
    ttk: list[float] = field(default_factory=list)
    ttd: list[float] = field(default_factory=list)
    clears: int = 0
    deaths: int = 0
    runs: int = 0


def run_wave(
    player: PlayerModel,
    wave: Wave,
    kinds: dict[str, EnemyKind],
    combat: CombatParams,
    dt: float,
    max_time: float,
    runs: int,
    seed: int,
) -> WaveSamples:
    """Run ``runs`` Monte-Carlo encounters of one wave and collect the samples.

    Seeds a fresh ``Random(seed)`` and draws every run from it, so the whole
    wave is reproducible from ``seed`` alone. The caller derives a distinct seed
    per wave (see ``report``) so waves are independent yet deterministic.
    """
    rng = Random(seed)
    ttk: list[float] = []
    ttd: list[float] = []
    clears = 0
    deaths = 0
    for _ in range(runs):
        outcome = simulate_encounter(player, wave, kinds, combat, dt, max_time, rng)
        ttk.append(outcome.ttk_sample)
        ttd.append(outcome.ttd_sample)
        clears += 1 if outcome.cleared else 0
        deaths += 1 if outcome.player_died else 0
    return WaveSamples(
        wave=wave.index,
        ttk=ttk,
        ttd=ttd,
        clears=clears,
        deaths=deaths,
        runs=runs,
    )
