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
import subprocess
from pathlib import Path as _Path

import pytest
from typer.testing import CliRunner

import gda.commands.daemon as daemon_ops
from gda.cli import app
from gda.display import WindowedUnavailable
from gda.errors import Failure
from gda.models import EnvironmentProbe
from gda.harness.install import (
    HARNESS_FILE,
    HARNESS_RES_DIR,
    HARNESS_VERSION,
    HarnessSnapshot,
    install_harness,
    installed_harness_version,
)
from gda.commands.daemon import (
    DaemonStartResult,
    DaemonStatusResult,
    DaemonUninstallResult,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")

_OK_VERSION = lambda binary: (4, 6)  # noqa: E731


def _unavailable(
    code: str = "live_windowed_unavailable",
    name: str = "CGSessionCopyCurrentDictionary",
    platform: str = "darwin",
) -> WindowedUnavailable:
    """A fake host-probe verdict (#345, #667).

    The refusal mapping is a pure function of this verdict, so injecting one covers
    BOTH windowed outcomes on ANY host — no display, no sandbox, and no capability
    gate needed. The real probe is proven separately against a real sandbox.
    """
    return WindowedUnavailable(
        code=code,
        reason=f"no windowed session here (test: {code})",
        probe=EnvironmentProbe(name=name, platform=platform),
    )


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
        project,
        None,
        spawn=lambda p, b, w, s: None,
        version_check=_OK_VERSION,
        **kw,
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
    assert not isinstance(first, Failure)
    assert first.installed_harness is True
    assert first.harness_synced is False  # first install is not a resync (#247)

    # A second start at the same HARNESS_VERSION must NOT re-sync (no rewrite), but
    # still reports the installed version.
    again = _start(project)
    assert not isinstance(again, Failure)
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
        spawn=lambda p, b, windowed, scene: spawned.append((p, b, windowed)),
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
        spawn=lambda p, b, windowed, scene: spawned.append((p, b, windowed)),
        version_check=_OK_VERSION,
        # A display IS usable here (inject the #345 precondition so this fast unit
        # test is display-independent — a headless CI host must not refuse the start).
        display_check=lambda: None,
    )

    assert isinstance(started, DaemonStartResult), started
    assert started.windowed is True
    # The windowed mode is threaded into the spawn (the daemon argv carries it).
    assert spawned[0][2] is True


def test_windowed_start_without_a_display_is_live_windowed_unavailable(
    tmp_path, short_runtime, monkeypatch
):
    # #345 Part B: a windowed start on a host with no usable DisplayServer is refused
    # BEFORE spawning Godot (and before installing the harness) with the typed
    # live_windowed_unavailable (ENVIRONMENT / exit 127) — mirroring the platform
    # precondition — rather than spawning a doomed engine that aborts during
    # DisplayServer registration.
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)
    spawned: list = []

    outcome = daemon_ops.run_daemon_start_operation(
        project,
        None,
        windowed=True,
        spawn=lambda p, b, w, s: spawned.append((p, b, w, s)),
        version_check=_OK_VERSION,
        display_check=lambda: _unavailable(),
    )

    assert isinstance(outcome, Failure), outcome
    assert outcome.error.code == "live_windowed_unavailable"
    assert outcome.error.category.value == "environment"
    assert outcome.exit_code == 127  # EXIT_NOT_FOUND
    assert spawned == []  # never spawned Godot
    # Pre-harness-install too: a doomed windowed start must not mutate the project.
    assert not (project / HARNESS_RES_DIR / HARNESS_FILE).exists()
    # #667: the deciding host call rides the envelope as DATA, not only as prose.
    assert outcome.error.probe is not None
    assert outcome.error.probe.name == "CGSessionCopyCurrentDictionary"
    assert outcome.error.probe.platform == "darwin"


def test_windowed_start_denied_by_a_sandbox_is_a_distinct_permission_code(
    tmp_path, short_runtime, monkeypatch
):
    # #667 (dogfooding GDA-DF-029): a windowed start refused because THIS PROCESS may
    # denied the window-server lookup is NOT the same failure as a host where none was
    # detected. It
    # reports the distinct live_windowed_permission_denied so automation retries
    # outside the sandbox instead of recording the machine as display-less — while
    # keeping the ENVIRONMENT/127 bucket of its sibling (the refusal is the same
    # pre-launch refusal). Ungated: the verdict is injected, so this runs on every
    # host including a display-less CI runner.
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)
    spawned: list = []

    outcome = daemon_ops.run_daemon_start_operation(
        project,
        None,
        windowed=True,
        spawn=lambda p, b, w, s: spawned.append((p, b, w, s)),
        version_check=_OK_VERSION,
        display_check=lambda: _unavailable(
            code="live_windowed_permission_denied",
            name="bootstrap_look_up(com.apple.windowserver.active)",
        ),
    )

    assert isinstance(outcome, Failure), outcome
    assert outcome.error.code == "live_windowed_permission_denied"
    # Deliberately NOT live_display_unavailable (the harness's capture-time code) and
    # NOT live_windowed_unavailable (the machine-capability verdict).
    assert outcome.error.category.value == "environment"
    assert outcome.exit_code == 127  # the same bucket as live_windowed_unavailable
    assert spawned == []  # still refused pre-launch, still no project mutation
    assert not (project / HARNESS_RES_DIR / HARNESS_FILE).exists()
    assert outcome.error.probe is not None
    assert (
        outcome.error.probe.name == "bootstrap_look_up(com.apple.windowserver.active)"
    )
    assert outcome.error.probe.platform == "darwin"


def test_windowed_refusal_json_carries_the_probe_and_others_are_unchanged(tmp_path):
    # #667 / the ADR-0004 amendment: `probe` is emitted for a failure that HAS one and
    # OMITTED entirely — not `null` — for every failure that does not, so each other
    # code's envelope JSON stays byte-identical to before the field existed.
    from gda.errors import make_failure
    from gda.models import GdaErrorEnvelope

    with_probe = make_failure(
        "live_windowed_permission_denied",
        "denied",
        "",
        probe=EnvironmentProbe(name="bootstrap_look_up(x)", platform="darwin"),
    )
    without = make_failure("binary_not_found", "nope", "")

    with_json = json.loads(
        GdaErrorEnvelope(error=with_probe.error).model_dump_json(exclude_none=True)
    )
    without_json = json.loads(
        GdaErrorEnvelope(error=without.error).model_dump_json(exclude_none=True)
    )

    assert with_json["error"]["probe"] == {
        "name": "bootstrap_look_up(x)",
        "platform": "darwin",
    }
    assert "probe" not in without_json["error"]
    assert set(without_json["error"]) == {
        "category",
        "code",
        "message",
        "diagnostics",
    }


def test_headless_start_never_consults_the_display_check(
    tmp_path, short_runtime, fake_ready, monkeypatch
):
    # The precondition is windowed-only: a default (headless) start must not consult
    # the display check at all — a headless session needs no window server.
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)

    def _boom() -> str:
        raise AssertionError("a headless start must not run the display check")

    started = _start(project, display_check=_boom)

    assert isinstance(started, DaemonStartResult), started
    assert started.windowed is False


# `daemon start --scene <path|UID>` is a START-TIME selector: the daemon holds it
# and passes it to the engine session as `--scene` (before `--path`). The recipe
# threads the value into the spawn (the daemon argv) — like `windowed`. With no
# `--scene`, the spawn carries `None` and the session runs the project's main_scene
# unchanged (#278, ADR-0017 amendment).


def test_start_threads_scene_into_spawn_when_set(
    tmp_path, short_runtime, fake_ready, monkeypatch
):
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)
    spawned: list[tuple] = []

    started = daemon_ops.run_daemon_start_operation(
        project,
        None,
        scene="res://B.tscn",
        spawn=lambda p, b, windowed, scene: spawned.append((p, b, windowed, scene)),
        version_check=_OK_VERSION,
    )

    assert isinstance(started, DaemonStartResult), started
    # The selector is threaded into the spawn (the daemon argv carries it).
    assert spawned[0][3] == "res://B.tscn"


def test_start_defaults_to_no_scene_selector(
    tmp_path, short_runtime, fake_ready, monkeypatch
):
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)
    spawned: list[tuple] = []

    started = daemon_ops.run_daemon_start_operation(
        project,
        None,
        spawn=lambda p, b, windowed, scene: spawned.append((p, b, windowed, scene)),
        version_check=_OK_VERSION,
    )

    assert isinstance(started, DaemonStartResult), started
    # No selector: the spawn carries None — the session runs main_scene unchanged.
    assert spawned[0][3] is None


def test_spawn_daemon_forwards_scene_into_the_daemon_argv(monkeypatch):
    # `_spawn_daemon` builds the detached `python -m gda.daemon` argv; the selector
    # is forwarded as `--scene <value>` so the daemon process holds it (#278).
    import subprocess as _subprocess

    captured: dict = {}

    class _FakePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv

    monkeypatch.setattr(_subprocess, "Popen", _FakePopen)

    daemon_ops._spawn_daemon(_Path("/proj"), "godot", False, "res://B.tscn")

    argv = captured["argv"]
    assert "--scene" in argv
    assert argv[argv.index("--scene") + 1] == "res://B.tscn"


def test_spawn_daemon_omits_scene_when_none(monkeypatch):
    import subprocess as _subprocess

    captured: dict = {}

    class _FakePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv

    monkeypatch.setattr(_subprocess, "Popen", _FakePopen)

    daemon_ops._spawn_daemon(_Path("/proj"), "godot", False, None)

    assert "--scene" not in captured["argv"]


def test_daemon_main_parses_scene_into_the_server(monkeypatch):
    # `python -m gda.daemon --scene res://B.tscn` parses the selector and constructs
    # the DaemonServer with it, so a launched session boots that scene (#278).
    import gda.daemon.__main__ as daemon_main

    captured: dict = {}

    class _FakeServer:
        def __init__(self, paths, godot="", windowed=False, scene=None):
            captured["scene"] = scene

        def serve(self):
            pass

    monkeypatch.setattr(daemon_main, "DaemonServer", _FakeServer)
    monkeypatch.setattr(
        "sys.argv",
        ["gda.daemon", "--project", "/proj", "--scene", "res://B.tscn"],
    )

    daemon_main.main()

    assert captured["scene"] == "res://B.tscn"


def test_daemon_main_scene_defaults_to_none(monkeypatch):
    import gda.daemon.__main__ as daemon_main

    captured: dict = {}

    class _FakeServer:
        def __init__(self, paths, godot="", windowed=False, scene=None):
            captured["scene"] = scene

        def serve(self):
            pass

    monkeypatch.setattr(daemon_main, "DaemonServer", _FakeServer)
    monkeypatch.setattr("sys.argv", ["gda.daemon", "--project", "/proj"])

    daemon_main.main()

    assert captured["scene"] is None


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


def test_already_running_start_with_scene_is_a_typed_refusal(
    tmp_path, short_runtime, monkeypatch
):
    # Finding 3: `--scene` only takes effect at daemon START. Requesting it against a
    # daemon that is already running would otherwise be a SILENT no-op (the chosen
    # scene never reaches the daemon). It is instead a typed `daemon_already_running`
    # refusal naming the remediation (stop, then start --scene).
    project = _project(tmp_path)
    install_harness(project)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 999)

    failure = daemon_ops.run_daemon_start_operation(
        project, None, scene="res://B.tscn", version_check=_OK_VERSION
    )

    assert isinstance(failure, Failure), failure
    assert failure.error.code == "daemon_already_running"


def test_already_running_start_without_scene_stays_idempotent_success(
    tmp_path, short_runtime, monkeypatch
):
    # The already-running + NO `--scene` path is unchanged: idempotent success.
    project = _project(tmp_path)
    install_harness(project)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 999)

    started = daemon_ops.run_daemon_start_operation(
        project, None, version_check=_OK_VERSION
    )

    assert isinstance(started, DaemonStartResult)
    assert started.already_running is True


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

    monkeypatch.setattr("gda.commands.daemon.run_daemon_start_operation", fake_start)

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

    monkeypatch.setattr("gda.commands.daemon.run_daemon_start_operation", fake_start)

    result = CliRunner().invoke(
        app, ["daemon", "start", "--project", str(project), "--json"]
    )

    assert result.exit_code == 0, result.output
    assert captured["windowed"] is False
    assert json.loads(result.stdout)["windowed"] is False


def test_cli_daemon_start_scene_threads_the_selector_to_the_recipe(
    tmp_path, short_runtime, monkeypatch
):
    # `gda daemon start --scene res://B.tscn` reaches the recipe with the selector;
    # the argv option is the start-time scene the session boots (#278).
    project = _project(tmp_path)
    captured: dict = {}

    def fake_start(proj, godot, *, windowed=False, scene=None, **kw):
        captured["scene"] = scene
        return DaemonStartResult(
            pid=1,
            socket_path="/tmp/x.sock",
            installed_harness=False,
            harness_version=HARNESS_VERSION,
            windowed=windowed,
            already_running=False,
        )

    monkeypatch.setattr("gda.commands.daemon.run_daemon_start_operation", fake_start)

    result = CliRunner().invoke(
        app,
        [
            "daemon",
            "start",
            "--scene",
            "res://B.tscn",
            "--project",
            str(project),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["scene"] == "res://B.tscn"


def test_cli_daemon_start_defaults_to_no_scene(tmp_path, short_runtime, monkeypatch):
    project = _project(tmp_path)
    captured: dict = {}

    def fake_start(proj, godot, *, windowed=False, scene=None, **kw):
        captured["scene"] = scene
        return DaemonStartResult(
            pid=1,
            socket_path="/tmp/x.sock",
            installed_harness=False,
            harness_version=HARNESS_VERSION,
            windowed=windowed,
            already_running=False,
        )

    monkeypatch.setattr("gda.commands.daemon.run_daemon_start_operation", fake_start)

    result = CliRunner().invoke(
        app, ["daemon", "start", "--project", str(project), "--json"]
    )

    assert result.exit_code == 0, result.output
    assert captured["scene"] is None


# --- status surfaces the running daemon's display mode (#251) -----------------
# `daemon status` is no longer pidfile-only: when a daemon is up it round-trips the
# STATUS_OP control op to read the daemon's launch-time `windowed` mode, so an agent
# can tell whether a live session can serve a `screen` capture before issuing one.
# No daemon -> `running: False` and `windowed: None`, with no round trip and no hang.


def test_status_reports_windowed_read_over_the_control_op(
    tmp_path, short_runtime, monkeypatch
):
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 4242)
    # Stub the IPC round trip: a windowed daemon answers STATUS_OP with windowed=True.
    monkeypatch.setattr(
        daemon_ops, "_control", lambda sock, op, **kw: {"ok": True, "windowed": True}
    )

    status = daemon_ops.run_daemon_status_operation(project)

    assert isinstance(status, DaemonStatusResult), status
    assert status.running is True and status.pid == 4242
    assert status.windowed is True


def test_status_reports_headless_when_the_daemon_is_headless(
    tmp_path, short_runtime, monkeypatch
):
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 4242)
    monkeypatch.setattr(
        daemon_ops, "_control", lambda sock, op, **kw: {"ok": True, "windowed": False}
    )

    status = daemon_ops.run_daemon_status_operation(project)

    assert isinstance(status, DaemonStatusResult)
    assert status.running is True and status.windowed is False


def test_status_windowed_is_null_when_no_daemon_is_running(
    tmp_path, short_runtime, monkeypatch
):
    # No daemon: `running` is False and `windowed` is None, and crucially the status
    # path must NOT round-trip (nothing to connect to) — a clean, hang-free fallback.
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)

    def _must_not_connect(*a, **k):
        raise AssertionError("status must not round-trip when no daemon is running")

    monkeypatch.setattr(daemon_ops, "_control", _must_not_connect)

    status = daemon_ops.run_daemon_status_operation(project)

    assert isinstance(status, DaemonStatusResult)
    assert status.running is False
    assert status.windowed is None


def test_status_windowed_is_null_when_the_control_round_trip_fails(
    tmp_path, short_runtime, monkeypatch
):
    # Pidfile says alive but the control round trip yields nothing (a transient race
    # on a dying daemon): `windowed` falls back to None rather than erroring.
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 4242)
    monkeypatch.setattr(daemon_ops, "_control", lambda sock, op, **kw: None)

    status = daemon_ops.run_daemon_status_operation(project)

    assert isinstance(status, DaemonStatusResult)
    assert status.running is True
    assert status.windowed is None


# --- uninstall recipe (#225, D2) ----------------------------------------------


def test_uninstall_refused_while_a_daemon_is_running(
    tmp_path, short_runtime, monkeypatch
):
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
    assert outcome.removed_paths == []  # and nothing to report
    assert outcome.removed_sections == []


# --- a failed start rolls its own install back (#680 review, claim 2) ----------
# The harness install happens BEFORE the daemon exists, so a start that never comes
# ready used to return `daemon_not_running` over a project it had silently mutated,
# with nothing in the envelope saying so. The failure path now undoes exactly what
# the in-hand install receipt reports.


def test_failed_start_rolls_the_harness_install_back(
    tmp_path, short_runtime, monkeypatch
):
    project = _project(tmp_path)
    project_godot = project / "project.godot"
    before = project_godot.read_bytes()
    monkeypatch.setattr(daemon_ops, "_spawn_daemon", lambda *a, **k: None)
    monkeypatch.setattr(daemon_ops, "_await_ready", lambda paths, *a, **k: None)

    failure = daemon_ops.run_daemon_start_operation(
        project, "godot", version_check=_OK_VERSION
    )

    assert isinstance(failure, Failure), failure
    assert failure.error.code == "daemon_not_running"
    # The project is back to its pre-start bytes, with no addons residue at all.
    assert project_godot.read_bytes() == before
    assert not (project / "addons").exists()
    # And the envelope SAYS what was undone, so the mutation is never silent.
    assert "rolled back" in failure.error.diagnostics
    assert HARNESS_RES_DIR in failure.error.diagnostics


def test_failed_start_leaves_a_pre_existing_install_alone(
    tmp_path, short_runtime, monkeypatch
):
    # `changed=False` means this start created nothing, so there is nothing to roll
    # back — a failed start must not uninstall a harness that was already there.
    project = _project(tmp_path)
    install_harness(project)
    installed_bytes = (project / "project.godot").read_bytes()
    monkeypatch.setattr(daemon_ops, "_spawn_daemon", lambda *a, **k: None)
    monkeypatch.setattr(daemon_ops, "_await_ready", lambda paths, *a, **k: None)

    failure = daemon_ops.run_daemon_start_operation(
        project, "godot", version_check=_OK_VERSION
    )

    assert isinstance(failure, Failure), failure
    assert failure.error.code == "daemon_not_running"
    assert (project / HARNESS_RES_DIR / HARNESS_FILE).exists()  # untouched
    assert (project / "project.godot").read_bytes() == installed_bytes
    assert failure.error.diagnostics == ""  # nothing rolled back -> nothing to say


def test_start_rolls_back_when_the_spawn_itself_raises(
    tmp_path, short_runtime, monkeypatch
):
    # The exception arm: a crash between install and readiness must not leave residue
    # either. The original exception propagates unchanged (no new error semantics).
    project = _project(tmp_path)
    project_godot = project / "project.godot"
    before = project_godot.read_bytes()

    def boom(*args, **kwargs):
        raise OSError("injected: cannot spawn")

    monkeypatch.setattr(daemon_ops, "_spawn_daemon", boom)

    with pytest.raises(OSError, match="cannot spawn"):
        daemon_ops.run_daemon_start_operation(
            project, "godot", version_check=_OK_VERSION
        )

    assert project_godot.read_bytes() == before
    assert not (project / "addons").exists()


def test_failed_start_restores_a_stale_harness_body_it_resynced(
    tmp_path, short_runtime, monkeypatch
):
    # PR #680 recheck, the reproduced residue. A project that ALREADY has a correct
    # harness autoload entry and a STALE harness body on disk: the start's install
    # re-materializes the body and creates nothing, so the receipt is empty and the
    # receipt-driven rollback did nothing — a failed start silently replaced tracked
    # content and reported no footprint at all. The snapshot restores it verbatim.
    project = _project(tmp_path)
    project_godot = project / "project.godot"
    project_godot.write_text(
        project_godot.read_text(encoding="utf-8")
        + f'\n[autoload]\n\nGdaHarness="*res://{HARNESS_RES_DIR}/{HARNESS_FILE}"\n',
        encoding="utf-8",
    )
    harness = project / HARNESS_RES_DIR / HARNESS_FILE
    harness.parent.mkdir(parents=True)
    stale = b"# gda-harness-version: stale-old\nextends Node\n# my own edits\n"
    harness.write_bytes(stale)
    godot_before = project_godot.read_bytes()
    monkeypatch.setattr(daemon_ops, "_spawn_daemon", lambda *a, **k: None)
    monkeypatch.setattr(daemon_ops, "_await_ready", lambda paths, *a, **k: None)

    failure = daemon_ops.run_daemon_start_operation(
        project, "godot", version_check=_OK_VERSION
    )

    assert isinstance(failure, Failure), failure
    assert failure.error.code == "daemon_not_running"
    # EVERY file is byte-identical to pre-start, the stale body included.
    assert harness.read_bytes() == stale
    assert project_godot.read_bytes() == godot_before
    # And the restore is reported, so the rewrite is never silent.
    assert "rolled back" in failure.error.diagnostics
    assert HARNESS_FILE in failure.error.diagnostics


@pytest.fixture
def read_only_project_godot():
    """Make a project.godot unwritable, and always put the mode back.

    The teardown matters: pytest's tmp_path cleanup fails on a directory whose files
    it cannot remove, which would turn a real assertion failure into a confusing
    cleanup error.
    """
    restore: list[tuple[_Path, int]] = []

    def make(path: _Path) -> None:
        restore.append((path, path.stat().st_mode))
        path.chmod(0o444)

    yield make
    for path, mode in restore:
        if path.exists():
            path.chmod(mode)


def test_failed_install_restores_a_project_whose_config_cannot_be_written(
    tmp_path, short_runtime, monkeypatch, read_only_project_godot
):
    # PR #680 recheck 2, the reproduced residue. `install_harness` materializes the
    # harness FILE first and writes the autoload config SECOND, so a config write
    # that fails leaves the harness on disk and raises — and the install call used to
    # sit OUTSIDE the guarded region, so no restore ran and no receipt ever existed.
    # A real filesystem fault (a read-only project.godot) drives it, not a stub.
    project = _project(tmp_path)
    project_godot = project / "project.godot"
    before = project_godot.read_bytes()
    read_only_project_godot(project_godot)
    monkeypatch.setattr(daemon_ops, "_spawn_daemon", lambda *a, **k: None)

    # The exception still surfaces to the caller exactly as before — the restore does
    # not swallow or reclassify it.
    with pytest.raises(PermissionError):
        daemon_ops.run_daemon_start_operation(
            project, "godot", version_check=_OK_VERSION
        )

    # ... but nothing of the half-finished install is left behind.
    assert not (project / HARNESS_RES_DIR / HARNESS_FILE).exists()
    assert not (project / HARNESS_RES_DIR / f"{HARNESS_FILE}.uid").exists()
    assert not (project / HARNESS_RES_DIR).exists()
    assert not (project / "addons").exists()  # the dir the install created, too
    assert project_godot.read_bytes() == before


def test_failed_install_keeps_a_pre_existing_harness_untouched(
    tmp_path, short_runtime, monkeypatch, read_only_project_godot
):
    # The same fault over a project that ALREADY has harness files (stale body) and
    # its own addons/ directory: the restore must put the stale bytes back and delete
    # NOTHING that predated the start.
    #
    # The autoload entry is deliberately ABSENT — a half-installed project, which is
    # what makes the install need a config write and so hit the read-only fault. With
    # a correct entry already in place the install writes no config at all and never
    # fails, which is itself worth knowing: the fault only bites when project.godot
    # actually has to change.
    project = _project(tmp_path)
    project_godot = project / "project.godot"
    harness = project / HARNESS_RES_DIR / HARNESS_FILE
    harness.parent.mkdir(parents=True)
    stale = b"# gda-harness-version: stale-old\nextends Node\n# my own edits\n"
    harness.write_bytes(stale)
    sidecar = harness.with_name(f"{HARNESS_FILE}.uid")
    sidecar.write_bytes(b"uid://bxxxxxxxxxxxxx\n")
    before = project_godot.read_bytes()
    read_only_project_godot(project_godot)
    monkeypatch.setattr(daemon_ops, "_spawn_daemon", lambda *a, **k: None)

    # The install re-materializes the stale body, then fails on the config write.
    with pytest.raises(PermissionError):
        daemon_ops.run_daemon_start_operation(
            project, "godot", version_check=_OK_VERSION
        )

    assert harness.read_bytes() == stale  # restored verbatim, still stale
    assert sidecar.read_bytes() == b"uid://bxxxxxxxxxxxxx\n"
    assert (project / HARNESS_RES_DIR).is_dir()  # pre-existing dirs survive
    assert (project / "addons").is_dir()
    assert project_godot.read_bytes() == before


def test_failed_install_leaves_a_tracked_project_porcelain_clean(
    tmp_path, short_runtime, monkeypatch, read_only_project_godot
):
    # Repro (a) as the user meets it: as a git diff. The half-finished install must
    # leave nothing for `git status` to report.
    project = _project(tmp_path)
    project_godot = project / "project.godot"

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(project), *args], capture_output=True, text=True
        )

    assert git("init", "-q").returncode == 0
    git("config", "user.email", "unit@example.invalid")
    git("config", "user.name", "gda unit")
    assert git("add", "-A").returncode == 0
    assert git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "baseline")
    assert git("status", "--porcelain").stdout == ""

    read_only_project_godot(project_godot)
    monkeypatch.setattr(daemon_ops, "_spawn_daemon", lambda *a, **k: None)

    with pytest.raises(PermissionError):
        daemon_ops.run_daemon_start_operation(
            project, "godot", version_check=_OK_VERSION
        )

    status = git("status", "--porcelain")
    assert status.stdout == "", (
        "the half-finished install left the tracked project dirty:\n" + status.stdout
    )


def test_failed_start_leaves_a_tracked_project_porcelain_clean(
    tmp_path, short_runtime, monkeypatch
):
    # The same residue seen the way a user sees it: as a git diff. A stale harness
    # body is COMMITTED, the start fails, and `git status --porcelain` must be empty
    # — the check that does not depend on the test naming the right file. No engine
    # needed, so this stays in the fast suite alongside the e2e round trip.
    project = _project(tmp_path)
    project_godot = project / "project.godot"
    project_godot.write_text(
        project_godot.read_text(encoding="utf-8")
        + f'\n[autoload]\n\nGdaHarness="*res://{HARNESS_RES_DIR}/{HARNESS_FILE}"\n',
        encoding="utf-8",
    )
    harness = project / HARNESS_RES_DIR / HARNESS_FILE
    harness.parent.mkdir(parents=True)
    harness.write_bytes(
        b"# gda-harness-version: stale-old\nextends Node\n# my own edits\n"
    )

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(project), *args], capture_output=True, text=True
        )

    assert git("init", "-q").returncode == 0
    git("config", "user.email", "unit@example.invalid")
    git("config", "user.name", "gda unit")
    assert git("add", "-A").returncode == 0
    assert git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "baseline")
    assert git("status", "--porcelain").stdout == ""  # a clean baseline

    monkeypatch.setattr(daemon_ops, "_spawn_daemon", lambda *a, **k: None)
    monkeypatch.setattr(daemon_ops, "_await_ready", lambda paths, *a, **k: None)

    failure = daemon_ops.run_daemon_start_operation(
        project, "godot", version_check=_OK_VERSION
    )

    assert isinstance(failure, Failure), failure
    status = git("status", "--porcelain")
    assert status.stdout == "", (
        "the failed start left the tracked project dirty:\n" + status.stdout
    )


def test_failed_start_reports_the_residual_delta_when_restore_also_fails(
    tmp_path, short_runtime, monkeypatch
):
    # A restore failure must not replace the start failure; it is reported ALONGSIDE
    # it, naming what the user now has to put right by hand (ADR-0004 shape unchanged
    # — same code, prose in `diagnostics`). The set is MEASURED against the snapshot,
    # so it reports what actually still differs rather than predicting from a receipt.
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "_spawn_daemon", lambda *a, **k: None)
    monkeypatch.setattr(daemon_ops, "_await_ready", lambda paths, *a, **k: None)

    def boom(self):
        raise OSError("injected: restore cannot write")

    monkeypatch.setattr(HarnessSnapshot, "restore", boom)

    failure = daemon_ops.run_daemon_start_operation(
        project, "godot", version_check=_OK_VERSION
    )

    assert isinstance(failure, Failure), failure
    assert failure.error.code == "daemon_not_running"  # still the start's failure
    assert "could NOT be rolled back" in failure.error.diagnostics
    assert "injected: restore cannot write" in failure.error.diagnostics
    # The files still differing from their pre-start state are spelled out.
    assert f"res://{HARNESS_RES_DIR}/{HARNESS_FILE}" in failure.error.diagnostics
    assert "project.godot" in failure.error.diagnostics


def test_failed_start_names_directory_residue_when_only_the_rmdir_fails(
    tmp_path, short_runtime, monkeypatch
):
    # PR #680 recheck 3: a restore can fail AFTER every captured file is already
    # back — the directory removal is its last step — leaving only a gda-created
    # directory behind. `pending()` measures files by bytes, so the residual list
    # was empty exactly when the residue was directory-only; the measured delta
    # must name still-present captured-absent directories too.
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "_spawn_daemon", lambda *a, **k: None)
    monkeypatch.setattr(daemon_ops, "_await_ready", lambda paths, *a, **k: None)

    real_rmdir = _Path.rmdir

    def boom(self):
        raise OSError("injected: directory removal failure")

    monkeypatch.setattr(_Path, "rmdir", boom)
    try:
        failure = daemon_ops.run_daemon_start_operation(
            project, "godot", version_check=_OK_VERSION
        )
    finally:
        monkeypatch.setattr(_Path, "rmdir", real_rmdir)

    assert isinstance(failure, Failure), failure
    assert failure.error.code == "daemon_not_running"
    assert "could NOT be rolled back" in failure.error.diagnostics
    assert "injected: directory removal failure" in failure.error.diagnostics
    # Every captured file is back, so the ONLY residue is the created directory —
    # and it is named, not silently omitted.
    harness_dir = project / HARNESS_RES_DIR
    assert harness_dir.is_dir()
    assert not (harness_dir / HARNESS_FILE).exists()
    assert f"res://{HARNESS_RES_DIR}" in failure.error.diagnostics
    assert f"res://{HARNESS_RES_DIR}/{HARNESS_FILE}" not in failure.error.diagnostics


def test_original_failure_carries_the_rollback_failure_as_a_note(
    tmp_path, short_runtime, monkeypatch
):
    # PR #688 review: when the start fails AND the snapshot restore also fails, the
    # original error must stay the primary failure without swallowing the rollback
    # outcome — it carries an exception note naming the restore failure and the
    # measured residual paths, per ADR-0018's report-what-still-differs requirement.
    project = _project(tmp_path)

    def spawn_boom(*args, **kwargs):
        raise OSError("injected: original spawn failure")

    monkeypatch.setattr(daemon_ops, "_spawn_daemon", spawn_boom)

    def restore_boom(self):
        raise OSError("injected: restore cannot write")

    monkeypatch.setattr(HarnessSnapshot, "restore", restore_boom)

    with pytest.raises(OSError, match="injected: original spawn failure") as excinfo:
        daemon_ops.run_daemon_start_operation(
            project, "godot", version_check=_OK_VERSION
        )

    notes = "\n".join(getattr(excinfo.value, "__notes__", []))
    assert "could NOT be rolled back" in notes
    assert "injected: restore cannot write" in notes
    # The residual delta is measured off the snapshot, files then directories.
    assert f"res://{HARNESS_RES_DIR}/{HARNESS_FILE}" in notes
    assert "project.godot" in notes


def test_original_failure_survives_when_restore_and_measurement_both_fail(
    tmp_path, short_runtime, monkeypatch
):
    # PR #688 recheck: the same filesystem condition can break the restore AND the
    # residual measurement (an unreadable project.godot does both). The original
    # operation error must stay the primary exception — never displaced by a thrown
    # measurement — and the note must still report the rollback failure with the
    # unmeasurable path named as residue.
    project = _project(tmp_path)
    project_godot = project / "project.godot"

    def spawn_boom(*args, **kwargs):
        # The reviewer's real-I/O shape: the project file becomes unreadable
        # immediately before the operation fails, after the install mutated it.
        project_godot.chmod(0o000)
        raise OSError("injected: original spawn failure")

    monkeypatch.setattr(daemon_ops, "_spawn_daemon", spawn_boom)

    try:
        with pytest.raises(
            OSError, match="injected: original spawn failure"
        ) as excinfo:
            daemon_ops.run_daemon_start_operation(
                project, "godot", version_check=_OK_VERSION
            )
    finally:
        project_godot.chmod(0o644)

    notes = "\n".join(getattr(excinfo.value, "__notes__", []))
    assert "could NOT be rolled back" in notes
    assert "project.godot (state unmeasurable: " in notes
    # The paths the measurement COULD read are still individually reported.
    assert f"res://{HARNESS_RES_DIR}/{HARNESS_FILE}" in notes


# --- the mutation receipt on both halves (#654) -------------------------------


def test_start_result_names_the_paths_and_sections_the_install_created(
    tmp_path, short_runtime, fake_ready, monkeypatch
):
    # #654 (GDA-DF-039): a `daemon start` writes into project.godot and addons/, so
    # unattended automation can commit or ship the harness by accident. The result
    # therefore names the exact set it created, which `daemon uninstall` reverses.
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "_spawn_daemon", lambda *a, **k: None)

    started = daemon_ops.run_daemon_start_operation(
        project, "godot", version_check=_OK_VERSION
    )

    assert isinstance(started, DaemonStartResult), started
    assert started.created_paths == [
        "res://addons",
        "res://addons/gda_harness",
        f"res://{HARNESS_RES_DIR}/{HARNESS_FILE}",
    ]
    assert started.created_sections == ["[autoload]"]


def test_already_running_start_reports_an_empty_receipt_when_nothing_is_created(
    tmp_path, short_runtime, monkeypatch
):
    # The idempotent repeat start creates nothing, so its receipt is empty — the
    # receipt is what THIS call wrote, not a standing inventory of the install.
    project = _project(tmp_path)
    install_harness(project)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 999)

    started = daemon_ops.run_daemon_start_operation(
        project, None, version_check=_OK_VERSION
    )

    assert isinstance(started, DaemonStartResult)
    assert started.created_paths == []
    assert started.created_sections == []


def test_uninstall_result_names_every_removed_path_and_section(
    tmp_path, short_runtime, monkeypatch
):
    # The removal half: the script, the engine-written .uid sidecar (GDA-DF-009) and
    # the emptied addon dir, plus the generated [autoload] section (GDA-DF-020).
    project = _project(tmp_path)
    install_harness(project)
    (project / HARNESS_RES_DIR / f"{HARNESS_FILE}.uid").write_text(
        "uid://bxxxxxxxxxxxxx\n", encoding="utf-8"
    )
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)

    outcome = daemon_ops.run_daemon_uninstall_operation(project)

    assert isinstance(outcome, DaemonUninstallResult), outcome
    assert outcome.removed_paths == [
        f"res://{HARNESS_RES_DIR}/{HARNESS_FILE}",
        f"res://{HARNESS_RES_DIR}/{HARNESS_FILE}.uid",
        f"res://{HARNESS_RES_DIR}",
    ]
    assert outcome.removed_sections == ["[autoload]"]


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


# --- `gda daemon install`: the explicit half of an implicit step (#670) --------
# ADR-0018 point 1 named an agent-runnable `gda daemon install`; the delivered
# surface folded it into `daemon start` and a 2026-06-23 outcome note recorded that
# there was no install-without-start use case. Dogfooding found one that is not about
# starting anything (GDA-DF-024): an agent looking for the harness step types the
# command the ADR names, gets "no such command", and cannot tell whether gda installs
# a harness at all. It is the SAME idempotent install `daemon start` performs — the
# one `install_harness` seam — never a second implementation.


def test_install_performs_the_first_install_and_reports_what_it_created(
    tmp_path, short_runtime, monkeypatch
):
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)

    outcome = daemon_ops.run_daemon_install_operation(project)

    assert isinstance(outcome, daemon_ops.DaemonInstallResult), outcome
    assert outcome.installed_harness is True
    assert outcome.harness_synced is False  # a first install is not a resync
    assert outcome.harness_version == HARNESS_VERSION
    assert outcome.created_paths == [
        "res://addons",
        f"res://{HARNESS_RES_DIR}",
        f"res://{HARNESS_RES_DIR}/{HARNESS_FILE}",
    ]
    assert outcome.created_sections == ["[autoload]"]
    assert (project / HARNESS_RES_DIR / HARNESS_FILE).exists()
    assert installed_harness_version(project) == HARNESS_VERSION


def test_install_is_idempotent(tmp_path, short_runtime, monkeypatch):
    # Run twice: the second changes nothing and says so, so an agent can call it
    # unconditionally before a live session (the reason it exists).
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)
    daemon_ops.run_daemon_install_operation(project)
    before = (project / "project.godot").read_bytes()

    outcome = daemon_ops.run_daemon_install_operation(project)

    assert isinstance(outcome, daemon_ops.DaemonInstallResult), outcome
    assert outcome.installed_harness is False
    assert outcome.harness_synced is False
    assert outcome.created_paths == [] and outcome.created_sections == []
    assert (project / "project.godot").read_bytes() == before


def test_install_resyncs_a_stale_harness(tmp_path, short_runtime, monkeypatch):
    # The same version self-sync `daemon start` performs (#225): a harness from an
    # older gda is re-materialized, and that is reported as a SYNC, not a first install.
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: None)
    daemon_ops.run_daemon_install_operation(project)
    harness = project / HARNESS_RES_DIR / HARNESS_FILE
    harness.write_bytes(b"# gda-harness-version: stale-old\nextends Node\n")

    outcome = daemon_ops.run_daemon_install_operation(project)

    assert isinstance(outcome, daemon_ops.DaemonInstallResult), outcome
    assert outcome.harness_synced is True
    assert outcome.installed_harness is True
    assert outcome.created_paths == []  # a rewrite creates nothing
    assert installed_harness_version(project) == HARNESS_VERSION


def test_install_is_allowed_while_a_daemon_is_running(
    tmp_path, short_runtime, monkeypatch
):
    # The asymmetry with `uninstall`, which is refused there: installing over a live
    # daemon is exactly what a repeat `daemon start` already does, and it cannot yank
    # an autoload out from under a running session.
    project = _project(tmp_path)
    monkeypatch.setattr(daemon_ops, "daemon_pid", lambda paths: 999)

    outcome = daemon_ops.run_daemon_install_operation(project)

    assert isinstance(outcome, daemon_ops.DaemonInstallResult), outcome
    assert outcome.installed_harness is True


def test_install_without_a_project_is_a_typed_refusal(monkeypatch):
    outcome = daemon_ops.run_daemon_install_operation(None)

    assert isinstance(outcome, Failure), outcome
    assert outcome.error.code == "project_not_found"


def test_a_failed_install_restores_the_project(
    tmp_path, short_runtime, monkeypatch, read_only_project_godot
):
    # The transactional guarantee `daemon start` gained in #654 applies here for the
    # same reason: `install_harness` materializes the file first and writes the config
    # second, so a config write that fails leaves the harness on disk. Same snapshot,
    # same restore — this command must not be the one that leaves residue behind.
    project = _project(tmp_path)
    project_godot = project / "project.godot"
    before = project_godot.read_bytes()
    read_only_project_godot(project_godot)

    with pytest.raises(PermissionError):
        daemon_ops.run_daemon_install_operation(project)

    assert not (project / HARNESS_RES_DIR).exists()
    assert not (project / "addons").exists()
    assert project_godot.read_bytes() == before


def test_cli_daemon_install_emits_the_install_json(
    tmp_path, short_runtime, monkeypatch
):
    project = _project(tmp_path)

    result = CliRunner().invoke(
        app, ["daemon", "install", "--project", str(project), "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["installed_harness"] is True
    assert payload["harness_version"] == HARNESS_VERSION
    assert (project / HARNESS_RES_DIR / HARNESS_FILE).exists()


def test_cli_daemon_install_renders_what_it_did(tmp_path, short_runtime, monkeypatch):
    project = _project(tmp_path)
    CliRunner().invoke(app, ["daemon", "install", "--project", str(project)])

    repeat = CliRunner().invoke(app, ["daemon", "install", "--project", str(project)])

    assert repeat.exit_code == 0, repeat.output
    assert "already installed" in repeat.stdout


def test_cli_daemon_install_is_self_describing_with_the_live_constraint(tmp_path):
    result = CliRunner().invoke(app, ["daemon", "install", "--schema"])

    assert result.exit_code == 0, result.output
    schema = json.loads(result.stdout)
    assert "installed_harness" in json.dumps(schema)
    # A daemon-lifecycle command, so it carries the live platform constraint — but no
    # engine floor: it never launches Godot (gda.execution.live_stack_constraints).
    assert schema["constraints"]["platforms"] == ["linux", "macos"]
    assert schema["constraints"]["min_godot_version"] is None
