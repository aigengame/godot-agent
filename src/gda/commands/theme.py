"""The ``theme`` command group: Godot Theme resource files (.tres) as the domain object.

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderer, its ``HeadlessCommand`` descriptor
(ADR-0023), and its Typer command body, and mounts them on the root app through
:func:`register`. It imports the shared machinery downward — the dispatch tail
(``gda.dispatch``), the descriptor machinery (``gda.headless``) and the
cross-command contract core (``gda.models``) — and is imported by nothing but
the composition root (``gda.cli``).
"""

from typing import Optional

import typer
from pydantic import BaseModel, Field

from gda.dispatch import _dispatch
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.models import NormalizedPath


class ThemeCreateParams(BaseModel):
    """The operation params of ``gda theme create`` (issue #115).

    ``path`` is the target ``.tres`` file. Unlike the shader trio (plain
    file authoring), a Theme is an ENGINE-BACKED resource: the operation
    constructs a ``Theme`` and writes it through ``ResourceSaver`` so the result
    is a genuine, loadable ``.tres`` (verified by loading it back), not hand-
    written text. The split mirrors the script group: file-level ops author text;
    a resource-producing op goes through the engine.
    """

    path: NormalizedPath = Field(description="Target .tres Theme path to write.")


class ThemeCreateResult(BaseModel):
    """The result of ``gda theme create``: the created Theme resource (issue #115).

    Echoes the saved ``path`` and the resource ``type`` written (``Theme``), so
    an agent can assert the effect without a second call. ``created_dirs`` lists
    parent directories the operation created before saving, from outermost to
    innermost.
    """

    path: str
    type: str = Field(description="The resource type written to the .tres (Theme).")
    created_dirs: list[str] = Field(
        description=(
            "Parent directories created before saving, from outermost to innermost."
        )
    )


def render_theme_create(created: "ThemeCreateResult") -> str:
    """Render a created theme as ``created <path> (<type>)``."""
    return f"created {created.path} ({created.type})"


THEME_CREATE_COMMAND: HeadlessCommand[ThemeCreateResult] = HeadlessCommand(
    operation="theme-create",
    input_model=ThemeCreateParams,
    output_model=ThemeCreateResult,
    render=render_theme_create,
)


# The second of the asset-file groups (issue #115; the first is
# gda.commands.shader): headless authoring of the asset-file types. `theme create`
# produces a loadable .tres Theme resource (engine-backed), unlike the shader trio
# that authors plain text — the same file-level vs engine-backed split the script
# group draws between create/get/set and attach/validate. Like every command it
# goes through the headless runner, so resolving --project still constructs the
# project's autoloads at engine startup (ADR-0009).
_app = typer.Typer(help="Act on theme resource files (.tres).", no_args_is_help=True)


@_app.command(name="create", cls=THEME_CREATE_COMMAND.command_class())
def create_theme(
    path: str = typer.Argument(..., help="Target .tres Theme path to write."),
    json_output: bool = json_option(),
    schema: bool = THEME_CREATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new, loadable .tres Theme resource (no-clobber)."""
    _dispatch(
        THEME_CREATE_COMMAND,
        ThemeCreateParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``theme`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="theme")
