"""S3: gda export run success paths against fake runners (issue #121).

``export run`` is the first command that does NOT route through operations.gd:
the Godot export subsystem is editor-only C++, unreachable from a ``--script``
SceneTree run, so the actual export is a native ``--export-release`` invocation
(#121 fixes the mode to release; --mode/--output are deferred to #170). ``gda``
synthesizes the typed result from that subprocess's exit code, not from an
ADR-0002 sentinel.

The command runs in three steps, the engine-touching ones behind injectable seams:

1. ``export-get`` (the existing sentinel op) resolves the preset's
   details + configured ``export_path`` + template-install status — reusing
   #114's clean structured preset/project errors.
2. a structured preflight (on export-get's ``templates_installed`` and the
   configured ``export_path``) fails fast — export_templates_missing /
   export_path_unset — before any native export is spawned.
3. the native ``ExportRunner`` performs the export to the configured path; its
   raw ``{stdout, stderr, exit_code}`` is classified into success or a
   ``GdaError``.

These tests inject both seams with canned output, so the full
Typer → resolve → preflight → export → classify → JSON pipeline runs engine-free.
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


def test_export_run_json_reports_configured_path_and_exit_zero(monkeypatch, tmp_path):
    # export run exports the named preset to its CONFIGURED export_path (the #121
    # acceptance behavior) and reports the result (preset, platform, mode,
    # output_path, warnings) as typed JSON. The mode is always release in #121; an
    # agent's template-readiness check via export get is now also gda's preflight.
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
    # The reported output_path is the preset's configured export_path verbatim.
    assert data["output_path"] == "build/game.x86_64"
    assert data["warnings"] == []
    # The export ran for the preset, in release mode, to the CONFIGURED path
    # (no --output override — that flag is deferred to #170).
    assert export_runner.calls == [("Linux/X11", "release", "build/game.x86_64")]


def test_export_run_has_no_mode_or_output_flags(monkeypatch, tmp_path):
    # #121 trims the surface to the issue's ask: --mode and --output are deferred
    # to #170, so passing either is an unknown-option usage error (Typer exits 2),
    # and no engine is ever spawned.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise AssertionError("a rejected flag must not spawn any engine")

    monkeypatch.setattr("gda.cli._make_runner", _boom)
    monkeypatch.setattr("gda.cli._make_export_runner", _boom)

    for bad in (["--mode", "debug"], ["--output", "dist/game.x86_64"]):
        result = CliRunner().invoke(
            app,
            ["export", "run", "--preset", "Linux/X11", *bad, "--project", str(tmp_path)],
        )
        assert result.exit_code == 2, f"{bad}: {result.stdout + result.stderr}"


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


def test_export_run_missing_templates_is_structured_preflight(monkeypatch, tmp_path):
    # Templates readiness is a STRUCTURED preflight: export get reports
    # templates_installed=False, so gda fails with export_templates_missing BEFORE
    # spawning any native export — no stderr string-matching (ADR-0002), no native
    # run. The message names the templates_version the agent must install.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    get = {**GET_RESULT, "templates_installed": False, "templates_version": "4.6.3.stable"}
    _, export_runner = _inject(monkeypatch, get=get)

    result = CliRunner().invoke(
        app,
        ["export", "run", "--preset", "Linux/X11", "--project", str(tmp_path), "--json"],
    )

    assert result.exit_code == 4
    error = _error(result)
    assert error["code"] == "export_templates_missing"
    assert error["category"] == "operation"
    assert "4.6.3.stable" in error["message"]
    # The native export was never attempted — the preflight caught it first.
    assert export_runner.calls == []


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
    # A preset whose configured export_path is empty is the export_path_unset
    # failure — reported BEFORE the native export runs (no --output to fall back
    # on; that override is deferred to #170).
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
    # The input schema carries only the command's single param (--mode / --output
    # are deferred to #170); the output schema carries the result.
    assert "preset" in schema["input"]["properties"]
    assert "mode" not in schema["input"]["properties"]
    assert "output_path" not in schema["input"]["properties"]
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
