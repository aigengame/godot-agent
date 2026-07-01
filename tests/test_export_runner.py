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
    assert rec.cmd is not None
    assert "--path" in rec.cmd and str(project) in rec.cmd
    assert rec.cmd[-3:] == ["--export-release", "Linux/X11", "build/game.x86_64"]


def _path_arg(cmd: list[str]) -> str:
    """The value following ``--path`` in a spawned argv."""
    return cmd[cmd.index("--path") + 1]


def test_relative_project_is_absolutized_so_cwd_and_path_agree(monkeypatch):
    # Regression for #344: this channel spawns with cwd = <project>, so a RELATIVE
    # --project passed as --path verbatim would be re-resolved by the engine
    # against the child CWD (<project>/<project>) — project.godot not found →
    # empty export_failed. The runner must absolutize the project so --path and
    # cwd name the SAME absolute directory (reaching the resolution an absolute
    # --project reaches).
    rec = _RecordingRun()
    monkeypatch.setattr(runner_mod.subprocess, "run", rec)
    relative = Path("relproj")
    expected = str(relative.absolute())

    runner = SubprocessExportRunner(Path("/x/Godot"), project=relative)
    runner.run("Linux/X11", "release", "build/game.x86_64")

    assert rec.kwargs is not None and rec.cmd is not None
    # --path carries the ABSOLUTE project, not the relative string the engine
    # would mis-resolve against the child cwd.
    passed_path = _path_arg(rec.cmd)
    assert Path(passed_path).is_absolute()
    assert passed_path == expected
    # cwd and --path name the SAME directory — the invariant the bug violated.
    assert rec.kwargs.get("cwd") == passed_path == expected


def test_relative_and_absolute_project_reach_the_same_resolution(monkeypatch, tmp_path):
    # The deterministic core of #344, independent of export templates: a RELATIVE
    # --project and the EQUIVALENT absolute --project produce the identical spawn
    # (same cwd, same --path). Building the absolute path from Path.cwd() — the
    # same base .absolute() uses — keeps the two naming one directory regardless
    # of any symlink in the tmp prefix.
    monkeypatch.chdir(tmp_path)
    abs_project = Path.cwd() / "proj"
    abs_project.mkdir()

    def _spawn(project: Path) -> tuple[list[str], dict]:
        rec = _RecordingRun()
        monkeypatch.setattr(runner_mod.subprocess, "run", rec)
        SubprocessExportRunner(Path("/x/Godot"), project=project).run(
            "Linux/X11", "release", "build/game.x86_64"
        )
        assert rec.cmd is not None and rec.kwargs is not None
        return rec.cmd, rec.kwargs

    rel_cmd, rel_kwargs = _spawn(Path("proj"))
    abs_cmd, abs_kwargs = _spawn(abs_project)

    # Relative resolves to the same absolute cwd and --path as absolute does.
    assert rel_kwargs["cwd"] == abs_kwargs["cwd"] == str(abs_project)
    assert _path_arg(rel_cmd) == _path_arg(abs_cmd) == str(abs_project)
    assert Path(rel_kwargs["cwd"]).is_absolute()


def test_export_without_project_passes_no_cwd(monkeypatch):
    # Projectless runs (no resolved project) spawn with the default cwd — there is
    # no project root to resolve a relative path against.
    rec = _RecordingRun()
    monkeypatch.setattr(runner_mod.subprocess, "run", rec)

    runner = SubprocessExportRunner(Path("/x/Godot"), project=None)
    runner.run("Linux/X11", "release", "/abs/out.x86_64")

    assert rec.kwargs is not None
    assert rec.kwargs.get("cwd") is None
    assert rec.cmd is not None
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


def test_export_timeout_keeps_the_export_worded_diagnostic(monkeypatch):
    # The export channel passes timeout_label="Godot export" to the shared
    # primitive so its timeout stderr stays byte-compatible with the pre-#185
    # wording. This stderr is what the classifier carries into the public
    # GdaError.diagnostics, so the wording is part of `export run --json` (#185
    # review). The shared launch handling itself is tested in test_launch.py.
    import subprocess

    from gda.exit_codes import EXIT_TIMEOUT
    from gda.runner import LaunchFailure

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)

    runner = SubprocessExportRunner(Path("/x/Godot"), timeout=600.0)
    result = runner.run("Linux/X11", "release", "out.x86_64")

    assert result.exit_code == EXIT_TIMEOUT
    assert result.stderr == "gda: Godot export timed out after 600.0s\n"
    assert result.launch_failure is LaunchFailure.TIMEOUT
