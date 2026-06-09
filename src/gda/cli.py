"""The ``gda`` CLI entrypoint.

Meta commands (about ``gda`` or the engine itself) sit at the top level
(ADR-0005). ``gda info`` is the first such command and the Phase-1 tracer
bullet: it runs the headless ``info`` operation and reports the engine version.
"""

import sys
from pathlib import Path
from typing import NoReturn, Optional

import typer

from gda.binary import resolve_godot_binary
from gda.errors import Failure, classify_info
from gda.models import CommandSchema, EngineVersion, GdaErrorEnvelope, InfoParams
from gda.runner import GodotRunner, SubprocessGodotRunner

app = typer.Typer(
    name="gda",
    help="An agent-facing Godot CLI with structured output.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """An agent-facing Godot CLI with structured output."""
    # A no-op callback keeps gda a command *group* so meta commands like
    # `gda info` stay named subcommands (ADR-0005) rather than collapsing to
    # the top level, as Typer does for a single-command app.


def _make_runner(binary: Path) -> GodotRunner:
    """Build the default (real) Godot runner for ``binary``.

    A seam tests override (via monkeypatch) to inject a fake runner.
    """
    return SubprocessGodotRunner(binary)


def _fail(failure: Failure) -> NoReturn:
    """Emit a structured error to stdout and exit non-zero (issue #3).

    The error JSON is the stdout contract for the failure path (always emitted,
    independent of ``--json``); the process exit code distinguishes categories.
    ``NoReturn`` lets the type checker prove the caller's fallthrough narrows
    the classification to the success model.
    """
    typer.echo(GdaErrorEnvelope(error=failure.error).model_dump_json())
    raise typer.Exit(code=failure.exit_code)


@app.command()
def info(
    json_output: bool = typer.Option(
        False, "--json", help="Emit the result as a single JSON object."
    ),
    schema: bool = typer.Option(
        False,
        "--schema",
        help="Emit this command's input/output JSON Schemas; no Godot is spawned.",
    ),
    godot: Optional[str] = typer.Option(
        None,
        "--godot",
        help="Path to the Godot binary (overrides $GDA_GODOT and the default).",
    ),
) -> None:
    """Report the Godot engine version info."""
    if schema:
        # Local, no-Godot self-description (ADR-0004): derived from the same
        # typed models that back --json. Short-circuit before touching the
        # engine — no binary resolution, no process spawned.
        typer.echo(CommandSchema.of(InfoParams, EngineVersion).model_dump_json())
        return

    binary = resolve_godot_binary(godot)
    runner = _make_runner(binary)
    result = runner.run("info", {})

    # stdout carries only the result payload; engine/script diagnostics are
    # surfaced on stderr (ADR-0002).
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    outcome = classify_info(result, binary)
    if isinstance(outcome, Failure):
        _fail(outcome)
    version = outcome

    if json_output:
        typer.echo(version.model_dump_json())
    else:
        typer.echo(version.string)
