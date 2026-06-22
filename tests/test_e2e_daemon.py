"""S1 (e2e): the full gda-daemon live loop through the console script (#7).

The Step-6 proof: a real ``gda daemon start`` (real detached daemon, real harness
install, live-version gate) → a real engine session it launches on demand →
``gda game tree`` returns the RUNNING game's runtime scene tree, observed live via
the harness over Unix domain sockets → ``gda daemon stop`` tears it down. Run e2e
serially; not a fresh empty HOME (Godot first-run). The ``daemon_runtime_dir``
fixture keeps the daemon's UDS path within the OS ``sun_path`` limit.
"""

import json
import os
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

from .conftest import project_godot

GODOT = resolve_godot_binary()

# A main scene so the launched session has a runtime SceneTree to read; a Player
# Node2D child carries a Vector2 storage property (position) for the game get/set
# round trip (#220). File logging stays disabled via project_godot (issue #180).
MAIN_TSCN = (
    "[gd_scene format=3]\n\n"
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
)
PROJECT_GODOT = project_godot(extra='run/main_scene="res://main.tscn"')

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


@pytest.mark.e2e
def test_daemon_serves_a_real_runtime_tree(tmp_path, daemon_runtime_dir):
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")

    # XDG_RUNTIME_DIR is set short by the daemon_runtime_dir fixture; the spawned
    # daemon inherits it through the subprocess environment.
    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [gda, *args, "--project", str(tmp_path), "--godot", str(GODOT), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        assert json.loads(started.stdout)["installed_harness"] is True

        # The daemon launches the engine session on demand and relays the live op;
        # the result is the running game's runtime scene tree.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        root = json.loads(tree.stdout)["root"]
        assert root["name"] == "Main"
        assert root["type"] == "Node2D"

        assert json.loads(run("daemon", "status").stdout)["running"] is True
        assert json.loads(run("daemon", "stop").stdout)["stopped"] is True
        assert json.loads(run("daemon", "status").stdout)["running"] is False
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_serves_game_get_set_round_trip(tmp_path, daemon_runtime_dir):
    # The #220 DoD: a real daemon → engine session → `game set` mutates a runtime
    # property, applied at a frame boundary, and `game get` observes the change —
    # State consistency (ADR-0020) end-to-end through the real harness over UDS.
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")

    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [gda, *args, "--project", str(tmp_path), "--godot", str(GODOT), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # set: mutate the Player's runtime position (a Vector2), coerced harness-side
        # from the CLI string "10,20" exactly as headless `node set` coerces it.
        was_set = run(
            "game", "set", "/root/Main/Player", "--property", "position", "--value", "10,20"
        )
        assert was_set.returncode == 0, was_set.stdout + was_set.stderr
        set_doc = json.loads(was_set.stdout)
        assert set_doc["path"] == "/root/Main/Player"
        assert set_doc["property"] == "position"
        assert set_doc["type"] == "Vector2"
        assert set_doc["value"] == [10.0, 20.0]

        # get: the SAME session observes the preceding write (single writer,
        # frame-coherent — ADR-0020). The session is held across the two ops.
        got = run("game", "get", "/root/Main/Player", "--property", "position")
        assert got.returncode == 0, got.stdout + got.stderr
        get_doc = json.loads(got.stdout)
        assert get_doc["path"] == "/root/Main/Player"
        position = next(p for p in get_doc["properties"] if p["name"] == "position")
        assert position["type"] == "Vector2"
        assert position["value"] == [10.0, 20.0]
    finally:
        run("daemon", "stop")
