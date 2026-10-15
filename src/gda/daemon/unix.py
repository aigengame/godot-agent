"""The Unix adapter of the daemon platform seam (ADR-0021, #1189).

The daemon's identity on Unix is a pidfile under a private (``0700``) runtime
directory, held by an advisory ``flock`` for the daemon's whole lifetime, beside
the two Unix domain sockets the CLI and the harness connect to. The held lock
is the liveness signal: a held lock means a live daemon, a grabbable lock a
crashed or stale one, with no reliance on PID liveness, which a reused PID could
spoof. The OS releases the lock when the daemon exits or crashes, so liveness
self-heals with no cleanup.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Callable, Optional, TextIO

from gda.daemon.discovery import DaemonPaths, runtime_unusable_message
from gda.daemon.platform import (
    HOME_RUNTIME_DIR,
    ControlDeadlines,
    ControlOutcome,
    RuntimeUnusable,
    SlotVerdict,
)
from gda.daemon.protocol import CONTROL_TIMEOUT, set_timeout_from_deadline

# The private runtime directory the sockets and the pidfile live in. Kept short
# so the absolute socket path stays under the OS ``sun_path`` limit (104 bytes on
# macOS, 108 on Linux); the long macOS ``$TMPDIR`` is deliberately never used.
XDG_RUNTIME_ENV = "XDG_RUNTIME_DIR"
RUNTIME_SUBDIR = "gda"
# How often teardown re-checks whether the engine's process group has emptied.
_RETIRE_POLL = 0.005


# Conservative UDS path bound (macOS ``sun_path`` is 104 bytes); a derived socket
# longer than this would fail to bind, so we surface it as a clear error here.
UDS_PATH_MAX = 104


def within_uds_limit(socket_path: Path) -> bool:
    """Whether ``socket_path`` fits the OS ``sun_path`` limit so it can bind.

    Pure derivation never raises on length (so it is testable under any tmp dir);
    the daemon checks this before binding and surfaces a clear error instead of an
    opaque bind failure (ADR-0021). The default runtime dirs are short enough that
    this only ever trips on an unusually long ``$XDG_RUNTIME_DIR``.
    """
    return len(str(socket_path)) <= UDS_PATH_MAX


class UnixPlatform:
    """Unix domain sockets, a pidfile lock and an owned process group."""

    def runtime_dir(self, env: Mapping[str, str]) -> Path:
        # ``$XDG_RUNTIME_DIR/gda`` when set (Linux), else ``~/.gda/run``: both
        # short, to respect the UDS ``sun_path`` length limit.
        xdg = env.get(XDG_RUNTIME_ENV)
        if xdg:
            return Path(xdg) / RUNTIME_SUBDIR
        return Path(HOME_RUNTIME_DIR).expanduser()

    def check_runtime(self, paths: DaemonPaths) -> None:
        # The slot is read with no privacy check: the daemon makes the directory
        # private when it takes the slot (ADR-0021). A slot that cannot be read is
        # refused before any operation reads it.
        try:
            self.daemon_pid(paths)
        except OSError:
            raise RuntimeUnusable(runtime_unusable_message(paths)) from None

    def prepare_runtime(self, paths: DaemonPaths) -> None:
        # The daemon creates the directory when it takes the slot.
        return None

    def check_bindable(self, paths: DaemonPaths) -> None:
        # A socket path over the OS ``sun_path`` limit fails the daemon's bind,
        # and the start then times out into a vague error (ADR-0021).
        if not (
            within_uds_limit(paths.cli_socket)
            and within_uds_limit(paths.harness_socket)
        ):
            raise RuntimeUnusable(
                f"the daemon runtime directory {paths.runtime_dir} yields a socket "
                "path longer than the OS limit for a Unix domain socket; set a "
                "shorter $XDG_RUNTIME_DIR"
            )

    def daemon_pid(self, paths: DaemonPaths) -> int | None:
        """The pid of a LIVE daemon for THIS project, or ``None`` (ADR-0021).

        Live requires all three: the pidfile's recorded project **matches** this
        project (else *foreign*: a hash collision or a reused slot), the CLI
        socket is **bound** (present), and the pidfile's advisory lock is
        **held** (a grabbable lock means a crashed or stale daemon). So a reused
        PID or a stale socket is never mistaken for a live daemon.
        """
        info = read_pidfile(paths)
        if info is None:
            return None
        pid, recorded = info
        if recorded != paths.project:
            return None  # foreign
        if not paths.cli_socket.exists():
            return None  # not bound -> stale
        if not _pidfile_lock_held(paths.pidfile):
            return None  # grabbable -> crashed/stale
        return pid

    def acquire_slot(
        self, paths: DaemonPaths, pid: int, startup_deadline: float | None
    ) -> TextIO:
        # No Unix start rolls back at a shared deadline: the parent passes none.
        return acquire_pidfile(paths, pid)

    def slot_verdict(
        self,
        paths: DaemonPaths,
        existing: int | None,
        ask_status: Callable[[], ControlOutcome],
    ) -> SlotVerdict | None:
        # The held pidfile lock proves the owner (ADR-0021).
        return None

    def settle_stop(self, paths: DaemonPaths, pid: int, overdue: bool) -> bool:
        # A graceful stop that did not take falls back to a signal.
        if overdue:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        return True

    def bind_endpoints(
        self, paths: DaemonPaths, pid: int, control_token: str
    ) -> tuple[socket.socket, socket.socket]:
        # The socket paths are the published endpoints; the pidfile lock, not a
        # token, keeps the slot to this daemon (ADR-0021).
        cli = _bind(paths.cli_socket)
        try:
            return cli, _bind(paths.harness_socket)
        except BaseException:
            cli.close()
            raise

    def unpublish(self, paths: DaemonPaths) -> None:
        # The pidfile goes with the sockets while its lock is still held.
        for path in (paths.cli_socket, paths.harness_socket, paths.pidfile):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def socket_path(self, paths: DaemonPaths) -> str | None:
        return str(paths.cli_socket)

    def endpoint_address(self, paths: DaemonPaths) -> tuple[str, int] | None:
        # The socket path is the published endpoint.
        return None

    def admit(self, conn: socket.socket, control_token: str) -> ControlDeadlines | None:
        # Only this user reaches the private socket directory (ADR-0021).
        return ControlDeadlines(None, None)

    def find_daemon(self, paths: DaemonPaths) -> int | None:
        try:
            return self.daemon_pid(paths)
        except OSError:
            raise RuntimeUnusable(runtime_unusable_message(paths)) from None

    @property
    def control_timeout(self) -> float:
        # The lock proves the owner and the reply is not read for it.
        return CONTROL_TIMEOUT

    def connect(self, paths: DaemonPaths, deadline: float) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            set_timeout_from_deadline(sock, deadline)
            sock.connect(str(paths.cli_socket))
            return sock
        except BaseException:
            sock.close()
            raise

    def owner_pid(self, reply: dict | None, pid: int | None) -> int | None:
        # The pidfile lock proves the owner (ADR-0021); the reply is not read.
        return pid

    def spawn_daemon(self, argv: list[str]) -> None:
        # A new session, so the daemon does not end with the caller's terminal.
        subprocess.Popen(
            argv,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def spawn_session(self, argv: list[str], deadline: float) -> UnixProcess:
        # The engine leads a new session, so gda owns its process group.
        return UnixProcess(
            subprocess.Popen(
                argv,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )

    def harness_argument(
        self, harness_listener: socket.socket, harness_socket: Path
    ) -> str:
        return str(harness_socket)

    @property
    def other_processes_reach_harness(self) -> bool:
        # The harness socket is in the private runtime directory (ADR-0021).
        return False


class UnixProcess:
    """An engine session process that leads a process group gda owns."""

    def __init__(self, popen: subprocess.Popen) -> None:
        self._popen = popen
        # The process group gda owns for this session, captured at spawn and
        # REMEMBERED (#725 re-review). It cannot be rediscovered at teardown:
        # ``poll()`` reaps the leader, and a reaped leader has no pid to read a
        # group from — after which nothing retires whatever the engine started.
        # A pid can also be reused; the id captured at spawn is the only one
        # known to be this session's. Captured while the leader certainly holds
        # its pid, and validated as the leader of a group other than gda's.
        self._owned_pgid = _capture_owned_pgid(popen)

    @property
    def pid(self) -> int:
        return self._popen.pid

    @property
    def returncode(self) -> int | None:
        return self._popen.returncode

    def poll(self) -> int | None:
        return self._popen.poll()

    def retire(self, deadline: float) -> None:
        terminate(self._popen, deadline, owned_pgid=self._owned_pgid)


def acquire_pidfile(paths: DaemonPaths, pid: int) -> TextIO:
    """Open + advisory-lock the pidfile, record ``pid`` + canonical path; return the held handle.

    Creates the private (``0700``) runtime directory first, so the socket is
    never in a world-reachable directory: the "no other-user surface" half of
    ADR-0021's "no localhost surface".

    The daemon keeps the returned file open for its whole lifetime so the ``flock``
    is *held*; that held lock IS the liveness signal (ADR-0021). Raises ``OSError``
    if another live daemon already holds it (a start race).

    Opened WITHOUT truncation, and truncated only AFTER the lock is won (#723
    review): ``open("w")`` zeroed the file before ``flock`` could refuse, so a
    LOSING start erased the live winner's recorded identity — ``daemon_pid``
    then read the running daemon as not running.
    """
    import fcntl

    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(paths.runtime_dir, 0o700)
    handle = os.fdopen(
        os.open(paths.pidfile, os.O_RDWR | os.O_CREAT, 0o644), "r+", encoding="utf-8"
    )
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise
    handle.seek(0)
    handle.truncate()
    handle.write(f"{pid}\n{paths.project}\n")
    handle.flush()
    return handle


def _bind(path: Path) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    # Reclaim a stale socket a crashed predecessor may have left bound.
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    sock.bind(str(path))
    sock.listen()
    return sock


def read_pidfile(paths: DaemonPaths) -> tuple[int, Path] | None:
    """Parse the pidfile into ``(pid, recorded_project)``, or ``None`` if absent/malformed."""
    try:
        text = paths.pidfile.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return None
    lines = text.splitlines()
    if len(lines) < 2 or not lines[0].strip().isdigit():
        return None
    return int(lines[0].strip()), Path(lines[1].strip())


def _pidfile_lock_held(pidfile: Path) -> bool:
    """Whether the pidfile's advisory lock is currently held by a live daemon."""
    import fcntl

    try:
        probe = open(pidfile, "r", encoding="utf-8")
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True  # could not grab it -> held by a live daemon
    else:
        fcntl.flock(probe.fileno(), fcntl.LOCK_UN)  # we grabbed it -> stale; release
        return False
    finally:
        probe.close()


def terminate(
    proc: subprocess.Popen,
    deadline: float,
    owned_pgid: Optional[int] = None,
) -> None:
    """SIGTERM the engine group, then SIGKILL it if it has not exited by ``deadline``.

    ``deadline`` is an absolute instant, and the wait is measured from it at the
    moment the wait begins — not from whenever the caller decided (#725
    re-review). The daemon serves one request at a time, so a child that ignores
    SIGTERM used to add a fresh five-second wait AFTER the caller's budget was
    spent (a 0.3s-bounded ``daemon wait-ready`` measured 5.3s); converting the
    instant to a duration up front had the same shape one layer down, since
    closing the channel and signalling the engine consume the budget too. A
    caller with no clock of its own mints one (``EngineSession.close`` does).

    What is retired is the ENGINE'S PROCESS GROUP, not the engine process. The
    session is launched with ``start_new_session=True``, so gda owns that group
    and everything the engine started inside it, and the leader's fate decides
    neither when the group is done nor how it ends (#725 re-review): a leader
    that OBEYED the group SIGTERM used to end the teardown while a descendant
    that ignored it kept running, orphaned — and a leader that exited on its own
    used to end it while its descendant had not been signalled at all.

    So the wait is for the GROUP to empty, within the same deadline, and only a
    group still standing when the deadline arrives is escalated to SIGKILL. That
    order matters both ways: a descendant given SIGTERM may legitimately still be
    finishing (killing it the instant the leader exits truncates that), and a
    descendant that ignores SIGTERM must not outlive the session (letting the
    leader's exit end the teardown orphaned it). ``owned_pgid`` comes from the
    OWNER — captured and validated at spawn — because it cannot be recovered
    here: polling the leader reaps it, and a reaped leader has no pid to read a
    group from.

    An immediate escalation costs no diagnostics: Godot's file logger flushes
    every error, and every print in a debug build (``core/io/logger.cpp``,
    ``application/run/flush_stdout_on_print.debug``).

    A killed child is still collected — rather than left with no ``returncode``
    for whatever happens to poll it next — but off this clock, best-effort: see
    :func:`_reap_in_background`. What this function guarantees about the deadline
    is that it starts no fresh blocking wait after it; a synchronous call already
    in flight can still delay the return.
    """
    if owned_pgid is None:
        # No owner told us, so recover what can still be recovered — accurate for
        # a leader that has not been reaped, ``None`` once it has.
        owned_pgid = _capture_owned_pgid(proc)
    leader_running = proc.poll() is None
    if owned_pgid is not None or leader_running:
        # Group ownership is independent of leader liveness. A preceding
        # `alive()` or launch diagnostic may already have reaped the leader, but
        # its descendants still need the graceful signal before the deadline.
        _signal_engine(proc, owned_pgid, signal.SIGTERM)
    while time.monotonic() < deadline:
        # Polled rather than blocked on the leader: the leader exiting is not the
        # group being done, and blocking on it cannot observe the difference.
        # ``poll`` also reaps the leader, keeping its ``returncode`` honest.
        proc.poll()
        if not _group_standing(owned_pgid, proc):
            return
        time.sleep(min(_RETIRE_POLL, max(deadline - time.monotonic(), 0.0)))
    # The deadline arrived with the session still standing.
    if proc.poll() is None:
        _signal_engine(proc, owned_pgid, signal.SIGKILL)
        _reap_in_background(proc)
    elif owned_pgid is not None:
        try:
            os.killpg(owned_pgid, signal.SIGKILL)
        except OSError:
            pass  # already empty: nothing left to retire


def _group_standing(owned_pgid: Optional[int], proc: subprocess.Popen) -> bool:
    """Whether anything gda owns for this session is still running."""
    if owned_pgid is None:
        return proc.poll() is None
    try:
        os.killpg(owned_pgid, 0)
    except ProcessLookupError:
        return False  # no members left
    except OSError:
        # Permission and transient signal failures do not prove absence. Waiting
        # to the existing deadline is safer than declaring a live group empty.
        return True
    return True


def _capture_owned_pgid(proc: subprocess.Popen) -> Optional[int]:
    """The process-group id led and owned by ``proc``, or ``None``.

    ``None`` when the leader is already reaped (its pid, and so its group id, is
    gone), when ``proc`` is only a member of somebody else's group, and when the
    group turns out to be gda's OWN. Only ``pgid == pid`` proves the ownership
    established by ``Popen(start_new_session=True)``; signalling any other group
    could terminate unrelated processes.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        return None
    return pgid if pgid == proc.pid and pgid != os.getpgrp() else None


def _signal_engine(proc: subprocess.Popen, owned_pgid: Optional[int], sig: int) -> None:
    """Signal the engine's whole process group, or the child alone if it has none."""
    if owned_pgid is not None:
        try:
            os.killpg(owned_pgid, sig)
            return
        except OSError:
            pass
    try:
        proc.terminate() if sig == signal.SIGTERM else proc.kill()
    except OSError:
        pass


def _reap_in_background(proc: subprocess.Popen) -> "threading.Thread":
    """Collect a SIGKILL'd child off the caller's clock (#725 re-review).

    The escalation is reached with the budget already spent, so waiting here — even
    briefly — is time the caller did not agree to and, in the daemon, time every
    queued request waits too: a fixed half-second allowance turned a 0.01s-bounded
    `wait-ready` into 0.5s. But a child that is never collected stays a zombie with
    no ``returncode``, so the duty is not dropped either: one short-lived thread
    owns the collection and this function returns at once.

    BEST-EFFORT, deliberately. The thread is a daemon thread — a killed engine must
    never keep gda alive — so it is not drained at shutdown, and a collection that
    fails is swallowed rather than reported. Giving it a managed lifecycle would buy
    a guarantee nothing needs: SIGKILL cannot be caught, so the wait ends on its own
    in every case anyone has observed, and the cost of a rare miss is one process-table
    entry — when the daemon exits, the child is reparented to init and reaped there.
    """
    reaper = threading.Thread(
        target=_reap, args=(proc,), name=f"gda-reap-{proc.pid}", daemon=True
    )
    reaper.start()
    return reaper


def _reap(proc: subprocess.Popen) -> None:
    try:
        proc.wait()
    except (OSError, subprocess.SubprocessError):
        # Nothing left to do about a child that cannot be collected, and a
        # traceback out of a daemon thread would land in the daemon's output.
        pass
