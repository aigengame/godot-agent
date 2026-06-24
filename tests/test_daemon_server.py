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


def test_a_nonexistent_scene_selector_is_a_typed_live_scene_not_found(tmp_path):
    # #278 / ADR-0017 amendment: a missing/non-existent `--scene` selector MUST
    # surface a typed `live_scene_not_found` — NEVER a silent fall back to
    # main_scene. The daemon validates the res:// selector against the project
    # before launching, so the failure is precise (not a vague launch error).
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    server = DaemonServer(
        daemon_paths(tmp_path), godot="godot", scene="res://nope.tscn"
    )

    reply = server._handle({"op": "game-tree", "params": {}})

    assert parse_result(reply["stdout"])["error"]["code"] == "live_scene_not_found"


def test_an_existing_scene_selector_passes_the_validation_gate(tmp_path):
    # An existing res:// scene passes scene validation; with no real Godot binary
    # the launch then fails as engine_session_not_running (not scene_not_found) —
    # proving the gate let a real scene through.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (tmp_path / "B.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
    server = DaemonServer(daemon_paths(tmp_path), godot="", scene="res://B.tscn")

    reply = server._handle({"op": "game-tree", "params": {}})

    assert (
        parse_result(reply["stdout"])["error"]["code"]
        == "engine_session_not_running"
    )


def test_a_uid_scene_selector_passes_the_validation_gate(tmp_path):
    # A `uid://…` selector cannot be checked by file existence daemon-side; it is
    # passed through to the engine, so it clears the gate (and then fails to launch
    # here with no real binary) rather than being wrongly rejected as not-found.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    server = DaemonServer(daemon_paths(tmp_path), godot="", scene="uid://abc123")

    reply = server._handle({"op": "game-tree", "params": {}})

    assert (
        parse_result(reply["stdout"])["error"]["code"]
        == "engine_session_not_running"
    )


def test_no_scene_selector_runs_main_scene_unchanged(tmp_path):
    # The selector-less default is unchanged: no scene validation, straight to the
    # launch path (which here is engine_session_not_running with no real binary).
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    server = DaemonServer(daemon_paths(tmp_path), godot="")

    reply = server._handle({"op": "game-tree", "params": {}})

    assert (
        parse_result(reply["stdout"])["error"]["code"]
        == "engine_session_not_running"
    )


def test_control_ops_report_liveness_and_request_stop(tmp_path):
    server = DaemonServer(daemon_paths(tmp_path), godot="")

    assert server._handle({"op": "__status__"})["ok"] is True

    stop = server._handle({"op": "__stop__"})
    assert stop["ok"] is True
    assert server._stopping is True


def test_status_op_reports_the_declared_display_mode(tmp_path):
    # `daemon status` reads the running daemon's launch-time display mode over
    # STATUS_OP (#251) — the daemon is the only authority for the mode it was
    # started with — so the control reply must carry `windowed`.
    headless = DaemonServer(daemon_paths(tmp_path), godot="")
    assert headless._handle({"op": "__status__"})["windowed"] is False

    windowed = DaemonServer(daemon_paths(tmp_path), godot="", windowed=True)
    assert windowed._handle({"op": "__status__"})["windowed"] is True


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
