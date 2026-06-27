"""The gda-daemon server: the per-project Unix-domain-socket broker (ADR-0017).

A long-lived process that binds the project's CLI socket (for the CLI) and harness
socket (for the engine session's harness), records its pidfile, and serves one
request at a time — single-writer serialization of live operations against the one
session it holds (ADR-0020). Two control ops manage its lifetime (``__status__``
liveness, ``__stop__`` graceful shutdown); any other op is a project live op,
served by the engine session, which is (re)launched lazily on demand.
"""

import os
import secrets
import signal
import socket

from gda.daemon.diag import parse_errors, parse_log_records
from gda.daemon.discovery import DaemonPaths, acquire_pidfile, ensure_runtime_dir
from gda.daemon.protocol import error_reply, read_message, result_reply, write_message
from gda.daemon.session import EngineSession, SceneMismatch, launch_session

# Control ops on the CLI socket — daemon lifetime, not project domain ops.
STATUS_OP = "__status__"
STOP_OP = "__stop__"

# Daemon-served log ops (#224, #281): the `gda diag errors` and `gda logger tail`
# ops. Unlike the other live ops, they are NOT relayed to the harness — the daemon
# serves them directly from the Session log it launched the engine with
# (`--log-file`). Served even after the session process has died, so a crash stays
# diagnosable. (`diag log` is SUPERSEDED by `logger tail --raw`, ADR-0026.)
DIAG_ERRORS_OP = "diag-errors"
LOGGER_TAIL_OP = "logger-tail"
LOG_OPS = (DIAG_ERRORS_OP, LOGGER_TAIL_OP)


class DaemonServer:
    """Binds the per-project sockets and serves requests until stopped."""

    def __init__(
        self,
        paths: DaemonPaths,
        godot: str = "",
        windowed: bool = False,
        scene: str | None = None,
    ) -> None:
        self.paths = paths
        self.godot = godot
        # The start-time declared display mode (ADR-0017 refined, #222): when true the
        # engine session is launched windowed (no --headless) so a `screen` capture op
        # has a real DisplayServer; fixed for the daemon's life (ADR-0020 single
        # session), never switched mid-session.
        self.windowed = windowed
        # The start-time scene selector (ADR-0017 amendment, #278): when set the engine
        # session boots this chosen scene (a `res://…` path or `uid://…` value) via
        # Godot's `--scene` engine option instead of the project's main_scene; None
        # runs main_scene unchanged. Fixed for the daemon's life (ADR-0020).
        self.scene = scene
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
        if not isinstance(op, str):
            # ``op`` arrives as a JSON frame from the client process, so this is an
            # IPC boundary, not an internal invariant — a malformed frame (``{}`` or
            # a non-string ``op``) must NOT crash the serve loop (``_accept_loop``
            # does not catch ``_handle``'s exceptions). Drop it: the connection
            # closes with no reply and the client surfaces it as engine_disconnected.
            return None
        if op == STATUS_OP:
            # `windowed` lets `gda daemon status` report the daemon's launch-time
            # display mode (#251): the running daemon is the only authority for the
            # mode it was started with, so it travels back on the control reply.
            return {"ok": True, "pid": os.getpid(), "windowed": self.windowed}
        if op == STOP_OP:
            self._stopping = True
            return {"ok": True, "pid": os.getpid()}
        if op in LOG_OPS:
            # `gda diag errors` / `gda logger tail` are daemon-served: the daemon
            # reads the Session log it owns rather than relaying to the harness
            # (#224, #281).
            return self._handle_log(op, request.get("params", {}))
        # A project live op. Serialized against the one session (single writer).
        # The scene selector is verified ONCE at launch (in the harness): a mismatch
        # is a typed live_scene_not_found, never a silent fall back to main_scene and
        # never a per-request re-check (#278, ADR-0017 amendment, ADR-0020).
        try:
            session = self._ensure_session()
        except SceneMismatch as mismatch:
            detail = (
                f"no scene named {mismatch.requested!r} exists in the project"
                if mismatch.current is None
                else f"the session ran {mismatch.current!r} instead (Godot silently "
                "falls back to main_scene for an invalid scene)"
            )
            return error_reply(
                "live_scene_not_found",
                f"the --scene selector {mismatch.requested!r} did not load: {detail}. "
                "gda never falls back — fix the path/UID or omit --scene to run the "
                "project's main_scene",
            )
        if session is None:
            return error_reply(
                "engine_session_not_running",
                "the gda-daemon could not launch an engine session (no Godot binary, "
                "or the harness did not connect)",
            )
        return session.request(op, request.get("params", {}))

    def _handle_log(self, op: str, params: dict) -> dict:
        """Serve a daemon-side log op from the Session log this daemon owns (#224, #281).

        Reads the running game's captured errors/output from the ``--log-file``
        the daemon launched the engine with, for ``diag errors`` (structured engine
        errors) and ``logger tail`` (the whole log as structured ``LogRecord``s, or
        verbatim lines with ``--raw``). Crucially served even when the session
        process has DIED — it does NOT launch or relaunch a session (a read-only
        diagnostic must not run the project's code, ADR-0009; a relaunch would also
        truncate the log and lose the crash). It requires only that a session was
        launched this daemon lifetime (ADR-0022): it reads the one the daemon
        already holds, alive OR dead. With NO session launched this lifetime it is
        ``engine_session_not_running`` — the user launches a session by running a
        live op (e.g. ``gda game tree``). With a remembered session whose log file
        is missing/unreadable it is ``live_log_unavailable`` (an empty log is an
        empty result, not an error).
        """
        # Use the session the daemon already holds — never launch one here. This is
        # a read-only observer of an already-launched session (ADR-0022); launching
        # would give it a hidden project-code-execution side effect (ADR-0009).
        session = self._session
        if session is None or session.log_file is None:
            return error_reply(
                "engine_session_not_running",
                "the gda-daemon holds no engine session to read runtime "
                "diagnostics from; it observes an already-launched session and "
                "does not start one — launch a session first by running a live op "
                "(e.g. `gda game tree`), then re-run the read",
            )
        try:
            raw = session.log_file.read_bytes()
        except OSError:
            return error_reply(
                "live_log_unavailable",
                f"the engine session's diagnostics log at {session.log_file} is "
                "missing or unreadable",
            )
        limit = params.get("limit")
        if op == DIAG_ERRORS_OP:
            return result_reply({"errors": parse_errors(raw, limit=limit)})
        # logger-tail: the whole Session log as structured LogRecord[] (records-only
        # result); `--raw` returns every line as a verbatim `info` record.
        records = parse_log_records(
            raw, level=params.get("level"), limit=limit, raw=bool(params.get("raw"))
        )
        return result_reply({"records": records})

    def _ensure_session(self) -> EngineSession | None:
        if self._session is not None and self._session.alive():
            return self._session
        if self._session is not None:
            self._session.close()
            self._session = None
        if not self.godot:
            return None
        # A res:// / filesystem scene selector that names no file is rejected HERE,
        # at the launch boundary (NOT per-request — finding 1), as a typed
        # SceneMismatch. Godot does not fall-back-and-run for a missing res:// path:
        # it fails to launch and the harness never connects, so the launch-time
        # harness verification can't see it. A bad uid:// (which Godot DOES silently
        # run as main_scene) is caught by that verification inside launch_session
        # instead. Both surface live_scene_not_found (#278, ADR-0017 amendment).
        scene = self.scene
        if scene is not None and not scene.startswith("uid://"):
            rel = scene[len("res://") :] if scene.startswith("res://") else scene
            if not (self.paths.project / rel).expanduser().is_file():
                raise SceneMismatch(scene)
        assert self._harness_listener is not None
        self._session = launch_session(
            self.paths.project,
            self.godot,
            self._harness_listener,
            self.paths.harness_socket,
            self._token,
            log_file=self._session_log_path(),
            windowed=self.windowed,
            scene=self.scene,
        )
        return self._session

    def _session_log_path(self):
        """The daemon-owned Session-log path for this project (#224).

        Under the daemon's private runtime dir (NOT ``user://logs`` — that shared
        path caused #180), keyed by the same project slug the sockets/pidfile use,
        so the engine's ``--log-file`` writes the running game's errors/output to a
        path the daemon can read back to serve ``gda diag``. ``RotatedFileLogger``
        truncates it each launch, making it session-bound (ADR-0020).
        """
        slug = self.paths.cli_socket.name.split(".", 1)[0]
        return self.paths.runtime_dir / f"{slug}.session.log"

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
