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
from gda.daemon.protocol import read_message, write_frame
from gda.daemon.server import DaemonServer
from gda.daemon.session import EngineSession
from gda.display import WindowedUnavailable
from gda.models import EnvironmentProbe
from gda.commands.daemon import (
    run_daemon_status_operation,
    run_daemon_stop_operation,
)
from gda.errors import Failure
from gda.parser import build_result, parse_result

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


class _FakeProc:
    def poll(self):
        return None


def _unavailable(
    code: str = "live_windowed_unavailable",
    name: str = "CGSessionCopyCurrentDictionary",
) -> WindowedUnavailable:
    """A fake host-probe verdict, so the relay is covered on any host (#345, #667)."""
    return WindowedUnavailable(
        code=code,
        reason=f"no usable DisplayServer (test: {code})",
        probe=EnvironmentProbe(name=name, platform="darwin"),
    )


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
    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )
    # The diagnostic rides the existing stderr field, not a new envelope key.
    assert "SIGABRT" in reply["stderr"]


def test_windowed_no_display_is_live_windowed_unavailable_without_launching(
    tmp_path, monkeypatch
):
    # #345 finding 1: the AUTHORITATIVE no-display guard lives at the session-launch
    # boundary (_ensure_session), not only the optional `daemon start` fail-fast. A
    # windowed daemon on a host with no usable DisplayServer refuses a live op with the
    # typed live_windowed_unavailable AND never calls launch_session — so a doomed
    # windowed Godot is never spawned, even if `daemon start --windowed` slipped through.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    def _must_not_launch(*a, **k):
        raise AssertionError("launch_session must not be called with no usable display")

    monkeypatch.setattr("gda.daemon.server.launch_session", _must_not_launch)
    server = DaemonServer(
        daemon_paths(tmp_path),
        godot="godot",
        windowed=True,
        display_check=lambda: _unavailable(),
    )
    server._harness_listener = cast(socket.socket, object())

    reply = server._handle({"op": "game-tree", "params": {}})
    assert reply is not None

    error = parse_result(reply["stdout"])["error"]
    assert error["code"] == "live_windowed_unavailable"
    # The probe's reason rides the advisory diagnostics (existing stderr) field.
    assert "no usable DisplayServer (test" in reply["stderr"]
    assert server._session is None  # nothing launched or cached


def test_windowed_denied_relays_the_permission_code_not_the_capability_one(
    tmp_path, monkeypatch
):
    # #667: the launch-boundary guard relays the code the PROBE decided, so a sandbox
    # denial reaching the daemon path is reported as live_windowed_permission_denied
    # rather than collapsing into live_windowed_unavailable. This is the
    # AUTHORITATIVE refusal (it fires on the lazy launch every live op goes through),
    # so it also carries the machine-readable `probe` — deliberately widening the live
    # wire envelope with that ONE optional key (#667 review), rather than reporting
    # less here than the optional CLI fail-fast reports.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    def _must_not_launch(*a, **k):
        raise AssertionError("launch_session must not be called with no usable display")

    monkeypatch.setattr("gda.daemon.server.launch_session", _must_not_launch)
    server = DaemonServer(
        daemon_paths(tmp_path),
        godot="godot",
        windowed=True,
        display_check=lambda: _unavailable(code="live_windowed_permission_denied"),
    )
    server._harness_listener = cast(socket.socket, object())

    reply = server._handle({"op": "game-tree", "params": {}})
    assert reply is not None

    error = parse_result(reply["stdout"])["error"]
    assert error["code"] == "live_windowed_permission_denied"
    # The one deliberate wire widening: `probe` rides the live envelope as data.
    assert set(error) == {"code", "message", "probe"}
    assert error["probe"] == {
        "name": "CGSessionCopyCurrentDictionary",
        "platform": "darwin",
    }
    assert "live_windowed_permission_denied" in reply["stderr"]
    assert server._session is None


def test_a_relayed_refusal_without_a_probe_keeps_the_narrow_wire_shape(
    tmp_path, monkeypatch
):
    # The widening is OPTIONAL: every live reply that has no probe — which is all of
    # them except the windowed refusals — is byte-identical to before, so the key can
    # never appear as a null for the harness-emitted and daemon-synthesized codes.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    monkeypatch.setattr("gda.daemon.server.launch_session", lambda *a, **k: None)
    server = DaemonServer(daemon_paths(tmp_path), godot="godot")
    server._harness_listener = cast(socket.socket, object())

    reply = server._handle({"op": "game-tree", "params": {}})
    assert reply is not None

    error = parse_result(reply["stdout"])["error"]
    assert error["code"] == "engine_session_not_running"
    assert set(error) == {"code", "message"}


def test_windowed_with_a_usable_display_reaches_launch(tmp_path, monkeypatch):
    # The guard is display-gated: a usable display (the check returns None) does NOT
    # short-circuit — the launch proceeds (here to the generic engine_session_not_running
    # via a patched None launch), proving the guard fires ONLY on no-display.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    calls = {"n": 0}

    def _launch(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr("gda.daemon.server.launch_session", _launch)
    server = DaemonServer(
        daemon_paths(tmp_path),
        godot="godot",
        windowed=True,
        display_check=lambda: None,  # a usable display
    )
    server._harness_listener = cast(socket.socket, object())

    reply = server._handle({"op": "game-tree", "params": {}})
    assert reply is not None
    assert calls["n"] == 1  # the launch boundary was reached
    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )


def test_headless_windowed_false_never_consults_the_display_check(
    tmp_path, monkeypatch
):
    # A default (headless) daemon must never consult the display check — a headless
    # session needs no window server; only a windowed session is gated.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    def _boom() -> WindowedUnavailable | None:
        raise AssertionError("a headless daemon must not run the display check")

    monkeypatch.setattr("gda.daemon.server.launch_session", lambda *a, **k: None)
    server = DaemonServer(
        daemon_paths(tmp_path), godot="godot", windowed=False, display_check=_boom
    )
    server._harness_listener = cast(socket.socket, object())

    reply = server._handle({"op": "game-tree", "params": {}})
    assert reply is not None
    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )


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


def test_a_timed_out_relay_leaves_the_session_dead_to_the_daemon(monkeypatch):
    # #725 re-review finding 1: this protocol carries no request id and a
    # timed-out frame is never drained, so a LATE reply is indistinguishable
    # from the next op's reply. Reproduced before the fix: op A times out, the
    # harness answers late, op B returns A's payload as its own. A channel that
    # can answer with another operation's result is not serving — the timeout
    # must latch it stale (with the engine PROCESS still alive throughout) so
    # the next session-needing op rebuilds it through the launch boundary.
    monkeypatch.setattr("gda.daemon.session.OP_TIMEOUT", 0.2)
    daemon_end, harness = socket.socketpair()
    proc = _FakeProc()
    session = EngineSession(cast(subprocess.Popen, proc), daemon_end)
    try:
        first = session.request("game-tree", {})
        assert parse_result(first["stdout"])["error"]["code"] == "live_timeout"
        assert read_message(harness) == {"op": "game-tree", "params": {}}
        write_frame(harness, build_result({"answer": "late"}).encode("utf-8"))
        assert proc.poll() is None  # the engine itself never died
        assert session.alive() is False
    finally:
        daemon_end.close()
        harness.close()


def test_daemon_status_on_non_unix_is_live_unsupported_platform(monkeypatch, tmp_path):
    monkeypatch.setattr("gda.commands.daemon._is_unix", lambda: False)
    outcome = run_daemon_status_operation(tmp_path)
    assert isinstance(outcome, Failure)
    assert outcome.error.code == "live_unsupported_platform"


def test_daemon_stop_on_non_unix_is_live_unsupported_platform(monkeypatch, tmp_path):
    monkeypatch.setattr("gda.commands.daemon._is_unix", lambda: False)
    outcome = run_daemon_stop_operation(tmp_path)
    assert isinstance(outcome, Failure)
    assert outcome.error.code == "live_unsupported_platform"
