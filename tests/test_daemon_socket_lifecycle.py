"""Socket-lifecycle tests for the gda-daemon server (#674).

These drive the REAL serve loop — real UDS bind, accept, reply, cleanup —
against a fake engine session injected through the ``SessionLaunch`` seam, so
the daemon's whole socket lifecycle (bind, stale-slot reclaim, double-start,
stop/signal cleanup) and its session lifecycle (lazy launch, launch failure,
death mid-request, relaunch) are covered by the fast suite with no Godot binary
and no real engine.

Real binds need the short-runtime-dir fixture: a UDS path is bounded by the OS
``sun_path`` limit, which pytest's long macOS ``tmp_path`` overflows.

``serve()`` installs signal handlers, which only works on the main thread — the
helpers below run it on a worker thread, so they record the registration
instead (the SIGTERM test invokes the recorded handler directly, which is
exactly what the signal delivery would run).
"""

import os
import signal
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest

from gda.commands.daemon import run_daemon_start_operation
from gda.daemon.discovery import daemon_paths
from gda.daemon.protocol import read_message, write_message
from gda.daemon.server import DaemonServer
from gda.daemon.session import EngineSession
from gda.errors import Failure
from gda.parser import parse_result

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


def _project(tmp_path: Path) -> Path:
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


class _Proc:
    """A stand-in engine process whose liveness the test flips."""

    def __init__(self, code: "int | None" = None) -> None:
        self.code = code

    def poll(self):
        return self.code


class _ServedSession:
    """A fake session that serves every relayed op."""

    log_file = None

    def __init__(self) -> None:
        self.closed = False

    def alive(self) -> bool:
        return True

    def request(self, operation: str, params: dict) -> dict:
        return {"stdout": f"served:{operation}", "stderr": "", "exit_code": 0}

    def close(self) -> None:
        self.closed = True


def _request(paths, payload: dict, timeout: float = 5.0):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(paths.cli_socket))
        write_message(sock, payload)
        return read_message(sock)


def _await_ready(paths, deadline: float = 5.0) -> dict:
    """Poll until the daemon answers ``__status__`` on its CLI socket."""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if paths.cli_socket.exists():
            try:
                reply = _request(paths, {"op": "__status__"})
                if isinstance(reply, dict):
                    return reply
            except OSError:
                pass
        time.sleep(0.02)
    raise AssertionError("the daemon socket never became ready")


@contextmanager
def _serving(server: DaemonServer, paths, monkeypatch):
    # serve() on a worker thread: signal.signal only works on the main thread, so
    # record the handler registrations instead of installing them.
    registered: list = []
    monkeypatch.setattr(signal, "signal", lambda sig, handler: registered.append(sig))
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    try:
        _await_ready(paths)
        yield thread
    finally:
        if thread.is_alive():
            try:
                _request(paths, {"op": "__stop__"})
            except OSError:
                server._on_signal(signal.SIGTERM, None)
            thread.join(timeout=5)


def _no_launch(*args, **kwargs):
    raise AssertionError("this test must not launch a session")


def test_serve_binds_both_sockets_and_answers_status(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_no_launch)

    with _serving(server, paths, monkeypatch):
        assert paths.cli_socket.exists()
        assert paths.harness_socket.exists()
        reply = _request(paths, {"op": "__status__"})
        assert reply == {"ok": True, "pid": os.getpid(), "windowed": False}


def test_a_stale_slot_left_by_a_crash_is_reclaimed(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # A crashed predecessor leaves socket files bound-then-abandoned and a pidfile
    # whose advisory lock nobody holds. A fresh serve() must reclaim the slot.
    paths = daemon_paths(_project(tmp_path))
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    for stale in (paths.cli_socket, paths.harness_socket):
        abandoned = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        abandoned.bind(str(stale))
        abandoned.close()  # the file stays on disk; nothing listens
    paths.pidfile.write_text("999999\n/nowhere\n", encoding="utf-8")

    server = DaemonServer(paths, godot="godot", launch=_no_launch)
    with _serving(server, paths, monkeypatch):
        reply = _request(paths, {"op": "__status__"})
        assert reply is not None and reply["ok"] is True


def test_a_double_start_loses_without_touching_the_live_daemons_sockets(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # Two starts race; the pidfile's advisory lock decides. The LOSER must fail
    # before it can unlink — or leave its cleanup to unlink — the winner's live
    # socket files: a losing start that destroys the winner's sockets turns one
    # daemon into zero (the winner keeps serving its open fd, but every new
    # client connect hits an unlinked path and reads "not running").
    paths = daemon_paths(_project(tmp_path))
    winner = DaemonServer(paths, godot="godot", launch=_no_launch)

    with _serving(winner, paths, monkeypatch):
        loser = DaemonServer(paths, godot="godot", launch=_no_launch)
        with pytest.raises(OSError):
            loser.serve()

        # The winner's slot is intact and still serves new connections.
        assert paths.cli_socket.exists()
        assert paths.harness_socket.exists()
        reply = _request(paths, {"op": "__status__"})
        assert reply is not None and reply["ok"] is True


def test_stop_op_unlinks_the_sockets_and_pidfile(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_no_launch)

    with _serving(server, paths, monkeypatch) as thread:
        reply = _request(paths, {"op": "__stop__"})
        assert reply is not None and reply["ok"] is True
        thread.join(timeout=5)

    assert not paths.cli_socket.exists()
    assert not paths.harness_socket.exists()
    assert not paths.pidfile.exists()


def test_a_termination_signal_cleans_up_the_slot(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # The handler serve() registers for SIGTERM/SIGINT: closing the listener
    # unblocks the pending accept, the loop exits, cleanup unlinks the slot.
    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_no_launch)

    with _serving(server, paths, monkeypatch) as thread:
        server._on_signal(signal.SIGTERM, None)
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert not paths.cli_socket.exists()
    assert not paths.harness_socket.exists()
    assert not paths.pidfile.exists()


def test_an_overlong_socket_path_is_refused_at_start(tmp_path, monkeypatch):
    # The UDS length refusal (ADR-0021): a runtime dir that pushes the derived
    # socket path over sun_path is refused with a clear typed failure BEFORE any
    # spawn, instead of the daemon's bind() failing and start timing out vaguely.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / ("x" * 150)))

    outcome = run_daemon_start_operation(_project(tmp_path), "godot")

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "daemon_not_running"
    assert "socket path longer" in outcome.error.message


def test_the_first_live_op_launches_the_session_lazily_and_reuses_it(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # The whole lazy-launch lifecycle through the REAL loop (ADR-0017): no session
    # at bind time; the first live op launches one via the seam; the second op
    # reuses it without relaunching.
    calls = {"n": 0}
    session = _ServedSession()

    def _launch(*args, **kwargs):
        calls["n"] += 1
        return cast(EngineSession, session)

    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    with _serving(server, paths, monkeypatch):
        assert calls["n"] == 0  # binding alone launches nothing
        first = _request(paths, {"op": "game-tree", "params": {}})
        second = _request(paths, {"op": "perf-monitors", "params": {}})

    assert first is not None and first["stdout"] == "served:game-tree"
    assert second is not None and second["stdout"] == "served:perf-monitors"
    assert calls["n"] == 1


def test_a_failed_launch_is_the_typed_engine_session_not_running(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    def _launch(*args, **kwargs):
        return None

    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    with _serving(server, paths, monkeypatch):
        reply = _request(paths, {"op": "game-tree", "params": {}})

    assert reply is not None
    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )


def test_a_session_dying_mid_request_reports_disconnect_then_relaunches(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # Death mid-request, end to end: the session passes the liveness check, its
    # connection breaks during the relay (the real EngineSession.request maps
    # that to engine_disconnected), the engine process then dies, and the NEXT
    # live op relaunches through the seam and serves.
    ours, theirs = socket.socketpair()
    theirs.close()  # the harness end is gone: the relay write breaks mid-request
    proc = _Proc(code=None)  # alive at the pre-request liveness check
    dying = EngineSession(cast(subprocess.Popen, proc), conn=ours)

    launches: list = []

    def _launch(*args, **kwargs):
        launches.append(kwargs.get("log_file"))
        if len(launches) == 1:
            return dying
        return cast(EngineSession, _ServedSession())

    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    with _serving(server, paths, monkeypatch):
        first = _request(paths, {"op": "game-tree", "params": {}})
        proc.code = 1  # the engine process is now observed dead
        second = _request(paths, {"op": "game-tree", "params": {}})

    assert first is not None
    assert parse_result(first["stdout"])["error"]["code"] == "engine_disconnected"
    assert second is not None and second["stdout"] == "served:game-tree"
    assert len(launches) == 2
    # Every launch was asked to log to the one DaemonPaths-derived path (#674).
    assert launches == [paths.session_log, paths.session_log]
