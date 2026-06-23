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
    """A launched engine run plus the daemon's connection to its harness.

    The daemon launches the session with Godot's ``--log-file`` pointed at a
    session-scoped path it owns (ADR: runtime-diagnostics-via-daemon-owned-session-
    log), and the session REMEMBERS that path (``log_file``) so the daemon can read
    the running game's captured errors/output to serve ``gda diag`` — even after
    this process has died, keeping a crash diagnosable.
    """

    def __init__(
        self,
        proc: subprocess.Popen,
        conn: socket.socket | None,
        log_file: Optional[Path] = None,
    ) -> None:
        self._proc = proc
        self._conn = conn
        self.log_file = log_file

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
        if self._conn is not None:
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
    log_file: Optional[Path] = None,
    timeout: float = CONNECT_TIMEOUT,
    windowed: bool = False,
) -> Optional[EngineSession]:
    """Launch an engine session and wait for the harness to connect.

    The session is ``--headless`` by default — the cheap non-visual sessions
    (``game tree``, ``perf``, ``diag``) need no viewport. When ``windowed`` is set
    (``gda daemon start --windowed``, #222) ``--headless`` is OMITTED so the session
    runs with a real ``DisplayServer`` whose viewport a ``screen`` capture op can
    read pixels from; ``--headless``'s dummy ``DisplayServer`` cannot (ADR-0017).
    The mode is start-time declared and fixed for the session's life (ADR-0020).

    When ``log_file`` is given, the engine is launched with Godot's
    ``--log-file <abs path>`` so the session writes BOTH its output and its errors
    to that one daemon-owned file (it forces file logging on even when the project
    disables it, and truncates per launch — verified against the engine's
    ``main/main.cpp`` / ``core/io/logger.cpp``). This sidesteps the shared
    ``user://logs`` contention (#180) by isolation, and the session REMEMBERS the
    path so the daemon can serve ``gda diag`` from it (ADR: runtime-diagnostics-
    via-daemon-owned-session-log). The session still relays live ops to the harness.
    """
    log_args = ["--log-file", str(log_file)] if log_file is not None else []
    headless_args = [] if windowed else ["--headless"]
    proc = subprocess.Popen(
        [
            str(binary),
            *headless_args,
            *log_args,
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
    return EngineSession(proc, conn, log_file=log_file)


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
