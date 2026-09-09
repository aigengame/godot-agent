"""Producer-owned validation reaches gda without initializing native tools."""

import json
import subprocess

import pytest
from typer.testing import CliRunner

from gda.cli import app
from tests.support import assert_no_pydantic_dump


@pytest.mark.parametrize("scale", [0, -1, True, "2", float("inf"), float("nan")])
def test_invalid_blender_scale_is_an_input_error_before_native_execution(
    godot_project,
    monkeypatch,
    scale,
):
    def no_process(*args, **kwargs):
        raise AssertionError("invalid producer input must not launch a process")

    monkeypatch.setattr("subprocess.run", no_process)
    production = {
        "kind": "blender_saved",
        "outputs": [{"role": "model", "target": "res://asset.glb"}],
        "options": {
            "source": "absent.blend",
            "scene": "Scene",
            "root": "Root",
            "uniform_scale": scale,
        },
    }
    result = CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--production",
            json.dumps(production),
            "--project",
            str(godot_project),
            "--json",
        ],
    )
    assert result.exit_code == 4, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "invalid_params"
    assert_no_pydantic_dump(error["message"])
    assert error["partial_result"]["outputs"] == []


def test_producer_timeout_preserves_bounded_diagnostics_and_cleans_workspace(
    godot_project, monkeypatch
):
    source = godot_project / "source.blend"
    source.write_bytes(b"saved source")

    def timeout(argv, **kwargs):
        kwargs["stderr"].write(b"x" * 20000 + b"last Blender diagnostic")
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr("gda_assets.adapters.blender.subprocess.run", timeout)
    production = {
        "kind": "blender_saved",
        "outputs": [{"role": "model", "target": "res://asset.glb"}],
        "options": {
            "source": str(source),
            "scene": "Scene",
            "root": "Root",
            "executable": "blender-test",
            "timeout_seconds": 0.1,
        },
    }
    result = CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--production",
            json.dumps(production),
            "--project",
            str(godot_project),
            "--json",
        ],
    )
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "launch_timeout"
    assert "0.1s" in error["message"]
    partial = error["partial_result"]
    tail = partial["failure"]["cause"]["stderr_tail"]
    assert len(tail) == 16384 and tail.endswith("last Blender diagnostic")
    assert partial["cleanup"]["workspace_removed"] is True
    assert partial["outputs"] == []
    assert source.read_bytes() == b"saved source"
    assert not (godot_project / "asset.glb").exists()


def test_missing_blender_has_an_actionable_environment_failure(godot_project):
    source = godot_project / "source.blend"
    source.write_bytes(b"saved source placeholder; engine will not be started")
    production = {
        "kind": "blender_saved",
        "outputs": [{"role": "model", "target": "res://asset.glb"}],
        "options": {
            "source": str(source),
            "scene": "Scene",
            "root": "Root",
            "executable": str(godot_project / "missing-blender"),
        },
    }
    result = CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--production",
            json.dumps(production),
            "--project",
            str(godot_project),
            "--json",
        ],
    )
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "binary_not_found"
    assert "Blender" in error["message"]
    assert error["partial_result"]["cleanup"]["workspace_removed"] is True
    assert error["partial_result"]["outputs"] == []


@pytest.mark.parametrize(
    ("worker_result", "export_bytes", "returncode", "message"),
    [
        ([], None, 0, "production result"),
        ({}, b"not GLB", 0, "production result"),
        ({"completed": ["inspect", "prepare", "export"]}, None, 0, "output is missing"),
        ({"completed": ["inspect", "prepare", "export"]}, b"not GLB", 0, "GLB"),
        ({"stage": "export", "failure": "exporter failed"}, None, 1, "exporter failed"),
    ],
)
def test_failed_or_incomplete_worker_never_installs(
    godot_project,
    monkeypatch,
    worker_result,
    export_bytes,
    returncode,
    message,
):
    from pathlib import Path

    source = godot_project / "source.blend"
    source.write_bytes(b"saved source")

    def worker(argv, **kwargs):
        request = json.loads(Path(argv[-1]).read_text())
        Path(request["result"]).write_text(json.dumps(worker_result))
        if export_bytes is not None:
            Path(request["output"]).write_bytes(export_bytes)
        return subprocess.CompletedProcess(argv, returncode)

    monkeypatch.setattr("gda_assets.adapters.blender.subprocess.run", worker)
    production = {
        "kind": "blender_saved",
        "outputs": [{"role": "model", "target": "res://asset.glb"}],
        "options": {
            "source": str(source),
            "scene": "Scene",
            "root": "Root",
            "executable": "blender-test",
        },
    }
    result = CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--production",
            json.dumps(production),
            "--project",
            str(godot_project),
            "--json",
        ],
    )
    assert result.exit_code == 4, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert message in error["message"]
    partial = error["partial_result"]
    assert partial["outputs"] == []
    assert partial["cleanup"]["workspace_removed"] is True
    assert not (godot_project / "asset.glb").exists()
    assert source.read_bytes() == b"saved source"


def test_relative_production_source_requires_explicit_base(godot_project, monkeypatch):
    (godot_project / "source.blend").write_bytes(b"saved source")

    def no_process(*args, **kwargs):
        raise AssertionError("relative source without base must fail before process")

    monkeypatch.setattr("gda_assets.adapters.blender.subprocess.run", no_process)
    production = {
        "kind": "blender_saved",
        "outputs": [{"role": "model", "target": "res://asset.glb"}],
        "options": {
            "source": "source.blend",
            "scene": "Scene",
            "root": "Root",
            "executable": "blender-test",
        },
    }
    result = CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--production",
            json.dumps(production),
            "--project",
            str(godot_project),
            "--json",
        ],
    )
    assert result.exit_code == 4, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "invalid_params"
    assert "source_root" in error["message"]
