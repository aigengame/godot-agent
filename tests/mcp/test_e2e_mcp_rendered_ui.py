"""Real stdio MCP input effects on standard rendered Controls in both eras."""

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import stdio_client

from tests.mcp_support import call_tool_success, stdio_params
from tests.rendered_ui_support import (
    BUTTON_A,
    GREEN,
    OUTSIDE,
    YELLOW,
    assert_ui_pixels,
    write_rendered_ui_project,
)
from tests.support import DEFAULT_TIMEOUT, Gda

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.rendered,
    pytest.mark.usefixtures("windowed_host"),
    pytest.mark.xdist_group("windowed"),
]


@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
def test_mcp_input_changes_rendered_ui_with_disjoint_routes(
    tmp_path, daemon_runtime_dir, mode
):
    project = write_rendered_ui_project(tmp_path)

    async def drive():
        async with Client(stdio_client(stdio_params(project)), mode=mode) as client:

            async def call(name, arguments):
                return await call_tool_success(client, name, arguments)

            async def observed():
                got = await call(
                    "game_get", {"node": "/root/Main", "property": "snapshot"}
                )
                return got["properties"][0]["value"]

            async def captured(name):
                return await call(
                    "screen_capture",
                    {"output": str(project / name), "settle_frames": 2},
                )

            await call("daemon_start", {"windowed": True})
            await call("daemon_wait_ready", {})
            session = (await call("daemon_status", {}))["session_id"]
            startup = (await call("diag_errors", {}))["errors"]
            await call("input_mouse_move", {"x": OUTSIDE[0], "y": OUTSIDE[1]})
            assert (await observed())["focus"] == "/root/Main/A"
            assert_ui_pixels(await captured("before.png"), session)

            moved = await call("input_mouse_move", {"x": BUTTON_A[0], "y": BUTTON_A[1]})
            assert moved["injection_route"] == "viewport_event"
            hover = await observed()
            assert hover["mouse_at"] == [70.0, 40.0] and hover["hover_a"] is True
            assert_ui_pixels(await captured("hover.png"), session, hover=GREEN)
            clicked = await call(
                "input_mouse_click", {"x": BUTTON_A[0], "y": BUTTON_A[1]}
            )
            assert [p["phase"] for p in clicked["phases"]] == [
                "move",
                "press",
                "release",
            ]
            assert {p["injection_route"] for p in clicked["phases"]} == {
                "viewport_event"
            }
            assert (await observed())["a_pressed"] == 1
            assert_ui_pixels(
                await captured("clicked.png"), session, a=GREEN, hover=GREEN
            )
            await call("input_mouse_move", {"x": OUTSIDE[0], "y": OUTSIDE[1]})

            navigated = await call("input_tap", {"key": "Down"})
            assert navigated["focus_before"] == "/root/Main/A"
            assert navigated["focus_after"] == "/root/Main/B"
            assert (await observed())["focus"] == "/root/Main/B"
            key = await call("input_key", {"key": "Space"})
            assert key["injection_route"] == "viewport_event"
            assert (await observed())["b_pressed"] == 0
            await call("input_key", {"key": "Space", "released": True})
            assert (await observed())["b_pressed"] == 1
            assert_ui_pixels(
                await captured("key.png"), session, a=GREEN, b=GREEN, focus=GREEN
            )

            pressed = await call("input_action", {"action": "ui_accept"})
            assert pressed["injection_route"] == "action_state"
            held = await observed()
            assert held["polled"] is True and held["b_pressed"] == 1
            assert_ui_pixels(
                await captured("state.png"),
                session,
                a=GREEN,
                b=GREEN,
                focus=GREEN,
                state=YELLOW,
            )
            await call("input_action", {"action": "ui_accept", "release": True})
            released = await observed()
            assert released["polled"] is False
            tapped = await call("input_tap", {"action": "ui_accept", "as_event": True})
            assert tapped["phases"] == [
                {"frame": 0, "phase": "press", "injection_route": "viewport_event"},
                {"frame": 2, "phase": "release", "injection_route": "viewport_event"},
            ]
            assert (await observed())["b_pressed"] == 2
            assert_ui_pixels(
                await captured("action-tapped.png"), session, a=GREEN, focus=GREEN
            )
            sequence = await call(
                "input_sequence",
                {
                    "events": [
                        {
                            "type": "action",
                            "action": "ui_accept",
                            "as_event": True,
                            "frame": 0,
                        },
                        {
                            "type": "action",
                            "action": "ui_accept",
                            "as_event": True,
                            "release": True,
                            "frame": 3,
                        },
                    ]
                },
            )
            assert [p["injection_route"] for p in sequence["phases"]] == [
                "viewport_event"
            ] * 2
            final = await observed()
            assert [final[k] for k in ("b_pressed", "b_down", "b_up")] == [3, 3, 3]
            assert final["a_pressed"] == 1 and final["hover_a"] is False
            assert (
                final["polled"] is False
                and final["polled_frames"] == released["polled_frames"]
            )
            assert_ui_pixels(
                await captured("sequence.png"), session, a=GREEN, b=GREEN, focus=GREEN
            )
            assert (await call("daemon_status", {}))["session_id"] == session
            assert (await call("diag_errors", {}))["errors"] == startup
            await call("daemon_stop", {})

    async def bounded():
        with anyio.fail_after(DEFAULT_TIMEOUT):
            await drive()

    try:
        anyio.run(bounded)
    finally:
        Gda(project)("daemon", "stop")
