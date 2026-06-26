"""S1 (e2e): `gda game` live commands through the real `gda` CLI (`python -m gda`, #7).

This slice's real path is the attach-or-fail: a real ``gda game tree`` with no
running daemon must emit the typed ``daemon_not_running`` envelope and exit
``EXIT_LIVE`` — exercised through the out-of-process `gda` CLI and the real
``DaemonRunner`` + discovery (no fake at the seam). The connected path (a live
tree from a real engine session) lands with the daemon, a later slice. Per
RULES.md DoD the fake-runner command tests do not count toward this gate.
"""

import json
import os
import subprocess

import pytest

from gda.exit_codes import EXIT_LIVE

from tests.support import GDA_CMD


@pytest.mark.e2e
def test_game_tree_without_a_daemon_reports_daemon_not_running(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    # An empty runtime dir so discovery finds no daemon for this fresh project.
    env = {**os.environ, "XDG_RUNTIME_DIR": str(tmp_path / "run")}
    proc = subprocess.run(
        [*GDA_CMD, "game", "tree", "--project", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode == EXIT_LIVE, proc.stdout + proc.stderr
    error = json.loads(proc.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert error["category"] == "live"
    assert "gda daemon start" in error["message"]
