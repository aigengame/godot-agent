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


@dataclass(frozen=True)
class ControlDeadlines:
    """The absolute deadlines of one admitted control connection.

    ``request`` bounds the request read and the reply to a control op;
    ``live_reply`` bounds the reply to a live operation. ``None`` is no deadline.
    """

    request: Optional[float]
    live_reply: Optional[float]


class HeldSlot(Protocol):
    """The daemon slot this process holds; closing it releases the slot."""

    def close(self) -> None: ...


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

    def acquire_slot(
        self, paths: DaemonPaths, pid: int, startup_deadline: Optional[float]
    ) -> HeldSlot:
        """Make the runtime directory usable and hold the daemon slot for ``pid``.

        The held slot is the daemon's mutual exclusion and its liveness signal
        (ADR-0021, ADR-0047). Raises ``OSError`` when another daemon holds it.
        ``startup_deadline`` is the readiness deadline that the spawning parent
        shares, or ``None``. An adapter whose start rolls back at that deadline
        raises ``TimeoutError`` once it has expired, and holds nothing.
        """
        ...

    def bind_endpoints(
        self, paths: DaemonPaths, pid: int, control_token: str
    ) -> tuple[socket.socket, socket.socket]:
        """Bind the CLI and harness listeners, publish them, and return them.

        A failure closes what this call bound.
        """
        ...

    def unpublish(self, paths: DaemonPaths) -> None:
        """Remove the daemon's on-disk record before the slot is released.

        The record is what :meth:`bind_endpoints` published, plus the slot
        record where the platform keeps one. The caller releases the slot after
        this returns, never before (#723).
        """
        ...

    def admit(
        self, conn: socket.socket, control_token: str
    ) -> Optional[ControlDeadlines]:
        """Admit one accepted CLI connection, or ``None`` to drop it."""
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
