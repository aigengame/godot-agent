"""The platform seam of gda-daemon (ADR-0047, #1189).

The daemon needs operations whose implementation differs by host: where its
runtime directory is and how it is made private, how the daemon slot is held and
read and what a held slot or a stop means, how the endpoints are bound and
published, how a control connection is made and admitted, how the daemon and its
engine session processes are started, how a session process is retired, which
argument tells the harness where to connect, and what a daemon lifecycle
operation holds while it changes the project or rolls a failed start back.
:class:`DaemonPlatform` states them. Two adapters satisfy it:
:mod:`gda.daemon.unix` (Unix domain sockets and a pidfile lock, ADR-0021) and
:mod:`gda.daemon.windows` (loopback TCP, a lock file and an owned job object,
ADR-0047).

:func:`gda.daemon.host.host_platform` is the one selection. The daemon entry
point, the Live client and each daemon lifecycle operation take the adapter from
it and pass it on. The seam selects an implementation. It does not decide
support: ``live_stack_constraints`` alone states which hosts the Live stack
serves (ADR-0047).
"""

from __future__ import annotations

import enum
import socket
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
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


class SlotReadTransient(PermissionError):
    """Another process held the slot state for a moment, so a read was denied.

    A later read can succeed. The readiness wait reads it as not ready yet, and
    the stop wait as still held (#1227).
    """


class SessionSpawnFailed(Exception):
    """The engine session process could not start; the message is the reason.

    The session launch records the message as its launch-failure reason.
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


class SlotVerdict(enum.Enum):
    """Why a held daemon slot does not hold a daemon that serves (#1162).

    ``HELD_WITHOUT_DAEMON``: another lifecycle operation holds the slot, and no
    daemon accepts a connection at the published endpoint, or none is published.
    ``UNRESPONSIVE``: the process the endpoint names accepted the status request
    and did not answer as the daemon.
    """

    HELD_WITHOUT_DAEMON = "held_without_daemon"
    UNRESPONSIVE = "unresponsive"


class HeldSlot(Protocol):
    """The daemon slot this process holds; closing it releases the slot."""

    def close(self) -> None: ...


class SessionProcess(Protocol):
    """The engine session process that a daemon owns."""

    @property
    def pid(self) -> int: ...

    @property
    def returncode(self) -> Optional[int]: ...

    def poll(self) -> Optional[int]:
        """The exit status, or ``None`` while the process runs."""
        ...

    def retire(self, deadline: float) -> None:
        """End the process and what it started, by the absolute ``deadline``."""
        ...


class DaemonPlatform(Protocol):
    """The platform operations gda-daemon needs; one adapter per host family."""

    def runtime_dir(self, env: Mapping[str, str]) -> Path:
        """The per-user directory that holds the daemon's on-disk identity."""
        ...

    def check_runtime(self, paths: DaemonPaths) -> None:
        """Refuse a runtime directory that exists and cannot serve.

        Raises :class:`RuntimeUnusable`. A directory that does not exist passes.
        """
        ...

    def prepare_runtime(self, paths: DaemonPaths) -> None:
        """Make the runtime directory usable before a start changes the project.

        Raises :class:`RuntimeUnusable` when it cannot.
        """
        ...

    def check_bindable(self, paths: DaemonPaths) -> None:
        """Refuse endpoints of ``paths`` that the daemon cannot bind.

        Raises :class:`RuntimeUnusable`. A start asks before it does anything else.
        """
        ...

    def daemon_pid(self, paths: DaemonPaths) -> Optional[int]:
        """The pid of the daemon that holds the slot of ``paths``, or ``None``.

        Raises ``OSError`` when the slot state cannot be read, and
        :class:`SlotReadTransient` when another process held it for a moment.
        """
        ...

    def acquire_slot(
        self, paths: DaemonPaths, pid: int, startup_deadline: Optional[float]
    ) -> HeldSlot:
        """Make the runtime directory usable and hold the daemon slot for ``pid``.

        The held slot is the daemon's mutual exclusion and its liveness signal
        (ADR-0021, ADR-0047). Raises ``OSError`` when another daemon holds it.
        ``startup_deadline`` is the readiness deadline that the spawning parent
        shares, or ``None``. An adapter whose failed start holds the slot until
        that deadline (:meth:`hold_slot_for_rollback`) raises ``TimeoutError``
        once it has expired, and holds nothing.
        """
        ...

    def slot_verdict(
        self,
        paths: DaemonPaths,
        existing: Optional[int],
        ask: Callable[[], ControlOutcome],
    ) -> Optional[SlotVerdict]:
        """Why the slot that :meth:`daemon_pid` read as ``existing`` does not serve.

        ``None`` when ``existing`` is the answer: the pid of the daemon that
        serves, or ``None`` for a free slot. ``ask`` gives the outcome of one
        control request to the published endpoint. A platform whose slot proves
        its owner does not call it.
        """
        ...

    def settle_stop(self, paths: DaemonPaths, pid: int, overdue: bool) -> bool:
        """Settle a stop that ``pid`` acknowledged; ``False`` when it did not take.

        ``overdue`` is true when ``pid`` still held the slot at the stop deadline.
        A platform that ends an overdue daemon by its pid does that here and
        reports the stop as done.
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

    def socket_path(self, paths: DaemonPaths) -> Optional[str]:
        """The published CLI socket path, or ``None`` where the platform has none."""
        ...

    def endpoint_address(self, paths: DaemonPaths) -> Optional[tuple[str, int]]:
        """The host and port of the published CLI endpoint, or ``None``.

        ``None`` where the platform publishes a socket path, or where no endpoint
        is published.
        """
        ...

    def admit(
        self, conn: socket.socket, control_token: str
    ) -> Optional[ControlDeadlines]:
        """Admit one accepted CLI connection, or ``None`` to drop it."""
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

    def spawn_daemon(self, argv: list[str]) -> None:
        """Start the daemon process detached from the caller, with no std streams.

        Raises ``OSError`` when the process does not start.
        """
        ...

    def launch_failure(self, error: OSError) -> str:
        """The clause that names a daemon start's ``error`` in its failure message."""
        ...

    def harness_transaction(
        self, paths: DaemonPaths, timeout: float
    ) -> AbstractContextManager[object]:
        """What a start, install or uninstall holds while it changes the project.

        The call takes it, and the exit of the context releases it. Raises
        ``TimeoutError`` when another lifecycle operation holds it past
        ``timeout``, and :class:`RuntimeUnusable` when the runtime directory
        cannot serve it.
        """
        ...

    def hold_slot_for_rollback(
        self, paths: DaemonPaths, pending_until: Optional[float]
    ) -> AbstractContextManager[object]:
        """What a failed start holds while it rolls its harness install back.

        ``pending_until`` is the readiness deadline of a child that the start
        spawned, or ``None``. A platform whose child checks that deadline before
        it publishes holds the daemon slot from the call until the deadline, so
        the child cannot publish after the rollback. Raises ``OSError`` when
        another owner holds the slot; the start then keeps its install.
        """
        ...

    def spawn_session(self, argv: list[str], deadline: float) -> SessionProcess:
        """Start an engine session process.

        Raises :class:`SessionSpawnFailed` for a start failure that the launch
        reports as its reason.
        """
        ...

    def harness_argument(
        self, harness_listener: socket.socket, harness_socket: Path
    ) -> str:
        """The launch argument that tells the harness where to connect."""
        ...

    @property
    def other_processes_reach_harness(self) -> bool:
        """Whether a process that is not the engine can reach the harness endpoint.

        When it can, the launch drops a peer that presents a wrong token and
        accepts the next connection until its deadline.
        """
        ...
