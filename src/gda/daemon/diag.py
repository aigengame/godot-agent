"""Parse a gda-daemon-owned Session log into structured runtime diagnostics (#224).

A pure function over a Godot engine log file's text — no daemon, no engine — so
``gda diag`` is fast-unit-testable. The daemon launches each Engine session with
``--log-file <session path>`` (ADR: runtime-diagnostics-via-daemon-owned-session-
log) and serves ``diag`` daemon-side by reading that one file, which captures
BOTH the game's print output and its errors.

The engine's own error-line format — the two-line ``<TYPE>: <message>`` /
``   at: <function> (<file>:<line>)`` pair and its optional GDScript backtrace —
is parsed by :mod:`gda.engine_log`, which this module imports downward and
re-exports :func:`parse_errors` from. That parser was extracted from here (#651)
once a second consumer appeared: the format is the *engine's*, not the daemon's,
and the Phase-1 ``script run`` channel reads the same lines off a one-shot
process's stderr. What stays here is what is genuinely daemon-side: the
``LogRecord`` view of a whole Session log (ADR-0026), including the opt-in
``<<<GDA:LOG>>>`` protocol. The verbatim whole-log view is served by
:func:`parse_log_records` with ``raw`` set.
"""

import json

from gda.engine_log import (
    AT_LINE as _AT_LINE,
)
from gda.engine_log import (
    ERROR_HEADER as _ERROR_HEADER,
)
from gda.engine_log import (
    lines as _lines,
)
from gda.engine_log import (
    parse_errors,
)

# ``parse_errors`` is re-exported: it was this module's public API before the
# extraction (the daemon server and the diag tests import it from here), so the
# move stays source-compatible for every existing consumer.
__all__ = ["parse_errors", "parse_log_records", "LOG_BEGIN"]


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
# test (tests/cli/test_error_registry.py) keeps the two byte-identical.
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
        {
            "function": entry.get("function"),
            "file": entry.get("file"),
            "line": entry.get("line"),
        }
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
