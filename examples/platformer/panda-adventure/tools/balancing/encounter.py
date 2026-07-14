"""The Monte-Carlo encounter simulation — the pipeline's micro engine.

One encounter pits the modeled player against one wave and runs a fixed-timestep
simulation to an outcome — per-enemy Time-To-Kill, whether/when the player died
(Time-To-Die), and whether the wave was cleared. The gameplay rules are the pure
functions in ``rules``; this module owns only the orchestration a game controller
would own in-engine (the clock, movement/projectile integration, the warp phase
machine, RNG, mutation) — never a second copy of a rule.

Attack delivery, at first-order fidelity:

- **Contact**: a ``rules.can_attack``-gated immediate strike through the
  player's i-frame gate, mitigated by the equipment-composed defender.
- **Ranged bolts**: an attack spawns a traveling bolt (per-kind speed/lifetime/
  spawn offset); damage lands on ARRIVAL (swept 1D contact against the target's
  box), and an expired bolt despawns harmless. The player's bolts travel the
  same way — a shot's damage is delayed by ``distance / projectile_speed``.
- **The warp kit**: the ``rules.should_warp`` gate opens the tell (steering and
  attack suspended), the blink relocates to the pure far-side landing clamped to
  the arena (inset by the body's half-width) and drops a slow field there, then
  a no-attack recovery precedes normal AI. While the player is inside an active
  field, the player's movement and the player's bolts inside it are slowed by
  the field's factor; fire cadence stays full speed (input registers — slowed,
  not stunned).

Spatial model (deliberately 1D): actors live on a single horizontal ground line —
the model targets games whose encounter steering is horizontal. Verticality is
irrelevant to encounter pacing, so ``y`` is pinned to 0: the rules' full-2D
distance reduces to the horizontal gap, and the y components of spawn offsets,
``warp_offset``, and the field sphere project onto the line (a documented model
assumption a targets file should restate for its game).

The Monte-Carlo variability is the modeled human: the player's shots land with
probability ``accuracy`` (rolled at fire time — a missed shot spawns no damaging
bolt) and the player evades an otherwise-landing enemy attack — contact or bolt
arrival — with probability ``dodge_chance``. Everything else is deterministic,
so a fixed RNG seed yields an identical outcome (the determinism the pipeline
needs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

from . import rules
from .model import CombatParams, EnemyKind, PlayerModel, Wave

_INF = float("inf")


@dataclass(frozen=True)
class TimeField:
    """One active slow field: the static zone a warp kind's blink drops at its
    landing. Injectable as an initial condition for deterministic tests;
    normally spawned by a warp kind's blink."""

    center_x: float
    radius: float
    factor: float
    expires_at: float


@dataclass
class _Bolt:
    """One traveling bolt (either side): swept 1D motion, damage on arrival."""

    x: float
    direction: float  # -1.0 or 1.0
    speed: float
    half_width: float
    expires_at: float
    attack: float  # the shooter's attack stat at fire time


@dataclass
class _EnemyState:
    """One enemy instance's live sim state."""

    kind: EnemyKind
    name: str
    x: float
    hp: float
    last_attack_time: float = rules.NEVER
    ttk: float | None = None  # when it died (None while alive)
    # The warp rotation: "" (none) / "tell" / "recovery", when the in-flight
    # phase ends, and the cooldown stamp (NEVER = the first warp is gated by
    # distance alone).
    warp_phase: str = ""
    warp_phase_until: float = 0.0
    last_warp_time: float = rules.NEVER


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


def _player_time_factor(fields: list[TimeField], x: float, t: float) -> float:
    """The player's current slow factor: the factor of an active field
    containing the player, else 1.0. Keeping ``time_field_duration`` strictly
    below ``warp_cooldown`` guarantees at most one active field."""
    for f in fields:
        if f.expires_at > t and rules.is_inside_field(
            x, 0.0, f.center_x, 0.0, f.radius
        ):
            return f.factor
    return 1.0


def _sweep_hits(bolt: _Bolt, new_x: float, target_x: float, target_half: float) -> bool:
    """Swept 1D contact: did the bolt's tick segment reach the target's box?
    Swept (segment vs interval), so a fast bolt cannot tunnel through in one
    discrete step."""
    reach = bolt.half_width + target_half
    lo = min(bolt.x, new_x) - reach
    hi = max(bolt.x, new_x) + reach
    return lo <= target_x <= hi


def simulate_encounter(
    player: PlayerModel,
    wave: Wave,
    kinds: dict[str, EnemyKind],
    combat: CombatParams,
    dt: float,
    max_time: float,
    rng: Random,
    arena_min_x: float = -_INF,
    arena_max_x: float = _INF,
    initial_fields: list[TimeField] | None = None,
) -> EncounterOutcome:
    """Run one encounter to its outcome (see :class:`EncounterOutcome`).

    Each tick, in order: the player moves (slowed inside an active field) and
    fires on cadence; the player's bolts advance (slowed inside a field) and
    resolve arrivals; each enemy runs its warp rotation or steers/attacks by the
    pure rules; enemy bolts advance and resolve arrivals through the i-frame and
    dodge gates against the equipment-composed defender.
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
    defender_defense = player.defender_stats.defense
    weapon_range = combat.player_weapon_range
    fields: list[TimeField] = list(initial_fields or [])
    player_bolts: list[_Bolt] = []
    enemy_bolts: list[_Bolt] = []

    def damage_player(attack: float, now: float) -> None:
        """One enemy attack arriving at the Player: i-frame gate, dodge roll,
        then the symmetric damage formula against the composed defender."""
        if rules.is_invulnerable(ps.last_hit_time, now, combat.iframe_duration):
            return
        if rng.random() < player.dodge_chance:
            return
        dmg = rules.compute_damage(
            attack,
            defender_defense,
            combat.attack_scale,
            combat.defense_scale,
            combat.min_damage,
        )
        ps.hp = max(0.0, ps.hp - dmg)
        ps.last_hit_time = now

    def damage_enemy(target: _EnemyState, attack: float, now: float) -> None:
        """One player hit landing on an enemy (the enemy side has no dodge)."""
        dmg = rules.compute_damage(
            attack,
            target.kind.stats.defense,
            combat.attack_scale,
            combat.defense_scale,
            combat.min_damage,
        )
        target.hp = max(0.0, target.hp - dmg)
        if rules.is_dead(target.hp) and target.ttk is None:
            target.ttk = now

    t = 0.0
    player_death_time: float | None = None
    # Step until the wave is cleared, the Player dies, or the cap is reached.
    while t < max_time:
        living = [e for e in enemies if not rules.is_dead(e.hp)]
        if not living:
            break
        fields = [f for f in fields if f.expires_at > t]
        player_factor = _player_time_factor(fields, ps.x, t)

        # --- Player: close to the engagement distance (slowed inside a
        # field), then fire on cadence (input registers at full speed) ---
        target = _nearest(ps.x, living)
        gap = target.x - ps.x
        advance = abs(gap) - player.engagement_distance
        if advance > 0.0:
            step = min(player.move_speed * player_factor * dt, advance)
            ps.x += step if gap > 0.0 else -step

        if rules.is_attack_ready(ps.last_fire_time, t, player.fire_interval):
            in_range = [e for e in living if abs(e.x - ps.x) <= weapon_range]
            if in_range:
                shot_target = _nearest(ps.x, in_range)
                ps.last_fire_time = t
                # Accuracy is rolled at fire time: a missed shot spawns no
                # damaging bolt (the documented player-model assumption).
                if rng.random() < player.accuracy:
                    facing = 1.0 if shot_target.x >= ps.x else -1.0
                    player_bolts.append(
                        _Bolt(
                            x=ps.x + facing * combat.projectile_spawn_offset_x,
                            direction=facing,
                            speed=combat.projectile_speed,
                            half_width=combat.projectile_half_width,
                            expires_at=t + combat.projectile_lifetime,
                            attack=player.stats.attack,
                        )
                    )

        # --- Player bolts: advance (slowed inside an active field — the
        # despawn timer stays on the real clock), resolve arrivals ---
        surviving_player_bolts: list[_Bolt] = []
        for bolt in player_bolts:
            if t >= bolt.expires_at:
                continue
            bolt_factor = _player_time_factor(fields, bolt.x, t)
            new_x = bolt.x + bolt.direction * bolt.speed * bolt_factor * dt
            candidates = [
                e
                for e in living
                if not rules.is_dead(e.hp)
                and _sweep_hits(bolt, new_x, e.x, e.kind.half_width)
            ]
            if candidates:
                # The FIRST body along the flight (one bolt, at most one hit).
                first = min(candidates, key=lambda e: (e.x - bolt.x) * bolt.direction)
                damage_enemy(first, bolt.attack, t)
                continue  # bolt spent
            bolt.x = new_x
            surviving_player_bolts.append(bolt)
        player_bolts = surviving_player_bolts

        # --- Enemies: the warp rotation, then steering + attack delivery ---
        for e in living:
            if rules.is_dead(e.hp):  # killed by this tick's bolt arrivals
                continue
            # An in-flight warp phase suspends steering and attack.
            if e.warp_phase:
                if t < e.warp_phase_until:
                    continue
                if e.warp_phase == "tell":
                    # The blink: the pure far-side landing clamped to the arena
                    # inset by the body's half-width, the field dropped at the
                    # SAME instant (the zone is the warp's wake), then recovery.
                    landing_x, _ = rules.warp_landing(
                        e.x,
                        0.0,
                        ps.x,
                        0.0,
                        e.kind.warp_offset_x,
                        0.0,
                        arena_min_x + e.kind.half_width,
                        arena_max_x - e.kind.half_width,
                    )
                    e.x = landing_x
                    fields.append(
                        TimeField(
                            center_x=landing_x,
                            radius=e.kind.time_field_radius,
                            factor=e.kind.time_field_factor,
                            expires_at=t + e.kind.time_field_duration,
                        )
                    )
                    e.warp_phase = "recovery"
                    e.warp_phase_until = t + e.kind.warp_recovery_duration
                else:
                    e.warp_phase = ""
                continue
            if rules.should_warp(  # the blink-engage gate
                e.x,
                0.0,
                ps.x,
                0.0,
                e.kind.aggro_range,
                e.kind.warp_trigger_range,
                e.kind.warp_cooldown,
                e.last_warp_time,
                t,
            ):
                # The tell begins: the cooldown is stamped at the DECISION
                # moment (it spans the whole rotation).
                e.last_warp_time = t
                e.warp_phase = "tell"
                e.warp_phase_until = t + e.kind.warp_tell_duration
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
                if e.kind.archetype == "ranged":
                    # Bolt delivery: aim at the player at fire time; a player
                    # exactly overhead (dx == 0) fires nothing (the zero-aim
                    # guard) though the cooldown is stamped.
                    aim = ps.x - e.x
                    if aim != 0.0:
                        direction = 1.0 if aim > 0.0 else -1.0
                        enemy_bolts.append(
                            _Bolt(
                                x=e.x + direction * e.kind.projectile_spawn_offset_x,
                                direction=direction,
                                speed=e.kind.projectile_speed,
                                half_width=e.kind.projectile_half_width,
                                expires_at=t + e.kind.projectile_lifetime,
                                attack=e.kind.stats.attack,
                            )
                        )
                else:
                    # Contact delivery (every non-ranged archetype).
                    damage_player(e.kind.stats.attack, t)

        # --- Enemy bolts: advance (never slowed — only the player's side
        # slows), resolve arrivals at the player ---
        surviving_enemy_bolts: list[_Bolt] = []
        for bolt in enemy_bolts:
            if t >= bolt.expires_at:
                continue
            new_x = bolt.x + bolt.direction * bolt.speed * dt
            if _sweep_hits(bolt, new_x, ps.x, player.half_width):
                damage_player(bolt.attack, t)
                continue  # bolt spent
            bolt.x = new_x
            surviving_enemy_bolts.append(bolt)
        enemy_bolts = surviving_enemy_bolts

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
    arena_min_x: float = -_INF,
    arena_max_x: float = _INF,
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
        outcome = simulate_encounter(
            player,
            wave,
            kinds,
            combat,
            dt,
            max_time,
            rng,
            arena_min_x=arena_min_x,
            arena_max_x=arena_max_x,
        )
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
