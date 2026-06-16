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
from gda.exit_codes import EXIT_NOT_FOUND
from gda.runner import LaunchFailure


class _RecordingRun:
    """A ``subprocess.run`` double recording the call and returning a clean exit."""

    def __init__(self) -> None:
        self.cmd: list[str] | None = None
        self.kwargs: dict | None = None

    def __call__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs

        class _Proc:
            # The runner captures bytes (no text=True) and decodes UTF-8 itself,
            # so the double mirrors that real subprocess contract (#33).
            stdout = b""
            stderr = b""
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


def test_export_directory_binary_maps_to_not_found_not_traceback(tmp_path):
    # A directory passed as --godot (e.g. the bundle "Godot.app") cannot be
    # exec'd; the native export runner must catch the OSError and synthesize a
    # launch failure rather than leak a raw traceback — mirroring the sentinel
    # runner so both runners close the same launch-failure surface (#33).
    runner = SubprocessExportRunner(tmp_path)

    result = runner.run("Linux/X11", "release", "out.x86_64")

    assert result.exit_code == EXIT_NOT_FOUND
    assert str(tmp_path) in result.stderr
    assert result.stdout == ""
    assert result.launch_failure is LaunchFailure.NOT_FOUND


def test_export_non_executable_file_binary_maps_to_not_found_not_traceback(tmp_path):
    # A plain, non-executable file passed as --godot cannot be exec'd; the
    # PermissionError must become a launch failure, not a traceback (#33).
    not_exec = tmp_path / "notgodot.txt"
    not_exec.write_text("i am not an engine")
    runner = SubprocessExportRunner(not_exec)

    result = runner.run("Linux/X11", "release", "out.x86_64")

    assert result.exit_code == EXIT_NOT_FOUND
    assert str(not_exec) in result.stderr
    assert result.stdout == ""
    assert result.launch_failure is LaunchFailure.NOT_FOUND


def test_export_output_is_decoded_as_utf8_regardless_of_host_locale(monkeypatch):
    # Like the sentinel runner, the native export channel must capture bytes and
    # decode UTF-8 explicitly so non-ASCII engine output round-trips regardless
    # of host locale, instead of locale-decoding via text=True (#33).
    stdout_bytes = "エクスポート完了\n".encode("utf-8")
    stderr_bytes = "警告: テンプレート\n".encode("utf-8")

    def fake_run(cmd, **kwargs):
        # The fix drops text=True and captures bytes; assert that contract here
        # so the test fails loudly if decoding silently reverts to locale text.
        assert kwargs.get("text") in (None, False)

        class _Proc:
            stdout = stdout_bytes
            stderr = stderr_bytes
            returncode = 0

        return _Proc()

    monkeypatch.setattr(export_runner_mod.subprocess, "run", fake_run)
    runner = SubprocessExportRunner(Path("/any/Godot"))

    result = runner.run("Linux/X11", "release", "out.x86_64")

    assert "エクスポート完了" in result.stdout
    assert "警告: テンプレート" in result.stderr
