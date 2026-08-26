"""Daemon-side `diag` serving + the Session-log launch wiring (#224).

In-process, engine-free. ``diag`` is a daemon-served live op (ADR: runtime-
diagnostics-via-daemon-owned-session-log): the daemon launches the Engine session
with ``--log-file <session path>``, remembers that path, and serves ``diag-errors``
by reading the file directly — NOT by relaying to the harness, and even after the
session process has died (so a crash stays diagnosable). These tests exercise the
launch argv, the remembered path, and the daemon's ``_handle`` read path against a
temp log file. (The raw ``diag-log`` op is superseded by ``logger-tail`` — see
``test_daemon_logger.py``, #281.)
"""

import json
import os
import socket
import subprocess
import time
from typing import cast

import pytest

from gda.daemon.discovery import daemon_paths
from gda.daemon.protocol import write_frame
from gda.daemon.server import DaemonServer
from gda.daemon.session import EngineSession, SceneMismatch, launch_session
from gda.parser import parse_result
from tests.support import no_engine_teardown

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


class _FakeProc:
    """A stand-in subprocess.Popen: ``poll()`` returns ``returncode`` (None = alive)."""

    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        return self.returncode

    # gda's OWN pid, deliberately: teardown reads the pid to find the process
    # group it owns, and the own-group guard then resolves this stand-in to no
    # group at all. An invented pid would instead resolve to whichever real
    # process holds it — which a test would then signal.
    pid = os.getpid()


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


# --- Slice 1: launch carries --log-file and the session remembers the path ---


def test_launch_session_passes_log_file_arg_and_remembers_path(monkeypatch, tmp_path):
    project = _project(tmp_path)
    log_file = tmp_path / "session.log"
    captured = {}

    class _ImmediatePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            self.pid = 4242

        def poll(self):
            return None

    monkeypatch.setattr(subprocess, "Popen", _ImmediatePopen)
    # _terminate kills the (fake) proc on the accept-timeout path; no-op it.
    no_engine_teardown(monkeypatch)

    class _NoAcceptListener:
        """A harness listener whose accept() times out at once: launch returns
        None, but the argv was already captured at Popen time (what we assert)."""

        def settimeout(self, _):
            pass

        def accept(self):
            raise TimeoutError

    launch_session(
        project,
        "godot",
        cast(socket.socket, _NoAcceptListener()),
        tmp_path / "h.sock",
        "tok",
        log_file=log_file,
        deadline=time.monotonic() + 0.1,
    )

    argv = captured["argv"]
    assert "--log-file" in argv
    assert str(log_file) in argv
    # --log-file precedes the `--` payload separator (it is an engine flag).
    assert argv.index("--log-file") < argv.index("--")


def test_engine_session_exposes_its_log_file_path(tmp_path):
    log_file = tmp_path / "s.log"
    session = EngineSession(
        cast(subprocess.Popen, _FakeProc()), conn=None, log_file=log_file
    )
    assert session.log_file == log_file


# --- #278: launch carries `--scene <path|UID>` BEFORE `--path`, omitted by default ---


def _capture_launch_argv(monkeypatch, project, **launch_kw):
    """Drive ``launch_session`` engine-free and return the argv it built."""
    captured = {}

    class _ImmediatePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            self.pid = 4242

        def poll(self):
            return None

    monkeypatch.setattr(subprocess, "Popen", _ImmediatePopen)
    no_engine_teardown(monkeypatch)

    class _NoAcceptListener:
        def settimeout(self, _):
            pass

        def accept(self):
            raise TimeoutError

    launch_session(
        project,
        "godot",
        cast(socket.socket, _NoAcceptListener()),
        project / "h.sock",
        "tok",
        deadline=time.monotonic() + 0.1,
        **launch_kw,
    )
    return captured["argv"]


def test_launch_session_inserts_scene_before_path_when_set(monkeypatch, tmp_path):
    project = _project(tmp_path)
    argv = _capture_launch_argv(monkeypatch, project, scene="res://B.tscn")

    # `--scene <path>` is an ENGINE option: present, paired, and BEFORE `--path`
    # (and so before the `--` payload separator too).
    assert "--scene" in argv
    assert argv[argv.index("--scene") + 1] == "res://B.tscn"
    assert argv.index("--scene") < argv.index("--path")
    assert argv.index("--scene") < argv.index("--")
    # The selector ALSO threads into the harness arg tail (after the launch
    # marker, socket, token; the session-identity slot follows it, #660) so the
    # harness can verify the loaded scene.
    assert argv[-2] == "res://B.tscn"
    # The trailing selector slot sits after the `--` payload separator.
    assert len(argv) - 2 > argv.index("--")


def test_launch_session_accepts_a_uid_scene_selector(monkeypatch, tmp_path):
    # Godot's `--scene` accepts a `uid://…` value too; the launch passes it through
    # verbatim in the same engine-option slot AND in the harness tail.
    project = _project(tmp_path)
    argv = _capture_launch_argv(monkeypatch, project, scene="uid://abc123")

    assert argv[argv.index("--scene") + 1] == "uid://abc123"
    assert argv.index("--scene") < argv.index("--path")
    assert argv[-2] == "uid://abc123"


def test_launch_session_omits_scene_by_default(monkeypatch, tmp_path):
    # No selector: behaviour unchanged — the engine runs the project's main_scene,
    # so no `--scene` engine option appears in the argv. The harness tail still
    # carries a slot for the selector — an EMPTY string (no selector requested).
    project = _project(tmp_path)
    argv = _capture_launch_argv(monkeypatch, project)

    assert "--scene" not in argv
    # The trailing harness-tail slots are empty strings: no selector requested,
    # and no session identity on a direct (non-daemon) launch (#660).
    assert argv[-2] == "" and argv[-1] == ""


# --- #278 (review): launch-time scene verification handshake ------------------
# After the auth token, the harness sends a SECOND frame: the scene-verification
# result {"scene_ok": bool, "current": "res://…"}. launch_session reads it and
# returns a verified session, raises SceneMismatch, or returns None (generic fail).


class _OneShotListener:
    """A harness listener whose accept() hands back a pre-connected socket once."""

    def __init__(self, conn):
        self._conn = conn

    def settimeout(self, _):
        pass

    def accept(self):
        if self._conn is None:
            raise TimeoutError
        conn, self._conn = self._conn, None
        return conn, None


def _launch_with_fake_harness(monkeypatch, tmp_path, *, token, verify, scene):
    """Drive launch_session against a socketpair playing the harness side.

    The "harness" end presents ``token`` then sends the ``verify`` dict as the
    second frame. Returns the launch_session outcome (or the raised exception class
    via pytest.raises in the caller).
    """
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: _FakeProc())
    no_engine_teardown(monkeypatch)
    daemon_end, harness_end = socket.socketpair()
    # The harness presents its token, then the scene-verification frame.
    write_frame(
        harness_end,
        token.to_utf8_buffer()
        if hasattr(token, "to_utf8_buffer")
        else token.encode("utf-8"),
    )
    if verify is not None:
        write_frame(harness_end, json.dumps(verify).encode("utf-8"))
    try:
        return launch_session(
            tmp_path,
            "godot",
            cast(socket.socket, _OneShotListener(daemon_end)),
            tmp_path / "h.sock",
            token,
            deadline=time.monotonic() + 1.0,
            scene=scene,
        )
    finally:
        harness_end.close()


def test_launch_returns_verified_session_when_scene_ok(monkeypatch, tmp_path):
    _project(tmp_path)
    session = _launch_with_fake_harness(
        monkeypatch,
        tmp_path,
        token="tok",
        verify={"scene_ok": True, "current": "res://B.tscn"},
        scene="res://B.tscn",
    )
    assert isinstance(session, EngineSession)


def test_launch_raises_scene_mismatch_when_loaded_scene_differs(monkeypatch, tmp_path):
    _project(tmp_path)
    with pytest.raises(SceneMismatch):
        _launch_with_fake_harness(
            monkeypatch,
            tmp_path,
            token="tok",
            verify={"scene_ok": False, "current": "res://main.tscn"},
            scene="res://B.tscn",
        )


def test_launch_with_no_selector_does_not_require_a_verification_frame(
    monkeypatch, tmp_path
):
    # No selector: scene_ok is trivially true (the harness sends it as ok), and the
    # session is verified — the main_scene default is unchanged.
    _project(tmp_path)
    session = _launch_with_fake_harness(
        monkeypatch,
        tmp_path,
        token="tok",
        verify={"scene_ok": True, "current": "res://main.tscn"},
        scene=None,
    )
    assert isinstance(session, EngineSession)


def test_launch_returns_none_on_bad_token(monkeypatch, tmp_path):
    _project(tmp_path)
    # A wrong token aborts the handshake BEFORE the verification frame: a generic
    # launch failure (None), distinct from a scene mismatch.
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: _FakeProc())
    no_engine_teardown(monkeypatch)
    daemon_end, harness_end = socket.socketpair()
    write_frame(harness_end, b"WRONG")
    try:
        outcome = launch_session(
            tmp_path,
            "godot",
            cast(socket.socket, _OneShotListener(daemon_end)),
            tmp_path / "h.sock",
            "tok",
            deadline=time.monotonic() + 1.0,
            scene="res://B.tscn",
        )
    finally:
        harness_end.close()
    assert outcome is None


# --- #345: a failed launch records a best-effort diagnostic in the sink ---------
# The child is spawned with stderr=DEVNULL, so launch_session polls the child at the
# failure boundary: a child that already died names its signal (a windowed-no-display
# abort is SIGABRT); a child still alive is the harness-never-connected case.


class _NoAcceptListener:
    """A harness listener whose accept() times out at once (no harness connects)."""

    def settimeout(self, _):
        pass

    def accept(self):
        raise TimeoutError


def test_failed_launch_records_signal_death_when_child_already_died(
    monkeypatch, tmp_path
):
    project = _project(tmp_path)
    # A child that reports it aborted by SIGABRT (returncode -6) — what a windowed
    # session with no usable DisplayServer does before the harness can connect.
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: _FakeProc(-6))
    no_engine_teardown(monkeypatch)

    diagnostics: list[str] = []
    outcome = launch_session(
        project,
        "godot",
        cast(socket.socket, _NoAcceptListener()),
        tmp_path / "h.sock",
        "tok",
        deadline=time.monotonic() + 0.1,
        diagnostics=diagnostics,
    )

    assert outcome is None
    assert diagnostics, "a failed launch must record a diagnostic"
    assert "SIGABRT" in diagnostics[0]
    assert "(6)" in diagnostics[0]


def test_failed_launch_records_harness_hung_when_child_still_alive(
    monkeypatch, tmp_path
):
    project = _project(tmp_path)
    # A child still alive (poll() is None) when the harness never connected: the
    # "engine up, harness hung" case, distinct from a crashed child.
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: _FakeProc(None))
    no_engine_teardown(monkeypatch)

    diagnostics: list[str] = []
    outcome = launch_session(
        project,
        "godot",
        cast(socket.socket, _NoAcceptListener()),
        tmp_path / "h.sock",
        "tok",
        deadline=time.monotonic() + 0.1,
        diagnostics=diagnostics,
    )

    assert outcome is None
    assert diagnostics
    assert "harness did not connect" in diagnostics[0]


def test_failed_launch_diagnostics_excludes_stale_session_log(
    monkeypatch, tmp_path, daemon_runtime_dir
):
    # #345 finding 2: a PRE-LOGGER abort (a windowed-no-DisplayServer crash, and
    # others) dies before Godot installs its --log-file logger, so nothing truncates
    # the deterministic session-log path. If a PREVIOUS session left content there, it
    # must NOT leak into the current failure's diagnostics. launch_session truncates
    # the log BEFORE spawning, so the tail reads EMPTY for a pre-logger abort.
    server = DaemonServer(daemon_paths(_project(tmp_path)), godot="godot")
    log_path = server.paths.session_log
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("STALE-PREVIOUS-SESSION-OUTPUT", encoding="utf-8")

    # A REAL launch_session runs (truncating the log), spawns a fake child that dies
    # pre-logger by SIGABRT and writes nothing, and no harness connects -> None.
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: _FakeProc(-6))
    no_engine_teardown(monkeypatch)
    server._harness_listener = cast(socket.socket, _NoAcceptListener())

    reply = server._handle({"op": "game-tree", "params": {}})
    assert reply is not None
    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )
    # The child-signal reason is present; the STALE log content is gone (truncated).
    assert "SIGABRT" in reply["stderr"]
    assert "STALE-PREVIOUS-SESSION-OUTPUT" not in reply["stderr"]
    # The file on disk was truncated by the launch attempt, honoring "truncated each
    # launch" even for a pre-logger abort (ADR-0022 / CONTEXT.md Session log).
    assert log_path.read_bytes() == b""


# --- Slice 2: the daemon serves diag from the remembered log file ---


def _server_with_session(tmp_path, log_file, alive=True):
    server = DaemonServer(daemon_paths(_project(tmp_path)), godot="godot")
    server._session = EngineSession(
        cast(subprocess.Popen, _FakeProc(None if alive else 0)),
        conn=None,
        log_file=log_file,
    )
    return server


def test_diag_errors_reads_structured_errors_from_the_log(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text(
        "print output\nERROR: boom\n   at: _ready (res://main.gd:9)\n", encoding="utf-8"
    )
    server = _server_with_session(tmp_path, log_file)

    reply = server._handle({"op": "diag-errors", "params": {}})
    assert reply is not None
    payload = parse_result(reply["stdout"])

    assert payload["errors"][0]["level"] == "error"
    assert payload["errors"][0]["message"] == "boom"
    assert payload["errors"][0]["file"] == "res://main.gd"
    assert payload["errors"][0]["line"] == 9


def test_diag_errors_limit_tails_the_most_recent_n(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text(
        "ERROR: one\n   at: a (res://a.gd:1)\nERROR: two\n   at: b (res://b.gd:2)\n",
        encoding="utf-8",
    )
    server = _server_with_session(tmp_path, log_file)

    reply = server._handle({"op": "diag-errors", "params": {"limit": 1}})
    assert reply is not None
    payload = parse_result(reply["stdout"])

    assert len(payload["errors"]) == 1
    assert payload["errors"][0]["message"] == "two"


def test_diag_serves_even_when_the_session_process_has_died(tmp_path):
    # A crash is diagnosable: the daemon serves diag from the remembered log file
    # even after the session process has exited (ADR rationale).
    log_file = tmp_path / "session.log"
    log_file.write_text(
        "ERROR: crashed\n   at: _ready (res://main.gd:3)\n", encoding="utf-8"
    )
    server = _server_with_session(tmp_path, log_file, alive=False)

    reply = server._handle({"op": "diag-errors", "params": {}})
    assert reply is not None
    payload = parse_result(reply["stdout"])

    assert payload["errors"][0]["message"] == "crashed"


def test_diag_empty_log_is_an_empty_result_not_an_error(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text("", encoding="utf-8")
    server = _server_with_session(tmp_path, log_file)

    errors_reply = server._handle({"op": "diag-errors", "params": {}})
    assert errors_reply is not None

    assert parse_result(errors_reply["stdout"])["errors"] == []


def test_diag_with_no_session_launched_is_engine_session_not_running(
    monkeypatch, tmp_path
):
    # ADR-0022: diag observes an already-launched session; it does NOT launch one.
    # With NO session launched this daemon lifetime, diag-errors returns a
    # structured `engine_session_not_running` (exit 6) — and crucially it must NOT
    # spawn an engine session as a side effect, even with a Godot binary set (that
    # hidden project-code-execution side effect is the bug under ADR-0009).
    op = "diag-errors"
    server = DaemonServer(daemon_paths(_project(tmp_path)), godot="godot")

    # Trip-wire: if diag tries to launch a session, fail loudly.
    def _boom(*args, **kwargs):
        raise AssertionError("diag must not launch an engine session")

    monkeypatch.setattr("gda.daemon.server.launch_session", _boom)

    reply = server._handle({"op": op, "params": {}})
    assert reply is not None

    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )
    # No session was created as a side effect of the read-only diag.
    assert server._session is None


def test_diag_with_a_remembered_session_but_missing_file_is_live_log_unavailable(
    tmp_path,
):
    # A session was launched (remembered) but its log file is gone/unreadable.
    log_file = tmp_path / "missing.log"  # never created
    server = _server_with_session(tmp_path, log_file, alive=False)

    reply = server._handle({"op": "diag-errors", "params": {}})
    assert reply is not None

    assert parse_result(reply["stdout"])["error"]["code"] == "live_log_unavailable"
