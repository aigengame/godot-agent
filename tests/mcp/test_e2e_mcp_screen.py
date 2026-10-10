"""Real stdio MCP windowed screen capture in both protocol eras."""

import base64
from pathlib import Path

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import stdio_client

from tests.mcp_support import call_tool_success, stdio_params
from tests.screen_support import (
    assert_capture_receipt,
    assert_screen_pixels,
    write_screen_project,
)
from tests.support import DEFAULT_TIMEOUT, Gda

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.rendered,
    pytest.mark.usefixtures("windowed_host"),
    pytest.mark.xdist_group("windowed"),
]


@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
def test_mcp_screen_returns_rendered_pixels_and_the_current_session(
    tmp_path, daemon_runtime_dir, mode
):
    project = write_screen_project(tmp_path)

    async def drive():
        async with Client(stdio_client(stdio_params(project)), mode=mode) as client:

            async def call(name, args):
                return await call_tool_success(client, name, args)

            started = await call("daemon_start", {"windowed": True})
            assert started["windowed"] is True
            await call("daemon_wait_ready", {})
            before = await call("daemon_status", {})
            capture = await call(
                "screen_capture",
                {
                    "output": str(project / "屏幕.png"),
                    "inline": True,
                    "settle_frames": 2,
                },
            )
            assert_screen_pixels(capture)
            assert_capture_receipt(capture, before["session_id"])
            assert (
                base64.b64decode(capture["inline"])
                == Path(capture["path"]).read_bytes()
            )
            frames = await call(
                "screen_frames",
                {
                    "frames": 3,
                    "output_dir": str(project / "连续帧"),
                    "settle_frames": 2,
                },
            )
            assert frames["count"] == 3 and frames["settle_frames"] == 2
            assert len({f["path"] for f in frames["frames"]}) == 3
            for frame in frames["frames"]:
                assert_screen_pixels(frame)
                assert_capture_receipt(frame, before["session_id"])
            again = await call("screen_capture", {"output": str(project / "after.png")})
            assert_capture_receipt(again, before["session_id"])
            assert again["receipt"]["render_frame"] > capture["receipt"]["render_frame"]
            assert (await call("daemon_status", {}))["session_id"] == before[
                "session_id"
            ]
            await call("daemon_stop", {})

    async def bounded():
        with anyio.fail_after(DEFAULT_TIMEOUT):
            await drive()

    try:
        anyio.run(bounded)
    finally:
        Gda(project)("daemon", "stop")
