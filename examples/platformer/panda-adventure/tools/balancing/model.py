"""The plain dataclasses the balancing pipeline runs on.

These carry the numbers the two engines need, decoupled from any game's
on-disk config shape: a per-game adapter (see the package docstring) maps the
game's config authority into these, and the pipeline (``encounter``,
``dynamics``, ``statistics``, ``report``, ``prediction``) consumes only these —
never the raw config files. Every field is a bare scalar or a plain mapping,
so the model imports nothing but ``dataclasses``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import rules


@dataclass(frozen=True)
class StatBlock:
    """One actor's combat stat block — the symmetric attacker/defender contract
    of the damage formula."""

    max_hp: float
    max_mp: float
    attack: float
    defense: float


def compose_defender(base: StatBlock, defense_bonus: float) -> StatBlock:
    """The worn-equipment defender composition every adapter needs: a fresh
    block copying ``base`` with ``defense`` raised by the equipment's bonus —
    the formula's mitigation term changes, the other stats copy unchanged.
    Public so adapters build ``GameData.player_defender`` without reaching
    into the ruleset internals."""
    return StatBlock(
        max_hp=base.max_hp,
        max_mp=base.max_mp,
        attack=base.attack,
        defense=rules.effective_defense(base.defense, defense_bonus),
    )


@dataclass(frozen=True)
class CombatParams:
    """The damage-formula and i-frame params, plus the player's ranged-weapon
    bolt (speed, lifetime, spawn offset, half-width — the bolt is a traveling
    body, so damage lands on ARRIVAL, not at fire time)."""

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
    """One enemy kind's sim-relevant numbers: its stat block, the archetype-AI
    gating params (aggro range, attack range/cooldown, steering band), its box
    half-width (bolt contact + the arena landing inset), the ranged bolt block,
    and the presence-gated warp kit (``warp_cooldown`` 0.0 means no kit — the
    has-warp predicate). ``archetype`` is the framework's delivery taxonomy,
    not a free-form label: the literal value ``"ranged"`` selects traveling-bolt
    delivery (and requires the bolt block), any other value delivers by contact
    — an adapter must map its game's own kind taxonomy onto it. Cosmetic fields
    are irrelevant to TTK/TTD and omitted."""

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
    # Ranged bolt delivery: the enemy bolt's motion + contact box.
    projectile_speed: float = 0.0
    projectile_lifetime: float = 0.0
    projectile_spawn_offset_x: float = 0.0
    projectile_half_width: float = 0.0
    # The warp kit (a blink-engage rotation), presence-gated on warp_cooldown > 0.
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
    """One spawn-roster entry: which kind spawns where (its x on the ground)."""

    kind: str
    name: str
    x: float
    y: float


@dataclass(frozen=True)
class Wave:
    """One wave: an ordered composition of spawns (a spawn roster)."""

    index: int
    spawns: tuple[Spawn, ...]


@dataclass(frozen=True)
class PlayerModel:
    """The stochastic player the Monte-Carlo sim runs — the design ASSUMPTIONS
    about how a player fights, not game runtime config.

    The stat block, move speed, spawn position, half-width, and the composed
    ``defender`` block come from the game's config authority (via the adapter);
    the behavioral assumptions (``fire_interval``, ``accuracy``,
    ``dodge_chance``, ``engagement_distance``) are design inputs that live in
    the targets file — a game usually has no fire-rate config for a
    per-input-press weapon, so the pipeline must model the human's cadence
    and aim.

    ``defender`` is the stat block incoming enemy damage mitigates against —
    the worn-equipment composition the adapter supplies (base defense + the
    equipment's bonus). ``None`` falls back to ``stats`` (an unequipped
    model)."""

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
        """The block incoming damage mitigates against."""
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
    """The design intent for one wave: the intended time to clear it (TTK) and
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
    """The game-side inputs the encounter sim needs, mapped out of the game's
    config authority by its adapter. ``player_defender`` is the pre-composed
    worn-equipment defender block (``None`` = unequipped)."""

    player_stats: StatBlock
    player_move_speed: float
    player_start_x: float
    player_half_width: float
    combat: CombatParams
    kinds: dict[str, EnemyKind]
    waves: tuple[Wave, ...]
    player_defender: StatBlock | None = None
    # The authored arena interval that clamps the warp blink's landing; an
    # infinite default means "no arena" (unit-test convenience).
    arena_min_x: float = float("-inf")
    arena_max_x: float = float("inf")


def build_player_model(
    game: GameData, player_model_params: dict[str, Any]
) -> PlayerModel:
    """Combine the game's player numbers with the design player-model assumptions.

    ``player_model_params`` are the design inputs from the targets file (fire
    cadence, aim, evasion, engagement distance); everything else — including the
    pre-composed ``defender`` block — comes from the adapter-mapped
    :class:`GameData`.
    """
    return PlayerModel(
        stats=game.player_stats,
        move_speed=game.player_move_speed,
        start_x=game.player_start_x,
        fire_interval=player_model_params["fire_interval"],
        accuracy=player_model_params["accuracy"],
        dodge_chance=player_model_params["dodge_chance"],
        engagement_distance=player_model_params["engagement_distance"],
        defender=game.player_defender,
        half_width=game.player_half_width,
    )


# --- The growth/economy inputs the system-dynamics model runs on ------------- #
#
# The SD model needs the reward and progression numbers the encounter sim does
# NOT — the per-tier kill reward + drop table, the leveling curve, and the
# heal-item restore amount — so these plain dataclasses carry them, mapped out
# of the same config authority by the same per-game adapter, never a second
# parser. Every field stays a bare scalar / mapping.


@dataclass(frozen=True)
class TierReward:
    """One tier's kill reward and expected drop yield: the guaranteed
    EXP/currency plus the per-item EXPECTED drop count (``Σ amount × chance``
    over that item's drop-table entries — the mean-field inflow the SD economy
    integrates, not a roll)."""

    tier: str
    exp_reward: float
    currency_reward: float
    expected_drops: dict[str, float]

    def expected_drop(self, item: str) -> float:
        """The expected count of ``item`` a kill of this tier yields (0 if none)."""
        return self.expected_drops.get(item, 0.0)


@dataclass(frozen=True)
class GrowthEconomy:
    """The growth/economy authority the SD model integrates over — the leveling
    curve (EXP→level), the per-tier kill reward + expected drop yield, and the
    item bindings: ``currency_item`` names the drop key whose yield folds into
    the currency stock (alongside the kill reward), ``heal_item`` names the
    consumable the balancing heal loop drains (restoring ``heal_item_restore``
    HP per unit). Every other dropped item is tracked as an inflow-only stock."""

    level_curve: tuple[float, ...]
    tier_rewards: dict[str, TierReward]
    player_max_hp: float
    currency_item: str | None = None
    heal_item: str | None = None
    heal_item_restore: float = 0.0

    @property
    def item_keys(self) -> tuple[str, ...]:
        """The tracked item stocks, in deterministic (sorted) order: every drop
        key except the currency item, plus the heal item (whose stock the heal
        loop needs even when no tier drops it)."""
        keys = {
            item
            for reward in self.tier_rewards.values()
            for item in reward.expected_drops
        }
        keys.discard(self.currency_item or "")
        if self.heal_item is not None:
            keys.add(self.heal_item)
        return tuple(sorted(keys))

    def level_for(self, exp: float) -> int:
        """The player's level at a cumulative EXP total — resolved through the
        shared :func:`rules.resolve_level`, so the SD growth loop reads level
        through the same ruleset the engines run on, not a private copy."""
        return rules.resolve_level(exp, list(self.level_curve))

    @property
    def max_level(self) -> int:
        """The highest reachable level (the curve's length + 1)."""
        return len(self.level_curve) + 1


@dataclass(frozen=True)
class GameInputs:
    """What an adapter returns: the encounter inputs, plus the growth/economy
    inputs when the game wants predict mode (``None`` = validate-only)."""

    game: GameData
    economy: GrowthEconomy | None = None
