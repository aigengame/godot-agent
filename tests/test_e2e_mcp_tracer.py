"""S1 (e2e): the gda-mcp `info` tracer — the real chain end to end (issue #193).

The tracer bullet: an in-memory MCP client → in-process low-level Server → the
real ``-m gda info`` subprocess → a real Godot engine. It proves the whole spine
composes (SDK + subprocess seam + dump-introspection + engine) before breadth or
polish. Godot is resolved by gda's OWN precedence — gda-mcp never hardcodes it
(Design decision 1) — so we pin ``$GDA_GODOT`` for determinism; the e2e marker
reuses the shared ``_require_godot_engine`` gate.
"""

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from gda.binary import GODOT_BIN_ENV, resolve_godot_binary
from gda.mcp.runner import SubprocessGdaRunner
from gda.mcp.server import build_server

GODOT = resolve_godot_binary()


@pytest.mark.e2e
def test_info_tracer_real_chain(monkeypatch):
    # Pin Godot for the nested `-m gda` via gda's own env precedence (never
    # hardcoded in gda-mcp). The in-process server introspects the real dump at
    # build time, then the info call shells out through the real seam to a real
    # engine.
    monkeypatch.setenv(GODOT_BIN_ENV, str(GODOT))
    server = build_server(SubprocessGdaRunner.default())

    async def _drive():
        async with connect(server) as session:
            tools = await session.list_tools()
            result = await session.call_tool("info", {})
            return tools, result

    tools, result = anyio.run(_drive)

    # Startup registered the real surface, including the info tracer tool.
    assert "info" in {t.name for t in tools.tools}
    # The call succeeded and the engine version came back as validated
    # structuredContent (the SDK checked it against info's outputSchema).
    assert result.isError is False, result.content
    version = result.structuredContent
    assert version["major"] == 4
    assert (version["major"], version["minor"]) >= (4, 4)  # ADR-0003 minimum
    assert isinstance(version["string"], str)
