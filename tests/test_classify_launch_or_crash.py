"""classify_launch_or_crash — the env/crash classifier prefix (issue #185).

Both headless channels open classification with the same env/crash prefix: a
synthesized ``NOT_FOUND`` launch failure → ``binary_not_found``, a synthesized
``TIMEOUT`` → ``launch_timeout``, and a signal death (``exit < 0``) →
``engine_crashed``; anything else returns ``None`` so the caller's
channel-specific tail takes over. That mapping used to be written (and asserted)
twice — once in ``classify_run``, once in ``classify_export_run``. It now lives in
one shared function, tested here once; each channel's suite keeps only its tail.

Environment failures key on the runner's typed ``launch_failure`` reason, not the
exit code, so an engine (or wrapper) that *genuinely* exits 124/127 falls through
the prefix (returns ``None``) and is classified by the tail as operation — that
fall-through is asserted here, the operation classification in each channel suite
(issue #15).
"""

from pathlib import Path

from gda.errors import Failure, classify_launch_or_crash
from gda.exit_codes import EXIT_NOT_FOUND, EXIT_OPERATION, EXIT_TIMEOUT
from gda.models import ErrorCategory
from gda.runner import LaunchFailure, RunResult

BINARY = Path("/x/Godot")


def test_synthesized_not_found_maps_to_binary_not_found():
    result = RunResult(
        stdout="",
        stderr="gda: Godot binary could not be launched: /x/Godot\n",
        exit_code=EXIT_NOT_FOUND,
        launch_failure=LaunchFailure.NOT_FOUND,
    )

    failure = classify_launch_or_crash(result, BINARY)

    assert isinstance(failure, Failure)
    assert failure.exit_code == EXIT_NOT_FOUND
    assert failure.error.category == ErrorCategory.ENVIRONMENT
    assert failure.error.code == "binary_not_found"
    assert str(BINARY) in failure.error.message
    # Engine/runner stderr is carried as diagnostics (ADR-0002).
    assert failure.error.diagnostics == result.stderr


def test_synthesized_timeout_maps_to_launch_timeout_distinct_from_not_found():
    result = RunResult(
        stdout="",
        stderr="gda: Godot timed out after 60.0s\n",
        exit_code=EXIT_TIMEOUT,
        launch_failure=LaunchFailure.TIMEOUT,
    )

    failure = classify_launch_or_crash(result, BINARY)

    assert isinstance(failure, Failure)
    assert failure.exit_code == EXIT_TIMEOUT
    assert failure.error.category == ErrorCategory.ENVIRONMENT
    assert failure.error.code == "launch_timeout"


def test_signal_death_maps_to_engine_crashed_naming_the_signal():
    # subprocess reports a signal death as a negative return code: the engine ran
    # but was killed (e.g. SIGSEGV) — an operation-category crash, never a raw
    # negative exit code leaking out.
    failure = classify_launch_or_crash(
        RunResult(stdout="", stderr="", exit_code=-11), BINARY
    )

    assert isinstance(failure, Failure)
    assert failure.exit_code == EXIT_OPERATION
    assert failure.error.category == ErrorCategory.OPERATION
    assert failure.error.code == "engine_crashed"
    assert "11" in failure.error.message


def test_clean_exit_returns_none_so_the_channel_tail_takes_over():
    # exit 0 with no launch failure is not an env/crash outcome: the prefix yields
    # to the channel-specific tail (sentinel parse vs synthesize-from-exit-code).
    assert (
        classify_launch_or_crash(RunResult(stdout="ok", stderr="", exit_code=0), BINARY)
        is None
    )


def test_genuine_engine_124_127_fall_through_to_the_tail():
    # A genuine engine/wrapper exit of 124/127 — with NO runner-synthesized launch
    # failure — is the engine's own result, not an env failure. The prefix returns
    # None so the tail classifies it as operation, never environment (issue #15).
    assert (
        classify_launch_or_crash(
            RunResult(stdout="", stderr="boom\n", exit_code=127), BINARY
        )
        is None
    )
    assert (
        classify_launch_or_crash(
            RunResult(stdout="", stderr="124\n", exit_code=124), BINARY
        )
        is None
    )
