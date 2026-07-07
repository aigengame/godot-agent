"""Panda Adventure adapter: the JSON authority mapped into the generic model.

The ONE per-game module (gADR-0011's per-game configuration): it knows this
game's on-disk config shape (``combat_config.json`` / ``enemies_config.json`` /
``player_config.json``) and maps it into the game-agnostic ``model`` the sim
runs on. It reads JSON only — it imports NO game code (no GDScript, no
``build_config``, no Godot), so the pipeline stays isolated from the engine
(gADR-0011). The numbers it reads (stat blocks, Archetype-AI params, wave
composition) are authored numbers, unaffected by the Scale spec composition that
only touches element sizes, so a plain JSON read is faithful to what the game
derives.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import (
    CombatParams,
    EnemyKind,
    GameData,
    PlayerModel,
    Spawn,
    StatBlock,
    Wave,
)


def _load(config_dir: Path, name: str) -> Any:
    return json.loads((config_dir / name).read_text(encoding="utf-8"))


def load_combat(config_dir: Path) -> tuple[StatBlock, CombatParams]:
    """The player's stat block and the combat-formula params (combat config)."""
    doc = _load(config_dir, "combat_config.json")
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
    )
    return player_stats, combat


def load_enemy_kinds(config_dir: Path) -> dict[str, EnemyKind]:
    """Every Enemy Kind's sim-relevant numbers (enemies config)."""
    doc = _load(config_dir, "enemies_config.json")
    kinds: dict[str, EnemyKind] = {}
    for name, k in doc["kinds"].items():
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
        )
    return kinds


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
    return GameData(
        player_stats=player_stats,
        player_move_speed=player["move_speed"],
        player_start_x=player["player_start"][0],
        combat=combat,
        kinds=load_enemy_kinds(config_dir),
        waves=load_waves(config_dir),
    )


def build_player_model(
    game: GameData, player_model_params: dict[str, Any]
) -> PlayerModel:
    """Combine the game's player numbers with the design player-model assumptions.

    ``player_model_params`` are the design inputs from the targets file
    (fire cadence, aim, evasion, engagement distance) — the game carries no
    Laser-Gun fire-rate config, so these model the human at the controls.
    """
    return PlayerModel(
        stats=game.player_stats,
        move_speed=game.player_move_speed,
        start_x=game.player_start_x,
        fire_interval=player_model_params["fire_interval"],
        accuracy=player_model_params["accuracy"],
        dodge_chance=player_model_params["dodge_chance"],
        engagement_distance=player_model_params["engagement_distance"],
    )
