"""The ``gda`` CLI entrypoint.

Meta commands (about ``gda`` or the engine itself) sit at the top level;
domain commands are grouped under their Godot domain object (ADR-0005).
``gda info`` is the Phase-1 tracer bullet; the ``scene`` group is the first
domain group (issue #18). Every command drives the same headless pipeline:
binary resolution → runner → sentinel parse → typed model → JSON.
"""

import json
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
    ListedNode,
    NodeAddParams,
    NodeAddResult,
    NodeGetParams,
    NodeGetResult,
    NodeListParams,
    NodeListResult,
    NodeSetParams,
    NodeSetResult,
    SceneCreateParams,
    SceneCreateResult,
    SceneDeleteParams,
    SceneDeleteResult,
    SceneGetParams,
    SceneGetResult,
    SceneListParams,
    SceneListResult,
    SceneNode,
    ScriptCreateParams,
    ScriptCreateResult,
    ScriptGetParams,
    ScriptGetResult,
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
scene_app = typer.Typer(help="Act on Godot scene files (.tscn).", no_args_is_help=True)
app.add_typer(scene_app, name="scene")

# The node command group (issue #53): commands acting on nodes WITHIN a scene
# file (load → locate → mutate → pack → save), so they stay headless.
node_app = typer.Typer(
    help="Act on nodes within a scene file (.tscn).", no_args_is_help=True
)
app.add_typer(node_app, name="node")

# The script command group (issue #110): commands acting on .gd/.cs script
# files on disk (write text / read text back), so they stay headless.
script_app = typer.Typer(
    help="Act on script files (.gd/.cs).", no_args_is_help=True
)
app.add_typer(script_app, name="script")


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

SCENE_LIST_COMMAND: HeadlessCommand[SceneListResult] = HeadlessCommand(
    operation="scene-list",
    input_model=SceneListParams,
    output_model=SceneListResult,
)

SCENE_DELETE_COMMAND: HeadlessCommand[SceneDeleteResult] = HeadlessCommand(
    operation="scene-delete",
    input_model=SceneDeleteParams,
    output_model=SceneDeleteResult,
)

NODE_ADD_COMMAND: HeadlessCommand[NodeAddResult] = HeadlessCommand(
    operation="node-add",
    input_model=NodeAddParams,
    output_model=NodeAddResult,
)

NODE_LIST_COMMAND: HeadlessCommand[NodeListResult] = HeadlessCommand(
    operation="node-list",
    input_model=NodeListParams,
    output_model=NodeListResult,
)

NODE_GET_COMMAND: HeadlessCommand[NodeGetResult] = HeadlessCommand(
    operation="node-get",
    input_model=NodeGetParams,
    output_model=NodeGetResult,
)

NODE_SET_COMMAND: HeadlessCommand[NodeSetResult] = HeadlessCommand(
    operation="node-set",
    input_model=NodeSetParams,
    output_model=NodeSetResult,
)

SCRIPT_CREATE_COMMAND: HeadlessCommand[ScriptCreateResult] = HeadlessCommand(
    operation="script-create",
    input_model=ScriptCreateParams,
    output_model=ScriptCreateResult,
)

SCRIPT_GET_COMMAND: HeadlessCommand[ScriptGetResult] = HeadlessCommand(
    operation="script-get",
    input_model=ScriptGetParams,
    output_model=ScriptGetResult,
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


def _render_tree(node: "SceneNode | ListedNode", depth: int = 0) -> str:
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


def _render_scene_list(listed: "SceneListResult") -> str:
    """Render the enumerated scenes as ``path (root_name: root_type)`` lines."""
    if not listed.scenes:
        return "(no scenes)"
    lines = []
    for scene in listed.scenes:
        if scene.root_name is not None and scene.root_type is not None:
            lines.append(f"{scene.path} ({scene.root_name}: {scene.root_type})")
        else:
            lines.append(f"{scene.path} (unreadable)")
    return "\n".join(lines)


@scene_app.command(name="list", cls=SCENE_LIST_COMMAND.command_class())
def list_scenes(
    json_output: bool = json_option(),
    schema: bool = SCENE_LIST_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Enumerate the .tscn scenes in the resolved project."""
    SCENE_LIST_COMMAND.emit(
        SceneListParams(),
        godot=godot,
        project=resolve_project_dir(project),
        json_output=json_output,
        render_text=_render_scene_list,
        make_runner=_make_runner,
    )


@scene_app.command(cls=SCENE_DELETE_COMMAND.command_class())
def delete(
    path: str = typer.Argument(..., help="The .tscn scene file to delete."),
    json_output: bool = json_option(),
    schema: bool = SCENE_DELETE_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Delete a scene file and report what was removed."""
    SCENE_DELETE_COMMAND.emit(
        SceneDeleteParams(path=_normalize_path(path)),
        godot=godot,
        project=resolve_project_dir(project),
        json_output=json_output,
        render_text=lambda removed: (
            f"deleted {removed.path} (root {removed.root_name}: {removed.root_type})"
        ),
        make_runner=_make_runner,
    )


@node_app.command(cls=NODE_ADD_COMMAND.command_class())
def add(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node_type: str = typer.Option(
        ...,
        "--type",
        help=(
            "Node type to add: a Godot node class (e.g. Sprite2D), or a "
            "class_name registered in the project's global class list."
        ),
    ),
    parent: str = typer.Option(
        ".",
        "--parent",
        help=(
            "Parent node path, relative to the scene root: '.' addresses the "
            "root itself, 'Player/Arm' a nested node."
        ),
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        help="Name for the new node. Defaults to the type name.",
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_ADD_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Add a node to a scene file under the given parent node path."""
    NODE_ADD_COMMAND.emit(
        NodeAddParams(
            path=_normalize_path(path),
            parent=parent,
            type=node_type,
            name=name if name is not None else node_type,
        ),
        godot=godot,
        project=resolve_project_dir(project),
        json_output=json_output,
        render_text=lambda added: (
            f"added {added.path} ({added.type}) to {added.scene_path}"
        ),
        make_runner=_make_runner,
    )


@node_app.command(name="list", cls=NODE_LIST_COMMAND.command_class())
def list_nodes(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = json_option(),
    schema: bool = NODE_LIST_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """List a scene's node tree with each node's path relative to the root."""
    NODE_LIST_COMMAND.emit(
        NodeListParams(path=_normalize_path(path)),
        godot=godot,
        project=resolve_project_dir(project),
        json_output=json_output,
        render_text=lambda listed: _render_tree(listed.root),
        make_runner=_make_runner,
    )


def _render_node_properties(got: "NodeGetResult") -> str:
    """Render a node's properties as ``name (Type) = value`` lines for humans."""
    header = f"{got.path} ({got.type})"
    lines = [
        f"  {prop.name} ({prop.type}) = {json.dumps(prop.value)}"
        for prop in got.properties
    ]
    return "\n".join([header, *lines])


@node_app.command(cls=NODE_GET_COMMAND.command_class())
def get(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path, relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_GET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a node's properties (by node path) as typed JSON."""
    NODE_GET_COMMAND.emit(
        NodeGetParams(path=_normalize_path(path), node=node),
        godot=godot,
        project=resolve_project_dir(project),
        json_output=json_output,
        render_text=_render_node_properties,
        make_runner=_make_runner,
    )


@node_app.command(name="set", cls=NODE_SET_COMMAND.command_class())
def set_property(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path, relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        ),
    ),
    property: str = typer.Option(
        ..., "--property", help="The property to set (e.g. position, visible)."
    ),
    value: str = typer.Option(
        ...,
        "--value",
        help=(
            "The value to set, as a string. Coerced to the property's declared "
            "Godot type; an uncoercible value is a clean error."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_SET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Set a node property, coercing the value to its declared Godot type."""
    NODE_SET_COMMAND.emit(
        NodeSetParams(
            path=_normalize_path(path), node=node, property=property, value=value
        ),
        godot=godot,
        project=resolve_project_dir(project),
        json_output=json_output,
        render_text=lambda was_set: (
            f"set {was_set.path}.{was_set.property} ({was_set.type}) = "
            f"{json.dumps(was_set.value)}"
        ),
        make_runner=_make_runner,
    )


def _render_script_metadata(script: "ScriptCreateResult | ScriptGetResult") -> str:
    """Render a script's path plus its class_name/extends for humans."""
    meta = []
    if script.extends is not None:
        meta.append(f"extends {script.extends}")
    if script.class_name is not None:
        meta.append(f"class_name {script.class_name}")
    if not meta:
        return script.path
    return f"{script.path} ({', '.join(meta)})"


@script_app.command(cls=SCRIPT_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .gd/.cs script path to write."),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help=(
            "Verbatim script source to write. Mutually exclusive with --extends; "
            "when omitted, a minimal template extending --extends is written."
        ),
    ),
    extends_type: Optional[str] = typer.Option(
        None,
        "--extends",
        help=(
            "Base class for the built-in template's 'extends' line (e.g. Node, "
            "Node2D). Defaults to Node. Ignored — and rejected — with --content."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_CREATE_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .gd/.cs script from a template or verbatim --content."""
    if content is not None and extends_type is not None:
        raise typer.BadParameter("--content and --extends are mutually exclusive.")
    normalized_path = _normalize_path(path)
    # The built-in template is GDScript (`extends`-based); it is meaningless as
    # C#, so a .cs target must supply its source verbatim via --content rather
    # than get a GDScript-shaped template written into a .cs file.
    if content is None and normalized_path.lower().endswith(".cs"):
        raise typer.BadParameter(
            "a .cs script needs --content; the built-in template is GDScript-only."
        )
    SCRIPT_CREATE_COMMAND.emit(
        ScriptCreateParams(
            path=normalized_path,
            content=content,
            extends_type=extends_type,
        ),
        godot=godot,
        project=resolve_project_dir(project),
        json_output=json_output,
        render_text=lambda created: f"created {_render_script_metadata(created)}",
        make_runner=_make_runner,
    )


@script_app.command(name="get", cls=SCRIPT_GET_COMMAND.command_class())
def get_script(
    path: str = typer.Argument(..., help="The .gd/.cs script file to read."),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_GET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a script's source and report its class_name/extends metadata."""
    SCRIPT_GET_COMMAND.emit(
        ScriptGetParams(path=_normalize_path(path)),
        godot=godot,
        project=resolve_project_dir(project),
        json_output=json_output,
        render_text=lambda got: "\n".join(
            [_render_script_metadata(got), got.source]
        ),
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
