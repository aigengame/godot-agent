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
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from gda.daemon.discovery import daemon_paths, daemon_pid
from gda.daemon.protocol import read_message, write_message
from gda.exit_codes import EXIT_LIVE
from gda.parser import RESULT_BEGIN, RESULT_END
from gda.runner import GodotRunner, RunResult


def make_daemon_runner(project: Optional[Path]) -> GodotRunner:
    """Build the LIVE runner for ``project`` — the daemon-channel runner factory."""
    return DaemonRunner(project)


@dataclass
class DaemonRunner:
    """A :class:`~gda.runner.GodotRunner` that serves a live op via gda-daemon."""

    project: Optional[Path]

    def run(self, operation: str, params: dict) -> RunResult:
        if self.project is None:
            # A live op is per-project; with no resolved project there is no
            # daemon to find (ADR-0021). Attach-or-fail, naming the remediation.
            return _live_error_result(
                "daemon_not_running",
                "no Godot project resolved; a live operation needs a project with a "
                "running gda-daemon (start one with `gda daemon start`)",
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
                sock.connect(str(cli_socket))
                write_message(sock, {"op": operation, "params": params})
                reply = read_message(sock)
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
