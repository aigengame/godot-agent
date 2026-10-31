"""S2: the result parser implements the ADR-0002 sentinel contract."""

import json

import pytest

from gda.commands.script import parse_validate_diagnostics
from gda.core.engine.sentinel import parse_result


def test_extracts_json_ignoring_engine_noise():
    # Real headless stdout interleaves the engine banner, warnings and stray
    # print() output around the single sentinel-delimited result block.
    stdout = (
        "Godot Engine v4.6.3.stable.official - https://godotengine.org\n"
        "WARNING: something benign happened\n"
        "stray print from user script\n"
        "<<<GDA:RESULT>>>"
        '{"major": 4, "minor": 6, "patch": 3, "status": "stable"}'
        "<<<GDA:END>>>\n"
        "trailing engine noise after the result\n"
    )

    result = parse_result(stdout)

    assert result == {"major": 4, "minor": 6, "patch": 3, "status": "stable"}


RECORD_PAYLOAD = {"classes": [{"name": "Player", "path": "res://player.gd"}]}
RECORD = f"<<<GDA:RESULT>>>{json.dumps(RECORD_PAYLOAD)}<<<GDA:END>>>\n"


@pytest.mark.parametrize(
    "stdout",
    [
        "noise\n<<<GDA:RESULT>>>   <<<GDA:END>>>\n",
        f"<<<GDA:RESULT>>>{json.dumps(RECORD_PAYLOAD)}\n",
        '<<<GDA:RESULT>>>{"classes": [<<<GDA:END>>>\n',
    ],
    ids=["empty", "no-end", "incomplete-json"],
)
def test_a_begin_sentinel_with_no_complete_record_raises_descriptive_error(stdout):
    # A contract violation: a begin sentinel came out, but no complete JSON value
    # followed by the end sentinel. The parser says so instead of leaking an opaque
    # JSONDecodeError.
    with pytest.raises(ValueError, match="no complete GDA result record"):
        parse_result(stdout)


def test_payload_containing_sentinel_text_round_trips():
    # issue #34: the result payload echoes user-controlled content (a path, node
    # names, script source). Sentinel text inside it, even a whole record, is part
    # of a string value, and the JSON decoder reads it as such.
    payload = {
        "path": "res://weird<<<GDA:END>>>name.tscn",
        "source": 'print("<<<GDA:RESULT>>>1<<<GDA:END>>>")',
    }
    stdout = f"<<<GDA:RESULT>>>{json.dumps(payload)}<<<GDA:END>>>\n"

    assert parse_result(stdout) == payload


@pytest.mark.parametrize(
    "stdout",
    [
        RECORD + "cleanup <<<GDA:END>>>\n",
        "init <<<GDA:RESULT>>>\n" + RECORD,
        "init <<<GDA:RESULT>>> [1]\n" + RECORD + "exit <<<GDA:END>>>\n",
        RECORD.replace("\n", "\r\n") + "exit <<<GDA:END>>>\r\n",
    ],
    ids=["end-after", "begin-before", "both", "crlf"],
)
def test_sentinel_text_that_project_code_prints_around_the_record_is_ignored(stdout):
    # Project code shares stdout with the payload: an autoload's or an editor
    # plugin's _exit_tree prints after the record, an autoload's _init before it.
    # Only the one complete record is the result (ADR-0002, Outcome note of
    # 2026-10-31).
    assert parse_result(stdout) == RECORD_PAYLOAD


def test_two_complete_records_are_refused():
    # Two records cannot both be the result, and the parser cannot tell which one
    # the payload wrote, so it refuses instead of choosing.
    with pytest.raises(ValueError, match="2 complete GDA result records"):
        parse_result(RECORD + RECORD)


# --- script validate diagnostics (issue #118) ---
#
# The line/message of a failed GDScript.reload() are available ONLY from the
# engine's stderr, never from a bound API, so they are parsed Python-side. This
# is the exact stderr shape the standard Godot build emits.
REAL_VALIDATE_STDERR = (
    'SCRIPT ERROR: Parse Error: Expected expression for variable initial value after "=".\n'
    "          at: GDScript::reload (gdscript://-9223371888644840980.gd:3)\n"
)


def test_parse_validate_diagnostics_extracts_line_and_message():
    # The mechanism gate's parser half: a SCRIPT ERROR line + its reload frame
    # yield one diagnostic with the 1-based line and the message (the prefix
    # stripped). There is no column on the standard build, so it is null.
    diagnostics = parse_validate_diagnostics(REAL_VALIDATE_STDERR)

    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.line == 3
    assert diag.column is None
    assert (
        diag.message
        == 'Parse Error: Expected expression for variable initial value after "=".'
    )


def test_parse_validate_diagnostics_empty_when_no_script_error():
    # Valid-script stderr (engine banner / progress noise only) parses to no
    # diagnostics — there is nothing to advise on.
    stderr = (
        "Godot Engine v4.6.3.stable.official - https://godotengine.org\n"
        "gda: running operation: script-validate\n"
    )

    assert parse_validate_diagnostics(stderr) == []


def test_parse_validate_diagnostics_ignores_operations_own_backtrace_frames():
    # A failed reload also prints a GDScript backtrace of operations.gd's OWN
    # frames ([n] _initialize (...)). Those are not the validated script's lines,
    # so they must not become diagnostics — only the SCRIPT ERROR + reload frame.
    # This is the backtrace shape the standard build actually emits.
    stderr = (
        'SCRIPT ERROR: Parse Error: Unexpected "Identifier" in class body.\n'
        "          at: GDScript::reload (gdscript://-123.gd:5)\n"
        "          GDScript backtrace (most recent call first):\n"
        "              [0] _op_script_validate (res://ops/operations.gd:864)\n"
        "              [1] _initialize (res://ops/operations.gd:60)\n"
    )

    diagnostics = parse_validate_diagnostics(stderr)

    assert len(diagnostics) == 1
    assert diagnostics[0].line == 5
    assert (
        diagnostics[0].message == 'Parse Error: Unexpected "Identifier" in class body.'
    )


def test_parse_validate_diagnostics_does_not_borrow_a_later_errors_reload_line():
    # Bounded pairing: a SCRIPT ERROR with NO reload frame in its own window must
    # not steal the line of a later, unrelated error's reload frame. The first
    # SCRIPT ERROR is dropped (no reload frame before the next one); only the
    # second — which owns a reload frame — is reported, at ITS line.
    stderr = (
        "SCRIPT ERROR: Method failed. Returning: null\n"
        "SCRIPT ERROR: Parse Error: the real parse error.\n"
        "          at: GDScript::reload (gdscript://-1.gd:7)\n"
    )

    diagnostics = parse_validate_diagnostics(stderr)

    assert len(diagnostics) == 1
    assert diagnostics[0].line == 7
    assert diagnostics[0].message == "Parse Error: the real parse error."


def test_parse_validate_diagnostics_empty_message_keeps_line_and_does_not_spill():
    # An empty SCRIPT ERROR message must not swallow the following reload frame
    # (the `[ \t]` bound keeps the capture on its own line): the diagnostic still
    # gets the frame's line, with an empty message rather than the frame text.
    stderr = "SCRIPT ERROR: \n          at: GDScript::reload (gdscript://-1.gd:4)\n"

    diagnostics = parse_validate_diagnostics(stderr)

    assert len(diagnostics) == 1
    assert diagnostics[0].line == 4
    assert diagnostics[0].message == ""


def test_parse_validate_diagnostics_ignores_unrelated_autoload_script_errors():
    # Under --project the engine may print an autoload's OWN startup error to the
    # same stderr; its frame is the autoload's _ready/_init, not GDScript::reload.
    # That error is not the validated script's, so it is dropped — only the
    # reload-framed diagnostic survives.
    stderr = (
        "SCRIPT ERROR: Some autoload blew up at startup.\n"
        "          at: GameState._ready (res://game_state.gd:12)\n"
        "SCRIPT ERROR: Parse Error: the validated script error.\n"
        "          at: GDScript::reload (gdscript://-1.gd:9)\n"
    )

    diagnostics = parse_validate_diagnostics(stderr)

    assert len(diagnostics) == 1
    assert diagnostics[0].line == 9
    assert diagnostics[0].message == "Parse Error: the validated script error."
