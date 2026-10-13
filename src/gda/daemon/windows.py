"""The Windows adapter of the daemon platform seam (ADR-0047, #1189).

A thin adapter over :mod:`gda.daemon.windows_discovery` (the lock file, the
private endpoint record and the control authentication) and
:mod:`gda.daemon.windows_process` (the owned engine session process). The
modules it wraps keep their own "requires Windows" guards.
"""

from __future__ import annotations

import socket
from collections.abc import Mapping
from pathlib import Path

from gda.daemon.discovery import DaemonPaths, runtime_unusable_message
from gda.daemon.platform import HOME_RUNTIME_DIR, RuntimeUnusable
from gda.daemon.protocol import LIVE_REQUEST_TIMEOUT
from gda.daemon.windows_discovery import connect_control, lock_held, read_endpoint


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
