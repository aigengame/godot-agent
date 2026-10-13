"""The platform seam of gda-daemon (ADR-0047, #1189).

The daemon needs operations whose implementation differs by host: where its
runtime directory is and how it is made private, how the daemon slot is held and
read, how the endpoints are bound and published, how a control connection is
made and admitted, how an engine session process is spawned and retired, and
which argument tells the harness where to connect. :class:`DaemonPlatform` states
them. Two adapters satisfy it: :mod:`gda.daemon.unix` (Unix domain sockets and a
pidfile lock, ADR-0021) and :mod:`gda.daemon.windows` (loopback TCP, a lock file
and an owned job object, ADR-0047).

:func:`host_platform` is the one selection. The server, the client, the session
launch and the daemon lifecycle operations each call it once, where they are
built, and pass the adapter on. The seam selects an implementation. It does not
decide support: ``live_stack_constraints`` alone states which hosts the Live
stack serves (ADR-0047).
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Protocol

if TYPE_CHECKING:
    from gda.daemon.discovery import DaemonPaths

# The per-user fallback runtime directory of both adapters, when the platform's
# own location variable is not set.
HOME_RUNTIME_DIR = "~/.gda/run"


class DaemonPlatform(Protocol):
    """The platform operations gda-daemon needs; one adapter per host family."""

    def runtime_dir(self, env: Mapping[str, str]) -> Path:
        """The per-user directory that holds the daemon's on-disk identity."""
        ...

    def daemon_pid(self, paths: DaemonPaths) -> Optional[int]:
        """The pid of the daemon that holds the slot of ``paths``, or ``None``.

        Raises ``OSError`` when the slot state cannot be read.
        """
        ...


def host_platform() -> DaemonPlatform:
    """The adapter for this host: Windows on a Windows host, Unix elsewhere.

    The one ``sys.platform`` read that chooses a daemon implementation. Each
    process calls it where it builds a server, a client, a session launch or a
    lifecycle operation, and passes the result on.
    """
    if sys.platform == "win32":
        from gda.daemon.windows import WindowsPlatform

        return WindowsPlatform()
    from gda.daemon.unix import UnixPlatform

    return UnixPlatform()
