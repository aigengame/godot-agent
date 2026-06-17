"""SubprocessGodotRunner builds the sentinel argv tail and delegates to launch.

The launch / timeout / OSError / UTF-8-decode contract now lives once on the
shared ``launch`` primitive (tested in ``test_launch.py``); this suite covers
only what is *specific* to the sentinel op-dispatch channel: the argv tail it
builds (``--path`` when a project is set, then ``--script operations.gd -- <op>
<json params>``), and that a launch failure still surfaces through the typed
``run(operation, params)`` adapter rather than escaping as a traceback (#185).
"""

import json
import subprocess
from pathlib import Path

from gda.exit_codes import EXIT_NOT_FOUND
from gda.runner import OPERATIONS_GD, LaunchFailure, SubprocessGodotRunner


class _RecordingRun:
    """A ``subprocess.run`` double recording the call and returning a clean exit."""

    def __init__(self) -> None:
        self.cmd: list[str] | None = None
        self.kwargs: dict | None = None

    def __call__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs

        class _Proc:
            # The primitive captures bytes (no text=True) and decodes UTF-8
            # itself, so the double mirrors that real subprocess contract (#33).
            stdout = b"<<<GDA:RESULT>>>{}<<<GDA:END>>>"
            stderr = b""
            returncode = 0

        return _Proc()


def test_projectless_run_builds_the_script_dispatch_tail(monkeypatch):
    # A projectless op spawns `--headless --script operations.gd -- <op> <json>`
    # with no --path and no working directory: everything after `--` reaches the
    # script verbatim via OS.get_cmdline_user_args().
    rec = _RecordingRun()
    monkeypatch.setattr(subprocess, "run", rec)
    runner = SubprocessGodotRunner(Path("/x/Godot"))

    runner.run("info", {"a": 1})

    assert rec.cmd == [
        "/x/Godot",
        "--headless",
        "--script",
        str(OPERATIONS_GD),
        "--",
        "info",
        json.dumps({"a": 1}),
    ]
    # A sentinel op never needs a working directory.
    assert rec.kwargs is not None and rec.kwargs.get("cwd") is None


def test_run_against_a_project_passes_path(monkeypatch):
    # When a project is resolved it is passed as --path so the engine runs against
    # it and res:// resolves there (#32); --path precedes the --script tail.
    rec = _RecordingRun()
    monkeypatch.setattr(subprocess, "run", rec)
    project = Path("/tmp/proj")
    runner = SubprocessGodotRunner(Path("/x/Godot"), project=project)

    runner.run("scene-get", {})

    assert rec.cmd is not None
    assert rec.cmd[:5] == ["/x/Godot", "--headless", "--path", str(project), "--script"]
    # A sentinel op runs against --path, never with a working directory.
    assert rec.kwargs is not None and rec.kwargs.get("cwd") is None


def test_launch_failure_surfaces_through_the_typed_run_adapter():
    # A missing binary surfaces through the typed run(operation, params) adapter
    # as a synthesized launch failure, not a raw traceback — the runner delegates
    # the launch handling to the shared primitive (#185).
    runner = SubprocessGodotRunner(Path("/nonexistent/Godot"))

    result = runner.run("info", {})

    assert result.exit_code == EXIT_NOT_FOUND
    assert "/nonexistent/Godot" in result.stderr
    assert result.launch_failure is LaunchFailure.NOT_FOUND
