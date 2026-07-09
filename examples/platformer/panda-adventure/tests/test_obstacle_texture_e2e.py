"""Integration seam — the Obstacle renders as a TEXTURE end-to-end (P2-S1, #439).

The tracer's screenshot gate (gADR-0014): a real ``gda daemon start --windowed``
boots the data-driven scene, and we prove the Obstacle now renders the acquired
crate texture rather than the flat block — end to end from the manifest id in the
authority, through the builder's id -> path composition, to a live sprite on screen:

- ``gda game tree`` shows a ``Sprite`` (TextureRect) child under
  ``/root/Main/Obstacle/Visual`` — the ViewBuilder adds it ONLY when the resolved
  texture loads (a null load takes the colored-block fallback and adds no child),
  so its presence is proof the texture path was taken;
- ``gda screen capture`` writes a real PNG of the running viewport (decodable, the
  screenshot the AC calls for).

Modeled on ``test_e2e_screenshot.py``: a throwaway project COPY (``daemon start``
mutates ``project.godot``), display-gated (skips visibly, ``-rs``, where no window
server is usable), posix-only (the live stack is ``AF_UNIX``). The copy carries the
committed ``assets/`` tree (the texture + its ``.import`` + the manifest), so its
rebuilt ``gravity_config.tres`` resolves the obstacle path just like the shipped one.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import time

import pytest

from gda.binary import resolve_godot_binary
from gda.display import windowed_unavailable_reason

import build_config

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")

GDA_CMD = [sys.executable, "-m", "gda"]
GODOT = resolve_godot_binary()
GAME_DIR = build_config.GAME_DIR
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

_COPY_IGNORE = shutil.ignore_patterns(
    "tests", ".godot", "build", "generated", "__pycache__"
)
_NO_DISPLAY_CODES = {"live_windowed_unavailable", "live_display_unavailable"}


def _error_code(stdout: str) -> str | None:
    try:
        return json.loads(stdout).get("error", {}).get("code")
    except (ValueError, AttributeError):
        return None


def _find_node(node: dict, name: str) -> dict | None:
    """Depth-first search a ``game tree`` subtree for a node by name."""
    if node.get("name") == name:
        return node
    for child in node.get("children", []):
        found = _find_node(child, name)
        if found is not None:
            return found
    return None


def _find_projectile_with_sprite(node: dict) -> dict | None:
    """Any live ``Projectile`` bolt whose Visual carries a ``Sprite`` child.

    Godot auto-names bolt instances ``Projectile``/``@Projectile@N``, so match on
    the name prefix; the ``Sprite`` (TextureRect) child is added ONLY when the
    resolved ``laser_bolt`` texture loads — its presence is proof of the texture
    path (a null load takes the block fallback and adds no child, #442/#439).
    """
    if "Projectile" in node.get("name", "") and _find_node(node, "Sprite") is not None:
        return node
    for child in node.get("children", []):
        found = _find_projectile_with_sprite(child)
        if found is not None:
            return found
    return None


def _make_project_copy(dst):
    shutil.copytree(GAME_DIR, dst, ignore=_COPY_IGNORE)
    build_config.build_all(root=dst)
    # Import the copy so the daemon session can load() the obstacle texture — the
    # `.godot` cache is not copied, and a game run does not auto-import (#439).
    subprocess.run(
        [str(GODOT), "--headless", "--path", str(dst), "--import"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return dst


@pytest.mark.e2e
def test_obstacle_renders_the_texture(tmp_path, daemon_runtime_dir):
    reason = windowed_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)
    project = _make_project_copy(tmp_path / "game")
    env = {**os.environ}
    out = tmp_path / "shot.png"

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
            timeout=120,
        )

    try:
        started = run("daemon", "start", "--windowed")
        if started.returncode != 0:
            code = _error_code(started.stdout)
            if code in _NO_DISPLAY_CODES:
                pytest.skip(f"windowed session unavailable ({code})")
            raise AssertionError(started.stdout + started.stderr)
        assert json.loads(started.stdout)["windowed"] is True

        # The running Obstacle renders the resolved texture: its Visual carries a
        # Sprite (TextureRect) child, added ONLY on a successful texture load.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        root = json.loads(tree.stdout)["root"]
        obstacle = _find_node(root, "Obstacle")
        assert obstacle is not None, tree.stdout
        sprite = _find_node(obstacle, "Sprite")
        assert sprite is not None, (
            "the Obstacle's Visual has no Sprite child — the texture did not load "
            "(the block fallback was taken)"
        )
        assert sprite["type"] == "TextureRect", sprite

        # A real PNG of the running viewport — the screenshot the AC calls for.
        cap = run("screen", "capture", "--output", str(out))
        if cap.returncode != 0:
            code = _error_code(cap.stdout)
            if code in _NO_DISPLAY_CODES:
                pytest.skip(f"windowed session unavailable ({code})")
            raise AssertionError(cap.stdout + cap.stderr)
        doc = json.loads(cap.stdout)
        assert doc["format"] == "png"
        assert doc["width"] > 0 and doc["height"] > 0
        data = out.read_bytes()
        assert data.startswith(PNG_MAGIC), data[:16]
        width, height = struct.unpack(">II", data[16:24])
        assert (width, height) == (doc["width"], doc["height"])
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_laser_projectile_renders_the_texture(tmp_path, daemon_runtime_dir):
    """The Laser Gun bolt renders its acquired texture live (P2-S3, #442).

    The obstacle-tracer pattern extended to a spawned actor: firing the Laser Gun
    (the boot-default weapon) spawns a Projectile bolt, and — because
    ``combat_config`` ``projectile_asset`` now resolves to ``laser_bolt`` — the
    bolt's Visual carries a ``Sprite`` (TextureRect) child, added ONLY on a
    successful texture load. We fire repeatedly (each press spawns one bolt that
    lives its full lifetime), so a ``game tree`` read reliably catches a live bolt
    carrying the Sprite — end to end from the manifest id through the builder's
    id -> path composition to a live textured bolt.
    """
    reason = windowed_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)
    project = _make_project_copy(tmp_path / "game")
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
            timeout=120,
        )

    def fire() -> None:
        seq = run(
            "input",
            "sequence",
            "--events",
            json.dumps(
                [
                    {"type": "action", "action": "fire", "frame": 0},
                    {"type": "action", "action": "fire", "release": True, "frame": 4},
                ]
            ),
        )
        assert seq.returncode == 0, seq.stdout + seq.stderr

    try:
        started = run("daemon", "start", "--windowed")
        if started.returncode != 0:
            code = _error_code(started.stdout)
            if code in _NO_DISPLAY_CODES:
                pytest.skip(f"windowed session unavailable ({code})")
            raise AssertionError(started.stdout + started.stderr)
        assert json.loads(started.stdout)["windowed"] is True

        found = None
        deadline = time.monotonic() + 20.0
        while found is None and time.monotonic() < deadline:
            fire()
            tree = run("game", "tree")
            if tree.returncode != 0:
                code = _error_code(tree.stdout)
                if code in _NO_DISPLAY_CODES:
                    pytest.skip(f"windowed session unavailable ({code})")
                raise AssertionError(tree.stdout + tree.stderr)
            found = _find_projectile_with_sprite(json.loads(tree.stdout)["root"])
            if found is None:
                time.sleep(0.3)

        assert found is not None, (
            "no live Projectile carried a Sprite child — the laser_bolt texture "
            "did not load (the block fallback was taken)"
        )
        sprite = _find_node(found, "Sprite")
        assert sprite is not None and sprite["type"] == "TextureRect", found
    finally:
        run("daemon", "stop")
