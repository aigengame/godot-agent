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
import sysconfig

import anyio
import pytest
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from gda.binary import GODOT_BIN_ENV, resolve_godot_binary

GODOT = resolve_godot_binary()


def _server_params() -> StdioServerParameters:
    # Spawn the REAL `gda-mcp` console script (deliberately NOT `python -m gda.mcp`):
    # this gate exists to validate ADR-0013 *packaging + launch* — that the generated
    # `gda-mcp = gda.mcp:main` entry-point wrapper actually starts and speaks MCP (#193).
    # Resolve it DETERMINISTICALLY from the running interpreter's own scripts dir
    # (`.venv/bin` under `uv run pytest`) — NOT an unbounded `shutil.which("gda-mcp")`,
    # whose PATH lookup returns whatever is first on PATH (a stale global uv-tool install
    # or another worktree's editable `gda-mcp` — the "wrong global" trap that
    # `tests/support.py::GDA_CMD` avoids for the `gda` CLI by keying off `sys.executable`).
    # `shutil.which(..., path=scripts_dir)` restricts the lookup to that one directory yet
    # still applies the platform's launcher rules (POSIX `gda-mcp`, Windows `gda-mcp.exe`
    # via PATHEXT) — so this headless gate stays cross-platform (only live daemon ops are
    # Unix-only) while still launching THIS checkout's console script.
    scripts_dir = sysconfig.get_path("scripts")
    gda_mcp = shutil.which("gda-mcp", path=scripts_dir)
    assert gda_mcp, f"`gda-mcp` console script not found in {scripts_dir}"
    # Full env + a pinned Godot, so the server's nested `-m gda` resolves the
    # same engine deterministically.
    env = {**os.environ, GODOT_BIN_ENV: str(GODOT)}
    return StdioServerParameters(command=str(gda_mcp), args=[], env=env)


def _call(tool: str, arguments: dict, *, mode: str = "legacy"):
    """Spawn the real gda-mcp over stdio, call one tool, return its result.

    ``mode`` pins the protocol era (ADR-0039's dual-era gate): ``"legacy"`` is
    the pre-2026 ``initialize`` handshake every surveyed agent speaks today;
    ``"auto"`` probes ``server/discover`` first — the 2026-07-28 stateless path.
    Deliberately NOT ``raise_exceptions`` (a client-side flag): this gate must
    see exactly what a real agent sees on the wire.
    """

    async def _drive():
        async with Client(stdio_client(_server_params()), mode=mode) as client:
            return await client.call_tool(tool, arguments)

    return anyio.run(_drive)


# Both protocol eras run the SAME assertions: backward compat ("no agent alive
# today breaks") and forward compat (a 2026-07-28 client is served by the same
# binary) are one gate, not a claim (ADR-0039).
@pytest.mark.e2e
@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_info_over_stdio_reports_engine_version(mode):
    result = _call("info", {}, mode=mode)

    assert result.is_error is False, result.content
    assert result.structured_content is not None
    assert result.structured_content["major"] == 4
    assert (result.structured_content["major"], result.structured_content["minor"]) >= (
        4,
        4,
    )


@pytest.mark.e2e
@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_scene_create_over_stdio_creates_a_scene_file(tmp_path, mode):
    scene = tmp_path / "main.tscn"

    result = _call(
        "scene_create", {"path": str(scene), "root_type": "Node2D"}, mode=mode
    )

    assert result.is_error is False, result.content
    assert result.structured_content is not None
    # The verbatim --params-json dispatch produced gda's typed result…
    assert result.structured_content["root_type"] == "Node2D"
    # root_name derived model-side from the filename, same as the argv path.
    assert result.structured_content["root_name"] == "main"
    # …and the .tscn really landed on disk (the real outcome, not a fake).
    assert scene.exists()
