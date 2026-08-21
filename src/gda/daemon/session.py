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
import time
from pathlib import Path
from typing import Optional

from gda.daemon.protocol import error_reply, read_frame, write_message
from gda.display import WindowedUnavailable

LAUNCH_MARKER = "gda-daemon"
# Engine boot + autoload + harness connect; a windowed/cold start can be slow.
CONNECT_TIMEOUT = 25.0
# Bounds one live op against the harness so a stuck op cannot hang the daemon
# forever; surfaced as the registered ``live_timeout`` (ADR-0021).
OP_TIMEOUT = 30.0
# How long a SIGTERM'd engine may take to exit before it is escalated to SIGKILL,
# when the caller set no deadline of its own (``EngineSession.close``). A launch
# teardown draws its grace from the launch deadline instead (#725 re-review).
TERMINATE_GRACE = 5.0


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


class WindowedDisplayUnavailable(Exception):
    """A windowed session cannot launch: the host has no usable ``DisplayServer``.

    Raised at the AUTHORITATIVE session-launch boundary (``_ensure_session``, where
    the lazy launch happens) BEFORE :func:`launch_session` is ever called, when a
    windowed daemon's pre-launch host-display check fails — a windowed Godot would
    abort during ``DisplayServer`` registration otherwise (#345). Mirrors
    :class:`SceneMismatch`: a typed launch-boundary signal the daemon maps to the
    probe's own error code — ``live_windowed_unavailable`` when no window-server
    session is detected, ``live_windowed_permission_denied`` when this process is
    denied the window-server lookup (which proves nothing about whether the host
    has one, #667) — distinct from a generic launch failure
    (``launch_session`` returns ``None``). It carries the whole ``verdict`` rather
    than only its prose, so the daemon relays the code the probe decided instead of
    re-deciding it here.
    """

    def __init__(self, verdict: WindowedUnavailable) -> None:
        super().__init__(verdict.reason)
        self.verdict = verdict
        self.reason = verdict.reason


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
        self._channel_stale = False

    def alive(self) -> bool:
        # Liveness is the PROCESS and the CHANNEL (#725 review): a session whose
        # harness channel was observed broken — dropped, closed, or left
        # response-ambiguous by a timed-out relay — cannot serve, however alive
        # the engine process is; calling it alive made `daemon wait-ready` report
        # a serving state the very next read disproved. Staleness is latched at
        # the observation point (a failed relay in ``request``), so the next
        # session-needing op rebuilds through the shared launch boundary.
        return self._proc.poll() is None and not self._channel_stale

    def request(self, operation: str, params: dict) -> dict:
        """Relay one live op to the harness; return the CLI reply dict."""
        if self._conn is None:
            # A session whose harness never connected has no channel to relay on
            # — report it as a dropped connection rather than crash on ``None``.
            self._channel_stale = True
            return error_reply(
                "engine_disconnected", "the engine session has no live connection"
            )
        try:
            self._conn.settimeout(OP_TIMEOUT)
            write_message(self._conn, {"op": operation, "params": params})
            reply = read_frame(self._conn)  # the raw ADR-0002 sentinel string
        except TimeoutError:
            # Latched stale too (#725 re-review). The earlier reading — "a slow op
            # is not a broken channel" — priced only the churn of relaunching. The
            # real price is worse: this protocol carries no request id and the
            # timed-out frame is NOT drained, so a late reply is indistinguishable
            # from the NEXT op's reply. Reproduced on the pre-fix head: op A times
            # out, op B reads A's late payload and returns it as B's result — a
            # validly-framed, semantically WRONG answer. A channel that can answer
            # with another operation's result cannot serve, so the session is dead
            # to the daemon from here; the next session-needing op rebuilds it
            # through the shared launch boundary. The cost is a relaunch after an
            # op that outran OP_TIMEOUT (state does not survive it — CONTEXT.md
            # "State consistency"); correlating replies instead would change the
            # cross-language harness protocol and belongs to its own decision.
            self._channel_stale = True
            return error_reply(
                "live_timeout",
                f"the engine session did not return within {int(OP_TIMEOUT)}s",
            )
        except OSError:
            self._channel_stale = True
            return error_reply(
                "engine_disconnected", "the engine session dropped the connection"
            )
        if reply is None:
            self._channel_stale = True
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
    diagnostics: Optional[list[str]] = None,
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

    On a failed launch (a ``None`` return) an optional ``diagnostics`` sink collects
    a best-effort reason string so the daemon can surface it instead of an empty
    ``engine_session_not_running`` (#345). Because the child is spawned with
    ``stderr=DEVNULL`` (redirecting it to a pipe risks a fill-buffer deadlock, out of
    scope here), the one cause signal we keep is the child's LIVENESS at the failure
    boundary: a child that already exited names its exit — a negative return code is
    a signal death (e.g. a windowed session that could not bring up a
    ``DisplayServer`` aborts with ``SIGABRT``) — while a child still alive when the
    harness never connected is the "harness hung" case. That distinction tells a
    crashed windowed process apart from a stuck harness.
    """

    def _record(message: str) -> None:
        # Collect a best-effort launch-failure reason for the daemon to surface
        # (#345); a no-op when the caller passed no sink.
        if diagnostics is not None:
            diagnostics.append(message)

    log_args = ["--log-file", str(log_file)] if log_file is not None else []
    if log_file is not None:
        # Truncate the Session log BEFORE spawning (#345 finding 2). Godot's
        # ``--log-file`` logger opens the path with ``FileAccess::WRITE`` (truncating)
        # only once it installs, but a PRE-LOGGER abort — a windowed-no-DisplayServer
        # crash, and others — dies before that, leaving a PREVIOUS session's output on
        # disk. Without this, the failed-launch diagnostics tail would attach that
        # stale content. Truncating here makes "truncated each launch" (ADR-0022 /
        # CONTEXT.md Session log) hold even for a pre-logger abort: a pre-logger
        # failure then reads EMPTY (honest), a post-logger one reads only the current
        # session. Best-effort — a truncate failure must not abort the launch.
        try:
            log_file.write_bytes(b"")
        except OSError:
            pass
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
    # ONE monotonic deadline for the WHOLE readiness handshake (#725 review):
    # accept, the token frame, and the scene-verification frame all draw down the
    # same budget. Bounding only the accept let a peer that connected and then
    # went silent block the token read forever — and the daemon serves one
    # request at a time, so that silence froze every later live and control
    # request with it.
    deadline = time.monotonic() + timeout

    def _remaining() -> float:
        return max(deadline - time.monotonic(), 0.001)

    def _teardown() -> None:
        # Teardown draws from the SAME deadline (#725 re-review). A failure path
        # is reached with the budget already spent, so a child that ignores
        # SIGTERM used to add a fresh five-second grace ON TOP of the caller's
        # bound — 5.3s for a `wait-ready --timeout 0.3` — with the single-threaded
        # serve loop blocked for all of it. Nothing left means kill now.
        _terminate(proc, grace=max(deadline - time.monotonic(), 0.0))

    harness_listener.settimeout(timeout)
    try:
        conn, _ = harness_listener.accept()
    except OSError:  # includes socket.timeout
        # No harness connected within the timeout. Poll the child BEFORE tearing it
        # down: this is where a windowed-no-DisplayServer abort (child died by
        # signal) is told apart from a genuinely hung harness (child still alive).
        _record(_child_exit_diagnostic(proc, timeout))
        _teardown()
        return None

    # The harness's first frame is the auth token.
    conn.settimeout(_remaining())
    try:
        presented = read_frame(conn)
    except OSError:  # includes the deadline expiring mid-read
        presented = None
    if presented is None:
        _record(
            "the harness connected but sent no auth token within the launch deadline"
        )
        _close(conn)
        _teardown()
        return None
    if presented.decode("utf-8", "replace") != token:
        _record("the harness connected but presented an invalid auth token")
        _close(conn)
        _teardown()
        return None

    # The harness's second frame is the launch-time scene verification: it reports
    # whether the scene the session ACTUALLY loaded matches the requested selector
    # (#278). A mismatch — including Godot's silent main_scene fallback for a bad
    # uid — tears the session down and raises SceneMismatch so the daemon surfaces a
    # typed live_scene_not_found rather than serving the wrong scene.
    conn.settimeout(_remaining())
    try:
        verify_frame = read_frame(conn)
    except OSError:
        verify_frame = None
    if verify_frame is None:
        _record("the harness connected but closed before the scene-verification frame")
        _close(conn)
        _teardown()
        return None
    try:
        verify = json.loads(verify_frame.decode("utf-8", "replace"))
    except (ValueError, TypeError):
        verify = {}
    if not isinstance(verify, dict) or not verify.get("scene_ok", False):
        current = verify.get("current", "") if isinstance(verify, dict) else ""
        _close(conn)
        _teardown()
        raise SceneMismatch(scene if scene is not None else "", str(current))
    return EngineSession(proc, conn, log_file=log_file)


def _child_exit_diagnostic(proc: subprocess.Popen, timeout: float) -> str:
    """A best-effort launch-failure reason from the child's liveness (#345).

    Called on a failure path BEFORE terminating the child (spawned with
    ``stderr=DEVNULL``, so its liveness is the one cause signal we keep). A child
    that has ALREADY exited means the engine died before the harness could connect:
    a negative return code is a signal death (a windowed session that could not
    register a ``DisplayServer`` aborts with ``SIGABRT``); a positive one is a plain
    non-zero exit. A child STILL alive is the "engine up, harness never connected"
    case — a hung/broken harness autoload. This is the signal that tells a crashed
    windowed process apart from a stuck harness.
    """
    code = proc.poll()
    if code is None:
        return f"the engine started but the harness did not connect within {timeout:.0f}s; session terminated"
    if code < 0:
        signum = -code
        try:
            name = signal.Signals(signum).name
        except ValueError:
            name = f"signal {signum}"
        return f"the engine child aborted by signal {name} ({signum}) before the harness connected"
    return f"the engine child exited with status {code} before the harness connected"


def _close(conn: socket.socket) -> None:
    try:
        conn.close()
    except OSError:
        pass


def _terminate(proc: subprocess.Popen, grace: float = TERMINATE_GRACE) -> None:
    """SIGTERM the engine, then SIGKILL it if it has not exited within ``grace``.

    ``grace`` is a BUDGET, not a fixed pause: the launch paths pass what remains
    of their readiness deadline (#725 re-review), because the daemon serves one
    request at a time and a child that ignores SIGTERM used to start a fresh
    five-second wait AFTER the caller's budget was already spent — a 0.3s-bounded
    ``daemon wait-ready`` measured 5.3s. With nothing left the escalation is
    immediate; the diagnostics that failure path reads are unaffected, because
    Godot's file logger flushes every error, and every print in a debug build
    (``core/io/logger.cpp``, ``application/run/flush_stdout_on_print.debug``).
    """
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
        proc.wait(timeout=max(grace, 0.0))
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
