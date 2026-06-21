"""The engine session gda-daemon holds for live operations (ADR-0017).

A transient gda-owned Godot run with the gda harness injected. The daemon listens
on the harness socket, launches the engine with the launch marker + the harness
socket path + an auth token (the args after ``--``), waits for the harness to
connect back over ``StreamPeerUDS`` and present the token, then relays one live op
at a time to it and returns the sentinel payload it replies with.

The session runs ``--headless`` for the tracer op (``game tree`` reads the runtime
``SceneTree`` and needs no viewport); a windowed session arrives with the first
viewport-capturing op (ADR-0017). The session is (re)launched per feedback-loop
iteration so it observes the project's current on-disk state.
"""

import json
import os
import signal
import socket
import subprocess
from pathlib import Path
from typing import Optional

from gda.daemon.protocol import read_frame, write_message
from gda.exit_codes import EXIT_LIVE
from gda.parser import RESULT_BEGIN, RESULT_END

LAUNCH_MARKER = "gda-daemon"
# Engine boot + autoload + harness connect; a windowed/cold start can be slow.
CONNECT_TIMEOUT = 25.0
# Bounds one live op against the harness so a stuck op cannot hang the daemon
# forever; surfaced as the registered ``live_timeout`` (ADR-0021).
OP_TIMEOUT = 30.0


class EngineSession:
    """A launched engine run plus the daemon's connection to its harness."""

    def __init__(self, proc: subprocess.Popen, conn: socket.socket) -> None:
        self._proc = proc
        self._conn = conn

    def alive(self) -> bool:
        return self._proc.poll() is None

    def request(self, operation: str, params: dict) -> dict:
        """Relay one live op to the harness; return the CLI reply dict."""
        try:
            self._conn.settimeout(OP_TIMEOUT)
            write_message(self._conn, {"op": operation, "params": params})
            reply = read_frame(self._conn)  # the raw ADR-0002 sentinel string
        except TimeoutError:
            return _live_reply(
                "live_timeout",
                f"the engine session did not return within {int(OP_TIMEOUT)}s",
            )
        except OSError:
            return _live_reply("engine_disconnected", "the engine session dropped the connection")
        if reply is None:
            return _live_reply("engine_disconnected", "the engine session closed before replying")
        return {"stdout": reply.decode("utf-8", "replace"), "stderr": "", "exit_code": 0}

    def close(self) -> None:
        try:
            self._conn.close()
        except OSError:
            pass
        _terminate(self._proc)


def launch_session(
    project: Path,
    binary: str,
    harness_listener: socket.socket,
    harness_socket: Path,
    token: str,
    timeout: float = CONNECT_TIMEOUT,
) -> Optional[EngineSession]:
    """Launch a headless engine session and wait for the harness to connect."""
    proc = subprocess.Popen(
        [
            str(binary),
            "--headless",
            "--path",
            str(project),
            "--",
            LAUNCH_MARKER,
            str(harness_socket),
            token,
        ],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    harness_listener.settimeout(timeout)
    try:
        conn, _ = harness_listener.accept()
    except OSError:  # includes socket.timeout
        _terminate(proc)
        return None

    # The harness's first frame is the auth token.
    try:
        presented = read_frame(conn)
    except OSError:
        presented = None
    if presented is None or presented.decode("utf-8", "replace") != token:
        try:
            conn.close()
        except OSError:
            pass
        _terminate(proc)
        return None
    return EngineSession(proc, conn)


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except OSError:
        try:
            proc.terminate()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass


def _live_reply(code: str, message: str) -> dict:
    body = json.dumps({"error": {"code": code, "message": message}})
    return {
        "stdout": f"{RESULT_BEGIN}{body}{RESULT_END}\n",
        "stderr": "",
        "exit_code": EXIT_LIVE,
    }
