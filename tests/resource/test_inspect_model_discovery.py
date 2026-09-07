"""The imported-model inspector is discoverable without launching Godot."""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.commands.resource import (
    ResourceInspectModelParams,
    run_resource_inspect_model_operation,
)
from gda.errors import Failure
from gda.mcp.server import build_server
from tests.mcp_support import FakeGdaRunner, list_tools, schema_then
from tests.support import panel_text


def test_cli_and_mcp_expose_the_same_bounded_model_report():
    def no_dispatch(args, stdin):
        raise AssertionError("schema discovery must not launch Godot")

    result = CliRunner().invoke(app, ["resource", "inspect-model", "--schema"])
    assert result.exit_code == 0
    schema = json.loads(result.stdout)
    assert schema["input"]["properties"]["max_nodes"]["maximum"] == 4096
    assert schema["input"]["properties"]["max_items"]["maximum"] == 16384
    assert {"measurement", "nodes", "bounds", "truncated", "omissions"} <= set(
        schema["output"]["properties"]
    )
    tools = list_tools(build_server(FakeGdaRunner(schema_then(no_dispatch)))).tools
    tool = next(t for t in tools if t.name == "resource_inspect_model")
    assert tool.input_schema == schema["input"]
    assert tool.output_schema == schema["output"]
    help_result = CliRunner().invoke(app, ["resource", "inspect-model", "--help"])
    assert help_result.exit_code == 0
    text = panel_text(help_result.stdout)
    assert "--subtree" in text and "--max-items" in text
    assert "static mesh AABBs" in text


def test_returning_inspection_seam_refuses_a_non_project_asset(godot_project):
    result = run_resource_inspect_model_operation(
        godot_project, ResourceInspectModelParams(path="res://../outside.glb")
    )
    assert isinstance(result, Failure)
    assert result.error.code == "target_outside_project"
