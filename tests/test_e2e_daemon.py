"""S1 (e2e): the full gda-daemon live loop through the console script (#7).

The Step-6 proof: a real ``gda daemon start`` (real detached daemon, real harness
install, live-version gate) → a real engine session it launches on demand →
``gda game tree`` returns the RUNNING game's runtime scene tree, observed live via
the harness over Unix domain sockets → ``gda daemon stop`` tears it down. Run e2e
serially; not a fresh empty HOME (Godot first-run).
"""

import json
import os
import shutil
import subprocess
import tempfile

import pytest

from gda.binary import resolve_godot_binary

from .conftest import project_godot

GODOT = resolve_godot_binary()

# A trivial main scene so the launched session has a runtime SceneTree to read;
# file logging stays disabled via project_godot (issue #180).
MAIN_TSCN = '[gd_scene format=3]\n\n[node name="Main" type="Node2D"]\n'
PROJECT_GODOT = project_godot(extra='run/main_scene="res://main.tscn"')

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


@pytest.mark.e2e
def test_daemon_serves_a_real_runtime_tree(tmp_path):
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")

    # A SHORT runtime dir so the daemon's UDS paths fit sun_path (~104B).
    runtime = tempfile.mkdtemp(prefix="gda-e2e-", dir="/tmp")
    env = {**os.environ, "XDG_RUNTIME_DIR": runtime}

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
        shutil.rmtree(runtime, ignore_errors=True)
