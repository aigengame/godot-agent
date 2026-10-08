"""The bounded first Windows Live session through the public CLI (#1118)."""

import os

import pytest

from tests.support import Gda, runnable_project


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.name != "nt", reason="Windows owned headless session"),
]


def test_windows_reaches_the_requested_scene_and_keeps_one_session(
    tmp_path,
    daemon_runtime_dir,
):
    project = runnable_project(tmp_path / "project")
    (project / "chosen.tscn").write_text(
        '[gd_scene format=3]\n\n[node name="Chosen" type="Node2D"]\n'
        "position = Vector2(11, 23)\n",
        encoding="utf-8",
    )
    run = Gda(project, json_output=True)
    try:
        run.json("daemon", "start", "--scene", "res://chosen.tscn")
        assert run.json("daemon", "wait-ready", "--timeout", "10")["launched"] is True
        session = run.json("daemon", "status")["session_id"]
        assert isinstance(session, str) and len(session) == 16
        assert run.json("game", "tree")["root"]["name"] == "Chosen"
        value = run.json("game", "get", "/root/Chosen", "--property", "position")
        position = next(
            item for item in value["properties"] if item["name"] == "position"
        )
        assert position["value"] == [11.0, 23.0]
        assert run.json("daemon", "wait-ready")["launched"] is False
        assert run.json("daemon", "status")["session_id"] == session
        assert run.json("daemon", "stop")["stopped"] is True
    finally:
        run("daemon", "stop")
