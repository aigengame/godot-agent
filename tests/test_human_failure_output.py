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
from gda.exit_codes import EXIT_LIVE, EXIT_OPERATION
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
                target_location="/work/game/hero.gd",
                project_root="/work/other",
                owning_project="/work/game",
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
        "  target location: /work/game/hero.gd",
        "  project root: /work/other",
        "  owning project: /work/game",
    ]


def test_the_bounded_keys_all_precede_the_unbounded_diagnostics():
    # The layout rule this slice leads with, asserted as the WHOLE sequence. Every
    # other layout test here fixes one part in isolation, and the #798 review
    # measured what that leaves open: moving `diagnostics` above `evidence` passed
    # all 2277 tests. It must not — `diagnostics` is the only unbounded part (a
    # `script run --strict` capture ran to 4,015 lines in that review), so anything
    # printed after it is off the terminal, verdict included.
    text = render_failure(
        _error(
            probe=EnvironmentProbe(name="CGSession", platform="darwin"),
            hint="gda script run <path>",
            evidence=FailureEvidence(exit_status=3),
            diagnostics="--- script stderr ---\nSCRIPT ERROR: boom\n",
        )
    )

    assert text.splitlines() == [
        "error: script_failed (operation)",
        "script run --strict: res://t.gd exited with status 3",
        "probe: CGSession (darwin)",
        "hint: gda script run <path>",
        "evidence:",
        "  exit status: 3",
        "",
        "--- script stderr ---",
        "SCRIPT ERROR: boom",
    ]


# One sample value per `FailureEvidence` field, so a field the model grows has to be
# given one here before this file will run. The renderer is a hand-written branch per
# field rather than a loop over `model_fields` — each field is formatted differently
# (a clock to two decimals, an enum by value, a list as a sub-block) — so the guard
# below is what keeps the hand-written half exhaustive.
_EVIDENCE_SAMPLES = {
    "exit_status": 3,
    "elapsed_seconds": 30.219,
    "timeout_seconds": 30.0,
    "termination_phase": TerminationPhase.OUTPUT_SEEN,
    "script_errors": [
        ScriptError(
            kind=ScriptErrorKind.PARSE_ERROR,
            message="Identifier 'Foo' not declared.",
            path="res://t.gd",
            line=12,
        )
    ],
    "target_location": "/tmp/outer/inner/main.gd",
    "project_root": "/tmp/outer",
    "owning_project": "/tmp/outer/inner",
}


def test_the_sample_table_covers_every_field_the_model_publishes():
    # The half that reds when `FailureEvidence` grows a sixth field.
    assert set(_EVIDENCE_SAMPLES) == set(FailureEvidence.model_fields)


@pytest.mark.parametrize("field", sorted(_EVIDENCE_SAMPLES))
def test_every_evidence_field_alone_reaches_the_human_block(field):
    # The half that reds when the renderer drops one. `--json` enumerates the
    # evidence from the model itself (`model_dump_json`), so a new field ships there
    # whatever the renderer does; without this the human side could silently omit it
    # and no test would notice (#798 review). Each field is rendered ALONE, so a
    # missing branch cannot hide behind a neighbour's line.
    text = render_failure(
        _error(evidence=FailureEvidence(**{field: _EVIDENCE_SAMPLES[field]}))
    )

    assert text.splitlines()[2] == "evidence:", field
    assert len(text.splitlines()) > 3, field


def test_recognizing_no_script_error_is_reported_rather_than_read_as_absent():
    # `script_errors` publishes THREE states, not two (`FailureEvidence`): absent
    # means this failure's channel does not parse stderr, `[]` means it parsed and
    # recognized none — itself a finding — and a list is what it found. The renderer
    # used a truthiness test, which collapsed the first two, so a real
    # `launch_timeout` shipped `"script_errors":[]` on `--json` and nothing at all to
    # a human (#798 review). It gets a sentence rather than the bare header the
    # layout rule forbids.
    text = render_failure(_error(evidence=FailureEvidence(script_errors=[])))

    assert text.splitlines()[2:] == ["evidence:", "  script errors: none recognized"]


def test_an_evidence_object_that_parses_nothing_still_renders_no_section():
    # The other side of that line: the ABSENT state stays absent. `None` is not a
    # finding, so it must not grow a section — the tri-state must not become a
    # two-state in the other direction.
    text = render_failure(_error(evidence=FailureEvidence(script_errors=None)))

    assert "evidence" not in text


def test_a_crlf_diagnostics_stream_leaves_no_stray_carriage_return():
    # The runner does no newline translation, so a Windows engine's stderr arrives
    # CRLF-terminated. Stripping only "\n" left a bare "\r" on the last line, which a
    # terminal renders by parking the cursor at column 0 (#798 review).
    text = render_failure(_error(diagnostics="SCRIPT ERROR: boom\r\n"))

    # Split on "\n" only: `str.splitlines` treats a lone "\r" as a line boundary too,
    # so it would hide exactly the character under test.
    assert text.split("\n")[-1] == "SCRIPT ERROR: boom"


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


def test_a_raw_stderr_failure_reaches_a_human_once_not_twice(monkeypatch):
    # The #798 review reproduction: for a classifier whose `diagnostics` IS the raw
    # child stderr, the pre-classification tee said the same bytes on stderr that
    # the rendered diagnostics block then said on stdout. The tee now yields at the
    # emission point when the bytes are identical, so a human reads ONE copy, on
    # the channel the layout owns.
    raw = "Godot Engine v4.6.stable\nERROR: the operation said no\n"
    inject_runner(monkeypatch, RunResult(stdout="", stderr=raw, exit_code=1))

    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == EXIT_OPERATION
    assert result.stdout.startswith("error: operation_failed (operation)\n")
    both = result.stdout + result.stderr
    assert both.count("ERROR: the operation said no") == 1
    assert raw not in result.stderr


def test_the_same_raw_failure_under_json_keeps_its_stderr_tee(monkeypatch):
    # The scope boundary: `--json`'s streams are exactly what they were — the
    # envelope alone on stdout, the child's stderr forwarded in full.
    raw = "Godot Engine v4.6.stable\nERROR: the operation said no\n"
    inject_runner(monkeypatch, RunResult(stdout="", stderr=raw, exit_code=1))

    result = CliRunner().invoke(app, ["info", "--json"])

    assert result.exit_code == EXIT_OPERATION
    assert json.loads(result.stdout)["error"]["code"] == "operation_failed"
    assert raw in result.stderr


def test_a_capped_diagnostics_failure_keeps_the_full_stderr_tee(monkeypatch):
    # Byte identity, not the error code, decides: a timeout's diagnostics is the
    # COMPOSED tail-capped capture, not the raw stream, so its tee — the only
    # complete copy — survives for a human too.
    raw = "Godot Engine v4.6.stable\n"
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="",
            stderr=raw,
            exit_code=124,
            launch_failure=LaunchFailure.TIMEOUT,
            elapsed_seconds=60.1,
            timeout_bound=TimeoutBound("Godot", 60.0),
        ),
    )

    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == 124
    assert "--- captured stderr ---\nGodot Engine v4.6.stable" in result.stdout
    assert raw in result.stderr


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


def test_a_usage_refusal_without_json_is_rendered_by_the_same_one_renderer():
    # The `usage` category answers here too (#798 review). It used to raise click's
    # own `UsageError` in human mode — a SECOND private layout, with no head line, no
    # code and no category, on stderr while its own `--json` twin already went to
    # stdout. `hint` is reachable only on this path, so routing it here is also what
    # makes the renderer's totality over the envelope real rather than dead code.
    result = CliRunner().invoke(app, ["scene", "inspect"])

    assert result.exit_code == 2
    assert result.stdout.splitlines() == [
        "error: unknown_command (usage)",
        "`gda scene inspect` is not a gda command. Use `gda scene get` instead: "
        "`get` is the read verb in every group (ADR-0005); it reports the scene's "
        "structured node tree",
        "hint: gda scene get",
    ]


# --- every call site, on the caller's channel -----------------------------------
#
# `emit_failure` has SIX call sites, and each one chooses the channel itself — the
# keyword is required precisely so a new one cannot default back into JSON. Two of
# them were already exercised in human mode above (`HeadlessCommand.run`, by the
# `gda info` timeout; `hints._answer`, by the usage refusal); the #798 review measured
# what the other four were worth and found that reverting any of them to always-JSON
# passed the whole suite. One CLI case each closes that, all four engine-free.


def _project(tmp_path):
    """The minimum that makes a directory a Godot project (ADR-0006)."""
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


def test_an_unresolvable_project_is_refused_in_lines_on_the_dispatch_tail(tmp_path):
    # `dispatch._resolve_project_or_fail`, the shared project-resolution point: it
    # refuses BEFORE any command runs, so the flag is the one the tail carries down.
    result = CliRunner().invoke(
        app, ["scene", "get", "res://a.tscn", "--project", str(tmp_path / "nope")]
    )

    assert result.exit_code == EXIT_OPERATION, result.stdout
    assert result.stdout.splitlines()[0] == "error: project_not_found (operation)"
    assert "no project.godot" in result.stdout.splitlines()[1]


def test_a_recipe_failure_is_refused_in_lines_too(monkeypatch, tmp_path):
    # `dispatch.dispatch_recipe`'s failure arm — the branch a recipe command takes
    # instead of the sentinel pipeline (ADR-0023). An empty runtime dir means the
    # real discovery finds no daemon, so no engine and no daemon are involved.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "capture",
            "--output",
            str(tmp_path / "shot.png"),
            "--project",
            str(_project(tmp_path)),
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout
    assert result.stdout.splitlines()[0] == "error: daemon_not_running (live)"
    assert "gda daemon start" in result.stdout.splitlines()[1]


def test_the_params_json_conflict_is_refused_in_lines(tmp_path):
    # `_SchemaCommand.invoke`'s first refusal. It runs inside the PARSER, before any
    # dispatch tail exists, so it reads the channel off the click context
    # (`json_in_effect`) rather than off a flag someone handed it.
    result = CliRunner().invoke(
        app,
        [
            "scene",
            "create",
            "--params-json",
            '{"path": "res://a.tscn", "root_type": "Node2D"}',
            "res://b.tscn",
            "--project",
            str(_project(tmp_path)),
        ],
    )

    assert result.exit_code == EXIT_OPERATION, result.stdout
    assert result.stdout.splitlines()[0] == "error: usage_error (operation)"
    assert "mutually exclusive" in result.stdout.splitlines()[1]


def test_an_invalid_params_json_object_is_refused_in_lines(tmp_path):
    # `_SchemaCommand.invoke`'s second refusal, same context-read channel. The
    # message is the shared clean-sentence extractor's, so what a human reads here is
    # the sentence the argv path would have given, laid out rather than escaped.
    result = CliRunner().invoke(
        app,
        [
            "scene",
            "create",
            "--params-json",
            "{}",
            "--project",
            str(_project(tmp_path)),
        ],
    )

    assert result.exit_code == EXIT_OPERATION, result.stdout
    assert result.stdout.splitlines()[0] == "error: invalid_params (operation)"
    assert "path: Field required" in result.stdout.splitlines()[1]
