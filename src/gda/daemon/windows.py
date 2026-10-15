"""The Windows adapter of the daemon platform seam (ADR-0047, #1189).

A thin adapter over :mod:`gda.daemon.windows_discovery` (the lock file, the
private endpoint record and the control authentication) and
:mod:`gda.daemon.windows_process` (the owned engine session process). The
modules it wraps keep their own "requires Windows" guards.
"""

from __future__ import annotations

import socket
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import BinaryIO

from gda.daemon import win32, windows_discovery
from gda.daemon.discovery import DaemonPaths, runtime_unusable_message
from gda.daemon.platform import (
    HOME_RUNTIME_DIR,
    ControlDeadlines,
    ControlOutcome,
    RuntimeUnusable,
    SessionSpawnFailed,
    SlotVerdict,
)
from gda.daemon.protocol import CONTROL_TIMEOUT, LIVE_REQUEST_TIMEOUT
from gda.daemon.windows_discovery import (
    LOOPBACK_HOST,
    acquire_harness_lock,
    acquire_lock,
    authenticate_control,
    connect_control,
    ensure_private_runtime,
    lock_held,
    read_endpoint,
    remove_endpoint,
)
from gda.daemon.windows_process import WindowsProcess


class WindowsPlatform:
    """Loopback TCP with authentication, a lock file and an owned job object."""

    def runtime_dir(self, env: Mapping[str, str]) -> Path:
        # ``%LOCALAPPDATA%\gda\run``, else the same per-user fallback as Unix.
        local = env.get("LOCALAPPDATA")
        if local:
            return Path(local) / "gda" / "run"
        return Path(HOME_RUNTIME_DIR).expanduser()

    def check_runtime(self, paths: DaemonPaths) -> None:
        # Every slot read checks the directory's privacy (ADR-0047), so a
        # directory that cannot serve is refused before any daemon state is read.
        if not paths.runtime_dir.exists():
            return
        try:
            ensure_private_runtime(paths.runtime_dir)
            self.daemon_pid(paths)
        except OSError:
            raise RuntimeUnusable(runtime_unusable_message(paths)) from None

    def prepare_runtime(self, paths: DaemonPaths) -> None:
        try:
            ensure_private_runtime(paths.runtime_dir)
        except OSError:
            raise RuntimeUnusable(runtime_unusable_message(paths)) from None

    def check_bindable(self, paths: DaemonPaths) -> None:
        # Loopback TCP has no path to bind.
        return None

    def daemon_pid(self, paths: DaemonPaths) -> int | None:
        """The endpoint record's pid while the slot lock is held, or ``None``.

        The record's pid is not a verified holder: only an authenticated control
        reply proves that the discovered owner is the one that serves now
        (ADR-0047). Reading the record verifies the runtime directory's privacy,
        so an ``OSError`` here is a runtime directory that is not private or not
        usable.
        """
        endpoint = read_endpoint(paths)
        return endpoint.pid if endpoint is not None and lock_held(paths) else None

    def acquire_slot(
        self, paths: DaemonPaths, pid: int, startup_deadline: float | None
    ) -> BinaryIO:
        # The lock makes the runtime directory private, or refuses it, first.
        slot = acquire_lock(paths)
        # The parent and child share the original readiness deadline. A
        # delayed child must not publish after its parent has rolled back.
        # It owns no metadata yet, so it releases the lock and nothing else.
        if startup_deadline is not None and time.monotonic() >= startup_deadline:
            slot.close()
            raise TimeoutError("the Windows daemon startup deadline expired")
        return slot

    def slot_verdict(
        self,
        paths: DaemonPaths,
        existing: int | None,
        ask: Callable[[], ControlOutcome],
    ) -> SlotVerdict | None:
        # ``existing`` is the endpoint record's pid while the slot is held, not a
        # verified holder (ADR-0047). A held slot with no record, or with one at
        # which no daemon accepts a connection, is another lifecycle operation in
        # progress. Only the authenticated reply proves the owner.
        if existing is None:
            return SlotVerdict.HELD_WITHOUT_DAEMON if lock_held(paths) else None
        answer = ask()
        if self.owner_pid(answer.reply, existing) is not None:
            return None
        if not answer.accepted:
            return SlotVerdict.HELD_WITHOUT_DAEMON
        return SlotVerdict.UNRESPONSIVE

    def settle_stop(self, paths: DaemonPaths, pid: int, overdue: bool) -> bool:
        # No unauthenticated PID-based termination of a native owner (ADR-0047).
        return self.daemon_pid(paths) != pid

    def bind_endpoints(
        self, paths: DaemonPaths, pid: int, control_token: str
    ) -> tuple[socket.socket, socket.socket]:
        cli = _bind_tcp()
        try:
            harness = _bind_tcp()
            try:
                # Called through the module, which a process can replace to
                # hold the publication (the successor e2e test does).
                windows_discovery.publish_endpoint(
                    paths,
                    pid,
                    cli.getsockname()[1],
                    harness.getsockname()[1],
                    control_token,
                )
            except BaseException:
                harness.close()
                raise
        except BaseException:
            cli.close()
            raise
        return cli, harness

    def unpublish(self, paths: DaemonPaths) -> None:
        # The lock file is stable; only the endpoint record goes.
        remove_endpoint(paths)

    def socket_path(self, paths: DaemonPaths) -> str | None:
        # The endpoint record is published instead.
        return None

    def endpoint_address(self, paths: DaemonPaths) -> tuple[str, int] | None:
        endpoint = read_endpoint(paths)
        return None if endpoint is None else (LOOPBACK_HOST, endpoint.cli_port)

    def admit(self, conn: socket.socket, control_token: str) -> ControlDeadlines | None:
        # Any local process can reach a loopback port, so a connection must
        # present the token first (ADR-0047).
        live_reply = time.monotonic() + LIVE_REQUEST_TIMEOUT
        request = time.monotonic() + CONTROL_TIMEOUT
        if not authenticate_control(conn, control_token, request):
            return None
        return ControlDeadlines(request, live_reply)

    @property
    def control_timeout(self) -> float:
        # The authenticated reply is the only proof of the owner, and the daemon
        # serves one connection at a time, so the wait outlasts one live request:
        # a daemon that does not answer within it is not merely busy (#1162).
        return LIVE_REQUEST_TIMEOUT

    def connect(self, paths: DaemonPaths, deadline: float) -> socket.socket:
        # Authenticated at the published loopback endpoint (ADR-0047).
        return connect_control(paths, deadline)

    def owner_pid(self, reply: dict | None, pid: int | None) -> int | None:
        # Only the authenticated reply proves that the discovered owner is the
        # one that serves now (ADR-0047), so the reply must echo ``pid``.
        if reply is None or reply.get("pid") != pid:
            return None
        return pid

    def spawn_daemon(self, argv: list[str]) -> None:
        # No console, no share in the caller's Ctrl+C, and out of the caller's
        # job, so the daemon outlives the caller.
        subprocess.Popen(
            argv,
            creationflags=win32.DETACHED_PROCESS
            | win32.CREATE_NEW_PROCESS_GROUP
            | win32.CREATE_BREAKAWAY_FROM_JOB,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def launch_failure(self, error: OSError) -> str:
        clause = f"Windows daemon launch failed: {error}"
        if getattr(error, "winerror", None) == win32.ERROR_ACCESS_DENIED:
            clause += "; the host must permit Job breakaway for detached startup"
        return clause

    def harness_transaction(
        self, paths: DaemonPaths, timeout: float
    ) -> AbstractContextManager[object]:
        # A lock byte the daemon does not hold, so it can become ready inside
        # the transaction (ADR-0047).
        try:
            return acquire_harness_lock(paths, timeout)
        except TimeoutError:
            raise
        except OSError:
            raise RuntimeUnusable(runtime_unusable_message(paths)) from None

    def hold_slot_for_rollback(
        self, paths: DaemonPaths, pending_until: float | None
    ) -> AbstractContextManager[object]:
        # Taken now, so that an owner that holds the slot keeps the install.
        return _slot_until(acquire_lock(paths), pending_until)

    def spawn_session(self, argv: list[str], deadline: float) -> WindowsProcess:
        try:
            return WindowsProcess(argv, deadline)
        except OSError as error:
            raise SessionSpawnFailed(
                f"Windows engine startup failed: {error}"
            ) from error

    def harness_argument(
        self, harness_listener: socket.socket, harness_socket: Path
    ) -> str:
        return f"tcp://{LOOPBACK_HOST}:{harness_listener.getsockname()[1]}"

    @property
    def other_processes_reach_harness(self) -> bool:
        # Any local process can connect to a loopback port (ADR-0047).
        return True


@contextmanager
def _slot_until(slot: BinaryIO, pending_until: float | None) -> Iterator[BinaryIO]:
    # A child can still be pending when startup is interrupted or readiness
    # raises early. Keep its slot until the deadline, so it cannot publish after
    # the rollback. This adds no fresh budget.
    with slot:
        if pending_until is not None:
            while (remaining := pending_until - time.monotonic()) > 0:
                time.sleep(remaining)
        yield slot


def _bind_tcp() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((LOOPBACK_HOST, 0))
        sock.listen()
        return sock
    except BaseException:
        sock.close()
        raise
