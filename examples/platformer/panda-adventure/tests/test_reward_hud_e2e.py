"""Integration seam (c) for S6a Kill reward (EXP/Gold per Tier) + HUD — THE gate.

The full reward/HUD loop through the gda CLI against a running Engine session,
on the SHIPPED default config (no data mutation — the shipped Spawn Roster's
dormant melee minion is both the damage source and the kill target):

- the gda-authored HUD is live: ``gda game tree`` shows the Hud CanvasLayer
  instanced in Main, ``hud_ready`` logs the initial snapshot, and every Label
  (read via ``gda game get`` on its ``text``) renders the AUTHORITATIVE
  JSON's boot values — full HP/MP, EXP/Gold at 0, the Laser Gun current;
- the HUD tracks the weapon toggle both ways (``switch_weapon`` ->
  ``GRAVITY GUN`` -> back) and the MP spend (a Gravity Gun fire drops the MP
  readout by ``mp_cost``) — the S3 economy surfaced live. The Wine RESTORE
  needs supply since S7 (gADR-0008): with none held ``drink_wine`` is
  refused (``consumable_blocked``) and the readout stays put; the restore
  readout lives in ``test_items_e2e.py``, where the supply exists;
- walking into the minion's Aggro Range brings it to point-blank and its
  contact hits show up in the HP readout (recomputed from the ``player_hit``
  records — the HUD must agree with the log trail);
- killing it with the Laser Gun (spaced shots past the i-frame window, the
  S2-proven loop) emits ``reward_gained`` whose amounts are the kind's TIER
  entry from the authoritative ``tiers`` table (exp/gold + first-kill totals
  + the tier name), and the EXP/Gold readouts tick up to the totals — the
  reward half of the death/reward story feeding the S2 StatsSystem.

Every expectation derives from the AUTHORITATIVE JSON configs, never
hardcoded. Per RULES.md, mocks cannot replace this end-to-end proof.

Isolation: same throwaway-copy pattern as ``test_player_e2e`` (``daemon
start`` mutates ``project.godot``); posix-only (AF_UNIX); fully headless —
Linux-CI-friendly. The windowed visual-presence half (the HUD actually
RENDERS) lives in the consolidated Visual-smoke seam gate,
``test_visual_smoke_e2e.py`` (gADR-0007), as its first checkpoint. The walk
uses ``input sequence`` ``physics_frame`` offsets (the physics-clock
schedule): displacement maps deterministically to held physics ticks
(move_speed / 60 per tick), unlike idle-frame offsets.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gda.binary import resolve_godot_binary

import build_config

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")

GDA_CMD = [sys.executable, "-m", "gda"]
GODOT = resolve_godot_binary()
GAME_DIR = build_config.GAME_DIR

_COPY_IGNORE = shutil.ignore_patterns(
    "tests", ".godot", "build", "generated", "__pycache__"
)

_HUD_LABEL = "/root/Main/Hud/Stats/%sLabel"


def _make_project_copy(dst: Path) -> Path:
    """Copy the committed game into a throwaway dir and build its config there."""
    shutil.copytree(GAME_DIR, dst, ignore=_COPY_IGNORE)
    build_config.build_all(root=dst)
    return dst


def _find_node(node: dict, name: str) -> dict | None:
    """Depth-first search a ``game tree`` subtree for a node by name."""
    if node.get("name") == name:
        return node
    for child in node.get("children", []):
        found = _find_node(child, name)
        if found is not None:
            return found
    return None


@pytest.mark.e2e
def test_daemon_serves_kill_reward_and_hud(tmp_path, daemon_runtime_dir):
    project = _make_project_copy(tmp_path / "game")
    # Every expectation derives from the AUTHORITATIVE JSON, never hardcoded.
    enemies = build_config.load_composed("content/data/json/enemies_config.json")
    combat = build_config.load_composed("content/data/json/combat_config.json")
    gravity = build_config.load_composed("content/data/json/gravity_config.json")
    items = build_config.load_composed("content/data/json/items_config.json")
    player_cfg = build_config.load_composed("content/data/json/player_config.json")
    level_cfg = build_config.load_composed("content/data/json/level_config.json")
    rampart = next(p for p in level_cfg["platforms"] if p["name"] == "Rampart")
    default_spawn = enemies["waves"][0]["spawns"][0]
    kind = enemies["kinds"][default_spawn["kind"]]
    reward = enemies["tiers"][kind["tier"]]
    player_stats = combat["player_stats"]
    max_hp = player_stats["max_hp"]
    max_mp = player_stats["max_mp"]
    mp_cost = gravity["mp_cost"]
    # The symmetric damage formula, both directions (gADR-0001). The Player
    # defends with the SPACESUIT-composed block since S7 (gADR-0008).
    laser_damage = max(
        combat["min_damage"],
        player_stats["attack"] * combat["attack_scale"]
        - kind["defense"] * combat["defense_scale"],
    )
    contact_damage = max(
        combat["min_damage"],
        kind["attack"] * combat["attack_scale"]
        - (player_stats["defense"] + items["spacesuit_defense"])
        * combat["defense_scale"],
    )
    shots_to_kill = math.ceil(kind["max_hp"] / laser_damage)
    iframe = combat["iframe_duration"]
    rest_y = (
        rampart["position"][1]
        - rampart["size"][1] / 2.0
        - player_cfg["player_size"][1] / 2.0
    )
    start_x = player_cfg["player_start"][0]
    enemy_x = default_spawn["position"][0]
    # Walk target: inside the minion's Aggro Range (it closes the rest — the
    # gADR-0003 dynamics this flow leans on) with margin on BOTH sides: well
    # past the aggro edge, well short of point-blank. The physics-clock hold
    # maps ticks to displacement exactly: move_speed / 60 px per tick.
    target_x = enemy_x - kind["aggro_range"] + 40.0
    hold_ticks = round((target_x - start_x) / (player_cfg["move_speed"] / 60.0))
    env = {**os.environ}

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(project),
                "--godot",
                str(GODOT),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    def records(message: str) -> list[dict]:
        proc = run("logger", "tail")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return [
            r
            for r in json.loads(proc.stdout)["records"]
            if r["message"] == message and r["origin"] == "gda_log"
        ]

    def poll(predicate, timeout: float = 20.0, interval: float = 0.5):
        deadline = time.monotonic() + timeout
        result = predicate()
        while not result and time.monotonic() < deadline:
            time.sleep(interval)
            result = predicate()
        return result

    def prop(path: str, name: str):
        got = run("game", "get", path, "--property", name)
        assert got.returncode == 0, got.stdout + got.stderr
        for p in json.loads(got.stdout)["properties"]:
            if p["name"] == name:
                return p["value"]
        raise AssertionError(f"{name} not returned for {path}")

    def label(key: str) -> str:
        return prop(_HUD_LABEL % key, "text")

    def tap(action: str) -> None:
        """One press+release of an InputMap action (one is_action_just_pressed)."""
        seq = run(
            "input",
            "sequence",
            "--events",
            json.dumps(
                [
                    {"type": "action", "action": action, "frame": 0},
                    {"type": "action", "action": action, "release": True, "frame": 4},
                ]
            ),
        )
        assert seq.returncode == 0, seq.stdout + seq.stderr

    def expected_hp_label() -> str:
        """The HP readout implied by the player_hit log trail right now."""
        hits = records("player_hit")
        hp = max_hp - contact_damage * len(hits)
        return f"HP {round(hp)}/{round(max_hp)}"

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # --- The HUD is live: the instanced CanvasLayer is in the runtime
        # tree with its Label column.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        root = json.loads(tree.stdout)["root"]
        hud = _find_node(root, "Hud")
        assert hud is not None and hud["type"] == "CanvasLayer", root
        for key in ("Hp", "Mp", "Exp", "Gold", "Weapon", "Bun", "Wine"):
            assert _find_node(hud, f"{key}Label") is not None, hud

        # Its boot record carries the initial snapshot from the data.
        ready = poll(lambda: records("hud_ready"))
        assert ready, "no gda_log 'hud_ready' record"
        assert ready[0]["fields"]["hp"] == pytest.approx(max_hp)
        assert ready[0]["fields"]["mp"] == pytest.approx(max_mp)
        assert ready[0]["fields"]["exp"] == pytest.approx(0.0)
        assert ready[0]["fields"]["gold"] == pytest.approx(0.0)
        assert ready[0]["fields"]["weapon"] == "laser_gun"

        # Let the Player settle on the platform (S1-proven poll) so the walk
        # below starts from rest.
        assert poll(
            lambda: abs(prop("/root/Main/Gameplay/Player", "position")[1] - rest_y) <= 2.0
        ), "Player did not land"

        # The boot readout renders the authoritative values.
        assert label("Hp") == f"HP {round(max_hp)}/{round(max_hp)}"
        assert label("Mp") == f"MP {round(max_mp)}/{round(max_mp)}"
        assert label("Exp") == "EXP 0"
        assert label("Gold") == "GOLD 0"
        assert label("Weapon") == "LASER GUN"

        # --- The weapon toggle is surfaced, both ways; the MP economy is
        # surfaced (spend on a Gravity Gun fire, restore on Wine — capped).
        tap("switch_weapon")
        assert poll(lambda: label("Weapon") == "GRAVITY GUN"), (
            "HUD should show the Gravity Gun after switch_weapon"
        )
        tap("fire")
        assert poll(lambda: records("gravity_fired")), "no gravity_fired record"
        assert poll(
            lambda: label("Mp") == f"MP {round(max_mp - mp_cost)}/{round(max_mp)}"
        ), "HUD should surface the MP spend"
        # With no Wine held the restore is REFUSED (the S7 supply gate,
        # gADR-0008): the MP readout stays on the spent value. The restore
        # readout is proven in test_items_e2e.py, where the supply exists.
        tap("drink_wine")
        assert poll(lambda: records("consumable_blocked")), (
            "no consumable_blocked record for the supply-less wine"
        )
        assert not records("wine_drunk"), "a refused drink must not restore MP"
        assert label("Mp") == f"MP {round(max_mp - mp_cost)}/{round(max_mp)}", (
            "a refused drink must leave the MP readout on the spent value"
        )
        tap("switch_weapon")
        assert poll(lambda: label("Weapon") == "LASER GUN"), (
            "HUD should show the Laser Gun after switching back"
        )

        # --- Damage is surfaced: walk into the minion's Aggro Range (a
        # deterministic physics-clock hold), let it close to point-blank and
        # land contact hits; the HP readout must agree with the player_hit
        # log trail (both sides derive from the same authoritative JSON).
        walk = run(
            "input",
            "sequence",
            "--events",
            json.dumps(
                [
                    {"type": "action", "action": "move_right", "physics_frame": 0},
                    {
                        "type": "action",
                        "action": "move_right",
                        "release": True,
                        "physics_frame": hold_ticks,
                    },
                ]
            ),
        )
        assert walk.returncode == 0, walk.stdout + walk.stderr
        player_x = prop("/root/Main/Gameplay/Player", "position")[0]
        assert abs(player_x - target_x) <= 20.0, (
            f"physics-clock walk missed its target: x={player_x}, want ~{target_x}"
        )
        assert poll(lambda: records("player_hit"), timeout=30.0), (
            "the aggroed minion never landed a contact hit"
        )
        assert records("player_hit")[0]["fields"]["damage"] == pytest.approx(
            contact_damage
        )
        assert poll(lambda: label("Hp") == expected_hp_label()), (
            f"HP readout disagrees with the log trail: {label('Hp')}"
        )

        # --- The Kill reward: spaced Laser shots (past the i-frame window)
        # kill the point-blank minion; the reward is its Tier's entry.
        for _ in range(shots_to_kill * 2):
            if records("enemy_died"):
                break
            time.sleep(iframe + 0.3)
            tap("fire")
            poll(lambda: bool(records("enemy_died")), timeout=3.0)
        assert poll(lambda: records("enemy_died")), "the Enemy never died"

        gained = poll(lambda: records("reward_gained"))
        assert gained, "no gda_log 'reward_gained' record"
        assert len(gained) == 1, f"one kill must award exactly once: {gained}"
        fields = gained[0]["fields"]
        assert fields["exp"] == pytest.approx(reward["exp_reward"])
        assert fields["gold"] == pytest.approx(reward["gold_reward"])
        # First kill: the accumulated totals ARE the single award.
        assert fields["exp_total"] == pytest.approx(reward["exp_reward"])
        assert fields["gold_total"] == pytest.approx(reward["gold_reward"])
        assert fields["tier"] == kind["tier"]

        # The HUD surfaces the accumulation (floored display of the totals).
        exp_text = f"EXP {int(reward['exp_reward'])}"
        gold_text = f"GOLD {int(reward['gold_reward'])}"
        assert poll(lambda: label("Exp") == exp_text), (
            f"EXP readout never showed the reward: {label('Exp')}"
        )
        assert poll(lambda: label("Gold") == gold_text), (
            f"Gold readout never showed the reward: {label('Gold')}"
        )

        # The dead Enemy stops the damage: the HP readout settles on the log
        # trail's final value and the weapon readout is unchanged.
        assert poll(lambda: label("Hp") == expected_hp_label())
        assert label("Weapon") == "LASER GUN"
    finally:
        run("daemon", "stop")
