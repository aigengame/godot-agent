"""`gda logger tail` — the running game's STRUCTURED runtime log, served LIVE (#281).

Engine-free: a fake daemon runner at the LIVE seam exercises the full
Typer -> classify_live -> JSON pipeline, and the no-daemon attach-or-fail path
runs the real ``DaemonRunner`` against an empty runtime dir. The real-engine
read-back is the e2e. Like ``diag``, ``logger tail`` is a daemon-served live op
(the daemon reads its own Session log), but from the CLI's side it is an ordinary
``kind = LIVE`` command — same routing as ``game``.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.exit_codes import EXIT_LIVE
from gda.runner import RunResult
from tests.support import (
    LOGGER_TAIL_RAW_RESULT,
    LOGGER_TAIL_RESULT,
    error_sentinel,
    inject_live_runner,
    sentinel,
)


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


def test_logger_tail_emits_structured_records_json_through_the_live_channel(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(LOGGER_TAIL_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["logger", "tail", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["records"][0]["level"] == "info"
    assert data["records"][1]["level"] == "error"
    assert data["records"][1]["origin"] == "engine"
    assert data["records"][1]["source"]["file"] == "res://main.gd"
    # Routed through the LIVE seam, dispatching the logger-tail op (no filters).
    assert fake.calls == [("logger-tail", {"level": None, "limit": None, "raw": False})]


def test_logger_tail_passes_level_and_limit_through(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(LOGGER_TAIL_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        ["logger", "tail", "--level", "warning", "--limit", "5",
         "--project", str(_project(tmp_path)), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls == [("logger-tail", {"level": "warning", "limit": 5, "raw": False})]


def test_logger_tail_raw_passes_raw_flag_and_returns_verbatim_lines(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(LOGGER_TAIL_RAW_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["logger", "tail", "--raw", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert "known line" in data["lines"]
    assert data["records"] == []
    assert fake.calls == [("logger-tail", {"level": None, "limit": None, "raw": True})]


def test_logger_tail_rejects_a_non_positive_limit_on_the_argv_path(tmp_path):
    # `--limit` is bound to >= 1 (Click min): a zero/negative limit is a usage
    # error, not a silently-accepted "no limit". No live runner needed.
    for bad in ("0", "-1"):
        result = CliRunner().invoke(
            app, ["logger", "tail", "--limit", bad, "--project", str(_project(tmp_path)), "--json"]
        )
        assert result.exit_code == 2, (bad, result.stdout + result.stderr)


def test_logger_tail_rejects_an_unknown_level_on_the_argv_path(tmp_path):
    # `--level` is the closed enum; an out-of-set value is a usage error.
    result = CliRunner().invoke(
        app, ["logger", "tail", "--level", "trace", "--project", str(_project(tmp_path)), "--json"]
    )
    assert result.exit_code == 2, result.stdout + result.stderr


def test_logger_tail_human_output_renders_records(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(LOGGER_TAIL_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["logger", "tail", "--project", str(_project(tmp_path))])

    assert result.exit_code == 0, result.stdout + result.stderr
    # Human output names the level and message; the location is shown when present.
    assert "known line" in result.stdout
    assert "boom" in result.stdout
    assert "res://main.gd:9" in result.stdout


def test_logger_tail_raw_human_output_renders_lines(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(LOGGER_TAIL_RAW_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["logger", "tail", "--raw", "--project", str(_project(tmp_path))])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "known line" in result.stdout


def test_logger_tail_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    # No fake: the real DaemonRunner + discovery run against an empty runtime dir.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app, ["logger", "tail", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert error["category"] == "live"


def test_logger_tail_log_unavailable_is_a_typed_live_error(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_log_unavailable", "log missing"),
            stderr="",
            exit_code=EXIT_LIVE,
        ),
    )

    result = CliRunner().invoke(
        app, ["logger", "tail", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_log_unavailable"
    assert error["category"] == "live"


def test_logger_tail_params_json_rejects_a_non_positive_limit_as_invalid_params(monkeypatch, tmp_path):
    for bad in (0, -1):
        result = CliRunner().invoke(
            app,
            ["logger", "tail", "--params-json", json.dumps({"limit": bad}),
             "--project", str(_project(tmp_path)), "--json"],
        )
        assert result.exit_code != 0, (bad, result.stdout + result.stderr)
        err = json.loads(result.stdout)["error"]
        assert err["code"] == "invalid_params", (bad, err)


def test_logger_tail_schema_reflects_the_limit_lower_bound_and_is_live():
    result = CliRunner().invoke(app, ["logger", "tail", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert schema["kind"] == "live"
    assert "input" in schema and "output" in schema
    limit_schema = schema["input"]["properties"]["limit"]
    minimums = [sub.get("minimum") for sub in limit_schema.get("anyOf", [limit_schema])]
    assert 1 in minimums, limit_schema


def test_diag_log_is_gone_superseded_by_logger_tail():
    # The raw `diag log` is SUPERSEDED by `gda logger tail --raw` (ADR-0026): it is
    # no longer a command. `diag errors` remains.
    result = CliRunner().invoke(app, ["diag", "log", "--schema"])
    assert result.exit_code != 0, result.stdout
    assert CliRunner().invoke(app, ["diag", "errors", "--schema"]).exit_code == 0
