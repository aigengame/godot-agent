"""S5 (fast): gda-mcp parametrized dispatch + success mapping (issue #193, ADR-0015).

A tool call forwards its input object *verbatim* to gda via
``gda <group> <command> --params-json -`` (object on stdin) and relays the
success: gda's ``--json`` dict becomes the tool's ``structuredContent``, which
the SDK validates against the tool's ``outputSchema`` (Design decision 5). These
drive the real surface through a fake seam (no gda subprocess, no Godot) over an
in-memory MCP client, asserting both the seam invocation and the relayed result.
"""

import json

from gda.mcp.server import build_server
from tests.mcp_support import FakeGdaRunner, call_tool, gda_result, schema_then
from tests.support import SCENE_CREATE_RESULT, VERSION_INFO


def test_scene_create_input_object_builds_params_json_dispatch():
    # The canonical S5 case: scene_create's input object → the exact gda argv +
    # the object on stdin; the canned --json result relays as structuredContent.
    runner = FakeGdaRunner(
        schema_then(lambda args, stdin: gda_result(json.dumps(SCENE_CREATE_RESULT)))
    )
    server = build_server(runner)
    arguments = {"path": "/tmp/proj/main.tscn", "root_type": "Node2D"}

    result = call_tool(server, "scene_create", arguments)

    # Success relayed as structuredContent, validated against the real outputSchema.
    assert result.isError is False
    assert result.structuredContent == SCENE_CREATE_RESULT
    # The seam was driven with the gda command argv + verbatim object on stdin.
    dispatch_args, dispatch_stdin = runner.calls[-1]
    assert dispatch_args == ["scene", "create", "--params-json", "-", "--json"]
    assert json.loads(dispatch_stdin) == arguments


def test_multiword_command_name_maps_back_to_the_right_argv():
    # The MCP tool name `scene_get_exports` must dispatch to `scene get-exports`
    # (hyphen restored), proving the argv comes from the dump's own name — not a
    # lossy reverse of the underscored tool name.
    runner = FakeGdaRunner(
        schema_then(lambda args, stdin: gda_result(json.dumps({"path": "x", "exports": []})))
    )
    server = build_server(runner)

    call_tool(server, "scene_get_exports", {"path": "res://main.tscn"})

    dispatch_args, _ = runner.calls[-1]
    assert dispatch_args[:2] == ["scene", "get-exports"]


def test_no_param_tool_dispatches_an_empty_params_object():
    # A no-arg tool (info) still goes through --params-json with `{}` on stdin —
    # the uniform passthrough, no special-casing of param-less commands.
    runner = FakeGdaRunner(
        schema_then(lambda args, stdin: gda_result(json.dumps(VERSION_INFO)))
    )
    server = build_server(runner)

    result = call_tool(server, "info", {})

    assert result.isError is False
    assert result.structuredContent["string"] == VERSION_INFO["string"]
    dispatch_args, dispatch_stdin = runner.calls[-1]
    assert dispatch_args == ["info", "--params-json", "-", "--json"]
    assert json.loads(dispatch_stdin) == {}
