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
import os
import sys
import time
from pathlib import Path

import pytest

import gda.commands.daemon as daemon_ops
import gda.daemon.client as client
from gda.core.engine.sentinel import parse_result
from gda.core.failure.catalog import Failure
from gda.core.failure.error_codes import ERROR_CODE_BY_CODE
from gda.daemon.discovery import daemon_paths
from gda.daemon.protocol import CONTROL_TIMEOUT, LIVE_REQUEST_TIMEOUT
from gda.daemon.server import STATUS_OP

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


def _no_reply(paths, request, deadline):
    """A daemon that accepts the connection and does not answer."""
    return None


def _refuse(paths, request, deadline):
    """A published endpoint at which nothing listens."""
    raise ConnectionRefusedError(111, "Connection refused")


def _answer_as(pid):
    return lambda paths, request, deadline: {"ok": True, "pid": pid}


# --- daemon_runtime_unusable: fix the directory ---------------------------------


def test_an_unusable_runtime_directory_is_refused_before_any_daemon_state(
    windows, monkeypatch
):
    paths = daemon_paths(windows)
    paths.runtime_dir.mkdir(parents=True)

    def shared(paths):
        raise PermissionError("Daemon runtime must not use a reparse point")

    def state_read(paths):
        raise AssertionError("the refusal must precede every daemon-state read")

    monkeypatch.setattr(daemon_ops, "ensure_runtime_dir", shared)
    monkeypatch.setattr(daemon_ops, "daemon_pid", state_read)
    monkeypatch.setattr(daemon_ops, "lock_held", state_read)

    failed = _failure(daemon_ops.run_daemon_status_operation(windows))

    assert failed.error.code == "daemon_runtime_unusable"
    assert str(paths.runtime_dir) in failed.error.message


def test_a_live_operation_reports_the_unusable_runtime_directory(windows, monkeypatch):
    paths = daemon_paths(windows)

    def unreadable(paths):
        raise PermissionError("Daemon runtime path has the wrong file type")

    monkeypatch.setattr(client, "daemon_pid", unreadable)

    result = client.DaemonRunner(windows).run("game-tree", {})

    error = parse_result(result.stdout)["error"]
    assert error["code"] == "daemon_runtime_unusable"
    assert str(paths.runtime_dir) in error["message"]


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
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)
    monkeypatch.setattr(daemon_ops, "lock_held", lambda paths: True)

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
    monkeypatch.setattr(daemon_ops, "lock_held", lambda paths: True)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)

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
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _refuse)

    failed = _failure(_start(windows))

    assert failed.error.code == "daemon_lifecycle_busy"
    assert "4242" in failed.error.message
    assert "no daemon accepts a connection" in failed.error.message


def test_a_stop_at_a_record_no_daemon_accepts_a_connection_at_is_busy(
    windows, monkeypatch
):
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 4242)
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
    monkeypatch.setattr(daemon_ops, "lock_held", lambda paths: True)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 4242)
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
    monkeypatch.setattr(daemon_ops, "lock_held", lambda paths: True)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _answer_as(4242))

    failed = _failure(daemon_ops.run_daemon_uninstall_operation(windows))

    assert failed.error.code == "daemon_running"


@pytest.mark.parametrize(
    ("round_trip", "accepted", "reply"),
    [
        (_refuse, False, None),
        (
            lambda paths, request, deadline: (_ for _ in ()).throw(
                FileNotFoundError("no native daemon endpoint is published")
            ),
            False,
            None,
        ),
        (
            lambda paths, request, deadline: (_ for _ in ()).throw(TimeoutError()),
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

    outcome = client.control_outcome(daemon_paths(windows), STATUS_OP)

    assert (outcome.accepted, outcome.reply) == (accepted, reply)


# --- daemon_unresponsive: confirm the process, then end it by hand -----------------


def test_a_slot_owner_that_does_not_answer_is_unresponsive(windows, monkeypatch):
    monkeypatch.setattr(
        daemon_ops,
        "acquire_harness_lock",
        lambda paths, timeout: contextlib.nullcontext(),
    )
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 4242)
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
    monkeypatch.setattr(daemon_ops, "lock_held", lambda paths: True)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _no_reply)

    failed = _failure(daemon_ops.run_daemon_uninstall_operation(windows))

    assert failed.error.code == "daemon_unresponsive"
    assert "4242" in failed.error.message


def test_a_stop_the_owner_does_not_acknowledge_is_unresponsive(windows, monkeypatch):
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _no_reply)

    failed = _failure(daemon_ops.run_daemon_stop_operation(windows))

    assert failed.error.code == "daemon_unresponsive"
    assert "4242" in failed.error.message
    assert "acknowledge" in failed.error.message


def test_a_daemon_that_does_not_retire_after_stop_is_unresponsive(windows, monkeypatch):
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 4242)
    monkeypatch.setattr(client, "_round_trip", _answer_as(4242))
    monkeypatch.setattr(daemon_ops, "_await_gone", lambda paths, pid: None)

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

    def round_trip(paths, request, deadline):
        waits.append(deadline - time.monotonic())
        return None

    monkeypatch.setattr(client, "_round_trip", round_trip)

    client.control(daemon_paths(windows), STATUS_OP)

    assert waits == [pytest.approx(LIVE_REQUEST_TIMEOUT, abs=1.0)]


def test_a_unix_control_request_keeps_the_control_deadline(monkeypatch, tmp_path):
    # On Unix the lock proves the owner and the reply is not read for it, so the
    # wait stays the control deadline (ADR-0047: Unix behaviour unchanged).
    monkeypatch.setattr(sys, "platform", "linux")
    waits: list[float] = []

    def round_trip(paths, request, deadline):
        waits.append(deadline - time.monotonic())
        return None

    monkeypatch.setattr(client, "_round_trip", round_trip)

    client.control(daemon_paths(tmp_path), STATUS_OP)

    assert waits == [pytest.approx(CONTROL_TIMEOUT, abs=0.5)]


def test_a_stop_is_complete_when_another_daemon_takes_the_slot(windows, monkeypatch):
    # After the stop is acknowledged the slot can pass to a daemon another caller
    # started; the retirement wait tells that daemon from the one that was stopped.
    holders: list[int] = []

    def holder(paths):
        holders.append(4242 if not holders else 4343)
        return holders[-1]

    monkeypatch.setattr(daemon_ops, "daemon_pid", holder)
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


# --- daemon_not_running keeps the failed start ------------------------------------


def test_a_rollback_that_cannot_take_the_slot_keeps_daemon_not_running(
    windows, monkeypatch
):
    opened = daemon_ops._install_harness_transactionally(windows)
    assert not isinstance(opened, Failure), opened
    paths = daemon_paths(windows)

    def held(paths):
        raise PermissionError("the daemon slot is held")

    monkeypatch.setattr(daemon_ops, "acquire_lock", held)

    failed = daemon_ops._failed_start_failure(opened.snapshot, paths)

    assert failed.error.code == "daemon_not_running"
    assert "gda daemon status" in failed.error.diagnostics
    # The winner's install is not removed: the rollback retained it.
    assert (windows / "addons" / "gda_harness" / "gda_harness.gd").exists()


# --- the platform refusal names no transport ------------------------------------------


def test_an_unsupported_platform_refusal_names_no_transport(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(sys, "platform", "sunos5")

    failed = _failure(daemon_ops.run_daemon_status_operation(Path(tmp_path)))

    assert failed.error.code == "live_unsupported_platform"
    assert "Unix" not in failed.error.message
    assert "UNIX" not in failed.error.message
    assert "socket" not in failed.error.message
