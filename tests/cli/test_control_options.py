"""Control-looking values must not change the command's input mode (#971)."""

import json
import subprocess

import pytest
from pydantic import BaseModel
import typer
from typer.testing import CliRunner

from gda.headless import schema_command_class, schema_option
from tests.support import GDA_CMD, panel_text


@pytest.mark.parametrize("equal_form", [False, True], ids=["space", "equals"])
@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_schema_token_as_option_value_is_an_argv_refusal(
    equal_form, json_output, tmp_path
):
    project = tmp_path / "project"
    project.mkdir()
    config = project / "project.godot"
    config.write_text("config_version=5\n", encoding="utf-8")
    updates = (
        ["--updates-json=--schema"] if equal_form else ["--updates-json", "--schema"]
    )
    done = subprocess.run(
        [
            *GDA_CMD,
            "resource",
            "reimport",
            "res://model.glb",
            *updates,
            "--project",
            str(project),
            "--godot",
            str(tmp_path / "must-not-launch"),
            *(["--json"] if json_output else []),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 2, done.stdout + done.stderr
    if json_output:
        assert done.stderr == ""
        error = json.loads(done.stdout)["error"]
        assert error["category"] == "usage"
        assert error["code"] == "invalid_argument"
        message = error["message"]
    else:
        assert done.stdout == ""
        message = panel_text(done.stderr)
    assert "updates-json must be a JSON object" in message
    assert list(project.iterdir()) == [config]
    assert config.read_text(encoding="utf-8") == "config_version=5\n"


@pytest.mark.parametrize("token", ["--schema", "--params-json"])
def test_control_looking_values_do_not_relax_required_arguments(token):
    done = subprocess.run(
        [*GDA_CMD, "resource", "reimport", "--updates-json", token, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 2, done.stdout + done.stderr
    assert done.stderr == ""
    error = json.loads(done.stdout)["error"]
    assert error["code"] == "invalid_argument"
    assert error["message"].lower().startswith("path:")


@pytest.mark.parametrize("token", ["--schema", "--params-json"])
def test_control_looking_positionals_do_not_select_an_input_mode(token):
    done = subprocess.run(
        [*GDA_CMD, "resource", "reimport", "--json", "--", token],
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 2, done.stdout + done.stderr
    assert done.stderr == ""
    error = json.loads(done.stdout)["error"]
    assert error["code"] == "invalid_argument"
    assert error["message"].startswith("--updates-json:")


@pytest.mark.parametrize("equal_form", [False, True], ids=["space", "equals"])
@pytest.mark.parametrize("conflict", [False, True], ids=["invalid", "conflict"])
def test_schema_token_in_structured_input_retains_its_failure_contract(
    equal_form, conflict
):
    params = ["--params-json=--schema"] if equal_form else ["--params-json", "--schema"]
    done = subprocess.run(
        [
            *GDA_CMD,
            "resource",
            "reimport",
            *(["res://model.glb"] if conflict else []),
            *params,
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 4, done.stdout + done.stderr
    assert done.stderr == ""
    error = json.loads(done.stdout)["error"]
    assert error["category"] == "operation"
    assert error["code"] == ("usage_error" if conflict else "invalid_params")


def test_mode_selection_keeps_parameter_callbacks_single_and_restores_required():
    class Input(BaseModel):
        value: str

    callbacks = []
    invoked = []

    def record(value: str) -> str:
        callbacks.append(value)
        return value

    probe = typer.Typer()

    @probe.command(cls=schema_command_class(Input, Input))
    def run(
        value: str = typer.Option(..., callback=record),
        schema: bool = schema_option(),
    ) -> None:
        invoked.append(value)
        typer.echo(value)

    runner = CliRunner()
    ordinary = runner.invoke(probe, ["--value", "--schema"])
    assert ordinary.exit_code == 0, ordinary.stdout + ordinary.stderr
    assert ordinary.stdout.strip() == "--schema"
    assert invoked == ["--schema"]
    assert callbacks == ["--schema"]

    callbacks.clear()
    schema = runner.invoke(probe, ["--value", "data", "--schema"])
    assert schema.exit_code == 0, schema.stdout + schema.stderr
    assert "input" in json.loads(schema.stdout)
    assert callbacks == ["data"]
    assert invoked == ["--schema"]

    missing = runner.invoke(probe, [])
    assert missing.exit_code == 2
    assert "Missing option" in panel_text(missing.stderr)
    assert invoked == ["--schema"]
