"""The LIVE execution channel: a daemon IPC client (ADR-0017, ADR-0021).

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

import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from gda.daemon.discovery import DaemonPaths, daemon_paths, daemon_pid
from gda.daemon.protocol import (
    LIVE_REQUEST_TIMEOUT,
    error_reply,
    read_message,
    write_message,
)
from gda.daemon.transport import connect_control
from gda.core.engine.launch import GodotRunner, RunResult
from gda.core.engine.execution import ExecutionKind, live_stack_constraints


def _is_unix() -> bool:
    return os.name == "posix"


def make_daemon_runner(project: Optional[Path]) -> GodotRunner:
    """Build the LIVE runner for ``project`` — the daemon-channel runner factory."""
    return DaemonRunner(project)


@dataclass
class DaemonRunner:
    """A :class:`~gda.core.engine.launch.GodotRunner` that serves a live op via gda-daemon."""

    project: Optional[Path]

    def run(self, operation: str, params: dict) -> RunResult:
        # Gate the operation's verified platforms before project/daemon lookup.
        constraints = live_stack_constraints(ExecutionKind.LIVE, operation)
        allows_windows = constraints is not None and "windows" in constraints[0]
        if not _is_unix() and not (sys.platform == "win32" and allows_windows):
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
        if sys.platform == "win32":
            return self._request(paths.cli_socket, operation, params, paths=paths)
        return self._request(paths.cli_socket, operation, params)

    def _request(
        self,
        cli_socket: Path,
        operation: str,
        params: dict,
        *,
        paths: DaemonPaths | None = None,
    ) -> RunResult:
        try:
            deadline = time.monotonic() + LIVE_REQUEST_TIMEOUT
            connection = (
                connect_control(paths, deadline)
                if paths is not None
                else socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            )
            with connection as sock:
                # An absolute instant, so the ceiling covers the WHOLE round
                # trip (#725 re-review). A socket timeout bounds each recv, and
                # the reply arrives in as many as the daemon sends — so 60s of
                # socket timeout was 60s of inactivity, not 60s of waiting.
                if paths is None:
                    sock.settimeout(LIVE_REQUEST_TIMEOUT)
                    sock.connect(str(cli_socket))
                write_message(sock, {"op": operation, "params": params}, deadline)
                reply = read_message(sock, deadline)
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
