"""Structured argv validation failures (issue #947).

These tests exercise the public Typer application.  The command bodies still use
their shared Pydantic input models; only the rendering of a rejected argv request
changes when the caller explicitly asks for JSON.
"""

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from gda.cli import app
from gda.commands.resource import ResourceReimportResult
from gda.exit_codes import EXIT_USAGE
from tests.support import GDA_CMD, minimal_project, panel_text


def test_reimport_wrong_update_type_is_a_structured_usage_failure(monkeypatch):
    """A model refusal is answered before the reimport recipe can run."""

    def no_reimport(*args, **kwargs):
        raise AssertionError("invalid argv must not reach the reimport recipe")

    monkeypatch.setattr(
        "gda.commands.resource.run_resource_reimport_operation", no_reimport
    )

    secret = "SECRET_ARGV_VALUE_947"
    result = CliRunner().invoke(
        app,
        [
            "resource",
            "reimport",
            "res://model.glb",
            "--updates-json",
            json.dumps({"nodes/root_scale": secret}),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_USAGE, result.stdout + result.stderr
    assert result.stderr == ""
    error = json.loads(result.stdout)["error"]
    assert error == {
        "category": "usage",
        "code": "invalid_argument",
        "message": "updates.nodes/root_scale: Input should be a valid number",
        "diagnostics": "",
    }
    assert secret not in result.stdout


def test_reimport_malformed_updates_json_is_a_structured_usage_failure(monkeypatch):
    def no_reimport(*args, **kwargs):
        raise AssertionError("malformed argv must not reach the reimport recipe")

    monkeypatch.setattr(
        "gda.commands.resource.run_resource_reimport_operation", no_reimport
    )

    result = CliRunner().invoke(
        app,
        [
            "resource",
            "reimport",
            "res://model.glb",
            "--updates-json",
            '{"nodes/root_scale":',
            "--json",
        ],
    )

    assert result.exit_code == EXIT_USAGE, result.stdout + result.stderr
    assert result.stderr == ""
    error = json.loads(result.stdout)["error"]
    assert error == {
        "category": "usage",
        "code": "invalid_argument",
        "message": "updates-json must be a JSON object",
        "diagnostics": "",
    }


def test_click_type_error_is_structured_without_echoing_the_raw_value():
    secret = "SECRET_MAX_DEPTH_947"

    result = CliRunner().invoke(
        app,
        ["game", "tree", "--max-depth", secret, "--json"],
    )

    assert result.exit_code == EXIT_USAGE, result.stdout + result.stderr
    assert result.stderr == ""
    error = json.loads(result.stdout)["error"]
    assert error == {
        "category": "usage",
        "code": "invalid_argument",
        "message": "--max-depth: does not satisfy its declared argv contract",
        "diagnostics": "",
    }
    assert secret not in result.stdout


def test_reimport_unknown_update_key_is_a_structured_usage_failure(monkeypatch):
    def no_reimport(*args, **kwargs):
        raise AssertionError("unknown argv key must not reach the reimport recipe")

    monkeypatch.setattr(
        "gda.commands.resource.run_resource_reimport_operation", no_reimport
    )

    result = CliRunner().invoke(
        app,
        [
            "resource",
            "reimport",
            "res://model.glb",
            "--updates-json",
            json.dumps({"meshes/generate_lods": False}),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_USAGE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["category"] == "usage"
    assert error["code"] == "invalid_argument"
    assert (
        "updates.meshes/generate_lods: Extra inputs are not permitted"
        in error["message"]
    )


def test_equivalent_params_json_failure_retains_invalid_params_exit_four(monkeypatch):
    def no_reimport(*args, **kwargs):
        raise AssertionError("invalid params must not reach the reimport recipe")

    monkeypatch.setattr(
        "gda.commands.resource.run_resource_reimport_operation", no_reimport
    )

    secret = "SECRET_PARAMS_VALUE_947"
    result = CliRunner().invoke(
        app,
        [
            "resource",
            "reimport",
            "--params-json",
            json.dumps(
                {
                    "path": "res://model.glb",
                    "updates": {"nodes/root_scale": secret},
                }
            ),
            "--json",
        ],
    )

    assert result.exit_code == 4, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["category"] == "operation"
    assert error["code"] == "invalid_params"
    assert error["message"].startswith("--params-json is not a valid params object: ")
    assert secret not in result.stdout


def test_human_argv_failure_keeps_clicks_readable_stderr():
    result = CliRunner().invoke(
        app,
        [
            "resource",
            "reimport",
            "res://model.glb",
            "--updates-json",
            "{broken",
        ],
    )

    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert "updates-json must be a JSON object" in panel_text(result.stderr)


def _snapshot_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_real_cli_argv_failure_does_not_launch_godot_or_mutate_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (project / "model.glb").write_bytes(b"unchanged model bytes")
    absent_godot = tmp_path / "godot-must-not-be-resolved-or-launched"
    assert not absent_godot.exists()
    before = _snapshot_files(project)

    done = subprocess.run(
        [
            *GDA_CMD,
            "resource",
            "reimport",
            "res://model.glb",
            "--updates-json",
            json.dumps({"nodes/root_scale": "wrong"}),
            "--project",
            str(project),
            "--godot",
            str(absent_godot),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == EXIT_USAGE, done.stdout + done.stderr
    assert json.loads(done.stdout)["error"]["code"] == "invalid_argument"
    assert done.stderr == ""
    # Reaching binary resolution would change this to binary_not_found/exit 127.
    assert not absent_godot.exists()
    assert _snapshot_files(project) == before


def test_invalid_argv_honors_each_json_flag_position():
    core = ["game", "tree", "--max-depth", "wrong"]
    spellings = (
        ["--json", *core],
        ["game", "--json", "tree", "--max-depth", "wrong"],
        [*core, "--json"],
    )

    outcomes = [CliRunner().invoke(app, argv) for argv in spellings]

    assert all(result.exit_code == EXIT_USAGE for result in outcomes)
    assert all(result.stderr == "" for result in outcomes)
    assert len({result.stdout for result in outcomes}) == 1
    assert json.loads(outcomes[0].stdout)["error"]["code"] == "invalid_argument"


def test_valid_reimport_argv_still_reaches_the_shared_model_and_recipe(
    monkeypatch, tmp_path
):
    project = minimal_project(tmp_path)
    received = []

    def checked(params_project, params, *, godot=None):
        received.append((params_project, params, godot))
        return ResourceReimportResult(
            path=params.path,
            dry_run=True,
            status="checked",
            changes=[],
        )

    monkeypatch.setattr(
        "gda.commands.resource.run_resource_reimport_operation", checked
    )

    result = CliRunner().invoke(
        app,
        [
            "resource",
            "reimport",
            "res://model.glb",
            "--updates-json",
            json.dumps({"nodes/root_scale": 2.0}),
            "--dry-run",
            "--project",
            str(project),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "checked"
    assert len(received) == 1
    called_project, params, called_godot = received[0]
    assert called_project == project
    assert params.updates.root_scale == 2.0
    assert params.dry_run is True
    assert called_godot is None


def test_real_cli_other_command_accepts_valid_and_structures_invalid_argv():
    valid = subprocess.run(
        [*GDA_CMD, "skill", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    invalid = subprocess.run(
        [*GDA_CMD, "skill", "--install", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert json.loads(valid.stdout)["name"] == "gda"
    assert invalid.returncode == EXIT_USAGE, invalid.stdout + invalid.stderr
    error = json.loads(invalid.stdout)["error"]
    assert error["category"] == "usage"
    assert error["code"] == "invalid_argument"
    assert "--install" in error["message"]
    assert invalid.stderr == ""
