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

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from gda.daemon.discovery import daemon_paths, daemon_pid
from gda.daemon.protocol import read_message, write_message
from gda.exit_codes import EXIT_LIVE
from gda.parser import RESULT_BEGIN, RESULT_END
from gda.runner import GodotRunner, RunResult

# Bounds a live call so it never hangs the CLI forever; generous because the
# daemon may launch the engine session on the first op (ADR-0017). A timeout is
# surfaced as the registered ``live_timeout`` (ADR-0021).
LIVE_REQUEST_TIMEOUT = 60.0


def _is_unix() -> bool:
    return os.name == "posix"


def make_daemon_runner(project: Optional[Path]) -> GodotRunner:
    """Build the LIVE runner for ``project`` — the daemon-channel runner factory."""
    return DaemonRunner(project)


@dataclass
class DaemonRunner:
    """A :class:`~gda.runner.GodotRunner` that serves a live op via gda-daemon."""

    project: Optional[Path]

    def run(self, operation: str, params: dict) -> RunResult:
        # Platform gate first (ADR-0021): live is UNIX-only (UDS), checked before
        # any project / daemon resolution and before any version concern.
        if not _is_unix():
            return _live_error_result(
                "live_unsupported_platform",
                "live operations require a UNIX platform (macOS/Linux); they use "
                "Unix domain sockets, which are unavailable here",
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
        if daemon_pid(paths) is None:
            return _live_error_result(
                "daemon_not_running",
                f"no gda-daemon is running for {self.project}; "
                "start one with `gda daemon start`",
            )
        return self._request(paths.cli_socket, operation, params)

    def _request(self, cli_socket: Path, operation: str, params: dict) -> RunResult:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(LIVE_REQUEST_TIMEOUT)
                sock.connect(str(cli_socket))
                write_message(sock, {"op": operation, "params": params})
                reply = read_message(sock)
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
    the SAME ADR-0002 envelope a real op error uses, so ``classify_live`` maps
    them to the registered code through the normal pipeline — no special path.
    """
    body = json.dumps({"error": {"code": code, "message": message}})
    return RunResult(stdout=f"{RESULT_BEGIN}{body}{RESULT_END}\n", stderr="", exit_code=EXIT_LIVE)
