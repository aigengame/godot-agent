"""The first Windows Engine session over real MCP stdio in both eras (#1118)."""

import json
import os
import shutil
import sys
import sysconfig

import anyio
import pytest
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from gda.core.engine.binary import GDA_GODOT_ENV
from gda.mcp.project_context import GDA_PROJECT_ENV
from gda.mcp.runner import GDA_BIN_ENV
from tests.conftest import LIVE_MAIN_TSCN, LIVE_PROJECT_GODOT
from tests.mcp_support import tool_text
from tests.support import DEFAULT_TIMEOUT, GODOT, Gda


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        sys.platform != "win32", reason="Windows owned headless session"
    ),
]


@pytest.mark.parametrize(
    ("mode", "expected_protocol"),
    [("legacy", "2025-11-25"), ("2026-07-28", "2026-07-28")],
)
def test_windows_mcp_wait_ready_reads_the_chosen_scene_then_stops(
    tmp_path, daemon_runtime_dir, mode, expected_protocol
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (project / "main.tscn").write_text(LIVE_MAIN_TSCN, encoding="utf-8")
    (project / "chosen.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="Script" path="res://chosen.gd" id="1"]\n\n'
        '[node name="Chosen" type="Node2D"]\n'
        'script = ExtResource("1")\n',
        encoding="utf-8",
    )
    (project / "chosen.gd").write_text(
        "extends Node2D\n\nfunc _ready() -> void:\n\tposition = Vector2(17, 29)\n",
        encoding="utf-8",
    )
    scripts_dir = sysconfig.get_path("scripts")
    executable = shutil.which("gda-mcp", path=scripts_dir)
    assert executable, f"`gda-mcp` console script not found in {scripts_dir}"
    env = {
        **os.environ,
        GDA_GODOT_ENV: str(GODOT),
        GDA_PROJECT_ENV: str(project),
    }
    # This gate drives this distribution's default CLI, not an ambient override.
    env.pop(GDA_BIN_ENV, None)
    params = StdioServerParameters(command=executable, args=[], env=env)

    async def drive():
        async with Client(stdio_client(params), mode=mode) as client:
            assert client.protocol_version == expected_protocol

            async def call(name, arguments):
                result = await client.call_tool(name, arguments)
                assert result.is_error is False, result.content
                assert result.structured_content is not None
                assert json.loads(tool_text(result)) == result.structured_content
                return result.structured_content

            started = await call("daemon_start", {"scene": "res://chosen.tscn"})
            assert started["installed_harness"] is True
            before = await call("daemon_status", {})
            assert before["running"] is True
            assert before["session_id"] is None

            ready = await call("daemon_wait_ready", {"timeout": 10})
            assert ready["launched"] is True
            assert ready["clean_start"] is True
            status = await call("daemon_status", {})
            session_id = status["session_id"]
            assert isinstance(session_id, str) and session_id

            tree = await call("game_tree", {})
            assert tree["root"]["name"] == "Chosen"
            assert tree["root"]["type"] == "Node2D"
            got = await call(
                "game_get", {"node": "/root/Chosen", "property": "position"}
            )
            position = next(
                item for item in got["properties"] if item["name"] == "position"
            )
            assert position["value"] == [17.0, 29.0]

            repeated = await call("daemon_wait_ready", {})
            assert repeated["launched"] is False
            status = await call("daemon_status", {})
            assert status["session_id"] == session_id
            stopped = await call("daemon_stop", {})
            assert stopped["stopped"] is True
            status = await call("daemon_status", {})
            assert status["running"] is False
            assert status["session_id"] is None

    async def bounded_drive():
        with anyio.fail_after(DEFAULT_TIMEOUT):
            await drive()

    try:
        anyio.run(bounded_drive)
    finally:
        Gda(project)("daemon", "stop")
