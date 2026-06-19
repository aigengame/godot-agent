"""Shared test support for driving gda-mcp without a real engine (issue #193).

The gda-mcp analogue of :mod:`tests.support`, one layer up: where ``support.py``
fakes gda's ``GodotRunner`` (gda ↔ engine), this fakes gda-mcp's ``GdaRunner``
seam (gda-mcp ↔ gda). :class:`FakeGdaRunner` satisfies the seam with a canned
:class:`~gda.mcp.runner.GdaResult` per invocation and records every
``(args, stdin)`` it is asked to run, so the whole introspect → register →
dispatch → result/error-map pipeline is exercised over an **in-memory MCP
client → in-process server** with no ``gda`` subprocess and no Godot (Design
decision 2 / 6).

The fast tiers drive the surface from the **real** aggregate dump
(:func:`real_manifest_json`), built in-process — so registration coverage is a
true mirror of the live ``gda`` surface, not a hand-stubbed subset.
"""

from typing import Callable, Optional

import anyio

from gda.cli import app
from gda.mcp.runner import GdaResult
from gda.surface import build_surface_manifest

# A responder maps one seam invocation ``(args, stdin)`` to its canned result.
Responder = Callable[[list[str], Optional[str]], GdaResult]


class FakeGdaRunner:
    """A fake ``GdaRunner``: routes each invocation through a responder, records calls."""

    def __init__(self, responder: Responder) -> None:
        self.responder = responder
        self.calls: list[tuple[list[str], Optional[str]]] = []

    def run(self, args: list[str], *, stdin: Optional[str] = None) -> GdaResult:
        self.calls.append((args, stdin))
        return self.responder(args, stdin)


def real_manifest_json() -> str:
    """The live ``gda schema`` manifest as JSON, built in-process (no subprocess).

    ``gda schema`` spawns no Godot (ADR-0012), so the manifest is produced
    directly from the Typer tree — giving the fake seam the *real* whole surface
    to register against.
    """
    return build_surface_manifest(app).model_dump_json()


def schema_then(dispatch: Responder) -> Responder:
    """A responder that serves the real dump for ``gda schema``, else ``dispatch``.

    Startup introspection (``["schema"]``) gets the real manifest so the full
    tool surface registers; every other invocation (a per-tool dispatch) is
    delegated to ``dispatch``.
    """
    manifest = real_manifest_json()

    def responder(args: list[str], stdin: Optional[str]) -> GdaResult:
        if args[:1] == ["schema"]:
            return GdaResult(stdout=manifest, stderr="", returncode=0)
        return dispatch(args, stdin)

    return responder


def gda_result(stdout: str = "", stderr: str = "", returncode: int = 0) -> GdaResult:
    """Terse :class:`GdaResult` factory for canned seam responses."""
    return GdaResult(stdout=stdout, stderr=stderr, returncode=returncode)


def list_tools(server):
    """Open an in-memory MCP session and return the server's ``list_tools`` result."""
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    async def _inner():
        async with connect(server) as session:
            return await session.list_tools()

    return anyio.run(_inner)


def call_tool(server, name: str, arguments: dict):
    """Open an in-memory MCP session, call one tool, return its ``CallToolResult``."""
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    async def _inner():
        async with connect(server) as session:
            return await session.call_tool(name, arguments)

    return anyio.run(_inner)
