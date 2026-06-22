"""`gda diag` — runtime diagnostics of the running game, served LIVE (#224).

Engine-free: a fake daemon runner at the LIVE seam exercises the full
Typer -> classify_live -> JSON pipeline, and the no-daemon attach-or-fail path
runs the real ``DaemonRunner`` against an empty runtime dir. The real-engine
read-back is the e2e. ``diag`` is a daemon-served live op (the daemon reads its
own Session log), but from the CLI's side it is an ordinary ``kind = LIVE``
command — same routing as ``game``.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.exit_codes import EXIT_LIVE
from gda.runner import RunResult
from tests.support import (
    DIAG_ERRORS_RESULT,
    DIAG_LOG_RESULT,
    error_sentinel,
    inject_live_runner,
    sentinel,
)


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


def test_diag_errors_emits_structured_errors_json_through_the_live_channel(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(DIAG_ERRORS_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["diag", "errors", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["errors"][0]["level"] == "error"
    assert data["errors"][0]["message"] == "boom"
    assert data["errors"][1]["level"] == "warning"  # warnings included
    # Routed through the LIVE seam, dispatching the diag-errors op (no limit).
    assert fake.calls == [("diag-errors", {"limit": None})]


def test_diag_errors_passes_limit_through(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(DIAG_ERRORS_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["diag", "errors", "--limit", "5", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls == [("diag-errors", {"limit": 5})]


def test_diag_errors_rejects_a_non_positive_limit_on_the_argv_path(tmp_path):
    # `--limit` is bound to >= 1 (Click min): a zero/negative limit is a usage
    # error, not a silently-accepted "no limit". No live runner is needed — Click
    # rejects before any dispatch.
    for bad in ("0", "-1"):
        result = CliRunner().invoke(
            app, ["diag", "errors", "--limit", bad, "--project", str(_project(tmp_path)), "--json"]
        )
        assert result.exit_code == 2, (bad, result.stdout + result.stderr)


def test_diag_log_rejects_a_non_positive_limit_on_the_argv_path(tmp_path):
    for bad in ("0", "-1"):
        result = CliRunner().invoke(
            app, ["diag", "log", "--limit", bad, "--project", str(_project(tmp_path)), "--json"]
        )
        assert result.exit_code == 2, (bad, result.stdout + result.stderr)


def test_diag_log_emits_raw_lines_json_through_the_live_channel(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(DIAG_LOG_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["diag", "log", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert "known line" in data["lines"]
    assert fake.calls == [("diag-log", {"limit": None})]


def test_diag_errors_human_output_renders_levels(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(DIAG_ERRORS_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["diag", "errors", "--project", str(_project(tmp_path))])

    assert result.exit_code == 0, result.stdout + result.stderr
    # Human output names the level and message; the location is shown when present.
    assert "boom" in result.stdout
    assert "res://main.gd:9" in result.stdout


def test_diag_log_human_output_renders_lines(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(DIAG_LOG_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["diag", "log", "--project", str(_project(tmp_path))])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "known line" in result.stdout


def test_diag_errors_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    # No fake: the real DaemonRunner + discovery run against an empty runtime dir.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app, ["diag", "errors", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert error["category"] == "live"


def test_diag_errors_log_unavailable_is_a_typed_live_error(monkeypatch, tmp_path):
    # The daemon-served `live_log_unavailable` rides the same envelope, surfaced by
    # classify_live as a registered LIVE error.
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_log_unavailable", "log missing"),
            stderr="",
            exit_code=EXIT_LIVE,
        ),
    )

    result = CliRunner().invoke(
        app, ["diag", "errors", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_log_unavailable"
    assert error["category"] == "live"


def test_diag_params_json_rejects_a_non_positive_limit_as_invalid_params(monkeypatch, tmp_path):
    # The `ge=1` bound on DiagErrorsParams / DiagLogParams: a zero/negative limit
    # via --params-json is a structured `invalid_params` (reflected in --schema),
    # not a silent "no limit". No dispatch happens — the model validation fails
    # first, so no live runner is needed.
    for op, key in (("errors", "errors"), ("log", "log")):  # both diag ops
        for bad in (0, -1):
            result = CliRunner().invoke(
                app,
                ["diag", op, "--params-json", json.dumps({"limit": bad}),
                 "--project", str(_project(tmp_path)), "--json"],
            )
            assert result.exit_code != 0, (op, bad, result.stdout + result.stderr)
            err = json.loads(result.stdout)["error"]
            assert err["code"] == "invalid_params", (op, bad, err)


def test_diag_errors_schema_reflects_the_limit_lower_bound():
    result = CliRunner().invoke(app, ["diag", "errors", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    # The `ge=1` constraint surfaces in the input schema as a minimum on `limit`.
    limit_schema = schema["input"]["properties"]["limit"]
    minimums = [sub.get("minimum") for sub in limit_schema.get("anyOf", [limit_schema])]
    assert 1 in minimums, limit_schema


def test_diag_errors_schema_is_self_describing_and_live():
    result = CliRunner().invoke(app, ["diag", "errors", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    # Self-describes its input/output contract and its LIVE execution kind.
    assert "input" in schema and "output" in schema
    assert schema["kind"] == "live"


def test_diag_log_schema_is_self_describing_and_live():
    result = CliRunner().invoke(app, ["diag", "log", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "input" in schema and "output" in schema
    assert schema["kind"] == "live"
