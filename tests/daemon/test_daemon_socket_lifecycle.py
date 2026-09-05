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
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from gda.commands.daemon import run_daemon_start_operation
from gda.daemon.discovery import (
    _pidfile_lock_held,
    daemon_paths,
    daemon_pid,
    read_pidfile,
)
from gda.daemon.protocol import read_message, write_frame, write_message
from gda.daemon.server import DAEMON_SERVED_OPS, DaemonServer
from gda.daemon.session import (
    LAUNCH_MARKER,
    EngineSession,
    _capture_owned_pgid,
    _group_standing,
    _terminate,
    launch_session,
)
from gda.errors import Failure
from gda.live_runner import DaemonRunner
from gda.parser import build_result, parse_result
from tests.support import FakeProc, runnable_project, no_engine_teardown

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")

_REAL_POPEN = subprocess.Popen

# What a bounded round trip may add on top of the bound itself: IPC, thread
# scheduling, and the daemon's own accept. Small on purpose — these assertions
# exist to pin the PUBLIC bound, so slack that swallows a restored full-duration
# wait would pin nothing.
_SCHEDULING_SLACK = 0.35


# A stand-in engine that survives SIGTERM, so a teardown's escalation is observable.
# It announces itself: the handler is installed by the CHILD, so a SIGTERM that
# arrives during interpreter startup still kills it by the default disposition —
# a teardown test that raced the startup would exercise the ordinary path and
# prove nothing (observed: `_terminate` 1ms after spawn returned -15, not -9).
# The same stand-in, plus a descendant inside its process group that is just as
# stubborn — so an escalation that reaches only the leader is observable.
_IGNORES_SIGTERM_WITH_CHILD = (
    "import signal, subprocess, sys, time;"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
    "child = subprocess.Popen([sys.executable, '-c',"
    ' "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN);'
    ' print(chr(120), flush=True); time.sleep(120)"'
    "], stdout=subprocess.PIPE,"
    " text=True);"
    "child.stdout.readline();"
    "print(child.pid, flush=True); time.sleep(120)"
)
# A leader that OBEYS SIGTERM, whose descendant does not — the asymmetric case,
# where the leader's own death used to end the teardown with the group alive.
_OBEYS_SIGTERM_WITH_STUBBORN_CHILD = (
    "import subprocess, sys, time;"
    "child = subprocess.Popen([sys.executable, '-c',"
    ' "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN);'
    ' print(chr(120), flush=True); time.sleep(120)"'
    "], stdout=subprocess.PIPE,"
    " text=True);"
    "child.stdout.readline();"
    "print(child.pid, flush=True); time.sleep(120)"
)
# A leader that EXITS AT ONCE, leaving a stubborn descendant in its group —
# so the group must survive the leader being reaped by a liveness check.
_EXITS_LEAVING_STUBBORN_CHILD = (
    "import subprocess, sys;"
    "child = subprocess.Popen([sys.executable, '-c',"
    ' "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN);'
    ' print(chr(120), flush=True); time.sleep(120)"'
    "], stdout=subprocess.PIPE,"
    " text=True);"
    "child.stdout.readline(); print(child.pid, flush=True)"
)
# A leader that obeys SIGTERM, whose descendant handles SIGTERM by doing 0.2s of
# work and touching a marker — so a teardown that kills the group the instant
# the leader exits is observable as a MISSING marker.
_CLEANING_CHILD = (
    "import signal, time\n"
    "def _cleanup(sig, frame):\n"
    "    time.sleep(0.2)\n"
    "    open({marker!r}, 'w').close()\n"
    "    raise SystemExit(0)\n"
    "signal.signal(signal.SIGTERM, _cleanup)\n"
    "print('ready', flush=True)\n"
    "time.sleep(120)\n"
)
_OBEYS_SIGTERM_WITH_CLEANING_CHILD = (
    "import subprocess, sys, time\n"
    "source = '''" + _CLEANING_CHILD + "'''\n"
    "child = subprocess.Popen([sys.executable, '-c', source],"
    " stdout=subprocess.PIPE, text=True)\n"
    "child.stdout.readline()\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(120)\n"
)
_EXITS_LEAVING_CLEANING_CHILD = (
    "import subprocess, sys\n"
    "source = '''" + _CLEANING_CHILD + "'''\n"
    "child = subprocess.Popen([sys.executable, '-c', source],"
    " stdout=subprocess.PIPE, text=True)\n"
    "child.stdout.readline()\n"
    "print(child.pid, flush=True)\n"
)
_IGNORES_SIGTERM = (
    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "print('ready', flush=True); time.sleep(60)"
)


def _stubborn_child(**kwargs) -> subprocess.Popen:
    """Spawn the SIGTERM-ignoring stand-in and return it only once it IS stubborn.

    Bound to the REAL ``Popen``: a test that fakes the launch spawn patches
    ``subprocess.Popen`` itself, and spawning through the patched name would
    recurse.
    """
    kwargs.pop("stdout", None)
    proc = _REAL_POPEN(
        [sys.executable, "-c", _IGNORES_SIGTERM],
        stdout=subprocess.PIPE,
        text=True,
        **kwargs,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "ready"
    return proc


class _ServedSession:
    """A fake session that serves every relayed op — a structural SessionHandle."""

    log_file: "Path | None" = None

    def __init__(self, session_id: str = "fake-session") -> None:
        self.closed = False
        self.session_id = session_id

    def alive(self) -> bool:
        return True

    def request(self, operation: str, params: dict) -> dict:
        return {"stdout": f"served:{operation}", "stderr": "", "exit_code": 0}

    def close(self, deadline: "float | None" = None) -> None:
        self.closed = True
        self.close_deadline = deadline


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
    paths = daemon_paths(runnable_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_no_launch)

    with _serving(server, paths, monkeypatch):
        assert paths.cli_socket.exists()
        assert paths.harness_socket.exists()
        reply = _request(paths, {"op": "__status__"})
        assert reply == {
            "ok": True,
            "pid": os.getpid(),
            "windowed": False,
            # No session launched this lifetime -> nothing to correlate (#660).
            "session_id": None,
        }


def test_a_stale_slot_left_by_a_crash_is_reclaimed(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # A crashed predecessor leaves socket files bound-then-abandoned and a pidfile
    # whose advisory lock nobody holds. A fresh serve() must reclaim the slot.
    paths = daemon_paths(runnable_project(tmp_path))
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
    paths = daemon_paths(runnable_project(tmp_path))
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
    paths = daemon_paths(runnable_project(tmp_path))
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
    paths = daemon_paths(runnable_project(tmp_path))
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
    paths = daemon_paths(runnable_project(tmp_path))
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

    outcome = run_daemon_start_operation(runnable_project(tmp_path), "godot")

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

    paths = daemon_paths(runnable_project(tmp_path))
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

    paths = daemon_paths(runnable_project(tmp_path))
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
    no_engine_teardown(monkeypatch)  # the dying session is a stand-in, not a child
    ours, theirs = socket.socketpair()
    theirs.close()  # the harness end is gone: the relay write breaks mid-request
    proc = FakeProc(returncode=None)  # alive at the pre-request liveness check
    dying = EngineSession(cast(subprocess.Popen, proc), conn=ours)

    launches: list = []

    def _launch(*args, **kwargs):
        launches.append(kwargs.get("log_file"))
        if len(launches) == 1:
            return dying
        return _ServedSession()

    paths = daemon_paths(runnable_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    with _serving(server, paths, monkeypatch):
        first = _request(paths, {"op": "game-tree", "params": {}})
        proc.returncode = 1  # the engine process is now observed dead
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
        launches.append(kwargs.get("deadline"))
        return session

    paths = daemon_paths(runnable_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    with _serving(server, paths, monkeypatch):
        asked = time.monotonic()
        first = _request(paths, {"op": "daemon-wait-ready", "params": {"timeout": 7.5}})
        again = _request(paths, {"op": "daemon-wait-ready", "params": {}})

    assert first is not None
    verdict = parse_result(first["stdout"])
    assert verdict == {"pid": os.getpid(), "launched": True}
    assert again is not None
    assert parse_result(again["stdout"])["launched"] is False
    # One launch, and what reaches the launcher is the caller's own DEADLINE —
    # an instant it cannot outlive, not a duration it could restart (#725
    # re-review). It is no later than 7.5s after the request was made, and (with
    # nothing to retire here) not meaningfully earlier either.
    assert len(launches) == 1
    # The slack is the request's own transit: the daemon starts the clock when it
    # RECEIVES the call, so the instant is 7.5s from there, not from here.
    assert asked < launches[0] <= asked + 7.5 + _SCHEDULING_SLACK


def test_status_reports_the_minted_session_identity_across_the_lifecycle(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #660 over the real loop: no identity before a launch; the launch boundary
    # MINTS one and hands it to the launcher (the daemon is the authority for
    # what it launches); `__status__` reports the SAME value while the session
    # lives AND after it dies — a crashed session stays correlatable, like the
    # log ops keep it diagnosable — and a relaunch mints a fresh one.
    minted: list = []
    sessions: list = []

    class _Mortal(_ServedSession):
        def __init__(self, session_id: str) -> None:
            super().__init__(session_id)
            self.dead = False

        def alive(self) -> bool:
            return not self.dead

    def _launch(*args, **kwargs):
        minted.append(kwargs["session_id"])
        session = _Mortal(kwargs["session_id"])
        sessions.append(session)
        return session

    paths = daemon_paths(runnable_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    with _serving(server, paths, monkeypatch):
        before = _request(paths, {"op": "__status__"})
        _request(paths, {"op": "game-tree", "params": {}})  # the lazy launch
        alive_status = _request(paths, {"op": "__status__"})
        sessions[0].dead = True  # the session dies, nothing has replaced it yet
        dead_status = _request(paths, {"op": "__status__"})
        _request(paths, {"op": "game-tree", "params": {}})  # the relaunch
        relaunched = _request(paths, {"op": "__status__"})

    assert before is not None and before["session_id"] is None
    assert len(minted) == 2
    first, second = minted
    # An opaque daemon-minted identity: 16 lowercase hex chars, fresh per launch.
    assert isinstance(first, str) and len(first) == 16
    assert set(first) <= set("0123456789abcdef")
    assert alive_status is not None and alive_status["session_id"] == first
    assert dead_status is not None and dead_status["session_id"] == first
    assert relaunched is not None and relaunched["session_id"] == second
    assert second != first


def test_a_failed_replacement_launch_retains_the_last_established_identity(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #746 review ARC-746-001: retirement drops the session OBJECT before the
    # replacement launch, so the identity must live in a read model written only
    # on success — a failed replacement replaces nothing and must not erase the
    # identity `daemon status` promised to keep readable until replacement.
    minted: list = []
    sessions: list = []

    class _Mortal(_ServedSession):
        def __init__(self, session_id: str) -> None:
            super().__init__(session_id)
            self.dead = False

        def alive(self) -> bool:
            return not self.dead

    def _launch(*args, **kwargs):
        minted.append(kwargs["session_id"])
        if len(minted) == 2:
            return None  # the replacement launch FAILS
        session = _Mortal(kwargs["session_id"])
        sessions.append(session)
        return session

    paths = daemon_paths(runnable_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    with _serving(server, paths, monkeypatch):
        _request(paths, {"op": "game-tree", "params": {}})  # establish
        sessions[0].dead = True
        failed = _request(paths, {"op": "game-tree", "params": {}})  # fails
        retained = _request(paths, {"op": "__status__"})
        recovered = _request(paths, {"op": "game-tree", "params": {}})  # succeeds
        replaced = _request(paths, {"op": "__status__"})

    assert failed is not None
    assert (
        parse_result(failed["stdout"])["error"]["code"] == "engine_session_not_running"
    )
    assert len(minted) == 3
    # dead -> failed replacement -> the OLD identity is retained...
    assert retained is not None and retained["session_id"] == minted[0]
    # ...and only the successful replacement publishes the new one.
    assert recovered is not None and recovered["stdout"] == "served:game-tree"
    assert replaced is not None and replaced["session_id"] == minted[2]
    assert replaced["session_id"] != minted[0]


def test_launch_session_places_the_identity_on_the_harness_tail(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # The identity travels to the harness on the existing launch tail (#660):
    # LAST, after the marker, socket, token, and scene selector — positional and
    # bounds-checked harness-side, so an older harness ignores it.
    spawned: list = []

    def _record_spawn(argv, **kwargs):
        spawned.append(argv)
        return FakeProc(returncode=None)

    monkeypatch.setattr(subprocess, "Popen", _record_spawn)
    no_engine_teardown(monkeypatch)
    paths = daemon_paths(runnable_project(tmp_path))
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(paths.harness_socket))
    listener.listen()

    try:
        outcome = launch_session(
            paths.project,
            "godot",
            listener,
            paths.harness_socket,
            "expected-token",
            deadline=time.monotonic() + 0.2,  # no harness will connect: bounded
            scene="res://main.tscn",
            session_id="a1b2c3d4e5f60718",
        )
    finally:
        listener.close()

    assert outcome is None  # nothing connected — only the spawn matters here
    assert len(spawned) == 1
    tail = spawned[0][spawned[0].index(LAUNCH_MARKER) :]
    assert tail == [
        LAUNCH_MARKER,
        str(paths.harness_socket),
        "expected-token",
        "res://main.tscn",
        "a1b2c3d4e5f60718",
    ]


def test_wait_ready_relays_the_typed_launch_failure(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # The wait shares the live ops' one launch boundary, so a failed launch is
    # the same typed refusal a live op gets — not a bespoke wait-ready error.
    def _launch(*args, **kwargs):
        return None

    paths = daemon_paths(runnable_project(tmp_path))
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
    monkeypatch.setattr(
        subprocess, "Popen", lambda argv, **kw: FakeProc(returncode=None)
    )
    no_engine_teardown(monkeypatch)
    paths = daemon_paths(runnable_project(tmp_path))
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
            deadline=time.monotonic() + 0.3,
            diagnostics=diagnostics,
        )
        elapsed = time.monotonic() - started
    finally:
        silent.close()
        listener.close()

    assert outcome is None
    assert elapsed < 3.0, f"the silent peer held the launch for {elapsed:.1f}s"
    assert any("no auth token" in reason for reason in diagnostics)


@pytest.mark.parametrize("frame", ["token", "verification"])
def test_a_trickling_handshake_peer_cannot_hold_the_launch_past_the_deadline(
    tmp_path, daemon_runtime_dir, monkeypatch, frame
):
    # #725 re-review finding 1: silence is not the only way to hold the reader.
    # A socket timeout bounds each recv, so a peer that sends ONE BYTE just
    # inside it restarts the clock on every chunk and the frame never ends. Both
    # handshake frames are read in chunks, so both are exposed; the deadline has
    # to be recomputed per recv, not set once per frame. Measured before the fix
    # at a 0.04s/byte trickle on a 0.05s bound: 0.7s for the token frame, 2.1s
    # for the verification frame — and the trickle rate is the peer's to choose.
    monkeypatch.setattr(
        subprocess, "Popen", lambda argv, **kw: FakeProc(returncode=None)
    )
    no_engine_teardown(monkeypatch)
    paths = daemon_paths(runnable_project(tmp_path))
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(paths.harness_socket))
    listener.listen()
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    peer.connect(str(paths.harness_socket))

    def _trickle() -> None:
        if frame == "verification":
            write_frame(peer, b"expected-token")  # the token frame arrives whole
            body = b'{"scene_ok": true, "current": "res://main.tscn"}'
        else:
            body = b"expected-token"
        wire = len(body).to_bytes(4, "big") + body
        for byte in wire:  # each byte lands inside the 0.05s bound, resetting it
            try:
                peer.sendall(bytes([byte]))
            except OSError:
                return
            time.sleep(0.04)

    trickler = threading.Thread(target=_trickle, daemon=True)
    trickler.start()
    started = time.monotonic()
    try:
        outcome = launch_session(
            paths.project,
            "godot",
            listener,
            paths.harness_socket,
            "expected-token",
            deadline=time.monotonic() + 0.05,
        )
        elapsed = time.monotonic() - started
    finally:
        peer.close()
        listener.close()
        trickler.join(timeout=5)

    assert outcome is None
    assert elapsed < 0.5, f"the trickling peer held the launch for {elapsed:.2f}s"


def test_a_slow_spawn_cannot_revive_the_callers_expired_deadline(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 third re-review: the launcher used to take a DURATION and start its own
    # clock with it — after truncating the log and spawning the engine. So the
    # spawn was charged to nobody and an exhausted budget came back whole: a
    # 0.05s-bounded launch whose spawn alone took 0.12s still SUCCEEDED, with both
    # handshake frames already queued. It takes the caller's absolute instant now,
    # so a spawn that outruns the budget ends in a refusal, not a session.
    no_engine_teardown(monkeypatch)

    def _slow_popen(argv, **kwargs):
        time.sleep(0.12)  # a spawn that costs more than the whole budget
        return FakeProc(returncode=None)

    monkeypatch.setattr(subprocess, "Popen", _slow_popen)
    paths = daemon_paths(runnable_project(tmp_path))
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(paths.harness_socket))
    listener.listen()
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    peer.connect(str(paths.harness_socket))
    # Both frames are ALREADY waiting, so nothing but the clock can refuse this.
    write_frame(peer, b"expected-token")
    write_frame(peer, b'{"scene_ok": true, "current": "res://main.tscn"}')

    try:
        outcome = launch_session(
            paths.project,
            "godot",
            listener,
            paths.harness_socket,
            "expected-token",
            deadline=time.monotonic() + 0.05,
        )
    finally:
        peer.close()
        listener.close()

    assert outcome is None


def test_launch_preparation_that_crosses_the_deadline_spawns_nothing(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 fourth re-review: the deadline was gated BEFORE the Session-log
    # truncation but not after it. That truncation is a filesystem write and can
    # block, so a 0.12s write against a 0.05s deadline still reached `Popen` —
    # 0.076s past the bound. The gate belongs at the last interruptible point.
    spawned: list = []

    def _record_spawn(argv, **kwargs):
        spawned.append(time.monotonic())
        return FakeProc(returncode=None)

    real_write = Path.write_bytes

    def _slow_write(self, data):
        time.sleep(0.12)
        return real_write(self, data)

    monkeypatch.setattr(subprocess, "Popen", _record_spawn)
    monkeypatch.setattr(Path, "write_bytes", _slow_write)
    no_engine_teardown(monkeypatch)
    paths = daemon_paths(runnable_project(tmp_path))
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(paths.harness_socket))
    listener.listen()

    diagnostics: list[str] = []
    try:
        outcome = launch_session(
            paths.project,
            "godot",
            listener,
            paths.harness_socket,
            "expected-token",
            log_file=paths.session_log,
            deadline=time.monotonic() + 0.05,
            diagnostics=diagnostics,
        )
    finally:
        listener.close()

    assert outcome is None
    assert not spawned, "the engine was started after the deadline had passed"
    assert any("preparing the launch" in reason for reason in diagnostics), diagnostics


def test_a_deadline_spent_by_the_spawn_is_not_blamed_on_the_harness(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 fourth re-review: the spawn is the one uninterruptible step, so it CAN
    # outrun the budget — but the refusal has to say so. It used to fall through
    # and report that the harness sent no auth token, which is a different
    # failure and plainly false here: the token is already queued.
    def _slow_popen(argv, **kwargs):
        time.sleep(0.12)
        return FakeProc(returncode=None)

    monkeypatch.setattr(subprocess, "Popen", _slow_popen)
    no_engine_teardown(monkeypatch)
    paths = daemon_paths(runnable_project(tmp_path))
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(paths.harness_socket))
    listener.listen()
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    peer.connect(str(paths.harness_socket))
    write_frame(peer, b"expected-token")
    write_frame(peer, b'{"scene_ok": true, "current": "res://main.tscn"}')

    diagnostics: list[str] = []
    try:
        outcome = launch_session(
            paths.project,
            "godot",
            listener,
            paths.harness_socket,
            "expected-token",
            deadline=time.monotonic() + 0.05,
            diagnostics=diagnostics,
        )
    finally:
        peer.close()
        listener.close()

    assert outcome is None
    assert any("while the engine was starting" in r for r in diagnostics), diagnostics
    assert not any("auth token" in r for r in diagnostics), diagnostics


def test_retiring_a_stale_session_is_charged_to_the_callers_deadline(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 re-review finding 2: the launch boundary retires the session it is
    # replacing, and that retirement is work on the CALLER's clock. A stale
    # session whose engine ignores SIGTERM used to be closed on its own
    # five-second grace before the bounded launch even began — 5.0s for a
    # `wait-ready --timeout 0.3`, with the serve loop blocked throughout. When
    # retirement uses the whole budget there is nothing left to launch WITHIN, so
    # the boundary refuses instead of reviving the bound for a replacement.
    # NOTE: no `no_engine_teardown` here on purpose — the real teardown IS the
    # subject, and mocking it is exactly what hid this interaction.
    monkeypatch.setattr("gda.daemon.session.OP_TIMEOUT", 0.2)
    stubborn = _stubborn_child(start_new_session=True)
    ours, silent_harness = socket.socketpair()
    stale = EngineSession(stubborn, conn=ours)

    launches: list = []

    def _launch(*args, **kwargs):
        launches.append(kwargs.get("deadline"))
        return stale if len(launches) == 1 else None

    paths = daemon_paths(runnable_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)
    queued: list = []

    def _control_request_behind_it() -> None:
        # Enqueued WHILE wait-ready is being served, not after it returns: the
        # daemon serves one request at a time, so this is what a caller behind the
        # bounded one actually waits.
        time.sleep(0.05)
        at = time.monotonic()
        reply = _request(paths, {"op": "__status__"}, timeout=20.0)
        queued.append((reply, time.monotonic() - at))

    try:
        with _serving(server, paths, monkeypatch):
            assert (
                _request(paths, {"op": "daemon-wait-ready", "params": {}}) is not None
            )
            timed_out = _request(paths, {"op": "game-tree", "params": {}})
            behind = threading.Thread(target=_control_request_behind_it, daemon=True)
            behind.start()
            started = time.monotonic()
            reply = _request(
                paths,
                {"op": "daemon-wait-ready", "params": {"timeout": 0.3}},
                timeout=20.0,
            )
            elapsed = time.monotonic() - started
            behind.join(timeout=20.0)
    finally:
        silent_harness.close()
        stubborn.kill()

    assert timed_out is not None
    assert parse_result(timed_out["stdout"])["error"]["code"] == "live_timeout"
    assert reply is not None
    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )
    assert elapsed < 0.3 + _SCHEDULING_SLACK, (
        f"a 0.3s-bounded wait-ready took {elapsed:.2f}s"
    )
    # Retirement used the whole budget, so no replacement was launched past it.
    assert len(launches) == 1
    status, waited = queued[0]
    assert status is not None and status["ok"] is True
    assert waited < 0.3 + _SCHEDULING_SLACK, (
        f"the request queued behind it waited {waited:.2f}s"
    )


class _SlowToCollect:
    """A killed child the kernel has not made reapable yet — the worst case.

    A real SIGKILL is collectable in microseconds, so only a stand-in shows what a
    fixed post-kill allowance costs when collection is NOT instant (a child in
    uninterruptible I/O, a loaded host). It wraps a real child so the signalling
    is real; only the collection blocks, until the test releases it.
    """

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc
        self.released = threading.Event()
        self.returncode = None

    @property
    def pid(self) -> int:
        return self._proc.pid

    def poll(self):
        return self._proc.poll()

    def terminate(self) -> None:
        self._proc.terminate()

    def kill(self) -> None:
        self._proc.kill()

    def wait(self, timeout=None):
        if not self.released.wait(timeout):
            raise subprocess.TimeoutExpired("engine", timeout or 0)
        return self._proc.wait()


def test_teardown_adds_no_waiting_after_work_that_spent_the_deadline(monkeypatch):
    # #725 re-review: the deadline reached teardown as a DURATION, so the work
    # before the wait — the caller's channel close, the poll, the signal — was
    # spent and the full original grace was handed to the wait anyway (probed at
    # 0.08s of pre-wait work against a 0.05s budget: the wait still got 0.05).
    # The remainder is re-read where it is used, so work that already spent the
    # budget is followed by no waiting at all — only by the escalation.
    killed: list = []

    class _SlowPoll:
        pid = os.getpid()  # resolves to gda's own group, so no signal escapes

        def __init__(self) -> None:
            self.polls = 0

        def poll(self):
            self.polls += 1
            if self.polls == 1:
                time.sleep(0.08)  # pre-wait work that outlives the whole budget
            return None

        def terminate(self) -> None: ...

        def kill(self) -> None:
            killed.append(time.monotonic())

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("engine", timeout or 0)

    started = time.monotonic()
    _terminate(cast(subprocess.Popen, _SlowPoll()), time.monotonic() + 0.05)
    elapsed = time.monotonic() - started

    assert killed, "the engine was never escalated"
    assert elapsed < 0.08 + _SCHEDULING_SLACK, (
        f"teardown waited {elapsed:.2f}s after a budget already spent"
    )


def _leader_with_descendant(
    source: str,
) -> "tuple[subprocess.Popen, int, int | None]":
    """Spawn a group leader that reports its descendant's pid, and both are up."""
    leader = _REAL_POPEN(
        [sys.executable, "-c", source],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    # Match production: ownership is captured immediately after Popen, not after
    # reading output from a leader whose source may already have exited.
    owned_pgid = _capture_owned_pgid(leader)
    assert leader.stdout is not None
    return leader, int(leader.stdout.readline().strip()), owned_pgid


def _assert_gone(pid: int, what: str) -> None:
    end = time.monotonic() + 5.0
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    raise AssertionError(f"the {what} {pid} outlived the group retirement")


def _reap_group(*pids: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_the_live_clients_ceiling_covers_the_whole_round_trip(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 re-review: the client set the socket timeout once and read the reply
    # in as many chunks as the daemon sent, so its published 60s was a per-recv
    # INACTIVITY timeout, not a round-trip ceiling — a trickling daemon could
    # hold the CLI indefinitely. Same absolute-instant rule as every other read.
    monkeypatch.setattr("gda.live_runner.LIVE_REQUEST_TIMEOUT", 0.3)
    paths = daemon_paths(runnable_project(tmp_path))
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(paths.cli_socket))
    listener.listen()

    def _trickle() -> None:
        conn, _ = listener.accept()
        read_message(conn)
        body = build_result({"ok": True}).encode("utf-8")
        wire = len(body).to_bytes(4, "big") + body
        for byte in wire:  # each byte lands inside the bound, resetting it
            try:
                conn.sendall(bytes([byte]))
            except OSError:
                return
            time.sleep(0.2)

    daemon = threading.Thread(target=_trickle, daemon=True)
    daemon.start()
    started = time.monotonic()
    try:
        # The request leg itself: daemon discovery is not what is under test.
        result = DaemonRunner(paths.project)._request(paths.cli_socket, "game-tree", {})
        elapsed = time.monotonic() - started
    finally:
        listener.close()
        daemon.join(timeout=5)

    assert elapsed < 0.3 + _SCHEDULING_SLACK, (
        f"the trickled reply held the CLI for {elapsed:.2f}s"
    )
    assert parse_result(result.stdout)["error"]["code"] == "live_timeout"


def test_the_live_client_write_uses_only_the_round_trip_budget_left(monkeypatch):
    # #725 re-review: passing the absolute instant only to the reply read left
    # connect and request send on independent full socket timeouts. Work in the
    # first leg therefore gave the second a fresh grace, despite the published
    # whole-round-trip ceiling.
    send_timeouts: list[float] = []

    class _AccumulatingSocket:
        timeout = 0.0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def settimeout(self, timeout: float) -> None:
            self.timeout = timeout

        def connect(self, path: str) -> None:
            time.sleep(0.06)

        def sendall(self, data: bytes) -> None:
            send_timeouts.append(self.timeout)
            time.sleep(self.timeout)
            raise TimeoutError

    monkeypatch.setattr("gda.live_runner.LIVE_REQUEST_TIMEOUT", 0.1)
    # Replace the runner's module binding, not ``socket.socket`` on the shared
    # stdlib module: another thread may legitimately create a real socket while
    # this test runs.
    monkeypatch.setattr(
        "gda.live_runner.socket",
        SimpleNamespace(
            AF_UNIX=socket.AF_UNIX,
            SOCK_STREAM=socket.SOCK_STREAM,
            socket=lambda *args, **kwargs: _AccumulatingSocket(),
        ),
    )
    started = time.monotonic()
    result = DaemonRunner(Path("."))._request(Path("unused.sock"), "game-tree", {})
    elapsed = time.monotonic() - started

    assert send_timeouts, "the request was never written"
    assert 0 < send_timeouts[0] < 0.08, (
        f"the write received a fresh {send_timeouts[0]:.3f}s timeout"
    )
    assert elapsed < 0.1 + _SCHEDULING_SLACK
    assert parse_result(result.stdout)["error"]["code"] == "live_timeout"


def test_the_owner_keeps_the_group_a_reaped_leader_cannot_name(tmp_path):
    # #725 re-review: the group id is the LEADER'S pid, and `EngineSession.alive()`
    # polls the leader — which reaps it. Rediscovering the group at teardown then
    # returned nothing and the engine's descendants were never retired (probed:
    # leader exited 0, group unrecoverable, descendant alive). The owner captures
    # the group at spawn and keeps it.
    leader, descendant, owned_pgid = _leader_with_descendant(
        _EXITS_LEAVING_STUBBORN_CHILD
    )
    session = EngineSession(leader, conn=None, owned_pgid=owned_pgid)
    try:
        end = time.monotonic() + 5.0
        while session.alive() and time.monotonic() < end:
            time.sleep(0.01)  # the liveness check that reaps the leader
        assert not session.alive()
        assert _capture_owned_pgid(leader) is None, (
            "the reaped leader still names a group"
        )
        # The deadline is this test's own, not a product constant: the descendant
        # ignores SIGTERM, so the teardown polls it out in full before it
        # escalates. 0.2s is the outcome's cost, not 5s (#815).
        session.close(time.monotonic() + 0.2)
        _assert_gone(descendant, "descendant")
    finally:
        _reap_group(descendant, leader.pid)


def test_a_reaped_leader_does_not_prevent_descendant_cleanup(tmp_path):
    # Capturing the group fixed its identity after `alive()` reaped the leader,
    # but teardown still gated SIGTERM on that leader being alive. The stored
    # group must receive its graceful signal independently of the leader.
    marker = tmp_path / "cleanup-after-leader"
    leader, descendant, owned_pgid = _leader_with_descendant(
        _EXITS_LEAVING_CLEANING_CHILD.format(marker=str(marker))
    )
    session = EngineSession(leader, conn=None, owned_pgid=owned_pgid)
    try:
        end = time.monotonic() + 5.0
        while session.alive() and time.monotonic() < end:
            time.sleep(0.01)
        assert not session.alive()
        started = time.monotonic()
        session.close(time.monotonic() + 1.0)
        elapsed = time.monotonic() - started
        assert marker.exists(), "the reaped leader prevented the group SIGTERM"
        assert elapsed < 1.0, "teardown waited out the whole deadline"
    finally:
        _reap_group(descendant, leader.pid)


def test_only_a_process_group_leader_can_be_claimed_as_owned(monkeypatch):
    class _GroupMember:
        pid = 1234

    monkeypatch.setattr(os, "getpgid", lambda pid: 1200)
    monkeypatch.setattr(os, "getpgrp", lambda: 1100)

    assert _capture_owned_pgid(cast(subprocess.Popen, _GroupMember())) is None


def test_a_permission_error_does_not_mean_the_group_is_empty(monkeypatch):
    def _permission_denied(group: int, sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "killpg", _permission_denied)

    assert _group_standing(1234, cast(subprocess.Popen, FakeProc()))


def test_a_descendant_may_finish_its_own_cleanup_inside_the_deadline(tmp_path):
    # #725 re-review, the other side of group ownership: SIGKILL used to follow
    # the moment the LEADER exited, so a descendant still running its own SIGTERM
    # handler was truncated even with the whole budget left. The wait is for the
    # group, so a descendant that completes within the deadline gets to.
    marker = tmp_path / "cleanup-done"
    leader, descendant, owned_pgid = _leader_with_descendant(
        _OBEYS_SIGTERM_WITH_CLEANING_CHILD.format(marker=str(marker))
    )
    try:
        started = time.monotonic()
        _terminate(
            leader,
            time.monotonic() + 5.0,
            owned_pgid=owned_pgid,
        )
        elapsed = time.monotonic() - started
        assert marker.exists(), "the descendant's cleanup was cut short"
        assert elapsed < 5.0, "teardown waited out the whole deadline"
    finally:
        _reap_group(descendant, leader.pid)


def test_the_group_is_retired_even_when_the_leader_obeys_sigterm(monkeypatch):
    # #725 fifth re-review: the escalation was decided from the LEADER alone, so
    # a leader that obeyed the group SIGTERM ended the teardown — `wait()`
    # succeeded, the SIGKILL branch was skipped — while a descendant that
    # ignored it kept running, orphaned (probed: leader -15 in 0.001s,
    # descendant alive). gda owns the group, so the group is what gets retired.
    leader, descendant, owned_pgid = _leader_with_descendant(
        _OBEYS_SIGTERM_WITH_STUBBORN_CHILD
    )
    try:
        # Same test-chosen deadline as above: the stubborn descendant makes the
        # wait run to the deadline, so it is kept short (#815).
        _terminate(leader, time.monotonic() + 0.2, owned_pgid=owned_pgid)
        assert leader.returncode == -signal.SIGTERM  # the leader DID obey
        _assert_gone(descendant, "descendant")
    finally:
        _reap_group(descendant, leader.pid)


def test_the_escalation_covers_the_group_the_engine_owns(monkeypatch):
    # #725 fourth re-review: SIGTERM went to the process group, SIGKILL only to
    # the leader — so a descendant that also ignored SIGTERM was left alive and
    # orphaned. The session is spawned with `start_new_session=True`, so gda owns
    # that group; the escalation must match the signal that preceded it.
    leader, descendant, owned_pgid = _leader_with_descendant(
        _IGNORES_SIGTERM_WITH_CHILD
    )
    try:
        _terminate(leader, time.monotonic() + 0.05, owned_pgid=owned_pgid)
        _assert_gone(descendant, "descendant")
    finally:
        _reap_group(descendant, leader.pid)


def test_teardown_does_not_wait_for_the_kernel_to_collect_the_child(monkeypatch):
    # #725 third re-review: the escalation to SIGKILL is reached with the budget
    # ALREADY spent, so ANY fixed allowance after it is time the caller never
    # agreed to — and in the daemon, time every queued request waits too. A
    # half-second one turned a 0.01s-bounded wait-ready into 0.5s. Collection is
    # now a background duty, so teardown returns as soon as it has killed.
    slow = _SlowToCollect(_stubborn_child(start_new_session=True))
    try:
        started = time.monotonic()
        _terminate(cast(subprocess.Popen, slow), time.monotonic() + 0.05)
        elapsed = time.monotonic() - started
        assert elapsed < 0.05 + _SCHEDULING_SLACK, (
            f"teardown spent {elapsed:.2f}s waiting past a 0.05s grace"
        )
    finally:
        slow.released.set()
        slow.kill()


def test_a_killed_engine_is_still_collected(monkeypatch):
    # The other half: not waiting must not become not collecting. An uncollected
    # child keeps a None returncode for whatever happens to poll it next — in a
    # long-lived daemon, possibly nothing.
    stubborn = _stubborn_child(start_new_session=True)
    try:
        _terminate(stubborn, time.monotonic() + 0.05)
        # `returncode` is read directly, never through `poll()` — poll() would
        # collect the child itself and pass with no reaper at all.
        end = time.monotonic() + 10.0
        while stubborn.returncode is None and time.monotonic() < end:
            time.sleep(0.01)
        assert stubborn.returncode is not None, "the killed child was never collected"
        assert stubborn.returncode < 0  # ended by a signal, not by its own exit
    finally:
        if stubborn.returncode is None:
            stubborn.kill()


def test_a_stuck_handshake_does_not_freeze_the_daemon(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 1, end to end: the REAL launch_session runs inside the
    # serve loop while a peer occupies the harness socket silently. wait-ready
    # must come back typed within its bound, and — the daemon serving one
    # request at a time — the NEXT control request must still be served.
    monkeypatch.setattr(
        subprocess, "Popen", lambda argv, **kw: FakeProc(returncode=None)
    )
    no_engine_teardown(monkeypatch)
    paths = daemon_paths(runnable_project(tmp_path))
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
    no_engine_teardown(monkeypatch)
    ours, theirs = socket.socketpair()
    theirs.close()
    zombie = EngineSession(cast(subprocess.Popen, FakeProc(returncode=None)), conn=ours)

    launches: list = []

    def _launch(*args, **kwargs):
        launches.append(1)
        return zombie if len(launches) == 1 else _ServedSession()

    paths = daemon_paths(runnable_project(tmp_path))
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


def test_wait_ready_rebuilds_a_session_whose_relay_timed_out(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 re-review finding 1, through the daemon: a relay that times out leaves
    # the channel response-ambiguous (no request id, the frame is never drained),
    # so wait-ready must NOT certify it. Before the fix the daemon reported
    # `launched: false` over that channel and the next read went back to it.
    monkeypatch.setattr("gda.daemon.session.OP_TIMEOUT", 0.2)
    no_engine_teardown(monkeypatch)
    ours, silent_harness = socket.socketpair()
    desynced = EngineSession(
        cast(subprocess.Popen, FakeProc(returncode=None)), conn=ours
    )

    launches: list = []

    def _launch(*args, **kwargs):
        launches.append(1)
        return desynced if len(launches) == 1 else _ServedSession()

    paths = daemon_paths(runnable_project(tmp_path))
    server = DaemonServer(paths, godot="godot", launch=_launch)

    try:
        with _serving(server, paths, monkeypatch):
            first = _request(paths, {"op": "daemon-wait-ready", "params": {}})
            timed_out = _request(paths, {"op": "game-tree", "params": {}})
            second = _request(paths, {"op": "daemon-wait-ready", "params": {}})
            served = _request(paths, {"op": "game-tree", "params": {}})
    finally:
        silent_harness.close()

    assert first is not None and parse_result(first["stdout"])["launched"] is True
    assert timed_out is not None
    assert parse_result(timed_out["stdout"])["error"]["code"] == "live_timeout"
    assert second is not None and parse_result(second["stdout"])["launched"] is True
    assert served is not None and served["stdout"] == "served:game-tree"
    assert len(launches) == 2


def test_a_teardown_cannot_outlast_the_readiness_deadline(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 re-review finding 2: teardown draws from the caller's deadline. An
    # engine child that ignores SIGTERM used to start a FRESH five-second grace
    # after the readiness budget was already spent — a measured 5.3s for
    # `--timeout 0.3` — and the daemon serves one request at a time, so the whole
    # round trip and every request behind it waited it out.
    spawned: list = []

    def _spawn_stubborn_child(argv, **kwargs):
        proc = _stubborn_child(**kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", _spawn_stubborn_child)
    paths = daemon_paths(runnable_project(tmp_path))
    server = DaemonServer(paths, godot="godot")  # the real launch + teardown
    queued: list = []

    def _control_request_behind_it() -> None:
        # Enqueued WHILE wait-ready is being served, so this measures what a
        # caller behind the bounded one actually waits — not what it waits once
        # the bounded one has already returned.
        time.sleep(0.05)
        at = time.monotonic()
        reply = _request(paths, {"op": "__status__"}, timeout=20.0)
        queued.append((reply, time.monotonic() - at))

    try:
        with _serving(server, paths, monkeypatch):
            behind = threading.Thread(target=_control_request_behind_it, daemon=True)
            behind.start()
            started = time.monotonic()
            reply = _request(
                paths,
                {"op": "daemon-wait-ready", "params": {"timeout": 0.3}},
                timeout=20.0,
            )
            elapsed = time.monotonic() - started
            behind.join(timeout=20.0)
    finally:
        for proc in spawned:
            proc.kill()

    assert reply is not None
    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )
    assert elapsed < 0.3 + _SCHEDULING_SLACK, (
        f"a 0.3s-bounded wait-ready took {elapsed:.2f}s"
    )
    status, waited = queued[0]
    assert status is not None and status["ok"] is True
    assert waited < 0.3 + _SCHEDULING_SLACK, (
        f"the request queued behind it waited {waited:.2f}s"
    )


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

    paths = daemon_paths(runnable_project(tmp_path))
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

    paths = daemon_paths(runnable_project(tmp_path))
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
    paths = daemon_paths(runnable_project(tmp_path))
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
