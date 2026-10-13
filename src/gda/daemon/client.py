"""The daemon IPC client (ADR-0017, ADR-0021): the LIVE execution channel, and the
control round trip and owner check that the ``daemon`` lifecycle commands use.

A ``LIVE`` command's runner is a client of the per-project ``gda-daemon`` rather
than a one-shot ``godot`` subprocess. It returns the SAME ``RunResult`` shape a
headless subprocess returns — ``stdout`` carrying the ADR-0002 sentinel payload —
so classification, sentinel parsing, output-model validation, and ``--json`` /
``GdaError`` emission are reused unchanged (the dispatcher's one new decision is
which runner factory to use, keyed on the command's ``kind``).

With no running daemon (or no resolved project) the client synthesizes a
``daemon_not_running`` sentinel envelope — the attach-or-fail typed error that
makes the daemon's start timing self-revealing (ADR-0017). A dropped connection
becomes ``engine_disconnected``. Both ride the normal classify pipeline via
``classify_live``.
"""

import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from gda.daemon.discovery import (
    DaemonPaths,
    daemon_paths,
    daemon_pid,
    runtime_unusable_message,
)
from gda.daemon.protocol import (
    CONTROL_TIMEOUT,
    LIVE_REQUEST_TIMEOUT,
    error_reply,
    read_message,
    set_timeout_from_deadline,
    write_message,
)
from gda.daemon.windows_discovery import connect_control
from gda.core.engine.launch import GodotRunner, RunResult
from gda.core.engine.execution import ExecutionKind, live_stack_supported


def _connect(paths: DaemonPaths, deadline: float) -> socket.socket:
    """Connect to the daemon of ``paths`` within the absolute ``deadline``.

    Windows authenticates at the published loopback endpoint (ADR-0047). Unix
    connects to the CLI socket (ADR-0021).
    """
    if sys.platform == "win32":
        return connect_control(paths, deadline)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        set_timeout_from_deadline(sock, deadline)
        sock.connect(str(paths.cli_socket))
        return sock
    except BaseException:
        sock.close()
        raise


def _round_trip(paths: DaemonPaths, request: dict, deadline: float) -> Any | None:
    """Send one request frame and read its reply frame.

    The connect, the write and the read all spend the one absolute ``deadline``
    (#725 re-review). A socket timeout bounds each ``recv``, so a reply that
    arrives in many chunks would otherwise restart the bound on every chunk.
    """
    with _connect(paths, deadline) as sock:
        write_message(sock, request, deadline)
        return read_message(sock, deadline)


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


def control_outcome(
    paths: DaemonPaths, op: str, timeout: float | None = None
) -> ControlOutcome:
    """Send a control op (``__status__`` / ``__stop__``) and report its outcome.

    The default reply wait is the platform's owner rule, like :func:`owner_pid`.
    On Windows the authenticated reply is the only proof of the owner, and the
    daemon serves one connection at a time, so the wait is the live-request
    deadline: it outlasts one live request, and a daemon that does not answer
    within it is not merely busy (ADR-0047, #1162). On Unix the lock proves the
    owner and the reply is not read for it, so the wait is the control deadline.
    A caller that polls passes its own bound.

    A refused connection, or no published endpoint, is an outcome no daemon
    accepted. A deadline expiry, a dropped connection, a malformed reply or a
    reply that is not ``ok`` is an accepted outcome with no reply.
    """
    if timeout is None:
        timeout = LIVE_REQUEST_TIMEOUT if sys.platform == "win32" else CONTROL_TIMEOUT
    try:
        reply = _round_trip(paths, {"op": op}, time.monotonic() + timeout)
    except (ConnectionRefusedError, FileNotFoundError):
        return ControlOutcome(None, accepted=False)
    except (OSError, ValueError):
        return ControlOutcome(None)
    return ControlOutcome(
        reply if isinstance(reply, dict) and reply.get("ok") else None
    )


def control(
    paths: DaemonPaths, op: str, timeout: float | None = None
) -> Optional[dict]:
    """The ``ok`` reply of :func:`control_outcome`, or ``None``.

    For a caller that reads the reply and not the slot's state: the status read
    and the readiness poll.
    """
    return control_outcome(paths, op, timeout).reply


def owner_pid(reply: Optional[dict], pid: Optional[int]) -> Optional[int]:
    """The daemon pid that the platform's owner rule confirms, or ``None``.

    On Unix the pidfile lock proves the owner (ADR-0021), so the answer is
    ``pid`` and ``reply`` is not read. On Windows the :func:`control` reply must
    echo ``pid``, because only the authenticated reply proves that the
    discovered owner is the one that serves now (ADR-0047). A caller that reads
    the reply's fields checks ``reply`` itself: on Unix this answer is ``pid``
    for a ``None`` reply too.
    """
    if sys.platform == "win32" and (reply is None or reply.get("pid") != pid):
        return None
    return pid


def make_daemon_runner(project: Optional[Path]) -> GodotRunner:
    """Build the LIVE runner for ``project`` — the daemon-channel runner factory."""
    return DaemonRunner(project)


@dataclass
class DaemonRunner:
    """A :class:`~gda.core.engine.launch.GodotRunner` that serves a live op via gda-daemon."""

    project: Optional[Path]

    def run(self, operation: str, params: dict) -> RunResult:
        # Refuse a host the Live stack does not serve before project/daemon lookup.
        if not live_stack_supported(ExecutionKind.LIVE, operation):
            return _live_error_result(
                "live_unsupported_platform",
                "this Live operation is not supported on this platform",
            )
        if self.project is None:
            # No resolved project is a project-resolution error, not a daemon one
            # (ADR-0021): a live op is per-project, so there is no daemon to find.
            return _live_error_result(
                "project_not_found",
                "no Godot project resolved; a live operation needs a project "
                "(pass --project or run inside one)",
            )
        paths = daemon_paths(self.project)
        if sys.platform == "win32":
            try:
                pid = daemon_pid(paths)
            except OSError:
                return _live_error_result(
                    "daemon_runtime_unusable", runtime_unusable_message(paths)
                )
        else:
            pid = daemon_pid(paths)
        if pid is None:
            return _live_error_result(
                "daemon_not_running",
                f"no gda-daemon is running for {self.project}; "
                "start one with `gda daemon start`",
            )
        return self._request(paths, operation, params)

    def _request(self, paths: DaemonPaths, operation: str, params: dict) -> RunResult:
        try:
            # An absolute instant, so the ceiling covers the WHOLE round trip
            # (#725 re-review). A socket timeout bounds each recv, and the reply
            # arrives in as many as the daemon sends — so 60s of socket timeout
            # was 60s of inactivity, not 60s of waiting.
            reply = _round_trip(
                paths,
                {"op": operation, "params": params},
                time.monotonic() + LIVE_REQUEST_TIMEOUT,
            )
        except TimeoutError:
            return _live_error_result(
                "live_timeout",
                f"the live operation did not return within {int(LIVE_REQUEST_TIMEOUT)}s",
            )
        except OSError:
            return _live_error_result(
                "engine_disconnected",
                "the gda-daemon connection dropped before the live operation returned",
            )
        if reply is None:
            return _live_error_result(
                "engine_disconnected",
                "the gda-daemon closed the connection before replying",
            )
        # The daemon relays the engine session's sentinel payload verbatim as the
        # RunResult fields; classify_live / parse_result handle it like any op.
        return RunResult(
            stdout=str(reply.get("stdout", "")),
            stderr=str(reply.get("stderr", "")),
            exit_code=int(reply.get("exit_code", 0)),
        )


def _live_error_result(code: str, message: str) -> RunResult:
    """A synthesized RunResult carrying a LIVE error envelope in the sentinel.

    The client surfaces its own failures (no daemon, dropped connection) through
    the SAME ADR-0002 envelope a real op error uses — built once by
    :func:`gda.daemon.protocol.error_reply` (the daemon synthesizes the identical
    reply dict) — so ``classify_live`` maps them to the registered code through the
    normal pipeline, no special path.
    """
    return RunResult(**error_reply(code, message))
