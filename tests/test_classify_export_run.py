"""S2: classify_export_run + parse_export_warnings — pure unit (issue #121).

``export run`` is the one command that does NOT emit an ADR-0002 sentinel: the
export subsystem is editor-only, so the artifact is produced by a native
``--export-<mode>`` invocation, and ``gda`` synthesizes the structured outcome
from the subprocess's exit code + stderr. ``classify_export_run`` owns that
synthesis as a pure function — exercised here without a real engine by injecting
a crafted :class:`~gda.runner.RunResult` (the shared raw-run dataclass both
channels return since #185), exactly like ``classify_run`` is for the sentinel
pipeline.
"""

from pathlib import Path

from gda.errors import (
    Failure,
    classify_export_run,
    export_path_unset_failure,
    parse_export_warnings,
)
from gda.exit_codes import EXIT_OPERATION
from gda.models import ExportRunMode, ExportRunResult
from gda.runner import LaunchFailure, RunResult

BINARY = Path("/x/Godot")


def _classify(output: RunResult) -> ExportRunResult | Failure:
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
    outcome = _classify(RunResult(stdout="", stderr="", exit_code=0))

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
        RunResult(
            stdout="",
            stderr="WARNING: missing icon.\nINFO: noise\nWARNING: skipped asset.\n",
            exit_code=0,
        )
    )

    assert isinstance(outcome, ExportRunResult)
    assert outcome.warnings == ["missing icon.", "skipped asset."]


def test_config_error_stderr_still_maps_to_generic_export_failed():
    # Template readiness is now a STRUCTURED preflight (export get's
    # templates_installed, decided BEFORE the native run), so classify_export_run
    # no longer string-matches stderr for a stable code (ADR-0002 forbids it). Any
    # non-zero native export — even the engine's old "due to configuration errors"
    # text — is the generic export_failed; the stderr is advisory diagnostics only.
    outcome = _classify(
        RunResult(
            stdout="",
            stderr="ERROR: export failed due to configuration errors.\n",
            exit_code=1,
        )
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_failed"
    assert outcome.exit_code == EXIT_OPERATION
    # The engine text is preserved advisorily, not parsed for the code.
    assert "configuration errors" in outcome.error.diagnostics


def test_other_nonzero_maps_to_generic_export_failed():
    # A non-zero export with no recognized signature is the generic export_failed,
    # preserving the engine stderr as diagnostics.
    outcome = _classify(
        RunResult(stdout="", stderr="ERROR: disk full\n", exit_code=1)
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_failed"
    assert "disk full" in outcome.error.diagnostics


def test_export_timeout_envelope_keeps_byte_compatible_diagnostics():
    # Regression for the #185 review: an export timeout maps to launch_timeout,
    # and the runner-synthesized stderr is carried verbatim into the PUBLIC
    # GdaError.diagnostics — the field serialized in `export run --json`. The
    # refactor must keep that diagnostics string byte-compatible with the pre-#185
    # "Godot export timed out" wording, so the error envelope is unchanged.
    timeout_stderr = "gda: Godot export timed out after 600.0s\n"
    outcome = _classify(
        RunResult(
            stdout="",
            stderr=timeout_stderr,
            exit_code=124,
            launch_failure=LaunchFailure.TIMEOUT,
        )
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "launch_timeout"
    assert outcome.error.diagnostics == timeout_stderr


def test_export_path_unset_failure_builder():
    # The pre-run path-unset failure names the preset and the registered code, and
    # points at the two ways to supply a destination (#170): --output or the
    # preset's export_path — no longer claiming "no configured export_path", since
    # --output can now supply one.
    failure = export_path_unset_failure("Linux/X11")

    assert isinstance(failure, Failure)
    assert failure.error.code == "export_path_unset"
    assert failure.exit_code == EXIT_OPERATION
    assert "Linux/X11" in failure.error.message
    assert "--output" in failure.error.message
    assert "export_path" in failure.error.message


def test_parse_export_warnings_is_empty_when_clean():
    # No WARNING lines → no warnings (a pure function of the stderr text).
    assert parse_export_warnings("INFO: built ok\nERROR: unrelated\n") == []
