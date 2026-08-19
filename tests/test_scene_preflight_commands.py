"""S3: ``gda scene preflight`` through the full CLI pipeline against a fake launch (#664).

The dynamic half of #664 (dogfooding GDA-DF-030). Unlike the rest of the ``scene``
group it does not go through ``cmd.emit``: it needs the STREAMING capture (#655), so
that a run gda has to END still carries what the engine printed before it stopped —
which is the whole evidence of a scene that never came up. The engine-touching step
is therefore :func:`gda.runner.launch`, replaced here with a canned
:class:`~gda.runner.RunResult` (patched at ``gda.commands.scene.launch``), so the
full Typer → recipe → classify → JSON pipeline runs engine-free.

What these pin is the verdict projection, which is where this command's contract
lives: the engine reports how far the boot got, gda reads the script errors off
stderr with #651's parser, and ``started`` is true only when BOTH agree.
"""

import json

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.runner import LaunchFailure, RunResult
from tests.support import sentinel

READY = sentinel({"path": "res://main.tscn", "status": "ready"})

# The engine's own error stream for a scene that reached _ready and raised inside it
# — the GDA-DF-030 shape (an application invariant rejecting the assembly).
READY_STDERR = (
    "gda: running operation: scene-preflight\n"
    "SCRIPT ERROR: Assertion failed: no spawn point in the encounter\n"
    "          at: _ready (res://encounter.gd:12)\n"
)


def _patch_launch(monkeypatch, result: RunResult) -> list:
    calls: list = []

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        calls.append((binary, args, cwd, timeout, timeout_label, watch))
        return result

    monkeypatch.setattr("gda.commands.scene.launch", fake_launch)
    return calls


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


def test_a_clean_start_is_ready_and_started(monkeypatch, tmp_path):
    project = _project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout=READY, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        ["scene", "preflight", "res://main.tscn", "--project", str(project), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "path": "res://main.tscn",
        "started": True,
        "status": "ready",
        "diagnostics": [],
        "project_root": str(project.resolve()),
    }
    # The sentinel op was dispatched through the shared argv spelling, under the
    # resolved project, with a watch (which is what selects the streaming capture).
    (_binary, args, cwd, timeout, _label, watch) = calls[0]
    assert args[:2] == ["--path", str(project)]
    assert args[2] == "--script"
    assert args[4:6] == ["--", "scene-preflight"]
    assert json.loads(args[6])["path"] == "res://main.tscn"
    assert cwd is None
    assert timeout == pytest.approx(30.0)
    assert watch is not None


def test_a_script_error_during_startup_is_reported_though_the_scene_reached_ready(
    monkeypatch, tmp_path
):
    # THE DISTINCTION the issue asks for: "compiles and loads" is not "reaches _ready
    # without script errors". The engine says ready; the stderr says otherwise, so
    # `started` is false while `status` still reports how far the boot got.
    project = _project(tmp_path)
    _patch_launch(
        monkeypatch, RunResult(stdout=READY, stderr=READY_STDERR, exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        ["scene", "preflight", "res://main.tscn", "--project", str(project), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "ready"
    assert data["started"] is False
    # Read with #651's parser, so a startup error is classified and located rather
    # than left as prose.
    assert data["diagnostics"] == [
        {
            "kind": "runtime_error",
            "message": "Assertion failed: no spawn point in the encounter",
            "path": "res://encounter.gd",
            "line": 12,
        }
    ]


def test_a_run_gda_ends_at_the_bound_is_a_timeout_verdict_not_an_envelope(
    monkeypatch, tmp_path
):
    # A scene whose _ready never returns blocks the engine before it can report
    # anything, so the bound is gda's. The answer is still the verdict the caller
    # asked for — "it did not start" — carrying what the engine had already printed,
    # which the streaming capture is what preserves.
    project = _project(tmp_path)
    _patch_launch(
        monkeypatch,
        RunResult(
            stdout="",
            stderr=READY_STDERR,
            exit_code=124,
            launch_failure=LaunchFailure.TIMEOUT,
            elapsed_seconds=5.0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "scene",
            "preflight",
            "res://main.tscn",
            "--project",
            str(project),
            "--timeout",
            "5",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "timeout"
    assert data["started"] is False
    assert data["path"] == "res://main.tscn"
    assert data["diagnostics"][0]["path"] == "res://encounter.gd"


def test_a_missing_binary_is_still_an_error_envelope(monkeypatch, tmp_path):
    # Only the SCENE's fate is a verdict. An environment failure is not about the
    # scene at all, so it stays the shared envelope every channel reports.
    project = _project(tmp_path)
    _patch_launch(
        monkeypatch,
        RunResult(
            stdout="",
            stderr="gda: Godot binary could not be launched\n",
            exit_code=127,
            launch_failure=LaunchFailure.NOT_FOUND,
        ),
    )

    result = CliRunner().invoke(
        app,
        ["scene", "preflight", "res://main.tscn", "--project", str(project), "--json"],
    )

    assert result.exit_code == 127, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "binary_not_found"


def test_an_operation_refusal_survives_the_recipe(monkeypatch, tmp_path):
    # The op's own structured refusals still classify normally: a scene that cannot
    # be instantiated at all is a dependency failure, not a startup verdict.
    project = _project(tmp_path)
    payload = sentinel(
        {
            "error": {
                "code": "missing_dependency",
                "message": "scene failed to instantiate: res://main.tscn",
            }
        }
    )
    _patch_launch(monkeypatch, RunResult(stdout=payload, stderr="", exit_code=1))

    result = CliRunner().invoke(
        app,
        ["scene", "preflight", "res://main.tscn", "--project", str(project), "--json"],
    )

    assert result.exit_code == 4, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "missing_dependency"


def test_frames_and_timeout_reach_the_launch_through_params_json(monkeypatch, tmp_path):
    project = _project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout=READY, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "scene",
            "preflight",
            "--params-json",
            json.dumps({"path": "res://main.tscn", "frames": 42, "timeout": 7.5}),
            "--project",
            str(project),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    (_binary, args, _cwd, timeout, _label, _watch) = calls[0]
    assert json.loads(args[6])["frames"] == 42
    assert timeout == pytest.approx(7.5)


@pytest.mark.parametrize("frames", ["0", "-1"])
def test_a_non_positive_frame_budget_is_a_usage_error(monkeypatch, tmp_path, frames):
    project = _project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout=READY, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "scene",
            "preflight",
            "res://main.tscn",
            "--frames",
            frames,
            "--project",
            str(project),
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert calls == []


def test_a_non_positive_timeout_is_a_usage_error(monkeypatch, tmp_path):
    project = _project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout=READY, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "scene",
            "preflight",
            "res://main.tscn",
            "--timeout",
            "0",
            "--project",
            str(project),
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert calls == []


def test_human_output_leads_with_the_verdict(monkeypatch, tmp_path):
    project = _project(tmp_path)
    _patch_launch(
        monkeypatch, RunResult(stdout=READY, stderr=READY_STDERR, exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["scene", "preflight", "res://main.tscn", "--project", str(project)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "ready with errors res://main.tscn"
    assert lines[1] == f"  project: {project.resolve()}"
    assert (
        lines[2]
        == "  runtime_error: res://encounter.gd:12: Assertion failed: no spawn "
        "point in the encounter"
    )
