"""gda-daemon process lifecycle (#7, ADR-0017): start / status / stop.

Spawns the REAL detached daemon process against a short runtime dir. ``start`` now
resolves the engine binary and gates the live version, so this needs a Godot
install (e2e), but the version check is injected so no engine actually runs — the
focus is the socket/pidfile lifecycle and idempotent start. The full session loop
(a real runtime tree) is the CLI e2e in ``test_e2e_daemon``.
"""

import os

import pytest

from gda.daemon.discovery import daemon_paths, daemon_pid
from gda.daemon_ops import (
    run_daemon_start_operation,
    run_daemon_status_operation,
    run_daemon_stop_operation,
)
from gda.harness.install import HARNESS_VERSION
from gda.models import DaemonStartResult, DaemonStatusResult, DaemonStopResult

pytestmark = [
    pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX"),
    pytest.mark.e2e,  # start resolves a real Godot binary
]

# A 4.6 engine so the live-version gate passes without running the engine. The
# short-runtime-dir requirement (UDS sun_path limit) is the shared
# ``daemon_runtime_dir`` fixture in conftest.
_OK_VERSION = lambda binary: (4, 6)  # noqa: E731


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


def test_daemon_start_status_stop_lifecycle(tmp_path, daemon_runtime_dir):
    project = _project(tmp_path)
    paths = daemon_paths(project)

    try:
        started = run_daemon_start_operation(project, None, version_check=_OK_VERSION)
        assert isinstance(started, DaemonStartResult), started
        assert started.already_running is False
        assert started.installed_harness is True  # harness installed + reported
        # #225/#247: a first install is reported by installed_harness, not as a sync.
        assert started.harness_synced is False
        assert started.harness_version == HARNESS_VERSION
        assert daemon_pid(paths) == started.pid

        # Idempotent: a second start finds the running daemon.
        again = run_daemon_start_operation(project, None, version_check=_OK_VERSION)
        assert isinstance(again, DaemonStartResult)
        assert again.already_running is True
        assert again.pid == started.pid
        assert again.installed_harness is False
        assert again.harness_synced is False  # syncs nothing
        assert again.harness_version == HARNESS_VERSION

        status = run_daemon_status_operation(project)
        assert isinstance(status, DaemonStatusResult)
        assert status.running is True and status.pid == started.pid
        # #251: status round-trips STATUS_OP to read the daemon's launch-time mode.
        # This daemon was started headless (the default), so it reports windowed.
        assert status.windowed is False
    finally:
        stopped = run_daemon_stop_operation(project)
        assert isinstance(stopped, DaemonStopResult)

    # Torn down: pidfile dead, socket gone.
    assert daemon_pid(paths) is None
    assert not paths.cli_socket.exists()


def test_daemon_status_reports_a_windowed_daemons_mode(tmp_path, daemon_runtime_dir):
    # #251: a daemon started `--windowed` reports `windowed: True` over STATUS_OP,
    # read back by `daemon status`. No engine session is launched here (lazy launch,
    # ADR-0017) — the daemon process merely records the declared mode — so this needs
    # no display and is headless-CI safe.
    project = _project(tmp_path)

    try:
        started = run_daemon_start_operation(
            project, None, windowed=True, version_check=_OK_VERSION
        )
        assert isinstance(started, DaemonStartResult), started
        assert started.windowed is True

        status = run_daemon_status_operation(project)
        assert isinstance(status, DaemonStatusResult)
        assert status.running is True
        assert status.windowed is True
    finally:
        run_daemon_stop_operation(project)


def test_live_version_gate_rejects_below_4_6(tmp_path, daemon_runtime_dir):
    from gda.errors import Failure

    project = _project(tmp_path)
    outcome = run_daemon_start_operation(
        project, None, version_check=lambda binary: (4, 5)
    )
    assert isinstance(outcome, Failure)
    assert outcome.error.code == "unsupported_version"
    assert daemon_pid(daemon_paths(project)) is None  # nothing spawned


def test_daemon_status_and_stop_when_not_running(tmp_path, daemon_runtime_dir):
    project = _project(tmp_path)

    status = run_daemon_status_operation(project)
    assert isinstance(status, DaemonStatusResult) and status.running is False
    # No daemon -> no mode to read; `windowed` is None (no round trip, no hang, #251).
    assert status.windowed is None

    stopped = run_daemon_stop_operation(project)
    assert isinstance(stopped, DaemonStopResult) and stopped.stopped is False
