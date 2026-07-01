"""DaemonServer request handling, in-process (#7).

Exercises the server's request branching directly (no spawned process, no real
engine), so the no-session and control-op paths stay covered in the fast suite.
"""

import os
import socket
import subprocess
from typing import cast

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
    assert reply is not None

    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )


def test_malformed_control_request_is_dropped_not_raised(tmp_path):
    # A malformed control frame crosses the IPC boundary from a client process —
    # read_message decodes any JSON value, so the frame may not even be an object.
    # Every malformed shape must be DROPPED (_handle returns None so the serve loop
    # survives), never raise an exception that would escape _accept_loop and kill the
    # daemon (regression: an assert, then an unguarded .get, used to do exactly that).
    server = DaemonServer(daemon_paths(tmp_path), godot="")

    assert server._handle({}) is None  # no "op"
    assert server._handle({"op": 1}) is None  # non-string "op"
    assert server._handle([]) is None  # non-dict frame
    assert server._handle("x") is None  # non-dict frame
    assert server._handle(1) is None  # non-dict frame


# --- #278 (review): scene verification happens at LAUNCH (in the harness), never
# per-request. The daemon maps the launch outcome: a verified session is cached and
# reused without re-checking (so deleting the scene file mid-session does NOT break
# live ops); a scene MISMATCH (loaded scene != requested selector, incl. a bad uid
# that Godot fell back from) tears the session down and is a typed live_scene_not_found.


def _project_with_marker(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return daemon_paths(tmp_path)


def test_scene_mismatch_at_launch_is_a_typed_live_scene_not_found(
    tmp_path, monkeypatch
):
    # The harness reported the loaded scene != the requested selector (the no-silent-
    # fallback guarantee, incl. a bad uid Godot replaced with main_scene): the daemon
    # surfaces a typed live_scene_not_found, not a vague launch error.
    from gda.daemon.session import SceneMismatch

    def _mismatch(*a, **k):
        raise SceneMismatch("res://B.tscn", "res://main.tscn")

    monkeypatch.setattr("gda.daemon.server.launch_session", _mismatch)
    server = DaemonServer(
        _project_with_marker(tmp_path), godot="godot", scene="res://B.tscn"
    )
    # launch_session is patched; the listener value is unused (just non-None).
    server._harness_listener = cast(socket.socket, object())

    reply = server._handle({"op": "game-tree", "params": {}})
    assert reply is not None

    assert parse_result(reply["stdout"])["error"]["code"] == "live_scene_not_found"
    # The half-alive (wrong-scene) session was NOT cached for reuse.
    assert server._session is None


def test_a_verified_session_is_reused_without_re_checking_the_scene(
    tmp_path, monkeypatch
):
    # Finding 1 fix: scene is verified ONCE at launch. A verified session is cached
    # and reused on later ops — launch_session is called exactly once even across
    # multiple live ops (no per-request disk/scene re-validation), so deleting the
    # scene file after launch cannot break a live op.
    calls = {"n": 0}
    served = EngineSession(cast(subprocess.Popen, _FakeProc()), conn=None)
    monkeypatch.setattr(
        served,
        "request",
        lambda op, params: {"stdout": "ok", "stderr": "", "exit_code": 0},
    )

    def _launch_once(*a, **k):
        calls["n"] += 1
        return served

    # The selector names a scene that EXISTS, so the launch-boundary res:// pre-check
    # passes and the (patched) launch proceeds; the point is it launches only ONCE.
    (tmp_path / "B.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
    monkeypatch.setattr("gda.daemon.server.launch_session", _launch_once)
    server = DaemonServer(
        _project_with_marker(tmp_path), godot="godot", scene="res://B.tscn"
    )
    # launch_session is patched; the listener value is unused (just non-None).
    server._harness_listener = cast(socket.socket, object())

    server._handle({"op": "game-tree", "params": {}})
    server._handle({"op": "game-tree", "params": {}})
    server._handle({"op": "game-tree", "params": {}})

    assert calls["n"] == 1  # launched (and verified) once, reused thereafter


def test_a_generic_launch_failure_is_engine_session_not_running(tmp_path, monkeypatch):
    # A None launch outcome (no connect / bad token / timeout) stays the generic
    # engine_session_not_running — distinct from a scene mismatch. The selector
    # exists, so the res:// pre-check passes and the (patched) launch is reached.
    (tmp_path / "B.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
    monkeypatch.setattr("gda.daemon.server.launch_session", lambda *a, **k: None)
    server = DaemonServer(
        _project_with_marker(tmp_path), godot="godot", scene="res://B.tscn"
    )
    # launch_session is patched; the listener value is unused (just non-None).
    server._harness_listener = cast(socket.socket, object())

    reply = server._handle({"op": "game-tree", "params": {}})
    assert reply is not None

    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )


def test_missing_res_scene_is_live_scene_not_found_before_launch(tmp_path, monkeypatch):
    # A res:// selector that names NO file is rejected at the launch boundary, BEFORE
    # launching — Godot would fail to launch (not fall-back-and-run) for a missing
    # res:// path, so the harness verification can't see it; the daemon's pre-check
    # surfaces the typed live_scene_not_found and never spawns the engine (#278).
    def _must_not_launch(*a, **k):
        raise AssertionError(
            "launch_session must not be called for a missing res:// scene"
        )

    monkeypatch.setattr("gda.daemon.server.launch_session", _must_not_launch)
    server = DaemonServer(
        _project_with_marker(tmp_path), godot="godot", scene="res://nope.tscn"
    )
    server._harness_listener = cast(socket.socket, object())

    reply = server._handle({"op": "game-tree", "params": {}})
    assert reply is not None

    assert parse_result(reply["stdout"])["error"]["code"] == "live_scene_not_found"
    assert server._session is None


def test_failed_launch_threads_diagnostics_into_the_error_reply(tmp_path, monkeypatch):
    # #345: a None launch outcome now threads the child-liveness diagnostic
    # launch_session recorded into the engine_session_not_running reply's `stderr`
    # (which becomes GdaError.diagnostics via the live path), instead of the old
    # EMPTY diagnostics. The wire envelope shape {stdout, stderr, exit_code} is
    # unchanged — the detail rides the existing stderr field.
    (tmp_path / "B.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")

    def _fail_launch(*a, diagnostics=None, **k):
        if diagnostics is not None:
            diagnostics.append("the engine child aborted by signal SIGABRT (6) ...")
        return None

    monkeypatch.setattr("gda.daemon.server.launch_session", _fail_launch)
    server = DaemonServer(
        _project_with_marker(tmp_path), godot="godot", scene="res://B.tscn"
    )
    server._harness_listener = cast(socket.socket, object())

    reply = server._handle({"op": "game-tree", "params": {}})
    assert reply is not None

    # The wire shape is unchanged: still {stdout, stderr, exit_code}.
    assert set(reply) == {"stdout", "stderr", "exit_code"}
    assert parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    # The diagnostic rides the existing stderr field, not a new envelope key.
    assert "SIGABRT" in reply["stderr"]


def test_no_scene_selector_runs_main_scene_unchanged(tmp_path):
    # The selector-less default is unchanged: straight to the launch path (which here
    # is engine_session_not_running with no real binary), no scene verification.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    server = DaemonServer(daemon_paths(tmp_path), godot="")

    reply = server._handle({"op": "game-tree", "params": {}})
    assert reply is not None

    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )


def test_control_ops_report_liveness_and_request_stop(tmp_path):
    server = DaemonServer(daemon_paths(tmp_path), godot="")

    status = server._handle({"op": "__status__"})
    assert status is not None
    assert status["ok"] is True

    stop = server._handle({"op": "__stop__"})
    assert stop is not None
    assert stop["ok"] is True
    assert server._stopping is True


def test_status_op_reports_the_declared_display_mode(tmp_path):
    # `daemon status` reads the running daemon's launch-time display mode over
    # STATUS_OP (#251) — the daemon is the only authority for the mode it was
    # started with — so the control reply must carry `windowed`.
    headless = DaemonServer(daemon_paths(tmp_path), godot="")
    headless_status = headless._handle({"op": "__status__"})
    assert headless_status is not None
    assert headless_status["windowed"] is False

    windowed = DaemonServer(daemon_paths(tmp_path), godot="", windowed=True)
    windowed_status = windowed._handle({"op": "__status__"})
    assert windowed_status is not None
    assert windowed_status["windowed"] is True


def test_engine_session_request_times_out_as_live_timeout(monkeypatch):
    # A harness that never replies must surface the registered live_timeout, not
    # hang the daemon forever (ADR-0021).
    monkeypatch.setattr("gda.daemon.session.OP_TIMEOUT", 0.2)
    daemon_end, silent_harness = socket.socketpair()
    session = EngineSession(cast(subprocess.Popen, _FakeProc()), daemon_end)
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
