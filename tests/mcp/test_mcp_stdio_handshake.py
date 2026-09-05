"""Fast dual-era stdio handshake gate (#601, ADR-0039).

The engine-free half of ADR-0039's dual-era gate, running on every PR: the real
``gda-mcp`` **console script** over **real stdio**, once per protocol era. Era
negotiation needs no Godot — startup introspection (``gda schema``) spawns no
engine (ADR-0012) — so this tier proves the handshake and the generated surface
where CI actually looks, while the e2e twin (``test_e2e_mcp_stdio.py``) adds
real tool dispatch against a real engine on the nightly tier.

Two deliberate choices keep the gate falsifiable (the whole point — era coverage
must be able to FAIL): the modern era is pinned as ``mode="2026-07-28"``, never
``"auto"`` (auto falls back to the legacy handshake on a server that lost modern
support, so it can go green without proving anything), and the negotiated
``protocol_version`` is asserted per era.
"""

import shutil
import sysconfig

import anyio
import pytest
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client


def _server_params() -> StdioServerParameters:
    # The real console script, resolved deterministically from this
    # interpreter's scripts dir — same rationale as the e2e twin (ADR-0013;
    # never an unbounded PATH lookup).
    scripts_dir = sysconfig.get_path("scripts")
    gda_mcp = shutil.which("gda-mcp", path=scripts_dir)
    assert gda_mcp, f"`gda-mcp` console script not found in {scripts_dir}"
    return StdioServerParameters(command=str(gda_mcp), args=[])


@pytest.mark.parametrize(
    ("mode", "expected_protocol"),
    [("legacy", "2025-11-25"), ("2026-07-28", "2026-07-28")],
)
def test_console_script_serves_both_protocol_eras(mode, expected_protocol):
    async def _drive():
        async with Client(stdio_client(_server_params()), mode=mode) as client:
            assert client.protocol_version == expected_protocol
            tools = await client.list_tools()
            # The generated surface registered over this era's handshake.
            assert "info" in {t.name for t in tools.tools}

    anyio.run(_drive)
