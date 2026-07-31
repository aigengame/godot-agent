"""S5 (fast): gda-mcp parametrized dispatch + success mapping (issue #193, ADR-0015).

A tool call forwards its input object *verbatim* to gda via
``gda <group> <command> --params-json -`` (object on stdin) and relays the
success: gda's ``--json`` dict becomes the tool's ``structured_content``, which
the SDK validates against the tool's ``output_schema`` (Design decision 5). These
drive the real surface through a fake seam (no gda subprocess, no Godot) over an
in-memory MCP client, asserting both the seam invocation and the relayed result.
"""

import json

from gda.mcp.server import build_server
from tests.mcp_support import FakeGdaRunner, call_tool, gda_result, schema_then
from tests.support import SCENE_CREATE_RESULT, VERSION_INFO


def test_scene_create_input_object_builds_params_json_dispatch():
    # The canonical S5 case: scene_create's input object → the exact gda argv +
    # the object on stdin; the canned --json result relays as structured_content.
    runner = FakeGdaRunner(
        schema_then(lambda args, stdin: gda_result(json.dumps(SCENE_CREATE_RESULT)))
    )
    server = build_server(runner)
    arguments = {"path": "/tmp/proj/main.tscn", "root_type": "Node2D"}

    result = call_tool(server, "scene_create", arguments)

    # Success relayed as structured_content, validated against the real output_schema.
    assert result.is_error is False
    assert result.structured_content == SCENE_CREATE_RESULT
    # The seam was driven with the gda command argv + verbatim object on stdin.
    dispatch_args, dispatch_stdin, _ = runner.calls[-1]
    assert dispatch_stdin is not None
    assert dispatch_args == ["scene", "create", "--params-json", "-", "--json"]
    assert json.loads(dispatch_stdin) == arguments


def test_multiword_command_name_maps_back_to_the_right_argv():
    # The MCP tool name `scene_get_exports` must dispatch to `scene get-exports`
    # (hyphen restored), proving the argv comes from the dump's own name — not a
    # lossy reverse of the underscored tool name.
    # The canned result must conform to the command's real output schema: SDK v2
    # validates structured content on every call (v1 skipped it when the tool
    # definition wasn't cached yet, so a shapeless stub used to slip through).
    runner = FakeGdaRunner(
        schema_then(
            lambda args, stdin: gda_result(json.dumps({"path": "x", "nodes": []}))
        )
    )
    server = build_server(runner)

    call_tool(server, "scene_get_exports", {"path": "res://main.tscn"})

    dispatch_args, _, _ = runner.calls[-1]
    assert dispatch_args[:2] == ["scene", "get-exports"]


def test_no_param_tool_dispatches_an_empty_params_object():
    # A no-arg tool (info) still goes through --params-json with `{}` on stdin —
    # the uniform passthrough, no special-casing of param-less commands.
    runner = FakeGdaRunner(
        schema_then(lambda args, stdin: gda_result(json.dumps(VERSION_INFO)))
    )
    server = build_server(runner)

    result = call_tool(server, "info", {})

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["string"] == VERSION_INFO["string"]
    dispatch_args, dispatch_stdin, _ = runner.calls[-1]
    assert dispatch_stdin is not None
    assert dispatch_args == ["info", "--params-json", "-", "--json"]
    assert json.loads(dispatch_stdin) == {}


def test_success_result_carries_content_block_alongside_structured_content():
    # ADR-0039: SDK v2 removed v1's auto-wrap, so gda-mcp constructs the success
    # result itself. Pin BOTH halves of the v1-identical shape: the structured
    # payload AND the indented-JSON TextContent block — many clients render
    # `content`, not `structured_content`, so dropping the block would silently
    # blank every result for them. No other test guards the hand-rolled wrap.
    runner = FakeGdaRunner(
        schema_then(lambda args, stdin: gda_result(json.dumps(SCENE_CREATE_RESULT)))
    )
    server = build_server(runner)

    result = call_tool(
        server, "scene_create", {"path": "/tmp/proj/main.tscn", "root_type": "Node2D"}
    )

    assert result.is_error is False
    assert result.structured_content == SCENE_CREATE_RESULT
    assert len(result.content) == 1
    block = result.content[0]
    assert block.type == "text"
    assert block.text == json.dumps(SCENE_CREATE_RESULT, indent=2)
