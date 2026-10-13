"""The Windows adapter of the daemon platform seam (ADR-0047, #1189).

A thin adapter over :mod:`gda.daemon.windows_discovery` (the lock file, the
private endpoint record and the control authentication) and
:mod:`gda.daemon.windows_process` (the owned engine session process). The
modules it wraps keep their own "requires Windows" guards.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO

from gda.daemon import windows_discovery
from gda.daemon.discovery import DaemonPaths, runtime_unusable_message
from gda.daemon.platform import HOME_RUNTIME_DIR, ControlDeadlines, RuntimeUnusable
from gda.daemon.protocol import CONTROL_TIMEOUT, LIVE_REQUEST_TIMEOUT
from gda.daemon.windows_discovery import (
    LOOPBACK_HOST,
    acquire_lock,
    authenticate_control,
    connect_control,
    lock_held,
    read_endpoint,
    remove_endpoint,
)


class WindowsPlatform:
    """Loopback TCP with authentication, a lock file and an owned job object."""

    def runtime_dir(self, env: Mapping[str, str]) -> Path:
        # ``%LOCALAPPDATA%\gda\run``, else the same per-user fallback as Unix.
        local = env.get("LOCALAPPDATA")
        if local:
            return Path(local) / "gda" / "run"
        return Path(HOME_RUNTIME_DIR).expanduser()

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

    def admit(self, conn: socket.socket, control_token: str) -> ControlDeadlines | None:
        # Any local process can reach a loopback port, so a connection must
        # present the token first (ADR-0047).
        live_reply = time.monotonic() + LIVE_REQUEST_TIMEOUT
        request = time.monotonic() + CONTROL_TIMEOUT
        if not authenticate_control(conn, control_token, request):
            return None
        return ControlDeadlines(request, live_reply)

    def find_daemon(self, paths: DaemonPaths) -> int | None:
        try:
            return self.daemon_pid(paths)
        except OSError:
            raise RuntimeUnusable(runtime_unusable_message(paths)) from None

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


def _bind_tcp() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((LOOPBACK_HOST, 0))
        sock.listen()
        return sock
    except BaseException:
        sock.close()
        raise
