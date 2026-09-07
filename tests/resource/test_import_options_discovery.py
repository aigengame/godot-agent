"""Import adjustment is discoverable through the same CLI and MCP contract."""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.mcp.server import build_server
from tests.mcp_support import FakeGdaRunner, list_tools, schema_then
from tests.support import panel_text


def test_import_adjustment_schema_exposes_the_supported_patch_without_godot():
    def no_dispatch(args, stdin):
        raise AssertionError("discovery must not run an engine")

    tools = list_tools(build_server(FakeGdaRunner(schema_then(no_dispatch)))).tools
    for command in ("import-options", "reimport"):
        result = CliRunner().invoke(app, ["resource", command, "--schema"])
        assert result.exit_code == 0
        schema = json.loads(result.stdout)
        tool = next(
            t for t in tools if t.name == "resource_" + command.replace("-", "_")
        )
        assert tool.input_schema == schema["input"]
        assert tool.output_schema == schema["output"]
        if command == "reimport":
            updates = schema["input"]["$defs"]["RootScaleUpdate"]
            assert updates["additionalProperties"] is False
            scale = updates["properties"]["nodes/root_scale"]
            assert scale["type"] == "number"
            assert scale["minimum"] == 0.001
            assert scale["maximum"] == 1000.0
            assert schema["kind"] == "composite"
    help_result = CliRunner().invoke(app, ["resource", "reimport", "--help"])
    assert help_result.exit_code == 0
    assert "--updates-json" in panel_text(help_result.stdout)
