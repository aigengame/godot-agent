"""S3: gda info with a fake Godot runner maps success to JSON output / exit 0."""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import (
    ENGINE_BANNER,
    VERSION_INFO,
    assert_operation_error,
    inject_runner,
    minimal_project,
    recording_runner,
    sentinel,
)


def test_info_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    # Engine banner / warnings around the sentinel, plus diagnostics on stderr.
    stdout = ENGINE_BANNER + "WARNING: benign\n" + sentinel(VERSION_INFO)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(app, ["info", "--json"])

    assert result.exit_code == 0
    # stdout carries ONLY the result payload — a single valid JSON object.
    data = json.loads(result.stdout)
    assert data["major"] == 4
    assert data["minor"] == 6
    assert data["string"] == "4.6.3-stable (official)"
    # The info operation was dispatched by name.
    assert fake.calls == [("info", {})]
    # Engine/script diagnostics are surfaced on stderr, not stdout.
    assert "engine diagnostic" in result.stderr


# --- `gda info --project`: accepted, validated, never inherited (#670) ---------


def _ok(monkeypatch) -> RunResult:
    return RunResult(stdout=sentinel(VERSION_INFO), stderr="", exit_code=0)


def test_info_accepts_an_explicit_project_and_runs_against_it(monkeypatch, tmp_path):
    # An orchestrator passes the same `--project` argv to every command; `gda info`
    # used to be the one that died with exit 2 on it (GDA-DF-032). It is now accepted,
    # and honoured the way every other command honours it — handed to the engine as
    # its project (ADR-0006).
    project = tmp_path / "game"
    minimal_project(project)
    projects = recording_runner(monkeypatch, _ok(monkeypatch))

    result = CliRunner().invoke(app, ["info", "--project", str(project), "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["major"] == 4
    assert projects == [project]


def test_info_refuses_an_explicit_project_that_is_not_one(monkeypatch, tmp_path):
    # Validated, not merely accepted: a `--project` that names no Godot project is the
    # ordinary structured refusal, not a silent run against the wrong root.
    recording_runner(monkeypatch, _ok(monkeypatch))

    result = CliRunner().invoke(app, ["info", "--project", str(tmp_path), "--json"])

    assert_operation_error(result, "project_not_found")


def test_info_ignores_an_inherited_project_context(monkeypatch, tmp_path):
    # `info` reports the ENGINE, so it must not acquire a project it was not given:
    # a stale $GDA_PROJECT in the shell would otherwise break the one command an agent
    # runs to find out whether anything works at all (#357's rule, same reasoning).
    monkeypatch.setenv("GDA_PROJECT", str(tmp_path / "gone"))
    projects = recording_runner(monkeypatch, _ok(monkeypatch))

    result = CliRunner().invoke(app, ["info", "--json"])

    assert result.exit_code == 0, result.stdout
    assert projects == [None]


def test_the_params_json_path_validates_the_project_the_same_way(monkeypatch, tmp_path):
    # ADR-0015 parity: the form gda-mcp dispatches must refuse identically.
    recording_runner(monkeypatch, _ok(monkeypatch))

    result = CliRunner().invoke(
        app, ["info", "--params-json", "{}", "--project", str(tmp_path), "--json"]
    )

    assert_operation_error(result, "project_not_found")


def test_the_project_option_is_not_an_operation_param(monkeypatch):
    # `--project` is a cross-cutting CLI option, not part of the operation's input
    # contract, so `info`'s `--schema` input stays the empty object (ADR-0004).
    result = CliRunner().invoke(app, ["info", "--schema"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["input"].get("properties", {}) == {}
