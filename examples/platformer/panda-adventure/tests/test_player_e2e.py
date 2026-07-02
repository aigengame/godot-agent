"""Integration seam (c) for S1 player traversal — THE gate.

The full live loop through the gda CLI against a running Engine session:

- ``gda daemon start`` installs the GdaHarness and launches the game;
- ``gda game tree`` shows the data-driven Player (CharacterBody2D), the Platform
  (StaticBody2D) it lands on, and the follow Camera2D;
- ``gda game get`` reads the Player's runtime ``position``: it has fallen from its
  spawn and come to rest exactly on the platform surface — proof that gravity,
  falling, landing, and platform collision all work end-to-end;
- ``gda input sequence`` presses ``move_right`` across frames and the Player's
  ``position.x`` advances — proof the registered InputMap action drives movement;
- ``gda game get`` on the Camera2D confirms smooth-follow is enabled;
- ``gda logger tail`` reads back the rich ``boot`` record.

Per RULES.md, mocks cannot replace this end-to-end proof.

Isolation: ``gda daemon start`` MUTATES ``project.godot`` (installs the autoload)
and copies harness files into ``res://``, so this runs against a throwaway COPY
of the committed project and never touches the real one. posix-only — the live
stack uses ``AF_UNIX`` (ADR-0021). No display needed (input + physics + property
reads are all headless), so this stays Linux-CI-friendly.
"""

from __future__ import annotations

import json
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

# Same-environment gda resolution (ADR-0011): the module in this interpreter.
GDA_CMD = [sys.executable, "-m", "gda"]
GODOT = resolve_godot_binary()
GAME_DIR = build_config.GAME_DIR

# Not copied into the throwaway project: the test suite itself, import/build
# artifacts, and the derived .tres (rebuilt into the copy below).
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


def _prop(get_result: dict, name: str):
    """Pull a single property value out of a ``gda game get`` result."""
    for p in get_result["properties"]:
        if p["name"] == name:
            return p["value"]
    raise AssertionError(f"property {name!r} not in {get_result}")


@pytest.mark.e2e
def test_daemon_serves_player_traversal(tmp_path, daemon_runtime_dir):
    project = _make_project_copy(tmp_path / "game")
    # Compare against the AUTHORITATIVE JSON, not hardcoded expectations.
    config = build_config.load_json(GAME_DIR / "data" / "json" / "player_config.json")
    # Where the Player comes to rest: platform top minus half the player height
    # (both bodies centered on their origin). Proof the fall was stopped by the
    # platform exactly at its surface.
    rest_y = (
        config["platform_position"][1]
        - config["platform_size"][1] / 2.0
        - config["player_size"][1] / 2.0
    )
    start_x = config["player_start"][0]
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

    def player_position() -> list[float]:
        got = run("game", "get", "/root/Main/Player", "--property", "position")
        assert got.returncode == 0, got.stdout + got.stderr
        return _prop(json.loads(got.stdout), "position")

    def poll_landed(timeout: float = 20.0) -> list[float]:
        # The session launches + runs real-time; the Player falls and lands within
        # a fraction of a second. Poll until it has settled on the platform.
        deadline = time.monotonic() + timeout
        pos = player_position()
        while time.monotonic() < deadline:
            if abs(pos[1] - rest_y) <= 2.0:
                return pos
            time.sleep(0.5)
            pos = player_position()
        return pos

    def poll_boot_record(timeout: float = 20.0) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            proc = run("logger", "tail")
            assert proc.returncode == 0, proc.stdout + proc.stderr
            for record in json.loads(proc.stdout)["records"]:
                if record["message"] == "boot" and record["origin"] == "gda_log":
                    return record
            time.sleep(1.0)
        return None

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        # `installed_harness` is NOT asserted True here: this project COMMITS the
        # gda harness (autoload + addons/gda_harness/), so `daemon start` finds it
        # already present and content-matching — an idempotent no-op, not a fresh
        # install (installed_harness is then False/null). What matters for the game
        # e2e is that the session serves; the tree/get/log below prove that.

        # First live op launches the session; the running scene tree carries the
        # data-driven blockout: the Player body, the Platform it lands on, the Camera.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        root = json.loads(tree.stdout)["root"]
        assert root["name"] == "Main"

        player = _find_node(root, "Player")
        assert player is not None and player["type"] == "CharacterBody2D", root
        platform = _find_node(root, "Platform")
        assert platform is not None and platform["type"] == "StaticBody2D", root
        camera = _find_node(root, "Camera2D")
        assert camera is not None and camera["type"] == "Camera2D", root

        # Gravity + fall + landing + collision: the Player fell from its spawn
        # (y=player_start) and came to rest on the platform surface.
        landed = poll_landed()
        assert landed[1] == pytest.approx(rest_y, abs=2.0), (
            f"Player did not land on the platform: y={landed[1]}, expected ~{rest_y}"
        )
        assert landed[0] == pytest.approx(start_x, abs=2.0), (
            f"Player drifted horizontally before input: x={landed[0]}"
        )

        # The registered move_right action drives movement: press it across frames,
        # then read the advanced position (the sequence releases it, so x is stable).
        events = [
            {"type": "action", "action": "move_right", "frame": 0},
            {"type": "action", "action": "move_right", "release": True, "frame": 24},
        ]
        seq = run("input", "sequence", "--events", json.dumps(events))
        assert seq.returncode == 0, seq.stdout + seq.stderr
        moved = player_position()
        assert moved[0] > landed[0] + 20.0, (
            f"Player did not move right on input: {landed[0]} -> {moved[0]}"
        )
        # Vertical stayed on the platform through the horizontal move.
        assert moved[1] == pytest.approx(rest_y, abs=3.0)

        # The registered jump action lifts the Player off the floor: press it, then
        # sample the arc — the lowest y (highest point) must rise well above the
        # resting surface. Sampling the min over the arc is robust to real-time
        # timing (we need only catch the Player mid-jump, not at a fixed instant).
        jump_events = [
            {"type": "action", "action": "jump", "frame": 0},
            {"type": "action", "action": "jump", "release": True, "frame": 2},
        ]
        jumped = run("input", "sequence", "--events", json.dumps(jump_events))
        assert jumped.returncode == 0, jumped.stdout + jumped.stderr
        min_y = rest_y
        for _ in range(8):
            min_y = min(min_y, player_position()[1])
        assert min_y < rest_y - 50.0, (
            f"Player did not jump: lowest y={min_y}, resting y={rest_y}"
        )

        # The follow camera is configured for smooth follow from data.
        cam_get = run(
            "game",
            "get",
            "/root/Main/Player/Camera2D",
            "--property",
            "position_smoothing_enabled",
        )
        assert cam_get.returncode == 0, cam_get.stdout + cam_get.stderr
        assert _prop(json.loads(cam_get.stdout), "position_smoothing_enabled") is True

        # The boot line is a RICH gda_log record (session daemon-launched, so
        # GameLog.emit routed through GdaHarness.gda_log).
        boot = poll_boot_record()
        assert boot is not None, "no gda_log 'boot' record found in the session log"
        assert boot["level"] == "info"
        assert boot["fields"]["scene"] == "main"
        assert boot["fields"]["move_speed"] == pytest.approx(config["move_speed"])
    finally:
        run("daemon", "stop")
