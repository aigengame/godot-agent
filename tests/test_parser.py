"""S2: the result parser implements the ADR-0002 sentinel contract."""

import json

import pytest

from gda.errors import parse_validate_diagnostics
from gda.parser import parse_result


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


def test_empty_payload_raises_descriptive_error():
    # A contract violation: the GDScript emitted adjacent sentinels with no
    # payload. The parser should say so, not leak an opaque JSONDecodeError.
    stdout = "noise\n<<<GDA:RESULT>>>   <<<GDA:END>>>\n"

    with pytest.raises(ValueError, match="empty GDA result payload"):
        parse_result(stdout)


def test_payload_containing_end_sentinel_round_trips():
    # issue #34: the result payload echoes user-controlled content (a path, and
    # later node names / script source). If that content contains the literal
    # end sentinel, extraction must still recover the whole payload — the real
    # terminator is the LAST end sentinel, not the first.
    payload = {"path": "res://weird<<<GDA:END>>>name.tscn", "root_type": "Node2D"}
    stdout = f"<<<GDA:RESULT>>>{json.dumps(payload)}<<<GDA:END>>>\n"

    assert parse_result(stdout) == payload


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
    stderr = (
        'SCRIPT ERROR: Parse Error: Unexpected "Identifier" in class body.\n'
        "          at: GDScript::reload (gdscript://-123.gd:5)\n"
        "   0: [gdscript] operations.gd:_op_script_validate(...) at line 700\n"
        "   1: [gdscript] operations.gd:_initialize(...) at line 60\n"
    )

    diagnostics = parse_validate_diagnostics(stderr)

    assert len(diagnostics) == 1
    assert diagnostics[0].line == 5
    assert diagnostics[0].message == 'Parse Error: Unexpected "Identifier" in class body.'
