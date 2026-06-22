"""S1 (e2e): a LIVE command served end-to-end through gda-mcp (issue #227).

The #227 verification, top to bottom: an in-memory MCP client → the in-process
gda-mcp ``Server`` → the real ``gda`` subprocess seam → ``gda-daemon`` → an
``Engine session`` it launches with the harness → the running game's runtime
``SceneTree``. It proves a live command auto-exposes and *routes* as a tool with
NO live-specific code in gda-mcp (ADR-0011): the same generic ``--params-json``
dispatch + exit-code map that serves a headless tool carries the live one, so on
success the SDK validates and wraps gda's result as ``structuredContent`` and on
failure gda's full ``GdaError`` envelope crosses verbatim as ``isError`` content.

Two routings:

- **success** — ``daemon_start`` then ``game_tree`` over one MCP session: the
  daemon launches the session on demand, the live op returns the runtime tree,
  and ``structuredContent.root.name == "Main"`` (the same proof as
  ``test_e2e_daemon``, now driven through gda-mcp instead of the console script).
- **failure** — ``game_tree`` with no daemon: gda's typed
  ``daemon_not_running`` / category ``live`` envelope reaches the client
  losslessly as ``isError`` content, with ``structuredContent is None`` (the
  envelope is kept out of the success channel — ADR-0011).

Godot is resolved by gda's OWN precedence (gda-mcp never hardcodes it); the
project reaches gda via the ``GDA_PROJECT`` env channel gda-mcp injects. Both are
pinned via ``monkeypatch.setenv`` for determinism. Run e2e serially; not a fresh
empty HOME (Godot first-run). ``daemon_runtime_dir`` keeps the daemon's UDS path
within the OS ``sun_path`` limit (NOT ``tmp_path``).
"""

import json
import os

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from gda.binary import GODOT_BIN_ENV, resolve_godot_binary
from gda.mcp.project_context import GDA_PROJECT_ENV
from gda.mcp.runner import SubprocessGdaRunner
from gda.mcp.server import build_server

from .conftest import project_godot

GODOT = resolve_godot_binary()

# Reuse test_e2e_daemon's scaffold: a main scene so the launched session has a
# runtime SceneTree to read; a Player child mirrors the daemon e2e fixture. File
# logging stays disabled via project_godot (issue #180).
MAIN_TSCN = (
    "[gd_scene format=3]\n\n"
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
)
PROJECT_GODOT = project_godot(extra='run/main_scene="res://main.tscn"')

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


def _scaffold_project(tmp_path):
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")


def _pin_env(monkeypatch, project):
    # Pin Godot for the nested `gda` via gda's own env precedence (never hardcoded
    # in gda-mcp), and hand gda the project through the GDA_PROJECT channel the
    # in-process server reads at resolve time and forwards on every dispatch
    # (ADR-0014). The daemon the start tool spawns inherits XDG_RUNTIME_DIR (set
    # short by daemon_runtime_dir) through the subprocess environment.
    monkeypatch.setenv(GODOT_BIN_ENV, str(GODOT))
    monkeypatch.setenv(GDA_PROJECT_ENV, str(project))


@pytest.mark.e2e
def test_mcp_live_game_tree_routes_through_daemon_to_a_real_tree(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # Success routing: the live `game tree` tool, dispatched by the SAME generic
    # gda-mcp path as a headless tool, returns the RUNNING game's runtime tree as
    # validated structuredContent.
    _scaffold_project(tmp_path)
    _pin_env(monkeypatch, tmp_path)
    server = build_server(SubprocessGdaRunner.default())

    async def _drive():
        async with connect(server) as session:
            # Start the daemon over MCP; it installs the harness and stands ready
            # to launch an engine session on demand.
            started = await session.call_tool("daemon_start", {})
            tree = await session.call_tool("game_tree", {})
            return started, tree

    try:
        started, tree = anyio.run(_drive)

        # daemon_start succeeded through the generic dispatcher (exit 0 → result
        # dict wrapped as structuredContent by the SDK).
        assert started.isError is False, started.content
        assert started.structuredContent["installed_harness"] is True

        # The live op routed CLI → daemon → engine session and returned the live
        # runtime tree — exactly what a headless tool's success looks like.
        assert tree.isError is False, tree.content
        root = tree.structuredContent["root"]
        assert root["name"] == "Main"
        assert root["type"] == "Node2D"
    finally:
        anyio.run(_stop_daemon, server)


@pytest.mark.e2e
def test_mcp_live_game_tree_relays_daemon_not_running_verbatim(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    # Failure routing: with no daemon, gda's typed `daemon_not_running` / category
    # `live` GdaError reaches the MCP client losslessly as isError content, and is
    # kept OUT of structuredContent (ADR-0011) — the same error channel a headless
    # tool failure uses, carrying a live-category code.
    _scaffold_project(tmp_path)
    _pin_env(monkeypatch, tmp_path)
    server = build_server(SubprocessGdaRunner.default())

    async def _drive():
        async with connect(server) as session:
            return await session.call_tool("game_tree", {})

    try:
        result = anyio.run(_drive)

        assert result.isError is True, result.content
        # The success channel is empty: gda-mcp never puts a failure envelope into
        # structuredContent / outputSchema.
        assert result.structuredContent is None
        # The full GdaError envelope crossed verbatim as text content.
        assert result.content, "expected the GdaError envelope as text content"
        payload = json.loads(result.content[0].text)
        error = payload["error"]
        assert error["code"] == "daemon_not_running"
        assert error["category"] == "live"
        # The remediation message is preserved, not flattened to bare prose.
        assert "gda daemon start" in error["message"]
    finally:
        anyio.run(_stop_daemon, server)


async def _stop_daemon(server):
    # Best-effort teardown over a fresh MCP session: stop any daemon this test
    # left running so e2e runs stay isolated. Tolerant of "no daemon" (the failure
    # test never starts one).
    try:
        async with connect(server) as session:
            await session.call_tool("daemon_stop", {})
    except Exception:
        pass
