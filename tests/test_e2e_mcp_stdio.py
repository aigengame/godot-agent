"""S6 (e2e): the non-negotiable gda-mcp stdio gate (issue #193, ADR-0013).

The real chain over the wire it ships on: a real MCP client → the real
``gda-mcp`` **console script** over **stdio** → the real ``gda`` subprocess → a
real Godot engine. This is what validates ADR-0013 packaging + launch (the
console script actually starts and speaks MCP), so the fake seam does NOT count
toward this gate (RULES.md DoD). Representative tools: ``info`` (reports the
engine version — #199-independent) and ``scene_create`` (creates a scene file on
disk — exercises the ADR-0015 ``--params-json`` dispatch).

Godot is pinned via ``$GDA_GODOT`` in the *server's* env — the same vector a real
MCP registration uses — since gda-mcp resolves Godot by gda's own precedence and
never hardcodes it (Design decision 1).
"""

import os
import shutil

import anyio
import pytest
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

from gda.binary import GODOT_BIN_ENV, resolve_godot_binary

GODOT = resolve_godot_binary()


def _server_params() -> StdioServerParameters:
    gda_mcp = shutil.which("gda-mcp")
    assert gda_mcp, "the `gda-mcp` console script is not on PATH"
    # Full env + a pinned Godot, so the server's nested `-m gda` resolves the
    # same engine deterministically.
    env = {**os.environ, GODOT_BIN_ENV: str(GODOT)}
    return StdioServerParameters(command=gda_mcp, args=[], env=env)


def _call(tool: str, arguments: dict):
    """Spawn the real gda-mcp over stdio, call one tool, return its result."""

    async def _drive():
        async with stdio_client(_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool, arguments)

    return anyio.run(_drive)


@pytest.mark.e2e
def test_info_over_stdio_reports_engine_version():
    result = _call("info", {})

    assert result.isError is False, result.content
    assert result.structuredContent["major"] == 4
    assert (result.structuredContent["major"], result.structuredContent["minor"]) >= (
        4,
        4,
    )


@pytest.mark.e2e
def test_scene_create_over_stdio_creates_a_scene_file(tmp_path):
    scene = tmp_path / "main.tscn"

    result = _call("scene_create", {"path": str(scene), "root_type": "Node2D"})

    assert result.isError is False, result.content
    # The verbatim --params-json dispatch produced gda's typed result…
    assert result.structuredContent["root_type"] == "Node2D"
    # root_name derived model-side from the filename, same as the argv path.
    assert result.structuredContent["root_name"] == "main"
    # …and the .tscn really landed on disk (the real outcome, not a fake).
    assert scene.exists()
