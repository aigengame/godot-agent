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
from tests.support import (
    LOGGER_TAIL_RAW_RESULT,
    LOGGER_TAIL_RESULT,
    invoke_live,
    minimal_project,
)


def test_logger_tail_emits_structured_records_json_through_the_live_channel(
    monkeypatch, tmp_path
):
    result, fake = invoke_live(
        monkeypatch,
        ["logger", "tail", "--project", str(minimal_project(tmp_path)), "--json"],
        LOGGER_TAIL_RESULT,
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
    result, fake = invoke_live(
        monkeypatch,
        [
            "logger",
            "tail",
            "--level",
            "warning",
            "--limit",
            "5",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
        LOGGER_TAIL_RESULT,
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls == [
        ("logger-tail", {"level": "warning", "limit": 5, "raw": False})
    ]


def test_logger_tail_raw_passes_raw_flag_and_returns_verbatim_info_records(
    monkeypatch, tmp_path
):
    result, fake = invoke_live(
        monkeypatch,
        [
            "logger",
            "tail",
            "--raw",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
        LOGGER_TAIL_RAW_RESULT,
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    # --raw returns LogRecord[] too: every line a verbatim, unclassified info record.
    assert "lines" not in data
    messages = [r["message"] for r in data["records"]]
    assert "known line" in messages
    assert "ERROR: boom" in messages  # the header is verbatim, not classified
    assert all(r["level"] == "info" for r in data["records"])
    assert fake.calls == [("logger-tail", {"level": None, "limit": None, "raw": True})]


def test_logger_tail_rejects_a_non_positive_limit_on_the_argv_path(tmp_path):
    # `--limit` is bound to >= 1 (Click min): a zero/negative limit is a usage
    # error, not a silently-accepted "no limit". No live runner needed.
    for bad in ("0", "-1"):
        result = CliRunner().invoke(
            app,
            [
                "logger",
                "tail",
                "--limit",
                bad,
                "--project",
                str(minimal_project(tmp_path)),
                "--json",
            ],
        )
        assert result.exit_code == 2, (bad, result.stdout + result.stderr)


def test_logger_tail_rejects_an_unknown_level_on_the_argv_path(tmp_path):
    # `--level` is the closed enum; an out-of-set value is a usage error.
    result = CliRunner().invoke(
        app,
        [
            "logger",
            "tail",
            "--level",
            "trace",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )
    assert result.exit_code == 2, result.stdout + result.stderr


def test_logger_tail_human_output_renders_records(monkeypatch, tmp_path):
    result, _ = invoke_live(
        monkeypatch,
        ["logger", "tail", "--project", str(minimal_project(tmp_path))],
        LOGGER_TAIL_RESULT,
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    # Human output names the level and message; the location is shown when present.
    assert "known line" in result.stdout
    assert "boom" in result.stdout
    assert "res://main.gd:9" in result.stdout


def test_logger_tail_raw_human_output_renders_lines(monkeypatch, tmp_path):
    result, _ = invoke_live(
        monkeypatch,
        ["logger", "tail", "--raw", "--project", str(minimal_project(tmp_path))],
        LOGGER_TAIL_RAW_RESULT,
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "known line" in result.stdout


def test_logger_tail_params_json_rejects_a_non_positive_limit_as_invalid_params(
    monkeypatch, tmp_path
):
    for bad in (0, -1):
        result = CliRunner().invoke(
            app,
            [
                "logger",
                "tail",
                "--params-json",
                json.dumps({"limit": bad}),
                "--project",
                str(minimal_project(tmp_path)),
                "--json",
            ],
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
