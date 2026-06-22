"""The Session-log parser: bytes/text -> structured diagnostics (#224).

A pure function over a Godot engine log file's text — no daemon, no engine — so
the diag parse logic is fast-unit-testable. Godot writes errors as a two-line
pair (``<TYPE>: <message>`` then ``   at: <function> (<file>:<line>)``) and
print output as plain lines, both into the one ``--log-file`` the daemon owns
(verified against the engine's ``core/io/logger.cpp``). The parser turns errors
into ``{level, message, function?, file?, line?}`` and ``log`` into raw lines,
best-effort: it never fails on a malformed/continuation line.
"""

from gda.daemon.diag import parse_errors, parse_log

# A realistic Godot --log-file capture: print output interleaved with the engine's
# two-line error pairs across all four ErrorType strings, a multi-line backtrace,
# and a trailing bare ERROR line with no at-line.
SAMPLE_LOG = """\
Godot Engine v4.6.stable.official - https://godotengine.org
known line
ERROR: known error
   at: _ready (res://main.gd:12)
WARNING: a warning happened
   at: _process (res://main.gd:20)
SCRIPT ERROR: a script error
   at: do_thing (res://player.gd:7)
   <Stack trace> player.gd:7 @ do_thing()
SHADER ERROR: a shader error
   at: compile (res://wave.gdshader:3)
another output line
ERROR: trailing error with no at line
"""


def test_parse_errors_extracts_all_four_levels_with_at_lines():
    errors = parse_errors(SAMPLE_LOG)
    levels = [e["level"] for e in errors]
    assert "error" in levels
    assert "warning" in levels  # warnings are included, distinguished by level
    assert "script_error" in levels
    assert "shader_error" in levels


def test_parse_errors_normalizes_type_to_level_and_keeps_message():
    errors = parse_errors(SAMPLE_LOG)
    first = errors[0]
    assert first["level"] == "error"
    assert first["message"] == "known error"
    assert first["function"] == "_ready"
    assert first["file"] == "res://main.gd"
    assert first["line"] == 12


def test_parse_errors_handles_script_error_two_word_type():
    errors = parse_errors(SAMPLE_LOG)
    script = next(e for e in errors if e["level"] == "script_error")
    assert script["message"] == "a script error"
    assert script["function"] == "do_thing"
    assert script["file"] == "res://player.gd"
    assert script["line"] == 7


def test_parse_errors_folds_or_skips_continuation_lines_without_failing():
    # The "<Stack trace>" backtrace line is neither a TYPE line nor an at-line; the
    # parser must not crash and must not invent an error from it.
    errors = parse_errors(SAMPLE_LOG)
    assert all("Stack trace" not in e["message"] for e in errors)


def test_parse_errors_tolerates_a_trailing_error_without_an_at_line():
    errors = parse_errors(SAMPLE_LOG)
    trailing = errors[-1]
    assert trailing["level"] == "error"
    assert trailing["message"] == "trailing error with no at line"
    # No at-line: function/file/line are absent (None), not a parse failure.
    assert trailing.get("function") is None
    assert trailing.get("file") is None
    assert trailing.get("line") is None


def test_parse_errors_accepts_bytes_and_decodes_best_effort():
    errors = parse_errors(b"ERROR: bytes error\n   at: f (res://a.gd:1)\n")
    assert errors[0]["message"] == "bytes error"
    assert errors[0]["level"] == "error"


def test_parse_errors_never_fails_on_garbage():
    # Pure noise / non-Godot lines yield no errors rather than raising.
    assert parse_errors("just some unrelated text\nno markers here\n") == []
    assert parse_errors(b"\xff\xfe not utf8 \x00") == []


def test_parse_errors_limit_tails_the_most_recent_n():
    errors = parse_errors(SAMPLE_LOG, limit=2)
    assert len(errors) == 2
    # The last two are the shader error and the trailing bare error.
    assert errors[-1]["message"] == "trailing error with no at line"
    assert errors[0]["level"] == "shader_error"


def test_parse_errors_empty_input_is_empty_list():
    assert parse_errors("") == []
    assert parse_errors(b"") == []


def test_parse_log_returns_raw_lines():
    lines = parse_log(SAMPLE_LOG)
    assert "known line" in lines
    assert "another output line" in lines
    # It is the full captured stream, including the error lines verbatim.
    assert any(line.startswith("ERROR: known error") for line in lines)


def test_parse_log_limit_tails_the_most_recent_n():
    lines = parse_log(SAMPLE_LOG, limit=1)
    assert lines == ["ERROR: trailing error with no at line"]


def test_parse_log_accepts_bytes_and_is_empty_on_empty():
    assert parse_log(b"a\nb\n") == ["a", "b"]
    assert parse_log("") == []
    assert parse_log(b"") == []
