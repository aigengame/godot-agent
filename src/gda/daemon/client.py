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

from gda.daemon.discovery import DaemonPaths, daemon_paths, daemon_pid
from gda.daemon.protocol import (
    CONTROL_TIMEOUT,
    LIVE_REQUEST_TIMEOUT,
    error_reply,
    read_message,
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
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("the control deadline has expired")
        sock.settimeout(left)
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


def control(
    paths: DaemonPaths, op: str, timeout: float = CONTROL_TIMEOUT
) -> Optional[dict]:
    """Send a control op (``__status__`` / ``__stop__``) and return the reply.

    A connection failure, a deadline expiry or a malformed reply is ``None``.
    """
    try:
        reply = _round_trip(paths, {"op": op}, time.monotonic() + timeout)
    except (OSError, ValueError):
        return None
    return reply if isinstance(reply, dict) else None


def owner_pid(reply: Optional[dict], pid: Optional[int]) -> Optional[int]:
    """The daemon pid that the control ``reply`` confirms, or ``None``.

    An ``ok`` reply confirms the owner. On Windows the reply must also echo
    ``pid``, because only the authenticated reply proves that the discovered
    owner is the one that serves now (ADR-0047). On Unix the pidfile lock
    proves the owner (ADR-0021).
    """
    if pid is None or not reply or not reply.get("ok"):
        return None
    if sys.platform == "win32" and reply.get("pid") != pid:
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
        # Gate the operation's verified platforms before project/daemon lookup.
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
                    "daemon_not_running",
                    "the Windows daemon discovery is not private and usable",
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
