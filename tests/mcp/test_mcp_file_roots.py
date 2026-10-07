"""Native file roots through the MCP session and public CLI runner seam (#1111)."""

import json
import os
from pathlib import Path

import anyio
import pytest
from mcp import Client
from mcp.types import ListRootsResult, Root
from pydantic import FileUrl

from gda.mcp.server import build_server
from tests.mcp_support import FakeGdaRunner, gda_result, schema_then
from tests.support import SCENE_CREATE_RESULT, minimal_project


def _call_with_uris(runner, uris):
    server = build_server(runner)

    async def _list_roots(context):
        return ListRootsResult(roots=[Root(uri=FileUrl(uri)) for uri in uris])

    async def _drive():
        async with Client(
            server,
            mode="legacy",
            list_roots_callback=_list_roots,
            raise_exceptions=True,
        ) as client:
            return await client.call_tool(
                "scene_create", {"path": "res://main.tscn", "root_type": "Node2D"}
            )

    return anyio.run(_drive)


def _runner():
    return FakeGdaRunner(
        schema_then(lambda args, stdin: gda_result(json.dumps(SCENE_CREATE_RESULT)))
    )


@pytest.mark.parametrize("has_valid_root", [True, False])
def test_unusable_file_root_uses_next_project_or_cwd(
    tmp_path, monkeypatch, has_valid_root
):
    monkeypatch.delenv("GDA_PROJECT", raising=False)
    invoking = minimal_project(tmp_path / "invoking")
    advertised = minimal_project(tmp_path / "advertised")
    monkeypatch.chdir(invoking)
    # No drive/share on Windows; on Unix, / is a valid path but not this project.
    uris = ["file:///"]
    if has_valid_root:
        uris.append(advertised.as_uri())
    runner = _runner()

    result = _call_with_uris(runner, uris)

    assert result.is_error is False
    assert runner.calls[-1][2] == (advertised if has_valid_root else invoking)


@pytest.mark.skipif(os.name != "nt", reason="native Windows UNC parsing")
def test_unc_file_root_preserves_server_share_and_escaped_name(monkeypatch):
    monkeypatch.delenv("GDA_PROJECT", raising=False)
    expected = Path(r"\\server\share\My Game#%")
    # Filesystem boundary only: parser coverage does not claim a mounted share.
    monkeypatch.setattr(Path, "exists", lambda path: path == expected / "project.godot")
    runner = _runner()

    result = _call_with_uris(runner, ["file://server/share/My%20Game%23%25"])

    assert result.is_error is False
    assert runner.calls[-1][2] == expected
