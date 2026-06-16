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
from pydantic import BaseModel

from gda.binary import resolve_godot_binary
from gda.errors import (
    Failure,
    classify_export_run,
    classify_info,
    classify_script_validate,
    export_path_unset_failure,
    export_templates_missing_failure,
)
from gda.export_runner import ExportRunner, make_subprocess_export_runner
from gda.headless import (
    HeadlessCommand,
    HumanRenderer,
    M,
    emit_failure,
    godot_option,
    json_option,
    make_subprocess_runner,
    project_option,
)
from gda.models import (
    EngineVersion,
    ExportGetParams,
    ExportGetResult,
    ExportListParams,
    ExportListResult,
    ExportRunMode,
    ExportRunParams,
    ExportRunResult,
    InfoParams,
    ProjectDependenciesParams,
    ProjectDependenciesResult,
    ProjectFindReferencesParams,
    ProjectFindReferencesResult,
    ProjectFindUnusedResourcesParams,
    ProjectFindUnusedResourcesResult,
    ProjectStatisticsParams,
    ProjectStatisticsResult,
    NodeAddParams,
    NodeAddResult,
    NodeConnectSignalParams,
    NodeConnectSignalResult,
    NodeDisconnectSignalParams,
    NodeDisconnectSignalResult,
    NodeDuplicateParams,
    NodeDuplicateResult,
    NodeGetParams,
    NodeGetResult,
    NodeListParams,
    NodeListResult,
    NodeMoveParams,
    NodeMoveResult,
    NodeRemoveParams,
    NodeRemoveResult,
    NodeSetParams,
    NodeSetResult,
    ProjectAddAutoloadParams,
    ProjectAddAutoloadResult,
    ProjectGetParams,
    ProjectGetResult,
    ProjectInfoParams,
    ProjectInfoResult,
    ProjectRemoveAutoloadParams,
    ProjectRemoveAutoloadResult,
    ProjectSetParams,
    ProjectSetResult,
    ResourceCreateParams,
    ResourceCreateResult,
    ResourceDeleteParams,
    ResourceDeleteResult,
    ResourceGetParams,
    ResourceGetResult,
    ResourceSetParams,
    ResourceSetResult,
    ResourceUidParams,
    ResourceUidResult,
    SceneCreateParams,
    SceneCreateResult,
    SceneDeleteParams,
    SceneDeleteResult,
    SceneGetExportsParams,
    SceneGetExportsResult,
    SceneGetParams,
    SceneGetResult,
    SceneListParams,
    SceneListResult,
    ScriptAttachParams,
    ScriptAttachResult,
    ScriptCreateParams,
    ScriptCreateResult,
    ScriptDeleteParams,
    ScriptDeleteResult,
    ScriptGetParams,
    ScriptGetResult,
    ScriptListParams,
    ScriptListResult,
    ScriptSetMode,
    ScriptSetParams,
    ScriptSetResult,
    ScriptValidateParams,
    ScriptValidateResult,
    ShaderCreateParams,
    ShaderCreateResult,
    ShaderGetParams,
    ShaderGetResult,
    ShaderSetParams,
    ShaderSetResult,
    ThemeCreateParams,
    ThemeCreateResult,
)
from gda.project import resolve_project_dir
from gda.render import render
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

# The script command group (issue #110): commands acting on .gd script files on
# disk (write text / read text back), so they stay headless. C# (.cs) is out of
# scope for now — it needs the .NET build of Godot (ADR-0003 targets the standard
# build) and a dedicated decision.
script_app = typer.Typer(
    help="Act on script files (.gd).", no_args_is_help=True
)
app.add_typer(script_app, name="script")

# The resource command group (issue #112): commands acting on .tres resource
# files on disk (load/save plumbing), so they stay headless. The group is a
# .tres tracer; the binary .res form is out of scope for this slice.
resource_app = typer.Typer(
    help="Act on resource files (.tres).", no_args_is_help=True
)
app.add_typer(resource_app, name="resource")

# The export command group (issue #114): read-only discovery of the project's
# export presets (from export_presets.cfg) and export-template readiness. These
# stay headless — they parse a config file and check the filesystem, never
# running an actual export (that is a later slice, issue #121).
export_app = typer.Typer(
    help="Discover export presets and export-template status.", no_args_is_help=True
)
app.add_typer(export_app, name="export")

# The project command group: commands acting on the Godot project as a whole.
# The project-settings read/write commands (info/get/set, issue #111) read and
# write the resolved project's project.godot / ProjectSettings headlessly. Issue
# #116 adds the read-only, project-wide static-analysis reads (find-references,
# dependencies, find-unused-resources, statistics), all backed by a single static
# project scan that parses files as text — never instantiating a scene or loading
# a script (issue #30). Every project command runs against an explicit project
# context (--project), so — like any --project op — it runs the project's
# autoloads at engine startup (#61, ADR-0009).
project_app = typer.Typer(
    help="Act on the Godot project as a whole.", no_args_is_help=True
)
app.add_typer(project_app, name="project")

# The asset-file groups (issue #115): headless authoring of the asset-file types.
# A .gdshader is plain shader source authored as text (create / get / set author
# the file directly and never load or compile the shader at the operation level),
# while theme create produces a loadable .tres Theme resource (engine-backed) —
# the same file-level vs engine-backed split the script group draws between
# create/get/set and attach/validate. This bounds the operation, not the run:
# every command still goes through the headless runner, so resolving --project
# still constructs the project's autoloads at engine startup (ADR-0009).
shader_app = typer.Typer(
    help="Act on shader files (.gdshader).", no_args_is_help=True
)
app.add_typer(shader_app, name="shader")

theme_app = typer.Typer(
    help="Act on theme resource files (.tres).", no_args_is_help=True
)
app.add_typer(theme_app, name="theme")


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


def _make_export_runner(binary: Path, project: Optional[Path]) -> ExportRunner:
    """Build the default (real) native-export runner for ``binary`` and ``project``.

    The ``export run``-only twin of :func:`_make_runner`: a seam tests override
    to inject a fake export runner, since ``export run`` spawns Godot with native
    ``--export-<mode>`` flags rather than the ``operations.gd`` payload.
    """
    return make_subprocess_export_runner(binary, project)


def _emit(
    cmd: HeadlessCommand[M],
    params: BaseModel,
    *,
    json_output: bool,
    godot: Optional[str],
    project: Optional[Path],
    render: HumanRenderer[M],
) -> None:
    """Drive ``cmd.emit`` with the shared CLI execution tail.

    The sole reference to the runner seam ``_make_runner`` — held here, at call
    time, so the test monkeypatch on ``gda.cli._make_runner`` still binds rather
    than being frozen as a def-time default. Both the domain dispatch
    (:func:`_dispatch`) and the meta dispatch (:func:`_dispatch_meta`) funnel
    through here; they differ only in how ``project`` is obtained.
    """
    cmd.emit(
        params,
        godot=godot,
        project=project,
        json_output=json_output,
        render_text=render,
        make_runner=_make_runner,
    )


def _dispatch(
    cmd: HeadlessCommand[M],
    params: BaseModel,
    *,
    json_output: bool,
    godot: Optional[str],
    project: Optional[str],
    render: HumanRenderer[M],
) -> None:
    """Run a domain command through the shared CLI execution tail.

    Owns the per-command-repeated wiring: project resolution
    (``resolve_project_dir``, kept at the CLI layer per ADR-0006), the runner
    seam, the ``json_output`` pass-through, and the JSON-vs-text branch. Each
    command keeps its own Typer signature, params construction, ``render``, and
    pre-dispatch validation; only this execution tail is shared.
    """
    _emit(
        cmd,
        params,
        json_output=json_output,
        godot=godot,
        project=resolve_project_dir(project),
        render=render,
    )


def _dispatch_meta(
    cmd: HeadlessCommand[M],
    params: BaseModel,
    *,
    json_output: bool,
    godot: Optional[str],
    render: HumanRenderer[M],
) -> None:
    """Run a meta command (no ``--project``, ADR-0005) through the shared tail.

    Unlike :func:`_dispatch`, this never calls ``resolve_project_dir``: a meta
    command (``gda info``) is about ``gda``/the engine itself, so it runs
    projectless rather than resolving a project context.
    """
    _emit(
        cmd,
        params,
        json_output=json_output,
        godot=godot,
        project=None,
        render=render,
    )


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

SCENE_GET_EXPORTS_COMMAND: HeadlessCommand[SceneGetExportsResult] = HeadlessCommand(
    operation="scene-get-exports",
    input_model=SceneGetExportsParams,
    output_model=SceneGetExportsResult,
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

NODE_REMOVE_COMMAND: HeadlessCommand[NodeRemoveResult] = HeadlessCommand(
    operation="node-remove",
    input_model=NodeRemoveParams,
    output_model=NodeRemoveResult,
)

NODE_DUPLICATE_COMMAND: HeadlessCommand[NodeDuplicateResult] = HeadlessCommand(
    operation="node-duplicate",
    input_model=NodeDuplicateParams,
    output_model=NodeDuplicateResult,
)

NODE_MOVE_COMMAND: HeadlessCommand[NodeMoveResult] = HeadlessCommand(
    operation="node-move",
    input_model=NodeMoveParams,
    output_model=NodeMoveResult,
)

NODE_CONNECT_SIGNAL_COMMAND: HeadlessCommand[NodeConnectSignalResult] = HeadlessCommand(
    operation="node-connect-signal",
    input_model=NodeConnectSignalParams,
    output_model=NodeConnectSignalResult,
)

NODE_DISCONNECT_SIGNAL_COMMAND: HeadlessCommand[NodeDisconnectSignalResult] = (
    HeadlessCommand(
        operation="node-disconnect-signal",
        input_model=NodeDisconnectSignalParams,
        output_model=NodeDisconnectSignalResult,
    )
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

SCRIPT_LIST_COMMAND: HeadlessCommand[ScriptListResult] = HeadlessCommand(
    operation="script-list",
    input_model=ScriptListParams,
    output_model=ScriptListResult,
)

SCRIPT_DELETE_COMMAND: HeadlessCommand[ScriptDeleteResult] = HeadlessCommand(
    operation="script-delete",
    input_model=ScriptDeleteParams,
    output_model=ScriptDeleteResult,
)

SCRIPT_SET_COMMAND: HeadlessCommand[ScriptSetResult] = HeadlessCommand(
    operation="script-set",
    input_model=ScriptSetParams,
    output_model=ScriptSetResult,
)

SCRIPT_ATTACH_COMMAND: HeadlessCommand[ScriptAttachResult] = HeadlessCommand(
    operation="script-attach",
    input_model=ScriptAttachParams,
    output_model=ScriptAttachResult,
)

SCRIPT_VALIDATE_COMMAND: HeadlessCommand[ScriptValidateResult] = HeadlessCommand(
    operation="script-validate",
    input_model=ScriptValidateParams,
    output_model=ScriptValidateResult,
    classify=classify_script_validate,
)

RESOURCE_CREATE_COMMAND: HeadlessCommand[ResourceCreateResult] = HeadlessCommand(
    operation="resource-create",
    input_model=ResourceCreateParams,
    output_model=ResourceCreateResult,
)

RESOURCE_GET_COMMAND: HeadlessCommand[ResourceGetResult] = HeadlessCommand(
    operation="resource-get",
    input_model=ResourceGetParams,
    output_model=ResourceGetResult,
)

RESOURCE_SET_COMMAND: HeadlessCommand[ResourceSetResult] = HeadlessCommand(
    operation="resource-set",
    input_model=ResourceSetParams,
    output_model=ResourceSetResult,
)

RESOURCE_DELETE_COMMAND: HeadlessCommand[ResourceDeleteResult] = HeadlessCommand(
    operation="resource-delete",
    input_model=ResourceDeleteParams,
    output_model=ResourceDeleteResult,
)

EXPORT_LIST_COMMAND: HeadlessCommand[ExportListResult] = HeadlessCommand(
    operation="export-list",
    input_model=ExportListParams,
    output_model=ExportListResult,
)

EXPORT_GET_COMMAND: HeadlessCommand[ExportGetResult] = HeadlessCommand(
    operation="export-get",
    input_model=ExportGetParams,
    output_model=ExportGetResult,
)

# export run is the one command that does NOT route through operations.gd: the
# Godot export subsystem is editor-only C++, unreachable from a --script
# SceneTree run, so the export itself is a native --export-<mode> invocation
# (gda.export_runner). This HeadlessCommand is used only for its --schema /
# --json model plumbing; the command body (run_export) drives the two phases by
# hand — export-get resolves the preset + path, the native ExportRunner exports,
# classify_export_run turns the subprocess outcome into the typed result — rather
# than the shared sentinel pipeline.
EXPORT_RUN_COMMAND: HeadlessCommand[ExportRunResult] = HeadlessCommand(
    operation="export-run",
    input_model=ExportRunParams,
    output_model=ExportRunResult,
)

RESOURCE_UID_COMMAND: HeadlessCommand[ResourceUidResult] = HeadlessCommand(
    operation="resource-uid",
    input_model=ResourceUidParams,
    output_model=ResourceUidResult,
)

PROJECT_INFO_COMMAND: HeadlessCommand[ProjectInfoResult] = HeadlessCommand(
    operation="project-info",
    input_model=ProjectInfoParams,
    output_model=ProjectInfoResult,
)

PROJECT_GET_COMMAND: HeadlessCommand[ProjectGetResult] = HeadlessCommand(
    operation="project-get",
    input_model=ProjectGetParams,
    output_model=ProjectGetResult,
)

PROJECT_SET_COMMAND: HeadlessCommand[ProjectSetResult] = HeadlessCommand(
    operation="project-set",
    input_model=ProjectSetParams,
    output_model=ProjectSetResult,
)

PROJECT_ADD_AUTOLOAD_COMMAND: HeadlessCommand[ProjectAddAutoloadResult] = HeadlessCommand(
    operation="project-add-autoload",
    input_model=ProjectAddAutoloadParams,
    output_model=ProjectAddAutoloadResult,
)

PROJECT_REMOVE_AUTOLOAD_COMMAND: HeadlessCommand[ProjectRemoveAutoloadResult] = (
    HeadlessCommand(
        operation="project-remove-autoload",
        input_model=ProjectRemoveAutoloadParams,
        output_model=ProjectRemoveAutoloadResult,
    )
)

SHADER_CREATE_COMMAND: HeadlessCommand[ShaderCreateResult] = HeadlessCommand(
    operation="shader-create",
    input_model=ShaderCreateParams,
    output_model=ShaderCreateResult,
)

SHADER_GET_COMMAND: HeadlessCommand[ShaderGetResult] = HeadlessCommand(
    operation="shader-get",
    input_model=ShaderGetParams,
    output_model=ShaderGetResult,
)

SHADER_SET_COMMAND: HeadlessCommand[ShaderSetResult] = HeadlessCommand(
    operation="shader-set",
    input_model=ShaderSetParams,
    output_model=ShaderSetResult,
)

THEME_CREATE_COMMAND: HeadlessCommand[ThemeCreateResult] = HeadlessCommand(
    operation="theme-create",
    input_model=ThemeCreateParams,
    output_model=ThemeCreateResult,
)

PROJECT_FIND_REFERENCES_COMMAND: HeadlessCommand[ProjectFindReferencesResult] = (
    HeadlessCommand(
        operation="project-find-references",
        input_model=ProjectFindReferencesParams,
        output_model=ProjectFindReferencesResult,
    )
)

PROJECT_DEPENDENCIES_COMMAND: HeadlessCommand[ProjectDependenciesResult] = (
    HeadlessCommand(
        operation="project-dependencies",
        input_model=ProjectDependenciesParams,
        output_model=ProjectDependenciesResult,
    )
)

PROJECT_FIND_UNUSED_RESOURCES_COMMAND: HeadlessCommand[
    ProjectFindUnusedResourcesResult
] = HeadlessCommand(
    operation="project-find-unused-resources",
    input_model=ProjectFindUnusedResourcesParams,
    output_model=ProjectFindUnusedResourcesResult,
)

PROJECT_STATISTICS_COMMAND: HeadlessCommand[ProjectStatisticsResult] = HeadlessCommand(
    operation="project-statistics",
    input_model=ProjectStatisticsParams,
    output_model=ProjectStatisticsResult,
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
    _dispatch(
        SCENE_CREATE_COMMAND,
        SceneCreateParams(
            path=normalized_path,
            root_type=root_type,
            root_name=root_name
            if root_name is not None
            else _derive_scene_root_name(normalized_path),
        ),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
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
    _dispatch(
        SCENE_GET_COMMAND,
        SceneGetParams(path=_normalize_path(path)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@scene_app.command(name="get-exports", cls=SCENE_GET_EXPORTS_COMMAND.command_class())
def get_exports(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = json_option(),
    schema: bool = SCENE_GET_EXPORTS_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """List the @export properties a scene's nodes' scripts declare, per node path."""
    _dispatch(
        SCENE_GET_EXPORTS_COMMAND,
        SceneGetExportsParams(path=_normalize_path(path)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@scene_app.command(name="list", cls=SCENE_LIST_COMMAND.command_class())
def list_scenes(
    json_output: bool = json_option(),
    schema: bool = SCENE_LIST_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Enumerate the .tscn scenes in the resolved project."""
    _dispatch(
        SCENE_LIST_COMMAND,
        SceneListParams(),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
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
    _dispatch(
        SCENE_DELETE_COMMAND,
        SceneDeleteParams(path=_normalize_path(path)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
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
    _dispatch(
        NODE_ADD_COMMAND,
        NodeAddParams(
            path=_normalize_path(path),
            parent=parent,
            type=node_type,
            name=name if name is not None else node_type,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
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
    _dispatch(
        NODE_LIST_COMMAND,
        NodeListParams(path=_normalize_path(path)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


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
    _dispatch(
        NODE_GET_COMMAND,
        NodeGetParams(path=_normalize_path(path), node=node),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
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
    _dispatch(
        NODE_SET_COMMAND,
        NodeSetParams(
            path=_normalize_path(path), node=node, property=property, value=value
        ),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@node_app.command(name="remove", cls=NODE_REMOVE_COMMAND.command_class())
def remove_node(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path of the node to delete, relative to the scene root: "
            "'Player/Arm' a nested node. The root ('.') cannot be removed."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_REMOVE_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Remove a node (and its subtree) from a scene file by node path."""
    _dispatch(
        NODE_REMOVE_COMMAND,
        NodeRemoveParams(path=_normalize_path(path), node=node),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@node_app.command(name="duplicate", cls=NODE_DUPLICATE_COMMAND.command_class())
def duplicate_node(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path of the node to copy, relative to the scene root: "
            "'Player/Arm' a nested node. The copy lands under this node's own "
            "parent with a fresh name. The root ('.') cannot be duplicated."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_DUPLICATE_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Duplicate a node (and its subtree) under its parent with a fresh name."""
    _dispatch(
        NODE_DUPLICATE_COMMAND,
        NodeDuplicateParams(path=_normalize_path(path), node=node),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@node_app.command(name="move", cls=NODE_MOVE_COMMAND.command_class())
def move_node(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path of the node to reparent, relative to the scene root: "
            "'Player/Arm' a nested node. The root ('.') cannot be moved."
        ),
    ),
    to: str = typer.Option(
        ...,
        "--to",
        help=(
            "Node path of the new parent, relative to the scene root: '.' "
            "addresses the root itself, 'Enemies' a nested node. Must not be the "
            "moved node or one of its descendants (a cyclic target)."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_MOVE_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Reparent a node (and its subtree) under a new parent node path."""
    _dispatch(
        NODE_MOVE_COMMAND,
        NodeMoveParams(path=_normalize_path(path), node=node, to=to),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


# The four connection flags reused by both connect-signal and disconnect-signal.
# Defined once so the source/target node-path addressing and the signal/method
# naming stay identical across the wire and unwire commands.
def _from_option() -> str:
    return typer.Option(
        ...,
        "--from",
        help=(
            "Source node path, relative to the scene root: '.' addresses the "
            "root itself, 'Player/Arm' a nested node."
        ),
    )


def _signal_option() -> str:
    return typer.Option(..., "--signal", help="The signal name on the source node.")


def _to_option() -> str:
    return typer.Option(
        ...,
        "--to",
        help=(
            "Target node path, relative to the scene root: '.' addresses the "
            "root itself, 'Player/Arm' a nested node."
        ),
    )


def _method_option() -> str:
    return typer.Option(..., "--method", help="The method name on the target node.")


@node_app.command(
    name="connect-signal", cls=NODE_CONNECT_SIGNAL_COMMAND.command_class()
)
def connect_signal(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    from_node: str = _from_option(),
    signal: str = _signal_option(),
    to: str = _to_option(),
    method: str = _method_option(),
    json_output: bool = json_option(),
    schema: bool = NODE_CONNECT_SIGNAL_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Wire a source node's signal to a target node's method, persisted in the scene."""
    _dispatch(
        NODE_CONNECT_SIGNAL_COMMAND,
        NodeConnectSignalParams(
            path=_normalize_path(path),
            from_node=from_node,
            signal=signal,
            to=to,
            method=method,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@node_app.command(
    name="disconnect-signal", cls=NODE_DISCONNECT_SIGNAL_COMMAND.command_class()
)
def disconnect_signal(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    from_node: str = _from_option(),
    signal: str = _signal_option(),
    to: str = _to_option(),
    method: str = _method_option(),
    json_output: bool = json_option(),
    schema: bool = NODE_DISCONNECT_SIGNAL_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Unwire an existing signal→method connection; errors if it is absent."""
    _dispatch(
        NODE_DISCONNECT_SIGNAL_COMMAND,
        NodeDisconnectSignalParams(
            path=_normalize_path(path),
            from_node=from_node,
            signal=signal,
            to=to,
            method=method,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@script_app.command(cls=SCRIPT_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .gd script path to write."),
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
    """Create a new .gd script from a template or verbatim --content."""
    if content is not None and extends_type is not None:
        raise typer.BadParameter("--content and --extends are mutually exclusive.")
    _dispatch(
        SCRIPT_CREATE_COMMAND,
        ScriptCreateParams(
            path=_normalize_path(path),
            content=content,
            extends_type=extends_type,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@script_app.command(name="get", cls=SCRIPT_GET_COMMAND.command_class())
def get_script(
    path: str = typer.Argument(..., help="The .gd script file to read."),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_GET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a script's source and report its class_name/extends metadata."""
    _dispatch(
        SCRIPT_GET_COMMAND,
        ScriptGetParams(path=_normalize_path(path)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@script_app.command(name="list", cls=SCRIPT_LIST_COMMAND.command_class())
def list_scripts(
    json_output: bool = json_option(),
    schema: bool = SCRIPT_LIST_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Enumerate the .gd scripts in the resolved project."""
    _dispatch(
        SCRIPT_LIST_COMMAND,
        ScriptListParams(),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@script_app.command(name="delete", cls=SCRIPT_DELETE_COMMAND.command_class())
def delete_script(
    path: str = typer.Argument(..., help="The .gd script file to delete."),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_DELETE_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Delete a script file and report what was removed."""
    _dispatch(
        SCRIPT_DELETE_COMMAND,
        ScriptDeleteParams(path=_normalize_path(path)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@script_app.command(name="set", cls=SCRIPT_SET_COMMAND.command_class())
def set_script(
    path: str = typer.Argument(..., help="The .gd script file to edit."),
    search: Optional[str] = typer.Option(
        None,
        "--search",
        help=(
            "search-replace mode: literal substring to find (not regex); all "
            "occurrences are replaced. Requires --replace."
        ),
    ),
    replace: Optional[str] = typer.Option(
        None,
        "--replace",
        help="search-replace mode: literal replacement text. Requires --search.",
    ),
    start_line: Optional[int] = typer.Option(
        None,
        "--start-line",
        help=(
            "line-range mode: first line to replace (1-based, inclusive). "
            "Requires --content."
        ),
    ),
    end_line: Optional[int] = typer.Option(
        None,
        "--end-line",
        help=(
            "line-range mode: last line to replace (1-based, inclusive); "
            "defaults to --start-line. Requires --content and --start-line."
        ),
    ),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help=(
            "Replacement text: the line span in line-range mode, or the whole "
            "file (full mode) when --start-line is omitted."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_SET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Edit a .gd script via search-replace, line-range, or full overwrite."""
    mode = _resolve_set_mode(search, replace, start_line, end_line, content)
    _dispatch(
        SCRIPT_SET_COMMAND,
        ScriptSetParams(
            path=_normalize_path(path),
            mode=mode,
            search=search,
            replace=replace,
            start_line=start_line,
            end_line=end_line,
            content=content,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


def _resolve_set_mode(
    search: Optional[str],
    replace: Optional[str],
    start_line: Optional[int],
    end_line: Optional[int],
    content: Optional[str],
) -> ScriptSetMode:
    """Resolve ``script set``'s edit mode, the single source of truth (issue #133).

    This is the one place the edit mode is decided: it enforces that exactly one
    of the three mutually-exclusive modes is supplied (a violation is a usage
    error, exit 2, like ``script create``'s mutual exclusion) and returns the
    resolved :class:`ScriptSetMode`. The CLI stamps it onto the op params so the
    operation dispatches on this explicit discriminator instead of re-inferring
    the mode from which params are present — the two can no longer drift.
    """
    has_search = search is not None or replace is not None
    has_line_range = start_line is not None or end_line is not None

    if has_search:
        if search is None or replace is None:
            raise typer.BadParameter("--search and --replace must be used together.")
        if content is not None or has_line_range:
            raise typer.BadParameter(
                "--search/--replace cannot be combined with --content, "
                "--start-line, or --end-line."
            )
        return ScriptSetMode.SEARCH_REPLACE

    if has_line_range:
        if content is None:
            raise typer.BadParameter("--start-line/--end-line require --content.")
        if start_line is None:
            raise typer.BadParameter("--end-line requires --start-line.")
        return ScriptSetMode.LINE_RANGE

    if content is None:
        raise typer.BadParameter(
            "script set needs an edit: --search/--replace, --start-line "
            "(+ --content), or --content (full overwrite)."
        )
    return ScriptSetMode.FULL


@script_app.command(name="attach", cls=SCRIPT_ATTACH_COMMAND.command_class())
def attach_script(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path, relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        ),
    ),
    script: str = typer.Option(
        ..., "--script", help="The .gd script file to attach to the node."
    ),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_ATTACH_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Attach a .gd script to a node (by node path) in a scene and save."""
    _dispatch(
        SCRIPT_ATTACH_COMMAND,
        ScriptAttachParams(
            path=_normalize_path(path),
            node=node,
            script=_normalize_path(script),
        ),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@script_app.command(name="validate", cls=SCRIPT_VALIDATE_COMMAND.command_class())
def validate_script(
    path: str = typer.Argument(..., help="The .gd script file to validate."),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_VALIDATE_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Syntax/compile-check a .gd script; an invalid script is a successful op."""
    _dispatch(
        SCRIPT_VALIDATE_COMMAND,
        ScriptValidateParams(path=_normalize_path(path)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@resource_app.command(cls=RESOURCE_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .tres resource path to write."),
    resource_type: str = typer.Option(
        ...,
        "--type",
        help="Godot resource class of the new .tres (e.g. Gradient, Curve).",
    ),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_CREATE_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .tres resource file of the given resource type."""
    _dispatch(
        RESOURCE_CREATE_COMMAND,
        ResourceCreateParams(path=_normalize_path(path), type=resource_type),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@project_app.command(name="info", cls=PROJECT_INFO_COMMAND.command_class())
def project_info(
    json_output: bool = json_option(),
    schema: bool = PROJECT_INFO_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Report the resolved project's metadata (name, main scene, viewport, engine)."""
    _dispatch(
        PROJECT_INFO_COMMAND,
        ProjectInfoParams(),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@project_app.command(name="get", cls=PROJECT_GET_COMMAND.command_class())
def project_get(
    setting: str = typer.Argument(
        ..., help="The project setting's full section/key name (e.g. application/config/name)."
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_GET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a single project setting by section/key as typed JSON."""
    _dispatch(
        PROJECT_GET_COMMAND,
        ProjectGetParams(setting=setting),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@project_app.command(
    name="find-references", cls=PROJECT_FIND_REFERENCES_COMMAND.command_class()
)
def find_references(
    target: str = typer.Argument(
        ...,
        help=(
            "What to find references to: a resource's res:// path (scene, "
            "script, image, .tres, …) or a script class_name."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_FIND_REFERENCES_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Find every project file that references a given resource path or class_name."""
    _dispatch(
        PROJECT_FIND_REFERENCES_COMMAND,
        ProjectFindReferencesParams(target=_normalize_path(target)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@shader_app.command(cls=SHADER_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .gdshader path to write."),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help=(
            "Verbatim shader source to write. Mutually exclusive with "
            "--shader-type; when omitted, a minimal template declaring the "
            "--shader-type is written."
        ),
    ),
    shader_type: Optional[str] = typer.Option(
        None,
        "--shader-type",
        help=(
            "Shader type for the built-in template's 'shader_type' line (e.g. "
            "canvas_item, spatial). Defaults to canvas_item. Ignored — and "
            "rejected — with --content."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SHADER_CREATE_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .gdshader from a template or verbatim --content."""
    if content is not None and shader_type is not None:
        raise typer.BadParameter(
            "--content and --shader-type are mutually exclusive."
        )
    _dispatch(
        SHADER_CREATE_COMMAND,
        ShaderCreateParams(
            path=_normalize_path(path),
            content=content,
            shader_type=shader_type,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@resource_app.command(name="get", cls=RESOURCE_GET_COMMAND.command_class())
def get_resource(
    path: str = typer.Argument(..., help="The .tres resource file to read."),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_GET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a .tres resource and report its properties as typed JSON."""
    _dispatch(
        RESOURCE_GET_COMMAND,
        ResourceGetParams(path=_normalize_path(path)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@resource_app.command(name="set", cls=RESOURCE_SET_COMMAND.command_class())
def set_resource(
    path: str = typer.Argument(..., help="The .tres resource file to mutate."),
    property: str = typer.Option(
        ..., "--property", help="The resource property to set (e.g. interpolation_mode)."
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
    schema: bool = RESOURCE_SET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Set a .tres property, coercing the value to its declared Godot type, then save."""
    _dispatch(
        RESOURCE_SET_COMMAND,
        ResourceSetParams(
            path=_normalize_path(path), property=property, value=value
        ),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@resource_app.command(name="delete", cls=RESOURCE_DELETE_COMMAND.command_class())
def delete_resource(
    path: str = typer.Argument(..., help="The .tres resource file to delete."),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_DELETE_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Delete a .tres resource file and report what was removed."""
    _dispatch(
        RESOURCE_DELETE_COMMAND,
        ResourceDeleteParams(path=_normalize_path(path)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@shader_app.command(name="get", cls=SHADER_GET_COMMAND.command_class())
def get_shader(
    path: str = typer.Argument(..., help="The .gdshader file to read."),
    json_output: bool = json_option(),
    schema: bool = SHADER_GET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a shader's source and report its shader_type metadata."""
    _dispatch(
        SHADER_GET_COMMAND,
        ShaderGetParams(path=_normalize_path(path)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@project_app.command(
    name="dependencies", cls=PROJECT_DEPENDENCIES_COMMAND.command_class()
)
def dependencies(
    json_output: bool = json_option(),
    schema: bool = PROJECT_DEPENDENCIES_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Map each scene/resource in the project to the resources it references."""
    _dispatch(
        PROJECT_DEPENDENCIES_COMMAND,
        ProjectDependenciesParams(),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@export_app.command(name="list", cls=EXPORT_LIST_COMMAND.command_class())
def list_presets(
    json_output: bool = json_option(),
    schema: bool = EXPORT_LIST_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Enumerate the resolved project's export presets (name, platform, runnable)."""
    _dispatch(
        EXPORT_LIST_COMMAND,
        ExportListParams(),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@project_app.command(
    name="find-unused-resources",
    cls=PROJECT_FIND_UNUSED_RESOURCES_COMMAND.command_class(),
)
def find_unused_resources(
    json_output: bool = json_option(),
    schema: bool = PROJECT_FIND_UNUSED_RESOURCES_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Find resource files that nothing references (built on the reference graph)."""
    _dispatch(
        PROJECT_FIND_UNUSED_RESOURCES_COMMAND,
        ProjectFindUnusedResourcesParams(),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@export_app.command(name="get", cls=EXPORT_GET_COMMAND.command_class())
def get_preset(
    preset: str = typer.Option(
        ...,
        "--preset",
        help="The export preset's display name, as 'gda export list' reports it.",
    ),
    json_output: bool = json_option(),
    schema: bool = EXPORT_GET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Report one preset's details plus export-template install status."""
    _dispatch(
        EXPORT_GET_COMMAND,
        ExportGetParams(preset=preset),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@export_app.command(name="run", cls=EXPORT_RUN_COMMAND.command_class())
def run_export(
    preset: str = typer.Option(
        ...,
        "--preset",
        help="The export preset's display name, as 'gda export list' reports it.",
    ),
    # --mode (#170): select the export flavor. A closed Enum so an unrecognized
    # value is a Typer usage error (exit 2) rather than reaching the runner;
    # release is the default, preserving #121's behavior when --mode is omitted.
    mode: ExportRunMode = typer.Option(
        ExportRunMode.RELEASE,
        "--mode",
        help="The export flavor to run (release/debug/pack); default release.",
    ),
    # --output (#170): override the preset's configured export_path. A filesystem
    # path normalized ONCE at the CLI layer (ADR-0006: ~ expanded), like every
    # other path-taking command.
    output: Optional[str] = typer.Option(
        None,
        "--output",
        help="Override the preset's configured export_path; write the artifact here instead.",
    ),
    json_output: bool = json_option(),
    schema: bool = EXPORT_RUN_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Export a named preset to a destination and report the artifact.

    Unlike every other command, the export itself is a native ``--export-<mode>``
    invocation (the export subsystem is editor-only, so it cannot run through
    operations.gd). The command orchestrates three phases by hand: ``export get``
    resolves the preset's platform + configured ``export_path`` + template
    readiness (reusing #114's clean preset/project errors), a structured preflight
    fails fast when templates are missing or there is no destination, then the
    native ``ExportRunner`` performs the export and ``classify_export_run``
    synthesizes the typed result from the subprocess's exit code.

    ``--mode`` selects the export flavor (release/debug/pack; default release) and
    ``--output`` overrides the preset's configured ``export_path``; both are
    reflected in the native invocation and the reported result (#170).
    """
    resolved_project = resolve_project_dir(project)
    binary = resolve_godot_binary(godot)
    # --output is a filesystem path: normalize it ONCE here (ADR-0006, ~-expanded)
    # so the runner and the reported result both see the effective destination.
    override_output = _normalize_path(output) if output is not None else None

    # Phase 1: resolve the preset via the existing export-get sentinel op. This
    # reuses #114's clean structured errors — an unknown preset is
    # export_preset_not_found, a project with no export_presets.cfg is
    # export_presets_not_found — and emits + exits on any of them via the shared
    # failure channel, before any native export is attempted.
    got = EXPORT_GET_COMMAND.run(
        ExportGetParams(preset=preset),
        godot=godot,
        project=resolved_project,
        make_runner=_make_runner,
    )

    # Resolve the effective destination: --output (already CLI-normalized) wins
    # over the preset's configured export_path (#170). This is what the native
    # export writes to AND what the result reports as output_path.
    output_path = override_output if override_output is not None else got.export_path

    # Phase 2: structured preflight, BEFORE any native run (ADR-0010). Two
    # fail-fast checks, both decided from export get's structured fields rather
    # than from the engine's stderr (which ADR-0002 forbids parsing for codes):
    #
    #  - There must be a destination. --output supplies one directly (#170); only
    #    when no override is given AND the configured export_path is empty is there
    #    nowhere to write — export_path_unset. Checked first because it is a
    #    config/argument error independent of the engine's template state, so it
    #    stays deterministic whether or not templates happen to be installed.
    #  - Templates for the running engine version must be installed. export get
    #    reports that structurally (templates_installed) — the readiness check
    #    built for exactly this — so an export against an uninstalled template
    #    version is the distinct export_templates_missing, decided here rather
    #    than by string-matching the engine's "due to configuration errors"
    #    stderr (which also fires for a merely-misconfigured preset).
    if not output_path:
        emit_failure(export_path_unset_failure(got.name))
    if not got.templates_installed:
        emit_failure(export_templates_missing_failure(got.name, got.templates_version))

    # Phase 3: run the native export and classify its raw outcome. The export-get
    # resolved name (got.name) is authoritative throughout — it is what the engine
    # exports and what the result echoes — so the native invocation, not the raw
    # --preset string, is keyed on it.
    export_runner = _make_export_runner(binary, resolved_project)
    export_output = export_runner.run(got.name, mode.value, output_path)
    outcome = classify_export_run(
        export_output,
        binary,
        preset=got.name,
        platform=got.platform,
        mode=mode,
        output_path=output_path,
    )
    if isinstance(outcome, Failure):
        emit_failure(outcome)

    if json_output:
        typer.echo(outcome.model_dump_json())
    else:
        typer.echo(render(outcome))


@resource_app.command(name="uid", cls=RESOURCE_UID_COMMAND.command_class())
def resolve_uid(
    target: str = typer.Argument(
        ...,
        help=(
            "A 'uid://…' value to resolve to its res:// path, or a 'res://…' / "
            "filesystem path to resolve to its 'uid://…'. The direction is chosen "
            "by whether the target begins with 'uid://'."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_UID_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Resolve a resource UID to/from its res:// path via the engine's UID cache."""
    _dispatch(
        RESOURCE_UID_COMMAND,
        ResourceUidParams(target=_normalize_path(target)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@shader_app.command(name="set", cls=SHADER_SET_COMMAND.command_class())
def set_shader(
    path: str = typer.Argument(..., help="The .gdshader file to edit."),
    search: Optional[str] = typer.Option(
        None,
        "--search",
        help=(
            "search-replace mode: literal substring to find (not regex); all "
            "occurrences are replaced. Requires --replace."
        ),
    ),
    replace: Optional[str] = typer.Option(
        None,
        "--replace",
        help="search-replace mode: literal replacement text. Requires --search.",
    ),
    start_line: Optional[int] = typer.Option(
        None,
        "--start-line",
        help=(
            "line-range mode: first line to replace (1-based, inclusive). "
            "Requires --content."
        ),
    ),
    end_line: Optional[int] = typer.Option(
        None,
        "--end-line",
        help=(
            "line-range mode: last line to replace (1-based, inclusive); "
            "defaults to --start-line. Requires --content and --start-line."
        ),
    ),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help=(
            "Replacement text: the line span in line-range mode, or the whole "
            "file (full mode) when --start-line is omitted."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SHADER_SET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Edit a .gdshader via search-replace, line-range, or full overwrite."""
    # shader set reuses the script set edit-mode interface (issue #115): the same
    # mutual-exclusion resolver decides the single ScriptSetMode discriminator.
    mode = _resolve_set_mode(search, replace, start_line, end_line, content)
    _dispatch(
        SHADER_SET_COMMAND,
        ShaderSetParams(
            path=_normalize_path(path),
            mode=mode,
            search=search,
            replace=replace,
            start_line=start_line,
            end_line=end_line,
            content=content,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@project_app.command(name="set", cls=PROJECT_SET_COMMAND.command_class())
def project_set(
    setting: str = typer.Argument(
        ..., help="The project setting's full section/key name (e.g. application/config/name)."
    ),
    value: str = typer.Option(
        ...,
        "--value",
        help=(
            "The value to set, as a string. Coerced to the setting's declared "
            "Godot type; an uncoercible value is a clean error."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_SET_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Set a project setting, coercing the value to its declared Godot type, then save."""
    _dispatch(
        PROJECT_SET_COMMAND,
        ProjectSetParams(setting=setting, value=value),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@project_app.command(
    name="add-autoload", cls=PROJECT_ADD_AUTOLOAD_COMMAND.command_class()
)
def project_add_autoload(
    name: str = typer.Argument(
        ..., help="The autoload singleton's global name (the autoload/<name> key)."
    ),
    path: str = typer.Argument(
        ..., help="The res:// path to the script or scene to autoload (e.g. res://global.gd)."
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_ADD_AUTOLOAD_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Register an autoload singleton (name → script/scene path), then save project.godot."""
    _dispatch(
        PROJECT_ADD_AUTOLOAD_COMMAND,
        ProjectAddAutoloadParams(name=name, path=_normalize_path(path)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@project_app.command(
    name="remove-autoload", cls=PROJECT_REMOVE_AUTOLOAD_COMMAND.command_class()
)
def project_remove_autoload(
    name: str = typer.Argument(
        ..., help="The global name of the autoload singleton to unregister."
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_REMOVE_AUTOLOAD_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Unregister an autoload singleton by name, then save project.godot."""
    _dispatch(
        PROJECT_REMOVE_AUTOLOAD_COMMAND,
        ProjectRemoveAutoloadParams(name=name),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@theme_app.command(name="create", cls=THEME_CREATE_COMMAND.command_class())
def create_theme(
    path: str = typer.Argument(..., help="Target .tres Theme path to write."),
    json_output: bool = json_option(),
    schema: bool = THEME_CREATE_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new, loadable .tres Theme resource (no-clobber)."""
    _dispatch(
        THEME_CREATE_COMMAND,
        ThemeCreateParams(path=_normalize_path(path)),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@project_app.command(name="statistics", cls=PROJECT_STATISTICS_COMMAND.command_class())
def statistics(
    json_output: bool = json_option(),
    schema: bool = PROJECT_STATISTICS_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Report the project's file/line counts, autoloads and plugins."""
    _dispatch(
        PROJECT_STATISTICS_COMMAND,
        ProjectStatisticsParams(),
        json_output=json_output,
        godot=godot,
        project=project,
        render=render,
    )


@app.command(cls=INFO_COMMAND.command_class())
def info(
    json_output: bool = json_option(),
    schema: bool = INFO_COMMAND.schema_option(),
    godot: Optional[str] = godot_option(),
) -> None:
    """Report the Godot engine version info."""
    _dispatch_meta(
        INFO_COMMAND,
        InfoParams(),
        json_output=json_output,
        godot=godot,
        render=render,
    )
