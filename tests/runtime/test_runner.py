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
import tempfile
from pathlib import Path

import pytest

from gda.exit_codes import EXIT_NOT_FOUND
from gda.runner import (
    OPERATIONS_GD,
    USER_DATA_ROOT_ENV,
    LaunchFailure,
    SubprocessGodotRunner,
    set_user_data_root,
)
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

_OK = "<<<GDA:RESULT>>>{}<<<GDA:END>>>"


def _arg_after(cmd: list[str], flag: str) -> Path:
    return Path(cmd[cmd.index(flag) + 1])


def _regular_file(tmp_path: Path) -> Path:
    """A path that cannot be a temporary directory: it is a regular file."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("", encoding="utf-8")
    return blocker


class _SpawnThatSeesItsDirectory:
    """A ``subprocess.Popen`` double that records the ``--path`` directory, and what
    it held, WHILE the engine ran.

    ``error`` makes the spawn fail after it recorded, as a binary that cannot be
    launched does. Otherwise the canned child is made up front, while the
    temporary directory still works: its streams are temporary files, and one test
    breaks that directory before the launch.
    """

    def __init__(self, error: OSError | None = None) -> None:
        self._error = error
        self._child = None if error is not None else RecordingSpawn(_OK)([])
        self.cmd: list[str] | None = None
        self.kwargs: dict | None = None
        self.held: list[str] | None = None

    def __call__(self, cmd, **kwargs):
        self.cmd, self.kwargs = cmd, kwargs
        self.held = sorted(p.name for p in _arg_after(cmd, "--path").iterdir())
        if self._error is not None:
            raise self._error
        return self._child

    @property
    def directory(self) -> Path:
        assert self.cmd is not None
        return _arg_after(self.cmd, "--path")

    @property
    def log_directory(self) -> Path:
        assert self.cmd is not None
        return _arg_after(self.cmd, "--log-file").parent


def test_a_run_that_ignores_the_cwd_points_the_engine_at_an_empty_directory(
    monkeypatch,
):
    # Without --path the engine loads the project it finds in its working
    # directory, which is the invoker's (#1035). A run that must load no project
    # gets an empty directory from its user-data placement, beside the log, as the
    # engine's working directory. The spawn's own cwd stays the default, so a
    # relative binary path still resolves against the invoker's directory; the
    # rest of the tail is unchanged.
    rec = _SpawnThatSeesItsDirectory()
    monkeypatch.setattr(subprocess, "Popen", rec)
    runner = SubprocessGodotRunner(Path("/x/Godot"), ignore_cwd=True)

    result = runner.run("info", {"a": 1})

    assert result.launch_failure is None
    assert rec.cmd is not None
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
    # Empty while the engine ran, in the log's directory, and gone after it.
    assert rec.held == []
    assert rec.directory.parent == rec.log_directory
    assert not rec.directory.exists()


def test_a_run_that_ignores_the_cwd_removes_its_directory_when_the_launch_fails(
    monkeypatch,
):
    # The directory is removed after every outcome, not only after a clean exit.
    rec = _SpawnThatSeesItsDirectory(error=FileNotFoundError(2, "No such file"))
    monkeypatch.setattr(subprocess, "Popen", rec)
    runner = SubprocessGodotRunner(Path("/x/Godot"), ignore_cwd=True)

    result = runner.run("info", {})

    assert result.launch_failure is LaunchFailure.NOT_FOUND
    assert rec.held == []
    assert rec.directory.parent == rec.log_directory
    assert not rec.directory.exists()


def test_under_a_root_a_run_that_ignores_the_cwd_does_not_use_the_temporary_directory(
    monkeypatch, tmp_path
):
    # The PR #1037 review counterexample. Under a writable user-data root, no part
    # of the placement uses the Python temporary directory, so an unusable one did
    # not stop a launch before #1035, and it must not stop this one: the empty
    # directory is made beside the log, in <root>/logs.
    set_user_data_root(None)
    root = tmp_path / "udr"
    monkeypatch.setenv(USER_DATA_ROOT_ENV, str(root))
    rec = _SpawnThatSeesItsDirectory()
    monkeypatch.setattr(subprocess, "Popen", rec)
    monkeypatch.setattr(tempfile, "tempdir", str(_regular_file(tmp_path)))

    result = SubprocessGodotRunner(Path("/x/Godot"), ignore_cwd=True).run("info", {})

    assert result.launch_failure is None
    assert result.exit_code == 0
    assert rec.directory.parent == root / "logs"
    assert rec.held == []
    assert not rec.directory.exists()


def test_without_a_root_an_unusable_temporary_directory_refuses_both_runs_alike(
    monkeypatch, tmp_path
):
    # Without a root, the log itself needs the temporary directory, so both runs
    # are refused before any spawn. The run that must load no project gets the
    # same refusal, byte for byte: its empty directory adds no failure of its own.
    # `mkdtemp` picks a random name and the OS error quotes it, so the names are
    # fixed here to compare the two refusals exactly.
    set_user_data_root(None)
    monkeypatch.delenv(USER_DATA_ROOT_ENV, raising=False)
    rec = RecordingSpawn()
    monkeypatch.setattr(subprocess, "Popen", rec)
    monkeypatch.setattr(tempfile, "tempdir", str(_regular_file(tmp_path)))
    monkeypatch.setattr(tempfile, "_get_candidate_names", lambda: iter(["fixed"]))

    isolated = SubprocessGodotRunner(Path("/x/Godot"), ignore_cwd=True).run("info", {})
    plain = SubprocessGodotRunner(Path("/x/Godot")).run("info", {})

    assert isolated.launch_failure is LaunchFailure.USER_DATA_UNWRITABLE
    assert (isolated.launch_failure, isolated.exit_code, isolated.stderr) == (
        plain.launch_failure,
        plain.exit_code,
        plain.stderr,
    )
    assert rec.spawns == 0


def test_ignoring_the_cwd_is_refused_for_a_run_with_a_project():
    # The two inputs contradict each other: a project IS the engine's directory.
    with pytest.raises(ValueError):
        SubprocessGodotRunner(Path("/x/Godot"), project=Path("/p"), ignore_cwd=True)
