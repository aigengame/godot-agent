"""Direct tests for the ExportRun operation (issue #187).

``export run`` is the one command whose recipe — resolve the preset via
``export-get`` → structured preflight (effective destination + template
readiness + output parent dirs, ADR-0010) → native ``--export-<mode>`` run →
classify — used to live
inside the Typer function and could only be exercised through a CliRunner. The
recipe now lives in :func:`gda.commands.export.run_export_operation`, a PURE function
that RETURNS the outcome (never emits/exits).

These tests drive that function directly with the two injected seams — a
``FakeRunner`` for the ``export-get`` resolve and a ``FakeExportRunner`` for the
native export — so the phase sequencing and each preflight branch are asserted
without a real engine and without CliRunner. They are the recipe's own test
surface, complementary to the command tests in
``tests/export/test_export_run_commands.py`` (the zero-behavior-change safety net).
"""

import json
from pathlib import Path

import pytest

from gda.commands.export import (  # EXPORT_RUN_COMMAND: the single fully-bound descriptor (ADR-0023)
    EXPORT_GET_COMMAND,
    EXPORT_RUN_COMMAND,
    ExportRunMode,
    ExportRunResult,
    resolve_host_data_path,
    run_export_operation,
)
from gda.errors import Failure
from gda.execution import ExecutionKind
from gda.harness.install import install_harness, uninstall_harness
from gda.models import GdaErrorEnvelope
from gda.runner import RunResult
from tests.support import (
    ENGINE_BANNER,
    FakeExportRunner,
    FakeRunner,
    error_sentinel,
    sentinel,
)


# The host data directory gda hands the export-get op (#840), computed by the
# production default so the assertion follows the host it runs on.
_HOST_DATA_PATH = resolve_host_data_path()

# The two export-templates directories of #840: the one an isolated
# ``--user-data-root`` makes the engine check, and the host's standard one.
ISO_TEMPLATES_ROOT = "/iso/Library/Application Support/Godot/export_templates"
HOST_TEMPLATES_ROOT = "/home/dev/Library/Application Support/Godot/export_templates"


def test_export_run_command_is_the_native_export_channel():
    # ``export run`` is the one editor-only-export capability that does not run
    # through operations.gd, so it carries the EXPORT execution channel (ADR-0017
    # / ADR-0010); ``export get`` resolves via the sentinel pipeline and stays
    # HEADLESS. The dispatcher selects the native recipe by this kind.
    assert EXPORT_RUN_COMMAND.kind is ExecutionKind.EXPORT
    assert EXPORT_GET_COMMAND.kind is ExecutionKind.HEADLESS


GET_RESULT = {
    "index": 0,
    "name": "Linux/X11",
    "platform": "Linux/X11",
    "runnable": True,
    "export_path": "build/game.x86_64",
    "templates_installed": True,
    "templates_version": "4.6.3.stable",
    # #840: where the engine looked, and (null here) where a redirect hid them.
    "templates_root": HOST_TEMPLATES_ROOT,
    "templates_root_host": None,
}


def _get_runner(get=GET_RESULT) -> FakeRunner:
    """A FakeRunner that returns ``get`` wrapped in an ADR-0002 success sentinel."""
    return FakeRunner(
        RunResult(
            stdout=ENGINE_BANNER + sentinel(get),
            stderr="",
            exit_code=0,
        )
    )


def _run(
    *,
    get_runner: FakeRunner,
    export_runner: FakeExportRunner,
    preset: str = "Linux/X11",
    mode: ExportRunMode = ExportRunMode.RELEASE,
    output_override: str | None = None,
    project: Path = Path("/tmp/project"),
):
    """Invoke the operation with both seams pinned to the given fakes."""
    return run_export_operation(
        preset=preset,
        mode=mode,
        output_override=output_override,
        godot="/tmp/Godot",
        project=project,
        make_runner=lambda binary, project=None: get_runner,
        make_export_runner=lambda binary, project=None: export_runner,
    )


def test_success_returns_typed_result_to_configured_path(tmp_path):
    # The happy path: export-get resolves the preset, the preflight passes, the
    # native export exits clean, and the operation RETURNS the typed
    # ExportRunResult (not an emitted envelope) targeting the configured path.
    project = tmp_path / "project"
    project.mkdir()
    get_runner = _get_runner()
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(get_runner=get_runner, export_runner=export_runner, project=project)
    expected = str(project / "build" / "game.x86_64")

    assert isinstance(outcome, ExportRunResult)
    assert outcome.preset == "Linux/X11"
    assert outcome.platform == "Linux/X11"
    assert outcome.mode is ExportRunMode.RELEASE
    assert outcome.output_path == expected
    assert outcome.warnings == []
    # Phase sequencing: export-get ran first, then the native export to the
    # configured path keyed on the export-get-resolved name.
    assert get_runner.calls == [
        ("export-get", {"preset": "Linux/X11", "host_data_path": _HOST_DATA_PATH})
    ]
    assert export_runner.calls == [("Linux/X11", "release", expected)]


def test_export_run_reports_native_export_progress_on_stderr(capsys, tmp_path):
    # issue #431: after export-get resolves the preset, the long native export
    # phase gets its own human progress line on stderr, while the operation result
    # and native runner invocation stay unchanged.
    project = tmp_path / "project"
    project.mkdir()
    get_runner = _get_runner()
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(get_runner=get_runner, export_runner=export_runner, project=project)

    expected_output = str(project / "build" / "game.x86_64")
    assert capsys.readouterr().err == (
        'gda: exporting preset "Linux/X11" (release) ...\n'
    )
    assert outcome == ExportRunResult(
        preset="Linux/X11",
        platform="Linux/X11",
        mode=ExportRunMode.RELEASE,
        output_path=expected_output,
        created_dirs=[str(project / "build")],
        warnings=[],
    )
    assert get_runner.calls == [
        ("export-get", {"preset": "Linux/X11", "host_data_path": _HOST_DATA_PATH})
    ]
    assert export_runner.calls == [("Linux/X11", "release", expected_output)]


def test_configured_export_path_reports_absolute_project_path(tmp_path):
    # issue #403: a preset export_path keeps Godot's project-relative convention,
    # but the native invocation/result should carry the resolved absolute path so
    # consumers can locate the artifact without knowing the export runner cwd.
    project = tmp_path / "project"
    project.mkdir()
    get_runner = _get_runner()
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = run_export_operation(
        preset="Linux/X11",
        mode=ExportRunMode.RELEASE,
        output_override=None,
        godot="/tmp/Godot",
        project=project,
        make_runner=lambda binary, project=None: get_runner,
        make_export_runner=lambda binary, project=None: export_runner,
    )

    assert isinstance(outcome, ExportRunResult)
    expected = str(project / "build" / "game.x86_64")
    assert outcome.output_path == expected
    assert export_runner.calls == [("Linux/X11", "release", expected)]


def test_configured_export_path_with_relative_project_reports_absolute_path(
    monkeypatch, tmp_path
):
    # issue #403 also applies when --project was given as a relative path:
    # resolve_project_dir preserves that relative path, so export run must anchor
    # it to the invoker cwd before resolving the preset's export_path.
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(tmp_path)
    get_runner = _get_runner()
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = run_export_operation(
        preset="Linux/X11",
        mode=ExportRunMode.RELEASE,
        output_override=None,
        godot="/tmp/Godot",
        project=Path("project"),
        make_runner=lambda binary, project=None: get_runner,
        make_export_runner=lambda binary, project=None: export_runner,
    )

    expected = str(project / "build" / "game.x86_64")
    assert isinstance(outcome, ExportRunResult)
    assert outcome.output_path == expected
    assert export_runner.calls == [("Linux/X11", "release", expected)]


def test_phase1_failure_returns_the_failure():
    # An unknown preset surfaces export-get's clean export_preset_not_found,
    # RETURNED verbatim as a Failure (Phase 1 short-circuits) — and no native
    # export is attempted.
    get_runner = FakeRunner(
        RunResult(
            stdout=error_sentinel("export_preset_not_found", "no such preset"),
            stderr="",
            exit_code=4,
        )
    )
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(get_runner=get_runner, export_runner=export_runner, preset="Nope")

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_preset_not_found"
    assert export_runner.calls == []


def test_export_path_unset_when_no_override_and_empty_configured_path():
    # No --output override AND an empty configured export_path means there is
    # nowhere to write: the operation RETURNS export_path_unset before the native
    # run, named on the export-get-resolved preset name.
    get_runner = _get_runner({**GET_RESULT, "export_path": ""})
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(get_runner=get_runner, export_runner=export_runner)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_path_unset"
    assert "Linux/X11" in outcome.error.message
    assert export_runner.calls == []


def test_output_override_supplies_destination_when_configured_path_empty(tmp_path):
    # An --output override supplies a destination even when the configured
    # export_path is empty: the unset preflight does NOT fire and the export runs
    # to the override (override-wins-over-configured).
    get_runner = _get_runner({**GET_RESULT, "export_path": ""})
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))
    output = str(tmp_path / "dist" / "custom.x86_64")

    outcome = _run(
        get_runner=get_runner,
        export_runner=export_runner,
        output_override=output,
        project=tmp_path / "project",
    )

    assert isinstance(outcome, ExportRunResult)
    assert outcome.output_path == output
    assert export_runner.calls == [("Linux/X11", "release", output)]


def test_output_override_wins_over_configured_path(tmp_path):
    # When BOTH a configured export_path and an --output override exist, the
    # override wins, for both the native invocation and the reported output_path.
    get_runner = _get_runner()
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))
    output = str(tmp_path / "dist" / "custom.x86_64")

    outcome = _run(
        get_runner=get_runner,
        export_runner=export_runner,
        output_override=output,
        project=tmp_path / "project",
    )

    assert isinstance(outcome, ExportRunResult)
    assert outcome.output_path == output
    assert export_runner.calls == [("Linux/X11", "release", output)]


def test_output_override_parent_dirs_are_created_and_reported(tmp_path):
    # issue #402: the native export should not be allowed to fail with raw engine
    # prose just because the requested destination's parent dirs are missing.
    # The structured preflight creates them before the native run and reports
    # exactly what it created, outermost to innermost.
    get_runner = _get_runner({**GET_RESULT, "export_path": ""})
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))
    output = tmp_path / "dist" / "nested" / "custom.x86_64"

    outcome = _run(
        get_runner=get_runner,
        export_runner=export_runner,
        output_override=str(output),
        project=tmp_path / "project",
    )

    assert isinstance(outcome, ExportRunResult)
    assert output.parent.is_dir()
    assert outcome.created_dirs == [
        str(tmp_path / "dist"),
        str(tmp_path / "dist" / "nested"),
    ]
    assert export_runner.calls == [("Linux/X11", "release", str(output))]


def test_configured_export_path_parent_dirs_are_created_and_reported(tmp_path):
    # issue #402 composes with #403: the preset's configured relative export_path
    # is first resolved against the project directory, then that absolute parent
    # directory is created before the native export runs.
    project = tmp_path / "project"
    project.mkdir()
    get_runner = _get_runner()
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(
        get_runner=get_runner,
        export_runner=export_runner,
        project=project,
    )

    expected = project / "build" / "game.x86_64"
    assert isinstance(outcome, ExportRunResult)
    assert expected.parent.is_dir()
    assert outcome.output_path == str(expected)
    assert outcome.created_dirs == [str(project / "build")]
    assert export_runner.calls == [("Linux/X11", "release", str(expected))]


def test_configured_export_path_keeps_literal_tilde_project_relative(tmp_path):
    # A preset export_path is Godot configuration, not a CLI path: "~" remains a
    # literal project-relative path component instead of expanding to $HOME.
    project = tmp_path / "project"
    project.mkdir()
    get_runner = _get_runner({**GET_RESULT, "export_path": "~/build/game.zip"})
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(
        get_runner=get_runner,
        export_runner=export_runner,
        project=project,
    )

    expected = project / "~" / "build" / "game.zip"
    assert isinstance(outcome, ExportRunResult)
    assert outcome.output_path == str(expected)
    assert outcome.created_dirs == [str(project / "~"), str(project / "~" / "build")]
    assert export_runner.calls == [("Linux/X11", "release", str(expected))]


def test_uncreatable_output_parent_returns_export_failure_before_native_run(tmp_path):
    # If a path component that must be a directory is already a file, report a
    # typed operation error naming the output path instead of delegating to
    # Godot's locale/version-dependent stderr.
    get_runner = _get_runner({**GET_RESULT, "export_path": ""})
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))
    blocking_file = tmp_path / "dist"
    blocking_file.write_text("not a directory\n", encoding="utf-8")
    output = blocking_file / "custom.x86_64"

    outcome = _run(
        get_runner=get_runner,
        export_runner=export_runner,
        output_override=str(output),
        project=tmp_path / "project",
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_output_parent_failed"
    assert str(output) in outcome.error.message
    assert str(blocking_file) in outcome.error.message
    assert outcome.error.diagnostics == ""
    assert export_runner.calls == []


def test_templates_missing_for_release_and_debug():
    # release/debug produce a full platform binary and need the matching export
    # templates: when export-get reports templates_installed=False, the operation
    # RETURNS export_templates_missing BEFORE any native run, for each of them.
    for mode in (ExportRunMode.RELEASE, ExportRunMode.DEBUG):
        get_runner = _get_runner({**GET_RESULT, "templates_installed": False})
        export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

        outcome = _run(get_runner=get_runner, export_runner=export_runner, mode=mode)

        assert isinstance(outcome, Failure), mode
        assert outcome.error.code == "export_templates_missing", mode
        assert "4.6.3.stable" in outcome.error.message, mode
        # The preflight fired before any native run.
        assert export_runner.calls == [], mode


def test_templates_hidden_by_a_redirect_name_both_directories_and_the_remedies():
    # THE #840 CASE. Under `--user-data-root` the engine checks the redirected
    # directory, which has no templates, while the host's standard directory does
    # — so the templates are not missing, they are out of sight. The failure has to
    # say that at the point it happens: it names BOTH directories, states that
    # `--user-data-root` moved the lookup, and gives the two remedies (drop the
    # redirect, or `--mode pack`, which needs no templates).
    get_runner = _get_runner(
        {
            **GET_RESULT,
            "templates_installed": False,
            "templates_root": ISO_TEMPLATES_ROOT,
            "templates_root_host": HOST_TEMPLATES_ROOT,
        }
    )
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(get_runner=get_runner, export_runner=export_runner)

    assert isinstance(outcome, Failure)
    error = outcome.error
    assert error.code == "export_templates_missing"
    assert ISO_TEMPLATES_ROOT in error.message
    assert HOST_TEMPLATES_ROOT in error.message
    assert "--user-data-root" in error.message
    assert "--mode pack" in error.message
    # Not a near miss: `hint` is contractually one corrected invocation from the
    # curated table (CONTEXT.md `Near-miss hint`), and this is not one.
    assert error.hint is None
    # The same two directories ride the envelope as typed facts, so an agent
    # branches without parsing the prose (ADR-0004 amendment, #687).
    assert error.evidence is not None
    assert error.evidence.templates_root_checked == ISO_TEMPLATES_ROOT
    assert error.evidence.templates_root_host == HOST_TEMPLATES_ROOT
    # Still a preflight: nothing was exported.
    assert export_runner.calls == []


def test_templates_genuinely_absent_name_only_the_directory_checked():
    # The other shape, and the one an agent must be able to tell from the first:
    # with no redirect in play the host directory IS the directory checked, so
    # there is no second one to name and no redirect remedy to offer. The two
    # shapes are distinguished by the PRESENCE of `templates_root_host`, which is
    # omitted here rather than emitted as null.
    get_runner = _get_runner(
        {
            **GET_RESULT,
            "templates_installed": False,
            "templates_root": HOST_TEMPLATES_ROOT,
            "templates_root_host": None,
        }
    )
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(get_runner=get_runner, export_runner=export_runner)

    assert isinstance(outcome, Failure)
    error = outcome.error
    assert error.code == "export_templates_missing"
    assert HOST_TEMPLATES_ROOT in error.message
    assert "--user-data-root" not in error.message
    assert error.evidence is not None
    assert error.evidence.templates_root_checked == HOST_TEMPLATES_ROOT
    assert error.evidence.templates_root_host is None
    emitted = json.loads(
        GdaErrorEnvelope(error=error).model_dump_json(exclude_none=True)
    )
    assert emitted["error"]["evidence"] == {
        "templates_root_checked": HOST_TEMPLATES_ROOT
    }


def test_no_evidence_at_all_when_no_directory_was_reported():
    # The omitted-never-null rule applied to this producer: an engine reply that
    # names no directory (an older payload, a projectless oddity) leaves the
    # builder with nothing to type, and it emits NO `evidence` key rather than the
    # empty object `{}` — which would be a key that says nothing on a failure whose
    # envelope should look exactly as it did before #840.
    get_runner = _get_runner(
        {
            **GET_RESULT,
            "templates_installed": False,
            "templates_root": "",
            "templates_root_host": None,
        }
    )
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(get_runner=get_runner, export_runner=export_runner)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_templates_missing"
    assert outcome.error.evidence is None
    emitted = json.loads(
        GdaErrorEnvelope(error=outcome.error).model_dump_json(exclude_none=True)
    )
    assert "evidence" not in emitted["error"]


def test_pack_is_exempt_from_templates_preflight(tmp_path):
    # --mode pack produces project data only and needs NO platform templates: with
    # templates_installed=False, pack does NOT emit export_templates_missing — it
    # proceeds straight to the native runner.
    project = tmp_path / "project"
    project.mkdir()
    get_runner = _get_runner({**GET_RESULT, "templates_installed": False})
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(
        get_runner=get_runner,
        export_runner=export_runner,
        mode=ExportRunMode.PACK,
        project=project,
    )
    expected = str(project / "build" / "game.x86_64")

    assert isinstance(outcome, ExportRunResult)
    assert outcome.mode is ExportRunMode.PACK
    assert export_runner.calls == [("Linux/X11", "pack", expected)]


# --- Transactional harness strip (ADR-0018: a shipped build must never carry the
# dev-only harness). run_export_operation paired-uninstalls the harness before the
# native export and restores it after, so the gda export path is harness-free yet
# the dev project is left unchanged. These drive a real temp project so the on-disk
# strip/restore is observed, with the export runner pinned to a fake. ----------------


def _project_with_harness(tmp_path: Path) -> Path:
    """A minimal real project with the harness installed; returns the harness path."""
    (tmp_path / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="t"\n', encoding="utf-8"
    )
    install_harness(tmp_path)
    harness = tmp_path / "addons" / "gda_harness" / "gda_harness.gd"
    assert harness.exists()  # precondition: installed
    return harness


def _run_export_in(project: Path, export_runner) -> object:
    """Invoke run_export_operation against a real ``project`` with seams pinned."""
    output = project / "build" / "game.zip"
    return run_export_operation(
        preset="Linux/X11",
        mode=ExportRunMode.PACK,  # pack: no template preflight, runs the native seam
        output_override=str(output),
        godot="/tmp/Godot",
        project=project,
        make_runner=lambda binary, project=None: _get_runner(),
        make_export_runner=lambda binary, project=None: export_runner,
    )


def test_export_strips_harness_during_run_then_restores_byte_identical(tmp_path):
    # The harness is ABSENT on disk while the native export builds the artifact, and
    # the dev project is restored BYTE-IDENTICAL afterward (ADR-0028) — not merely
    # "an autoload named GdaHarness exists", but the exact prior project.godot and
    # harness bytes.
    harness = _project_with_harness(tmp_path)
    project_godot = tmp_path / "project.godot"
    godot_before = project_godot.read_bytes()
    harness_before = harness.read_bytes()
    seen = {}

    class _AssertingRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def run(self, preset, mode, output_path):
            seen["harness_present_during_export"] = harness.exists()
            self.calls.append((preset, mode, output_path))
            return RunResult(stdout="", stderr="", exit_code=0)

    runner = _AssertingRunner()
    outcome = _run_export_in(tmp_path, runner)

    assert isinstance(outcome, ExportRunResult)
    assert seen["harness_present_during_export"] is False  # stripped for the export
    # Byte-identical restore of BOTH files — the dev project is untouched.
    assert project_godot.read_bytes() == godot_before
    assert harness.read_bytes() == harness_before


def test_export_strips_and_restores_the_harness_uid_sidecar(tmp_path):
    # #654 pairs the strip with a WIDER uninstall (the engine-generated `.uid`
    # sidecar goes too). The snapshot reads its file list from the installer, so the
    # sidecar is captured and restored — otherwise every `gda export run` on a
    # dogfooded project would silently delete a tracked file and break ADR-0028's
    # "the dev project is left byte-identical".
    harness = _project_with_harness(tmp_path)
    sidecar = harness.with_name(f"{harness.name}.uid")
    sidecar.write_bytes(b"uid://bxxxxxxxxxxxxx\n")
    seen = {}

    class _AssertingRunner:
        def run(self, preset, mode, output_path):
            seen["sidecar_present_during_export"] = sidecar.exists()
            return RunResult(stdout="", stderr="", exit_code=0)

    outcome = _run_export_in(tmp_path, _AssertingRunner())

    assert isinstance(outcome, ExportRunResult)
    assert seen["sidecar_present_during_export"] is False  # stripped for the export
    assert sidecar.read_bytes() == b"uid://bxxxxxxxxxxxxx\n"  # and put back exactly


def test_export_restores_the_project_when_the_STRIP_itself_fails(tmp_path):
    # PR #680 review, claim 1. The strip is a MULTI-STEP mutation (autoload entry,
    # script, sidecar, directory), so it can fail part way through — and it used to
    # run BEFORE the try/finally, so a mid-strip failure skipped the restore and left
    # the dev project with a stripped project.godot and a deleted harness. Injecting
    # the reviewer's fault (the sidecar unlink raises) must now leave the project
    # byte-identical, with the error still surfaced to the caller.
    harness = _project_with_harness(tmp_path)
    sidecar = harness.with_name(f"{harness.name}.uid")
    sidecar.write_bytes(b"uid://bxxxxxxxxxxxxx\n")
    project_godot = tmp_path / "project.godot"
    godot_before = project_godot.read_bytes()
    harness_before = harness.read_bytes()

    real_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self.name.endswith(".uid"):
            raise OSError("injected: cannot unlink the sidecar")
        return real_unlink(self, *args, **kwargs)

    class _NeverRuns:
        def run(self, preset, mode, output_path):  # pragma: no cover - unreachable
            raise AssertionError("the export must not run after a failed strip")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "unlink", failing_unlink)
        with pytest.raises(OSError, match="cannot unlink the sidecar"):
            _run_export_in(tmp_path, _NeverRuns())

    # The finally covered the partial strip: both files are back as they were.
    assert project_godot.read_bytes() == godot_before
    assert harness.read_bytes() == harness_before
    assert sidecar.read_bytes() == b"uid://bxxxxxxxxxxxxx\n"


def test_export_restores_harness_even_when_native_run_raises(tmp_path):
    # A crash-safe finally: if the native export raises, the harness is still
    # restored (never left stripped by a mid-export failure on the gda path).
    harness = _project_with_harness(tmp_path)

    class _BoomRunner:
        def run(self, preset, mode, output_path):
            raise RuntimeError("export blew up")

    try:
        _run_export_in(tmp_path, _BoomRunner())
    except RuntimeError:
        pass
    assert harness.exists()  # restored despite the exception
    assert "GdaHarness" in (tmp_path / "project.godot").read_text(encoding="utf-8")


def test_export_is_a_noop_when_no_harness_installed(tmp_path):
    # With no harness installed, the strip is a harmless no-op: nothing is created,
    # and the export still runs to completion.
    (tmp_path / "project.godot").write_text(
        "config_version=5\n\n[application]\n", encoding="utf-8"
    )
    # Ensure a clean slate (idempotent): no harness present.
    uninstall_harness(tmp_path)
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run_export_in(tmp_path, export_runner)

    assert isinstance(outcome, ExportRunResult)
    assert not (tmp_path / "addons" / "gda_harness").exists()
    assert "GdaHarness" not in (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert export_runner.calls == [
        ("Linux/X11", "pack", str(tmp_path / "build" / "game.zip"))
    ]


def test_export_restores_a_stale_harness_body_unchanged_not_a_fresh_install(tmp_path):
    # ADR-0028 "byte-identical": a STALE installed harness (older version/body) must
    # be restored exactly as it was — NOT re-materialized to the current
    # HARNESS_VERSION. A fresh install_harness would rewrite it; the snapshot restore
    # preserves the prior bytes.
    harness = _project_with_harness(tmp_path)
    stale = b"# gda-harness-version: stale-old\nextends Node\n# old body\n"
    harness.write_bytes(stale)
    godot_before = (tmp_path / "project.godot").read_bytes()

    outcome = _run_export_in(
        tmp_path, FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))
    )

    assert isinstance(outcome, ExportRunResult)
    assert harness.read_bytes() == stale  # not bumped to the current version
    assert (tmp_path / "project.godot").read_bytes() == godot_before


def test_export_does_not_add_autoload_for_a_stray_harness_file(tmp_path):
    # The reviewer's repro: a project with ONLY a stray harness file and NO
    # [autoload] entry must come out of export with NO autoload added. The strip
    # removes the stray file (so it cannot ship); the byte-exact restore puts the
    # stray file back WITHOUT synthesizing an autoload the project never had.
    (tmp_path / "project.godot").write_text(
        "config_version=5\n\n[application]\n", encoding="utf-8"
    )
    stray = tmp_path / "addons" / "gda_harness" / "gda_harness.gd"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"extends Node\n# stray, no autoload entry\n")
    godot_before = (tmp_path / "project.godot").read_bytes()

    outcome = _run_export_in(
        tmp_path, FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))
    )

    assert isinstance(outcome, ExportRunResult)
    # No autoload synthesized — project.godot is byte-identical to before.
    assert (tmp_path / "project.godot").read_bytes() == godot_before
    assert "GdaHarness" not in (tmp_path / "project.godot").read_text(encoding="utf-8")
    # The stray file is restored (the project is left exactly as found).
    assert stray.read_bytes() == b"extends Node\n# stray, no autoload entry\n"


def test_native_nonzero_exit_returns_export_failed(tmp_path):
    # A non-zero native export with no recognized stderr signature is classified
    # as the generic export_failed Failure; the engine's stderr is preserved as
    # advisory diagnostics.
    project = tmp_path / "project"
    project.mkdir()
    get_runner = _get_runner()
    export_runner = FakeExportRunner(
        RunResult(
            stdout="", stderr="ERROR: could not write artifact to disk.\n", exit_code=1
        )
    )

    outcome = _run(get_runner=get_runner, export_runner=export_runner, project=project)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_failed"
    assert "could not write artifact" in outcome.error.diagnostics
