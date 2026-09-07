"""The existing CLI and generated MCP advertise one Vector3 contract."""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.mcp.server import build_server
from tests.mcp_support import FakeGdaRunner, list_tools, schema_then


def test_local_transform_contract_reaches_cli_schema_and_generated_mcp():
    def no_dispatch(args, stdin):
        raise AssertionError("schema discovery must not dispatch a Godot operation")

    tools = {
        tool.name: tool
        for tool in list_tools(
            build_server(FakeGdaRunner(schema_then(no_dispatch)))
        ).tools
    }
    for group in ("node", "game"):
        for action in ("get", "set"):
            result = CliRunner().invoke(app, [group, action, "--schema"])
            assert result.exit_code == 0
            schema = json.loads(result.stdout)
            text = json.dumps(schema, ensure_ascii=False)
            assert "Vector3" in text and "[x, y, z]" in text
            assert "parent space" in text and "radians" in text
            tool = tools[f"{group}_{action}"]
            assert tool.input_schema == schema["input"]
            assert tool.output_schema == schema["output"]
