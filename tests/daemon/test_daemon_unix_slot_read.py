"""A Unix daemon slot that gda cannot read gives a structured result (#1201 A).

The Live commands and the daemon lifecycle commands read the daemon slot through
the project's pidfile. A pidfile that exists but cannot be read is a runtime
directory that cannot serve, as on Windows: `daemon_runtime_unusable`. A pidfile
whose bytes are not UTF-8 is malformed, and a malformed pidfile reads as absent.
"""

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.core.engine.binary import GDA_GODOT_ENV
from gda.daemon.discovery import daemon_paths
from gda.daemon.unix import UnixPlatform
from gda.exit_codes import EXIT_LIVE
from tests.support import runnable_project

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the Unix daemon slot is a pidfile"
)

COMMANDS = [
    ["game", "tree"],
    ["daemon", "status"],
    ["daemon", "stop"],
    ["daemon", "start"],
    ["daemon", "wait-ready"],
    ["daemon", "uninstall"],
]


@pytest.fixture(autouse=True)
def _no_engine(monkeypatch):
    # `daemon start` must stop before it spawns a daemon, on a host that has an
    # engine configured too.
    monkeypatch.setenv(GDA_GODOT_ENV, "/nonexistent/godot")


def _pidfile(project: Path) -> Path:
    pidfile = daemon_paths(project, platform=UnixPlatform()).pidfile
    pidfile.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return pidfile


def _run(command: list[str], project: Path):
    return CliRunner().invoke(app, [*command, "--project", str(project), "--json"])


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root reads a file with mode 000",
)
@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
def test_an_unreadable_pidfile_is_a_runtime_that_cannot_serve(
    command, tmp_path, daemon_runtime_dir
):
    project = runnable_project(tmp_path / "project")
    pidfile = _pidfile(project)
    pidfile.write_text(f"{os.getpid()}\n{project.resolve()}\n", encoding="utf-8")
    pidfile.chmod(0)
    try:
        result = _run(command, project)
    finally:
        pidfile.chmod(0o600)

    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.exit_code == EXIT_LIVE
    assert json.loads(result.stdout)["error"]["code"] == "daemon_runtime_unusable"


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
def test_an_undecodable_pidfile_reads_as_absent(command, tmp_path, daemon_runtime_dir):
    project = runnable_project(tmp_path / "project")
    absent = _run(command, project)
    _pidfile(project).write_bytes(b"\xff\xfe\x00bad\n")

    result = _run(command, project)

    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert (result.exit_code, result.stdout) == (absent.exit_code, absent.stdout)
