"""Actual headless input effects through real MCP stdio in both eras (#1120)."""

import json

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import stdio_client

from tests.input_support import write_input_observer_project
from tests.mcp_support import call_tool_success, stdio_params, tool_text
from tests.support import DEFAULT_TIMEOUT, Gda


@pytest.mark.e2e
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
def test_mcp_input_observes_paused_state_and_event_routes_separately(
    tmp_path, daemon_runtime_dir, mode
):
    project = write_input_observer_project(tmp_path)
    params = stdio_params(project)

    async def drive():
        async with Client(stdio_client(params), mode=mode) as client:

            async def call(name, arguments):
                return await call_tool_success(client, name, arguments)

            async def observed():
                got = await call(
                    "game_get", {"node": "/root/Main", "property": "snapshot"}
                )
                return got["properties"][0]["value"]

            await call("daemon_start", {})
            await call("daemon_wait_ready", {})
            session = (await call("daemon_status", {}))["session_id"]
            await call(
                "game_set",
                {"node": "/root/Main", "property": "paused", "value": "true"},
            )
            baseline = await observed()
            assert baseline["paused"] is True

            pressed = await call(
                "input_action", {"action": "move_right", "strength": 0.25}
            )
            assert pressed["injection_route"] == "action_state"
            state = await observed()
            assert state["state"] is True and state["polled"] > baseline["polled"]
            assert [state[k] for k in ("input", "gui", "unhandled")] == [0, 0, 0]
            await call("input_action", {"action": "move_right", "release": True})
            released = await observed()
            assert released["state"] is False

            event = await call(
                "input_action", {"action": "move_right", "as_event": True}
            )
            assert event["injection_route"] == "viewport_event"
            await call(
                "input_action",
                {"action": "move_right", "as_event": True, "release": True},
            )
            delivered = await observed()
            assert [delivered[k] for k in ("input", "gui", "unhandled")] == [1, 1, 1]
            assert [
                delivered[k]
                for k in ("input_release", "gui_release", "unhandled_release")
            ] == [1, 1, 1]
            assert delivered["polled"] == released["polled"]

            key = await call("input_key", {"key": "X"})
            assert key["injection_route"] == "viewport_event"
            await call("input_key", {"key": "X", "released": True})
            assert (await observed())["input"] == 2
            moved = await call("input_mouse_move", {"x": 20.0, "y": 25.0})
            assert moved["injection_route"] == "viewport_event"
            assert (await observed())["at"] == [20.0, 25.0]
            click = await call("input_mouse_click", {"x": 22.0, "y": 27.0})
            assert [p["phase"] for p in click["phases"]] == ["move", "press", "release"]
            assert {p["injection_route"] for p in click["phases"]} == {"viewport_event"}
            mouse = await observed()
            assert mouse["mouse"] == ["move", "move", "press", "release"]
            assert mouse["at"] == [22.0, 27.0]

            tap = await call(
                "input_tap",
                {"action": "move_right", "hold_frames": 2, "settle_frames": 2},
            )
            assert tap["frames"] == 5
            assert tap["phases"] == [
                {"frame": 0, "phase": "press", "injection_route": "action_state"},
                {"frame": 2, "phase": "release", "injection_route": "action_state"},
            ]
            tapped = await observed()
            assert (tapped["pressed"], tapped["released"]) == (
                released["pressed"] + 1,
                released["released"] + 1,
            )
            assert tapped["input"] == 2

            sequence = await call(
                "input_sequence",
                {
                    "events": [
                        {"type": "action", "action": "move_right", "frame": 0},
                        {
                            "type": "action",
                            "action": "move_right",
                            "as_event": True,
                            "frame": 1,
                        },
                        {
                            "type": "action",
                            "action": "move_right",
                            "as_event": True,
                            "release": True,
                            "frame": 2,
                        },
                        {
                            "type": "action",
                            "action": "move_right",
                            "release": True,
                            "frame": 3,
                        },
                    ]
                },
            )
            assert sequence["frames"] == 4
            assert [p["injection_route"] for p in sequence["phases"]] == [
                "action_state",
                "viewport_event",
                "viewport_event",
                "action_state",
            ]
            final = await observed()
            assert final["state"] is False and final["polled"] > tapped["polled"]
            assert [final[k] for k in ("input", "gui", "unhandled")] == [3, 3, 3]
            assert [
                final[k] for k in ("input_release", "gui_release", "unhandled_release")
            ] == [3, 3, 3]
            assert final["ticker"] == baseline["ticker"]

            refused = await client.call_tool("input_action", {"action": "missing"})
            assert refused.is_error is True
            assert refused.structured_content is None
            error = json.loads(tool_text(refused))["error"]
            assert (error["category"], error["code"]) == ("live", "live_unknown_action")
            assert (await call("daemon_status", {}))["session_id"] == session
            assert (await call("daemon_stop", {}))["stopped"] is True

    async def bounded_drive():
        with anyio.fail_after(DEFAULT_TIMEOUT):
            await drive()

    try:
        anyio.run(bounded_drive)
    finally:
        Gda(project)("daemon", "stop")
