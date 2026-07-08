"""Panda Adventure adapter: the JSON authority mapped into the generic model.

The ONE per-game module (gADR-0011's per-game configuration): it knows this
game's on-disk config shape — ``combat_config.json`` / ``enemies_config.json`` /
``player_config.json`` / ``items_config.json`` (the Spacesuit's defense bonus,
gADR-0008) / ``level_config.json`` (the Arena interval that clamps the Warp
Blink's landing, gADR-0010) / ``scale_spec.json`` (the single size authority:
the player/enemy/bolt boxes and the Time Dilation Field radius, gADR-0013) —
and maps it into the game-agnostic ``model`` the sim runs on. It reads JSON
only — it imports NO game code (no GDScript, no ``build_config``, no Godot),
so the pipeline stays isolated from the engine (gADR-0011). Sizes are read
from the Scale spec directly (the same authored home the builder composes
into each derived Resource), so the sim sees exactly what the game derives.

The one derived value composed here is the Player's ``defender`` block —
``ItemSystem.effective_defender``'s Spacesuit composition (gADR-0008), worn
from spawn — mirrored via the parity-pinned ``rules.effective_defense``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import rules
from .model import (
    CombatParams,
    EnemyKind,
    GameData,
    GrowthEconomy,
    PlayerModel,
    Spawn,
    StatBlock,
    TierReward,
    Wave,
)


def _load(config_dir: Path, name: str) -> Any:
    return json.loads((config_dir / name).read_text(encoding="utf-8"))


def load_combat(config_dir: Path) -> tuple[StatBlock, CombatParams]:
    """The player's stat block and the combat-formula + Laser-bolt params
    (combat config; the bolt's half-width from the Scale spec)."""
    doc = _load(config_dir, "combat_config.json")
    scale = _load(config_dir, "scale_spec.json")
    ps = doc["player_stats"]
    player_stats = StatBlock(
        max_hp=ps["max_hp"],
        max_mp=ps["max_mp"],
        attack=ps["attack"],
        defense=ps["defense"],
    )
    combat = CombatParams(
        attack_scale=doc["attack_scale"],
        defense_scale=doc["defense_scale"],
        min_damage=doc["min_damage"],
        iframe_duration=doc["iframe_duration"],
        projectile_speed=doc["projectile_speed"],
        projectile_lifetime=doc["projectile_lifetime"],
        projectile_spawn_offset_x=doc["projectile_spawn_offset"][0],
        projectile_half_width=scale["player_projectile_size"][0] / 2.0,
    )
    return player_stats, combat


def load_spacesuit_defense(config_dir: Path) -> float:
    """The worn Spacesuit's defense bonus (items config, gADR-0008)."""
    return _load(config_dir, "items_config.json")["spacesuit_defense"]


def load_arena(config_dir: Path) -> tuple[float, float]:
    """The authored Arena interval (level config, gADR-0010)."""
    doc = _load(config_dir, "level_config.json")
    return doc["arena_min_x"], doc["arena_max_x"]


def load_enemy_kinds(config_dir: Path) -> dict[str, EnemyKind]:
    """Every Enemy Kind's sim-relevant numbers (enemies config + Scale spec).

    A ranged kind carries its bolt block (gADR-0003; the bolt's box from the
    Scale spec's per-kind ``projectile_size``); a Warp kind carries the Warp
    kit (gADR-0009; ``time_field_radius`` from the Scale spec) — both exactly
    the families the builder composes into the derived ``EnemyConfig``.
    """
    doc = _load(config_dir, "enemies_config.json")
    boxes = _load(config_dir, "scale_spec.json")["enemy_boxes"]
    kinds: dict[str, EnemyKind] = {}
    for name, k in doc["kinds"].items():
        box = boxes[name]
        extra: dict[str, float] = {}
        if k["archetype"] == "ranged":
            extra.update(
                projectile_speed=k["projectile_speed"],
                projectile_lifetime=k["projectile_lifetime"],
                projectile_spawn_offset_x=k["projectile_spawn_offset"][0],
                projectile_half_width=box["projectile_size"][0] / 2.0,
            )
        if "warp_cooldown" in k:
            extra.update(
                warp_cooldown=k["warp_cooldown"],
                warp_trigger_range=k["warp_trigger_range"],
                warp_offset_x=k["warp_offset"][0],
                warp_tell_duration=k["warp_tell_duration"],
                warp_recovery_duration=k["warp_recovery_duration"],
                time_field_radius=box["time_field_radius"],
                time_field_factor=k["time_field_factor"],
                time_field_duration=k["time_field_duration"],
            )
        kinds[name] = EnemyKind(
            name=name,
            tier=k["tier"],
            archetype=k["archetype"],
            stats=StatBlock(
                max_hp=k["max_hp"],
                max_mp=k["max_mp"],
                attack=k["attack"],
                defense=k["defense"],
            ),
            move_speed=k["move_speed"],
            aggro_range=k["aggro_range"],
            attack_range=k["attack_range"],
            attack_cooldown=k["attack_cooldown"],
            keep_range_min=k["keep_range_min"],
            keep_range_max=k["keep_range_max"],
            half_width=box["size"][0] / 2.0,
            **extra,
        )
    return kinds


def load_growth_economy(config_dir: Path) -> GrowthEconomy:
    """Map this game's growth/economy authority into the generic
    :class:`GrowthEconomy` the SD model integrates over (#440).

    Reads the same JSON authority the game derives from — the Leveling curve
    (``progression_config``), the per-Tier Kill reward + Drop table
    (``enemies_config``, gADR-0004/0006), the Consumable restore amounts
    (``items_config``, gADR-0008), and the player pools (``combat_config``) —
    through the ONE per-game adapter, so the SD model never opens a second
    parser (gADR-0011). Expected drop counts are ``Σ amount × chance`` per item
    (the mean-field inflow, not a stochastic roll).
    """
    prog = _load(config_dir, "progression_config.json")
    enemies = _load(config_dir, "enemies_config.json")
    items = _load(config_dir, "items_config.json")
    player_stats = _load(config_dir, "combat_config.json")["player_stats"]
    tier_rewards: dict[str, TierReward] = {}
    for tier, t in enemies["tiers"].items():
        expected: dict[str, float] = {}
        for drop in t.get("drops", []):
            item = drop["item"]
            expected[item] = expected.get(item, 0.0) + drop["amount"] * drop["chance"]
        tier_rewards[tier] = TierReward(
            tier=tier,
            exp_reward=t["exp_reward"],
            gold_reward=t["gold_reward"],
            expected_drops=expected,
        )
    return GrowthEconomy(
        level_curve=tuple(prog["level_curve"]),
        tier_rewards=tier_rewards,
        bun_hp_restore=items["bun_hp_restore"],
        wine_mp_restore=items["wine_mp_restore"],
        player_max_hp=player_stats["max_hp"],
        player_max_mp=player_stats["max_mp"],
    )


def load_waves(config_dir: Path) -> tuple[Wave, ...]:
    """The Wave schedule as ordered waves of spawns (enemies config)."""
    doc = _load(config_dir, "enemies_config.json")
    waves: list[Wave] = []
    for i, wave in enumerate(doc["waves"], start=1):
        spawns = tuple(
            Spawn(
                kind=s["kind"],
                name=s["name"],
                x=s["position"][0],
                y=s["position"][1],
            )
            for s in wave["spawns"]
        )
        waves.append(Wave(index=i, spawns=spawns))
    return tuple(waves)


def load_game_data(config_dir: Path) -> GameData:
    """Map this game's whole JSON authority into the generic :class:`GameData`."""
    player_stats, combat = load_combat(config_dir)
    player = _load(config_dir, "player_config.json")
    scale = _load(config_dir, "scale_spec.json")
    arena_min_x, arena_max_x = load_arena(config_dir)
    return GameData(
        player_stats=player_stats,
        player_move_speed=player["move_speed"],
        player_start_x=player["player_start"][0],
        player_half_width=scale["player_size"][0] / 2.0,
        spacesuit_defense=load_spacesuit_defense(config_dir),
        combat=combat,
        kinds=load_enemy_kinds(config_dir),
        waves=load_waves(config_dir),
        arena_min_x=arena_min_x,
        arena_max_x=arena_max_x,
    )


def compose_defender(base: StatBlock, defense_bonus: float) -> StatBlock:
    """The Spacesuit-composed defender (``ItemSystem.effective_defender``,
    gADR-0008): a fresh block copying ``base`` with ``defense`` raised by the
    worn Equipment's bonus — the parity-pinned ``rules.effective_defense`` on
    the defense term, the other stats copied unchanged."""
    return StatBlock(
        max_hp=base.max_hp,
        max_mp=base.max_mp,
        attack=base.attack,
        defense=rules.effective_defense(base.defense, defense_bonus),
    )


def build_player_model(
    game: GameData, player_model_params: dict[str, Any]
) -> PlayerModel:
    """Combine the game's player numbers with the design player-model assumptions.

    ``player_model_params`` are the design inputs from the targets file
    (fire cadence, aim, evasion, engagement distance) — the game carries no
    Laser-Gun fire-rate config, so these model the human at the controls. The
    ``defender`` block is the Spacesuit composition (worn from spawn,
    gADR-0008), exactly what the game's ``take_hit`` mitigates against.
    """
    return PlayerModel(
        stats=game.player_stats,
        move_speed=game.player_move_speed,
        start_x=game.player_start_x,
        fire_interval=player_model_params["fire_interval"],
        accuracy=player_model_params["accuracy"],
        dodge_chance=player_model_params["dodge_chance"],
        engagement_distance=player_model_params["engagement_distance"],
        defender=compose_defender(game.player_stats, game.spacesuit_defense),
        half_width=game.player_half_width,
    )
