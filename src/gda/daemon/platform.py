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

import socket
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Protocol

if TYPE_CHECKING:
    from gda.daemon.discovery import DaemonPaths

# The per-user fallback runtime directory of both adapters, when the platform's
# own location variable is not set.
HOME_RUNTIME_DIR = "~/.gda/run"


class RuntimeUnusable(Exception):
    """The daemon runtime directory cannot serve; the message is the refusal.

    The lifecycle operations and the Live client report it as
    ``daemon_runtime_unusable`` with this message.
    """


@dataclass(frozen=True)
class ControlOutcome:
    """What one control request learned at the daemon's published endpoint (#1162).

    ``reply`` is the ``ok`` reply, or ``None``. ``accepted`` is ``False`` when no
    daemon accepted the connection: nothing listens at the published endpoint, or
    none is published any more. Such a record is the leftover of a daemon that
    ended, or precedes the daemon that holds the slot, and is not the address of
    one that serves: a process the OS ended ran no cleanup, a retiring daemon
    closes its listeners before it removes its record, and the next slot owner
    publishes its own record only after it binds. A daemon that accepted the
    connection and then did not answer is ``accepted`` with no ``reply``.
    """

    reply: Optional[dict]
    accepted: bool = True


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

    def find_daemon(self, paths: DaemonPaths) -> Optional[int]:
        """:meth:`daemon_pid` for a Live request.

        Raises :class:`RuntimeUnusable` where the platform reads the slot through
        a privacy check of the runtime directory and that check refuses it.
        """
        ...

    @property
    def control_timeout(self) -> float:
        """The default wait for the reply to one control request."""
        ...

    def connect(self, paths: DaemonPaths, deadline: float) -> socket.socket:
        """Connect to the daemon of ``paths`` within the absolute ``deadline``."""
        ...

    def owner_pid(self, reply: Optional[dict], pid: Optional[int]) -> Optional[int]:
        """The daemon pid that the platform's owner rule confirms, or ``None``.

        A caller that reads the reply's fields checks ``reply`` itself: where the
        rule does not read the reply, the answer is ``pid`` for a ``None`` reply
        too.
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
