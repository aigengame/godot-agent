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

import functools
import warnings
from pathlib import Path
from typing import Callable, Optional

import anyio
from mcp.client.session import ListRootsFnT
from mcp.shared.exceptions import MCPDeprecationWarning
from mcp.types import CallToolResult, TextContent
from pydantic import FileUrl

from gda.cli import app
from gda.mcp.runner import GdaResult
from gda.surface import build_surface_manifest

# A responder maps one seam invocation ``(args, stdin)`` to its canned result.
Responder = Callable[[list[str], Optional[str]], GdaResult]


class FakeGdaRunner:
    """A fake ``GdaRunner``: routes each invocation through a responder, records calls.

    Each recorded call is ``(args, stdin, project)`` — ``project`` is the resolved
    Godot project gda-mcp injects via the ``GDA_PROJECT`` env channel (ADR-0014,
    #194), so tests assert the project that reached the seam without a subprocess.
    """

    def __init__(self, responder: Responder) -> None:
        self.responder = responder
        self.calls: list[tuple[list[str], Optional[str], Optional[Path]]] = []

    def run(
        self,
        args: list[str],
        *,
        stdin: Optional[str] = None,
        project: Optional[Path] = None,
    ) -> GdaResult:
        self.calls.append((args, stdin, project))
        return self.responder(args, stdin)


@functools.cache
def real_manifest_json() -> str:
    """The live ``gda schema`` manifest as JSON, built in-process (no subprocess).

    ``gda schema`` spawns no Godot (ADR-0012), so the manifest is produced
    directly from the Typer tree — giving the fake seam the *real* whole surface
    to register against. Built ONCE per process (#815): the surface is immutable
    for the process lifetime (the registration tests assert exactly that for the
    server's cache hint), and every ``schema_then`` responder used to rebuild it.
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


def tool_text(result: CallToolResult, index: int = 0) -> str:
    """The text of a ``CallToolResult`` content block (the first by default).

    A gda-mcp tool reply carries its JSON envelope as a ``TextContent`` block, so a
    test reads ``.text`` off it. This narrows the MCP content union
    (``TextContent | ImageContent | …``) to ``TextContent`` once, here, instead of
    a per-assertion ``isinstance``.
    """
    block = result.content[index]
    assert isinstance(block, TextContent), (
        f"expected TextContent, got {type(block).__name__}"
    )
    return block.text


def list_tools(server, *, mode: str = "legacy"):
    """Open an in-memory MCP connection and return the server's ``list_tools`` result."""
    from mcp import Client

    async def _inner():
        async with Client(server, mode=mode, raise_exceptions=True) as client:
            return await client.list_tools()

    return anyio.run(_inner)


def call_tool(
    server,
    name: str,
    arguments: dict,
    *,
    roots: Optional[list[str]] = None,
    mode: str = "legacy",
):
    """Open an in-memory MCP connection, call one tool, return its ``CallToolResult``.

    When ``roots`` is given the in-memory client advertises them (as ``file://``
    URIs) and answers the server's ``roots/list`` request with them, so the
    server's project-context resolution (ADR-0014 precedence 2) can be exercised.
    ``mode`` pins the protocol era: ``"legacy"`` (the default — the pre-2026
    handshake every surveyed agent speaks today, with a roots back-channel) or
    ``"auto"`` (the 2026-07-28 stateless path, no back-channel — ADR-0039's
    degrade tier). ``raise_exceptions=True`` surfaces unexpected server crashes
    in the fast tier instead of the SDK's sanitized internal-error reply.
    """
    from mcp import Client

    list_roots_callback: ListRootsFnT | None = None
    if roots is not None:
        from mcp.types import ListRootsResult, Root

        # The param is named ``context`` to match the ListRootsFnT Protocol.
        async def _list_roots(context):
            return ListRootsResult(
                roots=[Root(uri=FileUrl(Path(r).as_uri())) for r in roots]
            )

        list_roots_callback = _list_roots

    async def _inner():
        async with Client(
            server,
            mode=mode,
            list_roots_callback=list_roots_callback,
            raise_exceptions=True,
        ) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(_inner)


def roots_changed_call(
    server,
    name: str,
    arguments: dict,
    *,
    roots_before: list[str],
    roots_after: list[str],
):
    """Drive #209 within ONE live session: call ``name``, switch the advertised
    roots and fire ``roots/list_changed``, then call ``name`` again.

    Returns ``(result1, result2)``. The client's ``list_roots_callback`` reads a
    mutable holder, so the server's first resolve sees ``roots_before`` and the
    post-notification re-resolve sees ``roots_after`` — exercising dynamic
    re-resolution that the single-shot :func:`call_tool` (roots fixed at connect,
    one call) structurally cannot. Legacy-era by construction: the notification
    only exists on back-channel connections (SEP-2577), so the client-side send
    is deprecated too — suppressed here for the same reason the server suppresses
    its ``list_roots`` warning.
    """
    from mcp import Client
    from mcp.types import ListRootsResult, Root

    holder = {"roots": roots_before}

    # The param is named ``context`` to match the ListRootsFnT Protocol.
    async def _list_roots(context):
        return ListRootsResult(
            roots=[Root(uri=FileUrl(Path(r).as_uri())) for r in holder["roots"]]
        )

    list_roots_callback: ListRootsFnT = _list_roots

    async def _inner():
        async with Client(
            server,
            mode="legacy",
            list_roots_callback=list_roots_callback,
            raise_exceptions=True,
        ) as client:
            r1 = await client.call_tool(name, arguments)
            holder["roots"] = roots_after
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", MCPDeprecationWarning)
                await client.send_roots_list_changed()
            r2 = await client.call_tool(name, arguments)
            return r1, r2

    return anyio.run(_inner)
