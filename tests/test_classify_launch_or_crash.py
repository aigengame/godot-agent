"""classify_launch_or_crash — the env/crash classifier prefix (issues #185, #714).

Every headless channel opens classification with the same env/crash prefix: a
synthesized ``NOT_FOUND`` launch failure → ``binary_not_found``, a synthesized
``TIMEOUT`` → ``launch_timeout``, and a signal death (``exit < 0``) →
``engine_crashed``; anything else returns ``None`` so the caller's
channel-specific tail takes over. That mapping used to be written (and asserted)
twice — once in ``classify_run``, once in ``classify_export_run``. It now lives in
one shared function, tested here once; each channel's suite keeps only its tail.

The ``TIMEOUT`` arm is where being ONE function pays: the sentinel, export and
import channels reach it through three different classifiers, so the evidence a
hung run reports — its captured output, the ceiling it reached and the wall clock
it spent — is asserted here once and holds for all three (#714).

Environment failures key on the runner's typed ``launch_failure`` reason, not the
exit code, so an engine (or wrapper) that *genuinely* exits 124/127 falls through
the prefix (returns ``None``) and is classified by the tail as operation — that
fall-through is asserted here, the operation classification in each channel suite
(issue #15).
"""

import json
from pathlib import Path

from gda.errors import (
    CAPTURED_OUTPUT_TAIL_CAP_BYTES,
    Failure,
    classify_launch_or_crash,
)
from gda.exit_codes import EXIT_NOT_FOUND, EXIT_OPERATION, EXIT_TIMEOUT
from gda.models import ErrorCategory, TerminationPhase
from gda.runner import LaunchFailure, RunResult, TimeoutBound

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
        stderr="",
        exit_code=EXIT_TIMEOUT,
        launch_failure=LaunchFailure.TIMEOUT,
    )

    failure = classify_launch_or_crash(result, BINARY)

    assert isinstance(failure, Failure)
    assert failure.exit_code == EXIT_TIMEOUT
    assert failure.error.category == ErrorCategory.ENVIRONMENT
    assert failure.error.code == "launch_timeout"


def test_a_timeout_carries_the_captured_output_the_ceiling_and_the_clock():
    # THE #714 acceptance criterion, asserted on the ONE branch all three buffered
    # channels open with. Before it, a hung sentinel op / export / import pass came
    # back with nothing but "gda: <label> timed out after <n>s": the engine's own
    # output was discarded by the buffered capture, and the envelope reported
    # neither how long the run had actually taken nor how far it got.
    result = RunResult(
        stdout="[  50% ] exporting resources\n",
        stderr="ERROR: the exporter wedged\n",
        exit_code=EXIT_TIMEOUT,
        launch_failure=LaunchFailure.TIMEOUT,
        elapsed_seconds=601.25,
        timeout_bound=TimeoutBound("Godot export", 600.0),
    )

    failure = classify_launch_or_crash(result, BINARY)

    assert isinstance(failure, Failure)
    assert failure.error.code == "launch_timeout"
    # WHICH launch gave up, the ceiling it reached, and the wall clock it spent —
    # the three numbers that name the consumed bound and what raising it buys.
    assert failure.error.message.startswith("Godot export launched but did not return")
    assert "timeout of 600.0s" in failure.error.message
    assert "elapsed 601.25s" in failure.error.message
    # The cap is STATED, so a caller knows the diagnostics are a tail and not all.
    assert f"{CAPTURED_OUTPUT_TAIL_CAP_BYTES} UTF-8 bytes (16 KiB)" in (
        failure.error.message
    )
    # And both streams are carried under fixed labels, so one split reads either.
    assert failure.error.diagnostics == (
        "--- captured stdout ---\n[  50% ] exporting resources\n"
        "--- captured stderr ---\nERROR: the exporter wedged\n"
    )


def test_a_timeout_tail_caps_each_captured_stream():
    # `diagnostics` is serialized inline in the JSON result, so a run that looped for
    # ten minutes must not put ten minutes of output in an error envelope. The TAIL
    # is what is kept: where the run got to is the interesting end.
    result = RunResult(
        stdout="x" * (CAPTURED_OUTPUT_TAIL_CAP_BYTES * 2) + "LAST LINE\n",
        stderr="y" * (CAPTURED_OUTPUT_TAIL_CAP_BYTES * 2),
        exit_code=EXIT_TIMEOUT,
        launch_failure=LaunchFailure.TIMEOUT,
        elapsed_seconds=60.0,
        timeout_bound=TimeoutBound("Godot", 60.0),
    )

    failure = classify_launch_or_crash(result, BINARY)

    assert isinstance(failure, Failure)
    diagnostics = failure.error.diagnostics
    assert "LAST LINE" in diagnostics
    assert diagnostics.count("x") == CAPTURED_OUTPUT_TAIL_CAP_BYTES - len("LAST LINE\n")
    assert diagnostics.count("y") == CAPTURED_OUTPUT_TAIL_CAP_BYTES


def test_an_unmeasured_timeout_still_reports_rather_than_crashing():
    # A hand-built RunResult at a test seam carries neither bound nor clock. The
    # builder degrades to the bare sentence instead of asserting on a boundary
    # value, which would kill the command (and vanish under -O).
    failure = classify_launch_or_crash(
        RunResult(
            stdout="",
            stderr="",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
        ),
        BINARY,
    )

    assert isinstance(failure, Failure)
    assert failure.error.code == "launch_timeout"
    assert failure.error.message.startswith(
        "Godot launched but did not return before the timeout."
    )
    assert "elapsed" not in failure.error.message


def test_the_timeout_remediation_reads_caller_first():
    # #717's decision, made observable: `launch_timeout` keeps its `environment`
    # category (asserted above and pinned by the registry test), so the MESSAGE is
    # the only place that can stop the category alone from sending an agent to
    # retry/reinstall/another-host remedies for a ceiling it chose itself. The
    # ORDER is the contract, not the prose: the caller's remedy must precede the
    # host suspicion, and the host suspicion must carry the condition that earns it.
    failure = classify_launch_or_crash(
        RunResult(
            stdout="",
            stderr="",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
            elapsed_seconds=30.2,
            timeout_bound=TimeoutBound("Godot import", 30.0),
        ),
        BINARY,
    )

    assert isinstance(failure, Failure)
    message = failure.error.message
    caller_remedy = message.index("read the captured output")
    host_suspicion = message.index("suspect the binary or the machine")
    assert caller_remedy < host_suspicion, message
    assert "the capture shows the engine never started" in message

    # The flag is named WITH its qualifier. Of the three channels on this builder
    # only `resource import` exposes `--timeout` (the sentinel's 60s and the
    # export's 600s are gda's own, fixed), so an unqualified "raise --timeout"
    # here would name a flag most callers of this message do not have — the
    # misfire #717 warned about.
    assert "--timeout, where the command exposes one" in message

    # ...and the two channels that qualifier EXCLUDES are then given their own next
    # step rather than a dead end (PR #793 review). An agent on the sentinel's 60s
    # or the export's 600s that has read the capture and seen the engine working has
    # nothing to raise; naming what is still actionable there is what keeps the
    # caller-first reading from running out before the host suspicion it withholds.
    assert "Where the command exposes no --timeout" in message
    assert "reduce the work or give the machine more headroom" in message


def test_the_timeout_message_says_a_captured_error_is_advisory():
    # #716's decision, made observable at the point of consumption: a recognized
    # engine error inside the capture does NOT re-verdict this code into a #651
    # entry-load failure, and the message says so, so a caller reading the
    # diagnostics does not re-verdict on gda's behalf either.
    failure = classify_launch_or_crash(
        RunResult(
            stdout="",
            stderr="SCRIPT ERROR: Parse Error: something\n",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
            elapsed_seconds=60.1,
            timeout_bound=TimeoutBound("Godot", 60.0),
        ),
        BINARY,
    )

    assert isinstance(failure, Failure)
    assert failure.error.code == "launch_timeout"  # NOT re-verdicted
    assert "advisory" in failure.error.message
    assert "the verdict here is the timeout" in failure.error.message
    # The error itself still reaches the caller as evidence, unchanged.
    assert "Parse Error" in failure.error.diagnostics


def test_the_shared_timeout_envelope_carries_its_numbers_as_data():
    # #687 (the ADR-0004 amendment) on the SHARED builder, so this holds for all
    # three channels that reach it. The three facts #714 put in the message — the
    # ceiling, the elapsed clock, and how far the run got — are now also DATA, read
    # as numbers instead of by matching a sentence; they support choosing the next
    # bound, not a slow-versus-stuck verdict.
    failure = classify_launch_or_crash(
        RunResult(
            stdout="Godot Engine v4.6.3\n",
            stderr="",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
            elapsed_seconds=30.2,
            timeout_bound=TimeoutBound("Godot import", 30.0),
        ),
        BINARY,
    )

    assert isinstance(failure, Failure)
    evidence = failure.error.evidence
    assert evidence is not None
    assert evidence.elapsed_seconds == 30.2
    assert evidence.timeout_seconds == 30.0
    assert evidence.termination_phase is TerminationPhase.OUTPUT_SEEN
    # The captured streams stay in `diagnostics` ALONE: copying two 16 KiB captures
    # into the evidence object would double the payload to say the same thing twice.
    assert "Godot Engine v4.6.3" in failure.error.diagnostics
    # This builder does not parse the capture — #716 keeps the stream advisory, and
    # only `script run` has the parser and the entry to attribute against — so the
    # unset fields are absent rather than empty.
    assert evidence.script_errors is None
    assert evidence.exit_status is None


def test_a_run_that_wrote_nothing_reports_the_narrower_phase_as_data():
    # The distinction the phase exists for, and the one case where suspecting the
    # binary or the host IS the right next step: the engine never reached its own
    # startup output. Godot prints its banner within ~0.1s of a normal spawn, so
    # silence here means it never got that far.
    failure = classify_launch_or_crash(
        RunResult(
            stdout="",
            stderr="",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
            elapsed_seconds=60.0,
            timeout_bound=TimeoutBound("Godot", 60.0),
        ),
        BINARY,
    )

    assert isinstance(failure, Failure)
    assert failure.error.evidence is not None
    assert failure.error.evidence.termination_phase is TerminationPhase.LAUNCHED


def test_an_unmeasured_timeout_omits_the_clocks_rather_than_inventing_them():
    # The typed half degrades exactly as the prose half does: a hand-built RunResult
    # at a test seam carries neither bound nor clock, and an absent key is honest
    # where a zero would read as "instant". This is also the nested-omission proof on
    # a REAL builder — the evidence object ships with only the field it could fill.
    failure = classify_launch_or_crash(
        RunResult(
            stdout="",
            stderr="",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
        ),
        BINARY,
    )

    assert isinstance(failure, Failure)
    emitted = json.loads(failure.error.model_dump_json(exclude_none=True))
    assert emitted["evidence"] == {"termination_phase": "launched"}


def test_a_failure_with_nothing_to_evidence_keeps_its_pre_687_envelope():
    # The scope-defining property of the amendment: `binary_not_found` computes no
    # evidence, so its envelope has the same four keys it had before #687 — not a
    # fifth key holding `null`, and not an empty object.
    failure = classify_launch_or_crash(
        RunResult(
            stdout="",
            stderr="gda: Godot binary could not be launched: /x/Godot\n",
            exit_code=EXIT_NOT_FOUND,
            launch_failure=LaunchFailure.NOT_FOUND,
        ),
        BINARY,
    )

    assert isinstance(failure, Failure)
    assert failure.error.evidence is None
    emitted = json.loads(failure.error.model_dump_json(exclude_none=True))
    assert set(emitted) == {"category", "code", "message", "diagnostics"}


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
