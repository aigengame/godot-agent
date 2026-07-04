"""Integration seam (c) for S2 Laser Gun combat — THE gate.

The full combat loop through the gda CLI against a running Engine session:

- ``gda game tree`` shows the runtime-spawned Enemy (a CharacterBody2D since
  S4's Archetype AI made enemies mobile) next to the S1 blockout;
- ``gda input sequence`` presses ``fire`` and the bolt crosses the level into
  the Enemy: ``gda logger tail`` returns rich ``laser_fired`` and ``enemy_hit``
  records whose damage/hp match the AUTHORITATIVE JSON through the data-driven
  formula — proof that the InputMap action, projectile flight, collision
  layers/masks, and the damage pipeline all work end-to-end;
- two shots fired a few frames apart (far inside the i-frame window) land
  exactly ONE hit — the live chained-hit proof (the boundary semantics stay
  owned by the logic seam);
- repeated shots spaced past the window drive ``hp_left`` strictly down to 0,
  ``enemy_died`` appears, and the Enemy leaves the runtime scene tree.

Per RULES.md, mocks cannot replace this end-to-end proof.

Isolation: same throwaway-copy pattern as ``test_player_e2e`` (``daemon start``
mutates ``project.godot``); posix-only (AF_UNIX); headless — Linux-CI-friendly.
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


def _expected_damage(combat: dict) -> float:
    """The data-driven formula, recomputed from the authoritative JSON."""
    return max(
        combat["min_damage"],
        combat["player_stats"]["attack"] * combat["attack_scale"]
        - combat["enemy_stats"]["defense"] * combat["defense_scale"],
    )


@pytest.mark.e2e
def test_daemon_serves_laser_combat(tmp_path, daemon_runtime_dir):
    project = _make_project_copy(tmp_path / "game")
    # Every expectation derives from the AUTHORITATIVE JSON, never hardcoded.
    combat = build_config.load_json(GAME_DIR / "data" / "json" / "combat_config.json")
    player_cfg = build_config.load_json(
        GAME_DIR / "data" / "json" / "player_config.json"
    )
    damage = _expected_damage(combat)
    max_hp = combat["enemy_stats"]["max_hp"]
    hits_to_kill = math.ceil(max_hp / damage)
    iframe = combat["iframe_duration"]
    rest_y = (
        player_cfg["platform_position"][1]
        - player_cfg["platform_size"][1] / 2.0
        - player_cfg["player_size"][1] / 2.0
    )
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

    def player_y() -> float:
        got = run("game", "get", "/root/Main/Player", "--property", "position")
        assert got.returncode == 0, got.stdout + got.stderr
        for p in json.loads(got.stdout)["properties"]:
            if p["name"] == "position":
                return p["value"][1]
        raise AssertionError("position not returned")

    def fire(events: list[dict]) -> None:
        seq = run("input", "sequence", "--events", json.dumps(events))
        assert seq.returncode == 0, seq.stdout + seq.stderr

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # The runtime-spawned Enemy is in the live tree with the S1 blockout.
        # CharacterBody2D since S4 (enemies move); the default Spawn Roster
        # keeps this flow's melee minion dormant (aggro_range < the distance),
        # so the S2 combat expectations below hold unchanged.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        root = json.loads(tree.stdout)["root"]
        enemy = _find_node(root, "Enemy")
        assert enemy is not None and enemy["type"] == "CharacterBody2D", root
        assert _find_node(root, "Player") is not None, root

        # Its boot record carries the data-driven stat block.
        ready = poll(lambda: records("enemy_ready"))
        assert ready, "no gda_log 'enemy_ready' record"
        assert ready[0]["fields"]["max_hp"] == pytest.approx(max_hp)
        assert ready[0]["fields"]["x"] == pytest.approx(combat["enemy_position"][0])

        # Let the Player settle on the platform before firing (S1-proven poll).
        assert poll(lambda: abs(player_y() - rest_y) <= 2.0), (
            "Player did not land before firing"
        )

        # --- i-frame live proof: two shots a few frames apart (~0.13s at 60fps,
        # far inside the window) must land exactly ONE hit. One input sequence,
        # so the shot spacing is frame-exact, immune to CLI-call latency.
        fire(
            [
                {"type": "action", "action": "fire", "frame": 0},
                {"type": "action", "action": "fire", "release": True, "frame": 2},
                {"type": "action", "action": "fire", "frame": 8},
                {"type": "action", "action": "fire", "release": True, "frame": 10},
            ]
        )
        assert poll(lambda: len(records("laser_fired")) >= 2), (
            "both fire presses should each spawn a bolt"
        )
        fired = records("laser_fired")
        assert fired[0]["fields"]["facing"] == pytest.approx(1.0)
        # Wait for the first hit, then give the second bolt time to arrive and
        # be i-frame-blocked (arrivals are ~0.13s apart; 2s is far past both).
        assert poll(lambda: len(records("enemy_hit")) >= 1), (
            "the first bolt should hit the Enemy"
        )
        time.sleep(2.0)
        hits = records("enemy_hit")
        assert len(hits) == 1, (
            f"i-frames should block the chained second hit, got {len(hits)}: {hits}"
        )
        assert hits[0]["fields"]["damage"] == pytest.approx(damage)
        assert hits[0]["fields"]["hp_left"] == pytest.approx(max_hp - damage)

        # --- kill loop: single shots spaced past the i-frame window drive HP
        # strictly down to 0. CLI-call latency plus an explicit sleep guarantees
        # the spacing; the loop bound is derived from the config, not guessed.
        for _ in range(hits_to_kill * 2):
            if records("enemy_died"):
                break
            time.sleep(iframe + 0.3)
            fire(
                [
                    {"type": "action", "action": "fire", "frame": 0},
                    {"type": "action", "action": "fire", "release": True, "frame": 2},
                ]
            )
            poll(lambda: bool(records("enemy_died")), timeout=3.0)
        died = poll(lambda: records("enemy_died"))
        assert died, "the Enemy never died"

        hits = records("enemy_hit")
        assert len(hits) == hits_to_kill, (
            f"expected {hits_to_kill} landed hits to kill, got {len(hits)}: {hits}"
        )
        hp_trace = [h["fields"]["hp_left"] for h in hits]
        assert hp_trace == sorted(hp_trace, reverse=True), (
            f"hp_left should strictly decrease: {hp_trace}"
        )
        assert all(a > b for a, b in zip(hp_trace, hp_trace[1:])), (
            f"hp_left should strictly decrease: {hp_trace}"
        )
        assert hp_trace[-1] == pytest.approx(0.0), (
            f"the killing hit should leave 0 HP: {hp_trace}"
        )

        # The dead Enemy leaves the runtime tree (queue_free is deferred — poll).
        def enemy_gone() -> bool:
            t = run("game", "tree")
            assert t.returncode == 0, t.stdout + t.stderr
            return _find_node(json.loads(t.stdout)["root"], "Enemy") is None

        assert poll(enemy_gone), "the dead Enemy is still in the scene tree"
    finally:
        run("daemon", "stop")
