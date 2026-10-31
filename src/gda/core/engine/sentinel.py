"""The ADR-0002 sentinel wire in one file: argv half, result half, default runner.

The argv half (:func:`sentinel_args`) spells how a sentinel op is dispatched; the
result half (:func:`parse_result` and its inverse) reads and writes the wire; and
:class:`SubprocessGodotRunner`, the default sentinel runner, goes with the argv it
spells so that the launch primitive names no payload (ADR-0045 §2).

A headless Godot process interleaves its banner, warnings and stray ``print()``
output into stdout. The GDScript operation emits exactly one result payload
wrapped in unique sentinels::

    <<<GDA:RESULT>>>{...json...}<<<GDA:END>>>

``parse_result`` finds the one complete result record: the begin sentinel, one
complete JSON value, then the end sentinel. Everything else on stdout is ignored,
and that includes sentinel text that project code prints before or after the
record. The payload echoes user-controlled content (a path, node names, script
source), so it can itself contain sentinel text; the JSON decoder reads such text
as part of a string value (ADR-0002, Outcome note of 2026-10-31).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gda.core.engine.launch import DEFAULT_TIMEOUT_SECONDS, RunResult, launch

# The bundled GDScript operations payload, dispatched by operation name. Resolved
# package-relative, two levels up out of ``gda/core/engine/`` (ADR-0045 §4).
OPERATIONS_GD = Path(__file__).parent.parent.parent / "ops" / "operations.gd"


def sentinel_args(
    operation: str,
    params: dict,
    *,
    project: Path | None,
    script: Path = OPERATIONS_GD,
) -> list[str]:
    """The argv tail that dispatches one sentinel operation (ADR-0001, ADR-0002).

    How a sentinel op is SPELLED on the command line, owned once: the payload
    script, the ``--`` separator, the operation name and its JSON params — plus
    ``--path`` when the op runs against a project, so ``res://`` resolves there
    (issue #32). Everything after ``--`` reaches the payload verbatim through
    ``OS.get_cmdline_user_args()``, which decouples it from however Godot orders
    its own engine arguments.

    Two channels build this tail (#664): :class:`SubprocessGodotRunner`, the default
    sentinel runner, and ``scene preflight``, which dispatches the same kind of op but
    calls :func:`gda.core.engine.launch.launch` itself — it bifurcates on the launch's
    own outcome (a timeout is its VERDICT, not an error) rather than handing the result
    to a classifier through the runner seam. Extracting the spelling keeps that second
    channel from re-deriving it, and keeps a change to it (a new separator, another
    engine flag) landing in one place.
    """
    args: list[str] = []
    if project is not None:
        args += ["--path", str(project)]
    return [*args, "--script", str(script), "--", operation, json.dumps(params)]


RESULT_BEGIN = "<<<GDA:RESULT>>>"
RESULT_END = "<<<GDA:END>>>"


def result_sentinel_start(stdout: str) -> int:
    """Where the first begin sentinel is in ``stdout``, or ``-1`` (#664).

    The first question :func:`parse_result` asks, exposed so a channel that needs
    only that answer does not restate the test. ``gda scene preflight`` is the
    caller: a clean engine exit with no result at all means the project ended the
    run before the op could report, while an exit that started a result and did not
    finish one is a broken payload — two different failures, and telling them apart
    needs exactly this boundary.

    Deliberately answers "did it start", NOT "is there a valid result": a BEGIN
    without its END is *started* here and REJECTED by :func:`parse_result`, so such
    output stays a parse failure rather than being mistaken for a project quit. A
    begin sentinel that project code prints counts too, so that run also goes to the
    parse. One rule, one home — both readings come from this function.
    """
    return stdout.find(RESULT_BEGIN)


# JSON's whitespace, which may surround the value inside a record.
_JSON_WHITESPACE = " \t\r\n"
_DECODER = json.JSONDecoder()


def _skip_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index] in _JSON_WHITESPACE:
        index += 1
    return index


def parse_result(stdout: str) -> Any:
    """The JSON value of the one complete result record in ``stdout``.

    A record is the begin sentinel, one complete JSON value, then the end
    sentinel: what :func:`build_result` writes. The scan starts at each begin
    sentinel in turn and continues after a record it found, so sentinel text
    inside the record's own string values is never read as a second record. No
    record, or more than one, is a contract violation (ADR-0002, Outcome note of
    2026-10-31).
    """
    start = result_sentinel_start(stdout)
    if start == -1:
        raise ValueError("no GDA result sentinel found in stdout")
    values: list[Any] = []
    while start != -1:
        value_start = _skip_whitespace(stdout, start + len(RESULT_BEGIN))
        try:
            value, value_end = _DECODER.raw_decode(stdout, value_start)
        except ValueError:
            start = stdout.find(RESULT_BEGIN, start + 1)
            continue
        end = _skip_whitespace(stdout, value_end)
        if stdout.startswith(RESULT_END, end):
            values.append(value)
            start = stdout.find(RESULT_BEGIN, end + len(RESULT_END))
        else:
            start = stdout.find(RESULT_BEGIN, start + 1)
    if not values:
        raise ValueError("no complete GDA result record in stdout")
    if len(values) > 1:
        raise ValueError(
            f"{len(values)} complete GDA result records in stdout, expected one"
        )
    return values[0]


def build_result(payload: Any) -> str:
    """Wrap ``payload`` as the ADR-0002 sentinel result string — the inverse of
    :func:`parse_result`.

    The single place the sentinel string is constructed. The engine op, the daemon,
    and the live client all emit ``<<<GDA:RESULT>>>{json}<<<GDA:END>>>`` followed by
    a trailing newline (matching what every emitter wrote before this was shared), so
    a relayed or synthesized result is byte-identical to a real engine run's.
    """
    return f"{RESULT_BEGIN}{json.dumps(payload)}{RESULT_END}\n"


def error_envelope(code: str, message: str, probe: dict | None = None) -> dict:
    """The ADR-0002 operation-error payload — ``{"error": {"code", "message"}}``.

    The one place that envelope dict is built (it mirrors
    :class:`~gda.core.contract.envelope.OperationErrorEnvelope`); wrap it with
    :func:`build_result` to synthesize a sentinel error result.

    ``probe`` is the OPTIONAL live-channel extension (#667): the daemon relays a
    windowed refusal that a HOST PROBE decided, and the probe context has to survive
    the relay or the authoritative lazy-launch path would report a strictly poorer
    failure than the CLI fail-fast does. The key is omitted entirely when absent, so
    every other envelope on this wire — and the whole GDScript-emitted headless
    sentinel, whose model stays ``extra="forbid"`` with no ``probe`` — is
    byte-identical to before. Only the live envelope model
    (:class:`~gda.core.contract.envelope.LiveErrorEnvelope`) accepts it.
    """
    error: dict = {"code": code, "message": message}
    if probe is not None:
        error["probe"] = probe
    return {"error": error}


@dataclass
class SubprocessGodotRunner:
    """A GodotRunner that spawns a one-shot ``godot --headless --script`` process.

    It dispatches the operation to the bundled ``operations.gd`` payload and
    returns the process's raw stdout/stderr/exit code unparsed — extracting the
    result from the noise is the parser's job (ADR-0002). When ``project`` is
    set it is passed as ``--path`` so the engine runs against that project and
    ``res://`` resolves there (issue #32).

    When ``project`` is ``None``, the engine reads the invoker's working directory and
    loads the project it finds there, if any (#1035): a ``project.godot``, a
    ``project.binary`` or an ``<executable name>.pck`` makes it load that project and
    start its autoloads (``ProjectSettings::_setup``). ``ignore_cwd`` is how a run that
    must load no project gets none: :func:`gda.core.engine.launch.launch` then passes an
    empty directory from the launch's user-data placement as ``--path``, which only sets
    the engine's working directory (``Main::setup`` calls ``set_cwd``). It applies only
    to a run without a ``project``.
    """

    binary: Path
    project: Path | None = None
    script: Path = OPERATIONS_GD
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    ignore_cwd: bool = False

    def __post_init__(self) -> None:
        if self.ignore_cwd and self.project is not None:
            raise ValueError("ignore_cwd applies only to a run without a project")

    def run(self, operation: str, params: dict) -> RunResult:
        # Build only this channel's argv tail (:func:`sentinel_args`, shared with the
        # one other channel that dispatches a sentinel op) and delegate the spawn /
        # timeout / OSError / UTF-8-decode handling to the shared launch primitive
        # (#185).
        #
        # A sentinel op never needs gda to change the spawn's working directory, so
        # cwd is always the default. The engine's own working directory is --path:
        # the project, or the empty directory that ``ignore_cwd`` asks the launch
        # for (#1035).
        return launch(
            self.binary,
            sentinel_args(operation, params, project=self.project, script=self.script),
            cwd=None,
            timeout=self.timeout,
            ignore_cwd=self.ignore_cwd,
        )
