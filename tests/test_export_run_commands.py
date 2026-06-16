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


def test_export_run_mode_and_output_override(monkeypatch, tmp_path):
    # --mode selects the export flavor and --output overrides the preset's
    # configured path; both are echoed on the result and passed to the runner.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _, export_runner = _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "export", "run",
            "--preset", "Linux/X11",
            "--mode", "debug",
            "--output", "dist/game-debug.x86_64",
            "--project", str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["mode"] == "debug"
    assert data["output_path"] == "dist/game-debug.x86_64"
    assert export_runner.calls == [("Linux/X11", "debug", "dist/game-debug.x86_64")]


def test_export_run_surfaces_advisory_warnings(monkeypatch, tmp_path):
    # A clean export (exit 0) that still emits engine WARNING lines surfaces them
    # advisorily on the success result (ADR-0002: stderr is advisory for success),
    # not as a failure — the export succeeded.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _inject(
        monkeypatch,
        export=ExportRunOutput(
            stdout="",
            stderr=(
                "WARNING: No export template found at the expected icon path.\n"
                "WARNING: ResourceImporter: skipped one asset.\n"
            ),
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        ["export", "run", "--preset", "Linux/X11", "--project", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["warnings"] == [
        "No export template found at the expected icon path.",
        "ResourceImporter: skipped one asset.",
    ]


def _error(result):
    """Parse the GdaError envelope from a failed run's stdout."""
    return json.loads(result.stdout)["error"]


def test_export_run_missing_templates_is_structured(monkeypatch, tmp_path):
    # A non-zero export whose stderr carries the engine's stable
    # "due to configuration errors" prefix (the missing-templates / misconfigured
    # signature) surfaces as the distinct export_templates_missing code so an
    # agent installs templates rather than re-parsing prose.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _inject(
        monkeypatch,
        export=ExportRunOutput(
            stdout="",
            stderr=(
                'ERROR: Project export for preset "Linux/X11" failed due to '
                "configuration errors.\n"
            ),
            exit_code=1,
        ),
    )

    result = CliRunner().invoke(
        app,
        ["export", "run", "--preset", "Linux/X11", "--project", str(tmp_path), "--json"],
    )

    assert result.exit_code == 4
    error = _error(result)
    assert error["code"] == "export_templates_missing"
    assert error["category"] == "operation"


def test_export_run_generic_failure_is_structured(monkeypatch, tmp_path):
    # A non-zero export with no recognized stderr signature is the generic
    # export_failed code; the engine's stderr is preserved as diagnostics.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _inject(
        monkeypatch,
        export=ExportRunOutput(
            stdout="", stderr="ERROR: could not write artifact to disk.\n", exit_code=1
        ),
    )

    result = CliRunner().invoke(
        app,
        ["export", "run", "--preset", "Linux/X11", "--project", str(tmp_path), "--json"],
    )

    assert result.exit_code == 4
    error = _error(result)
    assert error["code"] == "export_failed"
    assert error["category"] == "operation"
    assert "could not write artifact" in error["diagnostics"]


def test_export_run_unset_path_is_structured(monkeypatch, tmp_path):
    # A preset whose configured export_path is empty, with no --output override,
    # is the export_path_unset failure — reported BEFORE the native export runs.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    get = {**GET_RESULT, "export_path": ""}
    _, export_runner = _inject(monkeypatch, get=get)

    result = CliRunner().invoke(
        app,
        ["export", "run", "--preset", "Linux/X11", "--project", str(tmp_path), "--json"],
    )

    assert result.exit_code == 4
    assert _error(result)["code"] == "export_path_unset"
    # The export was never attempted — the unset path is caught first.
    assert export_runner.calls == []


def test_export_run_unknown_preset_reuses_export_get_error(monkeypatch, tmp_path):
    # An unknown preset surfaces export-get's clean export_preset_not_found,
    # reused verbatim — and no native export is attempted.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    get_runner = FakeRunner(
        RunResult(
            stdout=sentinel(
                {"error": {"code": "export_preset_not_found", "message": "no such preset"}}
            ),
            stderr="",
            exit_code=4,
        )
    )
    monkeypatch.setattr(
        "gda.cli._make_runner", lambda binary, project=None: get_runner
    )
    export_runner = FakeExportRunner(ExportRunOutput(stdout="", stderr="", exit_code=0))
    monkeypatch.setattr(
        "gda.cli._make_export_runner", lambda binary, project=None: export_runner
    )

    result = CliRunner().invoke(
        app,
        ["export", "run", "--preset", "Nope", "--project", str(tmp_path), "--json"],
    )

    assert result.exit_code == 4
    assert _error(result)["code"] == "export_preset_not_found"
    assert export_runner.calls == []


def test_export_run_schema_emits_contract_without_engine(monkeypatch):
    # ADR-0004 hard gate: --schema emits the {input, output, error} contract,
    # spawns no Godot (both seams would raise if touched), and never requires the
    # operational --preset.
    def _boom(*args, **kwargs):
        raise AssertionError("--schema must not spawn any engine")

    monkeypatch.setattr("gda.cli._make_runner", _boom)
    monkeypatch.setattr("gda.cli._make_export_runner", _boom)

    result = CliRunner().invoke(app, ["export", "run", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert set(schema) == {"input", "output", "error"}
    # The input schema carries the command's params; the output schema the result.
    assert "preset" in schema["input"]["properties"]
    assert "mode" in schema["input"]["properties"]
    assert "output_path" in schema["output"]["properties"]
    assert "warnings" in schema["output"]["properties"]


def test_export_run_human_output_echoes_artifact(monkeypatch, tmp_path):
    # Without --json the command renders a human line naming the artifact.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        ["export", "run", "--preset", "Linux/X11", "--project", str(tmp_path)],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "exported Linux/X11 (Linux/X11, release) -> build/game.x86_64" in result.stdout
