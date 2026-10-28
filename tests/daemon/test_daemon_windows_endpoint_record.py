"""The Windows adapter's endpoint record under another process's hold (#1236, #1227).

Windows refuses the deletion of a file that another handle holds open without
delete sharing, however short the hold, and the stop command's own 50 ms poll
opens the record that way. The removal retries for a bounded time, so the order
ADR-0047 fixes, the record removed before the slot is released, holds against
such a hold. The subject is the native delete refusal, so the hold test runs on
Windows only.

A hold also denies a read: while the daemon publishes or removes the record, a
reader's open can fail with access denied although the record exists (#1227).
Such a read is transient. The readiness wait reads it as not ready yet and the
stop wait as still held; a privacy refusal still ends a wait at once. Those
tests fake the platform (``sys.platform``), stub the privacy check and the slot
lock, which need the Win32 API, and deny the read or the existence check of the
record itself.
"""

import contextlib
import errno
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import gda.commands.daemon as daemon_ops
import gda.daemon.client as client
from gda.commands.daemon import _STOP_TIMEOUT
from gda.core.failure.catalog import Failure
from gda.daemon import win32, windows_discovery
from gda.daemon.discovery import daemon_paths
from gda.daemon.windows import WindowsPlatform
from gda.daemon.windows_discovery import REMOVAL_RETRY_BOUND, publish_endpoint
from tests.support import runnable_project, stub_daemon_platform

_OK_VERSION = lambda binary: (4, 6)  # noqa: E731
_TOKEN = "0123456789abcdef" * 4


@pytest.mark.skipif(sys.platform != "win32", reason="Windows delete sharing")
def test_the_removal_waits_out_a_transient_hold_on_the_record(
    daemon_runtime_dir, tmp_path, monkeypatch
):
    project = tmp_path / "game"
    project.mkdir()
    platform = WindowsPlatform()
    paths = daemon_paths(project, platform=platform)
    platform.prepare_runtime(paths)
    publish_endpoint(paths, os.getpid(), 40001, 40002, "0123456789abcdef" * 4)
    record = paths.endpoint_file
    assert record.exists()

    # Python's open shares reads and writes, not deletion: the record is held
    # the way the stop command's poll holds it.
    hold = open(record, "rb")
    refused: list[int | None] = []
    unlink = Path.unlink

    def release_on_refusal(path: Path, missing_ok: bool = False) -> None:
        # The hold ends when it has refused a delete, so the test does not
        # depend on how long the checks before the first delete take.
        try:
            unlink(path, missing_ok)
        except PermissionError as error:
            refused.append(getattr(error, "winerror", None))
            hold.close()
            raise

    monkeypatch.setattr(Path, "unlink", release_on_refusal)
    try:
        platform.unpublish(paths)
    finally:
        hold.close()

    assert refused == [win32.ERROR_SHARING_VIOLATION]
    assert not record.exists()


def test_the_removal_bound_is_inside_the_stop_wait():
    # A stop whose daemon waits out a hold still returns its stop result.
    assert REMOVAL_RETRY_BOUND < _STOP_TIMEOUT


# --- a read that a hold denies (#1227) ---------------------------------------------


@pytest.fixture
def windows(monkeypatch, tmp_path):
    """Fake Windows with a stubbed privacy check and slot lock.

    Returns the project, its daemon paths and the slot, whose ``held`` the
    test sets when its daemon holds the slot. A failed start's rollback cannot
    take the slot, as when the daemon holds it.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = runnable_project(tmp_path / "project")
    slot = SimpleNamespace(held=False)

    def private(path, *, directory=False):
        # The real check reads the path and then its native ACL.
        path.lstat()

    monkeypatch.setattr(windows_discovery, "_private_path", private)
    monkeypatch.setattr("gda.daemon.windows.lock_held", lambda paths: slot.held)

    def held_by_the_daemon(paths):
        raise PermissionError("the daemon slot is held")

    monkeypatch.setattr("gda.daemon.windows.acquire_lock", held_by_the_daemon)
    stub_daemon_platform(
        monkeypatch, harness_transaction=lambda paths, timeout: contextlib.nullcontext()
    )
    paths = daemon_paths(project, platform=WindowsPlatform())
    return project, paths, slot


def _hold(monkeypatch, record: Path, method: str = "read_text") -> dict[str, float]:
    """Deny the reads of ``record`` while ``hold["reads"]`` is above zero.

    ``method`` is the ``Path`` method that reads it. A denied read raises what
    CPython's ``open`` raises on Windows when another handle holds the file:
    ``PermissionError(13, message, filename)``, with no ``winerror``.
    """
    hold: dict[str, float] = {"reads": 0}
    original = getattr(Path, method)

    def read(path, *args, **kwargs):
        if path == record and hold["reads"] > 0:
            hold["reads"] -= 1
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, method, read)
    return hold


def _answer_as(pid):
    return lambda paths, request, deadline, platform: {"ok": True, "pid": pid}


def _publishing_spawn(paths, slot, hold=None, denied_reads: float = 0):
    """A daemon that publishes its record and holds the slot."""

    def spawn(project, binary, windowed, scene):
        publish_endpoint(paths, 4242, 40001, 40002, _TOKEN)
        slot.held = True
        if hold is not None:
            hold["reads"] = denied_reads

    return spawn


def test_a_start_waits_out_a_read_of_the_record_that_a_hold_denies(
    windows, monkeypatch
):
    project, paths, slot = windows
    hold = _hold(monkeypatch, paths.endpoint_file)
    monkeypatch.setattr(client, "_round_trip", _answer_as(4242))

    started = daemon_ops.run_daemon_start_operation(
        project,
        "godot",
        spawn=_publishing_spawn(paths, slot, hold, denied_reads=1),
        version_check=_OK_VERSION,
    )

    assert isinstance(started, daemon_ops.DaemonStartResult), started
    assert started.pid == 4242
    assert hold["reads"] == 0


def test_a_start_reports_a_denied_read_whose_existence_check_is_also_denied(
    windows, monkeypatch
):
    project, paths, slot = windows
    # The reader's privacy check reads the record with lstat, and so does its
    # existence check after the denial. A hold denies both until the deadline,
    # so the reader cannot tell that the record exists.
    hold = _hold(monkeypatch, paths.endpoint_file, method="lstat")
    monkeypatch.setattr(daemon_ops, "_READY_TIMEOUT", 0.3)

    failed = daemon_ops.run_daemon_start_operation(
        project,
        "godot",
        spawn=_publishing_spawn(paths, slot, hold, denied_reads=math.inf),
        version_check=_OK_VERSION,
    )

    assert isinstance(failed, Failure), failed
    assert failed.error.code == "daemon_not_running"
    assert failed.error.message == (
        "the gda-daemon did not start (it never began accepting on its socket); "
        "the readiness deadline expired while the daemon slot state could not be "
        f"read: [Errno 13] Permission denied: {str(paths.endpoint_file)!r}"
    )


def test_a_start_refuses_a_record_that_a_hold_still_denies_at_the_deadline(
    windows, monkeypatch
):
    project, paths, slot = windows
    hold = _hold(monkeypatch, paths.endpoint_file)
    monkeypatch.setattr(daemon_ops, "_READY_TIMEOUT", 0.3)

    failed = daemon_ops.run_daemon_start_operation(
        project,
        "godot",
        spawn=_publishing_spawn(paths, slot, hold, denied_reads=math.inf),
        version_check=_OK_VERSION,
    )

    assert isinstance(failed, Failure), failed
    assert failed.error.code == "daemon_not_running"
    assert failed.error.message == (
        "the gda-daemon did not start (it never began accepting on its socket); "
        "the readiness deadline expired while the daemon slot state could not be "
        f"read: [Errno 13] Permission denied: {str(paths.endpoint_file)!r}"
    )
    assert failed.error.diagnostics == (
        "retained this start's harness install: the rollback could not take the "
        "daemon slot; run `gda daemon status` before the next start"
    )


def test_a_privacy_refusal_of_the_record_ends_the_readiness_wait_at_once(
    windows, monkeypatch
):
    project, paths, slot = windows
    monkeypatch.setattr(daemon_ops, "_READY_TIMEOUT", 0.3)
    checks: list[Path] = []
    private = windows_discovery._private_path

    def refuse_the_record(path, *, directory=False):
        private(path, directory=directory)
        if path == paths.endpoint_file:
            checks.append(path)
            raise PermissionError("Daemon runtime is not private to the current user")

    monkeypatch.setattr(windows_discovery, "_private_path", refuse_the_record)

    failed = daemon_ops.run_daemon_start_operation(
        project,
        "godot",
        spawn=_publishing_spawn(paths, slot),
        version_check=_OK_VERSION,
    )

    assert isinstance(failed, Failure), failed
    assert failed.error.code == "daemon_not_running"
    assert checks == [paths.endpoint_file]


def test_a_stop_waits_out_a_read_of_the_record_that_a_hold_denies(windows, monkeypatch):
    project, paths, slot = windows
    publish_endpoint(paths, 4242, 40001, 40002, _TOKEN)
    hold = _hold(monkeypatch, paths.endpoint_file)
    # After the acknowledged stop, the first read of the record is denied. The
    # daemon still holds the slot at the next slot check, and has left by the
    # check after it.
    stop = SimpleNamespace(acknowledged=False, checks=0)

    def lock_held(paths):
        if not stop.acknowledged:
            return True
        stop.checks += 1
        return stop.checks == 1

    monkeypatch.setattr("gda.daemon.windows.lock_held", lock_held)

    def acknowledge(paths, request, deadline, platform):
        hold["reads"] = 1
        stop.acknowledged = True
        return {"ok": True, "pid": 4242}

    monkeypatch.setattr(client, "_round_trip", acknowledge)

    stopped = daemon_ops.run_daemon_stop_operation(project)

    assert stopped == daemon_ops.DaemonStopResult(stopped=True, pid=4242)
    assert hold["reads"] == 0


def test_a_stop_reads_a_record_that_a_hold_still_denies_at_the_deadline_as_held(
    windows, monkeypatch
):
    project, paths, slot = windows
    publish_endpoint(paths, 4242, 40001, 40002, _TOKEN)
    slot.held = True
    hold = _hold(monkeypatch, paths.endpoint_file)

    def acknowledge(paths, request, deadline, platform):
        # From the acknowledged stop on, a hold denies every read of the record.
        hold["reads"] = math.inf
        return {"ok": True, "pid": 4242}

    monkeypatch.setattr(client, "_round_trip", acknowledge)
    await_gone = daemon_ops._await_gone
    monkeypatch.setattr(
        daemon_ops,
        "_await_gone",
        lambda paths, platform, pid: await_gone(paths, platform, pid, timeout=0.3),
    )

    failed = daemon_ops.run_daemon_stop_operation(project)

    assert isinstance(failed, Failure), failed
    assert failed.error.code == "daemon_unresponsive"
    assert failed.error.message == (
        "the daemon 4242 acknowledged stop, but still held the daemon slot when "
        "the stop deadline expired"
    )
