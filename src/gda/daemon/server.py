"""The gda-daemon server: the per-project Unix-domain-socket broker (ADR-0017).

A long-lived process that binds the project's CLI socket (for the CLI) and harness
socket (for the engine session's harness), records its pidfile, and serves one
request at a time — single-writer serialization of live operations against the one
session it holds (ADR-0020). Two control ops manage its lifetime (``__status__``
liveness, ``__stop__`` graceful shutdown); any other op is a project live op,
served by the engine session, which is (re)launched lazily on demand.
"""

import math
import os
import secrets
import signal
import socket
import time
from pathlib import Path
from typing import Callable, NamedTuple, Optional, Protocol

from gda.daemon.diag import parse_errors, parse_log_records
from gda.daemon.discovery import DaemonPaths, acquire_pidfile, ensure_runtime_dir
from gda.daemon.protocol import error_reply, read_message, result_reply, write_message
from gda.daemon.session import (
    MainSceneUndefinedAtLaunch,
    CONNECT_TIMEOUT,
    SceneMismatch,
    WindowedDisplayUnavailable,
    launch_session,
)
from gda.display import WindowedUnavailable, windowed_unavailable
from gda.project import main_scene_undefined

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

# The daemon-served readiness op (#657): `gda daemon wait-ready`. Like the LOG_OPS
# it is answered by the daemon rather than relayed to the harness — but unlike
# them it deliberately LAUNCHES the engine session (the documented, bounded way to
# trigger ADR-0017's lazy launch), so it is not in their read-only family.
WAIT_READY_OP = "daemon-wait-ready"

# Every LIVE op the daemon answers ITSELF rather than relaying to the harness.
# The single membership authority (#725 review): production routing keys on this
# tuple (`_handle` -> `_handle_daemon_served`), and the cross-language op-table
# guard subtracts the same tuple before demanding a harness-side `const OP_…`
# mirror (PR #650 guards, #657) — so the two cannot drift.
DAEMON_SERVED_OPS = (*LOG_OPS, WAIT_READY_OP)

# The wire contract's cap on a wait-ready launch bound (#657): the live channel
# bounds one whole request round trip at 60s client-side
# (gda.live_runner.LIVE_REQUEST_TIMEOUT), so the daemon-side wait must resolve
# comfortably inside it. One authority for both enforcement points: the CLI
# params model (ADR-0015) and the daemon's own IPC-boundary check below.
WAIT_READY_TIMEOUT_MAX = 50.0


class SessionHandle(Protocol):
    """What the server consumes of a session (#723 review): a structural contract.

    The server owns this — it names exactly the capabilities the serve loop
    needs (liveness, one-op relay, the remembered log path, teardown) — so a
    unit-test fake conforms by shape, with no cast at the seam.
    :class:`gda.daemon.session.EngineSession` is the concrete implementation.
    """

    log_file: Optional[Path]
    session_id: str

    def alive(self) -> bool: ...

    def request(self, operation: str, params: dict) -> dict: ...

    def close(self, deadline: float | None = ...) -> None: ...


class _Established(NamedTuple):
    """A serving session plus the fact of who launched it (#725 review).

    ``launched`` is decided by the launch owner (``_ensure_session``) at the
    moment it reuses or launches — never re-derived by a caller, whose separate
    ``alive()`` sample raced the decision (a process exiting between the two
    samples made a call that DID launch report ``launched: false``).
    """

    session: SessionHandle
    launched: bool


class SessionLaunch(Protocol):
    """The server↔session seam: the shape of :func:`launch_session` (#674).

    :class:`DaemonServer` takes one so unit tests can drive the whole serve
    loop — lazy launch, launch failure, session death, relaunch — against a
    fake :class:`SessionHandle`, with no Godot binary and no real engine. The
    default is always the real :func:`launch_session`; the seam injects, it
    never re-implements.
    """

    def __call__(
        self,
        project: Path,
        binary: str,
        harness_listener: socket.socket,
        harness_socket: Path,
        token: str,
        log_file: Optional[Path] = None,
        deadline: Optional[float] = None,
        windowed: bool = False,
        scene: Optional[str] = None,
        diagnostics: Optional[list[str]] = None,
        session_id: str = "",
    ) -> Optional[SessionHandle]: ...


class DaemonServer:
    """Binds the per-project sockets and serves requests until stopped."""

    def __init__(
        self,
        paths: DaemonPaths,
        godot: str = "",
        windowed: bool = False,
        scene: str | None = None,
        display_check: Optional[Callable[[], Optional[WindowedUnavailable]]] = None,
        launch: Optional[SessionLaunch] = None,
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
        # The pre-launch host-display precondition seam (#345): returns the reason a
        # windowed session cannot come up on this host, or None when it can. Injectable
        # so tests drive the guard without a real display; defaults to the shared
        # gda.display probe. Consulted only for a windowed session.
        self._display_check = display_check or windowed_unavailable
        # The server↔session seam (#674): how an engine session is launched.
        # Injectable so unit tests drive the whole serve loop against a fake
        # session — no Godot binary, no real engine. Resolved at construction
        # against the module global, so the default stays the real launch.
        self._launch: SessionLaunch = launch or launch_session
        self._token = secrets.token_hex(16)
        self._stopping = False
        self._listener: socket.socket | None = None
        self._harness_listener: socket.socket | None = None
        self._session: SessionHandle | None = None
        # The last SUCCESSFULLY ESTABLISHED session's identity (#660, PR #746
        # review ARC-746-001): a read model beside the session object, because
        # the identity must outlive it — retirement drops `_session` before the
        # replacement launch, and a FAILED launch must not erase the identity
        # nothing replaced. Written only when a launch succeeds, at the same
        # place `_session` is assigned.
        self._last_session_id: str | None = None
        self._pidfile_handle = None

    def serve(self) -> None:
        ensure_runtime_dir(self.paths)
        # The pidfile's advisory lock is the daemon's mutual exclusion AND its
        # liveness signal (ADR-0021), so it is taken FIRST: a start that loses the
        # race fails here, before it can unlink — or leave the cleanup below to
        # unlink — the winner's live sockets (#674 socket-lifecycle test; binding
        # first let a losing double-start destroy the winner's slot). Liveness as
        # the CLI reads it needs the lock AND a bound socket, so the daemon is
        # still not reported live until the binds below land.
        self._pidfile_handle = acquire_pidfile(self.paths, os.getpid())
        try:
            self._listener = self._bind(self.paths.cli_socket)
            self._harness_listener = self._bind(self.paths.harness_socket)
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, self._on_signal)
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
                try:
                    request = read_message(conn)
                    if request is not None:
                        reply = self._handle(request)
                        if reply is not None:
                            write_message(conn, reply)
                except Exception:
                    # The daemon outlives any one client frame: a single request
                    # that fails to decode (bad JSON bytes) or to handle must never
                    # terminate the serve loop. Drop it — the conn closes with no
                    # reply and the client surfaces engine_disconnected — and keep
                    # accepting. (KeyboardInterrupt/SystemExit still propagate.)
                    pass
            if self._stopping:
                break

    def _handle(self, request: object) -> dict | None:
        # ``request`` is a JSON frame decoded from a client process (read_message
        # returns any JSON value), so this is an IPC boundary, not an internal
        # invariant. A malformed frame — a non-dict value (``[]``, ``"x"``, …), a
        # missing ``op``, or a non-string ``op`` — is DROPPED (return None) so the
        # serve loop survives rather than crashing on ``.get`` or a bad relay. The
        # connection closes with no reply; the client maps that to engine_disconnected.
        if not isinstance(request, dict):
            return None
        op = request.get("op")
        if not isinstance(op, str):
            return None
        if op == STATUS_OP:
            # `windowed` lets `gda daemon status` report the daemon's launch-time
            # display mode (#251): the running daemon is the only authority for the
            # mode it was started with, so it travels back on the control reply.
            # `session_id` (#660) is the identity of the last session this daemon
            # SUCCESSFULLY established — reported ALIVE OR DEAD, like the log ops
            # serve a dead session's log, so a capture receipt from a session that
            # then crashed stays correlatable until a NEW session replaces it. A
            # failed replacement launch replaces nothing, so it must not erase
            # the identity either (PR #746 review ARC-746-001) — hence the read
            # model, not the (already-retired) session object. Null before the
            # first successful launch this daemon lifetime.
            return {
                "ok": True,
                "pid": os.getpid(),
                "windowed": self.windowed,
                "session_id": self._last_session_id,
            }
        if op == STOP_OP:
            self._stopping = True
            return {"ok": True, "pid": os.getpid()}
        if op in DAEMON_SERVED_OPS:
            # Daemon-answered, never relayed. Membership is decided by the ONE
            # tuple the cross-language guard also reads (#725 review), so an op
            # declared daemon-served is intercepted here by construction.
            return self._handle_daemon_served(op, request.get("params", {}))
        # A project live op. Serialized against the one session (single writer).
        outcome = self._session_or_refusal()
        if isinstance(outcome, dict):
            return outcome
        return outcome.session.request(op, request.get("params", {}))

    def _handle_daemon_served(self, op: str, params: dict) -> dict:
        """Dispatch one DAEMON_SERVED_OPS member to its daemon-side handler."""
        if op in LOG_OPS:
            # `gda diag errors` / `gda logger tail`: the daemon reads the Session
            # log it owns rather than relaying to the harness (#224, #281).
            return self._handle_log(op, params)
        if op == WAIT_READY_OP:
            # `gda daemon wait-ready` (#657) — unlike the LOG_OPS it deliberately
            # LAUNCHES: the explicit, bounded way to establish the lazily-launched
            # session (ADR-0017) so an agent's first real read serves.
            return self._handle_wait_ready(params)
        # A DAEMON_SERVED_OPS member with no handler is a gda defect: refuse it
        # loudly rather than silently relaying it to a harness that never
        # declared it. Unreachable while the tuple is composed from LOG_OPS and
        # WAIT_READY_OP above; the parity test drives every member through here.
        return error_reply(
            "unknown_operation", f"daemon-served op {op!r} has no daemon handler"
        )

    def _handle_wait_ready(self, params: dict) -> dict:
        """Establish the engine session and report readiness (#657).

        The bounded-wait half of ADR-0017's lazy launch: sessions still launch
        lazily on the first operation that requires one, and THIS op is the
        explicit way to be that operation — its success means the harness has
        connected and presented its token, so subsequent live reads (including a
        first ``diag errors``, which never launches) serve. ``timeout`` bounds
        the launch's whole readiness handshake; an already-serving session
        returns immediately with ``launched: false`` and is never relaunched.
        ``launched`` is reported by the launch owner (``_ensure_session``), not
        inferred here — a pre-sampled ``alive()`` raced the launch decision and
        could report ``false`` for a call that did launch (#725 review).
        """
        raw = params.get("timeout")
        timeout: float | None = None
        if raw is not None:
            # The same finite (0, 50] rule the params model enforces (ADR-0015),
            # re-checked at the IPC boundary (#725 review): this socket can be
            # driven by clients other than gda's CLI, and an unbounded or
            # non-finite value here would defeat the very bound this op promises.
            if (
                isinstance(raw, bool)
                or not isinstance(raw, (int, float))
                or not math.isfinite(raw)
                or not 0 < raw <= WAIT_READY_TIMEOUT_MAX
            ):
                return error_reply(
                    "invalid_params",
                    "wait-ready timeout must be a finite number in "
                    f"(0, {int(WAIT_READY_TIMEOUT_MAX)}]; got {raw!r}",
                )
            timeout = float(raw)
        outcome = self._session_or_refusal(timeout=timeout)
        if isinstance(outcome, dict):
            return outcome
        return result_reply({"pid": os.getpid(), "launched": outcome.launched})

    def _session_or_refusal(
        self, timeout: float | None = None
    ) -> "_Established | dict":
        """The serving session — with whether this call launched it — or the typed refusal.

        The one launch boundary every session-needing op goes through (#657
        extracted it from the live-op branch so ``wait-ready`` shares it exactly).
        ``launched`` travels with the session because only the launch owner knows
        it (#725 review): sampling ``alive()`` before and after raced the
        decision. The scene selector is verified ONCE at launch (in the harness):
        a mismatch is a typed live_scene_not_found, never a silent fall back to
        main_scene and never a per-request re-check (#278, ADR-0017 amendment,
        ADR-0020).
        """
        launch_diagnostics: list[str] = []
        try:
            established = self._ensure_session(launch_diagnostics, timeout=timeout)
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
        except WindowedDisplayUnavailable as unavailable:
            # The authoritative no-display guard fired at the launch boundary (#345):
            # no windowed engine was spawned. Surface the code the PROBE decided —
            # live_windowed_unavailable, or live_windowed_permission_denied when this
            # process is denied the window-server lookup (which proves nothing about
            # whether the host has one, #667) — carrying
            # the probe's reason as diagnostics. The remediation differs per code, so
            # the message is the verdict's own rather than one shared sentence.
            #
            # This is the AUTHORITATIVE refusal — the one that fires on the lazy
            # launch every live op goes through — so it carries the same
            # machine-readable `probe` context the CLI fail-fast does, via the live
            # envelope's optional key (#667 review). Reporting less here than at the
            # optional fail-fast would make the authoritative path the poorer one.
            return error_reply(
                unavailable.verdict.code,
                f"a windowed engine session cannot launch: {unavailable.reason}",
                diagnostics=unavailable.reason,
                probe=unavailable.verdict.probe,
            )
        except MainSceneUndefinedAtLaunch as undefined:
            # The authoritative nothing-to-run guard fired at the launch boundary
            # (#829): no engine was spawned. Same code and sentence as the `daemon
            # start` fail-fast, so the two sites cannot disagree.
            return error_reply(undefined.verdict.code, undefined.reason)
        if established is None:
            return error_reply(
                "engine_session_not_running",
                "the gda-daemon could not launch an engine session (no Godot binary, "
                "or the engine died / the harness did not connect)",
                diagnostics=self._launch_failure_diagnostics(launch_diagnostics),
            )
        return established

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

    def _ensure_session(
        self, diagnostics: list[str] | None = None, timeout: float | None = None
    ) -> "_Established | None":
        # ONE deadline — an absolute instant, taken at ENTRY — for everything this
        # boundary does on the caller's clock (#725 re-review): the liveness check,
        # retiring the session it is replacing, and launching the replacement.
        # Retirement is not free (a stale session's engine may ignore SIGTERM) and
        # neither is a spawn, so charging either to nobody made the bound a
        # per-phase allowance rather than a bound. Every phase receives the INSTANT,
        # never a duration: a duration is a fresh budget to whatever receives it,
        # which is how an exhausted one came back whole one layer down.
        deadline = time.monotonic() + (
            timeout if timeout is not None else CONNECT_TIMEOUT
        )
        if self._session is not None and self._session.alive():
            return _Established(self._session, launched=False)
        if self._session is not None:
            self._session.close(deadline)
            self._session = None
        if not self.godot:
            return None
        if time.monotonic() >= deadline:
            # Retirement used the whole budget. Launching now would be launching
            # past the bound, so this is a refusal, reported like any other failed
            # launch — with the reason, since an empty one reads as a mystery.
            if diagnostics is not None:
                diagnostics.append(
                    "the readiness deadline expired while the previous engine "
                    "session was retired; no replacement was launched"
                )
            return None
        # The AUTHORITATIVE no-display guard (#345): a windowed session needs a usable
        # host DisplayServer, else a windowed Godot aborts during DisplayServer
        # registration. This is the launch boundary — where the lazy session launch
        # actually happens — so refuse HERE, BEFORE launch_session is ever called, with
        # a typed WindowedDisplayUnavailable (mirroring the SceneMismatch pattern). The
        # daemon maps it to live_windowed_unavailable. `daemon start --windowed` runs
        # the same check as an OPTIONAL fail-fast, but this is the one that guarantees a
        # doomed windowed engine is never spawned even when start slipped through.
        if self.windowed:
            verdict = self._display_check()
            if verdict is not None:
                raise WindowedDisplayUnavailable(verdict)
        # The AUTHORITATIVE nothing-to-run guard (#829): a session with no `--scene`
        # and an empty `application/run/main_scene` would make Godot print "no main
        # scene defined" and then block on a native alert (macOS, even headless)
        # until the readiness deadline killed it. Read from the project file at THIS
        # instant — the file can change after `daemon start`, which runs the same
        # check as its optional fail-fast — and refused before launch_session.
        undefined = main_scene_undefined(self.paths.project, self.scene)
        if undefined is not None:
            raise MainSceneUndefinedAtLaunch(undefined)
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
        # The session's identity (#660), minted HERE — the daemon is the
        # authority for what it launches — and handed to the launch so the
        # harness can stamp it into capture receipts while `daemon status`
        # reports the same value. One mint per launch: a relaunch is a NEW
        # identity, which is exactly what makes a receipt from a stale session
        # detectable. Published to the status read model ONLY on success below —
        # a failed launch replaces nothing, so the last established identity
        # stays readable (PR #746 review ARC-746-001).
        session_id = secrets.token_hex(8)
        self._session = self._launch(
            self.paths.project,
            self.godot,
            self._harness_listener,
            self.paths.harness_socket,
            self._token,
            log_file=self.paths.session_log,
            session_id=session_id,
            # The caller's own deadline (#657 `daemon wait-ready --timeout`, #725
            # re-review), not a duration derived from it: the launcher spends what
            # is left of THIS instant on the spawn, the connect, the handshake
            # frames, and its teardown.
            deadline=deadline,
            windowed=self.windowed,
            scene=self.scene,
            diagnostics=diagnostics,
        )
        if self._session is None:
            return None
        self._last_session_id = session_id
        return _Established(self._session, launched=True)

    def _launch_failure_diagnostics(self, child_diagnostics: list[str]) -> str:
        """Best-effort diagnostics for a failed engine-session launch (#345).

        Combines the child-liveness reason ``launch_session`` observed (the engine
        died by signal, or the harness never connected) with a tail of the daemon-
        owned Session log, read via the DETERMINISTIC ``DaemonPaths.session_log``
        (#674) — which needs no live session object, extending ADR-0022's read
        path to the failed-launch case. NOTE: a windowed-no-``DisplayServer`` abort happens
        BEFORE Godot installs its file logger, so this tail is usually EMPTY for that
        case (the child-signal reason carries it); it carries content for a
        post-logger crash.
        """
        parts = [reason for reason in child_diagnostics if reason]
        tail = self._read_session_log_tail()
        if tail:
            parts.append(f"session log tail:\n{tail}")
        return "\n".join(parts)

    def _read_session_log_tail(self, max_bytes: int = 2000) -> str:
        """The trailing bytes of the daemon-owned Session log, or "" if unreadable."""
        try:
            data = self.paths.session_log.read_bytes()
        except OSError:
            return ""
        return data.decode("utf-8", "replace").strip()[-max_bytes:]

    def _cleanup(self) -> None:
        if self._session is not None:
            self._session.close()
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
        # The advisory lock releases LAST (#723 review): it is the slot's mutual
        # exclusion (ADR-0021), so it must outlive the slot it guards. Released
        # before the unlinks above, a successor could acquire and bind a fresh
        # slot inside this window — which the remaining unlinks would then
        # destroy, leaving a serving daemon that discovery reports as not
        # running.
        if self._pidfile_handle is not None:
            try:
                self._pidfile_handle.close()  # releases the advisory lock
            except OSError:
                pass
