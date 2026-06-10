"""The ``gda`` CLI entrypoint.

Meta commands (about ``gda`` or the engine itself) sit at the top level;
domain commands are grouped under their Godot domain object (ADR-0005).
``gda info`` is the Phase-1 tracer bullet; the ``scene`` group is the first
domain group (issue #18). Every command drives the same headless pipeline:
binary resolution → runner → sentinel parse → typed model → JSON.
"""

from importlib.metadata import version as package_version
from pathlib import Path
from typing import Optional

import typer

from gda.errors import classify_info
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    make_subprocess_runner,
    project_option,
)
from gda.models import (
    EngineVersion,
    InfoParams,
    SceneCreateParams,
    SceneCreateResult,
    SceneGetParams,
    SceneGetResult,
    SceneNode,
)
from gda.project import resolve_project_dir
from gda.runner import GodotRunner

app = typer.Typer(
    name="gda",
    help="An agent-facing Godot CLI with structured output.",
    no_args_is_help=True,
    add_completion=False,
)

# The first domain command group (ADR-0005): commands acting on scene files.
scene_app = typer.Typer(
    help="Act on Godot scene files (.tscn).", no_args_is_help=True
)
app.add_typer(scene_app, name="scene")


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


def _make_runner(binary: Path, project: Optional[Path]) -> GodotRunner:
    """Build the default (real) Godot runner for ``binary`` and ``project``.

    A seam tests override (via monkeypatch) to inject a fake runner.
    """
    return make_subprocess_runner(binary, project)


INFO_COMMAND: HeadlessCommand[EngineVersion] = HeadlessCommand(
    operation="info",
    input_model=InfoParams,
    output_model=EngineVersion,
    classify=classify_info,
)

SCENE_CREATE_COMMAND: HeadlessCommand[SceneCreateResult] = HeadlessCommand(
    operation="scene-create",
    input_model=SceneCreateParams,
    output_model=SceneCreateResult,
)

SCENE_GET_COMMAND: HeadlessCommand[SceneGetResult] = HeadlessCommand(
    operation="scene-get",
    input_model=SceneGetParams,
    output_model=SceneGetResult,
)


def _normalize_path(path: str) -> str:
    """Normalize a path argument at the CLI layer (issue #32).

    Engine-resolved virtual paths (``res://``, ``user://``, ``uid://``) pass
    through untouched — the engine resolves them against the project. A
    filesystem path gets ``~`` expanded so a literal ``~`` works without a shell.
    """
    if "://" in path:
        return path
    return str(Path(path).expanduser())


def _derive_scene_root_name(path: str) -> str:
    """Derive the default scene root name from the target file name."""
    filename = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if "." in filename:
        return filename.rsplit(".", 1)[0]
    return filename


def _render_tree(node: SceneNode, depth: int = 0) -> str:
    """Render a node tree as an indented ``name (Type)`` outline for humans."""
    lines = [f"{'  ' * depth}{node.name} ({node.type})"]
    lines += (_render_tree(child, depth + 1) for child in node.children)
    return "\n".join(lines)


@scene_app.command(cls=SCENE_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .tscn path to write."),
    root_type: str = typer.Option(
        ...,
        "--root-type",
        help="Godot node class of the new scene's root (e.g. Node2D).",
    ),
    root_name: Optional[str] = typer.Option(
        None,
        "--root-name",
        help=(
            "Root node name to write. Defaults to the target filename without "
            "its final extension."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SCENE_CREATE_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .tscn scene file with the given root node type."""
    normalized_path = _normalize_path(path)
    SCENE_CREATE_COMMAND.emit(
        SceneCreateParams(
            path=normalized_path,
            root_type=root_type,
            root_name=root_name
            if root_name is not None
            else _derive_scene_root_name(normalized_path),
        ),
        godot=godot,
        project=resolve_project_dir(project),
        json_output=json_output,
        render_text=lambda created: (
            f"created {created.path} (root {created.root_type})"
        ),
        make_runner=_make_runner,
    )


@scene_app.command(cls=SCENE_GET_COMMAND.command_class())
def get(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = json_option(),
    schema: bool = SCENE_GET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a scene file and report its structured node tree."""
    SCENE_GET_COMMAND.emit(
        SceneGetParams(path=_normalize_path(path)),
        godot=godot,
        project=resolve_project_dir(project),
        json_output=json_output,
        render_text=lambda scene: _render_tree(scene.root),
        make_runner=_make_runner,
    )


@app.command(cls=INFO_COMMAND.command_class())
def info(
    json_output: bool = json_option(),
    schema: bool = INFO_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
) -> None:
    """Report the Godot engine version info."""
    INFO_COMMAND.emit(
        InfoParams(),
        godot=godot,
        json_output=json_output,
        render_text=lambda version: version.string,
        make_runner=_make_runner,
    )
