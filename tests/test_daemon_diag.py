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

import os
import subprocess

import pytest

from gda.daemon.discovery import daemon_paths
from gda.daemon.server import DaemonServer
from gda.daemon.session import EngineSession, launch_session
from gda.parser import parse_result

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


class _FakeProc:
    """A stand-in subprocess.Popen: ``poll()`` returns ``returncode`` (None = alive)."""

    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        return self.returncode


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
    monkeypatch.setattr("gda.daemon.session._terminate", lambda proc: None)

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
        _NoAcceptListener(),
        tmp_path / "h.sock",
        "tok",
        log_file=log_file,
        timeout=0.1,
    )

    argv = captured["argv"]
    assert "--log-file" in argv
    assert str(log_file) in argv
    # --log-file precedes the `--` payload separator (it is an engine flag).
    assert argv.index("--log-file") < argv.index("--")


def test_engine_session_exposes_its_log_file_path(tmp_path):
    log_file = tmp_path / "s.log"
    session = EngineSession(_FakeProc(), conn=None, log_file=log_file)
    assert session.log_file == log_file


# --- Slice 2: the daemon serves diag from the remembered log file ---


def _server_with_session(tmp_path, log_file, alive=True):
    server = DaemonServer(daemon_paths(_project(tmp_path)), godot="godot")
    server._session = EngineSession(_FakeProc(None if alive else 0), conn=None, log_file=log_file)
    return server


def test_diag_errors_reads_structured_errors_from_the_log(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text(
        "print output\nERROR: boom\n   at: _ready (res://main.gd:9)\n", encoding="utf-8"
    )
    server = _server_with_session(tmp_path, log_file)

    reply = server._handle({"op": "diag-errors", "params": {}})
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
    payload = parse_result(reply["stdout"])

    assert len(payload["errors"]) == 1
    assert payload["errors"][0]["message"] == "two"


def test_diag_serves_even_when_the_session_process_has_died(tmp_path):
    # A crash is diagnosable: the daemon serves diag from the remembered log file
    # even after the session process has exited (ADR rationale).
    log_file = tmp_path / "session.log"
    log_file.write_text("ERROR: crashed\n   at: _ready (res://main.gd:3)\n", encoding="utf-8")
    server = _server_with_session(tmp_path, log_file, alive=False)

    reply = server._handle({"op": "diag-errors", "params": {}})
    payload = parse_result(reply["stdout"])

    assert payload["errors"][0]["message"] == "crashed"


def test_diag_empty_log_is_an_empty_result_not_an_error(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text("", encoding="utf-8")
    server = _server_with_session(tmp_path, log_file)

    errors_reply = server._handle({"op": "diag-errors", "params": {}})

    assert parse_result(errors_reply["stdout"])["errors"] == []


def test_diag_with_no_session_launched_is_engine_session_not_running(monkeypatch, tmp_path):
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

    assert parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    # No session was created as a side effect of the read-only diag.
    assert server._session is None


def test_diag_with_a_remembered_session_but_missing_file_is_live_log_unavailable(tmp_path):
    # A session was launched (remembered) but its log file is gone/unreadable.
    log_file = tmp_path / "missing.log"  # never created
    server = _server_with_session(tmp_path, log_file, alive=False)

    reply = server._handle({"op": "diag-errors", "params": {}})

    assert parse_result(reply["stdout"])["error"]["code"] == "live_log_unavailable"
