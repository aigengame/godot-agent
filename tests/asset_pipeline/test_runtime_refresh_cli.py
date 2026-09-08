"""One optional workflow request across argv, structured input and discovery."""

import json
from pathlib import Path

from typer.testing import CliRunner

from gda.cli import app
from gda.mcp.server import build_server
from gda_assets.api import PipelineResult, RefreshResult
from tests.mcp_support import (
    FakeGdaRunner,
    call_tool,
    gda_result,
    list_tools,
    schema_then,
)
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
    refresh_result = schema["output"]["$defs"]["RefreshResult"]["properties"]
    for field, definition, properties in (
        ("stop", "StopObservation", {"stopped", "pid"}),
        (
            "start",
            "StartObservation",
            {
                "installed_harness",
                "harness_synced",
                "harness_version",
                "created_paths",
                "created_sections",
                "pid",
                "windowed",
                "already_running",
            },
        ),
        ("ready", "ReadyObservation", {"pid", "launched"}),
    ):
        assert refresh_result[field]["anyOf"][0]["$ref"].endswith(definition)
        assert set(schema["output"]["$defs"][definition]["properties"]) == properties
    tools = list_tools(
        build_server(FakeGdaRunner(schema_then(lambda *_: gda_result())))
    ).tools
    tool = next(item for item in tools if item.name == "asset_pipeline_run")
    assert tool.output_schema == schema["output"]


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


def test_mcp_relays_concrete_lifecycle_facts_in_refresh_result():
    request = {
        "path": "res://model.glb",
        "scene": "res://preview.tscn",
        "node": "/root/Preview/Model",
    }
    lifecycle = {
        "stop": {"stopped": True, "pid": 40},
        "start": {
            "installed_harness": True,
            "harness_synced": True,
            "harness_version": "1",
            "created_paths": ["res://.gda/live.gd"],
            "created_sections": ["autoload"],
            "pid": 41,
            "windowed": False,
            "already_running": False,
        },
        "ready": {"pid": 41, "launched": True},
    }
    payload = {
        "project_root": "/tmp/project",
        "pipeline": {
            "completed": [],
            "outputs": [],
            "observations": [],
            "refresh": {"request": request, **lifecycle},
        },
    }
    runner = FakeGdaRunner(
        schema_then(lambda *_: gda_result(stdout=json.dumps(payload)))
    )

    result = call_tool(
        build_server(runner),
        "asset_pipeline_run",
        {
            "files": [{"source": "/tmp/model.glb", "target": "res://model.glb"}],
            "refresh": request,
        },
    )

    assert result.is_error is False
    assert result.structured_content is not None
    assert (
        result.structured_content["pipeline"]["refresh"] | lifecycle
        == result.structured_content["pipeline"]["refresh"]
    )
