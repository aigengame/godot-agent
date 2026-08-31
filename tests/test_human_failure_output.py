"""Human-mode failure rendering (#685): real lines, and the JSON channel untouched.

Until this slice ``emit_failure`` had no human channel *at all*: it serialized the
envelope with ``model_dump_json`` and exited, so a caller who did not pass ``--json``
still got the JSON line — and read a ``script run --strict`` capture as one
``\\n``-escaped blob, blunting exactly the flag CI operators reach for. What is
asserted here is therefore two things at once:

- the human channel LAYS THE ENVELOPE OUT — a head line naming the verdict, the
  message, the typed keys as labelled lines, and ``diagnostics`` verbatim as real
  lines — with nothing rendered for a key the failure does not carry;
- the JSON channel is byte-identical to what it emitted before, measured across the
  whole registry rather than sampled, because "one renderer, no per-code special
  case" is only safe if the other channel cannot feel it.

The rendered assertions go through ``tests.support``'s shared normalizers where the
text can reach Rich (a usage error's panel); ``emit_failure``'s own output is echoed
verbatim, so it is compared as written.
"""

import json

import pytest
import typer
from typer.testing import CliRunner

from gda.cli import app
from gda.error_codes import ERROR_CODES
from gda.errors import make_failure
from gda.headless import emit_failure
from gda.models import (
    EnvironmentProbe,
    ErrorCategory,
    FailureEvidence,
    GdaError,
    GdaErrorEnvelope,
    TerminationPhase,
)
from gda.render import render_failure
from gda.runner import LaunchFailure, RunResult, TimeoutBound
from gda.script_errors import ScriptError, ScriptErrorKind
from tests.support import inject_runner


def _error(**overrides) -> GdaError:
    """A `script_failed` envelope with whatever this case is about overridden."""
    fields = {
        "category": ErrorCategory.OPERATION,
        "code": "script_failed",
        "message": "script run --strict: res://t.gd exited with status 3",
    }
    fields.update(overrides)
    return GdaError(**fields)


# --- the layout -----------------------------------------------------------------


def test_a_failure_with_nothing_but_a_verdict_renders_the_head_and_its_message():
    # The head line names the two machine-readable facts a caller branches on in
    # JSON — the code, and the category behind it — and the message follows on its
    # own line rather than being wrapped into the head: several messages are a
    # paragraph (the `launch_timeout` remediation is four sentences), so a joined
    # head line would be a wrapped blob again.
    text = render_failure(
        GdaError(
            category=ErrorCategory.ENVIRONMENT,
            code="binary_not_found",
            message="Godot binary could not be launched: /nope/Godot",
        )
    )

    assert text == (
        "error: binary_not_found (environment)\n"
        "Godot binary could not be launched: /nope/Godot"
    )


def test_labelled_diagnostics_reach_the_reader_as_real_lines():
    # The motivating case (#651/#678): `script run --strict` puts the script's own
    # stdout and stderr in `diagnostics` under fixed labels, which is the evidence a
    # CI operator reads. As one escaped JSON string it is unreadable.
    text = render_failure(
        _error(
            diagnostics=(
                "--- script stdout ---\nrunning 3 tests\n"
                "--- script stderr ---\nSCRIPT ERROR: boom\n"
            )
        )
    )

    assert "\\n" not in text
    assert text.splitlines() == [
        "error: script_failed (operation)",
        "script run --strict: res://t.gd exited with status 3",
        "",
        "--- script stdout ---",
        "running 3 tests",
        "--- script stderr ---",
        "SCRIPT ERROR: boom",
    ]


def test_a_failure_with_no_diagnostics_renders_no_trailing_section():
    # Most codes carry short prose and nothing else; those must stay compact —
    # no blank line, no empty section header, no trailing newline for the CLI's
    # own `typer.echo` to double.
    text = render_failure(_error(diagnostics="   \n\n"))

    assert text.splitlines() == [
        "error: script_failed (operation)",
        "script run --strict: res://t.gd exited with status 3",
    ]


def test_typed_evidence_renders_one_labelled_line_per_field_it_carries():
    # The #687 key laid out for a human. Field order follows the model's own
    # declaration order, so the two channels enumerate the evidence identically and
    # neither has to be kept in step with the other by hand.
    text = render_failure(
        _error(
            code="launch_timeout",
            category=ErrorCategory.ENVIRONMENT,
            message="Godot import launched but did not return before the timeout.",
            evidence=FailureEvidence(
                exit_status=3,
                elapsed_seconds=30.219,
                timeout_seconds=30.0,
                termination_phase=TerminationPhase.OUTPUT_SEEN,
                script_errors=[
                    ScriptError(
                        kind=ScriptErrorKind.PARSE_ERROR,
                        message="Identifier 'Foo' not declared.",
                        path="res://t.gd",
                        line=12,
                    )
                ],
            ),
        )
    )

    assert text.splitlines()[2:] == [
        "evidence:",
        "  exit status: 3",
        "  elapsed: 30.22s",
        "  timeout: 30.0s",
        "  termination phase: output_seen",
        "  script errors:",
        "    parse_error: res://t.gd:12: Identifier 'Foo' not declared.",
    ]


def test_evidence_that_carries_no_field_renders_no_section():
    # Every field inside `evidence` is individually optional (#687), so the human
    # channel must treat the KEY as absent-by-default too — an `evidence:` header
    # over nothing would be the empty trailing section this slice exists to remove.
    text = render_failure(_error(evidence=FailureEvidence()))

    assert "evidence" not in text


def test_the_probe_and_the_hint_render_as_their_own_lines():
    # The envelope's other two optional keys (#667, #670). The renderer is total
    # over the envelope: a human failure that dropped them would carry strictly less
    # than the JSON line it replaces — and `probe` IS reachable in human mode
    # (`gda daemon start --windowed` on a host with no window server).
    text = render_failure(
        _error(
            code="live_windowed_unavailable",
            category=ErrorCategory.LIVE,
            message="no usable macOS window-server session",
            probe=EnvironmentProbe(
                name="CGSessionCopyCurrentDictionary", platform="darwin"
            ),
            hint="gda daemon start",
        )
    )

    assert text.splitlines()[2:] == [
        "probe: CGSessionCopyCurrentDictionary (darwin)",
        "hint: gda daemon start",
    ]


# --- the two channels -----------------------------------------------------------


def test_a_human_invocation_gets_the_lines_and_never_the_envelope(monkeypatch):
    # End to end through the real CLI: no `--json`, so the failure arrives as text.
    # `gda info` with a hung runner is the fast engine-free fixture that carries
    # typed evidence as well as prose.
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="",
            stderr="Godot Engine v4.6.stable\n",
            exit_code=124,
            launch_failure=LaunchFailure.TIMEOUT,
            elapsed_seconds=60.1,
            timeout_bound=TimeoutBound("Godot", 60.0),
        ),
    )

    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == 124
    assert not result.stdout.startswith("{")
    assert result.stdout.startswith("error: launch_timeout (environment)\n")
    assert "  timeout: 60.0s" in result.stdout
    assert "  termination phase: output_seen" in result.stdout
    assert "--- captured stderr ---\nGodot Engine v4.6.stable" in result.stdout


def test_the_same_failure_under_json_is_the_envelope_and_nothing_else(monkeypatch):
    # The scope-defining half, at the CLI: `--json` must be exactly what it was —
    # ONE line, the model's own `exclude_none` dump, with no rendered text anywhere
    # near it.
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="",
            stderr="Godot Engine v4.6.stable\n",
            exit_code=124,
            launch_failure=LaunchFailure.TIMEOUT,
            elapsed_seconds=60.1,
            timeout_bound=TimeoutBound("Godot", 60.0),
        ),
    )

    result = CliRunner().invoke(app, ["info", "--json"])

    assert result.exit_code == 124
    assert len(result.stdout.splitlines()) == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "launch_timeout"
    assert error["evidence"] == {
        "elapsed_seconds": 60.1,
        "timeout_seconds": 60.0,
        "termination_phase": "output_seen",
    }


def test_the_json_channel_stays_the_model_dump_for_every_registered_code(capsys):
    # The regression the whole slice is scoped by: `--json` must not change by one
    # byte, ANYWHERE. Measured across the entire registry, through the real emit
    # path, with all three optional keys populated — so a renderer that leaked into
    # the JSON branch, or a key the dump grew, fails here rather than in whichever
    # command a consumer happened to be parsing.
    for spec in ERROR_CODES:
        failure = make_failure(
            spec.code,
            "message",
            "first line\nsecond line\n",
            probe=EnvironmentProbe(name="probe", platform="darwin"),
            hint="gda schema",
            evidence=FailureEvidence(exit_status=3),
        )

        with pytest.raises(typer.Exit):
            emit_failure(failure, json_output=True)

        expected = GdaErrorEnvelope(error=failure.error).model_dump_json(
            exclude_none=True
        )
        assert capsys.readouterr().out == expected + "\n", spec.code
