"""The ``gda`` CLI entrypoint.

Meta commands (about ``gda`` or the engine itself) sit at the top level;
domain commands are grouped under their Godot domain object (ADR-0005).
``gda info`` is the Phase-1 tracer bullet; the ``scene`` group is the first
domain group (issue #18). Every command drives the same headless pipeline:
binary resolution → runner → sentinel parse → typed model → JSON.
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


# Path normalization lives in the models (ADR-0015) via the NormalizedPath field
# type, the single home shared by the argv and ``--params-json`` paths — every
# command's body (``export run`` included, since ADR-0023 routed it through a built
# ``ExportRunParams``) passes its raw path straight to the params model, which
# ~-expands it. There is no CLI-layer normalization step left to share.


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
