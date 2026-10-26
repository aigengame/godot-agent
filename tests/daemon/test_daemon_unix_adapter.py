"""The Unix daemon adapter: a pidfile slot, socket files, signals, process groups.

The daemon's platform-bound operations sit behind one seam with an adapter per
platform (ADR-0047). Every test here needs a Unix mechanism and reads the
adapter's own state, so the module is gated on it; a test of the daemon's
platform-neutral behaviour reaches the adapter through the seam instead and
stays with its subject (#1233).

- The slot is a pidfile the daemon holds a lock on. One that exists but cannot
  be read is a runtime directory that cannot serve, ``daemon_runtime_unusable``;
  one whose bytes are not UTF-8 is malformed and reads as absent (#1201 A). A
  crashed predecessor's socket files and unlocked pidfile are reclaimed, the
  slot files are unlinked while the lock is still held, and a socket path longer
  than ``sun_path`` is refused before any spawn (ADR-0021).
- The signals: SIGTERM to a forked daemon cleans up the slot, an overdue stop
  signals the pid the slot names, and the status reports the socket path.
- The engine's process group: the adapter owns the group it spawned, retires
  the whole group and escalates for the whole group, collects a killed child
  without waiting for it, and charges a retirement to the caller's deadline
  (#725).
"""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.commands.daemon import (
    DaemonStatusResult,
    run_daemon_start_operation,
    run_daemon_status_operation,
)
from gda.core.engine.binary import GDA_GODOT_ENV
from gda.core.engine.sentinel import parse_result
from gda.core.failure.catalog import Failure
from gda.daemon.discovery import daemon_paths
from gda.daemon.host import host_platform
from gda.daemon.server import DaemonServer
from gda.daemon.session import EngineSession
from gda.daemon.unix import (
    UnixPlatform,
    UnixProcess,
    _capture_owned_pgid,
    _group_standing,
    _pidfile_lock_held,
    terminate,
)
from gda.exit_codes import EXIT_LIVE
from tests.support import (
    SCHEDULING_SLACK_S,
    FakeProc,
    await_daemon_ready,
    daemon_round_trip,
    no_launch,
    runnable_project,
    serving_daemon,
    stub_daemon_platform,
    stub_serving_daemon,
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the Unix daemon adapter"
)

COMMANDS = [
    ["game", "tree"],
    ["daemon", "status"],
    ["daemon", "stop"],
    ["daemon", "start"],
    ["daemon", "wait-ready"],
    ["daemon", "uninstall"],
]


@pytest.fixture(autouse=True)
def _no_engine(monkeypatch):
    # `daemon start` must stop before it spawns a daemon, on a host that has an
    # engine configured too.
    monkeypatch.setenv(GDA_GODOT_ENV, "/nonexistent/godot")


def _pidfile(project: Path) -> Path:
    pidfile = daemon_paths(project, platform=UnixPlatform()).pidfile
    pidfile.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return pidfile


def _run(command: list[str], project: Path):
    return CliRunner().invoke(app, [*command, "--project", str(project), "--json"])


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root reads a file with mode 000",
)
@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
def test_an_unreadable_pidfile_is_a_runtime_that_cannot_serve(
    command, tmp_path, daemon_runtime_dir
):
    project = runnable_project(tmp_path / "project")
    pidfile = _pidfile(project)
    pidfile.write_text(f"{os.getpid()}\n{project.resolve()}\n", encoding="utf-8")
    pidfile.chmod(0)
    try:
        result = _run(command, project)
    finally:
        pidfile.chmod(0o600)

    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.exit_code == EXIT_LIVE
    assert json.loads(result.stdout)["error"]["code"] == "daemon_runtime_unusable"


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
def test_an_undecodable_pidfile_reads_as_absent(command, tmp_path, daemon_runtime_dir):
    project = runnable_project(tmp_path / "project")
    absent = _run(command, project)
    _pidfile(project).write_bytes(b"\xff\xfe\x00bad\n")

    result = _run(command, project)

    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert (result.exit_code, result.stdout) == (absent.exit_code, absent.stdout)


# The slot on disk.


def test_a_stale_slot_left_by_a_crash_is_reclaimed(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # A crashed predecessor leaves socket files bound-then-abandoned and a pidfile
    # whose advisory lock nobody holds. A fresh serve() must reclaim the slot.
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    for stale in (paths.cli_socket, paths.harness_socket):
        abandoned = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        abandoned.bind(str(stale))
        abandoned.close()  # the file stays on disk; nothing listens
    paths.pidfile.write_text("999999\n/nowhere\n", encoding="utf-8")

    server = DaemonServer(
        paths, godot="godot", launch=no_launch, platform=host_platform()
    )
    with serving_daemon(server, paths, monkeypatch):
        reply = daemon_round_trip(paths, {"op": "__status__"})
        assert reply is not None and reply["ok"] is True


def test_cleanup_removes_the_slot_before_releasing_the_lock(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # The reverse half of the slot's critical section (#723 review): the lock is
    # the slot's mutual exclusion (ADR-0021), so it must outlive the slot it
    # guards. Released before the unlinks, a successor can acquire and bind a
    # fresh slot inside the cleanup window — which the predecessor's remaining
    # unlinks then destroy. Instrumenting unlink pins the order: every slot
    # path must be removed while the lock is still held.
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=no_launch, platform=host_platform()
    )
    slot = {paths.cli_socket, paths.harness_socket, paths.pidfile}
    held_at_unlink: dict = {}
    real_unlink = os.unlink

    def _recording_unlink(path, *args, **kwargs):
        target = Path(path)
        if target in slot:
            held_at_unlink[target.name] = _pidfile_lock_held(paths.pidfile)
        return real_unlink(path, *args, **kwargs)

    with serving_daemon(server, paths, monkeypatch) as thread:
        monkeypatch.setattr(os, "unlink", _recording_unlink)
        daemon_round_trip(paths, {"op": "__stop__"})
        thread.join(timeout=5)

    assert len(held_at_unlink) == 3
    assert all(held_at_unlink.values()), held_at_unlink

    # The handoff itself: a successor started after the stop owns a fresh slot
    # and is the one the discovery contract reports.
    successor = DaemonServer(
        paths, godot="godot", launch=no_launch, platform=host_platform()
    )
    with serving_daemon(successor, paths, monkeypatch):
        assert host_platform().daemon_pid(paths) == os.getpid()
        reply = daemon_round_trip(paths, {"op": "__status__"})
        assert reply is not None and reply["ok"] is True


def test_a_termination_signal_cleans_up_the_slot(tmp_path, daemon_runtime_dir):
    # The REAL production signal path, in a forked child where serve() runs on
    # the main thread exactly as the daemon does: SIGTERM interrupts the blocked
    # accept (EINTR), the registered handler closes the listener and sets the
    # stop flag, the loop exits, cleanup unlinks the slot. A worker-thread
    # re-enactment is deliberately NOT used here — on Linux, closing a listener
    # from another thread does not wake a blocked accept, which is a fact about
    # threads, not about the signal path under test.
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=no_launch, platform=host_platform()
    )

    child = os.fork()
    if child == 0:  # the daemon: serve until signalled, then leave pytest silently
        try:
            server.serve()
        finally:
            os._exit(0)

    try:
        await_daemon_ready(paths)
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
    assert outcome.error.code == "daemon_runtime_unusable"
    assert "socket path longer" in outcome.error.message


# The signals.


def test_a_unix_status_reports_the_socket_path_and_no_endpoint(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # The Unix daemon publishes its CLI socket path; a loopback endpoint record
    # is the Windows publication (ADR-0047).
    project = runnable_project(tmp_path)
    stub_serving_daemon(monkeypatch, 4242)

    status = run_daemon_status_operation(project)

    assert isinstance(status, DaemonStatusResult), status
    assert status.socket_path == str(
        daemon_paths(project, platform=host_platform()).cli_socket
    )
    assert status.endpoint is None


def test_an_overdue_unix_stop_signals_the_daemon_it_names(tmp_path):
    # The Unix slot proves its owner, so a daemon that still held the slot at
    # the stop deadline is ended by its pid. A stop that settled in time sends
    # nothing.
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert UnixPlatform().settle_stop(paths, child.pid, overdue=False) is True
        assert child.poll() is None
        assert UnixPlatform().settle_stop(paths, child.pid, overdue=True) is True
        assert child.wait(timeout=10) == -signal.SIGTERM
    finally:
        child.kill()
        child.wait()


# The engine's process group.


# A stand-in engine that survives SIGTERM, so a teardown's escalation is observable.
# It announces itself: the handler is installed by the CHILD, so a SIGTERM that
# arrives during interpreter startup still kills it by the default disposition —
# a teardown test that raced the startup would exercise the ordinary path and
# prove nothing (observed: `terminate` 1ms after spawn returned -15, not -9).
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
    """Spawn the SIGTERM-ignoring stand-in and return it only once it IS stubborn."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _IGNORES_SIGTERM],
        stdout=subprocess.PIPE,
        text=True,
        **kwargs,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "ready"
    return proc


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


def _leader_with_descendant(
    source: str,
) -> "tuple[subprocess.Popen, int, UnixProcess]":
    """Spawn a group leader that reports its descendant's pid, and both are up.

    Returns the leader, the descendant's pid, and the session process that owns
    the leader's group.
    """
    leader = subprocess.Popen(
        [sys.executable, "-c", source],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    # Match production: ownership is captured immediately after Popen, not after
    # reading output from a leader whose source may already have exited.
    owned = UnixProcess(leader)
    assert leader.stdout is not None
    return leader, int(leader.stdout.readline().strip()), owned


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
    terminate(cast(subprocess.Popen, _SlowPoll()), time.monotonic() + 0.05)
    elapsed = time.monotonic() - started

    assert killed, "the engine was never escalated"
    assert elapsed < 0.08 + SCHEDULING_SLACK_S, (
        f"teardown waited {elapsed:.2f}s after a budget already spent"
    )


def test_the_owner_keeps_the_group_a_reaped_leader_cannot_name(tmp_path):
    # #725 re-review: the group id is the LEADER'S pid, and `EngineSession.alive()`
    # polls the leader — which reaps it. Rediscovering the group at teardown then
    # returned nothing and the engine's descendants were never retired (probed:
    # leader exited 0, group unrecoverable, descendant alive). The owner captures
    # the group at spawn and keeps it.
    leader, descendant, owned = _leader_with_descendant(_EXITS_LEAVING_STUBBORN_CHILD)
    session = EngineSession(owned, conn=None)
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
    leader, descendant, owned = _leader_with_descendant(
        _EXITS_LEAVING_CLEANING_CHILD.format(marker=str(marker))
    )
    session = EngineSession(owned, conn=None)
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
    leader, descendant, owned = _leader_with_descendant(
        _OBEYS_SIGTERM_WITH_CLEANING_CHILD.format(marker=str(marker))
    )
    try:
        started = time.monotonic()
        owned.retire(time.monotonic() + 5.0)
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
    leader, descendant, owned = _leader_with_descendant(
        _OBEYS_SIGTERM_WITH_STUBBORN_CHILD
    )
    try:
        # Same test-chosen deadline as above: the stubborn descendant makes the
        # wait run to the deadline, so it is kept short (#815).
        owned.retire(time.monotonic() + 0.2)
        assert leader.returncode == -signal.SIGTERM  # the leader DID obey
        _assert_gone(descendant, "descendant")
    finally:
        _reap_group(descendant, leader.pid)


def test_the_escalation_covers_the_group_the_engine_owns(monkeypatch):
    # #725 fourth re-review: SIGTERM went to the process group, SIGKILL only to
    # the leader — so a descendant that also ignored SIGTERM was left alive and
    # orphaned. The session is spawned with `start_new_session=True`, so gda owns
    # that group; the escalation must match the signal that preceded it.
    leader, descendant, owned = _leader_with_descendant(_IGNORES_SIGTERM_WITH_CHILD)
    try:
        owned.retire(time.monotonic() + 0.05)
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
        terminate(cast(subprocess.Popen, slow), time.monotonic() + 0.05)
        elapsed = time.monotonic() - started
        assert elapsed < 0.05 + SCHEDULING_SLACK_S, (
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
        terminate(stubborn, time.monotonic() + 0.05)
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
    # NOTE: a real child, owned as the Unix adapter owns it, on purpose — the
    # real teardown IS the subject, and a stand-in that retires nothing is
    # exactly what hid this interaction.
    monkeypatch.setattr("gda.daemon.session.OP_TIMEOUT", 0.2)
    stubborn = _stubborn_child(start_new_session=True)
    ours, silent_harness = socket.socketpair()
    stale = EngineSession(UnixProcess(stubborn), conn=ours)

    launches: list = []

    def _launch(*args, **kwargs):
        launches.append(kwargs.get("deadline"))
        return stale if len(launches) == 1 else None

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )
    queued: list = []

    def _control_request_behind_it() -> None:
        # Enqueued WHILE wait-ready is being served, not after it returns: the
        # daemon serves one request at a time, so this is what a caller behind the
        # bounded one actually waits.
        time.sleep(0.05)
        at = time.monotonic()
        reply = daemon_round_trip(paths, {"op": "__status__"}, timeout=20.0)
        queued.append((reply, time.monotonic() - at))

    try:
        with serving_daemon(server, paths, monkeypatch):
            assert (
                daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})
                is not None
            )
            timed_out = daemon_round_trip(paths, {"op": "game-tree", "params": {}})
            behind = threading.Thread(target=_control_request_behind_it, daemon=True)
            behind.start()
            started = time.monotonic()
            reply = daemon_round_trip(
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
    assert elapsed < 0.3 + SCHEDULING_SLACK_S, (
        f"a 0.3s-bounded wait-ready took {elapsed:.2f}s"
    )
    # Retirement used the whole budget, so no replacement was launched past it.
    assert len(launches) == 1
    status, waited = queued[0]
    assert status is not None and status["ok"] is True
    assert waited < 0.3 + SCHEDULING_SLACK_S, (
        f"the request queued behind it waited {waited:.2f}s"
    )


def test_a_teardown_cannot_outlast_the_readiness_deadline(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 re-review finding 2: teardown draws from the caller's deadline. An
    # engine child that ignores SIGTERM used to start a FRESH five-second grace
    # after the readiness budget was already spent — a measured 5.3s for
    # `--timeout 0.3` — and the daemon serves one request at a time, so the whole
    # round trip and every request behind it waited it out.
    spawned: list = []

    def _spawn_stubborn_child(argv, deadline):
        proc = _stubborn_child(start_new_session=True)
        spawned.append(proc)
        return UnixProcess(proc)

    stub_daemon_platform(monkeypatch, spawn_session=_spawn_stubborn_child)
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", platform=host_platform()
    )  # the real launch + teardown
    queued: list = []

    def _control_request_behind_it() -> None:
        # Enqueued WHILE wait-ready is being served, so this measures what a
        # caller behind the bounded one actually waits — not what it waits once
        # the bounded one has already returned.
        time.sleep(0.05)
        at = time.monotonic()
        reply = daemon_round_trip(paths, {"op": "__status__"}, timeout=20.0)
        queued.append((reply, time.monotonic() - at))

    try:
        with serving_daemon(server, paths, monkeypatch):
            behind = threading.Thread(target=_control_request_behind_it, daemon=True)
            behind.start()
            started = time.monotonic()
            reply = daemon_round_trip(
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
    assert elapsed < 0.3 + SCHEDULING_SLACK_S, (
        f"a 0.3s-bounded wait-ready took {elapsed:.2f}s"
    )
    status, waited = queued[0]
    assert status is not None and status["ok"] is True
    assert waited < 0.3 + SCHEDULING_SLACK_S, (
        f"the request queued behind it waited {waited:.2f}s"
    )
