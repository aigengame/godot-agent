"""S3: gda export run success paths against fake runners (issue #121).

``export run`` is the first command that does NOT route through operations.gd:
the Godot export subsystem is editor-only C++, unreachable from a ``--script``
SceneTree run, so the actual export is a native ``--export-release`` invocation
(#121), selectable by ``--mode`` (#170). ``--output`` overrides the preset path
and resolves relative filesystem paths against the invoker cwd (#403). ``gda``
synthesizes the typed result from that subprocess's exit code, not from an
ADR-0002 sentinel, after creating missing output parent dirs (#402).

The command runs in three steps, the engine-touching ones behind injectable seams:

1. ``export-get`` (the existing sentinel op) resolves the preset's
   details + configured ``export_path`` + template-install status — reusing
   #114's clean structured preset/project errors.
2. a structured preflight (on export-get's ``templates_installed`` and the
   configured ``export_path``) fails fast — export_templates_missing /
   export_path_unset — before any native export is spawned.
3. missing output parent directories are created and reported; then the native
   ``ExportRunner`` performs the export to the effective path; its
   raw ``{stdout, stderr, exit_code}`` is classified into success or a
   ``GdaError``.

These tests inject both seams with canned output, so the full
Typer → resolve → preflight → export → classify → JSON pipeline runs engine-free.
"""

import json
from pathlib import Path

from typer.testing import CliRunner

from gda.cli import app
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
        export = RunResult(stdout="", stderr="", exit_code=0)
    export_runner = FakeExportRunner(export)
    monkeypatch.setattr(
        "gda.cli._make_export_runner", lambda binary, project=None: export_runner
    )
    return get_runner, export_runner


def _configured_output(project: Path) -> str:
    return str(project / "build" / "game.x86_64")


def _cwd_output(*parts: str) -> str:
    return str(Path.cwd().joinpath(*parts))


def test_export_run_params_json_drives_the_native_export_runner(monkeypatch, tmp_path):
    # export run is the native-export recipe (run_export_operation), NOT the
    # sentinel pipeline. --params-json (ADR-0015) must drive that SAME recipe, so
    # the export runner is actually invoked — a regression guard against the
    # generic dispatch hook routing it through the wrong (sentinel) path.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _, export_runner = _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--params-json",
            '{"preset": "Linux/X11"}',
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["mode"] == "release"
    assert data["created_dirs"] == [str(tmp_path / "build")]
    assert export_runner.calls == [
        ("Linux/X11", "release", _configured_output(tmp_path))
    ]


def test_export_run_json_reports_configured_path_and_exit_zero(monkeypatch, tmp_path):
    # export run exports the named preset to its CONFIGURED export_path (the #121
    # acceptance behavior) and reports the result (preset, platform, mode,
    # output_path, warnings) as typed JSON. The mode is always release in #121; an
    # agent's template-readiness check via export get is now also gda's preflight.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _, export_runner = _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["preset"] == "Linux/X11"
    assert data["platform"] == "Linux/X11"
    assert data["mode"] == "release"
    # The reported output_path is the preset's configured export_path resolved
    # against the project directory.
    assert data["output_path"] == _configured_output(tmp_path)
    assert data["created_dirs"] == [str(tmp_path / "build")]
    assert data["warnings"] == []
    # The export ran for the preset, in release mode, to the resolved configured path.
    assert export_runner.calls == [
        ("Linux/X11", "release", _configured_output(tmp_path))
    ]


def test_export_run_default_mode_is_release(monkeypatch, tmp_path):
    # #170 adds --mode but keeps release the default: omitting --mode runs the
    # native --export-release invocation and reports mode == "release", the #121
    # behavior preserved.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _, export_runner = _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["mode"] == "release"
    assert export_runner.calls == [
        ("Linux/X11", "release", _configured_output(tmp_path))
    ]


def test_export_run_mode_selects_export_flavor(monkeypatch, tmp_path):
    # --mode (issue #170) selects the export flavor, reflected in BOTH the native
    # invocation (the mode string the runner is asked to export) and the result's
    # `mode` field. Each of debug/pack flows end-to-end through the pipeline.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    for mode in ("debug", "pack"):
        _, export_runner = _inject(monkeypatch)

        result = CliRunner().invoke(
            app,
            [
                "export",
                "run",
                "--preset",
                "Linux/X11",
                "--mode",
                mode,
                "--project",
                str(tmp_path),
                "--json",
            ],
        )

        assert result.exit_code == 0, f"{mode}: {result.stdout + result.stderr}"
        data = json.loads(result.stdout)
        assert data["mode"] == mode
        # The native export was driven with the selected mode, to the configured path.
        assert export_runner.calls == [
            ("Linux/X11", mode, _configured_output(tmp_path))
        ]


def test_export_run_rejects_unknown_mode(monkeypatch, tmp_path):
    # --mode is a closed set (release/debug/pack); an unrecognized value is a
    # Typer usage error (exit 2) and spawns no engine.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise AssertionError("a rejected --mode must not spawn any engine")

    monkeypatch.setattr("gda.cli._make_runner", _boom)
    monkeypatch.setattr("gda.cli._make_export_runner", _boom)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--mode",
            "nonsense",
            "--project",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr


def test_export_run_output_overrides_configured_path(monkeypatch, tmp_path):
    # --output (issue #170) overrides the preset's configured export_path: the
    # native export is driven to the override, NOT the configured "build/game.x86_64",
    # and the result's output_path reports the effective destination.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _, export_runner = _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--output",
            "dist/custom.x86_64",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    # The reported output_path is the override, resolved against the invoker cwd.
    expected = _cwd_output("dist", "custom.x86_64")
    assert data["output_path"] == expected
    assert data["created_dirs"] == [str(tmp_path / "dist")]
    assert data["mode"] == "release"
    assert export_runner.calls == [("Linux/X11", "release", expected)]


def test_export_run_relative_output_resolves_against_invoker_cwd(monkeypatch, tmp_path):
    # issue #403: export run's native process runs with cwd=<project>, so a
    # relative --output must be absolutized against the invoker cwd before it
    # reaches Godot. The JSON result reports the same absolute artifact path.
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    invoker_cwd = tmp_path / "caller"
    invoker_cwd.mkdir()
    monkeypatch.chdir(invoker_cwd)
    _, export_runner = _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--output",
            "./dist/custom.x86_64",
            "--project",
            str(project),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    expected = str(invoker_cwd / "dist" / "custom.x86_64")
    data = json.loads(result.stdout)
    assert data["output_path"] == expected
    assert data["created_dirs"] == [str(invoker_cwd / "dist")]
    assert export_runner.calls == [("Linux/X11", "release", expected)]


def test_export_run_output_expands_leading_tilde(monkeypatch, tmp_path):
    # ADR-0006: --output is a filesystem path normalized ONCE at the CLI layer, so
    # a literal `~` is expanded to the user's home before it reaches the runner —
    # the artifact lands in $HOME, not a literal "~" directory.
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _, export_runner = _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--output",
            "~/builds/game.x86_64",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    expanded = str(home / "builds/game.x86_64")
    data = json.loads(result.stdout)
    # Both the native invocation and the reported destination carry the expanded path.
    assert data["output_path"] == expanded
    assert data["created_dirs"] == [str(home), str(home / "builds")]
    assert export_runner.calls == [("Linux/X11", "release", expanded)]


def test_export_run_output_overrides_unset_configured_path(monkeypatch, tmp_path):
    # --output supplies a destination even when the preset's configured export_path
    # is empty: the export_path_unset preflight no longer fires (there IS a place to
    # write), and the export runs to the override.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    get = {**GET_RESULT, "export_path": ""}
    _, export_runner = _inject(monkeypatch, get=get)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--output",
            "dist/custom.x86_64",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    expected = _cwd_output("dist", "custom.x86_64")
    assert data["output_path"] == expected
    assert data["created_dirs"] == [str(tmp_path / "dist")]
    assert export_runner.calls == [("Linux/X11", "release", expected)]


def test_export_run_surfaces_advisory_warnings(monkeypatch, tmp_path):
    # A clean export (exit 0) that still emits engine WARNING lines surfaces them
    # advisorily on the success result (ADR-0002: stderr is advisory for success),
    # not as a failure — the export succeeded.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _inject(
        monkeypatch,
        export=RunResult(
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
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--project",
            str(tmp_path),
            "--json",
        ],
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
    get = {
        **GET_RESULT,
        "templates_installed": False,
        "templates_version": "4.6.3.stable",
    }
    _, export_runner = _inject(monkeypatch, get=get)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 4
    error = _error(result)
    assert error["code"] == "export_templates_missing"
    assert error["category"] == "operation"
    assert "4.6.3.stable" in error["message"]
    # The native export was never attempted — the preflight caught it first.
    assert export_runner.calls == []


def test_export_run_pack_skips_template_preflight_when_missing(monkeypatch, tmp_path):
    # #170: --mode pack produces project data only (Godot's native --export-pack)
    # and needs NO platform export templates. So when export get reports
    # templates_installed=False, pack must NOT emit export_templates_missing — it
    # proceeds straight to the native runner. (release/debug, which DO need
    # templates, still fail fast — asserted by the parametric test below.)
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    get = {
        **GET_RESULT,
        "templates_installed": False,
        "templates_version": "4.6.3.stable",
    }
    _, export_runner = _inject(monkeypatch, get=get)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--mode",
            "pack",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["mode"] == "pack"
    # The preflight was skipped for pack: the native export actually ran.
    assert export_runner.calls == [("Linux/X11", "pack", _configured_output(tmp_path))]


def test_export_run_release_debug_still_require_templates_when_missing(
    monkeypatch, tmp_path
):
    # The counterpart guard: release and debug DO need platform templates, so with
    # templates_installed=False they still fail fast with export_templates_missing
    # before any native run — only pack is exempt (#170).
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    for mode in ("release", "debug"):
        get = {
            **GET_RESULT,
            "templates_installed": False,
            "templates_version": "4.6.3.stable",
        }
        _, export_runner = _inject(monkeypatch, get=get)

        result = CliRunner().invoke(
            app,
            [
                "export",
                "run",
                "--preset",
                "Linux/X11",
                "--mode",
                mode,
                "--project",
                str(tmp_path),
                "--json",
            ],
        )

        assert result.exit_code == 4, f"{mode}: {result.stdout + result.stderr}"
        error = _error(result)
        assert error["code"] == "export_templates_missing", f"{mode}: {result.stdout}"
        # The preflight fired before any native run.
        assert export_runner.calls == [], mode


def test_export_run_generic_failure_is_structured(monkeypatch, tmp_path):
    # A non-zero export with no recognized stderr signature is the generic
    # export_failed code; the engine's stderr is preserved as diagnostics.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _inject(
        monkeypatch,
        export=RunResult(
            stdout="", stderr="ERROR: could not write artifact to disk.\n", exit_code=1
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--project",
            str(tmp_path),
            "--json",
        ],
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
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--project",
            str(tmp_path),
            "--json",
        ],
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
                {
                    "error": {
                        "code": "export_preset_not_found",
                        "message": "no such preset",
                    }
                }
            ),
            stderr="",
            exit_code=4,
        )
    )
    monkeypatch.setattr("gda.cli._make_runner", lambda binary, project=None: get_runner)
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))
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
    # ADR-0004 hard gate: --schema emits the {input, output, error} contract
    # (plus the additive #230 `kind` and #233 `constraints`), spawns no Godot
    # (both seams would raise if touched), and never requires the operational
    # --preset.
    def _boom(*args, **kwargs):
        raise AssertionError("--schema must not spawn any engine")

    monkeypatch.setattr("gda.cli._make_runner", _boom)
    monkeypatch.setattr("gda.cli._make_export_runner", _boom)

    result = CliRunner().invoke(app, ["export", "run", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert set(schema) == {"input", "output", "error", "kind", "constraints"}
    # export run is the one EXPORT-channel command (issue #230); its sibling
    # read-only export commands stay HEADLESS.
    assert schema["kind"] == "export"
    # export run is not a live-stack command, so it carries no constraint (#233).
    assert schema["constraints"] is None
    # The input schema carries the command's params, now including the #170
    # --mode and --output overrides; the output schema carries the result.
    assert "preset" in schema["input"]["properties"]
    assert "mode" in schema["input"]["properties"]
    assert "output" in schema["input"]["properties"]
    assert (
        "invoker's current working directory"
        in schema["input"]["properties"]["output"]["description"]
    )
    assert "output_path" in schema["output"]["properties"]
    assert (
        "resolved absolute path"
        in schema["output"]["properties"]["output_path"]["description"]
    )
    assert "created_dirs" in schema["output"]["properties"]
    assert "warnings" in schema["output"]["properties"]


def test_export_run_help_documents_output_resolution():
    result = CliRunner().invoke(app, ["export", "run", "--help"])

    assert result.exit_code == 0
    assert "--output" in result.stdout
    assert "invoker's current working directory" in result.stdout


def test_export_run_human_output_echoes_artifact(monkeypatch, tmp_path):
    # Without --json the command renders a human line naming the artifact.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        ["export", "run", "--preset", "Linux/X11", "--project", str(tmp_path)],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert (
        f"exported Linux/X11 (Linux/X11, release) -> {_configured_output(tmp_path)}"
        in result.stdout
    )
