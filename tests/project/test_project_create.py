"""S3: ``gda project create`` against a fake runner (issue #1027).

The command creates a minimal project at a destination. The destination is an
operation input, not a project context: the command declares no ``--project``,
reads neither ``$GDA_PROJECT`` nor the cwd as a project, and its engine run loads
no project (#1035). These tests pin the CLI half of that contract engine-free:
the params model, the argv/``--params-json`` parity, the launch it asks for, and
the envelopes the operation's refusals become. The engine half is in
``test_e2e_project_create.py``.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.commands.project import (
    PROJECT_CREATE_COMMAND,
    ProjectCreateParams,
    ProjectCreateResult,
    render_project_create,
)
from gda.core.failure.error_codes import ERROR_CODE_BY_CODE
from gda.exit_codes import EXIT_OPERATION
from gda.core.contract.envelope import ErrorCategory
from gda.core.engine.launch import RunResult
from tests.support import (
    ENGINE_BANNER,
    FakeRunner,
    assert_operation_error,
    invoke_cli,
    invoke_operation_error,
    minimal_project,
    sentinel,
)

CREATED = {
    "path": "/work/game",
    "name": "My Game",
    "created_dirs": ["/work/game"],
    "project_file": "/work/game/project.godot",
}


def _record_launches(monkeypatch, payload: dict = CREATED) -> list[tuple]:
    # The runner seam, recorded with the keyword that decides whether the engine
    # may load a project from the invoker's working directory (#1035).
    launches: list[tuple] = []
    result = RunResult(stdout=ENGINE_BANNER + sentinel(payload), stderr="", exit_code=0)

    def record(binary, project=None, *, ignore_cwd=False):
        fake = FakeRunner(result)
        launches.append((project, ignore_cwd, fake))
        return fake

    monkeypatch.setattr("gda.dispatch.make_runner", record)
    return launches


# --- the params model -------------------------------------------------------


def test_a_relative_destination_resolves_against_the_invocation_cwd(
    monkeypatch, tmp_path
):
    # The engine runs in an empty directory of its own (#1035), so the CLI must
    # hand it an absolute path. Absolute, not canonical: `..` stays as named.
    monkeypatch.chdir(tmp_path)

    params = ProjectCreateParams(destination="games/../new", name="x")

    assert params.destination == str(Path.cwd() / "games/../new")


def test_a_home_relative_destination_expands(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    params = ProjectCreateParams(destination="~/game", name="x")

    assert params.destination == str(tmp_path / "game")


@pytest.mark.parametrize("destination", ["res://game", "user://game", "uid://abc", ""])
def test_a_value_the_operation_refuses_passes_the_model_unchanged(destination):
    # A virtual path and an empty string are refused by the OPERATION with
    # invalid_path, so the refusal is an Error envelope on both input channels.
    # An empty string must not become the cwd on the way.
    params = ProjectCreateParams(destination=destination, name="x")

    assert params.destination == destination


@pytest.mark.parametrize("name", ["", "   ", "  My Game  "])
def test_the_model_accepts_the_name_as_given(name):
    # The operation strips the name and refuses an empty result: a model refusal
    # would be an argv usage error, not the invalid_params envelope (#1027).
    assert ProjectCreateParams(destination="/d", name=name).name == name


# --- the descriptor and the surface -------------------------------------------


def test_the_command_inherits_no_project_and_runs_the_sentinel_operation():
    assert PROJECT_CREATE_COMMAND.operation == "project-create"
    assert PROJECT_CREATE_COMMAND.inherits_project is False
    # Only the sentinel arm gets the #1035 launch; a recipe would not.
    assert PROJECT_CREATE_COMMAND.recipe is None


def test_the_schema_declares_the_request_and_the_result():
    result = CliRunner().invoke(app, ["project", "create", "--schema"])

    assert result.exit_code == 0, result.stdout
    schema = json.loads(result.stdout)
    assert set(schema["input"]["properties"]) == {"destination", "name"}
    assert set(schema["input"]["required"]) == {"destination", "name"}
    assert set(schema["output"]["properties"]) == {
        "path",
        "name",
        "created_dirs",
        "project_file",
    }
    argv = {binding["name"]: binding for binding in schema["argv"]}
    assert argv["destination"]["kind"] == "argument"
    assert argv["name"]["option"] == "--name"
    assert argv["name"]["required"] is True
    assert "project" not in argv


def test_the_command_declares_no_project_option(tmp_path):
    result = CliRunner().invoke(
        app,
        ["project", "create", "d", "--name", "x", "--project", str(tmp_path), "--json"],
    )

    assert result.exit_code == 2, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "unknown_option"


def test_destination_not_empty_is_an_operation_code_like_already_exists():
    spec = ERROR_CODE_BY_CODE["destination_not_empty"]
    peer = ERROR_CODE_BY_CODE["already_exists"]

    assert spec.category is ErrorCategory.OPERATION
    assert spec.exit_code == EXIT_OPERATION
    assert (spec.category, spec.exit_code, spec.source) == (
        peer.category,
        peer.exit_code,
        peer.source,
    )


# --- dispatch -----------------------------------------------------------------


def test_the_engine_loads_no_project_whatever_the_invoker_context(
    monkeypatch, tmp_path
):
    # The cwd is a project and $GDA_PROJECT names another: neither is read as the
    # project, and the runner is asked to ignore the cwd (#1035).
    minimal_project(tmp_path)
    other = minimal_project(tmp_path / "other")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GDA_PROJECT", str(other))
    launches = _record_launches(monkeypatch)

    result = CliRunner().invoke(
        app, ["project", "create", "game", "--name", "My Game", "--json"]
    )

    assert result.exit_code == 0, result.stdout
    [(project, ignore_cwd, fake)] = launches
    assert (project, ignore_cwd) == (None, True)
    assert fake.calls == [
        ("project-create", {"destination": str(tmp_path / "game"), "name": "My Game"})
    ]
    assert json.loads(result.stdout) == CREATED


def test_the_params_json_path_dispatches_the_same_request(monkeypatch, tmp_path):
    # ADR-0015 parity: the form gda-mcp dispatches normalizes and launches alike.
    minimal_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    launches = _record_launches(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "project",
            "create",
            "--params-json",
            json.dumps({"destination": "game", "name": "My Game"}),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    [(project, ignore_cwd, fake)] = launches
    assert (project, ignore_cwd) == (None, True)
    assert fake.calls == [
        ("project-create", {"destination": str(tmp_path / "game"), "name": "My Game"})
    ]


@pytest.mark.parametrize(
    "code",
    [
        "already_exists",
        "destination_not_empty",
        "invalid_path",
        "invalid_params",
        "save_failed",
    ],
)
def test_each_refusal_the_operation_reports_is_its_envelope(monkeypatch, code):
    result = invoke_operation_error(
        monkeypatch,
        ["project", "create", "/work/game", "--name", "x", "--json"],
        code,
        "refused",
        "project-create",
    )

    assert_operation_error(result, code, "refused")


def test_the_human_rendering_names_the_project_and_what_was_created(monkeypatch):
    result, _ = invoke_cli(
        monkeypatch,
        ["project", "create", "/work/game", "--name", "My Game"],
        stdout=sentinel(CREATED),
    )

    assert result.exit_code == 0, result.stdout
    assert result.stdout.splitlines() == [
        "created project: /work/game",
        "name: My Game",
        "project_file: /work/game/project.godot",
        "created_dirs: /work/game",
    ]


def test_the_human_rendering_says_when_no_directory_was_created():
    rendered = render_project_create(
        ProjectCreateResult(**{**CREATED, "created_dirs": []})
    )

    assert "created_dirs: (none)" in rendered.splitlines()
