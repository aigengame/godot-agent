"""`gda game` — the running game's runtime scene graph, served LIVE (#7, ADR-0019).

Engine-free: a fake daemon runner at the LIVE seam exercises the full
Typer→classify_live→JSON pipeline, and the no-daemon attach-or-fail path runs the
real ``DaemonRunner`` against an empty runtime dir. The real-engine round trip is
the e2e.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.exit_codes import EXIT_LIVE
from gda.runner import RunResult
from tests.support import GAME_TREE_RESULT, inject_live_runner, sentinel


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


def test_game_tree_emits_runtime_tree_json_through_the_live_channel(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_TREE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["game", "tree", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["root"]["name"] == "Main"
    assert data["root"]["children"][0]["type"] == "CharacterBody2D"
    # Routed through the LIVE seam, dispatching the game-tree operation (no args).
    assert fake.calls == [("game-tree", {})]


def test_game_tree_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    # No fake: the real DaemonRunner + discovery run, against an empty runtime dir
    # so no daemon is found — the attach-or-fail typed error (ADR-0017).
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app, ["game", "tree", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert error["category"] == "live"
    assert "gda daemon start" in error["message"]


def test_game_tree_schema_is_self_describing():
    result = CliRunner().invoke(app, ["game", "tree", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    # Self-describes its input and output contracts like any headless command.
    assert "input" in schema and "output" in schema


def test_game_tree_without_a_project_reports_project_not_found(monkeypatch, tmp_path):
    # No --project and a projectless cwd -> the project resolves to None, which is
    # a project-resolution error, NOT a daemon error (ADR-0021).
    monkeypatch.chdir(tmp_path)  # tmp_path holds no project.godot

    result = CliRunner().invoke(app, ["game", "tree", "--json"])

    assert result.exit_code != 0, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"


def test_game_tree_on_non_unix_reports_live_unsupported_platform(monkeypatch, tmp_path):
    # The live stack is UNIX-only (UDS); a non-UNIX platform fails fast with the
    # typed error, before touching the daemon (ADR-0021).
    monkeypatch.setattr("gda.live_runner._is_unix", lambda: False)

    result = CliRunner().invoke(
        app, ["game", "tree", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code != 0, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "live_unsupported_platform"
