"""`gda perf` — runtime performance monitoring of the running game, LIVE (#223).

Engine-free: a fake daemon runner at the LIVE seam exercises the full
Typer→classify_live→JSON pipeline (mirroring ``test_game_commands``), and the
no-daemon attach-or-fail path runs the real ``DaemonRunner`` against an empty
runtime dir. The real-engine round trip (the time-windowed harness base + the
Performance snapshot) is the e2e in ``test_e2e_perf``.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.exit_codes import EXIT_LIVE
from gda.runner import RunResult
from tests.support import (
    PERF_MONITOR_PROPERTY_RESULT,
    PERF_MONITOR_SIGNAL_RESULT,
    PERF_MONITORS_RESULT,
    error_sentinel,
    inject_live_runner,
    sentinel,
)


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


# --- perf monitors (single-frame snapshot) ------------------------------------


def test_perf_monitors_emits_a_snapshot_through_the_live_channel(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_MONITORS_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["perf", "monitors", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["timestamp"] == 12345
    assert data["monitors"]["fps"]["value"] == 60.0
    assert data["monitors"]["node_count"]["type"] == "float"
    # Routed through the LIVE seam, dispatching the perf-monitors operation (no args).
    assert fake.calls == [("perf-monitors", {})]


def test_perf_monitors_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    # No fake: the real DaemonRunner + discovery run against an empty runtime dir,
    # so no daemon is found — the attach-or-fail typed error (ADR-0017).
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app, ["perf", "monitors", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert error["category"] == "live"
    assert "gda daemon start" in error["message"]


def test_perf_monitors_schema_is_self_describing():
    result = CliRunner().invoke(app, ["perf", "monitors", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "input" in schema and "output" in schema
    assert schema["kind"] == "live"


def test_perf_monitors_without_a_project_reports_project_not_found(
    monkeypatch, tmp_path
):
    # No --project and a projectless cwd -> the project resolves to None, which is a
    # project-resolution error, NOT a daemon error (ADR-0021).
    monkeypatch.chdir(tmp_path)  # tmp_path holds no project.godot

    result = CliRunner().invoke(app, ["perf", "monitors", "--json"])

    assert result.exit_code != 0, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"


def test_perf_monitors_on_non_unix_reports_live_unsupported_platform(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("gda.live_runner._is_unix", lambda: False)

    result = CliRunner().invoke(
        app, ["perf", "monitors", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code != 0, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "live_unsupported_platform"


# --- perf monitor (time-windowed property/signal timeline) --------------------


def test_perf_monitor_property_emits_a_timeline_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(PERF_MONITOR_PROPERTY_RESULT), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "position",
            "--frames",
            "3",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "property"
    assert data["property"] == "position"
    assert [s["frame"] for s in data["samples"]] == [0, 1, 2]
    assert data["emissions"] == []
    # The node, property, signal (absent) and frame count are threaded to the op.
    assert fake.calls == [
        (
            "perf-monitor",
            {
                "node": "/root/Main/Player",
                "property": "position",
                "signal": None,
                "frames": 3,
            },
        )
    ]


def test_perf_monitor_signal_records_emissions_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_MONITOR_SIGNAL_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--signal",
            "hit",
            "--frames",
            "3",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "signal"
    assert data["signal"] == "hit"
    assert data["emissions"][0]["args"] == [42]
    assert data["samples"] == []
    assert fake.calls == [
        (
            "perf-monitor",
            {
                "node": "/root/Main/Player",
                "property": None,
                "signal": "hit",
                "frames": 3,
            },
        )
    ]


def test_perf_monitor_default_frame_count_is_threaded(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(PERF_MONITOR_PROPERTY_RESULT), stderr="", exit_code=0
        ),
    )

    CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "position",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    # The default frames (60) is passed through when --frames is omitted.
    assert fake.calls[0][1]["frames"] == 60


def test_perf_monitor_missing_node_reports_live_perf_node_not_found(
    monkeypatch, tmp_path
):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel(
                "live_perf_node_not_found", "no node at runtime path"
            ),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Ghost",
            "--property",
            "position",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_perf_node_not_found"
    assert error["category"] == "live"


def test_perf_monitor_unknown_property_reports_live_perf_property_not_found(
    monkeypatch, tmp_path
):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel(
                "live_perf_property_not_found", "no readable property"
            ),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "nope",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "live_perf_property_not_found"


def test_perf_monitor_unknown_signal_reports_live_perf_signal_not_found(
    monkeypatch, tmp_path
):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_perf_signal_not_found", "no signal"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--signal",
            "nope",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "live_perf_signal_not_found"


def test_perf_monitor_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "position",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "daemon_not_running"


# --- argv selector / frames validation (#239) ---------------------------------
# Exactly one of --property/--signal is required and --frames is bounded. On the
# argv path these are usage errors (exit 2), the engine is never reached; the
# --params-json path surfaces them as the structured invalid_params error (see
# tests/test_params_json.py). Both forms derive from the one PerfMonitorParams
# model (ADR-0015), so neither can bypass the rule.


def test_perf_monitor_argv_both_selectors_is_a_usage_error(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(PERF_MONITOR_PROPERTY_RESULT), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "position",
            "--signal",
            "hit",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_perf_monitor_argv_no_selector_is_a_usage_error(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(PERF_MONITOR_PROPERTY_RESULT), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_perf_monitor_argv_frames_over_range_is_a_usage_error(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(PERF_MONITOR_PROPERTY_RESULT), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "position",
            "--frames",
            "601",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_perf_monitor_schema_reports_kind_live_and_is_self_describing():
    result = CliRunner().invoke(app, ["perf", "monitor", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "input" in schema and "output" in schema
    assert schema["kind"] == "live"
