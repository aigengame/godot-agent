"""The gda-daemon server: the per-project Unix-domain-socket broker (ADR-0017).

A long-lived process that binds the project's CLI socket, records its pidfile,
and serves one request at a time off the socket — single-writer serialization of
live operations against the session it holds (ADR-0020). Two control ops manage
its lifetime (``__status__`` liveness, ``__stop__`` graceful shutdown); any other
op is a project live op.

This slice (the daemon bootstrap, 6a) holds **no** engine session yet, so a live
op returns ``engine_session_not_running`` through the normal ADR-0002 sentinel
reply; launching and brokering the session is the next slice.
"""

import json
import os
import signal
import socket

from gda.daemon.discovery import DaemonPaths, ensure_runtime_dir, write_pidfile
from gda.daemon.protocol import read_message, write_message
from gda.exit_codes import EXIT_LIVE
from gda.parser import RESULT_BEGIN, RESULT_END

# Control ops on the CLI socket — daemon lifetime, not project domain ops.
STATUS_OP = "__status__"
STOP_OP = "__stop__"


class DaemonServer:
    """Binds the per-project CLI socket and serves requests until stopped."""

    def __init__(self, paths: DaemonPaths) -> None:
        self.paths = paths
        self._stopping = False
        self._listener: socket.socket | None = None

    def serve(self) -> None:
        ensure_runtime_dir(self.paths)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # Reclaim a stale socket a crashed predecessor may have left bound.
        try:
            os.unlink(self.paths.cli_socket)
        except FileNotFoundError:
            pass
        listener.bind(str(self.paths.cli_socket))
        listener.listen()
        self._listener = listener
        write_pidfile(self.paths, os.getpid())

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._on_signal)

        try:
            self._accept_loop()
        finally:
            self._cleanup()

    def _on_signal(self, signum: int, frame: object) -> None:
        # Closing the listener unblocks a pending accept(); the loop then exits.
        self._stopping = True
        if self._listener is not None:
            self._listener.close()

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stopping:
            try:
                conn, _ = self._listener.accept()
            except OSError:
                break  # listener closed by a signal
            with conn:
                request = read_message(conn)
                if request is not None:
                    reply = self._handle(request)
                    if reply is not None:
                        write_message(conn, reply)
            if self._stopping:
                break

    def _handle(self, request: dict) -> dict | None:
        op = request.get("op")
        if op == STATUS_OP:
            return {"ok": True, "pid": os.getpid()}
        if op == STOP_OP:
            self._stopping = True
            return {"ok": True, "pid": os.getpid()}
        # A project live op. No engine session is held in this slice, so report it
        # through the normal sentinel pipeline (classify_live maps the code).
        return _op_error_reply(
            "engine_session_not_running",
            "the gda-daemon holds no live engine session yet",
        )

    def _cleanup(self) -> None:
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        for path in (
            self.paths.cli_socket,
            self.paths.harness_socket,
            self.paths.pidfile,
        ):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass


def _op_error_reply(code: str, message: str) -> dict:
    """A CLI reply carrying a LIVE error envelope as the ADR-0002 sentinel payload."""
    body = json.dumps({"error": {"code": code, "message": message}})
    return {
        "stdout": f"{RESULT_BEGIN}{body}{RESULT_END}\n",
        "stderr": "",
        "exit_code": EXIT_LIVE,
    }
