"""S3: gda export run success paths against fake runners (issue #121).

``export run`` is the first command that does NOT route through operations.gd:
the Godot export subsystem is editor-only C++, unreachable from a ``--script``
SceneTree run, so the actual export is a native ``--export-release`` /
``--export-debug`` / ``--export-pack`` invocation. ``gda`` synthesizes the typed
result from that subprocess's exit code + stderr, not from an ADR-0002 sentinel.

The command runs in two phases, each behind its own injectable seam:

1. ``export-get`` (the existing sentinel op) resolves the preset's
   details + configured ``export_path`` + template-install status — reusing
   #114's clean structured preset/project errors.
2. the native ``ExportRunner`` performs the export to that path; its raw
   ``{stdout, stderr, exit_code}`` is classified into success or a ``GdaError``.

These tests inject both seams with canned output, so the full
Typer → resolve → export → classify → JSON pipeline runs engine-free.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.export_runner import ExportRunOutput
from gda.runner import RunResult
from tests.support import (
    FakeExportRunner,
    FakeRunner,
    sentinel,
)

GET_RESULT = {
    "index": 0,
    "name": "Linux/X11",
    "platform": "Linux/X11",
    "runnable": True,
    "export_path": "build/game.x86_64",
    "templates_installed": True,
    "templates_version": "4.6.3.stable",
}


def _inject(monkeypatch, *, get=GET_RESULT, export=None):
    """Wire both seams: the sentinel runner for export-get, the export runner."""
    get_runner = FakeRunner(
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n" + sentinel(get),
            stderr="",
            exit_code=0,
        )
    )
    monkeypatch.setattr("gda.cli._make_runner", lambda binary, project=None: get_runner)
    if export is None:
        export = ExportRunOutput(stdout="", stderr="", exit_code=0)
    export_runner = FakeExportRunner(export)
    monkeypatch.setattr(
        "gda.cli._make_export_runner", lambda binary, project=None: export_runner
    )
    return get_runner, export_runner


def test_export_run_json_reports_output_path_and_exit_zero(monkeypatch, tmp_path):
    # export run exports the named preset to its configured output path and
    # reports the result (preset, platform, mode, output_path, warnings) as typed
    # JSON. The default mode is release (a full platform export), matching the
    # template-readiness check an agent makes via export get first.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _, export_runner = _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        ["export", "run", "--preset", "Linux/X11", "--project", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["preset"] == "Linux/X11"
    assert data["platform"] == "Linux/X11"
    assert data["mode"] == "release"
    assert data["output_path"] == "build/game.x86_64"
    assert data["warnings"] == []
    # The export ran for the preset, in release mode, to the configured path.
    assert export_runner.calls == [("Linux/X11", "release", "build/game.x86_64")]
