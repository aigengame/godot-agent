"""S2: classify_export_run + parse_export_warnings — pure unit (issue #121).

``export run`` is the one command that does NOT emit an ADR-0002 sentinel: the
export subsystem is editor-only, so the artifact is produced by a native
``--export-<mode>`` invocation, and ``gda`` synthesizes the structured outcome
from the subprocess's exit code + stderr. ``classify_export_run`` owns that
synthesis as a pure function — exercised here without a real engine by injecting
a crafted :class:`~gda.export_runner.ExportRunOutput`, exactly like
``classify_run`` is for the sentinel pipeline.
"""

from pathlib import Path

from gda.errors import (
    Failure,
    classify_export_run,
    export_path_unset_failure,
    parse_export_warnings,
)
from gda.exit_codes import EXIT_NOT_FOUND, EXIT_OPERATION, EXIT_TIMEOUT
from gda.export_runner import ExportRunOutput
from gda.models import ExportRunMode, ExportRunResult
from gda.runner import LaunchFailure

BINARY = Path("/x/Godot")


def _classify(output: ExportRunOutput) -> ExportRunResult | Failure:
    return classify_export_run(
        output,
        BINARY,
        preset="Linux/X11",
        platform="Linux/X11",
        mode=ExportRunMode.RELEASE,
        output_path="build/game.x86_64",
    )


def test_clean_export_synthesizes_success_result():
    # A clean native export (exit 0, no warnings) becomes the typed result
    # echoing the preset/platform/mode/path that were exported.
    outcome = _classify(ExportRunOutput(stdout="", stderr="", exit_code=0))

    assert outcome == ExportRunResult(
        preset="Linux/X11",
        platform="Linux/X11",
        mode=ExportRunMode.RELEASE,
        output_path="build/game.x86_64",
        warnings=[],
    )


def test_clean_export_surfaces_advisory_warnings():
    # WARNING lines on a clean (exit 0) export are advisory diagnostics on the
    # success result (ADR-0002), not a failure.
    outcome = _classify(
        ExportRunOutput(
            stdout="",
            stderr="WARNING: missing icon.\nINFO: noise\nWARNING: skipped asset.\n",
            exit_code=0,
        )
    )

    assert isinstance(outcome, ExportRunResult)
    assert outcome.warnings == ["missing icon.", "skipped asset."]


def test_not_found_maps_to_environment_failure():
    # The runner synthesizes NOT_FOUND when the binary is missing — an
    # environment failure exiting 127, keyed on the typed launch_failure (not the
    # exit code), mirroring classify_run.
    outcome = _classify(
        ExportRunOutput(
            stdout="",
            stderr="gda: Godot binary not found\n",
            exit_code=EXIT_NOT_FOUND,
            launch_failure=LaunchFailure.NOT_FOUND,
        )
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "binary_not_found"
    assert outcome.exit_code == EXIT_NOT_FOUND


def test_timeout_maps_to_environment_failure():
    # A hung export the runner timed out is launch_timeout, exiting 124.
    outcome = _classify(
        ExportRunOutput(
            stdout="",
            stderr="gda: Godot export timed out\n",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
        )
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "launch_timeout"
    assert outcome.exit_code == EXIT_TIMEOUT


def test_signal_death_maps_to_engine_crashed():
    # subprocess reports a signal death as a negative return code: the engine ran
    # but was killed, not the export cleanly reporting an error.
    outcome = _classify(ExportRunOutput(stdout="", stderr="", exit_code=-11))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "engine_crashed"


def test_config_error_stderr_maps_to_templates_missing():
    # The engine's stable "due to configuration errors" prefix (missing templates
    # / misconfigured preset) surfaces as the distinct export_templates_missing.
    outcome = _classify(
        ExportRunOutput(
            stdout="",
            stderr='ERROR: export failed due to configuration errors.\n',
            exit_code=1,
        )
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_templates_missing"
    assert outcome.exit_code == EXIT_OPERATION


def test_other_nonzero_maps_to_generic_export_failed():
    # A non-zero export with no recognized signature is the generic export_failed,
    # preserving the engine stderr as diagnostics.
    outcome = _classify(
        ExportRunOutput(stdout="", stderr="ERROR: disk full\n", exit_code=1)
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_failed"
    assert "disk full" in outcome.error.diagnostics


def test_export_path_unset_failure_builder():
    # The pre-run path-unset failure names the preset and the registered code.
    failure = export_path_unset_failure("Linux/X11")

    assert isinstance(failure, Failure)
    assert failure.error.code == "export_path_unset"
    assert failure.exit_code == EXIT_OPERATION
    assert "Linux/X11" in failure.error.message


def test_parse_export_warnings_is_empty_when_clean():
    # No WARNING lines → no warnings (a pure function of the stderr text).
    assert parse_export_warnings("INFO: built ok\nERROR: unrelated\n") == []
