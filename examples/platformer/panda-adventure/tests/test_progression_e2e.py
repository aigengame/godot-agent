"""Integration seam (c) for S6b Leveling curve + drop tables — THE gate.

The full progression loop through the gda CLI against a running Engine
session: killing the Wave-1 minion levels the Player up along the
data-driven leveling curve (level_up log + the HUD LV readout), and the
kill's Drop table leaves Pickups on the deterministic scatter row that the
Player walks over to collect — gold accumulating onto the Gold readout,
the item landing in the S6b item-count hook (gADR-0006):

- boot: ``hud_ready`` carries level 1 and the LV Label renders it — the
  Player starts at the bottom of the curve;
- the kill (the S6a-proven walk-aggro-shoot loop) emits ``level_up`` whose
  from/to match the authoritative curve against the minion Tier's
  exp_reward, and the LV readout ticks up;
- one ``pickup_spawned`` record per resolved drop, the scatter row exactly
  ``pickup_spacing`` apart (drop POSITIONS are deterministic relative to the
  death spot even though the death spot itself follows the AI dynamics);
- walking across the drops emits ``gold_collected`` (amount + total = kill
  gold_reward + dropped gold) and ``item_collected`` (the bun, count 1), and
  the Gold readout agrees.

Every expectation derives from the AUTHORITATIVE JSON configs, never
hardcoded. One data seam is exercised e2e as well: the throwaway copy's
minion bun-drop chance is retuned to 1.0 (a JSON-only edit + rebuild — the
waves-e2e reconfiguration precedent) so the item path asserts
deterministically; the shipped 0.25 chance would make the bun a coin toss.
The gold entry ships at chance 1.0 and is asserted as shipped. Per RULES.md,
mocks cannot replace this end-to-end proof.

Isolation: same throwaway-copy pattern as ``test_reward_hud_e2e`` (``daemon
start`` mutates ``project.godot``); posix-only (AF_UNIX); headless. The walk
uses ``input sequence`` ``physics_frame`` offsets (the physics-clock
schedule): displacement maps deterministically to held physics ticks
(move_speed / 60 per tick).
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


def _make_project_copy(dst: Path) -> dict:
    """Copy the committed game into a throwaway dir, retune the minion's bun
    drop to a GUARANTEED drop (JSON-only, the per-Tier authority), and build
    the copy's config there. Returns the copy's enemies document — the
    authority the assertions below derive from."""
    shutil.copytree(GAME_DIR, dst, ignore=_COPY_IGNORE)
    enemies_path = dst / "data" / "json" / "enemies_config.json"
    enemies = json.loads(enemies_path.read_text(encoding="utf-8"))
    for entry in enemies["tiers"]["minion"]["drops"]:
        if entry["item"] != "gold":
            entry["chance"] = 1.0
    enemies_path.write_text(json.dumps(enemies), encoding="utf-8")
    build_config.build_all(root=dst)
    return enemies


@pytest.mark.e2e
def test_daemon_serves_leveling_and_drop_collection(tmp_path, daemon_runtime_dir):
    project = tmp_path / "game"
    enemies = _make_project_copy(project)
    # Every expectation derives from the AUTHORITATIVE JSON (the copy's, for
    # the retuned drop chance), never hardcoded.
    combat = build_config.load_json(GAME_DIR / "data" / "json" / "combat_config.json")
    player_cfg = build_config.load_json(
        GAME_DIR / "data" / "json" / "player_config.json"
    )
    progression = build_config.load_json(
        GAME_DIR / "data" / "json" / "progression_config.json"
    )
    default_spawn = enemies["waves"][0]["spawns"][0]
    kind = enemies["kinds"][default_spawn["kind"]]
    reward = enemies["tiers"][kind["tier"]]
    drops = reward["drops"]
    # With every chance at 1.0 the WHOLE table drops, in table order.
    assert all(entry["chance"] == 1.0 for entry in drops), drops
    gold_dropped = sum(e["amount"] for e in drops if e["item"] == "gold")
    item_drops = [e for e in drops if e["item"] != "gold"]
    assert gold_dropped and item_drops, "the minion table must cover both paths"
    # The level the kill's EXP reaches on the curve (GrowthSystem's rule:
    # 1 + thresholds reached) — the shipped curve levels a first minion kill.
    curve = progression["level_curve"]
    expected_level = 1 + sum(
        1 for threshold in curve if reward["exp_reward"] >= threshold
    )
    assert expected_level > 1, "the first kill must level up on the shipped curve"
    spacing = progression["pickup_spacing"]
    player_stats = combat["player_stats"]
    laser_damage = max(
        combat["min_damage"],
        player_stats["attack"] * combat["attack_scale"]
        - kind["defense"] * combat["defense_scale"],
    )
    shots_to_kill = math.ceil(kind["max_hp"] / laser_damage)
    iframe = combat["iframe_duration"]
    rest_y = (
        player_cfg["platform_position"][1]
        - player_cfg["platform_size"][1] / 2.0
        - player_cfg["player_size"][1] / 2.0
    )
    start_x = player_cfg["player_start"][0]
    enemy_x = default_spawn["position"][0]
    # The S6a-proven walk target: inside the minion's Aggro Range with margin
    # on both sides; the minion closes the rest (gADR-0003 dynamics).
    target_x = enemy_x - kind["aggro_range"] + 40.0
    ticks_per_px = 1.0 / (player_cfg["move_speed"] / 60.0)
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

    def walk_right(px: float) -> None:
        """Hold move_right for the physics ticks that cover ``px`` pixels."""
        seq = run(
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
                        "physics_frame": max(round(px * ticks_per_px), 1),
                    },
                ]
            ),
        )
        assert seq.returncode == 0, seq.stdout + seq.stderr

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # The first live op launches the Engine session (the daemon observes,
        # it does not start one on a diagnostics read); the tree also proves
        # the S6b LV line is instanced in the HUD column.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        assert '"LevelLabel"' in tree.stdout, tree.stdout

        # --- Boot: the Player starts at the bottom of the curve — hud_ready
        # carries level 1 and the LV Label (the S6b line in the HUD column)
        # renders it.
        ready = poll(lambda: records("hud_ready"))
        assert ready, "no gda_log 'hud_ready' record"
        assert ready[0]["fields"]["level"] == 1
        assert label("Level") == "LV 1"

        # Let the Player settle on the platform so the walk starts from rest.
        assert poll(
            lambda: abs(prop("/root/Main/Player", "position")[1] - rest_y) <= 2.0
        ), "Player did not land"

        # --- The kill: walk into the minion's Aggro Range (the deterministic
        # physics-clock hold), let it close, kill it with spaced Laser shots
        # (past the i-frame window) — the S6a-proven loop.
        walk_right(target_x - start_x)
        player_x = prop("/root/Main/Player", "position")[0]
        assert abs(player_x - target_x) <= 20.0, (
            f"physics-clock walk missed its target: x={player_x}, want ~{target_x}"
        )
        assert poll(lambda: records("player_hit"), timeout=30.0), (
            "the aggroed minion never landed a contact hit"
        )
        for _ in range(shots_to_kill * 2):
            if records("enemy_died"):
                break
            time.sleep(iframe + 0.3)
            tap("fire")
            poll(lambda: bool(records("enemy_died")), timeout=3.0)
        assert poll(lambda: records("enemy_died")), "the Enemy never died"

        # --- The leveling curve: the kill's EXP reaches the curve's first
        # threshold — one level_up record with the curve-derived from/to and
        # the EXP total, and the LV readout ticks up.
        leveled = poll(lambda: records("level_up"))
        assert leveled, "no gda_log 'level_up' record"
        assert len(leveled) == 1, f"one threshold crossing, one record: {leveled}"
        fields = leveled[0]["fields"]
        assert fields["from"] == 1
        assert fields["to"] == expected_level
        assert fields["exp_total"] == pytest.approx(reward["exp_reward"])
        assert poll(lambda: label("Level") == f"LV {expected_level}"), (
            f"LV readout never showed the level-up: {label('Level')}"
        )

        # --- The Drop table: one pickup_spawned per entry (every chance is
        # 1.0 in this copy), in table order on the deterministic scatter row —
        # neighbors exactly pickup_spacing apart, anchored on the death spot.
        spawned = poll(lambda: len(records("pickup_spawned")) == len(drops))
        assert spawned, (
            f"expected {len(drops)} pickup_spawned records, "
            f"got {records('pickup_spawned')}"
        )
        pickups = records("pickup_spawned")
        for got, expected in zip(pickups, drops):
            assert got["fields"]["item"] == expected["item"]
            assert got["fields"]["amount"] == expected["amount"]
        xs = [r["fields"]["x"] for r in pickups]
        for left, right in zip(xs, xs[1:]):
            assert right - left == pytest.approx(spacing), xs
        death = records("enemy_died")[0]["fields"]
        assert sum(xs) / len(xs) == pytest.approx(death["x"]), (
            f"the scatter row must center on the death spot: {xs} vs {death}"
        )

        # --- Collection: walk across the row; gold accumulates onto the
        # Player's Gold (the second source next to the Kill reward) and the
        # bun lands in the item-count hook. The readout agrees with the log.
        player_x = prop("/root/Main/Player", "position")[0]
        walk_right(max(xs) - player_x + 30.0)
        collected_gold = poll(lambda: records("gold_collected"), timeout=15.0)
        assert collected_gold, "no gda_log 'gold_collected' record"
        gold_total = reward["gold_reward"] + gold_dropped
        assert collected_gold[-1]["fields"]["gold_total"] == pytest.approx(gold_total)
        collected_items = poll(
            lambda: len(records("item_collected")) == len(item_drops), timeout=15.0
        )
        assert collected_items, (
            f"expected {len(item_drops)} item_collected records, "
            f"got {records('item_collected')}"
        )
        for got, expected in zip(records("item_collected"), item_drops):
            assert got["fields"]["item"] == expected["item"]
            assert got["fields"]["amount"] == expected["amount"]
            assert got["fields"]["count"] == expected["amount"]

        # The HUD surfaces the full accumulation: kill reward + dropped gold.
        assert poll(lambda: label("Gold") == f"GOLD {int(gold_total)}"), (
            f"Gold readout never showed the drops: {label('Gold')}"
        )
        assert label("Exp") == f"EXP {int(reward['exp_reward'])}"
    finally:
        run("daemon", "stop")
