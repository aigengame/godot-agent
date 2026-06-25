"""The Session-log -> structured `LogRecord` parser (#281, ADR-0026).

`parse_log_records` is the PASSIVE, non-invasive floor of the structured
runtime-log channel: a pure function over a Godot engine log file's text — no
daemon, no engine — so the logic is fast-unit-testable. It reuses the existing
`parse_errors` for the engine's two-line error/warning pairs (carrying the
`source` frame) and turns every other captured line into a plain `info` record.

Each yielded record is the ADR-0026 `LogRecord` dict shape: `{seq, level,
message, source?, origin?, fields}` where `level` is the closed, ordered enum
`debug < info < warning < error`. The engine's finer kinds map onto it — WARNING
-> (warning, origin=engine); ERROR -> (error, engine); SCRIPT ERROR -> (error,
script); SHADER ERROR -> (error, shader) — with the sub-kind preserved in
`origin`. `--level <min>` filters by minimum severity; `--limit N` tails the
most-recent-N.
"""

import json

from gda.daemon.diag import LOG_BEGIN, parse_log_records
from gda.parser import RESULT_BEGIN

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


def _by_message(records, needle):
    return next(r for r in records if needle in r["message"])


def test_plain_lines_become_info_records():
    records = parse_log_records(SAMPLE_LOG)
    known = _by_message(records, "known line")
    assert known["level"] == "info"
    # An info line has no engine source/origin; fields is present-but-empty (#282).
    assert known["origin"] is None
    assert known["source"] is None
    assert known["fields"] == {}


def test_engine_error_is_an_error_record_with_engine_origin_and_source():
    records = parse_log_records(SAMPLE_LOG)
    err = _by_message(records, "known error")
    assert err["level"] == "error"
    assert err["origin"] == "engine"
    assert err["source"] == {"function": "_ready", "file": "res://main.gd", "line": 12}


def test_engine_warning_maps_to_warning_level_engine_origin():
    records = parse_log_records(SAMPLE_LOG)
    warn = _by_message(records, "a warning happened")
    assert warn["level"] == "warning"
    assert warn["origin"] == "engine"
    assert warn["source"]["function"] == "_process"


def test_script_error_maps_to_error_level_script_origin():
    # ADR-0026: SCRIPT ERROR -> (level=error, origin=script) — the closed enum has
    # no `script_error`; the sub-kind lives in `origin`.
    records = parse_log_records(SAMPLE_LOG)
    rec = _by_message(records, "a script error")
    assert rec["level"] == "error"
    assert rec["origin"] == "script"
    assert rec["source"]["file"] == "res://player.gd"


def test_shader_error_maps_to_error_level_shader_origin():
    records = parse_log_records(SAMPLE_LOG)
    rec = _by_message(records, "a shader error")
    assert rec["level"] == "error"
    assert rec["origin"] == "shader"


def test_trailing_error_without_an_at_line_has_no_source():
    records = parse_log_records(SAMPLE_LOG)
    rec = _by_message(records, "trailing error with no at line")
    assert rec["level"] == "error"
    assert rec["origin"] == "engine"
    assert rec["source"] is None


def test_records_carry_a_monotonic_seq_in_capture_order():
    records = parse_log_records(SAMPLE_LOG)
    seqs = [r["seq"] for r in records]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)  # unique
    # The first captured line is the engine banner (an info record).
    assert records[0]["message"].startswith("Godot Engine")


def test_the_two_line_error_pair_yields_one_record_not_two():
    # The `   at:` follow-on is folded into the error's `source`, NOT emitted as a
    # second info record — so the location line never appears as its own message.
    records = parse_log_records(SAMPLE_LOG)
    assert not any(r["message"].lstrip().startswith("at:") for r in records)


def test_continuation_backtrace_line_becomes_an_info_record():
    # ADR-0026 decision 2 (amended #281): the WHOLE Session log is represented. The
    # `<Stack trace>` continuation line after an error is NOT dropped — it becomes a
    # plain `info` record. The error's `at:` is still folded into its `source`, but
    # the backtrace lines stay in the stream so `logger tail` is the full log.
    records = parse_log_records(SAMPLE_LOG)
    trace = _by_message(records, "Stack trace")
    assert trace["level"] == "info"
    assert trace["source"] is None
    assert trace["origin"] is None


def test_raw_returns_every_line_as_a_verbatim_info_record():
    # `raw=True` skips classification entirely: every captured line — even an
    # `ERROR:`/`WARNING:` header — is a verbatim `info` record (still LogRecord[]),
    # the uniformly-typed form of the superseded `diag log` view.
    records = parse_log_records(SAMPLE_LOG, raw=True)
    assert all(r["level"] == "info" and r["source"] is None for r in records)
    messages = [r["message"] for r in records]
    assert "ERROR: known error" in messages  # the header is verbatim, not classified
    assert "known line" in messages
    assert len(records) == len(SAMPLE_LOG.splitlines())


def test_level_filter_excludes_lower_severities():
    # The closed ordering debug < info < warning < error makes `--level warning`
    # drop info (and debug) while keeping warning + error.
    records = parse_log_records(SAMPLE_LOG, level="warning")
    levels = {r["level"] for r in records}
    assert "info" not in levels
    assert "warning" in levels
    assert "error" in levels


def test_level_filter_error_keeps_only_errors():
    records = parse_log_records(SAMPLE_LOG, level="error")
    assert {r["level"] for r in records} == {"error"}


def test_level_filter_info_keeps_everything_at_or_above_info():
    records = parse_log_records(SAMPLE_LOG, level="info")
    # No debug lines in the sample, so info is the floor: nothing is dropped.
    assert len(records) == len(parse_log_records(SAMPLE_LOG))


def test_limit_tails_the_most_recent_n():
    records = parse_log_records(SAMPLE_LOG, limit=2)
    assert len(records) == 2
    assert records[-1]["message"] == "trailing error with no at line"


def test_limit_applies_after_the_level_filter():
    # `--limit` tails the FILTERED stream, not the raw one: the most-recent-N of
    # the records that passed `--level`.
    records = parse_log_records(SAMPLE_LOG, level="error", limit=1)
    assert len(records) == 1
    assert records[0]["message"] == "trailing error with no at line"


def test_accepts_bytes_and_decodes_best_effort():
    records = parse_log_records(b"hello\nERROR: boom\n   at: f (res://a.gd:1)\n")
    assert _by_message(records, "hello")["level"] == "info"
    assert _by_message(records, "boom")["level"] == "error"


def test_empty_input_is_an_empty_list():
    assert parse_log_records("") == []
    assert parse_log_records(b"") == []


def test_never_fails_on_garbage():
    # Pure noise still parses (every line is an info record); bad UTF-8 is replaced.
    assert parse_log_records("just text\nmore text\n")  # non-empty, no raise
    assert isinstance(parse_log_records(b"\xff\xfe not utf8 \x00"), list)


# --- The opt-in rich `gda_log()` protocol (#282, ADR-0026 decision 2) -----------
#
# The ACTIVE layer: the harness emits one `<<<GDA:LOG>>>{json}` line per gda_log()
# call. The parser recognises the marker and turns it into a field-carrying
# `LogRecord` with the supplied level/message/fields and origin=gda_log. The marker
# is DISTINCT from ADR-0002's `<<<GDA:RESULT>>>` so a log line is never an op result
# and a result-shaped print is never a log record.


def _gda_log_line(level, message, fields=None):
    payload = {"level": level, "message": message, "fields": fields or {}}
    return LOG_BEGIN + json.dumps(payload)


def test_gda_log_line_becomes_a_rich_record():
    line = _gda_log_line("warning", "hi", {"k": 1})
    rec = parse_log_records(line + "\n")[0]
    assert rec["level"] == "warning"
    assert rec["message"] == "hi"
    assert rec["fields"] == {"k": 1}
    assert rec["origin"] == "gda_log"


def test_gda_log_record_carries_no_source_frame():
    rec = parse_log_records(_gda_log_line("info", "x", {}) + "\n")[0]
    assert rec["source"] is None


def test_gda_log_default_level_is_info_when_unset():
    # A malformed/partial payload still yields a record; a missing `level` falls
    # back to `info` (the safe floor) rather than raising.
    line = LOG_BEGIN + json.dumps({"message": "no level here"})
    rec = parse_log_records(line + "\n")[0]
    assert rec["level"] == "info"
    assert rec["message"] == "no level here"
    assert rec["origin"] == "gda_log"


def test_gda_log_unknown_level_falls_back_to_info():
    # A value outside the closed enum is not propagated verbatim; it degrades to
    # `info` so the record's `level` is always a valid LogLevel.
    rec = parse_log_records(_gda_log_line("loud", "x", {}) + "\n")[0]
    assert rec["level"] == "info"


def test_malformed_gda_log_line_is_a_best_effort_info_record():
    # Malformed JSON after the marker never raises: the whole line degrades to a
    # plain `info` record carrying its verbatim text (best-effort).
    line = LOG_BEGIN + "{not valid json"
    records = parse_log_records(line + "\n")
    assert len(records) == 1
    rec = records[0]
    assert rec["level"] == "info"
    assert rec["fields"] == {}
    assert line in rec["message"]


def test_gda_log_line_is_never_misparsed_as_an_op_result():
    # The `<<<GDA:LOG>>>` marker is distinct from `<<<GDA:RESULT>>>`: a log line
    # carries the LOG marker, never the RESULT marker, so the result parser never
    # claims it.
    line = _gda_log_line("info", "hello", {})
    assert RESULT_BEGIN not in line
    assert LOG_BEGIN != RESULT_BEGIN


def test_a_plain_print_of_result_shaped_text_is_not_a_log_record():
    # A game that prints `<<<GDA:RESULT>>>...`-shaped text is plain output: it does
    # NOT begin with the LOG marker, so it stays a plain `info` record (never a
    # rich gda_log record).
    line = RESULT_BEGIN + json.dumps({"foo": "bar"})
    rec = parse_log_records(line + "\n")[0]
    assert rec["level"] == "info"
    assert rec["origin"] is None
    assert rec["message"] == line


def test_raw_keeps_a_gda_log_line_as_a_verbatim_info_record():
    # Under `raw=True` classification is skipped entirely: a `<<<GDA:LOG>>>` line
    # stays a verbatim `info` record (consistent with #281's raw view), NOT a
    # decoded rich record.
    line = _gda_log_line("error", "boom", {"k": 1})
    records = parse_log_records(line + "\n", raw=True)
    assert len(records) == 1
    rec = records[0]
    assert rec["level"] == "info"
    assert rec["message"] == line
    assert rec["fields"] == {}
    assert rec["origin"] is None


def test_gda_log_records_compose_with_engine_and_plain_lines():
    # The two layers compose per line: a `<<<GDA:LOG>>>` line -> rich record; an
    # engine error -> typed record; every other line -> plain info (ADR-0026).
    log = (
        _gda_log_line("warning", "rich one", {"k": 1}) + "\n"
        "plain output\n"
        "ERROR: boom\n"
        "   at: f (res://a.gd:3)\n"
    )
    records = parse_log_records(log)
    rich = _by_message(records, "rich one")
    assert rich["origin"] == "gda_log" and rich["fields"] == {"k": 1}
    assert _by_message(records, "plain output")["level"] == "info"
    assert _by_message(records, "boom")["level"] == "error"


def test_gda_log_level_participates_in_the_level_filter():
    # A rich record's level is a real LogLevel, so `--level warning` keeps a
    # warning gda_log record and drops an info one.
    log = (
        _gda_log_line("info", "low", {}) + "\n"
        + _gda_log_line("warning", "high", {}) + "\n"
    )
    records = parse_log_records(log, level="warning")
    messages = [r["message"] for r in records]
    assert "high" in messages
    assert "low" not in messages
