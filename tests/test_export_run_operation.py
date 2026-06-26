"""Direct tests for the ExportRun operation (issue #187).

``export run`` is the one command whose recipe — resolve the preset via
``export-get`` → structured preflight (effective destination + template
readiness, ADR-0010) → native ``--export-<mode>`` run → classify — used to live
inside the Typer function and could only be exercised through a CliRunner. The
recipe now lives in :func:`gda.export_run.run_export_operation`, a PURE function
that RETURNS the outcome (never emits/exits).

These tests drive that function directly with the two injected seams — a
``FakeRunner`` for the ``export-get`` resolve and a ``FakeExportRunner`` for the
native export — so the phase sequencing and each preflight branch are asserted
without a real engine and without CliRunner. They are the recipe's own test
surface, complementary to the command tests in
``tests/test_export_run_commands.py`` (the zero-behavior-change safety net).
"""

from pathlib import Path

from gda.cli import EXPORT_RUN_COMMAND  # the single fully-bound descriptor (ADR-0023)
from gda.errors import Failure
from gda.execution import ExecutionKind
from gda.export_run import (
    EXPORT_GET_COMMAND,
    run_export_operation,
)
from gda.harness.install import install_harness, uninstall_harness
from gda.models import ExportRunMode, ExportRunResult
from gda.runner import RunResult
from tests.support import FakeExportRunner, FakeRunner, error_sentinel, sentinel


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
}


def _get_runner(get=GET_RESULT) -> FakeRunner:
    """A FakeRunner that returns ``get`` wrapped in an ADR-0002 success sentinel."""
    return FakeRunner(
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n" + sentinel(get),
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
):
    """Invoke the operation with both seams pinned to the given fakes."""
    return run_export_operation(
        preset=preset,
        mode=mode,
        output_override=output_override,
        godot="/tmp/Godot",
        project=Path("/tmp/project"),
        make_runner=lambda binary, project=None: get_runner,
        make_export_runner=lambda binary, project=None: export_runner,
    )


def test_success_returns_typed_result_to_configured_path():
    # The happy path: export-get resolves the preset, the preflight passes, the
    # native export exits clean, and the operation RETURNS the typed
    # ExportRunResult (not an emitted envelope) targeting the configured path.
    get_runner = _get_runner()
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(get_runner=get_runner, export_runner=export_runner)

    assert isinstance(outcome, ExportRunResult)
    assert outcome.preset == "Linux/X11"
    assert outcome.platform == "Linux/X11"
    assert outcome.mode is ExportRunMode.RELEASE
    assert outcome.output_path == "build/game.x86_64"
    assert outcome.warnings == []
    # Phase sequencing: export-get ran first, then the native export to the
    # configured path keyed on the export-get-resolved name.
    assert get_runner.calls == [("export-get", {"preset": "Linux/X11"})]
    assert export_runner.calls == [("Linux/X11", "release", "build/game.x86_64")]


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

    outcome = _run(
        get_runner=get_runner, export_runner=export_runner, preset="Nope"
    )

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


def test_output_override_supplies_destination_when_configured_path_empty():
    # An --output override supplies a destination even when the configured
    # export_path is empty: the unset preflight does NOT fire and the export runs
    # to the override (override-wins-over-configured).
    get_runner = _get_runner({**GET_RESULT, "export_path": ""})
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(
        get_runner=get_runner,
        export_runner=export_runner,
        output_override="dist/custom.x86_64",
    )

    assert isinstance(outcome, ExportRunResult)
    assert outcome.output_path == "dist/custom.x86_64"
    assert export_runner.calls == [("Linux/X11", "release", "dist/custom.x86_64")]


def test_output_override_wins_over_configured_path():
    # When BOTH a configured export_path and an --output override exist, the
    # override wins, for both the native invocation and the reported output_path.
    get_runner = _get_runner()
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(
        get_runner=get_runner,
        export_runner=export_runner,
        output_override="dist/custom.x86_64",
    )

    assert isinstance(outcome, ExportRunResult)
    assert outcome.output_path == "dist/custom.x86_64"
    assert export_runner.calls == [("Linux/X11", "release", "dist/custom.x86_64")]


def test_templates_missing_for_release_and_debug():
    # release/debug produce a full platform binary and need the matching export
    # templates: when export-get reports templates_installed=False, the operation
    # RETURNS export_templates_missing BEFORE any native run, for each of them.
    for mode in (ExportRunMode.RELEASE, ExportRunMode.DEBUG):
        get_runner = _get_runner({**GET_RESULT, "templates_installed": False})
        export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

        outcome = _run(
            get_runner=get_runner, export_runner=export_runner, mode=mode
        )

        assert isinstance(outcome, Failure), mode
        assert outcome.error.code == "export_templates_missing", mode
        assert "4.6.3.stable" in outcome.error.message, mode
        # The preflight fired before any native run.
        assert export_runner.calls == [], mode


def test_pack_is_exempt_from_templates_preflight():
    # --mode pack produces project data only and needs NO platform templates: with
    # templates_installed=False, pack does NOT emit export_templates_missing — it
    # proceeds straight to the native runner.
    get_runner = _get_runner({**GET_RESULT, "templates_installed": False})
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run(
        get_runner=get_runner, export_runner=export_runner, mode=ExportRunMode.PACK
    )

    assert isinstance(outcome, ExportRunResult)
    assert outcome.mode is ExportRunMode.PACK
    assert export_runner.calls == [("Linux/X11", "pack", "build/game.x86_64")]


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
    return run_export_operation(
        preset="Linux/X11",
        mode=ExportRunMode.PACK,  # pack: no template preflight, runs the native seam
        output_override="build/game.zip",
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
        'config_version=5\n\n[application]\n', encoding="utf-8"
    )
    # Ensure a clean slate (idempotent): no harness present.
    uninstall_harness(tmp_path)
    export_runner = FakeExportRunner(RunResult(stdout="", stderr="", exit_code=0))

    outcome = _run_export_in(tmp_path, export_runner)

    assert isinstance(outcome, ExportRunResult)
    assert not (tmp_path / "addons" / "gda_harness").exists()
    assert "GdaHarness" not in (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert export_runner.calls == [("Linux/X11", "pack", "build/game.zip")]


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
        'config_version=5\n\n[application]\n', encoding="utf-8"
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


def test_native_nonzero_exit_returns_export_failed():
    # A non-zero native export with no recognized stderr signature is classified
    # as the generic export_failed Failure; the engine's stderr is preserved as
    # advisory diagnostics.
    get_runner = _get_runner()
    export_runner = FakeExportRunner(
        RunResult(
            stdout="", stderr="ERROR: could not write artifact to disk.\n", exit_code=1
        )
    )

    outcome = _run(get_runner=get_runner, export_runner=export_runner)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_failed"
    assert "could not write artifact" in outcome.error.diagnostics
