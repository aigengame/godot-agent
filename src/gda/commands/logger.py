"""The ``logger`` command group: the running game's structured runtime log (#281).

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderer, its ``HeadlessCommand`` descriptor
(ADR-0023) and its Typer command body, and mounts them on the root app through
:func:`register`. It imports the shared machinery downward — the dispatch tail
(``gda.dispatch``), the descriptor machinery (``gda.headless``, which defaults a
LIVE descriptor's classifier to the shared ``classify_live``) and the
cross-command contract core (``gda.models``) — plus, one-way, the two shapes it
genuinely shares with its sibling ``gda.commands.diag`` (``SourceFrame`` and the
``--limit`` description / option, ADR-0040 §5). It is imported by nothing but the
composition root (``gda.cli``).

The group is LIVE (``kind = LIVE``) and, like ``diag``, daemon-served: the daemon
parses the `Session log` it owns (``--log-file``, ADR-0022) into typed
``LogRecord``s rather than relaying to the harness, so a crash stays diagnosable.
``logger tail`` is the passive, non-invasive floor of the structured-log protocol
(ADR-0026); the raw ``diag log`` view is superseded by ``logger tail --raw``.
"""

from enum import Enum
from typing import Any, Optional

import typer
from pydantic import BaseModel, Field

from gda.commands.diag import SourceFrame, _diag_limit_option, _DIAG_LIMIT_DESC
from gda.dispatch import _dispatch
from gda.execution import ExecutionKind
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)


class LogLevel(str, Enum):
    """The closed, ordered severity of a :class:`LogRecord` (ADR-0026).

    ``debug < info < warning < error`` — a TOTAL order, so ``--level <min>``
    filtering is a well-defined ``>=`` contract (ADR-0004). The engine's finer
    kinds collapse onto it (``WARNING`` -> ``warning``; ``ERROR`` / ``SCRIPT
    ERROR`` / ``SHADER ERROR`` -> ``error``), with the sub-kind kept in
    :class:`LogRecord.origin`.
    """

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class LogOrigin(str, Enum):
    """Where a typed :class:`LogRecord` came from — the sub-kind (ADR-0026).

    Preserves the distinction the closed :class:`LogLevel` collapses: an engine
    error vs a script error vs a shader error (all ``error`` level) vs an opt-in
    ``gda_log()`` record (#282). ``null`` on a plain ``info`` line that carries no
    engine/app origin.
    """

    ENGINE = "engine"
    SCRIPT = "script"
    SHADER = "shader"
    GDA_LOG = "gda_log"


class LogRecord(BaseModel):
    """One structured record of the running game's runtime log (ADR-0026, #281).

    The typed unit of the structured runtime-log channel, parsed from the
    daemon-owned Session log. ``seq`` is a monotonic ordinal in capture order.
    ``level`` is the closed, ordered :class:`LogLevel`. ``message`` is the logged
    text. ``source`` is the ``{function, file, line}`` frame when the engine
    recorded an ``at:`` location (engine errors/warnings), else ``null``.
    ``origin`` names the sub-kind the closed level collapses (``engine`` /
    ``script`` / ``shader`` / ``gda_log``), else ``null`` for a plain ``info``
    line. ``fields`` is an app-supplied structured object — empty here (the passive
    floor); populated only by the opt-in ``gda_log()`` protocol (#282).
    """

    seq: int = Field(description="Monotonic ordinal in capture order (0-based).")
    level: LogLevel = Field(
        description="Closed, ordered severity: debug < info < warning < error."
    )
    message: str = Field(description="The logged message text.")
    source: SourceFrame | None = Field(
        default=None,
        description="The {function, file, line} location when known (engine errors), else null.",
    )
    origin: LogOrigin | None = Field(
        default=None,
        description=(
            "The sub-kind the closed level collapses (engine / script / shader / "
            "gda_log), or null for a plain info line."
        ),
    )
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "App-supplied structured fields; empty for a passively-parsed record, "
            "populated only by the opt-in gda_log() protocol (#282)."
        ),
    )


class LoggerTailParams(BaseModel):
    """The params of ``gda logger tail``: read the running game's structured log (#281).

    Reads the current Engine session's captured log as structured records.
    ``level`` filters by minimum severity over the closed ordering
    ``debug < info < warning < error`` (e.g. ``warning`` excludes ``info`` /
    ``debug``); omit for all severities. ``limit`` tails the most recent N records
    (constrained ``>= 1``) AFTER the level filter; omit for all. ``raw`` skips
    classification, returning every captured line as a verbatim ``info`` record
    (the view the superseded ``diag log`` returned), still as ``LogRecord[]``.
    """

    level: LogLevel | None = Field(
        default=None,
        description=(
            "If set, return only records at or above this minimum severity over the "
            "closed ordering debug < info < warning < error. Omit for all."
        ),
    )
    limit: int | None = Field(default=None, ge=1, description=_DIAG_LIMIT_DESC)
    raw: bool = Field(
        default=False,
        description=(
            "If set, skip classification: return every captured line as a verbatim "
            "`info` record (the superseded `diag log` view), still as LogRecord[]. "
            "Otherwise lines are classified into typed records."
        ),
    )


class LoggerTailResult(BaseModel):
    """The result of ``gda logger tail``: the running game's structured log (#281).

    ``records`` is the whole captured Session log as ``LogRecord[]`` — one record
    per line: engine errors/warnings typed (their ``at:`` folded into ``source``),
    every other line a plain ``info`` record (ADR-0026 decision 2, amended #281).
    With ``--raw`` the same shape carries every line as an unclassified ``info``
    record holding its verbatim text (the view the superseded ``diag log``
    returned). It mirrors how ``diag errors`` delivers ``DiagError[]`` as
    ``DiagErrorsResult.errors``. An empty read is a successful empty result, not an
    error.
    """

    records: list[LogRecord] = Field(
        default_factory=list,
        description="The whole Session log as structured records (LogRecord[]).",
    )


def render_logger_tail(tail: "LoggerTailResult") -> str:
    """Render the running game's structured runtime log (#281, ADR-0026).

    One ``LEVEL: message (at: loc)`` line per record, the location appended when
    known (a plain info line omits it). Under ``--raw`` records are unclassified
    ``info`` lines carrying verbatim text, so they render as the message alone (the
    superseded ``diag log`` view). An empty read renders a short note rather than a
    blank string, so the human output is never ambiguous.
    """
    if not tail.records:
        return "no log records"
    lines = []
    for rec in tail.records:
        line = f"{rec.level.value.upper()}: {rec.message}"
        if rec.source is not None and rec.source.file is not None:
            loc = (
                f"{rec.source.file}:{rec.source.line}"
                if rec.source.line is not None
                else rec.source.file
            )
            at = (
                f" (at: {rec.source.function} {loc})"
                if rec.source.function
                else f" (at: {loc})"
            )
            line += at
        lines.append(line)
    return "\n".join(lines)


def _logger_level_option() -> Optional[LogLevel]:
    """The `--level <min>` option for `gda logger tail`: a minimum-severity filter.

    Bound to the closed :class:`LogLevel` enum (Click choices), so an out-of-set
    value is a usage error on the argv path, mirroring the enum-typed field on
    ``LoggerTailParams`` that the ``--params-json`` / ``--schema`` path enforces.
    Omitting it returns all severities.
    """
    return typer.Option(
        None,
        "--level",
        help=(
            "If set, return only records at or above this minimum severity over the "
            "closed ordering debug < info < warning < error. Omit for all."
        ),
    )


def _logger_raw_option() -> bool:
    """The `--raw` flag for `gda logger tail`: verbatim lines instead of records.

    The superseded `diag log` view: with it, the result carries the verbatim
    captured lines (`lines`) and no structured records.
    """
    return typer.Option(
        False,
        "--raw",
        help="Return the verbatim captured log lines instead of structured records.",
    )


LOGGER_TAIL_COMMAND: HeadlessCommand[LoggerTailResult] = HeadlessCommand(
    operation="logger-tail",
    input_model=LoggerTailParams,
    output_model=LoggerTailResult,
    render=render_logger_tail,
    kind=ExecutionKind.LIVE,
)


# The logger command group (Phase 2, ADR-0019, ADR-0026, #281): the running game's
# STRUCTURED runtime-log stream as a domain object, marked LIVE by `kind`. Like
# `diag`, it is daemon-served — the daemon parses the Session log it owns
# (`--log-file`) into typed `LogRecord`s rather than relaying to the harness, so a
# crash stays diagnosable. `logger tail` is the passive, non-invasive floor of the
# structured-log protocol; the raw `diag log` is superseded by `logger tail --raw`.
_app = typer.Typer(
    help="Read the running game's structured runtime log (live; needs `gda daemon start`).",
    no_args_is_help=True,
)


@_app.command(name="tail", cls=LOGGER_TAIL_COMMAND.command_class())
def logger_tail(
    level: Optional[LogLevel] = _logger_level_option(),
    limit: Optional[int] = _diag_limit_option(),
    raw: bool = _logger_raw_option(),
    json_output: bool = json_option(),
    schema: bool = LOGGER_TAIL_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read the running game's structured runtime log (live).

    The passive, non-invasive structured runtime-log channel (#281, ADR-0026): the
    daemon parses the whole daemon-owned Session log into typed `LogRecord`s —
    engine errors/warnings via the diag parser (carrying `source` + an `origin`
    sub-kind), every other line a plain `info` record. So an un-instrumented
    project gets structured logs for free. `--level <min>` filters by minimum
    severity over the closed ordering debug < info < warning < error; `--limit N`
    tails the most recent N (after the filter); `--raw` returns the verbatim lines
    instead (the superseded `diag log` view). Daemon-served like `diag`: read from
    the `--log-file` the daemon owns, so it works even after the game has crashed.
    With no daemon it reports `daemon_not_running`; with a daemon but no session
    ever launched, `engine_session_not_running`; with a session whose log file is
    gone, `live_log_unavailable`. An empty log is an empty result, not an error.
    """
    _dispatch(
        LOGGER_TAIL_COMMAND,
        LoggerTailParams(level=level, limit=limit, raw=raw),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``logger`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="logger")
