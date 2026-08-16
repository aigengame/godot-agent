"""Parse Godot's error-line format out of any engine output capture (#651).

The single home of **how the engine formats an error**, extracted from
``gda.daemon.diag`` so both of its consumers can import it downward (ADR-0000's
component order, ADR-0040's module direction): the Phase-2 daemon reads a
`Session log` file, and the Phase-1 ``script run`` channel reads a one-shot
process's stderr. Same engine, same format, one parser — and this module sits
below both, importing nothing from ``daemon`` or ``commands``.

Godot writes an error as a two-line pair (verified against the engine's
``core/io/logger.cpp`` ``Logger::log_error``)::

    <TYPE>: <message>
       at: <function> (<file>:<line>)

where ``<TYPE>`` is one of ``ERROR`` / ``WARNING`` / ``SCRIPT ERROR`` /
``SHADER ERROR``. Print output is plain lines. A runtime GDScript error carries
a multi-line call stack after the ``at:`` line — a ``GDScript backtrace (most
recent call first):`` marker then one ``[N] <function> (<file>:<line>)`` frame
line per stack frame (#283); :func:`parse_errors` folds those frames into the
error's ordered ``callstack`` (frame ``[0]`` equals the ``at:`` location).

The parsing is **best-effort**: a line that is neither a recognized ``<TYPE>:``
header nor the ``   at:`` follow-on (a backtrace, an interleaved print line) is
skipped for ``errors`` and never raises.
"""

import re

# A ``<TYPE>: <message>`` header. The TYPE strings come straight from the engine's
# ``Logger::error_type_string`` — kept anchored to line start so a print line that
# merely contains the word "ERROR" is not mistaken for an error header.
ERROR_HEADER = re.compile(r"^(ERROR|WARNING|SCRIPT ERROR|SHADER ERROR): (.*)$")

# The engine's follow-on location line: ``   at: <function> (<file>:<line>)``.
# Leading whitespace varies by ErrorType indent, so it is matched loosely.
AT_LINE = re.compile(
    r"^\s*at:\s*(?P<function>.*?)\s*\((?P<file>.*):(?P<line>\d+)\)\s*$"
)

# After the ``at:`` line, a runtime GDScript error MAY carry a full call stack:
# a marker line ``GDScript backtrace (most recent call first):`` then one frame
# line per stack frame, ``       [N] <function> (<file>:<line>)`` (verified
# against Godot 4.6.3). Frames are ordered most-recent-first; frame ``[0]``
# equals the ``at:`` location. push_error / warnings carry no backtrace.
BACKTRACE_MARKER = re.compile(r"^\s*GDScript backtrace\b.*:\s*$")
FRAME_LINE = re.compile(
    r"^\s*\[\d+\]\s*(?P<function>.*?)\s*\((?P<file>.*):(?P<line>\d+)\)\s*$"
)

# The engine ``<TYPE>`` string -> the normalized, machine-stable ``level``.
LEVEL_BY_TYPE = {
    "ERROR": "error",
    "WARNING": "warning",
    "SCRIPT ERROR": "script_error",
    "SHADER ERROR": "shader_error",
}


def as_text(data: str | bytes) -> str:
    """Decode bytes best-effort; pass text through (never raises on bad UTF-8)."""
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data


def lines(data: str | bytes) -> list[str]:
    """Split an output capture into lines, tolerating bytes and empty input."""
    text = as_text(data)
    if not text:
        return []
    return text.splitlines()


def parse_errors(data: str | bytes, limit: int | None = None) -> list[dict]:
    """Structured errors from an engine output capture — best-effort (#224).

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
    captured = lines(data)
    errors: list[dict] = []
    i = 0
    while i < len(captured):
        header = ERROR_HEADER.match(captured[i])
        if header is None:
            i += 1
            continue
        type_str, message = header.group(1), header.group(2)
        entry: dict = {
            "level": LEVEL_BY_TYPE[type_str],
            "message": message,
            "function": None,
            "file": None,
            "line": None,
            "callstack": [],
        }
        # The next line MAY be the engine's ``at:`` location follow-on; if so,
        # consume it. Anything else (the next header, an output line) is left for
        # the next iteration.
        if i + 1 < len(captured):
            at = AT_LINE.match(captured[i + 1])
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
        if i + 1 < len(captured) and BACKTRACE_MARKER.match(captured[i + 1]):
            i += 1
            while i + 1 < len(captured):
                frame = FRAME_LINE.match(captured[i + 1])
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
