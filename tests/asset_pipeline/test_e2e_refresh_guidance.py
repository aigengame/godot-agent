"""Public installed-output inspection and explicit file-only refresh."""

import hashlib
import os

import pytest

from tests.asset_pipeline.test_e2e_runtime_refresh import (
    MODEL,
    NODE,
    SCENE,
    _fixture,
    _handoff_args,
)
from tests.support import Gda

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX"),
    pytest.mark.xdist_group("windowed"),
]


@pytest.mark.usefixtures("daemon_runtime_dir")
def test_inspect_installed_output_then_refresh_only_those_files(tmp_path, monkeypatch):
    project, source = tmp_path / "project", tmp_path / "source"
    _fixture(project, source)
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    monkeypatch.setenv("GDA_BLENDER", str(tmp_path / "missing-blender"))
    run = Gda(project, json_output=True, timeout=180)
    installed = project / "model.glb"
    request = {"path": MODEL, "scene": SCENE, "node": NODE}
    try:
        run.json(*_handoff_args(source, "a.glb"))
        run.json("daemon", "start")
        run.json("daemon", "wait-ready", "--timeout", "25")
        old = run.json("game", "inspect-model-content", "--node", NODE)
        assert old["content"]["complete"] is True

        # Install/import/load B without resetting the still-running A session.
        run.json(*_handoff_args(source, "b.glb"))
        installed_hash = hashlib.sha256(installed.read_bytes()).hexdigest()
        inspected = run.json("resource", "inspect-model-content", "--path", MODEL)
        assert inspected["content"]["complete"] is True
        assert inspected["content"]["digest"] != old["content"]["digest"]
        stale = run.json("game", "inspect-model-content", "--node", NODE)
        assert stale["session_id"] == old["session_id"]
        assert stale["content"]["digest"] == old["content"]["digest"]

        # The producer's original output is gone; the installed file is sufficient.
        (source / "b.glb").unlink()
        assert hashlib.sha256(installed.read_bytes()).hexdigest() == installed_hash
        result = run.json(*_handoff_args(project, str(installed), refresh=request))
        refresh = result["pipeline"]["refresh"]
        assert result["pipeline"]["production"] is None
        assert refresh["status"] == "verified"
        assert refresh["before"]["session_id"] == old["session_id"]
        assert refresh["after"]["session_id"] != old["session_id"]
        assert (
            refresh["instance"]["content"]["digest"] == inspected["content"]["digest"]
        )
        assert hashlib.sha256(installed.read_bytes()).hexdigest() == installed_hash

        # A diagnosed omission remains a negative when LOD/texture support expands.
        bounded = run.json(
            "resource",
            "inspect-model-content",
            "--path",
            MODEL,
            "--max-vertices",
            "1",
        )
        assert bounded["content"]["complete"] is False
        assert bounded["content"]["digest"] is None
        assert bounded["content"]["omitted"]
        assert hashlib.sha256(installed.read_bytes()).hexdigest() == installed_hash
        error = run.error(
            *_handoff_args(
                project, str(installed), refresh=request | {"max_vertices": 1}
            ),
            code="operation_failed",
        )
        partial = error["partial_result"]["refresh"]
        assert partial["status"] == "incomplete"
        assert partial["before"]["running"] is True
        assert partial["before"]["session_id"] == refresh["after"]["session_id"]
        assert partial["after"]["running"] is True
        assert partial["after"]["session_id"] != partial["before"]["session_id"]
        assert partial["imported"]["content"]["omitted"]
        assert partial["runtime_state_preserved"] is False
        assert "completed reset stages: stop, start, ready" in error["message"]
        assert (
            f"last observed: running=true, session={partial['after']['session_id']}"
            in error["message"]
        )
        assert "content verification is incomplete" in error["message"]
    finally:
        stopped = run("daemon", "stop")
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
