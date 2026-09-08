"""One optional workflow request across argv, structured input and discovery."""

import json
from pathlib import Path

from typer.testing import CliRunner

from gda.cli import app
from gda_assets.api import PipelineResult, RefreshResult
from tests.support import minimal_project


def test_refresh_request_has_one_binding_and_typed_optional_result():
    result = CliRunner().invoke(app, ["asset-pipeline", "run", "--schema"])
    assert result.exit_code == 0, result.output
    schema = json.loads(result.stdout)
    binding = next(
        item for item in schema["argv"] if item["input_property"] == "refresh"
    )
    assert binding["option"] == "--refresh"
    assert binding["json_value"] is True
    assert schema["input"]["properties"]["refresh"]["default"] is None
    assert "RefreshResult" in schema["output"]["$defs"]


def test_refresh_argv_and_structured_input_use_same_injected_runtime(
    monkeypatch, tmp_path
):
    project = minimal_project(tmp_path / "project")
    calls = []

    def run(recipe, **kwargs):
        assert kwargs["runtime"] is kwargs["godot"]
        assert kwargs["collection"] is None
        calls.append(kwargs["refresh"])
        return PipelineResult(refresh=RefreshResult(kwargs["refresh"]))

    monkeypatch.setattr("gda.commands.asset_pipeline.run_pipeline", run)
    files = [{"source": str(tmp_path / "model.glb"), "target": "res://model.glb"}]
    refresh = {
        "path": "res://model.glb",
        "scene": "res://test.tscn",
        "node": "/root/Test/Model",
        "windowed": True,
        "capture_output": str(tmp_path / "view.png"),
    }
    results = []
    for args in (
        ["--files", json.dumps(files), "--refresh", json.dumps(refresh)],
        ["--params-json", json.dumps({"files": files, "refresh": refresh})],
    ):
        result = CliRunner().invoke(
            app, ["asset-pipeline", "run", *args, "--project", str(project), "--json"]
        )
        assert result.exit_code == 0, result.output
        results.append(json.loads(result.stdout))
    assert calls[0] == calls[1]
    assert calls[0].capture_output == Path(refresh["capture_output"])
    assert results[0] == results[1]
