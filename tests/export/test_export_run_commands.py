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

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.commands.export import ProjectTreeMutations
from gda.runner import RunResult
from tests.support import (
    ENGINE_BANNER,
    FakeExportRunner,
    assert_no_pydantic_dump,
    inject_runner,
    invoke_cli,
    minimal_project,
    plain_text,
    sentinel,
    usage_error_text,
)

GET_RESULT = {
    "index": 0,
    "name": "Linux/X11",
    "platform": "Linux/X11",
    "runnable": True,
    "export_path": "build/game.x86_64",
    "templates_installed": True,
    "templates_version": "4.6.3.stable",
    # #840: where the engine looked, and (null here — no redirect) the host
    # directory holding templates it could not see.
    "templates_root": "/host/data/Godot/export_templates",
    "templates_root_host": None,
}


def _inject(monkeypatch, *, get=GET_RESULT, export=None):
    """Wire both seams: the sentinel runner for export-get, the export runner."""
    get_runner = inject_runner(
        monkeypatch,
        RunResult(stdout=ENGINE_BANNER + sentinel(get), stderr="", exit_code=0),
    )
    if export is None:
        export = RunResult(stdout="", stderr="", exit_code=0)
    export_runner = FakeExportRunner(export)
    monkeypatch.setattr(
        "gda.dispatch.make_export_runner", lambda binary, project=None: export_runner
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
    minimal_project(tmp_path)
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
    minimal_project(tmp_path)
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


def test_export_run_json_keeps_native_progress_on_stderr(monkeypatch, tmp_path):
    # issue #431: the native export phase gets a progress line, but JSON stdout
    # remains exactly one machine-readable result object.
    minimal_project(tmp_path)
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
    expected = {
        "preset": "Linux/X11",
        "platform": "Linux/X11",
        "mode": "release",
        "output_path": _configured_output(tmp_path),
        "created_dirs": [str(tmp_path / "build")],
        "warnings": [],
        # The fake export runner writes nothing, so the project-tree mutation
        # report (#839) is the empty one — and it rides the SAME single result
        # object this test is about.
        "project_tree_mutations": ProjectTreeMutations().model_dump(mode="json"),
    }
    assert result.stdout == json.dumps(expected, separators=(",", ":")) + "\n"
    assert plain_text(result.stderr) == (
        'gda: exporting preset "Linux/X11" (release) ...\n'
    )
    assert export_runner.calls == [
        ("Linux/X11", "release", _configured_output(tmp_path))
    ]


def test_export_run_default_mode_is_release(monkeypatch, tmp_path):
    # #170 adds --mode but keeps release the default: omitting --mode runs the
    # native --export-release invocation and reports mode == "release", the #121
    # behavior preserved.
    minimal_project(tmp_path)
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
    minimal_project(tmp_path)
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
    minimal_project(tmp_path)

    def _boom(*args, **kwargs):
        raise AssertionError("a rejected --mode must not spawn any engine")

    monkeypatch.setattr("gda.dispatch.make_runner", _boom)
    monkeypatch.setattr("gda.dispatch.make_export_runner", _boom)

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
    minimal_project(tmp_path)
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
    minimal_project(project)
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
    minimal_project(tmp_path)
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


@pytest.mark.parametrize(
    "destination",
    ["res://build/game.x86_64", "user://game.pck", "uid://bxxxx", "foo://game"],
)
def test_a_virtual_output_is_refused_on_argv(monkeypatch, tmp_path, destination):
    # #1003: `--output` takes a filesystem path only. Every `://` spelling is
    # refused by the params model (ADR-0015), so the argv channel answers with its
    # existing Click usage error at exit 2 — the same channel every other model
    # refusal reaches there — and neither engine seam is touched. No scheme is
    # named, resolved or special-cased: the message quotes the value it was given.
    minimal_project(tmp_path)
    get_runner, export_runner = _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--output",
            destination,
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    message = usage_error_text(result)
    assert "--output requires a filesystem path" in message
    assert destination in message
    assert_no_pydantic_dump(message)
    assert get_runner.calls == []
    assert export_runner.calls == []


def test_a_virtual_output_is_refused_through_params_json(monkeypatch, tmp_path):
    # The same model, the other input channel: `--params-json` surfaces the
    # identical refusal as the structured `invalid_params` envelope (exit 4), so an
    # agent branches on the code rather than on the argv channel's panel text.
    minimal_project(tmp_path)
    get_runner, export_runner = _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--params-json",
            '{"preset": "Linux/X11", "output": "res://build/game.x86_64"}',
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 4, result.stdout + result.stderr
    error = _error(result)
    assert error["code"] == "invalid_params"
    assert "--output requires a filesystem path" in error["message"]
    assert "res://build/game.x86_64" in error["message"]
    assert_no_pydantic_dump(error["message"])
    assert get_runner.calls == []
    assert export_runner.calls == []


def test_a_virtual_configured_export_path_is_refused_before_the_export(
    monkeypatch, tmp_path
):
    # #1003, the preset half: with no `--output`, a configured export_path that
    # carries a virtual scheme is not resolved and not handed to the engine. It is
    # the EXISTING export_path_unset preflight — no new code — whose message now
    # quotes the configured value and names the remedy.
    minimal_project(tmp_path)
    get = {**GET_RESULT, "export_path": "res://build/game.x86_64"}
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

    assert result.exit_code == 4, result.stdout + result.stderr
    error = _error(result)
    assert error["code"] == "export_path_unset"
    assert error["category"] == "operation"
    assert "res://build/game.x86_64" in error["message"]
    assert "--output" in error["message"]
    # Refused in the preflight: the native export was never spawned.
    assert export_runner.calls == []


def test_export_run_output_overrides_unset_configured_path(monkeypatch, tmp_path):
    # --output supplies a destination even when the preset's configured export_path
    # is empty: the export_path_unset preflight no longer fires (there IS a place to
    # write), and the export runs to the override.
    monkeypatch.chdir(tmp_path)
    minimal_project(tmp_path)
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
    minimal_project(tmp_path)
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
    minimal_project(tmp_path)
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
    minimal_project(tmp_path)
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
    minimal_project(tmp_path)
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
    minimal_project(tmp_path)
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
    minimal_project(tmp_path)
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
    minimal_project(tmp_path)
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))
    monkeypatch.setattr(
        "gda.dispatch.make_export_runner", lambda binary, project=None: export_runner
    )

    result, _ = invoke_cli(
        monkeypatch,
        ["export", "run", "--preset", "Nope", "--project", str(tmp_path), "--json"],
        stdout=sentinel(
            {"error": {"code": "export_preset_not_found", "message": "no such preset"}}
        ),
        exit_code=4,
    )

    assert result.exit_code == 4
    assert _error(result)["code"] == "export_preset_not_found"
    assert export_runner.calls == []


def test_export_run_empty_godot_is_binary_not_found(monkeypatch, tmp_path):
    # An empty `--godot ""` cannot be resolved. The refusal comes from the FIRST
    # phase: export get resolves the binary before its runner is built, so the
    # shared binary_not_found envelope (exit 127) is returned and neither seam
    # runs (#33).
    minimal_project(tmp_path)
    get_runner, export_runner = _inject(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--godot",
            "",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 127, result.stdout + result.stderr
    assert _error(result)["code"] == "binary_not_found"
    assert get_runner.calls == []
    assert export_runner.calls == []


def test_export_run_schema_emits_contract_without_engine(monkeypatch):
    # ADR-0004 hard gate: --schema emits the {input, output, error} contract
    # (plus the additive #230 `kind` and #233 `constraints`), spawns no Godot
    # (both seams would raise if touched), and never requires the operational
    # --preset.
    def _boom(*args, **kwargs):
        raise AssertionError("--schema must not spawn any engine")

    monkeypatch.setattr("gda.dispatch.make_runner", _boom)
    monkeypatch.setattr("gda.dispatch.make_export_runner", _boom)

    result = CliRunner().invoke(app, ["export", "run", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert set(schema) == {"input", "output", "error", "kind", "constraints", "argv"}
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
    described = schema["input"]["properties"]["output"]["description"]
    assert "invoker's current working directory" in described
    # #1003: the published input contract states the filesystem-only boundary.
    assert "filesystem path only" in described
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
    help_text = plain_text(result.stdout)
    normalized = " ".join(help_text.split())
    assert "--output" in help_text
    assert "invoker's current working directory" in normalized
    # #1003: and the page an agent reads before it picks a value says that the
    # override takes a filesystem path only.
    assert "filesystem path only" in normalized


def test_export_run_help_states_that_templates_follow_the_redirected_root(monkeypatch):
    # #840: the root `--user-data-root` help already warns that a release/debug
    # export under it finds no installed templates; nothing at the export itself
    # did. `export run --help` — the page an agent reads when it picks the
    # command — now states the same boundary.
    result = CliRunner().invoke(app, ["export", "run", "--help"])

    assert result.exit_code == 0
    normalized = " ".join(plain_text(result.stdout).split())
    assert "--user-data-root" in normalized
    assert "export templates" in normalized


def test_export_run_human_output_echoes_artifact(monkeypatch, tmp_path):
    # Without --json the command renders a human line naming the artifact.
    minimal_project(tmp_path)
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
