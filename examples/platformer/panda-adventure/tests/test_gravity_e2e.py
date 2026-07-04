"""Integration seam (c) for S3 Gravity Gun / Gravity Field / MP economy — THE gate.

The full change-gravity loop through the gda CLI against a running Engine
session:

- ``gda game tree`` shows the scene-authored Obstacle; ``gda logger tail``
  returns its data-driven ``obstacle_ready`` record;
- ``fire`` fires the CURRENT weapon: before any switch it spawns a Laser bolt
  (``laser_fired``), never a Gravity Field — the spawn default;
- ``switch_weapon`` toggles to the Gravity Gun (``weapon_switched``) and
  ``fire`` now spends MP (``gravity_fired {mp_before, mp_after}``) and spawns
  a Gravity Field: the field is in the runtime tree, its ``gravity_field_
  spawned`` record carries the data-driven velocity/radius/duration, the
  in-range Obstacle is lifted, the out-of-range Enemy does NOT move (the field
  is LOCAL), and the Player never moves off its resting y (never affected —
  the collision mask, gADR-0002);
- walking into range and firing again lifts the Enemy up to exactly its
  config displacement clamp (clamped-displacement integration, gADR-0002);
- repeated fires drain MP to 0; at 0 MP the fire is refused
  (``gravity_blocked``, no new field) — the MP gate;
- ``drink_wine`` restores MP (``wine_drunk``) and the Gravity Gun fires again;
- switching back re-arms the Laser Gun (``laser_fired`` again) — the weapon
  toggle round-trips.

Every expectation derives from the AUTHORITATIVE JSON configs, never
hardcoded. Per RULES.md, mocks cannot replace this end-to-end proof.

Isolation: same throwaway-copy pattern as ``test_player_e2e`` (``daemon
start`` mutates ``project.godot``); posix-only (AF_UNIX); headless —
Linux-CI-friendly.
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


@pytest.mark.e2e
def test_daemon_serves_gravity_loop(tmp_path, daemon_runtime_dir):
    project = _make_project_copy(tmp_path / "game")
    # Every expectation derives from the AUTHORITATIVE JSON, never hardcoded.
    gravity = build_config.load_json(GAME_DIR / "data" / "json" / "gravity_config.json")
    combat = build_config.load_json(GAME_DIR / "data" / "json" / "combat_config.json")
    player_cfg = build_config.load_json(
        GAME_DIR / "data" / "json" / "player_config.json"
    )
    mp_max = combat["player_stats"]["max_mp"]
    mp_cost = gravity["mp_cost"]
    wine_restore = gravity["wine_mp_restore"]
    obstacle_pos = gravity["obstacle_position"]
    enemy_pos = combat["enemy_position"]
    enemy_clamp = gravity["enemy_max_gravity_offset"]
    # The field velocity the runtime derives from the data (direction x strength).
    direction = gravity["field_direction"]
    length = math.hypot(*direction)
    field_velocity = [c / length * gravity["field_strength"] for c in direction]
    rest_y = (
        player_cfg["platform_position"][1]
        - player_cfg["platform_size"][1] / 2.0
        - player_cfg["player_size"][1] / 2.0
    )
    start_x = player_cfg["player_start"][0]
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

    def node_position(path: str) -> list[float]:
        got = run("game", "get", path, "--property", "position")
        assert got.returncode == 0, got.stdout + got.stderr
        for p in json.loads(got.stdout)["properties"]:
            if p["name"] == "position":
                return p["value"]
        raise AssertionError(f"position not returned for {path}")

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

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # The scene-authored Obstacle is in the live tree; no field exists yet.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        root = json.loads(tree.stdout)["root"]
        obstacle = _find_node(root, "Obstacle")
        assert obstacle is not None and obstacle["type"] == "StaticBody2D", root
        assert _find_node(root, "GravityField") is None, root

        # Its boot record carries the data-driven placement.
        ready = poll(lambda: records("obstacle_ready"))
        assert ready, "no gda_log 'obstacle_ready' record"
        assert ready[0]["fields"]["x"] == pytest.approx(obstacle_pos[0])
        assert ready[0]["fields"]["y"] == pytest.approx(obstacle_pos[1])

        # Let the Player settle on the platform before firing (S1-proven poll).
        assert poll(
            lambda: abs(node_position("/root/Main/Player")[1] - rest_y) <= 2.0
        ), "Player did not land before firing"

        # --- Default weapon: `fire` fires the CURRENT weapon, and the spawn
        # default is the Laser Gun — a bolt, never a Gravity Field, no MP spent.
        tap("fire")
        assert poll(lambda: records("laser_fired")), (
            "the default-weapon fire should spawn a Laser bolt"
        )
        assert not records("gravity_fired"), (
            "the default-weapon fire must not fire the Gravity Gun"
        )

        # --- Switch to the Gravity Gun.
        tap("switch_weapon")
        switched = poll(lambda: records("weapon_switched"))
        assert switched, "no gda_log 'weapon_switched' record"
        assert switched[-1]["fields"]["weapon"] == "gravity_gun"

        # --- First gravity fire: spends MP from the S2 StatsSystem and spawns
        # a field whose params are the authoritative data.
        obstacle_before = node_position("/root/Main/Obstacle")
        tap("fire")
        fired = poll(lambda: records("gravity_fired"))
        assert fired, "no gda_log 'gravity_fired' record"
        assert fired[0]["fields"]["mp_before"] == pytest.approx(mp_max)
        assert fired[0]["fields"]["mp_after"] == pytest.approx(mp_max - mp_cost)

        spawned = poll(lambda: records("gravity_field_spawned"))
        assert spawned, "no gda_log 'gravity_field_spawned' record"
        assert spawned[0]["fields"]["velocity_x"] == pytest.approx(field_velocity[0])
        assert spawned[0]["fields"]["velocity_y"] == pytest.approx(field_velocity[1])
        assert spawned[0]["fields"]["radius"] == pytest.approx(gravity["field_radius"])
        assert spawned[0]["fields"]["duration"] == pytest.approx(
            gravity["field_duration"]
        )

        # The field is a real node in the runtime tree (checked within its
        # config lifetime).
        def field_in_tree() -> bool:
            t = run("game", "tree")
            assert t.returncode == 0, t.stdout + t.stderr
            return _find_node(json.loads(t.stdout)["root"], "GravityField") is not None

        assert poll(field_in_tree, timeout=gravity["field_duration"], interval=0.2), (
            "the Gravity Field never appeared in the runtime scene tree"
        )

        # The in-range Obstacle is lifted (its y decreases: lift is the shipped
        # upward default) without horizontal drift.
        assert poll(
            lambda: node_position("/root/Main/Obstacle")[1] < obstacle_before[1] - 10.0
        ), "the Gravity Field did not lift the in-range Obstacle"
        assert node_position("/root/Main/Obstacle")[0] == pytest.approx(
            obstacle_before[0], abs=1.0
        )

        # The field is LOCAL: the far-away Enemy does not move...
        assert node_position("/root/Main/Enemy") == pytest.approx(enemy_pos, abs=1.0), (
            "the out-of-range Enemy must not be affected"
        )
        # ...and it NEVER acts on the Player (mask guarantee): still resting.
        assert node_position("/root/Main/Player")[1] == pytest.approx(rest_y, abs=2.0)

        # --- Walk into range of the Enemy, fire, and the field lifts it up to
        # exactly the config displacement clamp (gADR-0002).
        #
        # Sequence `frame` offsets are IDLE frames, and a headless session's
        # idle rate is decoupled from the 60Hz physics clock, so a fixed-length
        # walk is not portable. Walk in SHORT bounded bursts with position
        # feedback instead, until the Player is inside the (wide, geometry-
        # derived) firing window: |field_center_x - enemy_x| within the field
        # radius plus the Enemy's half width, with a safety margin.
        reach = gravity["field_radius"] + combat["enemy_size"][0] / 2.0
        walk_lo = enemy_pos[0] - gravity["field_spawn_offset"][0] - reach + 30.0
        walk_hi = enemy_pos[0] - gravity["field_spawn_offset"][0] + reach - 30.0
        walk_mid = (walk_lo + walk_hi) / 2.0

        def burst_right() -> None:
            seq = run(
                "input",
                "sequence",
                "--events",
                json.dumps(
                    [
                        {"type": "action", "action": "move_right", "frame": 0},
                        {
                            "type": "action",
                            "action": "move_right",
                            "release": True,
                            "frame": 12,
                        },
                    ]
                ),
            )
            assert seq.returncode == 0, seq.stdout + seq.stderr

        player_x = start_x
        for _ in range(40):
            player_x = node_position("/root/Main/Player")[0]
            if player_x >= walk_mid - 40.0:
                break
            burst_right()
        assert walk_lo <= player_x <= walk_hi, (
            f"the Player did not stop inside the firing window: x={player_x}, "
            f"window=[{walk_lo}, {walk_hi}]"
        )

        tap("fire")
        assert poll(lambda: len(records("gravity_fired")) >= 2), (
            "the in-range fire should spend MP and spawn a field"
        )
        assert records("gravity_fired")[1]["fields"]["mp_after"] == pytest.approx(
            mp_max - 2 * mp_cost
        )
        assert poll(
            lambda: (
                node_position("/root/Main/Enemy")[1]
                == pytest.approx(enemy_pos[1] - enemy_clamp, abs=3.0)
            )
        ), "the in-range Enemy should be lifted to exactly its displacement clamp"
        assert node_position("/root/Main/Enemy")[0] == pytest.approx(
            enemy_pos[0], abs=1.0
        )

        # --- Drain the MP budget: every remaining full-cost fire succeeds...
        fires_so_far = 2
        n_more = int((mp_max - fires_so_far * mp_cost) // mp_cost)
        leftover = mp_max - (fires_so_far + n_more) * mp_cost  # < mp_cost by def
        for _ in range(n_more):
            tap("fire")
        total_fires = fires_so_far + n_more
        assert poll(lambda: len(records("gravity_fired")) >= total_fires), (
            f"expected {total_fires} gravity fires before the budget runs dry"
        )
        fired = records("gravity_fired")
        assert len(fired) == total_fires
        assert fired[-1]["fields"]["mp_after"] == pytest.approx(leftover)

        # ...and the next fire is REFUSED: blocked record, no new field, MP intact.
        tap("fire")
        blocked = poll(lambda: records("gravity_blocked"))
        assert blocked, "at insufficient MP the Gravity Gun must refuse to fire"
        assert blocked[-1]["fields"]["mp"] == pytest.approx(leftover)
        assert blocked[-1]["fields"]["mp_cost"] == pytest.approx(mp_cost)
        assert len(records("gravity_fired")) == total_fires, (
            "a refused fire must not spawn a field"
        )

        # --- Wine restores MP (capped at max), re-arming the Gravity Gun.
        tap("drink_wine")
        drunk = poll(lambda: records("wine_drunk"))
        assert drunk, "no gda_log 'wine_drunk' record"
        assert drunk[-1]["fields"]["mp_before"] == pytest.approx(leftover)
        restored = min(leftover + wine_restore, mp_max)
        assert drunk[-1]["fields"]["mp_after"] == pytest.approx(restored)

        # Config sanity for the next step: one Wine must re-arm at least one fire.
        assert restored >= mp_cost, "gravity_config: wine_mp_restore < mp_cost"
        tap("fire")
        assert poll(lambda: len(records("gravity_fired")) >= total_fires + 1), (
            "after Wine the Gravity Gun should fire again"
        )
        assert records("gravity_fired")[-1]["fields"]["mp_after"] == pytest.approx(
            restored - mp_cost
        )

        # --- Switch back: `fire` drives the Laser Gun again (the toggle
        # round-trips; existing combat flows stay reachable).
        tap("switch_weapon")
        assert poll(
            lambda: (
                records("weapon_switched")
                and records("weapon_switched")[-1]["fields"]["weapon"] == "laser_gun"
            )
        ), "switching back should re-arm the Laser Gun"
        tap("fire")
        assert poll(lambda: len(records("laser_fired")) >= 2), (
            "after switching back, fire should spawn a Laser bolt again"
        )
    finally:
        run("daemon", "stop")
