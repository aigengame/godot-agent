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
``SHADER ERROR``. Print output is plain lines. Some errors carry a multi-line
script backtrace after the ``at:`` line.

The parsing is **best-effort**: a line that is neither a recognized ``<TYPE>:``
header nor the ``   at:`` follow-on (a backtrace, an interleaved print line) is
skipped for ``errors`` and never raises. ``log`` keeps every line verbatim.
"""

import re

# A ``<TYPE>: <message>`` header. The TYPE strings come straight from the engine's
# ``Logger::error_type_string`` — kept anchored to line start so a print line that
# merely contains the word "ERROR" is not mistaken for an error header.
_ERROR_HEADER = re.compile(r"^(ERROR|WARNING|SCRIPT ERROR|SHADER ERROR): (.*)$")

# The engine's follow-on location line: ``   at: <function> (<file>:<line>)``.
# Leading whitespace varies by ErrorType indent, so it is matched loosely.
_AT_LINE = re.compile(r"^\s*at:\s*(?P<function>.*?)\s*\((?P<file>.*):(?P<line>\d+)\)\s*$")

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

    Returns ``{level, message, function, file, line}`` per recognized error
    header (warnings included, distinguished by ``level``). The optional ``at:``
    follow-on fills ``function``/``file``/``line``; absent, they are ``None`` (a
    bare error without a location is not a failure). Unrecognized/continuation
    lines (backtraces, interleaved print output) are skipped. ``limit`` tails the
    most recent ``N`` errors. Empty input -> ``[]``.
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
        }
        # The next line MAY be the engine's ``at:`` location follow-on; if so,
        # consume it. Anything else (a backtrace, the next header, an output
        # line) is left for the next iteration.
        if i + 1 < len(lines):
            at = _AT_LINE.match(lines[i + 1])
            if at is not None:
                entry["function"] = at.group("function") or None
                entry["file"] = at.group("file") or None
                entry["line"] = int(at.group("line"))
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
# The opt-in rich `gda_log()` protocol (the `<<<GDA:LOG>>>` marker) is a SEPARATE
# follow-up slice (#282) and is NOT parsed here.

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
    """The whole Session log as structured ``LogRecord`` dicts (#281, ADR-0026).

    The passive structured runtime-log channel: EVERY captured line becomes a
    typed record, so the structured stream represents the whole Session log
    losslessly (ADR-0026 decision 2). An engine error/warning (recognized by the
    same two-line format :func:`parse_errors` reads) yields a typed record carrying
    its normalized ``level`` (mapped onto the closed enum), an ``origin`` sub-kind
    (``engine`` / ``script`` / ``shader``), and a ``source`` ``{function, file,
    line}`` frame when the log recorded an ``at:`` line; the ``at:`` follow-on is
    folded into ``source`` rather than re-emitted. Every OTHER line — game output,
    the engine banner, AND the indented ``GDScript backtrace`` continuation lines
    that follow an error — becomes a plain ``info`` record (nothing is dropped).
    Each record carries a monotonic ``seq`` in capture order and a present-but-
    empty ``fields`` object (populated only by the opt-in #282 protocol).

    With ``raw`` set, classification is skipped entirely: every captured line
    becomes a plain ``info`` record carrying its verbatim text (the view the
    superseded ``diag log`` returned, now uniformly typed as ``LogRecord[]``) —
    even an error header stays a verbatim ``info`` line.

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
