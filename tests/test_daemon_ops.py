"""gda-daemon process lifecycle (#7, ADR-0017): start / status / stop.

Spawns the REAL detached daemon process (Python only — no engine) against a short
runtime dir, so the socket/pidfile lifecycle, idempotent start, and the
no-session live-op reply are exercised end-to-end without Godot.
"""

import os
import shutil
import socket
import tempfile
from pathlib import Path

import pytest

from gda.daemon.discovery import daemon_paths, daemon_pid
from gda.daemon.protocol import read_message, write_message
from gda.daemon_ops import (
    run_daemon_start_operation,
    run_daemon_status_operation,
    run_daemon_stop_operation,
)
from gda.models import DaemonStartResult, DaemonStatusResult, DaemonStopResult
from gda.parser import parse_result

# The daemon binds AF_UNIX sockets — UNIX-only (ADR-0021).
pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


@pytest.fixture
def short_runtime(monkeypatch):
    # A real UDS path must fit the OS ``sun_path`` limit (~104B); pytest's macOS
    # tmp_path is already too long, so point XDG_RUNTIME_DIR at a short /tmp dir.
    runtime = tempfile.mkdtemp(prefix="gda-", dir="/tmp")
    monkeypatch.setenv("XDG_RUNTIME_DIR", runtime)
    yield Path(runtime)
    shutil.rmtree(runtime, ignore_errors=True)


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


def test_daemon_start_status_stop_lifecycle(tmp_path, short_runtime):
    project = _project(tmp_path)
    paths = daemon_paths(project)

    try:
        started = run_daemon_start_operation(project, None)
        assert isinstance(started, DaemonStartResult), started
        assert started.already_running is False
        assert started.installed_harness is True  # harness installed + reported
        assert daemon_pid(paths) == started.pid

        # Idempotent: a second start finds the running daemon.
        again = run_daemon_start_operation(project, None)
        assert isinstance(again, DaemonStartResult)
        assert again.already_running is True
        assert again.pid == started.pid
        assert again.installed_harness is False

        status = run_daemon_status_operation(project)
        assert isinstance(status, DaemonStatusResult)
        assert status.running is True and status.pid == started.pid

        # A live op against the running daemon: no session held yet, so it returns
        # the engine_session_not_running sentinel through the normal reply.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(str(paths.cli_socket))
            write_message(sock, {"op": "game-tree", "params": {}})
            reply = read_message(sock)
        assert parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    finally:
        stopped = run_daemon_stop_operation(project)
        assert isinstance(stopped, DaemonStopResult)

    # Torn down: pidfile dead, socket gone.
    assert daemon_pid(paths) is None
    assert not paths.cli_socket.exists()


def test_daemon_status_and_stop_when_not_running(tmp_path, short_runtime):
    project = _project(tmp_path)

    status = run_daemon_status_operation(project)
    assert isinstance(status, DaemonStatusResult) and status.running is False

    stopped = run_daemon_stop_operation(project)
    assert isinstance(stopped, DaemonStopResult) and stopped.stopped is False
