"""Socket-lifecycle tests for the gda-daemon server (#674).

These drive the REAL serve loop — a real bind through the platform seam, accept,
reply, cleanup — against a fake engine session injected through the
``SessionLaunch`` seam, so the daemon's endpoint lifecycle (bind, double-start,
stop cleanup) and its session lifecycle (lazy launch, launch failure, death
mid-request, relaunch) are covered by the fast suite with no Godot binary and no
real engine, on every platform the seam serves. A test that needs a Unix
mechanism — the slot files, a forked daemon, a process group — is in
``test_daemon_unix_adapter`` (#1233).

Real binds take the task-local runtime-directory fixture: on Unix a socket path
is bounded by the OS ``sun_path`` limit, which pytest's long macOS ``tmp_path``
overflows. A test reaches the daemon as the CLI does, through the seam's
connect, and a fake harness peer reaches the harness listener as the engine-side
harness does, from the launch argument (#1233).

``serve()`` installs signal handlers, which only works on the main thread — the
shared ``serving_daemon`` door runs it on a worker thread and records the
registration instead.
"""

import os
import socket
import threading
import time
from pathlib import Path
from typing import cast

import pytest

from gda.daemon.discovery import daemon_paths
from gda.daemon.host import host_platform
from gda.daemon.protocol import read_message, write_frame
from gda.daemon.server import DAEMON_SERVED_OPS, DaemonServer
from gda.daemon.session import LAUNCH_MARKER, EngineSession, launch_session
from gda.daemon.client import DaemonRunner, control_outcome
from gda.core.engine.sentinel import build_result, parse_result
from tests.support import (
    LAUNCH_DEADLINE_S,
    SCHEDULING_SLACK_S,
    FakeHarnessListener,
    FakeProc,
    bound_endpoints,
    daemon_round_trip,
    fake_session_spawn,
    harness_peer,
    no_launch,
    runnable_project,
    serving_daemon,
    stub_daemon_platform,
)


class _ServedSession:
    """A fake session that serves every relayed op — a structural SessionHandle."""

    log_file: "Path | None" = None

    def __init__(
        self, session_id: str = "fake-session", handshake_log_size: "int | None" = None
    ) -> None:
        self.closed = False
        self.session_id = session_id
        # The bound of the startup verdict (#848): the log's size at the instant
        # the handshake completed. None models a launch that could not measure
        # it, which the daemon reports as no verdict.
        self.handshake_log_size = handshake_log_size

    def alive(self) -> bool:
        return True

    def request(self, operation: str, params: dict) -> dict:
        return {"stdout": f"served:{operation}", "stderr": "", "exit_code": 0}

    def close(self, deadline: "float | None" = None) -> None:
        self.closed = True
        self.close_deadline = deadline


def _unpublished(paths) -> bool:
    """No daemon accepts a connection at the project's endpoint, as the CLI reads it."""
    return not control_outcome(
        paths, "__status__", 1.0, platform=host_platform()
    ).accepted


def test_serve_publishes_both_endpoints_and_answers_status(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=no_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        # Live as the CLI reads it: the slot is held AND the endpoint is published.
        assert host_platform().daemon_pid(paths) == os.getpid()
        harness_peer(cast(socket.socket, server._harness_listener), paths).close()
        reply = daemon_round_trip(paths, {"op": "__status__"})
        assert reply == {
            "ok": True,
            "pid": os.getpid(),
            "windowed": False,
            # No session launched this lifetime -> nothing to correlate (#660),
            # and no startup to report on (#848). The verdict is null rather
            # than an empty list, which would claim a clean start nothing backs.
            "session_id": None,
            "startup_diagnostics": None,
            "clean_start": None,
        }


def test_a_double_start_loses_without_touching_the_live_daemons_slot(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # Two starts race; the pidfile's advisory lock decides. The LOSER must fail
    # without disturbing ANY part of the winner's slot (ADR-0021): not its
    # socket files (a losing start that unlinks them turns one daemon into zero
    # reachable ones), and not its pidfile CONTENT either — a pre-lock
    # truncation erases the winner's recorded identity, so status, attach, and
    # stop all read the live daemon as not running (#723 review).
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    winner = DaemonServer(
        paths, godot="godot", launch=no_launch, platform=host_platform()
    )

    with serving_daemon(winner, paths, monkeypatch):
        loser = DaemonServer(
            paths, godot="godot", launch=no_launch, platform=host_platform()
        )
        with pytest.raises(OSError):
            loser.serve()

        # The winner's slot is intact and still serves new connections.
        reply = daemon_round_trip(paths, {"op": "__status__"})
        assert reply is not None and reply["ok"] is True
        # And its DISCOVERY identity survives: the recorded identity is
        # untouched, so the liveness contract still reports the winner.
        assert host_platform().daemon_pid(paths) == os.getpid()


def test_stop_op_unpublishes_the_endpoints_and_frees_the_slot(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=no_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch) as thread:
        reply = daemon_round_trip(paths, {"op": "__stop__"})
        assert reply is not None and reply["ok"] is True
        thread.join(timeout=5)

    assert host_platform().daemon_pid(paths) is None
    assert _unpublished(paths)


def test_the_first_live_op_launches_the_session_lazily_and_reuses_it(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # The whole lazy-launch lifecycle through the REAL loop (ADR-0017): no session
    # at bind time; the first live op launches one via the seam; the second op
    # reuses it without relaunching.
    calls = {"n": 0}
    session = _ServedSession()

    def _launch(*args, **kwargs):
        calls["n"] += 1
        return session

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        assert calls["n"] == 0  # binding alone launches nothing
        first = daemon_round_trip(paths, {"op": "game-tree", "params": {}})
        second = daemon_round_trip(paths, {"op": "perf-monitors", "params": {}})

    assert first is not None and first["stdout"] == "served:game-tree"
    assert second is not None and second["stdout"] == "served:perf-monitors"
    assert calls["n"] == 1


def test_a_failed_launch_is_the_typed_engine_session_not_running(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    def _launch(*args, **kwargs):
        return None

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        reply = daemon_round_trip(paths, {"op": "game-tree", "params": {}})

    assert reply is not None
    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )


def test_a_session_dying_mid_request_reports_disconnect_then_relaunches(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # Death mid-request, end to end: the session passes the liveness check, its
    # connection breaks during the relay (the real EngineSession.request maps
    # that to engine_disconnected), the engine process then dies, and the NEXT
    # live op relaunches through the seam and serves.
    ours, theirs = socket.socketpair()
    theirs.close()  # the harness end is gone: the relay write breaks mid-request
    proc = FakeProc(returncode=None)  # alive at the pre-request liveness check
    dying = EngineSession(proc, conn=ours)

    launches: list = []

    def _launch(*args, **kwargs):
        launches.append(kwargs.get("log_file"))
        if len(launches) == 1:
            return dying
        return _ServedSession()

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        first = daemon_round_trip(paths, {"op": "game-tree", "params": {}})
        proc.returncode = 1  # the engine process is now observed dead
        second = daemon_round_trip(paths, {"op": "game-tree", "params": {}})

    assert first is not None
    assert parse_result(first["stdout"])["error"]["code"] == "engine_disconnected"
    assert second is not None and second["stdout"] == "served:game-tree"
    assert len(launches) == 2
    # Every launch was asked to log to the one DaemonPaths-derived path (#674).
    assert launches == [paths.session_log, paths.session_log]


def test_wait_ready_launches_once_and_reports_the_bounded_wait(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #657 over the real socket: the wait-ready op IS the first live op — it
    # launches through the seam with the caller's bound as the harness-connect
    # timeout and reports launched=true; a repeat while the session is alive is
    # idempotent (launched=false, no relaunch).
    launches: list = []
    # A measured launch whose game printed nothing before the handshake: an
    # empty log and a bound of zero (#848).
    session = _ServedSession(handshake_log_size=0)

    def _launch(*args, **kwargs):
        launches.append(kwargs.get("deadline"))
        paths.session_log.write_text("", encoding="utf-8")
        return session

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        asked = time.monotonic()
        first = daemon_round_trip(
            paths, {"op": "daemon-wait-ready", "params": {"timeout": 7.5}}
        )
        again = daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})

    assert first is not None
    verdict = parse_result(first["stdout"])
    # The startup verdict rides success (#848); this launch measured an empty
    # log at the handshake, so nothing is recognized against the start it
    # reports.
    assert verdict == {
        "pid": os.getpid(),
        "launched": True,
        "startup_diagnostics": [],
        "clean_start": True,
    }
    assert again is not None
    assert parse_result(again["stdout"])["launched"] is False
    # One launch, and what reaches the launcher is the caller's own DEADLINE —
    # an instant it cannot outlive, not a duration it could restart (#725
    # re-review). It is no later than 7.5s after the request was made, and (with
    # nothing to retire here) not meaningfully earlier either.
    assert len(launches) == 1
    # The slack is the request's own transit: the daemon starts the clock when it
    # RECEIVES the call, so the instant is 7.5s from there, not from here.
    assert asked < launches[0] <= asked + 7.5 + SCHEDULING_SLACK_S


def test_status_reports_the_minted_session_identity_across_the_lifecycle(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #660 over the real loop: no identity before a launch; the launch boundary
    # MINTS one and hands it to the launcher (the daemon is the authority for
    # what it launches); `__status__` reports the SAME value while the session
    # lives AND after it dies — a crashed session stays correlatable, like the
    # log ops keep it diagnosable — and a relaunch mints a fresh one.
    minted: list = []
    sessions: list = []

    class _Mortal(_ServedSession):
        def __init__(self, session_id: str) -> None:
            super().__init__(session_id)
            self.dead = False

        def alive(self) -> bool:
            return not self.dead

    def _launch(*args, **kwargs):
        minted.append(kwargs["session_id"])
        session = _Mortal(kwargs["session_id"])
        sessions.append(session)
        return session

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        before = daemon_round_trip(paths, {"op": "__status__"})
        daemon_round_trip(paths, {"op": "game-tree", "params": {}})  # the lazy launch
        alive_status = daemon_round_trip(paths, {"op": "__status__"})
        sessions[0].dead = True  # the session dies, nothing has replaced it yet
        dead_status = daemon_round_trip(paths, {"op": "__status__"})
        daemon_round_trip(paths, {"op": "game-tree", "params": {}})  # the relaunch
        relaunched = daemon_round_trip(paths, {"op": "__status__"})

    assert before is not None and before["session_id"] is None
    assert len(minted) == 2
    first, second = minted
    # An opaque daemon-minted identity: 16 lowercase hex chars, fresh per launch.
    assert isinstance(first, str) and len(first) == 16
    assert set(first) <= set("0123456789abcdef")
    assert alive_status is not None and alive_status["session_id"] == first
    assert dead_status is not None and dead_status["session_id"] == first
    assert relaunched is not None and relaunched["session_id"] == second
    assert second != first


def test_a_failed_replacement_launch_retains_the_last_established_identity(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #746 review ARC-746-001: retirement drops the session OBJECT before the
    # replacement launch, so the identity must live in a read model written only
    # on success — a failed replacement replaces nothing and must not erase the
    # identity `daemon status` promised to keep readable until replacement.
    minted: list = []
    sessions: list = []

    class _Mortal(_ServedSession):
        def __init__(self, session_id: str) -> None:
            super().__init__(session_id)
            self.dead = False

        def alive(self) -> bool:
            return not self.dead

    def _launch(*args, **kwargs):
        minted.append(kwargs["session_id"])
        if len(minted) == 2:
            return None  # the replacement launch FAILS
        session = _Mortal(kwargs["session_id"])
        sessions.append(session)
        return session

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        daemon_round_trip(paths, {"op": "game-tree", "params": {}})  # establish
        sessions[0].dead = True
        failed = daemon_round_trip(paths, {"op": "game-tree", "params": {}})  # fails
        retained = daemon_round_trip(paths, {"op": "__status__"})
        recovered = daemon_round_trip(
            paths, {"op": "game-tree", "params": {}}
        )  # succeeds
        replaced = daemon_round_trip(paths, {"op": "__status__"})

    assert failed is not None
    assert (
        parse_result(failed["stdout"])["error"]["code"] == "engine_session_not_running"
    )
    assert len(minted) == 3
    # dead -> failed replacement -> the OLD identity is retained...
    assert retained is not None and retained["session_id"] == minted[0]
    # ...and only the successful replacement publishes the new one.
    assert recovered is not None and recovered["stdout"] == "served:game-tree"
    assert replaced is not None and replaced["session_id"] == minted[2]
    assert replaced["session_id"] != minted[0]


# The startup verdict (#848) is a per-session read model, written beside the
# identity above and governed by the same two rules. Both are pinned here rather
# than left to the field descriptions, because both survived a whole-suite run as
# plausible one-line regressions: refreshing the verdict only when it is unset,
# and writing it before the launch is known to have succeeded.

# One recognized parse failure — enough to tell one launch's verdict from
# another's, which is all these two tests compare.
_BROKEN_STARTUP_LOG = (
    "Godot Engine v4.6.3.stable.official - https://godotengine.org\n"
    "\n"
    'ERROR: Failed to load script "res://main.gd" with error "Parse error".\n'
    "   at: load (modules/gdscript/gdscript.cpp:2907)\n"
)


class _MortalSession(_ServedSession):
    """A fake session that can be declared dead, forcing a relaunch."""

    def __init__(
        self, session_id: str, handshake_log_size: "int | None" = None
    ) -> None:
        super().__init__(session_id, handshake_log_size)
        self.dead = False

    def alive(self) -> bool:
        return not self.dead


def test_a_relaunch_replaces_the_previous_sessions_startup_verdict(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # A session is relaunched to pick up on-disk edits (ADR-0017), so the verdict
    # MUST be re-read per established session: reporting the retired session's
    # would tell a caller their fix did not take. Mirrors what
    # `test_status_reports_the_minted_session_identity_across_the_lifecycle`
    # pins for `session_id` — the two are written at the same place and must
    # describe the same session.
    launched: list = []
    sessions: list = []

    def _launch(*args, **kwargs):
        # Broken on the first launch, fixed on the second — as an edit between
        # the two would leave it.
        text = _BROKEN_STARTUP_LOG if not launched else ""
        paths.session_log.write_text(text, encoding="utf-8")
        launched.append(kwargs["session_id"])
        session = _MortalSession(
            kwargs["session_id"], handshake_log_size=len(text.encode("utf-8"))
        )
        sessions.append(session)
        return session

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        first = daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})
        sessions[0].dead = True
        second = daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})
        after = daemon_round_trip(paths, {"op": "__status__"})

    assert len(launched) == 2
    assert first is not None
    broken = parse_result(first["stdout"])
    assert broken["launched"] is True
    assert broken["clean_start"] is False
    assert [error["path"] for error in broken["startup_diagnostics"]] == [
        "res://main.gd"
    ]
    # The relaunch reports ITS OWN startup, not the retired session's.
    assert second is not None
    fixed = parse_result(second["stdout"])
    assert fixed["launched"] is True
    assert fixed["clean_start"] is True
    assert fixed["startup_diagnostics"] == []
    # And `daemon status` agrees: one verdict per daemon, always the last
    # ESTABLISHED session's.
    assert after is not None
    assert after["clean_start"] is True
    assert after["startup_diagnostics"] == []


def test_a_failed_replacement_launch_retains_the_previous_startup_verdict(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # The retention rule the verdict inherits from `session_id` (PR #746 review
    # ARC-746-001): a FAILED replacement replaced nothing, so the verdict of the
    # session it did not replace stays readable. The failing direction is not
    # hypothetical — `launch_session` TRUNCATES the Session log before every
    # attempt (#345 finding 2), so a verdict written before the success guard
    # would read that failed attempt's empty log and report a clean start for a
    # session that never came up.
    attempts: list = []
    sessions: list = []

    def _launch(*args, **kwargs):
        attempts.append(kwargs["session_id"])
        failing = len(attempts) == 2
        # What the real launcher does on EVERY attempt, failed ones included.
        text = "" if failing else _BROKEN_STARTUP_LOG
        paths.session_log.write_text(text, encoding="utf-8")
        if failing:
            return None
        session = _MortalSession(
            kwargs["session_id"], handshake_log_size=len(text.encode("utf-8"))
        )
        sessions.append(session)
        return session

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})  # establish
        sessions[0].dead = True
        failed = daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})
        retained = daemon_round_trip(paths, {"op": "__status__"})

    assert len(attempts) == 2
    assert failed is not None
    assert (
        parse_result(failed["stdout"])["error"]["code"] == "engine_session_not_running"
    )
    # The retired session's verdict survives the launch that did not replace it.
    assert retained is not None
    assert retained["clean_start"] is False
    assert [error["path"] for error in retained["startup_diagnostics"]] == [
        "res://main.gd"
    ]


def test_launch_session_places_the_identity_on_the_harness_tail(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # The identity travels to the harness on the existing launch tail (#660):
    # LAST, after the marker, socket, token, and scene selector — positional and
    # bounds-checked harness-side, so an older harness ignores it.
    spawned = fake_session_spawn(monkeypatch)
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    listener = cast(socket.socket, FakeHarnessListener())

    # Only the spawn matters here, so no harness endpoint is bound: the listener
    # refuses at once and the deadline only outlives the pre-spawn work (#996).
    outcome = launch_session(
        paths.project,
        "godot",
        listener,
        paths.harness_socket,
        "expected-token",
        deadline=time.monotonic() + LAUNCH_DEADLINE_S,
        scene="res://main.tscn",
        session_id="a1b2c3d4e5f60718",
        platform=host_platform(),
    )

    assert outcome is None  # nothing connected — only the spawn matters here
    assert len(spawned) == 1
    tail = spawned[0][spawned[0].index(LAUNCH_MARKER) :]
    assert tail == [
        LAUNCH_MARKER,
        host_platform().harness_argument(listener, paths.harness_socket),
        "expected-token",
        "res://main.tscn",
        "a1b2c3d4e5f60718",
    ]


def test_wait_ready_relays_the_typed_launch_failure(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # The wait shares the live ops' one launch boundary, so a failed launch is
    # the same typed refusal a live op gets — not a bespoke wait-ready error.
    def _launch(*args, **kwargs):
        return None

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        reply = daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})

    assert reply is not None
    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )


def test_a_silent_handshake_peer_cannot_hold_the_launch_past_the_deadline(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 1, at the launcher: ONE monotonic deadline spans
    # accept, the token frame, and the verification frame. A peer that connects
    # and then never speaks used to block the token read forever — here the
    # REAL launch_session must give up within the bound and record why.
    fake_session_spawn(monkeypatch)
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    diagnostics: list[str] = []
    with bound_endpoints(paths) as (_cli, listener, _token):
        silent = harness_peer(listener, paths)  # queued for the launch's accept
        started = time.monotonic()
        try:
            outcome = launch_session(
                paths.project,
                "godot",
                listener,
                paths.harness_socket,
                "expected-token",
                deadline=time.monotonic() + 0.3,
                diagnostics=diagnostics,
                platform=host_platform(),
            )
            elapsed = time.monotonic() - started
        finally:
            silent.close()

    assert outcome is None
    assert elapsed < 3.0, f"the silent peer held the launch for {elapsed:.1f}s"
    assert any("no auth token" in reason for reason in diagnostics)


def test_a_launch_skips_a_wrong_peer_where_other_processes_reach_the_harness(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # ADR-0047: where any local process can reach the harness endpoint (loopback
    # TCP on Windows), a peer that presents a wrong token is not the engine. The
    # launch drops it and accepts the next connection within the same deadline,
    # so a queued stranger cannot retire the real launch. The reachability is
    # the Windows adapter's answer; it is stated here so every platform tests
    # the branch. The other branch is in test_daemon_diag.
    fake_session_spawn(monkeypatch)
    stub_daemon_platform(monkeypatch, other_processes_reach_harness=True)
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    with bound_endpoints(paths) as (_cli, listener, _token):
        stranger = harness_peer(listener, paths)  # queued first
        write_frame(stranger, b"another-token")
        harness = harness_peer(listener, paths)
        write_frame(harness, b"expected-token")
        write_frame(harness, b'{"scene_ok": true, "current": "res://main.tscn"}')

        try:
            session = launch_session(
                paths.project,
                "godot",
                listener,
                paths.harness_socket,
                "expected-token",
                deadline=time.monotonic() + 2.0,
                platform=host_platform(),
            )
        finally:
            stranger.close()
            harness.close()

    assert session is not None
    session.close()


@pytest.mark.parametrize("frame", ["token", "verification"])
def test_a_trickling_handshake_peer_cannot_hold_the_launch_past_the_deadline(
    tmp_path, daemon_runtime_dir, monkeypatch, frame
):
    # #725 re-review finding 1: silence is not the only way to hold the reader.
    # A socket timeout bounds each recv, so a peer that sends ONE BYTE just
    # inside it restarts the clock on every chunk and the frame never ends. Both
    # handshake frames are read in chunks, so both are exposed; the deadline has
    # to be recomputed per recv, not set once per frame. Measured before the fix
    # at a 0.04s/byte trickle on a 0.05s bound: 0.7s for the token frame, 2.1s
    # for the verification frame — and the trickle rate is the peer's to choose.
    fake_session_spawn(monkeypatch)
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    with bound_endpoints(paths) as (_cli, listener, _token):
        peer = harness_peer(listener, paths)

        def _trickle() -> None:
            if frame == "verification":
                write_frame(peer, b"expected-token")  # the token frame arrives whole
                body = b'{"scene_ok": true, "current": "res://main.tscn"}'
            else:
                body = b"expected-token"
            wire = len(body).to_bytes(4, "big") + body
            for byte in wire:  # each byte lands inside the 0.05s bound, resetting it
                try:
                    peer.sendall(bytes([byte]))
                except OSError:
                    return
                time.sleep(0.04)

        trickler = threading.Thread(target=_trickle, daemon=True)
        trickler.start()
        started = time.monotonic()
        try:
            outcome = launch_session(
                paths.project,
                "godot",
                listener,
                paths.harness_socket,
                "expected-token",
                deadline=time.monotonic() + 0.05,
                platform=host_platform(),
            )
            elapsed = time.monotonic() - started
        finally:
            peer.close()
            trickler.join(timeout=5)

    assert outcome is None
    assert elapsed < 0.5, f"the trickling peer held the launch for {elapsed:.2f}s"


def test_a_slow_spawn_cannot_revive_the_callers_expired_deadline(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 third re-review: the launcher used to take a DURATION and start its own
    # clock with it — after truncating the log and spawning the engine. So the
    # spawn was charged to nobody and an exhausted budget came back whole: a
    # 0.05s-bounded launch whose spawn alone took 0.12s still SUCCEEDED, with both
    # handshake frames already queued. It takes the caller's absolute instant now,
    # so a spawn that outruns the budget ends in a refusal, not a session.
    def _slow_spawn(argv, deadline):
        time.sleep(0.12)  # a spawn that costs more than the whole budget
        return FakeProc(returncode=None)

    stub_daemon_platform(monkeypatch, spawn_session=_slow_spawn)
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    with bound_endpoints(paths) as (_cli, listener, _token):
        peer = harness_peer(listener, paths)
        # Both frames are ALREADY waiting, so nothing but the clock can refuse this.
        write_frame(peer, b"expected-token")
        write_frame(peer, b'{"scene_ok": true, "current": "res://main.tscn"}')

        try:
            outcome = launch_session(
                paths.project,
                "godot",
                listener,
                paths.harness_socket,
                "expected-token",
                deadline=time.monotonic() + 0.05,
                platform=host_platform(),
            )
        finally:
            peer.close()

    assert outcome is None


def test_launch_preparation_that_crosses_the_deadline_spawns_nothing(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 fourth re-review: the deadline was gated BEFORE the Session-log
    # truncation but not after it. That truncation is a filesystem write and can
    # block, so a 0.12s write against a 0.05s deadline still reached `Popen` —
    # 0.076s past the bound. The gate belongs at the last interruptible point.
    spawned = fake_session_spawn(monkeypatch)
    real_write = Path.write_bytes

    def _slow_write(self, data):
        time.sleep(0.12)
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", _slow_write)
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    diagnostics: list[str] = []
    with bound_endpoints(paths) as (_cli, listener, _token):
        outcome = launch_session(
            paths.project,
            "godot",
            listener,
            paths.harness_socket,
            "expected-token",
            log_file=paths.session_log,
            deadline=time.monotonic() + 0.05,
            diagnostics=diagnostics,
            platform=host_platform(),
        )

    assert outcome is None
    assert not spawned, "the engine was started after the deadline had passed"
    assert any("preparing the launch" in reason for reason in diagnostics), diagnostics


def test_a_deadline_spent_by_the_spawn_is_not_blamed_on_the_harness(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 fourth re-review: the spawn is the one uninterruptible step, so it CAN
    # outrun the budget — but the refusal has to say so. It used to fall through
    # and report that the harness sent no auth token, which is a different
    # failure and plainly false here: the token is already queued.
    def _slow_spawn(argv, deadline):
        time.sleep(0.12)
        return FakeProc(returncode=None)

    stub_daemon_platform(monkeypatch, spawn_session=_slow_spawn)
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    diagnostics: list[str] = []
    with bound_endpoints(paths) as (_cli, listener, _token):
        peer = harness_peer(listener, paths)
        write_frame(peer, b"expected-token")
        write_frame(peer, b'{"scene_ok": true, "current": "res://main.tscn"}')

        try:
            outcome = launch_session(
                paths.project,
                "godot",
                listener,
                paths.harness_socket,
                "expected-token",
                deadline=time.monotonic() + 0.05,
                diagnostics=diagnostics,
                platform=host_platform(),
            )
        finally:
            peer.close()

    assert outcome is None
    assert any("while the engine was starting" in r for r in diagnostics), diagnostics
    assert not any("auth token" in r for r in diagnostics), diagnostics


def test_the_live_clients_ceiling_covers_the_whole_round_trip(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 re-review: the client set the socket timeout once and read the reply
    # in as many chunks as the daemon sent, so its published 60s was a per-recv
    # INACTIVITY timeout, not a round-trip ceiling — a trickling daemon could
    # hold the CLI indefinitely. Same absolute-instant rule as every other read.
    monkeypatch.setattr("gda.daemon.client.LIVE_REQUEST_TIMEOUT", 0.3)
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    with bound_endpoints(paths) as (listener, _harness, token):

        def _trickle() -> None:
            conn, _ = listener.accept()
            host_platform().admit(conn, token)
            read_message(conn)
            body = build_result({"ok": True}).encode("utf-8")
            wire = len(body).to_bytes(4, "big") + body
            for byte in wire:  # each byte lands inside the bound, resetting it
                try:
                    conn.sendall(bytes([byte]))
                except OSError:
                    return
                time.sleep(0.2)

        daemon = threading.Thread(target=_trickle, daemon=True)
        daemon.start()
        started = time.monotonic()
        try:
            # The request leg itself: daemon discovery is not what is under test.
            result = DaemonRunner(paths.project)._request(paths, "game-tree", {})
            elapsed = time.monotonic() - started
        finally:
            listener.close()
            daemon.join(timeout=5)

    assert elapsed < 0.3 + SCHEDULING_SLACK_S, (
        f"the trickled reply held the CLI for {elapsed:.2f}s"
    )
    assert parse_result(result.stdout)["error"]["code"] == "live_timeout"


def test_the_live_client_write_uses_only_the_round_trip_budget_left(monkeypatch):
    # #725 re-review: passing the absolute instant only to the reply read left
    # connect and request send on independent full socket timeouts. Work in the
    # first leg therefore gave the second a fresh grace, despite the published
    # whole-round-trip ceiling.
    send_timeouts: list[float] = []

    class _AccumulatingSocket:
        timeout = 0.0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def settimeout(self, timeout: float) -> None:
            self.timeout = timeout

        def sendall(self, data: bytes) -> None:
            send_timeouts.append(self.timeout)
            time.sleep(self.timeout)
            raise TimeoutError

    def _slow_connect(paths, deadline):
        time.sleep(0.06)  # the connect leg spends part of the one budget
        return _AccumulatingSocket()

    monkeypatch.setattr("gda.daemon.client.LIVE_REQUEST_TIMEOUT", 0.1)
    # The seam's connect, so the write leg under test gets this socket on either
    # adapter.
    stub_daemon_platform(monkeypatch, connect=_slow_connect)
    started = time.monotonic()
    result = DaemonRunner(Path("."))._request(
        daemon_paths(Path("."), platform=host_platform()), "game-tree", {}
    )
    elapsed = time.monotonic() - started

    assert send_timeouts, "the request was never written"
    assert 0 < send_timeouts[0] < 0.08, (
        f"the write received a fresh {send_timeouts[0]:.3f}s timeout"
    )
    assert elapsed < 0.1 + SCHEDULING_SLACK_S
    assert parse_result(result.stdout)["error"]["code"] == "live_timeout"


def test_a_stuck_handshake_does_not_freeze_the_daemon(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 1, end to end: the REAL launch_session runs inside the
    # serve loop while a peer occupies the harness socket silently. wait-ready
    # must come back typed within its bound, and — the daemon serving one
    # request at a time — the NEXT control request must still be served.
    fake_session_spawn(monkeypatch)
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", platform=host_platform()
    )  # the real launch seam default

    with serving_daemon(server, paths, monkeypatch):
        silent = harness_peer(cast(socket.socket, server._harness_listener), paths)
        try:
            reply = daemon_round_trip(
                paths,
                {"op": "daemon-wait-ready", "params": {"timeout": 0.3}},
                timeout=10.0,
            )
            assert reply is not None
            assert (
                parse_result(reply["stdout"])["error"]["code"]
                == "engine_session_not_running"
            )
            status = daemon_round_trip(paths, {"op": "__status__"})
            assert status is not None and status["ok"] is True
        finally:
            silent.close()


def test_wait_ready_rebuilds_a_session_whose_channel_broke(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 2: a relay that hits a broken harness channel latches
    # the session stale, so the NEXT wait-ready relaunches through the shared
    # boundary instead of reporting a serving state (launched: false) that the
    # very next read disproves — the engine process is still alive throughout.
    ours, theirs = socket.socketpair()
    theirs.close()
    zombie = EngineSession(FakeProc(returncode=None), conn=ours)

    launches: list = []

    def _launch(*args, **kwargs):
        launches.append(1)
        return zombie if len(launches) == 1 else _ServedSession()

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        first = daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})
        read = daemon_round_trip(paths, {"op": "game-tree", "params": {}})
        second = daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})
        served = daemon_round_trip(paths, {"op": "game-tree", "params": {}})

    assert first is not None and parse_result(first["stdout"])["launched"] is True
    assert read is not None
    assert parse_result(read["stdout"])["error"]["code"] == "engine_disconnected"
    assert second is not None and parse_result(second["stdout"])["launched"] is True
    assert served is not None and served["stdout"] == "served:game-tree"
    assert len(launches) == 2


def test_wait_ready_rebuilds_a_session_whose_relay_timed_out(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 re-review finding 1, through the daemon: a relay that times out leaves
    # the channel response-ambiguous (no request id, the frame is never drained),
    # so wait-ready must NOT certify it. Before the fix the daemon reported
    # `launched: false` over that channel and the next read went back to it.
    monkeypatch.setattr("gda.daemon.session.OP_TIMEOUT", 0.2)
    ours, silent_harness = socket.socketpair()
    desynced = EngineSession(FakeProc(returncode=None), conn=ours)

    launches: list = []

    def _launch(*args, **kwargs):
        launches.append(1)
        return desynced if len(launches) == 1 else _ServedSession()

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    try:
        with serving_daemon(server, paths, monkeypatch):
            first = daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})
            timed_out = daemon_round_trip(paths, {"op": "game-tree", "params": {}})
            second = daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})
            served = daemon_round_trip(paths, {"op": "game-tree", "params": {}})
    finally:
        silent_harness.close()

    assert first is not None and parse_result(first["stdout"])["launched"] is True
    assert timed_out is not None
    assert parse_result(timed_out["stdout"])["error"]["code"] == "live_timeout"
    assert second is not None and parse_result(second["stdout"])["launched"] is True
    assert served is not None and served["stdout"] == "served:game-tree"
    assert len(launches) == 2


def test_launched_is_reported_by_the_launch_owner(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 3 (TOCTOU): the launch fact travels WITH the launch
    # decision. A liveness that flips between two samples must never yield a
    # call that launched yet reported launched: false — the invariant is
    # "launched == (a launch actually happened on this call)".
    class _FlipSession(_ServedSession):
        def __init__(self) -> None:
            super().__init__()
            self.polls = 0

        def alive(self) -> bool:
            self.polls += 1
            return self.polls == 1  # alive at the first sample, gone at the next

    launches: list = []
    flip = _FlipSession()

    def _launch(*args, **kwargs):
        launches.append(1)
        return flip if len(launches) == 1 else _ServedSession()

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        first = daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})
        second = daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})

    assert first is not None and parse_result(first["stdout"])["launched"] is True
    assert second is not None
    launched_second = parse_result(second["stdout"])["launched"]
    assert launched_second == (len(launches) == 2), (
        f"launched={launched_second} but launches={len(launches)} — the reported "
        "fact desynced from what the launch owner actually did"
    )


def test_every_declared_daemon_served_op_is_intercepted_not_relayed(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 4: DAEMON_SERVED_OPS is the routing authority, so a
    # mutation that declares an op daemon-served without intercepting it must
    # fail HERE — every member is driven through the real loop with a session
    # cached, and none may reach the session's relay.
    class _RecordingSession(_ServedSession):
        def __init__(self) -> None:
            super().__init__()
            self.relayed: list[str] = []

        def request(self, operation: str, params: dict) -> dict:
            self.relayed.append(operation)
            return super().request(operation, params)

    session = _RecordingSession()

    def _launch(*args, **kwargs):
        return session

    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        primed = daemon_round_trip(paths, {"op": "daemon-wait-ready", "params": {}})
        assert primed is not None
        for op in DAEMON_SERVED_OPS:
            reply = daemon_round_trip(paths, {"op": op, "params": {}})
            assert reply is not None, op

    assert session.relayed == []


def test_the_wire_boundary_re_enforces_the_wait_ready_bound(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # #725 review finding 4: the finite (0, 50] rule holds at the IPC boundary
    # too — this socket can be driven by clients other than gda's CLI, and an
    # unbounded or non-finite value would defeat the bound the op promises.
    paths = daemon_paths(runnable_project(tmp_path), platform=host_platform())
    server = DaemonServer(
        paths, godot="godot", launch=no_launch, platform=host_platform()
    )

    with serving_daemon(server, paths, monkeypatch):
        for bad in (-1, 0, 1000, float("inf"), float("nan"), True, "10"):
            reply = daemon_round_trip(
                paths, {"op": "daemon-wait-ready", "params": {"timeout": bad}}
            )
            assert reply is not None, bad
            assert parse_result(reply["stdout"])["error"]["code"] == "invalid_params", (
                bad
            )
