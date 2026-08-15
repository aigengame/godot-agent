"""Classify Godot's script-error stderr lines into structured diagnostics (#651).

The single home of *what Godot's error stream says about a script*. It is the
read-side companion to :func:`gda.daemon.diag.parse_errors`, which is the single
home of *how the engine formats an error line* (the two-line ``<TYPE>: <message>``
/ ``   at: <function> (<file>:<line>)`` shape of ``core/io/logger.cpp``). This
module reuses that parser verbatim and adds the one thing it does not do: decide
which of the engine's known script-failure sentences a record is, and which
``res://`` script the sentence is about.

The split matters because the engine reports a failed script run **only** on
stderr — the process still exits ``0``. A missing entry script, a parse error in
the entry script, and a parse error in one of its dependencies all leave a clean
exit status behind (verified against Godot 4.6.3), so a channel that reads only
the exit code reports a phantom success (#651, dogfooding GDA-DF-007/GDA-DF-032).
:func:`entry_load_failure` turns the stderr evidence into that missing verdict.

Consumers (the reason this is a module and not a helper inside one command):

- ``gda script run`` (:mod:`gda.commands.script`) — the verdict plus the
  ``diagnostics`` it carries on its result;
- the ``script run`` timeout path (#655) — the same diagnostics from the partial
  stderr captured before the timeout;
- the scene-startup preflight (#664) — the same script errors from a scene launch.

Everything here is a **pure function of the stderr text**: no engine, no I/O.
Recognition is deliberately closed — only the sentences below are classified, so
``diagnostics`` stays a curated high-signal list rather than a re-encoding of the
whole error stream (the verbatim stream is preserved separately by each caller).
An unrecognized error or warning is skipped and never raises.

The recognized sentences, verbatim from Godot 4.6.3::

    SCRIPT ERROR: Parse Error: <message>
              at: GDScript::reload (res://entry.gd:4)
    ERROR: Failed to load script "res://entry.gd" with error "Parse error".
    ERROR: Attempt to open script 'res://gone.gd' resulted in error 'File not found'.
    ERROR: Can't load script: res://gone.gd
    ERROR: Can't load the script "res://plain.gd" as it doesn't inherit from SceneTree or MainLoop.
"""

import re
from collections.abc import Sequence
from enum import Enum

from pydantic import BaseModel, Field

from gda.daemon.diag import parse_errors

# The res:// scheme prefix. A diagnostic's ``path`` is only ever a res:// script:
# the engine's own ``at:`` frame for an engine-side error names a C++ source file
# (``modules/gdscript/gdscript.cpp``), which is gda-irrelevant noise.
_RES_PREFIX = "res://"

# The engine's ``SCRIPT ERROR:`` records carry the compile failure as a message
# prefixed ``Parse Error:``; every other SCRIPT ERROR is a runtime failure raised
# while the script was already executing.
_PARSE_ERROR_PREFIX = "Parse Error:"

# `ERROR: Attempt to open script '<path>' resulted in error '<reason>'.` — the
# engine could not even read the file. The reason distinguishes a missing script
# (the #651 defect) from any other open failure.
_OPEN_FAILED = re.compile(
    r"^Attempt to open script '(?P<path>[^']*)' resulted in error '(?P<reason>[^']*)'"
)
_FILE_NOT_FOUND = "File not found"

# `ERROR: Failed to load script "<path>" with error "<reason>".` — the file was
# read but the script did not compile (its own parse error, or an unresolvable
# dependency: the entry script is what the engine names either way).
_LOAD_FAILED = re.compile(
    r'^Failed to load script "(?P<path>[^"]*)" with error "(?P<reason>[^"]*)"'
)

# `ERROR: Can't load script: <path>` — main.cpp's `start()` giving up on the
# `--script` entry point. Emitted alongside the more specific sentences above;
# on its own it is the generic "the entry never became the main loop".
_CANT_LOAD = re.compile(r"^Can't load script: (?P<path>\S+?)\.?$")

# `ERROR: Can't load the script "<path>" as it doesn't inherit from SceneTree or
# MainLoop.` — the script compiled fine but cannot BE the one-shot entry point.
_NOT_A_MAIN_LOOP = re.compile(
    r'^Can\'t load the script "(?P<path>[^"]*)" as it doesn\'t inherit from '
    r"SceneTree or MainLoop"
)


class ScriptErrorKind(str, Enum):
    """What a recognized engine error line says about a script (#651).

    A closed, public enum: it is projected into ``--schema`` through the results
    that carry :class:`ScriptError`. **Five** of the six kinds mean the named
    script **never ran** — it was missing, unreadable, non-compiling, or unusable
    as an entry point. Only ``RUNTIME_ERROR`` means the script was loaded and
    running when the error was raised.
    """

    #: A compile failure in the named script (its own syntax error, or a
    #: dependency it preloads that does not resolve). The script never ran.
    PARSE_ERROR = "parse_error"
    #: A GDScript error raised while the script was already executing. The ONLY
    #: kind that says the script ran.
    RUNTIME_ERROR = "runtime_error"
    #: The named script does not exist. It never ran.
    SCRIPT_MISSING = "script_missing"
    #: The named script exists but could not be loaded (an open failure other
    #: than a missing file, or the engine giving up on the entry point). It
    #: never ran.
    LOAD_FAILED = "load_failed"
    #: The named script was read but did not compile. It never ran.
    COMPILE_FAILED = "compile_failed"
    #: The named script compiles but does not extend ``SceneTree``/``MainLoop``,
    #: so it cannot be a one-shot ``--script`` entry point. It never ran.
    NOT_A_MAIN_LOOP = "not_a_main_loop"


#: The kinds that prove a script never ran, in verdict precedence — the order
#: :func:`entry_load_failure` returns them in when a run emits several. It runs
#: EARLIEST-STAGE, MOST SPECIFIC first, because the engine reports the whole
#: cascade and only the first cause explains the rest:
#:
#: 1. ``SCRIPT_MISSING`` — a file that does not exist cannot compile, so it
#:    outranks the generic "can't load" the engine emits beside it;
#: 2. ``COMPILE_FAILED`` — the engine's explicit "Failed to load script … with
#:    error …" verdict sentence;
#: 3. ``PARSE_ERROR`` — the individual diagnostic that CAUSED (2). Ranked below it
#:    because (2) is the engine's own conclusion, but kept in the list so a
#:    non-compiling entry is still caught if a build ever emits the diagnostic
#:    without the conclusion;
#: 4. ``LOAD_FAILED`` — "can't load", the least specific reason;
#: 5. ``NOT_A_MAIN_LOOP`` — last because it is only reachable by a script that
#:    already existed AND compiled; it is a refusal, not a load failure.
#:
#: ``RUNTIME_ERROR`` is absent by construction: it is the one kind that proves the
#: script DID run.
_ENTRY_FAILURE_PRECEDENCE = (
    ScriptErrorKind.SCRIPT_MISSING,
    ScriptErrorKind.COMPILE_FAILED,
    ScriptErrorKind.PARSE_ERROR,
    ScriptErrorKind.LOAD_FAILED,
    ScriptErrorKind.NOT_A_MAIN_LOOP,
)


class ScriptError(BaseModel):
    """One recognized script error read out of the engine's stderr (#651).

    Best-effort and advisory in the ADR-0002 sense — parsed from stderr, not from
    a bound API — but unlike free-form diagnostics it is *classified*, so an agent
    can branch on ``kind`` instead of matching engine prose.
    """

    kind: ScriptErrorKind = Field(
        description=(
            "Which known engine script failure this line reports. Five of the six "
            "mean the named script never ran: 'script_missing', 'compile_failed', "
            "'parse_error', 'load_failed' and 'not_a_main_loop'. Only "
            "'runtime_error' means the script was loaded and running when it raised."
        )
    )
    message: str = Field(
        description=(
            "The engine's error text verbatim, with its 'ERROR:'/'SCRIPT ERROR:' "
            "prefix stripped."
        )
    )
    path: str | None = Field(
        default=None,
        description=(
            "The res:// script this error is about, or null when the engine named none."
        ),
    )
    line: int | None = Field(
        default=None,
        description=(
            "The 1-based line in 'path' the engine reported, or null when it "
            "reported none (engine-side load errors carry no script line)."
        ),
    )


def parse_script_errors(stderr: str) -> list[ScriptError]:
    """Recognized script errors from an engine stderr capture, in emission order.

    Pure and best-effort: an error the engine formats in a way this module does
    not recognize — and every warning — is skipped rather than guessed at, and
    malformed input yields ``[]`` instead of raising. Callers keep the verbatim
    stderr, so nothing is lost by the narrow recognition.
    """
    errors: list[ScriptError] = []
    for record in parse_errors(stderr):
        recognized = _classify(record)
        if recognized is not None:
            errors.append(recognized)
    return errors


def entry_load_failure(
    errors: Sequence[ScriptError], script: str
) -> ScriptError | None:
    """The error proving ``script`` never ran as the entry point, or ``None``.

    ``script`` is the ``res://`` path the caller asked the engine to run. Matching
    on that exact path is what keeps the verdict honest: a running script that
    *itself* loads a missing or broken resource produces the very same engine
    sentences for a DIFFERENT path, and must not be reported as a failed run.

    A dependency's compile failure still fails the entry: the engine reports the
    unresolvable preload as "Failed to load script" naming the **entry** script
    (verified against Godot 4.6.3), so no dependency walk is needed here.

    Returns the most specific matching error (see ``_ENTRY_FAILURE_PRECEDENCE``);
    ``None`` when the entry point loaded, whatever else went wrong afterwards.
    """
    for kind in _ENTRY_FAILURE_PRECEDENCE:
        for error in errors:
            if error.kind is kind and error.path == script:
                return error
    return None


def _classify(record: dict) -> ScriptError | None:
    """One ``parse_errors`` record as a :class:`ScriptError`, or ``None`` if unknown."""
    level = record.get("level")
    message = record.get("message") or ""
    if level == "script_error":
        return _script_error(record, message)
    if level != "error":
        # Warnings and the other engine levels say nothing about a script's fate.
        return None
    return _engine_error(message)


def _script_error(record: dict, message: str) -> ScriptError:
    """A ``SCRIPT ERROR:`` record: a compile failure or a runtime failure.

    The location comes from the engine's ``at:`` frame, which for a script error
    names the script itself (``GDScript::reload (res://entry.gd:4)`` for a parse
    error, the raising function for a runtime one), so both a ``path`` and a
    ``line`` are available here — unlike the engine-side load errors below.
    """
    kind = (
        ScriptErrorKind.PARSE_ERROR
        if message.startswith(_PARSE_ERROR_PREFIX)
        else ScriptErrorKind.RUNTIME_ERROR
    )
    file = record.get("file")
    path = file if isinstance(file, str) and file.startswith(_RES_PREFIX) else None
    return ScriptError(
        kind=kind,
        message=message,
        path=path,
        # A line without a res:// path would be a line number in the engine's own
        # C++ source, which is meaningless to an agent — so both travel together.
        line=record.get("line") if path is not None else None,
    )


def _engine_error(message: str) -> ScriptError | None:
    """A plain ``ERROR:`` record, if it is one of the known script-load sentences.

    The path is read out of the MESSAGE, not the record's ``at:`` frame: these are
    raised by the engine's own C++ (``main.cpp``, ``gdscript.cpp``), so the frame
    names an engine source file. No script line is available for any of them.
    """
    open_failed = _OPEN_FAILED.match(message)
    if open_failed is not None:
        kind = (
            ScriptErrorKind.SCRIPT_MISSING
            if open_failed.group("reason") == _FILE_NOT_FOUND
            else ScriptErrorKind.LOAD_FAILED
        )
        return ScriptError(kind=kind, message=message, path=open_failed.group("path"))
    load_failed = _LOAD_FAILED.match(message)
    if load_failed is not None:
        return ScriptError(
            kind=ScriptErrorKind.COMPILE_FAILED,
            message=message,
            path=load_failed.group("path"),
        )
    # Checked before the bare `Can't load script:` form — the two sentences share a
    # prefix word, and only the anchored patterns tell them apart.
    not_a_main_loop = _NOT_A_MAIN_LOOP.match(message)
    if not_a_main_loop is not None:
        return ScriptError(
            kind=ScriptErrorKind.NOT_A_MAIN_LOOP,
            message=message,
            path=not_a_main_loop.group("path"),
        )
    cant_load = _CANT_LOAD.match(message)
    if cant_load is not None:
        return ScriptError(
            kind=ScriptErrorKind.LOAD_FAILED,
            message=message,
            path=cant_load.group("path"),
        )
    return None
