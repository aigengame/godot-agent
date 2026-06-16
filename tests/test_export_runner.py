"""S2: SubprocessExportRunner spawn shape — pure unit (issue #121).

The native-export seam builds the ``godot --headless --export-release`` command
line and spawns it. The one behavior that is load-bearing for #121's acceptance
criterion (export to the preset's *configured* ``export_path``) is the working
directory: Godot resolves a *relative* export output path against its own CWD
(``FileAccess``/``DirAccess`` with no project globalization — verified against the
engine source, ``platform/*/export/export_plugin.cpp``), so the runner must spawn
Godot with ``cwd = <project>`` for the preset's relative configured path (e.g.
``build/game.x86_64``) to land at ``<project>/build/game.x86_64``, exactly as the
editor resolves it. These tests assert that spawn shape without a real engine.
"""

from pathlib import Path

import gda.export_runner as export_runner_mod
from gda.export_runner import SubprocessExportRunner


class _RecordingRun:
    """A ``subprocess.run`` double recording the call and returning a clean exit."""

    def __init__(self) -> None:
        self.cmd: list[str] | None = None
        self.kwargs: dict | None = None

    def __call__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs

        class _Proc:
            stdout = ""
            stderr = ""
            returncode = 0

        return _Proc()


def test_export_runs_with_project_as_cwd(monkeypatch):
    # The configured export_path is relative and Godot resolves a relative output
    # path against its CWD, so the runner must spawn Godot with cwd = the project
    # for the artifact to land inside the project (the #121 acceptance behavior).
    rec = _RecordingRun()
    monkeypatch.setattr(export_runner_mod.subprocess, "run", rec)
    project = Path("/tmp/proj")

    runner = SubprocessExportRunner(Path("/x/Godot"), project=project)
    runner.run("Linux/X11", "release", "build/game.x86_64")

    assert rec.kwargs is not None
    assert rec.kwargs.get("cwd") == str(project)
    # The command still carries --path <project> and the export flags.
    assert "--path" in rec.cmd and str(project) in rec.cmd
    assert rec.cmd[-3:] == ["--export-release", "Linux/X11", "build/game.x86_64"]


def test_export_without_project_passes_no_cwd(monkeypatch):
    # Projectless runs (no resolved project) spawn with the default cwd — there is
    # no project root to resolve a relative path against.
    rec = _RecordingRun()
    monkeypatch.setattr(export_runner_mod.subprocess, "run", rec)

    runner = SubprocessExportRunner(Path("/x/Godot"), project=None)
    runner.run("Linux/X11", "release", "/abs/out.x86_64")

    assert rec.kwargs is not None
    assert rec.kwargs.get("cwd") is None
    assert "--path" not in rec.cmd
