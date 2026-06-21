"""DaemonServer request handling, in-process (#7).

Exercises the server's request branching directly (no spawned process, no real
engine), so the no-session and control-op paths stay covered in the fast suite.
"""

import os
import socket

import pytest

from gda.daemon.discovery import daemon_paths
from gda.daemon.server import DaemonServer
from gda.daemon.session import EngineSession
from gda.daemon_ops import (
    run_daemon_status_operation,
    run_daemon_stop_operation,
)
from gda.errors import Failure
from gda.parser import parse_result

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


class _FakeProc:
    def poll(self):
        return None


def test_live_op_without_a_launchable_session_is_engine_session_not_running(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    # No Godot binary -> ensure_session cannot launch -> engine_session_not_running.
    server = DaemonServer(daemon_paths(tmp_path), godot="")

    reply = server._handle({"op": "game-tree", "params": {}})

    assert parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"


def test_control_ops_report_liveness_and_request_stop(tmp_path):
    server = DaemonServer(daemon_paths(tmp_path), godot="")

    assert server._handle({"op": "__status__"})["ok"] is True

    stop = server._handle({"op": "__stop__"})
    assert stop["ok"] is True
    assert server._stopping is True


def test_engine_session_request_times_out_as_live_timeout(monkeypatch):
    # A harness that never replies must surface the registered live_timeout, not
    # hang the daemon forever (ADR-0021).
    monkeypatch.setattr("gda.daemon.session.OP_TIMEOUT", 0.2)
    daemon_end, silent_harness = socket.socketpair()
    session = EngineSession(_FakeProc(), daemon_end)
    try:
        reply = session.request("game-tree", {})
        assert parse_result(reply["stdout"])["error"]["code"] == "live_timeout"
    finally:
        daemon_end.close()
        silent_harness.close()


def test_daemon_status_on_non_unix_is_live_unsupported_platform(monkeypatch, tmp_path):
    monkeypatch.setattr("gda.daemon_ops._is_unix", lambda: False)
    outcome = run_daemon_status_operation(tmp_path)
    assert isinstance(outcome, Failure)
    assert outcome.error.code == "live_unsupported_platform"


def test_daemon_stop_on_non_unix_is_live_unsupported_platform(monkeypatch, tmp_path):
    monkeypatch.setattr("gda.daemon_ops._is_unix", lambda: False)
    outcome = run_daemon_stop_operation(tmp_path)
    assert isinstance(outcome, Failure)
    assert outcome.error.code == "live_unsupported_platform"
