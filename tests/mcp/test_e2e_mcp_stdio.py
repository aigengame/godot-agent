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
import shlex
import shutil
import subprocess
import sys
import sysconfig

import anyio
import pytest
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import ListRootsResult, Root
from pydantic import FileUrl

from gda.core.engine.binary import GDA_GODOT_ENV
from gda.mcp.runner import GDA_BIN_ENV
from tests.conftest import project_godot
from tests.support import GODOT, minimal_project, runnable_project, Gda


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
    env = {**os.environ, GDA_GODOT_ENV: str(GODOT)}
    return StdioServerParameters(command=str(gda_mcp), args=[], env=env)


def _call(tool: str, arguments: dict, *, mode: str, expected_protocol: str):
    """Spawn the real gda-mcp over stdio, call one tool, return its result.

    ``mode`` pins the protocol era (ADR-0039's dual-era gate): ``"legacy"`` is
    the pre-2026 ``initialize`` handshake every surveyed agent speaks today;
    ``"2026-07-28"`` pins the stateless era outright — deliberately NOT
    ``"auto"``, which falls back to the legacy handshake on a server that lost
    modern support, so an auto-mode run could go green without ever proving the
    modern path. The negotiated ``expected_protocol`` is asserted for the same
    reason: era coverage must be able to FAIL, not just happen. Deliberately
    NOT ``raise_exceptions`` (a client-side flag): this gate must see exactly
    what a real agent sees on the wire.
    """

    async def _drive():
        async with Client(stdio_client(_server_params()), mode=mode) as client:
            assert client.protocol_version == expected_protocol
            return await client.call_tool(tool, arguments)

    return anyio.run(_drive)


# Both protocol eras run the SAME assertions: backward compat ("no agent alive
# today breaks") and forward compat (a 2026-07-28 client is served by the same
# binary) are one gate, not a claim (ADR-0039). The engine-free half of the
# gate (handshake + surface) also runs on every PR in the fast tier
# (test_mcp_stdio_handshake.py); this e2e half adds real tool dispatch.
_ERAS = [("legacy", "2025-11-25"), ("2026-07-28", "2026-07-28")]


@pytest.mark.e2e
@pytest.mark.parametrize(("mode", "expected_protocol"), _ERAS)
def test_daemon_lifecycle_over_stdio(
    mode, expected_protocol, tmp_path, daemon_runtime_dir, monkeypatch
):
    project = runnable_project(tmp_path / "project")
    monkeypatch.setenv("GDA_PROJECT", str(project))

    async def drive():
        async with Client(stdio_client(_server_params()), mode=mode) as client:
            assert client.protocol_version == expected_protocol
            started = await client.call_tool("daemon_start", {})
            assert started.is_error is False, started.content
            status = await client.call_tool("daemon_status", {})
            assert status.is_error is False, status.content
            assert status.structured_content["running"] is True
            assert status.structured_content["session_id"] is None
            stopped = await client.call_tool("daemon_stop", {})
            assert stopped.is_error is False, stopped.content
            assert stopped.structured_content["stopped"] is True
            status = await client.call_tool("daemon_status", {})
            assert status.structured_content["running"] is False

    try:
        anyio.run(drive)
    finally:
        Gda(project)("daemon", "stop")


@pytest.mark.e2e
@pytest.mark.parametrize(("mode", "expected_protocol"), _ERAS)
def test_info_over_stdio_reports_engine_version(mode, expected_protocol):
    result = _call("info", {}, mode=mode, expected_protocol=expected_protocol)

    assert result.is_error is False, result.content
    assert result.structured_content is not None
    assert result.structured_content["major"] == 4
    assert (result.structured_content["major"], result.structured_content["minor"]) >= (
        4,
        4,
    )


@pytest.mark.e2e
@pytest.mark.parametrize(("mode", "expected_protocol"), _ERAS)
def test_scene_create_over_stdio_creates_a_scene_file(
    tmp_path, mode, expected_protocol
):
    scene = tmp_path / "main.tscn"

    result = _call(
        "scene_create",
        {"path": str(scene), "root_type": "Node2D"},
        mode=mode,
        expected_protocol=expected_protocol,
    )

    assert result.is_error is False, result.content
    assert result.structured_content is not None
    # The verbatim --params-json dispatch produced gda's typed result…
    assert result.structured_content["root_type"] == "Node2D"
    # root_name derived model-side from the filename, same as the argv path.
    assert result.structured_content["root_name"] == "main"
    # …and the .tscn really landed on disk (the real outcome, not a fake).
    assert scene.exists()


@pytest.mark.e2e
@pytest.mark.parametrize(("mode", "expected_protocol"), _ERAS)
def test_command_override_starts_mcp_and_mutates_the_pinned_project(
    tmp_path, mode, expected_protocol
):
    project = minimal_project(tmp_path / "My Game")
    entry = tmp_path / "command with spaces" / "gda entry.py"
    entry.parent.mkdir()
    entry.write_text("from gda.cli import entrypoint\nentrypoint()\n", encoding="utf-8")
    command = [sys.executable, "-B", str(entry)]
    params = _server_params()
    assert params.env is not None
    params.env[GDA_BIN_ENV] = (
        subprocess.list2cmdline(command)
        if sys.platform == "win32"
        else shlex.join(command)
    )
    params.env["GDA_PROJECT"] = str(project)

    async def _drive():
        async with Client(stdio_client(params), mode=mode) as client:
            assert client.protocol_version == expected_protocol
            tools = await client.list_tools()
            assert "scene_create" in {tool.name for tool in tools.tools}
            created = await client.call_tool(
                "scene_create",
                {"path": "res://from_override.tscn", "root_type": "Node2D"},
            )
            assert created.is_error is False, created.content
            got = await client.call_tool(
                "scene_get", {"path": "res://from_override.tscn"}
            )
            assert got.is_error is False, got.content
            assert got.structured_content is not None
            assert got.structured_content["root"]["name"] == "from_override"

    anyio.run(_drive)
    assert (project / "from_override.tscn").exists()


def _project_files(project):
    return {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }


@pytest.mark.e2e
@pytest.mark.parametrize("pin_project", [False, True], ids=["roots", "env"])
def test_file_roots_over_stdio_respect_project_precedence(tmp_path, pin_project):
    advertised = minimal_project(tmp_path / "My Game % # café")
    invoking = minimal_project(tmp_path / "invoking")
    pinned = minimal_project(tmp_path / "pinned")
    for project in (advertised, invoking, pinned):
        (project / "project.godot").write_text(project_godot(), encoding="utf-8")
    target = pinned if pin_project else advertised
    untouched = (invoking, advertised if pin_project else pinned)
    before = {project: _project_files(project) for project in untouched}
    params = _server_params()
    assert params.env is not None
    params.env.pop("GDA_PROJECT", None)
    if pin_project:
        params.env["GDA_PROJECT"] = str(pinned)
    params.cwd = invoking

    async def _list_roots(context):
        return ListRootsResult(roots=[Root(uri=FileUrl(advertised.as_uri()))])

    async def _drive():
        async with Client(
            stdio_client(params), mode="legacy", list_roots_callback=_list_roots
        ) as client:
            assert client.protocol_version == "2025-11-25"
            return await client.call_tool(
                "scene_create", {"path": "res://from_roots.tscn", "root_type": "Node2D"}
            )

    result = anyio.run(_drive)

    assert result.is_error is False, result.content
    assert (target / "from_roots.tscn").exists()
    after = {project: _project_files(project) for project in untouched}
    assert after == before
