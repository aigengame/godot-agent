"""The plain dataclasses the balancing pipeline runs on (game-agnostic).

These carry the numbers the encounter simulation and validate report need,
decoupled from any game's on-disk shape: the per-game adapter (``game_config``)
maps a game's JSON authority into these, and the generic core (``encounter``,
``statistics``, ``report``) consumes only these — never the raw JSON. Every
field is a bare scalar so the model imports nothing but ``dataclasses``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatBlock:
    """One actor's combat stat block — the symmetric attacker/defender contract
    of the damage formula (the game's ``StatsConfig``)."""

    max_hp: float
    max_mp: float
    attack: float
    defense: float


@dataclass(frozen=True)
class CombatParams:
    """The damage-formula and i-frame params, plus the player's Laser Gun bolt
    (speed, lifetime, spawn offset, half-width — the bolt is a traveling body,
    so damage lands on ARRIVAL, not at fire time) — from the combat config
    authority plus the Scale spec's ``player_projectile_size``."""

    attack_scale: float
    defense_scale: float
    min_damage: float
    iframe_duration: float
    projectile_speed: float
    projectile_lifetime: float
    projectile_spawn_offset_x: float = 0.0
    projectile_half_width: float = 0.0

    @property
    def player_weapon_range(self) -> float:
        """How far a player bolt can reach before its lifetime expires."""
        return self.projectile_speed * self.projectile_lifetime


@dataclass(frozen=True)
class EnemyKind:
    """One Enemy Kind's sim-relevant numbers: its stat block, the Archetype-AI
    gating params (Aggro Range, attack range/cooldown, Steering Band), its box
    half-width (bolt contact + the arena landing inset), the Ranged bolt block
    (gADR-0003 — present iff the kind is ranged), and the presence-gated Warp
    kit (gADR-0009 — ``warp_cooldown`` 0.0 means no kit, the ``WarpSystem``
    has-Warp predicate). Cosmetic and juice fields are irrelevant to TTK/TTD
    and omitted."""

    name: str
    tier: str
    archetype: str
    stats: StatBlock
    move_speed: float
    aggro_range: float
    attack_range: float
    attack_cooldown: float
    keep_range_min: float
    keep_range_max: float
    half_width: float = 0.0
    # Ranged bolt delivery (gADR-0003): the enemy bolt's motion + contact box.
    projectile_speed: float = 0.0
    projectile_lifetime: float = 0.0
    projectile_spawn_offset_x: float = 0.0
    projectile_half_width: float = 0.0
    # The Boss Warp kit (gADR-0009), presence-gated on warp_cooldown > 0.
    warp_cooldown: float = 0.0
    warp_trigger_range: float = 0.0
    warp_offset_x: float = 0.0
    warp_tell_duration: float = 0.0
    warp_recovery_duration: float = 0.0
    time_field_radius: float = 0.0
    time_field_factor: float = 1.0
    time_field_duration: float = 0.0


@dataclass(frozen=True)
class Spawn:
    """One Spawn Roster entry: which kind spawns where (its x on the ground)."""

    kind: str
    name: str
    x: float
    y: float


@dataclass(frozen=True)
class Wave:
    """One Wave: an ordered composition of spawns (a Spawn Roster)."""

    index: int
    spawns: tuple[Spawn, ...]


@dataclass(frozen=True)
class PlayerModel:
    """The stochastic player the Monte-Carlo sim runs — the design ASSUMPTIONS
    about how a player fights, not game runtime config.

    The stat block, move speed, spawn position, half-width, and the
    Spacesuit-composed ``defender`` block come from the game's JSON authority;
    the behavioral assumptions (``fire_interval``, ``accuracy``,
    ``dodge_chance``, ``engagement_distance``) are design inputs that live in the
    targets file, because the game has no Laser-Gun fire-rate config — firing is
    per-input-press, so the pipeline must model the human's cadence and aim.

    ``defender`` is the stat block incoming enemy damage mitigates against —
    the game's ``ItemSystem.effective_defender`` composition (base defense +
    the worn Spacesuit's bonus, gADR-0008). ``None`` falls back to ``stats``
    (an unequipped model)."""

    stats: StatBlock
    move_speed: float
    start_x: float
    fire_interval: float
    accuracy: float
    dodge_chance: float
    engagement_distance: float
    defender: StatBlock | None = None
    half_width: float = 0.0

    @property
    def defender_stats(self) -> StatBlock:
        """The block incoming damage mitigates against (the game's
        ``_defender_stats`` fallback shape)."""
        return self.defender if self.defender is not None else self.stats


@dataclass(frozen=True)
class SimConfig:
    """The simulation controls: the fixed timestep, the per-encounter time cap,
    the number of Monte-Carlo runs, and the base RNG seed (determinism)."""

    dt: float
    max_time: float
    runs: int
    seed: int


@dataclass(frozen=True)
class WaveTarget:
    """The design intent for one Wave: the intended time to clear it (TTK) and
    the intended player survival time (TTD)."""

    wave: int
    ttk: float
    ttd: float


@dataclass(frozen=True)
class Targets:
    """The full design intent: per-wave TTK/TTD targets and the relative
    tolerance the measured medians are checked against."""

    waves: tuple[WaveTarget, ...]
    tolerance: float

    def for_wave(self, index: int) -> WaveTarget | None:
        return next((w for w in self.waves if w.wave == index), None)


@dataclass(frozen=True)
class GameData:
    """The game-side inputs the sim needs, mapped out of the JSON authority."""

    player_stats: StatBlock
    player_move_speed: float
    player_start_x: float
    player_half_width: float
    spacesuit_defense: float
    combat: CombatParams
    kinds: dict[str, EnemyKind]
    waves: tuple[Wave, ...]
    # The authored Arena interval (gADR-0010) that clamps the Warp Blink's
    # landing; an infinite default means "no arena" (unit-test convenience).
    arena_min_x: float = float("-inf")
    arena_max_x: float = float("inf")
