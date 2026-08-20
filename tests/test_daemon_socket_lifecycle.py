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
from gda.daemon.discovery import (
    _pidfile_lock_held,
    daemon_paths,
    daemon_pid,
    read_pidfile,
)
from gda.daemon.protocol import read_message, write_message
from gda.daemon.server import DAEMON_SERVED_OPS, DaemonServer
from gda.daemon.session import EngineSession, launch_session
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
    """A fake session that serves every relayed op — a structural SessionHandle."""

    log_file: "Path | None" = None

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


def test_a_double_start_loses_without_touching_the_live_daemons_slot(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # Two starts race; the pidfile's advisory lock decides. The LOSER must fail
    # without disturbing ANY part of the winner's slot (ADR-0021): not its
    # socket files (a losing start that unlinks them turns one daemon into zero
    # reachable ones), and not its pidfile CONTENT either — a pre-lock
    # truncation erases the winner's recorded identity, so status, attach, and
    # stop all read the live daemon as not running (#723 review).
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
        # And its DISCOVERY identity survives: the recorded pid + project are
        # untouched, so the liveness contract still reports the winner.
        assert read_pidfile(paths) == (os.getpid(), paths.project)
        assert daemon_pid(paths) == os.getpid()


def test_cleanup_removes_the_slot_before_releasing_the_lock(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # The reverse half of the slot's critical section (#723 review): the lock is
    # the slot's mutual exclusion (ADR-0021), so it must outlive the slot it
    # guards. Released before the unlinks, a successor can acquire and bind a
    # fresh slot inside the cleanup window — which the predecessor's remaining
    # unlinks then destroy. Instrumenting unlink pins the order: every slot
    # path must be removed while the lock is still held.
    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_no_launch)
    slot = {paths.cli_socket, paths.harness_socket, paths.pidfile}
    held_at_unlink: dict = {}
    real_unlink = os.unlink

    def _recording_unlink(path, *args, **kwargs):
        target = Path(path)
        if target in slot:
            held_at_unlink[target.name] = _pidfile_lock_held(paths.pidfile)
        return real_unlink(path, *args, **kwargs)

    with _serving(server, paths, monkeypatch) as thread:
        monkeypatch.setattr(os, "unlink", _recording_unlink)
        _request(paths, {"op": "__stop__"})
        thread.join(timeout=5)

    assert len(held_at_unlink) == 3
    assert all(held_at_unlink.values()), held_at_unlink

    # The handoff itself: a successor started after the stop owns a fresh slot
    # and is the one the discovery contract reports.
    successor = DaemonServer(paths, godot="godot", launch=_no_launch)
    with _serving(successor, paths, monkeypatch):
        assert daemon_pid(paths) == os.getpid()
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


def test_a_termination_signal_cleans_up_the_slot(tmp_path, daemon_runtime_dir):
    # The REAL production signal path, in a forked child where serve() runs on
    # the main thread exactly as the daemon does: SIGTERM interrupts the blocked
    # accept (EINTR), the registered handler closes the listener and sets the
    # stop flag, the loop exits, cleanup unlinks the slot. A worker-thread
    # re-enactment is deliberately NOT used here — on Linux, closing a listener
    # from another thread does not wake a blocked accept, which is a fact about
    # threads, not about the signal path under test.
    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_no_launch)

    child = os.fork()
    if child == 0:  # the daemon: serve until signalled, then leave pytest silently
        try:
            server.serve()
        finally:
            os._exit(0)

    try:
        _await_ready(paths)
        os.kill(child, signal.SIGTERM)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            done, _ = os.waitpid(child, os.WNOHANG)
            if done == child:
                break
            time.sleep(0.02)
        else:
            os.kill(child, signal.SIGKILL)
            os.waitpid(child, 0)
            raise AssertionError("the daemon did not exit on SIGTERM")
    except BaseException:
        # Never leak the forked daemon into the rest of the suite.
        try:
            os.kill(child, signal.SIGKILL)
            os.waitpid(child, 0)
        except (OSError, ChildProcessError):
            pass
        raise

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
        return session

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
        return _ServedSession()

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


def test_wait_ready_launches_once_and_reports_the_bounded_wait(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #657 over the real socket: the wait-ready op IS the first live op — it
    # launches through the seam with the caller's bound as the harness-connect
    # timeout and reports launched=true; a repeat while the session is alive is
    # idempotent (launched=false, no relaunch).
    launches: list = []
    session = _ServedSession()

    def _launch(*args, **kwargs):
        launches.append(kwargs.get("timeout"))
        return session

    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    with _serving(server, paths, monkeypatch):
        first = _request(paths, {"op": "daemon-wait-ready", "params": {"timeout": 7.5}})
        again = _request(paths, {"op": "daemon-wait-ready", "params": {}})

    assert first is not None
    verdict = parse_result(first["stdout"])
    assert verdict == {"pid": os.getpid(), "launched": True}
    assert again is not None
    assert parse_result(again["stdout"])["launched"] is False
    assert launches == [7.5]  # one launch, bounded by the caller's timeout


def test_wait_ready_relays_the_typed_launch_failure(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # The wait shares the live ops' one launch boundary, so a failed launch is
    # the same typed refusal a live op gets — not a bespoke wait-ready error.
    def _launch(*args, **kwargs):
        return None

    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    with _serving(server, paths, monkeypatch):
        reply = _request(paths, {"op": "daemon-wait-ready", "params": {}})

    assert reply is not None
    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )


def test_a_silent_handshake_peer_cannot_hold_the_launch_past_the_deadline(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 1, at the launcher: ONE monotonic deadline spans
    # accept, the token frame, and the verification frame. A peer that connects
    # and then never speaks used to block the token read forever — here the
    # REAL launch_session must give up within the bound and record why.
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: _Proc(code=None))
    monkeypatch.setattr("gda.daemon.session._terminate", lambda proc: None)
    paths = daemon_paths(_project(tmp_path))
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(paths.harness_socket))
    listener.listen()
    silent = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    silent.connect(str(paths.harness_socket))  # queued for the launch's accept

    diagnostics: list[str] = []
    started = time.monotonic()
    try:
        outcome = launch_session(
            paths.project,
            "godot",
            listener,
            paths.harness_socket,
            "expected-token",
            timeout=0.3,
            diagnostics=diagnostics,
        )
        elapsed = time.monotonic() - started
    finally:
        silent.close()
        listener.close()

    assert outcome is None
    assert elapsed < 3.0, f"the silent peer held the launch for {elapsed:.1f}s"
    assert any("no auth token" in reason for reason in diagnostics)


def test_a_stuck_handshake_does_not_freeze_the_daemon(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 1, end to end: the REAL launch_session runs inside the
    # serve loop while a peer occupies the harness socket silently. wait-ready
    # must come back typed within its bound, and — the daemon serving one
    # request at a time — the NEXT control request must still be served.
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: _Proc(code=None))
    monkeypatch.setattr("gda.daemon.session._terminate", lambda proc: None)
    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot")  # the real launch seam default

    with _serving(server, paths, monkeypatch):
        silent = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        silent.connect(str(paths.harness_socket))
        try:
            reply = _request(
                paths,
                {"op": "daemon-wait-ready", "params": {"timeout": 0.3}},
                timeout=10.0,
            )
            assert reply is not None
            assert (
                parse_result(reply["stdout"])["error"]["code"]
                == "engine_session_not_running"
            )
            status = _request(paths, {"op": "__status__"})
            assert status is not None and status["ok"] is True
        finally:
            silent.close()


def test_wait_ready_rebuilds_a_session_whose_channel_broke(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 2: a relay that hits a broken harness channel latches
    # the session stale, so the NEXT wait-ready relaunches through the shared
    # boundary instead of reporting a serving state (launched: false) that the
    # very next read disproves — the engine process is still alive throughout.
    # The relaunch path close()s the stale session, whose real _terminate needs
    # a real process; the fake has none.
    monkeypatch.setattr("gda.daemon.session._terminate", lambda proc: None)
    ours, theirs = socket.socketpair()
    theirs.close()
    zombie = EngineSession(cast(subprocess.Popen, _Proc(code=None)), conn=ours)

    launches: list = []

    def _launch(*args, **kwargs):
        launches.append(1)
        return zombie if len(launches) == 1 else _ServedSession()

    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    with _serving(server, paths, monkeypatch):
        first = _request(paths, {"op": "daemon-wait-ready", "params": {}})
        read = _request(paths, {"op": "game-tree", "params": {}})
        second = _request(paths, {"op": "daemon-wait-ready", "params": {}})
        served = _request(paths, {"op": "game-tree", "params": {}})

    assert first is not None and parse_result(first["stdout"])["launched"] is True
    assert read is not None
    assert parse_result(read["stdout"])["error"]["code"] == "engine_disconnected"
    assert second is not None and parse_result(second["stdout"])["launched"] is True
    assert served is not None and served["stdout"] == "served:game-tree"
    assert len(launches) == 2


def test_launched_is_reported_by_the_launch_owner(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 3 (TOCTOU): the launch fact travels WITH the launch
    # decision. A liveness that flips between two samples must never yield a
    # call that launched yet reported launched: false — the invariant is
    # "launched == (a launch actually happened on this call)".
    class _FlipSession(_ServedSession):
        def __init__(self) -> None:
            super().__init__()
            self.polls = 0

        def alive(self) -> bool:
            self.polls += 1
            return self.polls == 1  # alive at the first sample, gone at the next

    launches: list = []
    flip = _FlipSession()

    def _launch(*args, **kwargs):
        launches.append(1)
        return flip if len(launches) == 1 else _ServedSession()

    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    with _serving(server, paths, monkeypatch):
        first = _request(paths, {"op": "daemon-wait-ready", "params": {}})
        second = _request(paths, {"op": "daemon-wait-ready", "params": {}})

    assert first is not None and parse_result(first["stdout"])["launched"] is True
    assert second is not None
    launched_second = parse_result(second["stdout"])["launched"]
    assert launched_second == (len(launches) == 2), (
        f"launched={launched_second} but launches={len(launches)} — the reported "
        "fact desynced from what the launch owner actually did"
    )


def test_every_declared_daemon_served_op_is_intercepted_not_relayed(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 4: DAEMON_SERVED_OPS is the routing authority, so a
    # mutation that declares an op daemon-served without intercepting it must
    # fail HERE — every member is driven through the real loop with a session
    # cached, and none may reach the session's relay.
    class _RecordingSession(_ServedSession):
        def __init__(self) -> None:
            super().__init__()
            self.relayed: list[str] = []

        def request(self, operation: str, params: dict) -> dict:
            self.relayed.append(operation)
            return super().request(operation, params)

    session = _RecordingSession()

    def _launch(*args, **kwargs):
        return session

    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    with _serving(server, paths, monkeypatch):
        primed = _request(paths, {"op": "daemon-wait-ready", "params": {}})
        assert primed is not None
        for op in DAEMON_SERVED_OPS:
            reply = _request(paths, {"op": op, "params": {}})
            assert reply is not None, op

    assert session.relayed == []


def test_the_wire_boundary_re_enforces_the_wait_ready_bound(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 4: the finite (0, 50] rule holds at the IPC boundary
    # too — this socket can be driven by clients other than gda's CLI, and an
    # unbounded or non-finite value would defeat the bound the op promises.
    paths = daemon_paths(_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_no_launch)

    with _serving(server, paths, monkeypatch):
        for bad in (-1, 0, 1000, float("inf"), float("nan"), True, "10"):
            reply = _request(
                paths, {"op": "daemon-wait-ready", "params": {"timeout": bad}}
            )
            assert reply is not None, bad
            assert parse_result(reply["stdout"])["error"]["code"] == "invalid_params", (
                bad
            )
