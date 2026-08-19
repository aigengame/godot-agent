"""The ``scene`` command group: Godot scene files (.tscn) as the domain object.

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderers, its ``HeadlessCommand`` descriptors
(ADR-0023), and its Typer command bodies, and mounts them on the root app
through :func:`register`. It imports the shared machinery downward — the
dispatch tail (``gda.dispatch``), the descriptor machinery (``gda.headless``),
the cross-command contract core (``gda.models``) and the shared render helpers
(``gda.render``) — and is imported by nothing but the composition root
(``gda.cli``) and its one sanctioned sibling, ``gda.commands.node`` (which
reuses ``SceneNode`` / ``derive_scene_root_name``, ADR-0040 §5).
"""

from enum import Enum
from pathlib import Path
from typing import Any, Optional

import typer
from pydantic import BaseModel, Field, model_validator

from gda import dispatch
from gda.dispatch import dispatch_domain, dispatch_recipe
from gda.errors import Failure
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.models import (
    CREATED_DIRS_DESC,
    NormalizedPath,
    projected_value_schema_extra,
    VALUE_PROJECTION_DESC,
)
from gda.render import format_value, render_node_tree


def derive_scene_root_name(path: str) -> str:
    """Derive the default scene root name from the target file name."""
    filename = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if "." in filename:
        return filename.rsplit(".", 1)[0]
    return filename


class SceneCreateParams(BaseModel):
    """The operation params of ``gda scene create`` (issue #18).

    ``path`` is the target ``.tscn`` file; ``root_type`` the Godot node class
    of the new scene's root (e.g. ``Node2D``). ``root_name`` is explicit so the
    operation never silently derives a name Godot later sanitizes; when omitted,
    it is derived from the target filename without the final extension. Path
    normalization and that derivation live in the model (ADR-0015), so the argv
    and ``--params-json`` paths produce identical params.
    """

    path: NormalizedPath = Field(description="Target .tscn path to write.")
    root_type: str = Field(
        description="Godot node class of the new scene's root (e.g. Node2D)."
    )
    root_name: str | None = Field(
        default=None,
        description=(
            "Root node name to write. If omitted, it is derived from the target "
            "filename without its final extension. Must be non-empty and must not "
            "contain '.', ':', '@', '/', '\"', or '%'."
        ),
    )

    @model_validator(mode="after")
    def _default_root_name(self) -> "SceneCreateParams":
        if self.root_name is None:
            self.root_name = derive_scene_root_name(self.path)
        return self


class SceneCreateResult(BaseModel):
    """The result of ``gda scene create``: what was written where.

    Echoes the saved path and the root node the operation actually created, so
    an agent can assert the effect without a second call. ``created_dirs`` lists
    parent directories the operation created before saving, from outermost to
    innermost.
    """

    path: str
    root_name: str
    root_type: str
    created_dirs: list[str] = Field(description=CREATED_DIRS_DESC)


class SceneInstanceStatus(str, Enum):
    """Whether a statically-read instanced scene reference resolved."""

    RESOLVED = "resolved"
    MISSING = "missing"


class SceneNode(BaseModel):
    """One node of a scene's structured tree: name, type, instance marker, children.

    Recursive on purpose — the tree IS the contract: ``gda scene get`` reports
    arbitrarily nested scenes through this one shape.
    """

    name: str
    type: str = Field(
        description=(
            "Godot node class. For an instanced scene node, this is the "
            "instanced scene's root class when it can be resolved statically."
        )
    )
    instance_path: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "The referenced PackedScene path when this node is an instanced "
            "scene; null for a plain typed node."
        ),
    )
    instance_status: SceneInstanceStatus | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Whether the instanced scene reference resolved. Null for a plain "
            "typed node; 'missing' means instance_path is visible but could not "
            "be loaded as a PackedScene."
        ),
    )
    children: list["SceneNode"] = []


class SceneGetParams(BaseModel):
    """The operation params of ``gda scene get``: the ``.tscn`` file to read."""

    path: NormalizedPath = Field(description="The .tscn scene file to read.")


class SceneGetResult(BaseModel):
    """The result of ``gda scene get``: the scene file's structured node tree."""

    path: str
    root: SceneNode


class SceneExport(BaseModel):
    """One ``@export`` property a node's attached script declares (issue #58).

    ``type`` is the property's declared Godot type name (``float``, ``String``,
    ``Vector2``, …), the same spelling :class:`NodeProperty` uses. ``hint`` is the
    Godot ``PropertyHint`` enum value the ``@export`` annotation produced (e.g. a
    ``@export_range`` yields ``PROPERTY_HINT_RANGE``); ``hint_string`` is its
    companion string (the range bounds, the enum members, the file filter, …) —
    together they capture HOW the export is meant to be edited. ``value`` is the
    property's current value in the same recursive JSON value projection
    ``node get`` reports (ADR-0035), which on a freshly-instantiated node is
    the export's default.
    """

    name: str
    type: str = Field(
        description="The export's declared Godot type name (e.g. float, String, Vector2)."
    )
    hint: int = Field(
        description=(
            "The Godot PropertyHint enum value the @export annotation produced "
            "(0 = PROPERTY_HINT_NONE)."
        )
    )
    hint_string: str = Field(
        description="The PropertyHint's companion string (range bounds, enum members, …); empty when none."
    )
    value: Any = Field(
        description=(
            "The export's current value as JSON (its default on a freshly-loaded "
            "node). " + VALUE_PROJECTION_DESC
        ),
        json_schema_extra=projected_value_schema_extra,
    )


class ExportingNode(BaseModel):
    """One node of ``gda scene get-exports``: the exports its script declares (issue #58).

    A node appears only when its attached script declares at least one ``@export``
    property. ``path`` is the node's node path relative to the scene root ('.' for
    the root), the same addressing ``node get`` uses, so an agent can read or set
    any export with ``node get``/``node set``. ``script`` is the attached script's
    ``res://`` path, naming where the exports came from. ``exports`` lists them in
    declaration order.
    """

    path: str = Field(
        description=(
            "The node's node path relative to the scene root: '.' for the root "
            "itself, 'Player/Arm' for a nested node."
        )
    )
    name: str
    type: str = Field(description="The node's engine class (e.g. Node2D).")
    script: str | None = Field(
        default=None,
        description=(
            "The res:// path of the script that declares these exports, or null "
            "when the attached script has no resource path (an embedded script)."
        ),
    )
    exports: list[SceneExport]


class SceneGetExportsParams(BaseModel):
    """The operation params of ``gda scene get-exports``: the ``.tscn`` file to read (issue #58)."""

    path: NormalizedPath = Field(description="The .tscn scene file to read.")


class SceneGetExportsResult(BaseModel):
    """The result of ``gda scene get-exports``: each node's declared ``@export``s (issue #58).

    Echoes the scene ``path`` and, per node that declares them, the ``@export``
    properties its attached script exposes — name, type, hint/hint_string, and
    current value — as typed JSON. Reuses ``node get``'s property-value
    projection, so an export's ``value`` reads exactly as ``node get`` would
    report it. Nodes without an export-declaring script are omitted; a scene with
    no exported variables anywhere is a valid, empty listing (``nodes == []``).
    """

    path: str
    nodes: list[ExportingNode]


class SceneListParams(BaseModel):
    """The operation params of ``gda scene list`` — none (ADR-0004).

    ``scene list`` enumerates the ``.tscn`` scenes in the resolved project's
    ``res://`` tree; the project is process context (``--project``), not an
    operation param (ADR-0006), so the ``input`` schema is trivially empty.
    """


class ListedScene(BaseModel):
    """One enumerated scene of ``gda scene list``: its path and root summary.

    ``path`` is the scene's ``res://`` path — the address an agent feeds back
    into other scene commands. ``root_name``/``root_type`` are read cheaply from
    the scene's stored state (no instantiation, issue #30); both are null when
    the ``.tscn`` could not be loaded as a scene, so the entry still names a file
    the listing found rather than dropping it.
    """

    path: str
    root_name: str | None = Field(
        default=None,
        description="The scene root node's name, or null if the file could not be loaded as a scene.",
    )
    root_type: str | None = Field(
        default=None,
        description=(
            "The scene root node's type, resolving an inherited/instanced root "
            "to the referenced scene's root type when possible; null if the "
            "file could not be loaded as a scene."
        ),
    )
    root_instance_path: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "The referenced PackedScene path when the scene root inherits or "
            "instances another scene; null for a plain typed root or an "
            "unloadable scene."
        ),
    )
    root_instance_status: SceneInstanceStatus | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Whether the root instance reference resolved. Null for a plain "
            "typed root or an unloadable scene; 'missing' means "
            "root_instance_path is visible but could not be loaded as a "
            "PackedScene."
        ),
    )


class SceneListResult(BaseModel):
    """The result of ``gda scene list``: the project's enumerated ``.tscn`` scenes.

    An empty project is a valid, empty listing — ``scenes == []`` — not a
    failure.
    """

    scenes: list[ListedScene]


class SceneProblemKind(str, Enum):
    """What ``gda scene validate`` found wrong with one of a scene's dependencies (#664).

    A closed, public enum projected into ``--schema``, so an agent branches on the
    kind instead of matching the message prose. The three values are kept apart
    because the REMEDY differs: a missing file has to be restored or the reference
    fixed, an unloadable asset has to be imported, and a broken script has to be
    edited.
    """

    #: The referenced ``res://`` file does not exist.
    MISSING_RESOURCE = "missing_resource"
    #: The file is on disk, but no ``ResourceLoader`` can open it — typically an
    #: asset that was never imported, which a non-editor engine cannot load at all
    #: (so the running game would lose it exactly as the scene does here).
    UNLOADABLE_RESOURCE = "unloadable_resource"
    #: A referenced ``.gd`` script exists and loads, but does not compile — the same
    #: verdict ``gda script validate`` reports for it, reached from the scene side.
    SCRIPT_COMPILE_FAILED = "script_compile_failed"


class SceneProblem(BaseModel):
    """One dependency of a scene that did not resolve (#664).

    Dependency-centric, one entry per referenced file rather than per reference: a
    path the scene declares twice is one broken file, and both referencing nodes
    appear under ``nodes``.
    """

    kind: SceneProblemKind
    path: str = Field(
        description=(
            "The res:// path of the dependency, as the scene's [ext_resource] "
            "declares it (a relative reference resolved against the scene's own "
            "directory)."
        )
    )
    type: str | None = Field(
        default=None,
        description=(
            "The class the scene DECLARED for this reference (e.g. 'Script', "
            "'Texture2D', 'PackedScene'), or null when the declaration names none. "
            "It says what was expected at the path, which a missing file cannot."
        ),
    )
    nodes: list[str] = Field(
        default_factory=list,
        description=(
            "The node paths, relative to the scene root ('.' for the root), whose "
            "properties reference this dependency — the same addressing 'node get' "
            "takes. Empty when only a sub-resource (not a node) references it."
        ),
    )
    message: str = Field(
        description="What gda found, in one line; advisory prose, never a stable code."
    )


class SceneValidateParams(BaseModel):
    """The operation params of ``gda scene validate``: the ``.tscn`` file to check (#664)."""

    path: NormalizedPath = Field(description="The .tscn scene file to validate.")


class SceneValidateResult(BaseModel):
    """The result of ``gda scene validate``: the scene's static validity verdict (#664).

    Validating an INVALID scene is a SUCCESSFUL operation — the command exits 0 and
    reports ``valid=false`` with the problems, exactly as ``script validate`` does
    for a script that does not compile. Read the verdict from this field, never from
    the process status; the process only fails for an addressing error (a missing
    file, a file that does not load as a scene at all), which refuses the whole call
    rather than becoming a verdict.

    The verdict is STATIC: the scene is loaded but never instantiated, so validating
    it runs no project code (the read boundary of issue #30). It therefore cannot
    speak for what happens once the scene runs — that is ``gda scene preflight``.
    """

    path: str
    valid: bool = Field(
        description=(
            "True when every dependency the scene declares resolves and every "
            "attached script compiles. False when any does not — the command still "
            "exits 0, so read this field, not the exit code."
        )
    )
    problems: list[SceneProblem] = Field(
        description=(
            "One entry per unresolved dependency, in the order the scene file "
            "declares them; empty when the scene is valid."
        )
    )
    project_root: str | None = Field(
        description=(
            "The Godot project the scene's res:// dependencies were resolved "
            "against, as an absolute path (ADR-0006: --project, then $GDA_PROJECT, "
            "then the current directory). Always present; null when gda ran "
            "projectless. Read it before trusting an invalid verdict: a scene "
            "checked against the wrong root reports every dependency as missing "
            "(the #658 lesson, which applies here for the same reason — every "
            "problem below is a res:// resolution outcome)."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _supply_absent_project_root(cls, data: Any) -> Any:
        """Fill the key the ENGINE never sends, so the field can stay required.

        ``project_root`` is gda's own addition: ADR-0006 keeps project resolution
        CLI-side, so the ADR-0002 sentinel this model is parsed from carries only the
        fields ``operations.gd`` reports. Declaring the field required — so it
        appears in the published ``required`` list every consumer reads — would make
        that internal parse fail, so the absent key is supplied as ``null`` here and
        the recipe stamps the resolved project immediately after. The same shape
        :class:`~gda.commands.script.ScriptValidateResult` uses, for the same reason.
        """
        if isinstance(data, dict) and "project_root" not in data:
            return {**data, "project_root": None}
        return data


class SceneDeleteParams(BaseModel):
    """The operation params of ``gda scene delete``: the ``.tscn`` file to remove."""

    path: NormalizedPath = Field(description="The .tscn scene file to delete.")


class SceneDeleteResult(BaseModel):
    """The result of ``gda scene delete``: what was removed.

    Echoes the deleted scene's path and its root node's name/type (read from the
    scene's stored state before deletion), so the result names the content
    removed, not just the file path.
    """

    path: str
    root_name: str
    root_type: str


def render_scene_metadata(scene: "SceneCreateResult") -> str:
    """Render a created scene as ``created <path> (root <type>)``."""
    return f"created {scene.path} (root {scene.root_type})"


def render_scene_tree(scene: "SceneGetResult") -> str:
    """Render a read scene's node tree."""
    return render_node_tree(scene.root)


def render_scene_exports(scene: "SceneGetExportsResult") -> str:
    """Render a scene's per-node @export properties for humans.

    One ``path (Type)`` header per node that declares exports, then a
    ``name (Type) = value`` line per export — reusing :func:`format_value` for
    the value, the same projection ``node get`` renders. An empty listing (no
    exported variables anywhere) reads as ``(no exports)``.
    """
    if not scene.nodes:
        return "(no exports)"
    lines = []
    for node in scene.nodes:
        lines.append(f"{node.path} ({node.type})")
        for export in node.exports:
            lines.append(
                f"  {export.name} ({export.type}) = {format_value(export.value)}"
            )
    return "\n".join(lines)


def render_scene_list(listed: "SceneListResult") -> str:
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


def render_scene_delete(removed: "SceneDeleteResult") -> str:
    """Render a deleted scene as ``deleted <path> (root <name>: <type>)``."""
    return f"deleted {removed.path} (root {removed.root_name}: {removed.root_type})"


def render_scene_validate(validated: "SceneValidateResult") -> str:
    """Render a scene's validity verdict: the answer, then its evidence (#664).

    Conclusion first — one line an agent or a human reads without scanning. An
    INVALID verdict then leads with the project the dependencies were resolved
    against, before the problems rather than after them: when the root is the wrong
    one, every problem below it is an artefact of that single mistake and the reader
    needs the cause before the cascade (the shape ``script validate`` uses, #658).
    """
    if validated.valid:
        return f"valid {validated.path}"
    total = len(validated.problems)
    noun = "problem" if total == 1 else "problems"
    lines = [
        f"invalid {validated.path} ({total} {noun})",
        f"  project: {validated.project_root or '(none resolved: projectless)'}",
    ]
    for problem in validated.problems:
        declared = f" ({problem.type})" if problem.type is not None else ""
        lines.append(f"  {problem.kind.value}: {problem.path}{declared}")
        lines.append(f"    {problem.message}")
        if problem.nodes:
            lines.append(f"    nodes: {', '.join(problem.nodes)}")
    return "\n".join(lines)


SCENE_CREATE_COMMAND: HeadlessCommand[SceneCreateResult] = HeadlessCommand(
    operation="scene-create",
    input_model=SceneCreateParams,
    output_model=SceneCreateResult,
    render=render_scene_metadata,
)

SCENE_GET_COMMAND: HeadlessCommand[SceneGetResult] = HeadlessCommand(
    operation="scene-get",
    input_model=SceneGetParams,
    output_model=SceneGetResult,
    render=render_scene_tree,
)

SCENE_GET_EXPORTS_COMMAND: HeadlessCommand[SceneGetExportsResult] = HeadlessCommand(
    operation="scene-get-exports",
    input_model=SceneGetExportsParams,
    output_model=SceneGetExportsResult,
    render=render_scene_exports,
)

SCENE_LIST_COMMAND: HeadlessCommand[SceneListResult] = HeadlessCommand(
    operation="scene-list",
    input_model=SceneListParams,
    output_model=SceneListResult,
    render=render_scene_list,
)

SCENE_DELETE_COMMAND: HeadlessCommand[SceneDeleteResult] = HeadlessCommand(
    operation="scene-delete",
    input_model=SceneDeleteParams,
    output_model=SceneDeleteResult,
    render=render_scene_delete,
)


def _scene_validate_recipe(
    params: SceneValidateParams,
    *,
    project: Optional[Path],
    godot: Optional[str],
) -> "SceneValidateResult | Failure":
    """Check → report the root: ``scene validate``'s recipe (#664).

    The sentinel op still does the checking (``cmd.execute``); this wraps it in the
    one decision only the CLI can make, because ADR-0006 keeps project resolution
    CLI-side and the engine is TOLD the project through ``--path``, never asked
    about it: the resolved root is stamped onto the verdict as ``project_root``, so
    a caller reading ``valid=false`` sees which root the ``res://`` dependencies
    resolved against instead of inferring it (#658's rule, which lands here for the
    same reason — every problem this command reports is a res:// resolution
    outcome). The root is reported RESOLVED: ``--project game`` in a result tells
    the reader nothing about which directory was meant.

    ``project`` arrives ALREADY resolved from ``dispatch_recipe`` (an invalid
    ``--project``/``$GDA_PROJECT`` became a structured ``project_not_found`` before
    this runs, #353); ``None`` means projectless, which is a legitimate context here
    (a self-contained scene addressed by filesystem path), not a refusal.
    """
    root = project.expanduser().resolve() if project is not None else None
    # The runner seam is read off the module at call time — never imported by name —
    # so a test monkeypatch on ``gda.dispatch.make_runner`` still binds. Naming the
    # HEADLESS factory directly is correct only while this command is HEADLESS (the
    # same pairing note as ``script validate``'s recipe).
    outcome = SCENE_VALIDATE_COMMAND.execute(
        params,
        godot=godot,
        project=project,
        make_runner=dispatch.make_runner,
    )
    if isinstance(outcome, Failure):
        return outcome
    # A copy, not an in-place set: the classified result is the engine's answer, and
    # ``project_root`` is gda's addition to it.
    return outcome.model_copy(
        update={"project_root": str(root) if root is not None else None}
    )


# ``scene validate`` stays a HEADLESS sentinel op — the engine resolves the
# dependencies — but carries a ``recipe`` (ADR-0023) because one part of its
# contract is decided at the CLI, where ADR-0006's resolved project lives: the
# ``project_root`` on the result. The recipe channel is the ONE descriptor-driven
# hook both input paths share, so argv and ``--params-json`` get the same behaviour
# (ADR-0015) without the shared dispatch tail learning anything about this command.
SCENE_VALIDATE_COMMAND: HeadlessCommand[SceneValidateResult] = HeadlessCommand(
    operation="scene-validate",
    input_model=SceneValidateParams,
    output_model=SceneValidateResult,
    render=render_scene_validate,
    recipe=_scene_validate_recipe,
)

# The first domain command group (ADR-0005): commands acting on scene files.
_app = typer.Typer(help="Act on Godot scene files (.tscn).", no_args_is_help=True)


@_app.command(cls=SCENE_CREATE_COMMAND.command_class())
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
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .tscn scene file with the given root node type.

    A Control-derived root is created with zero anchors and zero offsets,
    so it does not fill the viewport. A root class with no intrinsic
    minimum size (plain Control, Panel, an empty container) renders as a
    zero-size rect at the origin; a class with an intrinsic minimum (e.g.
    Button, Label) renders at that minimum instead, still not the
    viewport. Container minimum sizes can keep descendants visible and
    mask this. Fill the viewport by setting the root's anchor_right and
    anchor_bottom to 1 with 'gda node set' (offsets stay 0); confirm with
    'gda game rect', which reports the root's rendered rect at runtime.
    """
    # Normalization + root-name derivation live in SceneCreateParams (ADR-0015),
    # so this body is a thin argv→model adapter and the --params-json path agrees.
    dispatch_domain(
        SCENE_CREATE_COMMAND,
        SceneCreateParams(path=path, root_type=root_type, root_name=root_name),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(cls=SCENE_GET_COMMAND.command_class())
def get(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = json_option(),
    schema: bool = SCENE_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a scene file and report its structured node tree."""
    dispatch_domain(
        SCENE_GET_COMMAND,
        SceneGetParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="get-exports", cls=SCENE_GET_EXPORTS_COMMAND.command_class())
def get_exports(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = json_option(),
    schema: bool = SCENE_GET_EXPORTS_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """List the @export properties a scene's nodes' scripts declare, per node path."""
    dispatch_domain(
        SCENE_GET_EXPORTS_COMMAND,
        SceneGetExportsParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="list", cls=SCENE_LIST_COMMAND.command_class())
def list_scenes(
    json_output: bool = json_option(),
    schema: bool = SCENE_LIST_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Enumerate the .tscn scenes in the resolved project."""
    dispatch_domain(
        SCENE_LIST_COMMAND,
        SceneListParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="validate", cls=SCENE_VALIDATE_COMMAND.command_class())
def validate_scene(
    path: str = typer.Argument(..., help="The .tscn scene file to validate."),
    json_output: bool = json_option(),
    schema: bool = SCENE_VALIDATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Check a scene's dependencies and scripts statically; invalid exits 0 with valid=false.

    Answers what 'scene get' cannot: loading a scene SUCCEEDS whatever is broken
    inside it — the engine substitutes null for a reference it could not resolve and
    still hands back a usable tree — so a scene whose script and texture are both
    gone reads as perfectly healthy. This command resolves every dependency the
    scene declares and compiles every '.gd' it attaches, and reports one problem per
    file that did not resolve: 'missing_resource' (the file is gone),
    'unloadable_resource' (it is there but no loader can open it — typically an
    asset that was never imported) or 'script_compile_failed' (run 'gda script
    validate' on it for the line and message). Each problem names the declared type
    and the node paths that reference it.

    STATIC: the scene is loaded but never instantiated, so no project code runs
    (issue #30). It therefore says nothing about what happens once the scene RUNS —
    a scene can pass this and still fail on its first frame; 'gda scene preflight'
    is the command that boots it.

    An invalid scene is a SUCCESSFUL operation: exit 0 with 'valid': false. Only an
    addressing error fails — a missing file is 'path_not_found' and a file that does
    not load as a scene at all is 'not_a_scene', the same ladder the rest of the
    scene group uses. The result carries 'project_root', the root the res://
    dependencies resolved against; read it before trusting an invalid verdict,
    because the wrong project reports every dependency as missing.
    """
    dispatch_recipe(
        SCENE_VALIDATE_COMMAND,
        SceneValidateParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(cls=SCENE_DELETE_COMMAND.command_class())
def delete(
    path: str = typer.Argument(..., help="The .tscn scene file to delete."),
    json_output: bool = json_option(),
    schema: bool = SCENE_DELETE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Delete a scene file and report what was removed."""
    dispatch_domain(
        SCENE_DELETE_COMMAND,
        SceneDeleteParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``scene`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="scene")
