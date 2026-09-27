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

import pytest

import gda.runner as runner_module
from gda.exit_codes import EXIT_NOT_FOUND
from gda.runner import OPERATIONS_GD, LaunchFailure, SubprocessGodotRunner
from tests.support import RecordingSpawn


def test_projectless_run_builds_the_script_dispatch_tail(monkeypatch):
    # A projectless op spawns `--headless --script operations.gd -- <op> <json>`
    # with no --path and no working directory: everything after `--` reaches the
    # script verbatim via OS.get_cmdline_user_args().
    rec = RecordingSpawn("<<<GDA:RESULT>>>{}<<<GDA:END>>>")
    monkeypatch.setattr(subprocess, "Popen", rec)
    runner = SubprocessGodotRunner(Path("/x/Godot"))

    runner.run("info", {"a": 1})

    # gda owns the engine log target on every launch (#653), so `--log-file <path>`
    # sits with the other ENGINE options, ahead of this channel's tail — and so
    # ahead of the `--` separator, which must stay the last engine-side argument.
    assert rec.cmd is not None
    assert rec.cmd[:2] == ["/x/Godot", "--headless"]
    assert rec.cmd[2] == "--log-file"
    assert rec.cmd[4:] == [
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
    rec = RecordingSpawn("<<<GDA:RESULT>>>{}<<<GDA:END>>>")
    monkeypatch.setattr(subprocess, "Popen", rec)
    project = Path("/tmp/proj")
    runner = SubprocessGodotRunner(Path("/x/Godot"), project=project)

    runner.run("scene-get", {})

    assert rec.cmd is not None
    # gda's `--log-file <path>` (#653) precedes this channel's tail; --path leads it.
    assert rec.cmd[:3] == ["/x/Godot", "--headless", "--log-file"]
    assert rec.cmd[4:7] == ["--path", str(project), "--script"]
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


# --- a run that must load no project (#1035) ----------------------------------


class _SpawnThatSeesItsDirectory(RecordingSpawn):
    """Record what the ``--path`` directory held WHILE the engine ran."""

    def __init__(self) -> None:
        super().__init__("<<<GDA:RESULT>>>{}<<<GDA:END>>>")
        self.directory: Path | None = None
        self.held: list[str] | None = None

    def __call__(self, cmd, **kwargs):
        self.directory = Path(cmd[cmd.index("--path") + 1])
        self.held = sorted(p.name for p in self.directory.iterdir())
        return super().__call__(cmd, **kwargs)


def test_a_run_that_ignores_the_cwd_points_the_engine_at_an_empty_directory(
    monkeypatch,
):
    # Without --path the engine loads the project it finds in its working
    # directory, which is the invoker's (#1035). A run that must load no project
    # gets a fresh, empty directory as the engine's working directory instead. The
    # spawn's own cwd stays the default, so a relative binary path still resolves
    # against the invoker's directory; the rest of the tail is unchanged.
    rec = _SpawnThatSeesItsDirectory()
    monkeypatch.setattr(subprocess, "Popen", rec)
    runner = SubprocessGodotRunner(Path("/x/Godot"), ignore_cwd=True)

    runner.run("info", {"a": 1})

    assert rec.cmd is not None and rec.directory is not None
    assert rec.cmd[:3] == ["/x/Godot", "--headless", "--log-file"]
    assert rec.cmd[4:] == [
        "--path",
        str(rec.directory),
        "--script",
        str(OPERATIONS_GD),
        "--",
        "info",
        json.dumps({"a": 1}),
    ]
    assert rec.kwargs is not None and rec.kwargs.get("cwd") is None
    # Empty while the engine ran, and gone after it.
    assert rec.held == []
    assert not rec.directory.exists()


def test_a_run_that_ignores_the_cwd_removes_its_directory_when_the_launch_fails(
    monkeypatch,
):
    # The directory is removed after every outcome, not only after a clean exit.
    made: list[str] = []
    real_mkdtemp = runner_module.tempfile.mkdtemp

    def recording_mkdtemp(*args, **kwargs):
        made.append(real_mkdtemp(*args, **kwargs))
        return made[-1]

    monkeypatch.setattr(runner_module.tempfile, "mkdtemp", recording_mkdtemp)
    runner = SubprocessGodotRunner(Path("/nonexistent/Godot"), ignore_cwd=True)

    result = runner.run("info", {})

    assert result.launch_failure is LaunchFailure.NOT_FOUND
    assert [name for name in made if "gda-noproject-" in name]
    assert not any(Path(name).exists() for name in made)


def test_a_run_that_ignores_the_cwd_is_refused_when_its_directory_cannot_be_made(
    monkeypatch,
):
    # No traceback and no new code: the same typed refusal as a private log target
    # that cannot be made in the same temporary directory. Nothing is spawned.
    rec = RecordingSpawn()
    monkeypatch.setattr(subprocess, "Popen", rec)

    def no_room(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(runner_module.tempfile, "mkdtemp", no_room)

    result = SubprocessGodotRunner(Path("/x/Godot"), ignore_cwd=True).run("info", {})

    assert result.launch_failure is LaunchFailure.USER_DATA_UNWRITABLE
    assert result.exit_code == EXIT_NOT_FOUND
    assert "Permission denied" in result.stderr
    assert rec.spawns == 0


def test_ignoring_the_cwd_is_refused_for_a_run_with_a_project():
    # The two inputs contradict each other: a project IS the engine's directory.
    with pytest.raises(ValueError):
        SubprocessGodotRunner(Path("/x/Godot"), project=Path("/p"), ignore_cwd=True)
