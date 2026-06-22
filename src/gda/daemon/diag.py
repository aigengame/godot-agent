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
