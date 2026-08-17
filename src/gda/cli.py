"""The ``gda`` CLI composition root (ADR-0040).

This module holds no command: it creates the root Typer app and calls the
``register(root)`` of every ``gda.commands.<group>`` module, in the historical
mount order so ``gda --help`` is unchanged. A group module owns its own vertical
slice (models, renderers, descriptors, Typer bodies) and mounts its sub-app;
``meta`` attaches its top-level, ungrouped commands directly (ADR-0005).
Mounting IS the registration — the live Typer tree stays the only registry
(ADR-0012/0023), so nothing here is a parallel table to keep in sync.

Also here: the root ``--version`` / ``--json`` options and the no-op root callback
that keeps ``gda`` a command *group*. ``--version`` renders through
``gda.provenance``, which owns the payload itself. ``gda.cli:app`` is the packaged
entry point.
"""

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
from gda.headless import root_json, set_root_json
from gda.provenance import build_version_provenance, render_version_line
from gda.runner import USER_DATA_ROOT_ENV, set_user_data_root

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


def _record_root_json(ctx: typer.Context, value: bool) -> bool:
    """Hand a root ``--json`` to the shared option layer as soon as it is bound.

    Recorded from the option's OWN callback rather than the group-callback body so
    the value is in place before any other root option is processed — which is what
    lets ``--version`` below render either form (#659). How the value travels is the
    option layer's contract (``gda.headless.set_root_json``), not this module's.
    """
    set_root_json(ctx, value)
    return value


def _version_callback(ctx: typer.Context, value: Optional[bool]) -> None:
    """Render the root ``--version``: a human line, or the provenance payload.

    ``--json`` selects the structured form (#659), so an agent's evidence collector
    reads which ``gda`` ran — version, executable, interpreter, install kind, and an
    editable install's source checkout and revision — instead of parsing one line of
    prose. No Godot is spawned either way.
    """
    if not value or ctx.resilient_parsing:
        return
    if root_json(ctx):
        typer.echo(build_version_provenance().model_dump_json())
    else:
        typer.echo(render_version_line())
    raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    show_version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        # NOT eager, deliberately (#659). Click orders parameter processing by
        # `(not is_eager, argv index)`, so an EAGER `--version` would run in argv
        # order against the eager `--json` below and never see it in the
        # `gda --version --json` spelling — the exact spelling the dogfooding report
        # used. Non-eager, it sorts after EVERY eager parameter instead, so `--json`
        # is bound first in BOTH orders. The trade is that click's own eager
        # `--help` now wins over `--version` when both are given, which is the
        # conventional precedence anyway.
        help="Show the installed gda version and exit; with --json, emit structured "
        "install provenance instead (no Godot is spawned).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        callback=_record_root_json,
        # Eager, so the flag is bound before every non-eager root option — notably
        # `--version`, whose callback reads it. (A SUBCOMMAND is unaffected either
        # way: this callback body runs before click parses one.)
        is_eager=True,
        help="Emit the invoked command's result as JSON — the same as passing "
        "--json after the command; with --version it emits structured install "
        "provenance (`--help` stays text).",
    ),
    user_data_root: Optional[str] = typer.Option(
        None,
        "--user-data-root",
        help="Directory to place Godot's user data under for a HEADLESS launch: "
        f"the engine log and `user://` (overrides ${USER_DATA_ROOT_ENV}). By "
        "default gda redirects only the engine log, to a private temporary file, "
        "so a read-only application-data directory is not fatal and concurrent "
        "runs do not share one log; pass this when `user://` itself must be "
        "writable. Godot reads the export templates and editor settings from that "
        "same directory, so a release/debug 'export run' under it finds no "
        "installed templates unless you place them there ('--mode pack' needs "
        "none). A live session is unaffected: the daemon owns its log (ADR-0022).",
    ),
) -> None:
    """An agent-facing Godot CLI with structured output."""
    # This callback keeps gda a command *group* so meta commands like `gda info`
    # stay named subcommands (ADR-0005) rather than collapsing to the top level,
    # as Typer does for a single-command app.
    #
    # `--json` is accepted here so the ONE documented rule an agent follows —
    # "always pass --json" — never dies with exit 2 on the discovery surface
    # (`gda --json --help`, `gda --json <group> <command> …`, #671). It is NOT
    # inert: handing it to the shared option layer makes the invoked command's own
    # `--json` inherit it, so the root and post-command spellings mean the same
    # thing — accepting a flag that silently returned human text would be worse than
    # the loud usage error it replaced. The --json hand-over happens in the
    # option's own callback (`_record_root_json`), so it needs no line here.
    # `--user-data-root` is a root option because it is process-wide ENVIRONMENT
    # placement, not an operation parameter: it applies to whichever command runs,
    # on every channel that spawns an engine, and the runner reads it there (#653).
    # Handing it over here keeps the knowledge running downward.
    set_user_data_root(user_data_root)


meta_commands.register(app)
