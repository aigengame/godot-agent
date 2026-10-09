"""All six headless game routes through real MCP stdio in both eras (#1119)."""

import json

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import stdio_client

from tests.game_support import write_game_state_project
from tests.mcp_support import call_tool_success, stdio_params, tool_text
from tests.support import DEFAULT_TIMEOUT, Gda


@pytest.mark.e2e
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
def test_mcp_game_state_reads_writes_layout_and_typed_refusals(
    tmp_path, daemon_runtime_dir, mode
):
    project = write_game_state_project(tmp_path)
    params = stdio_params(project)

    async def drive():
        async with Client(stdio_client(params), mode=mode) as client:

            async def call(name, arguments):
                return await call_tool_success(client, name, arguments)

            await call("daemon_start", {})
            await call("daemon_wait_ready", {})
            session = (await call("daemon_status", {}))["session_id"]
            tree = await call("game_tree", {"max_depth": 1})
            assert tree["root"]["name"] == "Main"
            assert tree["root"]["children"][0]["name"] == "Panel"
            found = await call("game_find", {"type": "Control"})
            assert found["count"] == 1
            assert found["matches"][0]["path"] == "/root/Main/Panel"

            changed = await call(
                "game_set", {"node": "/root/Main", "property": "count", "value": "41"}
            )
            assert (changed["value"], changed["verified"]) == (41, True)
            got = await call("game_get", {"node": "/root/Main", "property": "count"})
            assert got["properties"][0]["value"] == 41
            state = await call("game_call", {"node": "/root/Main", "method": "state"})
            assert state["value"]["count"] == 41
            assert state["value"]["payload"] == {"items": [1, 1.25], "at": [5.0, 7.0]}
            for value in (3.141592653589793, 1e17):
                echoed = await call(
                    "game_call",
                    {"node": "/root/Main", "method": "echo_float", "args": [value]},
                )
                assert echoed["value"] == value

            rect = await call("game_rect", {"node": "/root/Main/Panel"})
            assert rect["position"] == [20.0, 30.0]
            assert rect["size"] == [100.0, 50.0]
            assert rect["combined_minimum_size"] == [40.0, 25.0]
            for name, arguments, code in (
                ("game_rect", {"node": "/root/Main"}, "live_not_control"),
                (
                    "game_call",
                    {"node": "/root/Main", "method": "secret"},
                    "live_method_not_allowlisted",
                ),
            ):
                refused = await client.call_tool(name, arguments)
                assert refused.is_error is True, refused.content
                assert refused.structured_content is None
                error = json.loads(tool_text(refused))["error"]
                assert (error["category"], error["code"]) == ("live", code)
            assert (await call("daemon_status", {}))["session_id"] == session
            assert (await call("daemon_stop", {}))["stopped"] is True

    async def bounded_drive():
        with anyio.fail_after(DEFAULT_TIMEOUT):
            await drive()

    try:
        anyio.run(bounded_drive)
    finally:
        Gda(project)("daemon", "stop")
