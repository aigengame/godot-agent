"""S1 (e2e): `gda daemon` lifecycle through the real console script (#7).

Drives the installed ``gda`` console script against a REAL detached daemon
process: start (idempotent, reports the harness install) → status → a live op
that finds the daemon but no engine session yet (``engine_session_not_running``)
→ stop → torn down. The engine session itself is the next slice; this proves the
CLI → daemon-process → IPC path end-to-end. Python-only (no engine).
"""

import json
import os
import shutil
import subprocess
import tempfile

import pytest

from gda.exit_codes import EXIT_LIVE

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


@pytest.mark.e2e
def test_daemon_lifecycle_through_the_cli(tmp_path):
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    # A SHORT runtime dir so the daemon's UDS path fits sun_path (~104B).
    runtime = tempfile.mkdtemp(prefix="gda-e2e-", dir="/tmp")
    env = {**os.environ, "XDG_RUNTIME_DIR": runtime}

    def run(*args):
        return subprocess.run(
            [gda, *args, "--project", str(tmp_path), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        start_data = json.loads(started.stdout)
        assert start_data["already_running"] is False
        assert start_data["installed_harness"] is True
        assert start_data["pid"] > 0

        # Idempotent: a second start reports the already-running daemon.
        again = json.loads(run("daemon", "start").stdout)
        assert again["already_running"] is True and again["pid"] == start_data["pid"]

        assert json.loads(run("daemon", "status").stdout)["running"] is True

        # A live op reaches the running daemon but it holds no engine session yet.
        tree = run("game", "tree")
        assert tree.returncode == EXIT_LIVE, tree.stdout + tree.stderr
        assert json.loads(tree.stdout)["error"]["code"] == "engine_session_not_running"

        stop = run("daemon", "stop")
        assert stop.returncode == 0, stop.stdout + stop.stderr
        assert json.loads(stop.stdout)["stopped"] is True

        assert json.loads(run("daemon", "status").stdout)["running"] is False
    finally:
        run("daemon", "stop")
        shutil.rmtree(runtime, ignore_errors=True)
