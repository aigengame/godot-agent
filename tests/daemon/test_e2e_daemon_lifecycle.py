"""Public daemon lifecycle, independently of engine-session availability (#1117)."""

import json
import os

import pytest

from tests.support import Gda, runnable_project


@pytest.fixture
def lifecycle_project(tmp_path, monkeypatch, request):
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    else:
        request.getfixturevalue("daemon_runtime_dir")
    return runnable_project(tmp_path / "project")


@pytest.mark.e2e
def test_a_daemon_remains_available_after_start_and_protects_its_harness(
    lifecycle_project,
):
    run = Gda(lifecycle_project, json_output=True)
    try:
        started = run.json("daemon", "start")
        assert started["already_running"] is False
        status = run.json("daemon", "status")
        assert status["running"] is True
        assert status["pid"] == started["pid"]
        assert status["session_id"] is None
        assert status["startup_diagnostics"] is None
        assert status["clean_start"] is None
        again = run.json("daemon", "start")
        assert again["already_running"] is True
        assert again["pid"] == started["pid"]
        refused = run("daemon", "uninstall")
        assert refused.returncode == 6, refused.stdout + refused.stderr
        assert json.loads(refused.stdout)["error"]["code"] == "daemon_running"
    finally:
        run("daemon", "stop")
    assert run.json("daemon", "status")["running"] is False
    assert run.json("daemon", "stop")["stopped"] is False
    assert run.json("daemon", "uninstall")["removed"] is True
    assert run.json("daemon", "uninstall")["removed"] is False
