"""The ``gda`` CLI entrypoint.

Meta commands (about ``gda`` or the engine itself) sit at the top level
(ADR-0005). ``gda info`` is the first such command and the Phase-1 tracer
bullet: it runs the headless ``info`` operation and reports the engine version.
"""

import sys
from pathlib import Path
from typing import Optional

import typer

from gda.binary import resolve_godot_binary
from gda.models import EngineVersion
from gda.parser import parse_result
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


@app.command()
def info(
    json_output: bool = typer.Option(
        False, "--json", help="Emit the result as a single JSON object."
    ),
    godot: Optional[str] = typer.Option(
        None,
        "--godot",
        help="Path to the Godot binary (overrides $GDA_GODOT and the default).",
    ),
) -> None:
    """Report the Godot engine version info."""
    binary = resolve_godot_binary(godot)
    runner = _make_runner(binary)
    result = runner.run("info", {})

    # stdout carries only the result payload; engine/script diagnostics are
    # surfaced on stderr (ADR-0002).
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.exit_code != 0:
        raise typer.Exit(code=1)

    version = EngineVersion.model_validate(parse_result(result.stdout))

    if json_output:
        typer.echo(version.model_dump_json())
    else:
        typer.echo(version.string)
