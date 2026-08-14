"""The ``gda`` CLI composition root (ADR-0040).

This module holds no command: it creates the root Typer app and calls the
``register(root)`` of every ``gda.commands.<group>`` module, in the historical
mount order so ``gda --help`` is unchanged. A group module owns its own vertical
slice (models, renderers, descriptors, Typer bodies) and mounts its sub-app;
``meta`` attaches its top-level, ungrouped commands directly (ADR-0005).
Mounting IS the registration — the live Typer tree stays the only registry
(ADR-0012/0023), so nothing here is a parallel table to keep in sync.

Also here: the root ``--version`` option and the no-op root callback that keeps
``gda`` a command *group*. ``gda.cli:app`` is the packaged entry point.
"""

from importlib.metadata import version as package_version
from typing import Optional

import typer

from gda.commands import (
    daemon as daemon_commands,
    diag as diag_commands,
    export as export_commands,
    game as game_commands,
    input as input_commands,
    logger as logger_commands,
    meta as meta_commands,
    node as node_commands,
    perf as perf_commands,
    project as project_commands,
    resource as resource_commands,
    scene as scene_commands,
    screen as screen_commands,
    script as script_commands,
    shader as shader_commands,
    theme as theme_commands,
)

app = typer.Typer(
    name="gda",
    help="An agent-facing Godot CLI with structured output.",
    no_args_is_help=True,
    add_completion=False,
)

# Each group owns its sub-app (ADR-0040) and mounts it here, at the same point in
# the sequence the old `add_typer` call occupied, so the registration order — and
# therefore `gda --help` — is unchanged.
scene_commands.register(app)
node_commands.register(app)

script_commands.register(app)

resource_commands.register(app)

export_commands.register(app)

project_commands.register(app)

shader_commands.register(app)

theme_commands.register(app)

game_commands.register(app)

diag_commands.register(app)

logger_commands.register(app)

perf_commands.register(app)

input_commands.register(app)

screen_commands.register(app)

daemon_commands.register(app)


def _version_callback(value: Optional[bool]) -> None:
    if value:
        typer.echo(f"gda {package_version('gda')}")
        raise typer.Exit()


@app.callback()
def main(
    show_version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed gda version and exit.",
    ),
) -> None:
    """An agent-facing Godot CLI with structured output."""
    # A no-op callback keeps gda a command *group* so meta commands like
    # `gda info` stay named subcommands (ADR-0005) rather than collapsing to
    # the top level, as Typer does for a single-command app.


meta_commands.register(app)
