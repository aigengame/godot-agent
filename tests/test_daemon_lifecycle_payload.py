"""gda daemon lifecycle payload mapping (#225, ADR-0018): start sync report + uninstall.

Fast unit tests for the *payload* the daemon-lifecycle recipes return — distinct
from ``test_daemon_ops`` (which spawns a REAL daemon and so is e2e). The process
lifecycle and a real install are exercised by the e2e suite; here the spawn /
readiness / liveness seams are stubbed so the focus is the additive
``DaemonStartResult`` fields this issue owns (``harness_synced`` /
``harness_version``) and the new ``run_daemon_uninstall_operation`` recipe
(refused while a daemon is running; idempotent paired removal otherwise).
"""

import json
import os

import pytest
from typer.testing import CliRunner

import gda.daemon_ops as daemon_ops
from gda.cli import app
from gda.errors import Failure
from gda.harness.install import (
    HARNESS_FILE,
    HARNESS_RES_DIR,
    HARNESS_VERSION,
    install_harness,
    installed_harness_version,
)
from gda.models import DaemonStartResult, DaemonUninstallResult

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")

_OK_VERSION = lambda binary: (4, 6)  # noqa: E731


def _project(tmp_path):
    (tmp_path / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="t"\n', encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def short_runtime(monkeypatch, tmp_path):
    # Keep derived socket paths short enough to pass the UDS sun_path gate without
    # binding a real socket (no daemon is spawned here).
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/tmp")
    return tmp_path


@pytest.fixture
def fake_ready(monkeypatch):
    # No real daemon is spawned, so stub the spawn (no-op) and the readiness wait
    # (return a fixed pid) — the start recipe then returns its mapped payload.
    monkeypatch.setattr(daemon_ops, "_await_ready", lambda paths, *a, **k: 4242)
    return 4242


def _start(project, **kw):
    return daemon_ops.run_daemon_start_operation(
        project, None, spawn=lambda p, b, w: None, version_check=_OK_VERSION, **kw
    )


# --- start reports harness_synced / harness_version (#225, D1) ----------------


def test_start_reports_harness_version_and_first_install_is_not_a_sync(
    tmp_path, short_runtime, fake_ready, monkeypatch
):
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)

    started = _start(project)

    assert isinstance(started, DaemonStartResult), started
    # A first install is reported by installed_harness, NOT as a sync (#247 review):
    # harness_synced is reserved for correcting an already-installed stale harness.
    assert started.installed_harness is True
    assert started.harness_synced is False
    assert started.harness_version == HARNESS_VERSION
    assert installed_harness_version(project) == HARNESS_VERSION


def test_start_reports_not_synced_when_version_already_matches(
    tmp_path, short_runtime, fake_ready, monkeypatch
):
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)

    first = _start(project)
    assert first.installed_harness is True
    assert first.harness_synced is False  # first install is not a resync (#247)

    # A second start at the same HARNESS_VERSION must NOT re-sync (no rewrite), but
    # still reports the installed version.
    again = _start(project)
    assert again.harness_synced is False
    assert again.installed_harness is False
    assert again.harness_version == HARNESS_VERSION


def test_already_running_start_is_a_noop_when_harness_is_current(
    tmp_path, short_runtime, monkeypatch
):
    project = _project(tmp_path)
    # A current harness on disk, then a live daemon already up.
    install_harness(project)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 999)

    started = daemon_ops.run_daemon_start_operation(
        project, None, version_check=_OK_VERSION
    )

    assert isinstance(started, DaemonStartResult)
    assert started.already_running is True
    # An already-running start re-checks the harness; a CURRENT one is a no-op (no
    # rewrite, no mtime bump), so it neither installs nor syncs.
    assert started.installed_harness is False
    assert started.harness_synced is False
    assert started.harness_version == HARNESS_VERSION


def test_already_running_start_resyncs_a_stale_harness(
    tmp_path, short_runtime, monkeypatch
):
    # PR #247 review: a daemon already up must NOT skip the harness self-sync. If
    # `gda` is upgraded while the old daemon stays running, an already-running start
    # still re-materializes a stale installed harness — so the next engine session
    # the daemon launches picks up the current copy, never a stale mismatch.
    project = _project(tmp_path)
    install_harness(project)
    # Simulate an older gda's harness left on disk: rewrite the version header stale.
    harness = project / HARNESS_RES_DIR / HARNESS_FILE
    lines = harness.read_text(encoding="utf-8").splitlines()
    lines[0] = "# gda-harness-version: stale-old"
    harness.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert installed_harness_version(project) == "stale-old"
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 999)

    started = daemon_ops.run_daemon_start_operation(
        project, None, version_check=_OK_VERSION
    )

    assert isinstance(started, DaemonStartResult)
    assert started.already_running is True
    assert started.harness_synced is True  # stale -> re-materialized despite running
    assert started.harness_version == HARNESS_VERSION
    assert installed_harness_version(project) == HARNESS_VERSION  # rewritten on disk


# --- start declares the display mode (#222, D1) -------------------------------
# `daemon start --windowed` is a START-TIME declared mode: the daemon launches a
# windowed engine session (no `--headless`) so a `screen` op can capture pixels
# (ADR-0017 refined; ADR-0020 single session). The recipe threads `windowed` into
# the spawn (the daemon argv) and surfaces it on the result so an agent sees the
# mode. Default is headless (the cheap non-visual sessions).


def test_start_defaults_to_headless_and_reports_windowed_false(
    tmp_path, short_runtime, fake_ready, monkeypatch
):
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)
    spawned: list[tuple] = []

    started = daemon_ops.run_daemon_start_operation(
        project,
        None,
        spawn=lambda p, b, windowed: spawned.append((p, b, windowed)),
        version_check=_OK_VERSION,
    )

    assert isinstance(started, DaemonStartResult), started
    assert started.windowed is False
    # The default (headless) mode is threaded into the spawn.
    assert spawned == [(project, str(daemon_ops.resolve_godot_binary(None)), False)]


def test_start_windowed_threads_mode_into_spawn_and_result(
    tmp_path, short_runtime, fake_ready, monkeypatch
):
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)
    spawned: list[tuple] = []

    started = daemon_ops.run_daemon_start_operation(
        project,
        None,
        windowed=True,
        spawn=lambda p, b, windowed: spawned.append((p, b, windowed)),
        version_check=_OK_VERSION,
    )

    assert isinstance(started, DaemonStartResult), started
    assert started.windowed is True
    # The windowed mode is threaded into the spawn (the daemon argv carries it).
    assert spawned[0][2] is True


def test_already_running_start_reports_windowed_unknown(
    tmp_path, short_runtime, monkeypatch
):
    # PR #248 review: an idempotent start does not relaunch the session and cannot
    # re-derive the running daemon's launch-time display mode from the pidfile, so it
    # reports `None` ("not determined here"), NOT a misleading `False` — even though
    # `--windowed=True` was requested, a running daemon's mode is whatever it was
    # launched with, which this start neither knows nor changes.
    project = _project(tmp_path)
    install_harness(project)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 999)

    started = daemon_ops.run_daemon_start_operation(
        project, None, windowed=True, version_check=_OK_VERSION
    )

    assert isinstance(started, DaemonStartResult)
    assert started.already_running is True
    assert started.windowed is None


def test_cli_daemon_start_windowed_threads_the_flag_to_the_recipe(
    tmp_path, short_runtime, monkeypatch
):
    # `gda daemon start --windowed` reaches the recipe with windowed=True; the argv
    # flag is the start-time declared display mode (#222).
    project = _project(tmp_path)
    captured: dict = {}

    def fake_start(proj, godot, *, windowed=False, **kw):
        captured["windowed"] = windowed
        return DaemonStartResult(
            pid=1,
            socket_path="/tmp/x.sock",
            installed_harness=False,
            harness_version=HARNESS_VERSION,
            windowed=windowed,
            already_running=False,
        )

    monkeypatch.setattr("gda.cli.run_daemon_start_operation", fake_start)

    result = CliRunner().invoke(
        app, ["daemon", "start", "--windowed", "--project", str(project), "--json"]
    )

    assert result.exit_code == 0, result.output
    assert captured["windowed"] is True
    assert json.loads(result.stdout)["windowed"] is True


def test_cli_daemon_start_defaults_to_headless(tmp_path, short_runtime, monkeypatch):
    project = _project(tmp_path)
    captured: dict = {}

    def fake_start(proj, godot, *, windowed=False, **kw):
        captured["windowed"] = windowed
        return DaemonStartResult(
            pid=1,
            socket_path="/tmp/x.sock",
            installed_harness=False,
            harness_version=HARNESS_VERSION,
            windowed=windowed,
            already_running=False,
        )

    monkeypatch.setattr("gda.cli.run_daemon_start_operation", fake_start)

    result = CliRunner().invoke(
        app, ["daemon", "start", "--project", str(project), "--json"]
    )

    assert result.exit_code == 0, result.output
    assert captured["windowed"] is False
    assert json.loads(result.stdout)["windowed"] is False


# --- uninstall recipe (#225, D2) ----------------------------------------------


def test_uninstall_refused_while_a_daemon_is_running(tmp_path, short_runtime, monkeypatch):
    project = _project(tmp_path)
    install_harness(project)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 999)  # a live daemon

    outcome = daemon_ops.run_daemon_uninstall_operation(project)

    assert isinstance(outcome, Failure), outcome
    assert outcome.error.code == "daemon_running"
    # Refusal must not touch the install: the harness file is still on disk.
    assert (project / HARNESS_RES_DIR / HARNESS_FILE).exists()


def test_uninstall_removes_harness_when_no_daemon(tmp_path, short_runtime, monkeypatch):
    project = _project(tmp_path)
    install_harness(project)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)

    outcome = daemon_ops.run_daemon_uninstall_operation(project)

    assert isinstance(outcome, DaemonUninstallResult), outcome
    assert outcome.removed is True
    assert not (project / HARNESS_RES_DIR / HARNESS_FILE).exists()


def test_uninstall_is_idempotent_no_op_when_not_installed(
    tmp_path, short_runtime, monkeypatch
):
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)

    outcome = daemon_ops.run_daemon_uninstall_operation(project)

    assert isinstance(outcome, DaemonUninstallResult)
    assert outcome.removed is False  # nothing to remove -> no-op success


# --- CLI surface (#225) -------------------------------------------------------


def test_cli_daemon_uninstall_emits_removal_json(tmp_path, short_runtime, monkeypatch):
    # `gda daemon uninstall --json` routes through the recipe and emits the typed
    # DaemonUninstallResult. No daemon is running for the fresh tmp project, so the
    # paired removal proceeds.
    project = _project(tmp_path)
    install_harness(project)

    result = CliRunner().invoke(
        app, ["daemon", "uninstall", "--project", str(project), "--json"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["removed"] is True
    assert not (project / HARNESS_RES_DIR / HARNESS_FILE).exists()


def test_cli_daemon_uninstall_refused_while_running_exits_live(
    tmp_path, short_runtime, monkeypatch
):
    # Refused while a daemon is running: the CLI surfaces the daemon_running error
    # envelope at the LIVE exit code (6).
    project = _project(tmp_path)
    install_harness(project)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 999)

    result = CliRunner().invoke(
        app, ["daemon", "uninstall", "--project", str(project), "--json"]
    )

    assert result.exit_code == 6, result.output
    assert json.loads(result.stdout)["error"]["code"] == "daemon_running"


def test_cli_daemon_uninstall_schema_describes_the_result(tmp_path):
    # The command is --schema self-describing (ADR-0004), so gda-mcp follows it.
    result = CliRunner().invoke(app, ["daemon", "uninstall", "--schema"])

    assert result.exit_code == 0, result.output
    schema = json.loads(result.stdout)
    assert "removed" in json.dumps(schema)
