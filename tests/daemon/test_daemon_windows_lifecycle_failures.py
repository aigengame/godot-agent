"""The Windows daemon-lifecycle failures report the code of their recovery (#1162).

Fast tests for the five failures ADR-0047's lifecycle refuses on Windows, each
pinned to the registered code whose description states its recovery: an unusable
runtime directory (``daemon_runtime_unusable``), a lifecycle operation that another
one blocks (``daemon_lifecycle_busy``), a slot owner that does not answer or does
not retire (``daemon_unresponsive``), and a failed start whose rollback could not
take the slot, which keeps ``daemon_not_running``.

The platform is faked (``sys.platform``) and the Windows discovery primitives are
stubbed at the recipe's seams, because the real primitives need the Win32 API.
The ACL, lock-byte and TCP boundaries themselves are proven by the Windows-only
e2e in ``test_e2e_daemon_lifecycle``; here the subject is which code each refusal
mints and what its message names.
"""

import contextlib
import sys
import time
from pathlib import Path

import pytest

import gda.commands.daemon as daemon_ops
import gda.daemon.client as client
from gda.core.engine.execution import ExecutionKind, live_stack_supported
from gda.core.engine.sentinel import parse_result
from gda.core.failure.catalog import Failure
from gda.core.failure.error_codes import ERROR_CODE_BY_CODE
from gda.daemon.discovery import daemon_paths
from gda.daemon.host import host_platform
from gda.daemon.protocol import CONTROL_TIMEOUT, LIVE_REQUEST_TIMEOUT
from gda.daemon.server import STATUS_OP
from gda.daemon.windows_discovery import WindowsEndpoint
from tests.support import stub_daemon_platform

_OK_VERSION = lambda binary: (4, 6)  # noqa: E731


@pytest.fixture
def windows(monkeypatch, tmp_path):
    """Fake the Windows platform and give its discovery a private runtime root."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="t"\n'
        'run/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
    return project


def _start(project, **kw):
    return daemon_ops.run_daemon_start_operation(
        project,
        None,
        spawn=lambda p, b, w, s: None,
        version_check=_OK_VERSION,
        **kw,
    )


def _failure(outcome) -> Failure:
    assert isinstance(outcome, Failure), outcome
    return outcome


def _no_reply(paths, request, deadline, platform):
    """A daemon that accepts the connection and does not answer."""
    return None


def _refuse(paths, request, deadline, platform):
    """A published endpoint at which nothing listens."""
    raise ConnectionRefusedError(111, "Connection refused")


def _answer_as(pid):
    return lambda paths, request, deadline, platform: {"ok": True, "pid": pid}


# --- daemon_runtime_unusable: fix the directory ---------------------------------


def test_an_unusable_runtime_directory_is_refused_before_any_daemon_state(
    windows, monkeypatch
):
    paths = daemon_paths(windows, platform=host_platform())
    paths.runtime_dir.mkdir(parents=True)

    def shared(directory):
        raise PermissionError("Daemon runtime must not use a reparse point")

    def state_read(paths):
        raise AssertionError("the refusal must precede every daemon-state read")

    monkeypatch.setattr("gda.daemon.windows.ensure_private_runtime", shared)
    stub_daemon_platform(monkeypatch, daemon_pid=state_read)
    monkeypatch.setattr("gda.daemon.windows.lock_held", state_read)

    failed = _failure(daemon_ops.run_daemon_status_operation(windows))

    assert failed.error.code == "daemon_runtime_unusable"
    assert str(paths.runtime_dir) in failed.error.message


def test_a_live_operation_reports_the_unusable_runtime_directory(windows, monkeypatch):
    paths = daemon_paths(windows, platform=host_platform())

    def unreadable(paths):
        raise PermissionError("Daemon runtime path has the wrong file type")

    stub_daemon_platform(monkeypatch, daemon_pid=unreadable)

    result = client.DaemonRunner(windows).run("game-tree", {})

    error = parse_result(result.stdout)["error"]
    assert error["code"] == "daemon_runtime_unusable"
    assert str(paths.runtime_dir) in error["message"]


def test_a_start_refuses_a_runtime_directory_it_cannot_make_private_before_the_install(
    windows, monkeypatch
):
    # The directory does not exist yet, so the opening check passes. The start
    # then creates it private, and refuses it before the project changes.
    monkeypatch.setattr(
        daemon_ops,
        "acquire_harness_lock",
        lambda paths, timeout: contextlib.nullcontext(),
    )
    stub_daemon_platform(monkeypatch, daemon_pid=lambda paths: None)
    monkeypatch.setattr("gda.daemon.windows.lock_held", lambda paths: False)

    def shared(directory):
        raise PermissionError("Daemon runtime must not use a reparse point")

    monkeypatch.setattr("gda.daemon.windows.ensure_private_runtime", shared)

    failed = _failure(
        daemon_ops.run_daemon_start_operation(
            windows, "godot", spawn=lambda p, b, w, s: None, version_check=_OK_VERSION
        )
    )

    assert failed.error.code == "daemon_runtime_unusable"
    assert (
        str(daemon_paths(windows, platform=host_platform()).runtime_dir)
        in failed.error.message
    )
    assert not (windows / "addons").exists()


# --- daemon_lifecycle_busy: wait, then retry ---------------------------------------


def test_a_held_harness_transaction_is_busy(windows, monkeypatch):
    def occupied(paths, timeout):
        raise TimeoutError("the Windows harness transaction is occupied")

    monkeypatch.setattr(daemon_ops, "acquire_harness_lock", occupied)

    failed = _failure(_start(windows))

    assert failed.error.code == "daemon_lifecycle_busy"
    assert "harness transaction" in failed.error.message


def test_a_held_slot_with_no_endpoint_is_busy(windows, monkeypatch):
    monkeypatch.setattr(
        daemon_ops,
        "acquire_harness_lock",
        lambda paths, timeout: contextlib.nullcontext(),
    )
    stub_daemon_platform(monkeypatch, daemon_pid=lambda paths: None)
    monkeypatch.setattr("gda.daemon.windows.lock_held", lambda paths: True)

    failed = _failure(_start(windows))

    assert failed.error.code == "daemon_lifecycle_busy"
    assert "no daemon endpoint is published" in failed.error.message


def test_an_uninstall_while_the_slot_is_held_with_no_endpoint_is_busy(
    windows, monkeypatch
):
    monkeypatch.setattr(
        daemon_ops,
        "acquire_harness_lock",
        lambda paths, timeout: contextlib.nullcontext(),
    )
    monkeypatch.setattr("gda.daemon.windows.lock_held", lambda paths: True)
    stub_daemon_platform(monkeypatch, daemon_pid=lambda paths: None)

    failed = _failure(daemon_ops.run_daemon_uninstall_operation(windows))

    assert failed.error.code == "daemon_lifecycle_busy"
    assert "no daemon endpoint is published" in failed.error.message


def test_a_record_at_which_no_daemon_accepts_a_connection_is_busy(windows, monkeypatch):
    # The endpoint record outlives its daemon: a process the OS ended ran no
    # cleanup, and a retiring daemon closes its listeners before it removes the
    # record; the next slot owner publishes its own only after it binds. So a held
    # slot whose record names a port nothing listens at is a lifecycle operation
    # in progress, not a daemon that does not answer (the native
    # `test_stale_metadata_cannot_identify_a_successor_before_publication`).
    monkeypatch.setattr(
        daemon_ops,
        "acquire_harness_lock",
        lambda paths, timeout: contextlib.nullcontext(),
    )
    stub_daemon_platform(monkeypatch, daemon_pid=lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _refuse)

    failed = _failure(_start(windows))

    assert failed.error.code == "daemon_lifecycle_busy"
    assert "4242" in failed.error.message
    assert "no daemon accepts a connection" in failed.error.message


def test_a_stop_at_a_record_no_daemon_accepts_a_connection_at_is_busy(
    windows, monkeypatch
):
    stub_daemon_platform(monkeypatch, daemon_pid=lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _refuse)

    failed = _failure(daemon_ops.run_daemon_stop_operation(windows))

    assert failed.error.code == "daemon_lifecycle_busy"
    assert "4242" in failed.error.message


def test_an_uninstall_at_a_record_no_daemon_accepts_a_connection_at_is_busy(
    windows, monkeypatch
):
    monkeypatch.setattr(
        daemon_ops,
        "acquire_harness_lock",
        lambda paths, timeout: contextlib.nullcontext(),
    )
    monkeypatch.setattr("gda.daemon.windows.lock_held", lambda paths: True)
    stub_daemon_platform(monkeypatch, daemon_pid=lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _refuse)

    failed = _failure(daemon_ops.run_daemon_uninstall_operation(windows))

    assert failed.error.code == "daemon_lifecycle_busy"
    assert "4242" in failed.error.message


def test_an_uninstall_under_a_daemon_that_answers_is_refused_as_running(
    windows, monkeypatch
):
    # The owner rule confirms the record's daemon, so the verdict is the one a
    # running daemon gets on every platform: stop it first.
    monkeypatch.setattr(
        daemon_ops,
        "acquire_harness_lock",
        lambda paths, timeout: contextlib.nullcontext(),
    )
    monkeypatch.setattr("gda.daemon.windows.lock_held", lambda paths: True)
    stub_daemon_platform(monkeypatch, daemon_pid=lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _answer_as(4242))

    failed = _failure(daemon_ops.run_daemon_uninstall_operation(windows))

    assert failed.error.code == "daemon_running"


@pytest.mark.parametrize(
    ("round_trip", "accepted", "reply"),
    [
        (_refuse, False, None),
        (
            lambda paths, request, deadline, platform: (_ for _ in ()).throw(
                FileNotFoundError("no native daemon endpoint is published")
            ),
            False,
            None,
        ),
        (
            lambda paths, request, deadline, platform: (_ for _ in ()).throw(
                TimeoutError()
            ),
            True,
            None,
        ),
        (_no_reply, True, None),
        (_answer_as(4242), True, {"ok": True, "pid": 4242}),
    ],
    ids=["refused", "no-endpoint", "deadline", "no-reply", "answered"],
)
def test_a_control_outcome_tells_no_daemon_from_one_that_does_not_answer(
    windows, monkeypatch, round_trip, accepted, reply
):
    # A refused connection, or no published endpoint, is no daemon at the record;
    # a deadline expiry or a silent daemon is one that accepted and did not answer.
    monkeypatch.setattr(client, "_round_trip", round_trip)

    outcome = client.control_outcome(
        daemon_paths(windows, platform=host_platform()),
        STATUS_OP,
        platform=host_platform(),
    )

    assert (outcome.accepted, outcome.reply) == (accepted, reply)


# --- daemon_unresponsive: confirm the process, then end it by hand -----------------


def test_a_slot_owner_that_does_not_answer_is_unresponsive(windows, monkeypatch):
    monkeypatch.setattr(
        daemon_ops,
        "acquire_harness_lock",
        lambda paths, timeout: contextlib.nullcontext(),
    )
    stub_daemon_platform(monkeypatch, daemon_pid=lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _no_reply)

    failed = _failure(_start(windows))

    assert failed.error.code == "daemon_unresponsive"
    assert "4242" in failed.error.message
    assert "retained" in failed.error.diagnostics


def test_an_uninstall_under_a_slot_owner_that_does_not_answer_is_unresponsive(
    windows, monkeypatch
):
    monkeypatch.setattr(
        daemon_ops,
        "acquire_harness_lock",
        lambda paths, timeout: contextlib.nullcontext(),
    )
    monkeypatch.setattr("gda.daemon.windows.lock_held", lambda paths: True)
    stub_daemon_platform(monkeypatch, daemon_pid=lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _no_reply)

    failed = _failure(daemon_ops.run_daemon_uninstall_operation(windows))

    assert failed.error.code == "daemon_unresponsive"
    assert "4242" in failed.error.message


def test_a_stop_the_owner_does_not_acknowledge_is_unresponsive(windows, monkeypatch):
    stub_daemon_platform(monkeypatch, daemon_pid=lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _no_reply)

    failed = _failure(daemon_ops.run_daemon_stop_operation(windows))

    assert failed.error.code == "daemon_unresponsive"
    assert "4242" in failed.error.message
    assert "acknowledge" in failed.error.message


def test_a_daemon_that_does_not_retire_after_stop_is_unresponsive(windows, monkeypatch):
    stub_daemon_platform(monkeypatch, daemon_pid=lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _answer_as(4242))
    monkeypatch.setattr(daemon_ops, "_await_gone", lambda paths, platform, pid: False)

    failed = _failure(daemon_ops.run_daemon_stop_operation(windows))

    assert failed.error.code == "daemon_unresponsive"
    assert "4242" in failed.error.message
    assert "still held" in failed.error.message


def test_a_windows_control_request_waits_out_one_live_request(windows, monkeypatch):
    # The daemon serves one connection at a time, so a reply wait of the control
    # deadline reports a daemon that is busy with a live request as one that does
    # not answer. The wait is the live-request deadline, which outlasts one live
    # request; the lifecycle commands above pass no bound of their own.
    waits: list[float] = []

    def round_trip(paths, request, deadline, platform):
        waits.append(deadline - time.monotonic())
        return None

    monkeypatch.setattr(client, "_round_trip", round_trip)

    client.control(
        daemon_paths(windows, platform=host_platform()),
        STATUS_OP,
        platform=host_platform(),
    )

    assert waits == [pytest.approx(LIVE_REQUEST_TIMEOUT, abs=1.0)]


def test_a_unix_control_request_keeps_the_control_deadline(monkeypatch, tmp_path):
    # On Unix the lock proves the owner and the reply is not read for it, so the
    # wait stays the control deadline (ADR-0047: Unix behaviour unchanged).
    monkeypatch.setattr(sys, "platform", "linux")
    waits: list[float] = []

    def round_trip(paths, request, deadline, platform):
        waits.append(deadline - time.monotonic())
        return None

    monkeypatch.setattr(client, "_round_trip", round_trip)

    client.control(
        daemon_paths(tmp_path, platform=host_platform()),
        STATUS_OP,
        platform=host_platform(),
    )

    assert waits == [pytest.approx(CONTROL_TIMEOUT, abs=0.5)]


def test_a_stop_is_complete_when_another_daemon_takes_the_slot(windows, monkeypatch):
    # After the stop is acknowledged the slot can pass to a daemon another caller
    # started; the retirement wait tells that daemon from the one that was stopped.
    holders: list[int] = []

    def holder(paths):
        holders.append(4242 if not holders else 4343)
        return holders[-1]

    stub_daemon_platform(monkeypatch, daemon_pid=holder)
    monkeypatch.setattr(client, "_round_trip", _answer_as(4242))

    outcome = daemon_ops.run_daemon_stop_operation(windows)

    assert isinstance(outcome, daemon_ops.DaemonStopResult), outcome
    assert outcome.stopped is True and outcome.pid == 4242


def test_the_unresponsive_recovery_states_no_retry_window():
    # The reply wait outlasts one live request, so the description owns no
    # timing heuristic: its recovery is the by-hand step and nothing else.
    description = ERROR_CODE_BY_CODE["daemon_unresponsive"].description

    assert "live-request deadline" in description
    assert "retry for" not in description.lower()
    assert "seconds" not in description


# --- the published endpoint -------------------------------------------------------


def test_a_windows_status_reports_the_published_loopback_endpoint(windows, monkeypatch):
    # Windows publishes a loopback endpoint record, not a socket path (ADR-0047).
    record = WindowsEndpoint(
        pid=4242, project=windows, cli_port=50123, harness_port=50124, token="t"
    )
    stub_daemon_platform(monkeypatch, daemon_pid=lambda paths: 4242)
    monkeypatch.setattr("gda.daemon.windows.read_endpoint", lambda paths: record)
    monkeypatch.setattr(client, "_round_trip", _answer_as(4242))

    status = daemon_ops.run_daemon_status_operation(windows)

    assert isinstance(status, daemon_ops.DaemonStatusResult), status
    assert status.running is True and status.socket_path is None
    assert status.endpoint is not None
    assert status.endpoint.address == "127.0.0.1:50123"


# --- daemon_not_running keeps the failed start ------------------------------------


def test_a_rollback_that_cannot_take_the_slot_keeps_daemon_not_running(
    windows, monkeypatch
):
    opened = daemon_ops._install_harness_transactionally(windows)
    assert not isinstance(opened, Failure), opened
    paths = daemon_paths(windows, platform=host_platform())

    def held(paths):
        raise PermissionError("the daemon slot is held")

    monkeypatch.setattr(daemon_ops, "acquire_lock", held)

    failed = daemon_ops._failed_start_failure(opened.snapshot, paths)

    assert failed.error.code == "daemon_not_running"
    assert "gda daemon status" in failed.error.diagnostics
    # The winner's install is not removed: the rollback retained it.
    assert (windows / "addons" / "gda_harness" / "gda_harness.gd").exists()


# --- the platform guard reads the published set ---------------------------------------


@pytest.mark.parametrize(
    ("platform", "served"),
    [
        ("linux", True),
        ("darwin", True),
        ("win32", True),
        ("cygwin", False),
        ("freebsd14", False),
        ("sunos5", False),
    ],
)
def test_the_live_guard_serves_exactly_the_published_platforms(
    monkeypatch, platform, served
):
    # One encoding of "which hosts the Live stack serves": the guard reads the
    # platform set `--schema` publishes, keyed by `sys.platform`, so a POSIX host
    # the schema does not list is refused and a Windows host is served on every
    # route, an unknown operation included — the retired allow-list would refuse
    # it (#1124).
    monkeypatch.setattr(sys, "platform", platform)

    for kind, operation in [
        (ExecutionKind.HEADLESS, "daemon-start"),
        (ExecutionKind.HEADLESS, "daemon-status"),
        (ExecutionKind.LIVE, "game-tree"),
        (ExecutionKind.LIVE, "no-such-op"),
    ]:
        assert live_stack_supported(kind, operation) is served, (platform, operation)
    # A command with no live-stack constraint has nothing to refuse.
    assert live_stack_supported(ExecutionKind.HEADLESS, "scene-get") is True


# --- the platform refusal names no transport ------------------------------------------


def test_an_unsupported_platform_refusal_names_no_transport(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "sunos5")

    failed = _failure(daemon_ops.run_daemon_status_operation(Path(tmp_path)))

    assert failed.error.code == "live_unsupported_platform"
    assert "Unix" not in failed.error.message
    assert "UNIX" not in failed.error.message
    assert "socket" not in failed.error.message
