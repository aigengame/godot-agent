"""The ``diag`` command group: the RUNNING game's runtime diagnostics (#224).

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderer, its ``HeadlessCommand`` descriptor
(ADR-0023) and its Typer command body, and mounts them on the root app through
:func:`register`. It imports the shared machinery downward — the dispatch tail
(``gda.dispatch``), the descriptor machinery (``gda.headless``, which defaults a
LIVE descriptor's classifier to the shared ``classify_live``) and the
cross-command contract core (``gda.models``) — and is imported by the composition
root (``gda.cli``) plus ``gda.commands.logger``, which reuses the two shapes the
two log-reading groups genuinely share (``SourceFrame`` and the ``--limit``
description) one-way, ADR-0040 §5.

NOT to be confused with ``gda.daemon.diag`` — the daemon-side LOG PARSER that
turns a `Session log` into error/record dicts. That module stays in the
``gda.daemon`` package; this one is the CLI-side command group. Both are reached
by their absolute import paths, never a relative one, so the two stay distinct.

``diag`` is LIVE (``kind = LIVE``) but daemon-served: the daemon reads the
`Session log` it launched the engine with (``--log-file``) rather than relaying
to the harness, and serves it even after the session process has died, so a
crash stays diagnosable (ADR-0022). The introspection-only counterpart to
``perf``.
"""

from typing import Optional

import typer
from pydantic import BaseModel, Field

from gda.dispatch import _dispatch
from gda.execution import ExecutionKind
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)

# Shared by the two log-reading live commands — ``gda diag errors`` and ``gda
# logger tail`` (which imports it from here, the one-way sibling edge of
# ADR-0040 §5, following the ADR-0022/0026 lineage that made `logger` the
# structured successor of this group's raw view).
_DIAG_LIMIT_DESC = (
    "If set, tail only the most recent N entries (newest last); must be >= 1. "
    "Omit for all entries."
)


class SourceFrame(BaseModel):
    """A source location ``{function, file, line}`` (ADR-0026, #283).

    A small, generic frame model: a function name, the source path it lives in,
    and the line, each ``null`` when the source did not carry it. Shared by a
    :class:`LogRecord`'s ``source`` (the engine's ``at:`` follow-on) and the
    ordered ``callstack`` frames of a :class:`DiagError` (best-effort, never a
    parse failure).
    """

    function: str | None = Field(
        default=None, description="The frame's function name, if known."
    )
    file: str | None = Field(
        default=None,
        description="The frame's source path (e.g. res://main.gd), if known.",
    )
    line: int | None = Field(
        default=None, description="The frame's source line, if known."
    )


class DiagError(BaseModel):
    """One structured runtime error/warning of the running game (#224).

    Parsed from Godot's two-line log format. ``level`` normalizes the engine's
    ``<TYPE>`` (``error`` / ``warning`` / ``script_error`` / ``shader_error``) so
    an agent branches on the severity without parsing prose — warnings are
    included, told apart by ``level``. The location (``function``/``file``/
    ``line``) is filled from the ``   at:`` follow-on when present; a bare error
    leaves them ``null`` (best-effort, never a parse failure). A runtime GDScript
    error additionally carries its ordered ``callstack`` of frames (#283); a bare
    push_error / warning has no backtrace, so ``callstack`` is empty.
    """

    level: str = Field(
        description="Normalized severity: error / warning / script_error / shader_error."
    )
    message: str = Field(description="The error/warning message the engine logged.")
    function: str | None = Field(
        default=None,
        description="The reporting function, if the log had an `at:` line.",
    )
    file: str | None = Field(
        default=None, description="The source path (e.g. res://main.gd), if known."
    )
    line: int | None = Field(default=None, description="The source line, if known.")
    callstack: list[SourceFrame] = Field(
        default_factory=list,
        description=(
            "The ordered call stack (most-recent-first) when the engine emitted a "
            "GDScript backtrace; frame [0] equals the top {function,file,line}. "
            "Empty for a bare push_error / warning."
        ),
    )


class DiagErrorsParams(BaseModel):
    """The params of ``gda diag errors``: read the running game's runtime errors (#224).

    Reads the current Engine session's captured errors. ``limit`` tails the most
    recent N (constrained ``>= 1``); v1 returns the current session's log with no
    incremental offset. Omitting ``limit`` returns all entries.
    """

    limit: int | None = Field(default=None, ge=1, description=_DIAG_LIMIT_DESC)


class DiagErrorsResult(BaseModel):
    """The result of ``gda diag errors``: the running game's structured errors (#224).

    An empty ``errors`` list is a successful empty read (the game logged nothing),
    not an error.
    """

    errors: list[DiagError]


def render_diag_errors(diag: "DiagErrorsResult") -> str:
    """Render the running game's runtime errors as `LEVEL: message (at: loc)` lines (#224).

    One line per error/warning; the location is appended when known (a bare error
    omits it). A runtime GDScript error's ordered ``callstack`` (#283) renders as
    indented ``function (file:line)`` frame lines below the headline (most-recent-
    first); a bare error with no backtrace shows just its one line. An empty read
    renders a short `no runtime errors` note rather than a blank string, so the
    human output is never ambiguous.
    """
    if not diag.errors:
        return "no runtime errors"
    lines = []
    for err in diag.errors:
        line = f"{err.level.upper()}: {err.message}"
        if err.file is not None:
            loc = f"{err.file}:{err.line}" if err.line is not None else err.file
            at = f" (at: {err.function} {loc})" if err.function else f" (at: {loc})"
            line += at
        lines.append(line)
        for frame in err.callstack:
            loc = f"{frame.file}:{frame.line}" if frame.line is not None else frame.file
            where = f"({loc})" if loc is not None else ""
            lines.append(f"  {frame.function or '<unknown>'} {where}".rstrip())
    return "\n".join(lines)


def _diag_limit_option() -> Optional[int]:
    """The shared `--limit N` option for the log-reading live commands: tail N.

    Used by both ``gda diag errors`` and ``gda logger tail``. Bound to ``>= 1``
    (Click ``min``) so a zero/negative limit is a usage error on the argv path,
    mirroring the ``ge=1`` constraint on ``DiagErrorsParams`` /
    ``LoggerTailParams`` that the ``--params-json`` / ``--schema`` path enforces.
    """
    return typer.Option(
        None,
        "--limit",
        min=1,
        help="If set, tail only the most recent N entries (newest last); must be >= 1.",
    )


DIAG_ERRORS_COMMAND: HeadlessCommand[DiagErrorsResult] = HeadlessCommand(
    operation="diag-errors",
    input_model=DiagErrorsParams,
    output_model=DiagErrorsResult,
    render=render_diag_errors,
    kind=ExecutionKind.LIVE,
)


# The diag command group (Phase 2, ADR-0019, #224): the RUNNING game's runtime
# diagnostics — its errors and its output log — served LIVE (`kind = LIVE`).
# Unlike `game`, diag is daemon-served: the daemon reads the Session log it
# launched the engine with (`--log-file`) rather than relaying to the harness,
# and serves it even after the session process has died, so a crash stays
# diagnosable. From the CLI's side it routes like any live command (kind = LIVE
# -> the daemon socket); the daemon recognizes the diag op names.
_app = typer.Typer(
    help="Read the running game's runtime diagnostics (live; needs `gda daemon start`).",
    no_args_is_help=True,
)


@_app.command(name="errors", cls=DIAG_ERRORS_COMMAND.command_class())
def diag_errors(
    limit: Optional[int] = _diag_limit_option(),
    json_output: bool = json_option(),
    schema: bool = DIAG_ERRORS_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read the running game's runtime errors as structured output (live).

    Routes through gda-daemon (kind = LIVE, ADR-0017), but is daemon-served: the
    daemon reads the Session log it launched the engine with (`--log-file`) — NOT
    the harness — so it works even after the game has crashed, keeping the crash
    diagnosable (#224). Each entry carries a normalized `level` (error / warning /
    script_error / shader_error) and, when the log recorded it, the source
    function/file/line. `--limit N` tails the most recent N. With no daemon it
    reports `daemon_not_running`; with a daemon but no session ever launched,
    `engine_session_not_running`; with a session whose log file is gone,
    `live_log_unavailable`. An empty log is an empty result, not an error.
    """
    _dispatch(
        DIAG_ERRORS_COMMAND,
        DiagErrorsParams(limit=limit),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``diag`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="diag")
