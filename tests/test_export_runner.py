"""S2: SubprocessExportRunner spawn shape — pure unit (issue #121, #185).

The native-export seam builds the ``godot --headless --export-release`` argv tail
and the export-only working directory, then delegates the spawn / timeout /
``OSError`` / UTF-8-decode handling to the shared ``launch`` primitive (tested in
``test_launch.py``). This suite covers only what is *specific* to the export
channel: the argv tail and the working directory.

The one behavior load-bearing for #121's acceptance criterion (export to the
preset's *configured* ``export_path``) is that working directory: Godot resolves
a *relative* export output path against its own CWD (``FileAccess``/``DirAccess``
with no project globalization — verified against the engine source,
``platform/*/export/export_plugin.cpp``), so the runner must spawn Godot with
``cwd = <project>`` for the preset's relative configured path (e.g.
``build/game.x86_64``) to land at ``<project>/build/game.x86_64``, exactly as the
editor resolves it. These tests assert that spawn shape without a real engine.
"""

from pathlib import Path

import gda.runner as runner_mod
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
            # The primitive captures bytes (no text=True) and decodes UTF-8
            # itself, so the double mirrors that real subprocess contract (#33).
            stdout = b""
            stderr = b""
            returncode = 0

        return _Proc()


def test_export_runs_with_project_as_cwd(monkeypatch):
    # The configured export_path is relative and Godot resolves a relative output
    # path against its CWD, so the runner must spawn Godot with cwd = the project
    # for the artifact to land inside the project (the #121 acceptance behavior).
    rec = _RecordingRun()
    monkeypatch.setattr(runner_mod.subprocess, "run", rec)
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
    monkeypatch.setattr(runner_mod.subprocess, "run", rec)

    runner = SubprocessExportRunner(Path("/x/Godot"), project=None)
    runner.run("Linux/X11", "release", "/abs/out.x86_64")

    assert rec.kwargs is not None
    assert rec.kwargs.get("cwd") is None
    assert "--path" not in rec.cmd


def test_export_launch_failure_surfaces_through_the_typed_run_adapter(tmp_path):
    # A directory passed as --godot (e.g. the bundle "Godot.app") cannot be
    # exec'd; the failure surfaces through the typed run(preset, mode, output)
    # adapter as a synthesized launch failure, not a raw traceback — the export
    # runner delegates the launch handling to the shared primitive (#185).
    from gda.exit_codes import EXIT_NOT_FOUND
    from gda.runner import LaunchFailure

    runner = SubprocessExportRunner(tmp_path)

    result = runner.run("Linux/X11", "release", "out.x86_64")

    assert result.exit_code == EXIT_NOT_FOUND
    assert str(tmp_path) in result.stderr
    assert result.launch_failure is LaunchFailure.NOT_FOUND
