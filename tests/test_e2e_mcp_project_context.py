"""S1 (e2e): gda-mcp project-context resolution — real MCP -> gda -> engine (#194).

The DoD gate for project-context resolution (ADR-0014): an in-memory MCP client
-> in-process low-level Server -> the real ``-m gda`` subprocess -> a real Godot
engine, with the project resolved by gda-mcp and handed to gda through the
``GDA_PROJECT`` env channel (mechanism D). Fakes at the seam (the S2/S3 tiers)
exercise the resolver engine-free; this tier proves the resolution actually
drives gda against the right project on a real engine.

Godot is pinned via gda's OWN ``$GDA_GODOT`` precedence (gda-mcp never hardcodes
it); the e2e marker reuses the shared ``_require_godot_engine`` gate.
"""

from pathlib import Path

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect
from mcp.types import ListRootsResult, Root

from gda.binary import GODOT_BIN_ENV, resolve_godot_binary
from gda.mcp.runner import SubprocessGdaRunner
from gda.mcp.server import build_server

GODOT = resolve_godot_binary()


def _call_tool(server, name, arguments, *, roots=None):
    """Drive one tool call over a real in-memory MCP session (optionally advertising roots)."""
    list_roots_callback = None
    if roots is not None:

        async def list_roots_callback(_ctx):
            return ListRootsResult(roots=[Root(uri=Path(r).as_uri()) for r in roots])

    async def _drive():
        async with connect(server, list_roots_callback=list_roots_callback) as session:
            return await session.call_tool(name, arguments)

    return anyio.run(_drive)


@pytest.mark.e2e
def test_roots_resolution_drives_real_tool_against_resolved_project(
    godot_project, monkeypatch
):
    # The strongest proof: gda cannot read MCP roots itself, so a res:// write
    # landing in the advertised-root project proves gda-mcp resolved the project
    # from roots/list and injected it via GDA_PROJECT for the real gda subprocess.
    monkeypatch.setenv(GODOT_BIN_ENV, str(GODOT))
    monkeypatch.delenv("GDA_PROJECT", raising=False)
    server = build_server(SubprocessGdaRunner.default())

    result = _call_tool(
        server,
        "scene_create",
        {"path": "res://from_roots.tscn", "root_type": "Node2D"},
        roots=[str(godot_project)],
    )

    assert result.isError is False, result.content
    assert (godot_project / "from_roots.tscn").exists()


@pytest.mark.e2e
def test_gda_project_scoped_resolution_drives_real_tool(godot_project, monkeypatch):
    # The recommended project-scoped mode: GDA_PROJECT pins the project, res://
    # resolves against it, and the scene file lands in that project on a real engine.
    monkeypatch.setenv(GODOT_BIN_ENV, str(GODOT))
    monkeypatch.setenv("GDA_PROJECT", str(godot_project))
    server = build_server(SubprocessGdaRunner.default())

    result = _call_tool(
        server, "scene_create", {"path": "res://pinned.tscn", "root_type": "Node2D"}
    )

    assert result.isError is False, result.content
    assert (godot_project / "pinned.tscn").exists()


@pytest.mark.e2e
def test_meta_command_tolerates_a_pinned_project(godot_project, monkeypatch):
    # Mechanism D's payoff: with a project pinned, the meta tool `info` — which
    # rejects a `--project` flag outright — still succeeds, because the project
    # rides the GDA_PROJECT env channel that meta commands simply ignore. A flag
    # mechanism would have broken every meta tool whenever a project was pinned.
    monkeypatch.setenv(GODOT_BIN_ENV, str(GODOT))
    monkeypatch.delenv("GDA_PROJECT", raising=False)
    server = build_server(SubprocessGdaRunner.default())

    result = _call_tool(server, "info", {}, roots=[str(godot_project)])

    assert result.isError is False, result.content
    assert result.structuredContent["major"] == 4
