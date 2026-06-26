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

from gda.daemon.protocol import error_reply, read_frame, write_message

LAUNCH_MARKER = "gda-daemon"
# Engine boot + autoload + harness connect; a windowed/cold start can be slow.
CONNECT_TIMEOUT = 25.0
# Bounds one live op against the harness so a stuck op cannot hang the daemon
# forever; surfaced as the registered ``live_timeout`` (ADR-0021).
OP_TIMEOUT = 30.0


class SceneMismatch(Exception):
    """The launched session loaded a scene other than the requested ``--scene``.

    Raised at the launch boundary when the requested ``--scene`` cannot be honoured:
    either the daemon's pre-launch check finds a ``res://`` selector that names no
    file (``current`` is ``None`` — Godot would fail to launch rather than run it),
    or the harness's launch-time verification reports the ACTUALLY-loaded scene
    differs from the selector (Godot silently ran ``main_scene`` for a bad
    ``uid://``). Either way it is the no-silent-fallback guarantee's signal (#278);
    the daemon maps it to the typed ``live_scene_not_found`` (ADR-0017 amendment),
    distinct from a generic launch failure (``launch_session`` returns ``None``).
    """

    def __init__(self, requested: str, current: str | None = None) -> None:
        super().__init__(
            f"requested scene {requested!r} but the session loaded {current!r}"
            if current is not None
            else f"requested scene {requested!r} does not exist in the project"
        )
        self.requested = requested
        self.current = current


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
            return error_reply(
                "live_timeout",
                f"the engine session did not return within {int(OP_TIMEOUT)}s",
            )
        except OSError:
            return error_reply(
                "engine_disconnected", "the engine session dropped the connection"
            )
        if reply is None:
            return error_reply(
                "engine_disconnected", "the engine session closed before replying"
            )
        return {
            "stdout": reply.decode("utf-8", "replace"),
            "stderr": "",
            "exit_code": 0,
        }

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
    scene: Optional[str] = None,
) -> Optional[EngineSession]:
    """Launch an engine session and wait for the harness to connect.

    The session is ``--headless`` by default — the cheap non-visual sessions
    (``game tree``, ``perf``, ``diag``) need no viewport. When ``windowed`` is set
    (``gda daemon start --windowed``, #222) ``--headless`` is OMITTED so the session
    runs with a real ``DisplayServer`` whose viewport a ``screen`` capture op can
    read pixels from; ``--headless``'s dummy ``DisplayServer`` cannot (ADR-0017).
    The mode is start-time declared and fixed for the session's life (ADR-0020).

    When ``scene`` is set (``gda daemon start --scene <path|UID>``, #278) the engine
    is launched with Godot's ``--scene <path|UID>`` engine option — placed BEFORE
    ``--path`` alongside ``--headless``/``--log-file`` — so the session boots that
    chosen scene instead of the project's ``main_scene`` (verified to run the scene
    without mutating ``main_scene``). Omitted when ``scene`` is ``None`` (the default,
    runs ``main_scene`` unchanged). The selector accepts a scene path or UID and is
    start-time declared, fixed for the session's life (ADR-0017 amendment, ADR-0020).

    The selector is ALSO threaded into the harness arg tail (after the launch
    marker, socket, and token; the empty string when ``None``) so the harness can
    verify the ACTUALLY-loaded scene against it at launch — the only way to honor
    "no silent fallback" for a ``uid://`` selector (the harness resolves uids; Godot
    silently falls back to ``main_scene`` for a bad one). After the token, the
    harness sends a SECOND frame, the verification result
    ``{"scene_ok": bool, "current": "res://…"}``. This function returns the verified
    :class:`EngineSession` when ``scene_ok``, raises :class:`SceneMismatch` when the
    loaded scene differs from the requested selector, and returns ``None`` on a
    generic launch failure (no connect / bad token / timeout).

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
    # `--scene <path|UID>` is an ENGINE option, so it sits before `--path` (and so
    # before the `--` payload separator) alongside the other engine args (#278).
    scene_args = ["--scene", scene] if scene is not None else []
    # The harness tail also carries the selector (empty string when none) so the
    # harness can verify the loaded scene against it at launch (#278).
    requested_scene = scene if scene is not None else ""
    proc = subprocess.Popen(
        [
            str(binary),
            *headless_args,
            *log_args,
            *scene_args,
            "--path",
            str(project),
            "--",
            LAUNCH_MARKER,
            str(harness_socket),
            token,
            requested_scene,
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

    # The harness's second frame is the launch-time scene verification: it reports
    # whether the scene the session ACTUALLY loaded matches the requested selector
    # (#278). A mismatch — including Godot's silent main_scene fallback for a bad
    # uid — tears the session down and raises SceneMismatch so the daemon surfaces a
    # typed live_scene_not_found rather than serving the wrong scene.
    try:
        verify_frame = read_frame(conn)
    except OSError:
        verify_frame = None
    if verify_frame is None:
        _close(conn)
        _terminate(proc)
        return None
    try:
        verify = json.loads(verify_frame.decode("utf-8", "replace"))
    except (ValueError, TypeError):
        verify = {}
    if not isinstance(verify, dict) or not verify.get("scene_ok", False):
        current = verify.get("current", "") if isinstance(verify, dict) else ""
        _close(conn)
        _terminate(proc)
        raise SceneMismatch(scene if scene is not None else "", str(current))
    return EngineSession(proc, conn, log_file=log_file)


def _close(conn: socket.socket) -> None:
    try:
        conn.close()
    except OSError:
        pass


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
