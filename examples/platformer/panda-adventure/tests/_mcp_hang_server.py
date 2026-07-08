"""A minimal MCP server whose ``generate_image`` tool hangs — for the McpBackend
timeout test (P2-S1, #439). Not a test file (leading underscore -> not collected);
launched as a subprocess. Uses only ``mcp`` (a dev dependency), never
``google-genai``, so it runs in the fast CI tier."""

from __future__ import annotations

import time

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("hang")


@mcp.tool()
def generate_image(prompt: str, output_path: str = "") -> str:
    """Never returns in time — sleeps far past any reasonable acquire timeout."""
    time.sleep(30)
    return "unreachable"


if __name__ == "__main__":
    mcp.run()
