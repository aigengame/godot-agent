"""S (e2e): `gda perf` live commands through the real gda-daemon loop (#223).

The Step-6 proof for perf: a real `gda daemon start` (real detached daemon, real
harness install, live-version gate) -> a real engine session it launches on
demand -> `gda perf monitors` returns the RUNNING game's live performance
snapshot, and `gda perf monitor --property ... --frames N` returns an N-sample
per-frame timeline collected by the harness's time-windowed multi-frame base.
Run e2e SERIALLY; not a fresh empty HOME (Godot first-run). The
`daemon_runtime_dir` fixture keeps the daemon's UDS path within `sun_path`.
"""

import json
import os
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

from .conftest import project_godot

GODOT = resolve_godot_binary()

# A main scene with a Player Node2D so the launched session has a runtime
# SceneTree to monitor; Player.position is a Vector2 storage property the property
# timeline samples each frame. File logging stays disabled via project_godot (#180).
MAIN_TSCN = (
    "[gd_scene format=3]\n\n"
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
)
PROJECT_GODOT = project_godot(extra='run/main_scene="res://main.tscn"')

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


@pytest.mark.e2e
def test_daemon_serves_a_live_perf_snapshot(tmp_path, daemon_runtime_dir):
    # `perf monitors`: a real daemon -> engine session -> the running game's live
    # Performance counters, snapshotted in one frame (frame-coherent, ADR-0020).
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

        snap = run("perf", "monitors")
        assert snap.returncode == 0, snap.stdout + snap.stderr
        doc = json.loads(snap.stdout)
        # A real snapshot: a timestamp and the named monitors, with live values.
        assert isinstance(doc["timestamp"], int)
        monitors = doc["monitors"]
        assert "fps" in monitors and "static_memory" in monitors
        assert "node_count" in monitors and "draw_calls" in monitors
        # node_count is the running tree's live node total (at least Main + Player).
        assert monitors["node_count"]["value"] >= 2
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_serves_a_property_timeline_over_a_window(tmp_path, daemon_runtime_dir):
    # `perf monitor --property --frames N`: the time-windowed multi-frame base
    # (#223) collects one sample per frame across the engine session and returns
    # the whole N-sample timeline in a single blocking call (ADR-0017 one-shot RPC).
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

        timeline = run(
            "perf", "monitor", "/root/Main/Player",
            "--property", "position", "--frames", "5",
        )
        assert timeline.returncode == 0, timeline.stdout + timeline.stderr
        doc = json.loads(timeline.stdout)
        assert doc["node"] == "/root/Main/Player"
        assert doc["kind"] == "property"
        assert doc["property"] == "position"
        # An N-sample timeline, one per frame, frame-indexed 0..N-1 (ADR-0020).
        assert doc["frames"] == 5
        assert len(doc["samples"]) == 5
        assert [s["frame"] for s in doc["samples"]] == [0, 1, 2, 3, 4]
        # Each sample carries the Vector2 position projection [x, y].
        assert all(len(s["value"]) == 2 for s in doc["samples"])
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_perf_monitor_missing_node_reports_live_perf_node_not_found(tmp_path, daemon_runtime_dir):
    # A path that resolves to no running node is the typed harness op-error,
    # relayed through the daemon (exit-0 sentinel) and mapped by classify_live.
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
        assert run("daemon", "start").returncode == 0

        from gda.exit_codes import EXIT_LIVE

        missing = run(
            "perf", "monitor", "/root/Main/Ghost", "--property", "position", "--frames", "2"
        )
        assert missing.returncode == EXIT_LIVE, missing.stdout + missing.stderr
        assert json.loads(missing.stdout)["error"]["code"] == "live_perf_node_not_found"
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_perf_monitors_without_a_daemon_reports_daemon_not_running(tmp_path):
    # The attach-or-fail path through the real DaemonRunner + discovery, no daemon.
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    from gda.exit_codes import EXIT_LIVE

    env = {**os.environ, "XDG_RUNTIME_DIR": str(tmp_path / "run")}
    proc = subprocess.run(
        [gda, "perf", "monitors", "--project", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode == EXIT_LIVE, proc.stdout + proc.stderr
    error = json.loads(proc.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert "gda daemon start" in error["message"]
