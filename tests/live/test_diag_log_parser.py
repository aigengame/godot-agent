"""The Session-log parser: bytes/text -> structured diagnostics (#224).

A pure function over a Godot engine log file's text — no daemon, no engine — so
the diag parse logic is fast-unit-testable. Godot writes errors as a two-line
pair (``<TYPE>: <message>`` then ``   at: <function> (<file>:<line>)``) and
print output as plain lines, both into the one ``--log-file`` the daemon owns
(verified against the engine's ``core/io/logger.cpp``). The parser turns errors
into ``{level, message, function?, file?, line?}``, best-effort: it never fails
on a malformed/continuation line.
"""

from gda.daemon.diag import parse_errors

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


# A real Godot 4.6 runtime GDScript error: the `at:` follow-on is succeeded by a
# `GDScript backtrace (most recent call first):` marker, then one `[N] func
# (file:line)` frame line per stack frame (verified against Godot 4.6.3). Frames
# are ordered most-recent-first. The `at:` frame equals frame `[0]` FOR THIS
# CLASS — GDScript itself raised the error, at the failing statement — which is
# not the general rule; see MIXED_RAISER_LOG below (#722).
BACKTRACE_LOG = """\
SCRIPT ERROR: Invalid call. Nonexistent function 'do_thing' in base 'Nil'.
   at: b (res://main.gd:9)
   GDScript backtrace (most recent call first):
       [0] b (res://main.gd:9)
       [1] a (res://main.gd:6)
       [2] _ready (res://main.gd:3)
"""


def test_parse_errors_extracts_the_ordered_callstack_frames():
    errors = parse_errors(BACKTRACE_LOG)
    assert len(errors) == 1
    callstack = errors[0]["callstack"]
    assert callstack == [
        {"function": "b", "file": "res://main.gd", "line": 9},
        {"function": "a", "file": "res://main.gd", "line": 6},
        {"function": "_ready", "file": "res://main.gd", "line": 3},
    ]


def test_parse_errors_top_frame_fields_match_the_at_line_unchanged():
    # The existing single-frame {function,file,line} fields stay the `at:` location
    # and are unchanged by the callstack enrichment. They also equal frame [0] here
    # because GDScript raised this error itself — a property of THIS record, not of
    # every record (#722).
    error = parse_errors(BACKTRACE_LOG)[0]
    assert error["function"] == "b"
    assert error["file"] == "res://main.gd"
    assert error["line"] == 9
    assert error["callstack"][0] == {
        "function": error["function"],
        "file": error["file"],
        "line": error["line"],
    }


# One real Godot 4.6.3 headless capture holding BOTH raiser shapes, so the
# relation between `at:` and frame `[0]` is pinned by evidence rather than by the
# assumption the docs used to carry. Reproduced (#722) from a scene whose
# `_ready` calls `_inner()` (which calls `push_error`) and then `_boom()` (which
# calls a method on null). The differing indentation is the engine's own
# ErrorType indent, kept verbatim.
MIXED_RAISER_LOG = """\
ERROR: probe: invariant violated
   at: push_error (core/variant/variant_utility.cpp:1024)
   GDScript backtrace (most recent call first):
       [0] _inner (res://main.gd:10)
       [1] _ready (res://main.gd:5)
SCRIPT ERROR: Invalid call. Nonexistent function 'do_thing' in base 'Nil'.
          at: _boom (res://main.gd:15)
          GDScript backtrace (most recent call first):
              [0] _boom (res://main.gd:15)
              [1] _ready (res://main.gd:6)
"""


def test_parse_errors_frame_zero_is_not_the_at_line_for_a_push_error():
    # The corrected contract (#722): `at:` is where the error was RAISED, the
    # backtrace is where the SCRIPT was, and for a `push_error` those are two
    # different places — the engine's own C++ `VariantUtilityFunctions::push_error`
    # versus the .gd line that called it. An implementation that folded one into
    # the other (synthesizing frame [0] from `at:`, or overwriting the top fields
    # from frame [0]) would lose the project's only script attribution.
    raised_by_engine, raised_by_gdscript = parse_errors(MIXED_RAISER_LOG)

    at_location = {
        "function": raised_by_engine["function"],
        "file": raised_by_engine["file"],
        "line": raised_by_engine["line"],
    }
    assert at_location == {
        "function": "push_error",
        "file": "core/variant/variant_utility.cpp",
        "line": 1024,
    }
    assert raised_by_engine["callstack"][0] == {
        "function": "_inner",
        "file": "res://main.gd",
        "line": 10,
    }
    # The point of the regression: the two locations differ in every field.
    assert raised_by_engine["callstack"][0] != at_location

    # And the counterpart class in the same capture, where they DO coincide —
    # which is why the unconditional claim looked true for so long.
    assert raised_by_gdscript["callstack"][0] == {
        "function": raised_by_gdscript["function"],
        "file": raised_by_gdscript["file"],
        "line": raised_by_gdscript["line"],
    }


def test_parse_errors_callstack_is_empty_for_a_bare_error():
    # An error raised outside any GDScript call stack carries NO backtrace; its
    # callstack is an empty list (not an error, not a one-frame synthesis).
    # NOT a push_error, which does carry one on the build gda drives (#722) — the
    # earlier name for this test claimed the opposite.
    errors = parse_errors("ERROR: bare error\n   at: f (res://a.gd:1)\n")
    assert errors[0]["callstack"] == []


def test_parse_errors_callstack_empty_when_no_at_line_either():
    errors = parse_errors("ERROR: trailing error with no at line\n")
    assert errors[0]["callstack"] == []


def test_parse_errors_backtrace_consumption_stops_before_the_next_error():
    # An error WITH a backtrace immediately followed by ANOTHER error header: the
    # frame-consuming loop must stop at the next header and not swallow it, so the
    # second error is parsed independently with its own (empty) callstack.
    log = BACKTRACE_LOG + "ERROR: second error\n   at: g (res://b.gd:2)\n"
    errors = parse_errors(log)
    assert len(errors) == 2
    assert (
        errors[0]["message"]
        == "Invalid call. Nonexistent function 'do_thing' in base 'Nil'."
    )
    assert len(errors[0]["callstack"]) == 3
    assert errors[1]["message"] == "second error"
    assert errors[1]["function"] == "g"
    assert errors[1]["callstack"] == []


def test_parse_errors_backtrace_consumption_stops_before_a_print_line():
    # An interleaved print line after the frames ends the backtrace; it is neither
    # a frame nor an error and must not be folded into the callstack.
    log = BACKTRACE_LOG + "an ordinary print line\n"
    errors = parse_errors(log)
    assert len(errors) == 1
    assert len(errors[0]["callstack"]) == 3
    assert all("print" not in (f["function"] or "") for f in errors[0]["callstack"])


def test_parse_errors_existing_entries_gain_an_empty_callstack_key():
    # Every entry from the original (backtrace-free) SAMPLE_LOG now carries a
    # callstack key — empty, since none of those errors has a GDScript backtrace.
    for error in parse_errors(SAMPLE_LOG):
        assert error["callstack"] == []
