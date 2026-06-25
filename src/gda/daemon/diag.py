"""Parse a gda-daemon-owned Session log into structured runtime diagnostics (#224).

A pure function over a Godot engine log file's text — no daemon, no engine — so
``gda diag`` is fast-unit-testable. The daemon launches each Engine session with
``--log-file <session path>`` (ADR: runtime-diagnostics-via-daemon-owned-session-
log) and serves ``diag`` daemon-side by reading that one file, which captures
BOTH the game's print output and its errors.

Godot writes an error as a two-line pair (verified against the engine's
``core/io/logger.cpp`` ``Logger::log_error``)::

    <TYPE>: <message>
       at: <function> (<file>:<line>)

where ``<TYPE>`` is one of ``ERROR`` / ``WARNING`` / ``SCRIPT ERROR`` /
``SHADER ERROR``. Print output is plain lines. A runtime GDScript error carries
a multi-line call stack after the ``at:`` line — a ``GDScript backtrace (most
recent call first):`` marker then one ``[N] <function> (<file>:<line>)`` frame
line per stack frame (#283); ``parse_errors`` folds those frames into the
error's ordered ``callstack`` (frame ``[0]`` equals the ``at:`` location).

The parsing is **best-effort**: a line that is neither a recognized ``<TYPE>:``
header nor the ``   at:`` follow-on (a backtrace, an interleaved print line) is
skipped for ``errors`` and never raises. ``log`` keeps every line verbatim.
"""

import json
import re

# A ``<TYPE>: <message>`` header. The TYPE strings come straight from the engine's
# ``Logger::error_type_string`` — kept anchored to line start so a print line that
# merely contains the word "ERROR" is not mistaken for an error header.
_ERROR_HEADER = re.compile(r"^(ERROR|WARNING|SCRIPT ERROR|SHADER ERROR): (.*)$")

# The engine's follow-on location line: ``   at: <function> (<file>:<line>)``.
# Leading whitespace varies by ErrorType indent, so it is matched loosely.
_AT_LINE = re.compile(r"^\s*at:\s*(?P<function>.*?)\s*\((?P<file>.*):(?P<line>\d+)\)\s*$")

# After the ``at:`` line, a runtime GDScript error MAY carry a full call stack:
# a marker line ``GDScript backtrace (most recent call first):`` then one frame
# line per stack frame, ``       [N] <function> (<file>:<line>)`` (verified
# against Godot 4.6.3). Frames are ordered most-recent-first; frame ``[0]``
# equals the ``at:`` location. push_error / warnings carry no backtrace.
_BACKTRACE_MARKER = re.compile(r"^\s*GDScript backtrace\b.*:\s*$")
_FRAME_LINE = re.compile(
    r"^\s*\[\d+\]\s*(?P<function>.*?)\s*\((?P<file>.*):(?P<line>\d+)\)\s*$"
)

# The engine ``<TYPE>`` string -> the normalized, machine-stable ``level``.
_LEVEL_BY_TYPE = {
    "ERROR": "error",
    "WARNING": "warning",
    "SCRIPT ERROR": "script_error",
    "SHADER ERROR": "shader_error",
}


def _as_text(data: str | bytes) -> str:
    """Decode bytes best-effort; pass text through (never raises on bad UTF-8)."""
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data


def _lines(data: str | bytes) -> list[str]:
    text = _as_text(data)
    if not text:
        return []
    return text.splitlines()


def parse_errors(data: str | bytes, limit: int | None = None) -> list[dict]:
    """Structured errors from a Session log's text — best-effort (#224).

    Returns ``{level, message, function, file, line, callstack}`` per recognized
    error header (warnings included, distinguished by ``level``). The optional
    ``at:`` follow-on fills ``function``/``file``/``line``; absent, they are
    ``None`` (a bare error without a location is not a failure). ``callstack`` is
    the ordered ``{function, file, line}`` frames from the optional ``GDScript
    backtrace`` block (most-recent-first; frame ``[0]`` equals the ``at:``
    location); a push_error / warning carries no backtrace, so ``callstack`` is
    ``[]``. Unrecognized/continuation lines (interleaved print output) are
    skipped. ``limit`` tails the most recent ``N`` errors. Empty input -> ``[]``.
    """
    lines = _lines(data)
    errors: list[dict] = []
    i = 0
    while i < len(lines):
        header = _ERROR_HEADER.match(lines[i])
        if header is None:
            i += 1
            continue
        type_str, message = header.group(1), header.group(2)
        entry: dict = {
            "level": _LEVEL_BY_TYPE[type_str],
            "message": message,
            "function": None,
            "file": None,
            "line": None,
            "callstack": [],
        }
        # The next line MAY be the engine's ``at:`` location follow-on; if so,
        # consume it. Anything else (the next header, an output line) is left for
        # the next iteration.
        if i + 1 < len(lines):
            at = _AT_LINE.match(lines[i + 1])
            if at is not None:
                entry["function"] = at.group("function") or None
                entry["file"] = at.group("file") or None
                entry["line"] = int(at.group("line"))
                i += 1
        # After the ``at:`` line, the engine MAY emit a ``GDScript backtrace``
        # marker followed by ``[N] func (file:line)`` frame lines. Consume the
        # marker and every contiguous frame line into ``callstack``; a non-frame
        # line (the next header, a print line) ends the block, left for the next
        # iteration.
        if i + 1 < len(lines) and _BACKTRACE_MARKER.match(lines[i + 1]):
            i += 1
            while i + 1 < len(lines):
                frame = _FRAME_LINE.match(lines[i + 1])
                if frame is None:
                    break
                entry["callstack"].append(
                    {
                        "function": frame.group("function") or None,
                        "file": frame.group("file") or None,
                        "line": int(frame.group("line")),
                    }
                )
                i += 1
        errors.append(entry)
        i += 1
    if limit is not None and limit >= 0:
        return errors[-limit:] if limit else []
    return errors


def parse_log(data: str | bytes, limit: int | None = None) -> list[str]:
    """The raw captured output lines from a Session log — minimal parsing (#224).

    The full captured stream (print output AND error lines) verbatim, one entry
    per line. ``limit`` tails the most recent ``N`` lines. Empty input -> ``[]``.
    """
    lines = _lines(data)
    if limit is not None and limit >= 0:
        return lines[-limit:] if limit else []
    return lines


# --- The structured `LogRecord` channel (#281, ADR-0026) -----------------------
#
# The PASSIVE, non-invasive floor: parse the WHOLE Session log into typed
# `LogRecord`s. Engine errors/warnings come from `parse_errors` above (reused
# verbatim — this code is purely additive); every OTHER captured line becomes a
# plain `info` record. An un-instrumented project gets structured logs for free.
# Overlaid on it is the ACTIVE, opt-in rich `gda_log()` protocol (#282): a line
# beginning with the `<<<GDA:LOG>>>` marker carries the app's own structured record.

# The active-layer marker (#282, ADR-0026 decision 2). A `gda_log()` call emits one
# `<<<GDA:LOG>>>{json}` line into the Session log; the parser recognises the prefix
# and decodes the JSON into a field-carrying record. A SEPARATE marker family from
# ADR-0002's single `<<<GDA:RESULT>>>` (gda.parser.RESULT_BEGIN), so a log line is
# never mistaken for an op result and a result-shaped print is never a log record.
# Mirrors the harness `LOG_MARKER` const (src/gda/harness/gda_harness.gd); a const
# test (tests/test_error_registry.py) keeps the two byte-identical.
LOG_BEGIN = "<<<GDA:LOG>>>"

# The closed, ordered severity enum (ADR-0026): `debug < info < warning < error`.
# A record's rank is its index, so `--level <min>` is a well-defined `>=` filter.
_LEVEL_ORDER = ("debug", "info", "warning", "error")
_LEVEL_RANK = {name: i for i, name in enumerate(_LEVEL_ORDER)}

# Map a `parse_errors` diag `level` onto the closed `LogRecord` (level, origin)
# pair: the engine's finer kinds collapse onto the enum, with the sub-kind kept
# in `origin` (ADR-0026). `SCRIPT ERROR` / `SHADER ERROR` are still `error` level;
# only `origin` tells them apart.
_DIAG_LEVEL_TO_RECORD = {
    "error": ("error", "engine"),
    "warning": ("warning", "engine"),
    "script_error": ("error", "script"),
    "shader_error": ("error", "shader"),
}


def parse_log_records(
    data: str | bytes,
    level: str | None = None,
    limit: int | None = None,
    raw: bool = False,
) -> list[dict]:
    """The whole Session log as structured ``LogRecord`` dicts (#281/#282, ADR-0026).

    The structured runtime-log channel, two layers overlaid (ADR-0026 decision 2).
    EVERY captured line becomes a typed record, so the structured stream represents
    the whole Session log losslessly. Per line:

    - A line beginning with the active-layer ``<<<GDA:LOG>>>`` marker (#282) is an
      opt-in ``gda_log()`` record: the JSON after the marker is decoded into a
      field-carrying record carrying the app-supplied ``level`` (clamped to the
      closed enum, defaulting to ``info``), ``message``, and ``fields``, with
      ``origin = gda_log`` and no ``source`` frame. Malformed JSON never raises —
      the whole line degrades to a plain ``info`` record (best-effort).
    - An engine error/warning (recognized by the same two-line format
      :func:`parse_errors` reads) yields a typed record carrying its normalized
      ``level`` (mapped onto the closed enum), an ``origin`` sub-kind (``engine`` /
      ``script`` / ``shader``), and a ``source`` ``{function, file, line}`` frame
      when the log recorded an ``at:`` line; the ``at:`` follow-on is folded into
      ``source`` rather than re-emitted.
    - Every OTHER line — game output, the engine banner, AND the indented ``GDScript
      backtrace`` continuation lines that follow an error — becomes a plain ``info``
      record (nothing is dropped).

    Each record carries a monotonic ``seq`` in capture order; a passively-parsed
    record's ``fields`` is a present-but-empty object (populated only by the opt-in
    #282 protocol).

    With ``raw`` set, classification is skipped entirely: every captured line
    becomes a plain ``info`` record carrying its verbatim text (the view the
    superseded ``diag log`` returned, now uniformly typed as ``LogRecord[]``) —
    even an error header or a ``<<<GDA:LOG>>>`` line stays a verbatim ``info`` line.

    ``level`` filters by minimum severity over the closed ordering
    ``debug < info < warning < error`` (e.g. ``"warning"`` drops ``info`` and
    ``debug``); an unknown value disables the filter. ``limit`` tails the most
    recent ``N`` records AFTER the level filter. Best-effort and pure: empty input
    -> ``[]``; it never raises on a malformed/continuation line or bad UTF-8.
    """
    lines = _lines(data)
    records: list[dict] = []
    seq = 0

    if raw:
        # `--raw`: no classification — each captured line is a verbatim `info`
        # record (the superseded `diag log` view, uniformly typed as LogRecord[]).
        for line in lines:
            records.append(_info_record(seq, line))
            seq += 1
    else:
        # An engine error/warning header (+ its optional `at:` follow-on) becomes
        # ONE typed record via `parse_errors` (single-sourced level/source); the
        # `at:` line is folded into `source`. EVERY other line — including the
        # `GDScript backtrace` continuation lines after an error — becomes a plain
        # `info` record, so the whole log is represented (ADR-0026 decision 2).
        i = 0
        n = len(lines)
        while i < n:
            # The active opt-in layer (#282): a `<<<GDA:LOG>>>` line is a rich
            # `gda_log()` record. Checked FIRST so an app's own structured record
            # is never re-classified as engine output. Best-effort: malformed JSON
            # degrades to a plain `info` record (see `_gda_log_record`).
            if lines[i].startswith(LOG_BEGIN):
                records.append(_gda_log_record(seq, lines[i]))
                seq += 1
                i += 1
                continue
            if _ERROR_HEADER.match(lines[i]) is None:
                records.append(_info_record(seq, lines[i]))
                seq += 1
                i += 1
                continue
            block = lines[i]
            consumed = 1
            if i + 1 < n and _AT_LINE.match(lines[i + 1]) is not None:
                block += "\n" + lines[i + 1]
                consumed += 1
            # `parse_errors` yields exactly one entry for a single header.
            records.append(_error_record(seq, parse_errors(block)[0]))
            seq += 1
            i += consumed

    if level is not None and level in _LEVEL_RANK:
        floor = _LEVEL_RANK[level]
        records = [r for r in records if _LEVEL_RANK[r["level"]] >= floor]

    if limit is not None and limit >= 0:
        return records[-limit:] if limit else []
    return records


def _info_record(seq: int, message: str) -> dict:
    """A plain captured line as an ``info`` ``LogRecord`` (#281)."""
    return {
        "seq": seq,
        "level": "info",
        "message": message,
        "source": None,
        "origin": None,
        "fields": {},
    }


def _error_record(seq: int, entry: dict) -> dict:
    """A ``parse_errors`` entry as a typed error/warning ``LogRecord`` (#281)."""
    rec_level, origin = _DIAG_LEVEL_TO_RECORD.get(entry["level"], ("error", "engine"))
    # A `source` frame only when the engine logged an `at:` location; a bare error
    # (no follow-on) leaves `source` null rather than an all-null frame.
    has_location = any(entry.get(k) is not None for k in ("function", "file", "line"))
    source = (
        {"function": entry.get("function"), "file": entry.get("file"), "line": entry.get("line")}
        if has_location
        else None
    )
    return {
        "seq": seq,
        "level": rec_level,
        "message": entry["message"],
        "source": source,
        "origin": origin,
        "fields": {},
    }


def _gda_log_record(seq: int, line: str) -> dict:
    """A ``<<<GDA:LOG>>>{json}`` line as a rich ``gda_log`` ``LogRecord`` (#282).

    Decodes the JSON after the marker into a field-carrying record: the app-supplied
    ``level`` (clamped to the closed enum, defaulting to ``info`` when missing or
    unknown), ``message``, and ``fields``, with ``origin = gda_log`` and no engine
    ``source`` frame. Best-effort and never raises: a malformed payload (bad JSON, a
    non-object, wrong-typed members) degrades to a plain ``info`` record carrying the
    line verbatim, so a corrupt opt-in line can never break the passive stream.
    """
    payload_text = line[len(LOG_BEGIN) :]
    try:
        payload = json.loads(payload_text)
    except (ValueError, TypeError):
        return _info_record(seq, line)
    if not isinstance(payload, dict):
        return _info_record(seq, line)

    level = payload.get("level")
    if not isinstance(level, str) or level not in _LEVEL_RANK:
        level = "info"
    message = payload.get("message")
    if not isinstance(message, str):
        message = ""
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    return {
        "seq": seq,
        "level": level,
        "message": message,
        "source": None,
        "origin": "gda_log",
        "fields": fields,
    }
