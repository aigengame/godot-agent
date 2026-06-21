"""The gda-daemon server: the per-project Unix-domain-socket broker (ADR-0017).

A long-lived process that binds the project's CLI socket (for the CLI) and harness
socket (for the engine session's harness), records its pidfile, and serves one
request at a time — single-writer serialization of live operations against the one
session it holds (ADR-0020). Two control ops manage its lifetime (``__status__``
liveness, ``__stop__`` graceful shutdown); any other op is a project live op,
served by the engine session, which is (re)launched lazily on demand.
"""

import json
import os
import secrets
import signal
import socket

from gda.daemon.discovery import DaemonPaths, acquire_pidfile, ensure_runtime_dir
from gda.daemon.protocol import read_message, write_message
from gda.daemon.session import EngineSession, launch_session
from gda.exit_codes import EXIT_LIVE
from gda.parser import RESULT_BEGIN, RESULT_END

# Control ops on the CLI socket — daemon lifetime, not project domain ops.
STATUS_OP = "__status__"
STOP_OP = "__stop__"


class DaemonServer:
    """Binds the per-project sockets and serves requests until stopped."""

    def __init__(self, paths: DaemonPaths, godot: str = "") -> None:
        self.paths = paths
        self.godot = godot
        self._token = secrets.token_hex(16)
        self._stopping = False
        self._listener: socket.socket | None = None
        self._harness_listener: socket.socket | None = None
        self._session: EngineSession | None = None
        self._pidfile_handle = None

    def serve(self) -> None:
        ensure_runtime_dir(self.paths)
        self._listener = self._bind(self.paths.cli_socket)
        self._harness_listener = self._bind(self.paths.harness_socket)
        # Hold the pidfile's advisory lock for our lifetime — that held lock is the
        # liveness signal the CLI keys on (ADR-0021); bind first so the socket is
        # present before we are reported live.
        self._pidfile_handle = acquire_pidfile(self.paths, os.getpid())

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._on_signal)

        try:
            self._accept_loop()
        finally:
            self._cleanup()

    @staticmethod
    def _bind(path) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # Reclaim a stale socket a crashed predecessor may have left bound.
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        sock.bind(str(path))
        sock.listen()
        return sock

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
        # A project live op. Serialized against the one session (single writer).
        session = self._ensure_session()
        if session is None:
            return _op_error_reply(
                "engine_session_not_running",
                "the gda-daemon could not launch an engine session (no Godot binary, "
                "or the harness did not connect)",
            )
        return session.request(op, request.get("params", {}))

    def _ensure_session(self) -> EngineSession | None:
        if self._session is not None and self._session.alive():
            return self._session
        if self._session is not None:
            self._session.close()
            self._session = None
        if not self.godot:
            return None
        assert self._harness_listener is not None
        self._session = launch_session(
            self.paths.project,
            self.godot,
            self._harness_listener,
            self.paths.harness_socket,
            self._token,
        )
        return self._session

    def _cleanup(self) -> None:
        if self._session is not None:
            self._session.close()
        if self._pidfile_handle is not None:
            try:
                self._pidfile_handle.close()  # releases the advisory lock
            except OSError:
                pass
        for sock in (self._listener, self._harness_listener):
            if sock is not None:
                try:
                    sock.close()
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
