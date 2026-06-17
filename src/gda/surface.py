"""Aggregate command-surface introspection for ``gda schema`` (ADR-0012).

The whole-surface generalisation of per-command ``--schema`` (ADR-0004):
:func:`build_surface_manifest` walks the *live* Typer command tree and emits one
:class:`~gda.models.CommandManifestEntry` per command. Walking the registered
tree — rather than a hand-maintained list — keeps the manifest a faithful mirror
of the installed ``gda``: a newly registered command appears automatically, with
no central registry to update (ADR-0012's zero-touch sync). Each entry's
``input`` / ``output`` / ``error`` is derived through the same
:meth:`~gda.models.CommandSchema.of` that backs a single command's ``--schema``,
so there is one source of truth for a command's contract.
"""

import typer

from gda.models import CommandManifestEntry, CommandSchema, SurfaceManifest


def build_surface_manifest(app: typer.Typer) -> SurfaceManifest:
    """Walk ``app``'s live command tree into the aggregate surface manifest.

    Recurses every group into its leaf commands; the manifest is sorted by
    ``name`` so its output is deterministic (stable to diff and to test).
    """
    root = typer.main.get_command(app)
    entries: list[CommandManifestEntry] = []
    _collect(root, [], entries)
    entries.sort(key=lambda entry: entry.name)
    return SurfaceManifest(commands=entries)


def _collect(
    command: object, path: list[str], entries: list[CommandManifestEntry]
) -> None:
    """Append ``command`` (or, if a group, its descendant leaves) to ``entries``.

    ``path`` is the chain of command names from the root *excluding* the root
    itself, so a top-level meta command (``info``) yields a bare ``name`` while a
    grouped command yields the ``<group> <command>`` MCP mapping basis (ADR-0005).

    A group is identified by its ``commands`` mapping (Click groups have one, leaf
    commands do not) — a duck-type that avoids importing Click, which is only a
    transitive dependency through Typer.
    """
    subcommands = getattr(command, "commands", None)
    if subcommands is not None:
        for name, subcommand in subcommands.items():
            _collect(subcommand, [*path, name], entries)
        return

    # Every leaf command owns its ``--schema`` (the ADR-0004 hard gate), which
    # puts its models on the command class (gda.headless.schema_command_class). A
    # command missing them was registered without that gate — fail loudly with
    # the actionable cause rather than emit a silently incomplete manifest.
    input_model = getattr(command, "gda_input_model", None)
    output_model = getattr(command, "gda_output_model", None)
    if input_model is None or output_model is None:
        raise RuntimeError(
            f"command {' '.join(path)!r} exposes no --schema models; every command "
            "must be registered via HeadlessCommand.command_class() (ADR-0004)."
        )
    schema = CommandSchema.of(input_model, output_model)
    description = (command.help or command.short_help or "").strip()
    entries.append(
        CommandManifestEntry(
            name=" ".join(path),
            description=description,
            input=schema.input,
            output=schema.output,
            error=schema.error,
        )
    )
