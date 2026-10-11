"""Real gda-mcp startup diagnostics and Unicode stdio round trips (#1110)."""

import json
import os
import shutil
import subprocess
import sysconfig

import pytest
import anyio
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from tests.mcp_support import tool_text


@pytest.fixture
def mcp_entry():
    console = shutil.which("gda-mcp", path=sysconfig.get_path("scripts"))
    assert console, "gda-mcp console script missing from this environment"
    return console


@pytest.fixture(params=["native", "legacy"])
def entry_env(request):
    env = {**os.environ, "PYTHONUTF8": "0"}
    env.pop("PYTHONIOENCODING", None)
    if request.param == "legacy":
        env["PYTHONIOENCODING"] = "cp1252"
    return env


def test_startup_failure_reports_unicode_on_stderr(mcp_entry, entry_env, tmp_path):
    # Introspection cannot launch this override. The real entry must still
    # report the Unicode command on stderr before a server session exists.
    missing = (tmp_path / "missing_中文_😀").as_posix()
    entry_env["GDA_BIN"] = f'"{missing}"'
    proc = subprocess.run([mcp_entry], capture_output=True, env=entry_env, timeout=30)
    assert proc.returncode != 0
    assert not proc.stdout
    assert missing in proc.stderr.decode("utf-8")


@pytest.mark.e2e
def test_real_mcp_scene_mutation_roundtrips_unicode(
    mcp_entry, entry_env, godot_project
):
    scene = godot_project / "中文_😀.tscn"
    # Use the existing project env channel, not roots (whose Windows URI
    # correction belongs to #1111). Let the paired CLI choose Godot normally.
    entry_env.pop("GDA_BIN", None)
    entry_env["GDA_PROJECT"] = str(godot_project)
    params = StdioServerParameters(command=mcp_entry, args=[], env=entry_env)

    async def drive():
        async with Client(stdio_client(params), mode="legacy") as client:
            tools = await client.list_tools()
            assert "scene_create" in {tool.name for tool in tools.tools}
            created = await client.call_tool(
                "scene_create",
                {"path": str(scene), "root_type": "Node2D", "root_name": "中文_😀"},
            )
            assert created.is_error is False, created.content
            assert created.structured_content is not None
            assert created.structured_content["root_name"] == "中文_😀"
            assert json.loads(tool_text(created))["root_name"] == "中文_😀"

            got = await client.call_tool("scene_get", {"path": str(scene)})
            assert got.is_error is False, got.content
            assert got.structured_content is not None
            assert got.structured_content["root"]["name"] == "中文_😀"

    anyio.run(drive)
    assert 'name="中文_😀"' in scene.read_text(encoding="utf-8")
