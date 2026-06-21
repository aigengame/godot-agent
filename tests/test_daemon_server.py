"""DaemonServer request handling, in-process (#7).

Exercises the server's request branching directly (no spawned process, no real
engine), so the no-session and control-op paths stay covered in the fast suite.
"""

import os

import pytest

from gda.daemon.discovery import daemon_paths
from gda.daemon.server import DaemonServer
from gda.parser import parse_result

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


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
