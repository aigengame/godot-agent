"""The ``resource`` command group: Godot resource files (.tres) as the domain object.

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderers, its ``HeadlessCommand`` descriptors
(ADR-0023), and its Typer command bodies, and mounts them on the root app
through :func:`register`. It imports the shared machinery downward — the
dispatch tail (``gda.dispatch``), the descriptor machinery (``gda.headless``),
the cross-command contract core (``gda.models``, for the shared
:class:`~gda.models.NodeProperty` shape) and the shared render helpers
(``gda.render``). The composition root (``gda.cli``) mounts the group;
the asset integration consumes its returning Godot operations (ADR-0042).

:class:`~gda.commands.project.ResourceReference` is NOT this group's model
despite its name: it is the ``project find-references`` result shape, so it
lives with its single consumer in the ``project`` group (ADR-0040 §5).
"""

import hashlib
import json
import math
import os
import re
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Any, Callable, Literal, Optional

import typer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from gda.binary import resolve_godot_binary
from gda.dispatch import dispatch_domain, dispatch_recipe, params_or_bad_parameter
from gda.errors import (
    captured_output_tail,
    classify_launch_or_crash,
    containment_refusal,
    Failure,
    make_failure,
    unresolvable_binary_failure,
)
from gda.execution import ExecutionKind
from gda.headless import (
    HeadlessCommand,
    RunnerFactory,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.model_content import ModelContent
from gda.package_runner import PackageRunnerFactory, make_package_runner
from gda.models import (
    CREATED_DIRS_DESC,
    EngineVersion,
    NodeProperty,
    NormalizedPath,
    OBJECT_SET_ECHO_DESC,
    projected_value_schema_extra,
)
from gda.project import (
    RES_PREFIX,
    canonical_res_path,
    is_engine_virtual_path,
    project_absolute,
    project_anchored,
)
from gda.render import render_property_lines, render_set_echo
from gda.runner import RunResult, launch


class ResourceCreateParams(BaseModel):
    """The operation params of ``gda resource create`` (issue #112).

    ``path`` is the target ``.tres`` resource file, addressed by its ``res://``
    or filesystem path (resource-file addressing — by file path). ``type`` is
    the Resource type to instantiate and save: a built-in Resource class (e.g.
    ``Gradient``, ``Curve``) OR a project-defined ``class_name`` (a GDScript
    ``class_name Foo extends Resource``), resolved the same way ``node add``
    resolves ``--type`` (issue #342) — mirroring ``scene create``'s ``root_type``
    check against ``Node``.
    """

    path: NormalizedPath = Field(description="Target .tres resource path to write.")
    type: str = Field(
        description=(
            "The Resource type to create: a built-in Resource class (e.g. "
            "Gradient, Curve) or a registered Resource class_name (a GDScript "
            "class_name Foo extends Resource)."
        )
    )


class ResourceCreateResult(BaseModel):
    """The result of ``gda resource create``: what was written where (issue #112).

    Echoes the saved ``path`` and the ``type`` of the resource it created, so an
    agent can assert the effect (path + type) without a second call.
    ``created_dirs`` lists parent directories the operation created before
    saving, from outermost to innermost (mirrors ``scene``/``script`` create).
    """

    path: str
    type: str = Field(description="The Godot resource class that was created.")
    created_dirs: list[str] = Field(description=CREATED_DIRS_DESC)


class ResourceGetParams(BaseModel):
    """The operation params of ``gda resource get``: the ``.tres`` to read (issue #112).

    ``path`` addresses the resource by its ``res://`` or filesystem path. Loading
    a ``.tres`` instantiates the resource (the same trust boundary every load
    carries, ADR-0009), but a plain resource file holds data, not a script that
    runs on load.
    """

    path: NormalizedPath = Field(description="The .tres resource file to read.")


class ResourceGetResult(BaseModel):
    """The result of ``gda resource get``: a resource's properties as typed JSON (issue #112).

    Echoes the ``path``, the resource's ``type`` (its engine class), and its
    storage properties — the ones that serialize into the ``.tres`` — each as a
    typed :class:`NodeProperty` (the same projection ``node get`` reports), so a
    ``resource create`` round-trips: ``create`` then ``get`` reports the
    resource it wrote.
    """

    path: str
    type: str = Field(description="The resource's engine class (e.g. Gradient).")
    properties: list[NodeProperty]


class ResourceLoadParams(BaseModel):
    """The internal engine-load observation request used by asset workflows (#908)."""

    path: NormalizedPath = Field(
        description="An imported project resource to load through Godot."
    )


ROOT_SCALE_MIN = 0.001
ROOT_SCALE_MAX = 1000.0


class ResourceImportOptionsParams(BaseModel):
    path: NormalizedPath = Field(
        description="An existing GLB source with a Godot .import sidecar."
    )


class ConfiguredImportOption(BaseModel):
    name: str
    value: Any
    value_type: str = Field(
        description="Observed Godot Variant type, not importer-declared metadata."
    )
    value_unavailable_reason: str | None


class SupportedImportUpdate(BaseModel):
    name: Literal["nodes/root_scale"] = "nodes/root_scale"
    value_type: Literal["float"] = "float"
    minimum: float = ROOT_SCALE_MIN
    maximum: float = ROOT_SCALE_MAX


class ResourceImportOptionsResult(BaseModel):
    path: str
    sidecar: str
    engine_version: EngineVersion
    importer: str
    resource_type: str
    configured_options: list[ConfiguredImportOption]
    configured_options_truncated: bool
    default_metadata_available: Literal[False] = False
    metadata_limitations: list[str] = Field(
        default_factory=lambda: [
            "The importer name is recorded in the sidecar, not proof of an active registered importer.",
            "Configured values are not an importer capability list or proof of explicit authorship.",
            "Importer defaults, declared types, hints and plugin capabilities are not exposed by this operation.",
            "Effective engine values require reimport/load verification; sidecar values alone do not prove adoption.",
            "At most 128 options are reported; complex values and strings above 4096 characters are omitted.",
        ]
    )
    supported_updates: list[SupportedImportUpdate] = Field(
        default_factory=lambda: [SupportedImportUpdate()],
        description="The gda built-in scene-importer update contract, not dynamically discovered plugin metadata.",
    )


def render_resource_import_options(result: ResourceImportOptionsResult) -> str:
    return (
        f"{result.path}: {result.importer} importer, "
        f"{len(result.configured_options)} configured options; "
        "importer defaults unavailable (use --json for values and limitations)"
    )


@contextmanager
def _import_config_project():
    """Use Godot's Variant parser without executing the target project."""
    with TemporaryDirectory(prefix="gda-import-options-") as directory:
        scratch = Path(directory)
        (scratch / "project.godot").write_text(
            'config_version=5\n[application]\nconfig/name="gda import options"\n'
        )
        yield scratch


def run_resource_import_options_operation(
    project: Path, params: ResourceImportOptionsParams, *, godot: str | None = None
) -> ResourceImportOptionsResult | Failure:
    """Read native ConfigFile values without starting the target project's code."""
    addressed = _asset_res_path(project, params.path)
    if isinstance(addressed, Failure):
        return addressed
    if Path(addressed).suffix.lower() != ".glb":
        return make_failure(
            "invalid_params", "import-options currently supports GLB sources only", ""
        )
    source = project_absolute(project) / addressed[len(RES_PREFIX) :]
    if not source.is_file():
        return make_failure("path_not_found", f"asset not found: {addressed}", "")
    # ConfigFile owns Variant parsing. An empty project prevents metadata reads
    # from running target autoloads or performing a target-project import scan.
    with _import_config_project() as scratch:
        result = RESOURCE_IMPORT_OPTIONS_COMMAND.execute(
            ResourceImportOptionsParams(path=str(source)), project=scratch, godot=godot
        )
    if isinstance(result, Failure):
        return result
    return result.model_copy(
        update={"path": addressed, "sidecar": addressed + ".import"}
    )


def _resource_import_options_recipe(params, *, project, godot):
    return run_resource_import_options_operation(project, params, godot=godot)


RESOURCE_IMPORT_OPTIONS_COMMAND: HeadlessCommand[ResourceImportOptionsResult] = (
    HeadlessCommand(
        operation="resource-import-options",
        input_model=ResourceImportOptionsParams,
        output_model=ResourceImportOptionsResult,
        render=render_resource_import_options,
        recipe=_resource_import_options_recipe,
    )
)


ModelVector3 = tuple[float, float, float]


class ModelTransform(BaseModel):
    """A transform with basis columns and origin in the declared coordinate space."""

    origin: ModelVector3
    basis: tuple[ModelVector3, ModelVector3, ModelVector3]


class ModelBounds(BaseModel):
    position: ModelVector3
    size: ModelVector3


class ModelResource(BaseModel):
    type: str
    name: str
    path: str | None
    unavailable_reason: str | None


class ModelTexture(BaseModel):
    role: str
    resource: ModelResource


class ModelMaterial(BaseModel):
    resource: ModelResource
    source: Literal["material_override", "surface_override", "mesh_surface"]
    textures: list[ModelTexture]
    textures_unavailable_reason: str | None


class ModelSurface(BaseModel):
    index: int
    primitive: str | None
    vertex_count: int | None
    index_count: int | None
    triangle_count: int | None
    triangle_count_basis: Literal["index_slots", "vertex_slots"] | None
    counts_unavailable_reason: str | None = Field(
        description="Why primitive and compact counts are unavailable; no vertex arrays are read."
    )
    material: ModelMaterial | None


class ModelBone(BaseModel):
    index: int
    name: str
    parent: int
    rest: ModelTransform = Field(
        description="Rest transform relative to the parent bone."
    )


class ModelSkeleton(BaseModel):
    bone_count: int
    bones: list[ModelBone]


class ModelSkinBind(BaseModel):
    index: int
    bone_index: int
    name: str
    pose: ModelTransform
    resolved_bone_index: int | None
    unresolved_reason: str | None


class ModelSkin(BaseModel):
    resource: ModelResource
    skeleton_path: str
    resolved_skeleton_path: str | None
    unresolved_reason: str | None
    bind_count: int
    binds: list[ModelSkinBind]


class ModelMesh(BaseModel):
    resource: ModelResource
    surface_count: int
    surfaces: list[ModelSurface]
    skin: ModelSkin | None
    skin_unavailable_reason: str | None


class ModelAnimationTrack(BaseModel):
    index: int
    type: str
    path: str
    enabled: bool
    target_node_path: str | None
    bone_name: str | None
    status: Literal["resolved", "unresolved", "unavailable"]
    resolution_scope: Literal["node", "bone", "declared_property"] | None = Field(
        description="Located static identity only, not successful playback or property writability."
    )
    reason: str | None


class ModelAnimation(BaseModel):
    name: str
    length: float
    loop_mode: int = Field(
        description="Godot Animation.LoopMode: 0 none, 1 linear, 2 ping-pong."
    )
    track_count: int
    tracks: list[ModelAnimationTrack]


class ModelAnimationPlayer(BaseModel):
    root_path: str
    resolved_root_path: str | None
    unresolved_reason: str | None
    animation_count: int
    animations: list[ModelAnimation]


class ModelNode(BaseModel):
    path: str = Field(
        description="Full node path relative to the loaded resource root."
    )
    type: str
    local_transform: ModelTransform | None
    resource_transform: ModelTransform | None
    mesh: ModelMesh | None
    skeleton: ModelSkeleton | None
    animation_player: ModelAnimationPlayer | None


class ModelOmission(BaseModel):
    node_path: str
    section: str
    reason: Literal["node_limit", "detail_limit"]


class ModelMeasurement(BaseModel):
    coordinate_space: Literal["resource"]
    geometry: Literal["static_mesh_aabb"]
    limitations: list[str]


class ModelSummary(BaseModel):
    node_count: int
    mesh_instance_count: int
    unique_mesh_count: int


class ResourceInspectModelParams(BaseModel):
    path: NormalizedPath = Field(
        description="An imported PackedScene resource to inspect."
    )
    subtree: str = Field(
        default=".",
        description="Selected root-inclusive subtree, relative to the resource root.",
    )
    max_nodes: int = Field(
        default=256,
        ge=1,
        le=4096,
        description="Maximum reported nodes; counts and bounds cover only those visited.",
    )
    max_items: int = Field(
        default=1024,
        ge=1,
        le=16384,
        description="Global limit for surface, texture, bone, bind, animation and track records.",
    )


class ResourceInspectModelResult(BaseModel):
    path: str
    subtree: str
    engine_version: EngineVersion
    measurement: ModelMeasurement
    nodes: list[ModelNode]
    summary: ModelSummary
    bounds: ModelBounds | None = Field(
        description="Merged static mesh bounds; null when the visited nodes have no mesh geometry."
    )
    truncated: bool = Field(
        description="True when node or detail records were omitted by a report limit."
    )
    omissions: list[ModelOmission]


class PackageResourcePresenceParams(BaseModel):
    paths: list[NormalizedPath] = Field(
        min_length=1,
        max_length=64,
        description="Exact res:// resource paths to test in the selected PCK.",
    )


class PackageResourcePresenceItem(BaseModel):
    path: str
    present: bool


class PackageResourcePresenceResult(BaseModel):
    engine_version: EngineVersion
    resources: list[PackageResourcePresenceItem]


class ResourceInspectModelContentParams(BaseModel):
    path: NormalizedPath = Field(description="An imported GLB model resource.")
    max_nodes: int = Field(
        default=256, ge=1, le=1024, description="Maximum nodes to sample."
    )
    max_vertices: int = Field(
        default=200000,
        ge=1,
        le=1000000,
        description="Maximum ArrayMesh vertices to sample.",
    )


class ResourceInspectModelContentResult(BaseModel):
    path: str
    content: ModelContent


def render_resource_inspect_model(result: ResourceInspectModelResult) -> str:
    summary = result.summary
    text = (
        f"{result.path} [{result.subtree}]: {summary.node_count} nodes, "
        f"{summary.mesh_instance_count} mesh instances, "
        f"{summary.unique_mesh_count} unique meshes"
    )
    if result.truncated:
        text += " (partial report)"
    return text


RESOURCE_INSPECT_MODEL_COMMAND: HeadlessCommand[ResourceInspectModelResult] = (
    HeadlessCommand(
        operation="resource-inspect-model",
        input_model=ResourceInspectModelParams,
        output_model=ResourceInspectModelResult,
        render=render_resource_inspect_model,
    )
)


PACKAGE_RESOURCE_PRESENCE_COMMAND: HeadlessCommand[PackageResourcePresenceResult] = (
    HeadlessCommand(
        operation="package-resource-presence",
        input_model=PackageResourcePresenceParams,
        output_model=PackageResourcePresenceResult,
        render=lambda result: f"checked {len(result.resources)} package resources",
    )
)


def render_resource_inspect_model_content(
    result: ResourceInspectModelContentResult,
) -> str:
    digest = result.content.digest or "unavailable"
    return f"{result.path}: {result.content.nodes} nodes, digest {digest}"


RESOURCE_INSPECT_MODEL_CONTENT_COMMAND: HeadlessCommand[
    ResourceInspectModelContentResult
] = HeadlessCommand(
    operation="resource-inspect-model-content",
    input_model=ResourceInspectModelContentParams,
    output_model=ResourceInspectModelContentResult,
    render=render_resource_inspect_model_content,
)


class ResourceLoadResult(BaseModel):
    """A bounded observation of one resource loaded by the real engine (#908)."""

    path: str
    resource_type: str
    engine_version: EngineVersion
    texture_size: list[int] | None = Field(default=None, min_length=2, max_length=2)
    scene_node_count: int | None = Field(default=None, ge=1)


def _render_resource_load(outcome: "ResourceLoadResult") -> str:
    """Internal-only renderer required by the command descriptor contract."""
    return f"loaded {outcome.path} as {outcome.resource_type}"


RESOURCE_LOAD_COMMAND: HeadlessCommand[ResourceLoadResult] = HeadlessCommand(
    operation="resource-load",
    input_model=ResourceLoadParams,
    output_model=ResourceLoadResult,
    render=_render_resource_load,
)


def _execute_resource_load(
    params: ResourceLoadParams, *, godot: str | None, project: Path
) -> ResourceLoadResult | Failure:
    return RESOURCE_LOAD_COMMAND.execute(params, godot=godot, project=project)


class ResourceSetParams(BaseModel):
    """The operation params of ``gda resource set`` (issue #120).

    ``path`` is the ``.tres`` resource file to mutate, addressed by its ``res://``
    or filesystem path; ``property`` is the resource property to set; ``value`` is
    the CLI string value, coerced to the property's declared Godot type by the
    operation (the same coercion rules as ``node set`` / ``project set``, #55)
    before the ``.tres`` is re-saved. ``set`` edits an EXISTING property — an
    unknown property is a clean error, never a silent create — so the declared
    type to coerce to is always known (read off the resource's property list).
    Mirrors ``project set`` closely: load → coerce to the declared type → save →
    round-trip via ``resource get``.
    """

    path: NormalizedPath = Field(description="The .tres resource file to mutate.")
    property: str = Field(
        description="The resource property to set (e.g. interpolation_mode)."
    )
    value: str = Field(
        description=(
            "The value to set, as a string. The operation coerces it to the "
            "property's declared Godot type (see the command catalog's 'Property "
            "value coercion'). For Dictionary/Array JSON values, JSON integer "
            "literals stay int and JSON float literals stay float; typed "
            "containers assign entries through their declared container type. An "
            "uncoercible value is a clean error."
        )
    )


class ResourceSetResult(BaseModel):
    """The result of ``gda resource set``: the one property it set (issue #120).

    Echoes the ``path``, the ``property`` set, the declared ``type`` the CLI value
    was coerced to, and the coerced ``value`` as JSON — the same projection
    ``resource get`` reports for a storage property, so a ``set`` round-trips
    through a ``get`` without re-reading the ``.tres``.
    """

    path: str
    property: str
    type: str = Field(
        description="The property's declared Godot type the value was coerced to."
    )
    value: Any = Field(
        description=(
            "The coerced value as JSON, as the resource now holds it. "
            + OBJECT_SET_ECHO_DESC
        ),
        json_schema_extra=projected_value_schema_extra,
    )


class ResourceDeleteParams(BaseModel):
    """The operation params of ``gda resource delete``: the ``.tres`` file to remove (issue #120)."""

    path: NormalizedPath = Field(description="The .tres resource file to delete.")


class ResourceDeleteResult(BaseModel):
    """The result of ``gda resource delete``: what was removed (issue #120).

    Echoes the deleted resource's ``path`` and its ``type`` (the engine class,
    read from the resource before deletion), so the result names the content
    removed, not just the file path — mirroring ``scene``/``script delete``.
    """

    path: str
    type: str = Field(
        description="The deleted resource's engine class (e.g. Gradient)."
    )


class ResourceUidParams(BaseModel):
    """The operation params of ``gda resource uid`` (issue #113).

    Resolves a Godot resource UID to/from its resource path in BOTH directions
    against the engine's UID cache — read-only, it never mutates the cache or any
    file. ``target`` is the single addressing argument and selects the direction
    by its form:

    - a ``uid://…`` value: report the ``res://…`` path it resolves to.
    - a ``res://…`` (or filesystem) path: report its assigned ``uid://…``.

    The UID cache is the engine's own ``res://.godot/uid_cache.bin``, loaded at
    startup, so resolution needs project context (``--project``); a projectless
    run has no cache to query. This is distinct from ``.tres`` file CRUD: it
    queries the cache, not a file's contents.
    """

    target: NormalizedPath = Field(
        description=(
            "The resolution target: a 'uid://…' value to resolve to its res:// "
            "path, or a 'res://…' / filesystem path to resolve to its 'uid://…'. "
            "The direction is chosen by whether 'target' begins with 'uid://'."
        )
    )


class ResourceUidResult(BaseModel):
    """The result of ``gda resource uid``: the resolved UID↔path pair (issue #113).

    Both directions converge on the same shape — the resolved ``uid`` and the
    ``path`` it maps to — so an agent always gets both sides of the mapping
    regardless of which it queried. ``queried`` echoes which direction was
    resolved, so the result is self-describing: ``uid`` means the target was a
    ``uid://`` resolved to its path, ``path`` means the target was a path
    resolved to its UID.
    """

    queried: str = Field(
        description=(
            "Which direction was resolved: 'uid' when the target was a 'uid://' "
            "value (resolved to its path), 'path' when the target was a path "
            "(resolved to its UID)."
        )
    )
    uid: str = Field(description="The resource's 'uid://…' value.")
    path: str = Field(description="The resource's 'res://…' path the UID maps to.")


def render_resource_create(created: "ResourceCreateResult") -> str:
    """Render a created resource as ``created <path> (<type>)``."""
    return f"created {created.path} ({created.type})"


def render_resource_properties(got: "ResourceGetResult") -> str:
    """Render a resource's properties as ``name (Type) = value`` lines for humans.

    Mirrors :func:`render_node_properties`: a header naming the resource and its
    type, then one typed line per storage property — the same human surface a
    node's properties get, since both read the shared :class:`NodeProperty`.
    """
    return render_property_lines(got.path, got.type, got.properties)


def render_resource_set(was_set: "ResourceSetResult") -> str:
    """Render a set property as ``set <path>.<property> (<type>) = <value>``."""
    return render_set_echo(was_set.path, was_set.property, was_set.type, was_set.value)


def render_resource_delete(removed: "ResourceDeleteResult") -> str:
    """Render a deleted resource as ``deleted <path> (<type>)``."""
    return f"deleted {removed.path} ({removed.type})"


def render_resource_uid(resolved: "ResourceUidResult") -> str:
    """Render a resolved UID↔path mapping as ``<uid> -> <path>`` for humans."""
    return f"{resolved.uid} -> {resolved.path}"


RESOURCE_CREATE_COMMAND: HeadlessCommand[ResourceCreateResult] = HeadlessCommand(
    operation="resource-create",
    input_model=ResourceCreateParams,
    output_model=ResourceCreateResult,
    render=render_resource_create,
)

RESOURCE_GET_COMMAND: HeadlessCommand[ResourceGetResult] = HeadlessCommand(
    operation="resource-get",
    input_model=ResourceGetParams,
    output_model=ResourceGetResult,
    render=render_resource_properties,
)

RESOURCE_SET_COMMAND: HeadlessCommand[ResourceSetResult] = HeadlessCommand(
    operation="resource-set",
    input_model=ResourceSetParams,
    output_model=ResourceSetResult,
    render=render_resource_set,
)

RESOURCE_DELETE_COMMAND: HeadlessCommand[ResourceDeleteResult] = HeadlessCommand(
    operation="resource-delete",
    input_model=ResourceDeleteParams,
    output_model=ResourceDeleteResult,
    render=render_resource_delete,
)

RESOURCE_UID_COMMAND: HeadlessCommand[ResourceUidResult] = HeadlessCommand(
    operation="resource-uid",
    input_model=ResourceUidParams,
    output_model=ResourceUidResult,
    render=render_resource_uid,
)


# The resource command group (issue #112): commands acting on .tres resource
# files on disk (load/save plumbing), so they stay headless. The group is a
# .tres tracer; the binary .res form is out of scope for this slice.
_app = typer.Typer(help="Act on resource files (.tres).", no_args_is_help=True)


@_app.command(cls=RESOURCE_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .tres resource path to write."),
    resource_type: str = typer.Option(
        ...,
        "--type",
        help=(
            "Resource type of the new .tres: a built-in Resource class (e.g. "
            "Gradient, Curve) or a registered Resource class_name (a GDScript "
            "class_name Foo extends Resource)."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_CREATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .tres resource file of the given resource type."""
    dispatch_domain(
        RESOURCE_CREATE_COMMAND,
        ResourceCreateParams(path=path, type=resource_type),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="get", cls=RESOURCE_GET_COMMAND.command_class())
def get_resource(
    path: str = typer.Argument(..., help="The .tres resource file to read."),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a .tres resource and report its properties as typed JSON."""
    dispatch_domain(
        RESOURCE_GET_COMMAND,
        ResourceGetParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(
    name="import-options", cls=RESOURCE_IMPORT_OPTIONS_COMMAND.command_class()
)
def import_options(
    path: str = typer.Argument(
        ..., help="An existing GLB source with an import sidecar."
    ),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_IMPORT_OPTIONS_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read configured import values and the supported update scope without reimporting.

    A sidecar does not disclose explicit authorship, importer defaults or whether
    cached engine results adopted its values. Metadata limitations are explicit.
    """
    dispatch_recipe(
        RESOURCE_IMPORT_OPTIONS_COMMAND,
        ResourceImportOptionsParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="inspect-model", cls=RESOURCE_INSPECT_MODEL_COMMAND.command_class())
def inspect_model(
    path: str = typer.Argument(
        ..., help="An imported PackedScene resource to inspect."
    ),
    subtree: str = typer.Option(
        ".", help="Root-inclusive subtree relative to the resource root."
    ),
    max_nodes: int = typer.Option(256, min=1, max=4096, help="Maximum reported nodes."),
    max_items: int = typer.Option(
        1024, min=1, max=16384, help="Maximum detail records across the whole report."
    ),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_INSPECT_MODEL_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Inspect the selected Godot-loaded model without importing or running gameplay.

    Bounds cover static mesh AABBs in resource space, including the selected root.
    Loading and instantiation use the existing trusted-project execution surface.
    """
    dispatch_domain(
        RESOURCE_INSPECT_MODEL_COMMAND,
        ResourceInspectModelParams(
            path=path, subtree=subtree, max_nodes=max_nodes, max_items=max_items
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(
    name="inspect-model-content",
    cls=RESOURCE_INSPECT_MODEL_CONTENT_COMMAND.command_class(),
)
def inspect_model_content(
    path: str = typer.Option(..., "--path", help="Imported GLB model resource."),
    max_nodes: int = typer.Option(256, min=1, max=1024),
    max_vertices: int = typer.Option(200000, min=1, max=1000000),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_INSPECT_MODEL_CONTENT_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Digest bounded static content from an imported GLB through Godot."""
    dispatch_domain(
        RESOURCE_INSPECT_MODEL_CONTENT_COMMAND,
        ResourceInspectModelContentParams(
            path=path, max_nodes=max_nodes, max_vertices=max_vertices
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="set", cls=RESOURCE_SET_COMMAND.command_class())
def set_resource(
    path: str = typer.Argument(..., help="The .tres resource file to mutate."),
    property: str = typer.Option(
        ...,
        "--property",
        help="The resource property to set (e.g. interpolation_mode).",
    ),
    value: str = typer.Option(
        ...,
        "--value",
        help=(
            "The value to set, as a string. Coerced to the property's declared "
            "Godot type: Vector2/Vector2i/Color take comma-separated components "
            '(e.g. "48,72", "0.2,0.6,1,1"), and a property expecting a Resource '
            "(sub)class takes a res:// path to an existing Resource of that class. "
            "An uncoercible value is a clean error."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_SET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Set a .tres property, coercing the value to its declared Godot type, then save."""
    dispatch_domain(
        RESOURCE_SET_COMMAND,
        ResourceSetParams(path=path, property=property, value=value),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="delete", cls=RESOURCE_DELETE_COMMAND.command_class())
def delete_resource(
    path: str = typer.Argument(..., help="The .tres resource file to delete."),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_DELETE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Delete a .tres resource file and report what was removed."""
    dispatch_domain(
        RESOURCE_DELETE_COMMAND,
        ResourceDeleteParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="uid", cls=RESOURCE_UID_COMMAND.command_class())
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
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Resolve a resource UID to/from its res:// path via the engine's UID cache."""
    dispatch_domain(
        RESOURCE_UID_COMMAND,
        ResourceUidParams(target=target),
        json_output=json_output,
        godot=godot,
        project=project,
    )


# --- resource import (scoped import surface, #668) -----------------------------
#
# Clean-worktree resource loading (GDA-DF-010): a fresh checkout carries the
# sources and their committed `.import` sidecars but not the gitignored
# `.godot/` cache, so a one-shot run's `preload()` of a PNG dies with "no
# recognized resource loader" although the imported project loads it fine. The
# engine's ONE scriptable import primitive is the project-wide
# `godot --headless --import` pass (a per-file reimport exists only inside the
# editor process; `--script` requires a MainLoop, verified against the engine
# source) — so gda's scoping is in the DECISION and the REPORT, not the pass:
# it runs the pass only when a requested asset is missing or stale, and it
# reports everything the pass touched, each created file classified against the
# explicit cache root. Plain `script run` is untouched (#668's guarantee: gda
# adds no import pass). Per the issue's triage decisions the command lives
# under `resource` (no near-synonym `asset` group), and the importer-execution
# point joins CONTEXT.md's Project-code execution surface — within the Trusted
# project assumption (ADR-0009), no new trust axis.


class ResourceImportParams(BaseModel):
    """The params of ``gda resource import``: ensure assets are importable (#668).

    ``assets`` are the requested dependencies, as ``res://`` paths or filesystem
    paths inside the project (a relative filesystem path is read as
    project-relative; other engine-virtual schemes like ``user://`` are
    refused). gda reads each asset's EVIDENCE STATE the way the engine's own
    reimport test reads its artifacts — ``cached`` / ``missing`` / ``stale`` /
    ``invalid`` (see :class:`ResourceImportAsset`) — and runs the engine's
    project-wide import pass only when a request is ``missing`` or ``stale``
    (an ``invalid`` one takes the conservative no-pass path and settles
    ``failed``; see :class:`ResourceImportAsset`);
    ``dry_run`` reports the states and the decidable predictions without
    running anything or writing anything.
    """

    assets: list[NormalizedPath] = Field(
        min_length=1,
        description=(
            "The assets to ensure are imported (repeatable): res:// paths, or "
            "filesystem paths inside the project (relative means "
            "project-relative)."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description=(
            "Report the per-asset cache verdicts and the predicted mutation "
            "inventory without running the engine pass or writing anything."
        ),
    )
    timeout: float = Field(
        default=300.0,
        gt=0,
        description=(
            "Seconds to allow the engine import pass (it re-imports every "
            "missing or stale asset in the project, not only the requested "
            "ones)."
        ),
    )


AssetStatus = Literal[
    "cached", "missing", "stale", "invalid", "imported", "not_importable", "failed"
]


class ResourceImportAsset(BaseModel):
    """One requested asset's import verdict (#668).

    Before a pass (and on a dry run) the status is an EVIDENCE state, read
    from the same project artifacts the engine's reimport test reads (#738
    review): ``cached`` (every ARTIFACT-level check passes — the engine-state
    checks it cannot read are a declared remainder, see below), ``missing`` (no
    sidecar — a new asset the pass would import), ``stale`` (the sidecar is
    present but an engine check fails — a destination or `.md5` receipt
    absent, the recorded `source_md5`/`dest_md5` disagreeing with the bytes,
    `source_file` naming a different source, or the pre-UID format — the pass
    WOULD re-import it), or ``invalid`` (the engine marked the last import
    `valid=false`, or the sidecar does not parse, or the `.md5` receipt falls
    outside gda's documented engine-written assignment subset; the engine
    deliberately SKIPS parse errors and gda conservatively skips unsupported
    receipt syntax — delete the sidecar to retry, which heals a malformed
    receipt too, because the pass rewrites both). The receipt subset accepts
    quoted-string assignments, whitespace, ``;`` comments, JSON-style escapes
    (lone UTF-16 surrogates excluded — VariantParser rejects them), and
    repeated assignments; as in the engine, the final value wins. Broader
    Variant values take the conservative no-pass direction. A real run settles
    each non-cached state: ``imported``, ``not_importable`` (the pass decided the
    type needs no import — e.g. a script), or ``failed`` (still not cached
    after the pass; every ``invalid`` request settles here, because the pass
    does not retry it). The declared remainder: the checks the engine makes
    from its OWN state — importer availability and format version,
    import-settings validity, and the editor cache's expected sidecar MD5 —
    are not readable from the project's artifacts, so an asset the engine
    would still re-import (e.g. a sidecar whose recorded importer no longer
    exists) can read ``cached`` here until any pass runs; the next pass
    converges it, and none of these can make gda spend a pass the engine
    would not.
    """

    path: str = Field(description="The asset's res:// path.")
    status: AssetStatus = Field(
        description="The verdict for this asset (see the class docstring)."
    )
    sidecar: str | None = Field(
        default=None,
        description=(
            "The asset's source-adjacent .import sidecar (res:// path), null "
            "when the asset has none."
        ),
    )
    dest_files: list[str] = Field(
        default_factory=list,
        description=(
            "The cache files the sidecar declares (res://.godot/imported/…); "
            "empty when there is no sidecar or it declares none (importer=keep)."
        ),
    )
    declared_importer: str | None = Field(
        default=None,
        description=(
            "The importer name declared by the observed sidecar; null when "
            "unavailable. This does not prove that the importer is registered "
            "or active."
        ),
    )
    declared_source_file: str | None = Field(
        default=None,
        description=(
            "The source path declared by the observed sidecar; null when unavailable."
        ),
    )


class ImportCreatedFile(BaseModel):
    """One file the engine import pass created, classified (#668).

    ``classification`` is ``cache_owned`` for a file under the explicit cache
    root (the project's ``.godot/``) and ``source_adjacent`` for anything else
    the pass wrote beside the sources (an asset's ``.import`` sidecar, a
    script's ``.uid``) — the DF-038 noise an unattended admission must account
    for, file by file.
    """

    path: str = Field(description="The created file's res:// path.")
    classification: Literal["cache_owned", "source_adjacent"] = Field(
        description="cache_owned (under .godot/) or source_adjacent."
    )


class ResourceImportSummary(BaseModel):
    """The machine-readable completion summary of ``gda resource import`` (#668)."""

    requested: int = Field(description="Assets requested.")
    cached: int = Field(
        description=(
            "Assets the artifacts show the engine's pass would leave as is "
            "(subject to the declared engine-state remainder)."
        )
    )
    missing: int = Field(
        description="Assets with no sidecar yet (nonzero only on a dry run)."
    )
    stale: int = Field(
        description=(
            "Assets whose sidecar fails an engine check (nonzero only on a dry run)."
        )
    )
    invalid: int = Field(
        description=(
            "Assets whose last import the engine marked failed, whose sidecar "
            "does not parse, or whose .md5 receipt falls outside gda's "
            "documented engine-written assignment subset (nonzero only on a "
            "dry run; the pass does not retry these)."
        )
    )
    imported: int = Field(
        description="Assets with cached artifact evidence after the pass; not proof that requested options were adopted."
    )
    not_importable: int = Field(description="Assets the pass decided need no import.")
    failed: int = Field(description="Assets still without an intact cache.")
    created_cache_owned: int = Field(
        description="Files the pass created under the cache root."
    )
    created_source_adjacent: int = Field(
        description="Files the pass created beside the sources."
    )


class ResourceImportResult(BaseModel):
    """The result of ``gda resource import`` (#668).

    The report IS the scoping: the engine's import primitive is project-wide,
    so gda runs it only when a requested asset's evidence state is ``missing``
    or ``stale`` (``engine_pass``; an ``invalid`` request settles ``failed``
    without a pass — the engine skips failed imports and parse errors, while
    gda conservatively skips unsupported receipt syntax), and accounts
    for everything it touched — ``created`` lists every new file, classified
    against ``cache_root``. On a dry run nothing runs and nothing is written:
    ``assets`` carry the ``cached`` / ``missing`` / ``stale`` / ``invalid``
    states, ``engine_pass`` says whether a real run WOULD run the pass,
    ``predicted_source_adjacent`` lists the requested assets' sidecars-to-be,
    and ``pass_will_also_import`` the other stale assets the pass will
    re-import (the remaining inventory — engine hash-named cache files under
    ``cache_root``, sidecars for no-sidecar assets, generated ``.uid`` files —
    is the engine's to decide, and the real run's ``created`` is the
    authoritative list). The mode's field set is validated, not merely
    described.
    """

    dry_run: bool = Field(description="Whether this was a dry run.")
    cache_root: str = Field(
        description="The explicit cache root created files are classified against "
        "(res://.godot)."
    )
    engine_pass: bool = Field(
        description=(
            "Whether the engine import pass ran (dry run: whether it WOULD run)."
        )
    )
    assets: list[ResourceImportAsset] = Field(
        description="Per requested asset: the import verdict."
    )
    created: list[ImportCreatedFile] = Field(
        default_factory=list,
        description="Every file the pass created, classified; empty on a dry run.",
    )
    predicted_source_adjacent: list[str] = Field(
        default_factory=list,
        description=(
            "Dry run only: the .import sidecars a real run would create for the "
            "requested assets."
        ),
    )
    pass_will_also_import: list[str] = Field(
        default_factory=list,
        description=(
            "Dry run only: OTHER assets whose committed sidecar fails an "
            "engine check (stale) — the project-wide pass WILL re-import "
            "these. Invalid assets are excluded (the engine skips them), and "
            "assets with no sidecar or generated .uid sidecars cannot be "
            "predicted; the real run's `created` list is the authoritative "
            "inventory."
        ),
    )
    summary: ResourceImportSummary

    @model_validator(mode="after")
    def _mode_fields(self) -> "ResourceImportResult":
        # The #732 lesson: the mode's field set is validated. A dry run writes
        # nothing, so it reports nothing created; a real run predicts nothing,
        # it reports what happened. The summary counts must match the lists.
        if self.dry_run:
            if self.created:
                raise ValueError("a dry run creates nothing.")
            if any(
                asset.status in ("imported", "not_importable", "failed")
                for asset in self.assets
            ):
                raise ValueError("a dry run reports evidence states, not settlements.")
        else:
            if self.predicted_source_adjacent or self.pass_will_also_import:
                raise ValueError("a real run reports created files, not predictions.")
            if any(
                asset.status in ("missing", "stale", "invalid") for asset in self.assets
            ):
                raise ValueError(
                    "evidence states are dry-run verdicts; a real run settles them."
                )
        counted = {
            "cached": self.summary.cached,
            "missing": self.summary.missing,
            "stale": self.summary.stale,
            "invalid": self.summary.invalid,
            "imported": self.summary.imported,
            "not_importable": self.summary.not_importable,
            "failed": self.summary.failed,
        }
        for status, expected in counted.items():
            actual = sum(1 for a in self.assets if a.status == status)
            if actual != expected:
                raise ValueError(f"summary.{status} disagrees with the asset list.")
        if self.summary.requested != len(self.assets):
            raise ValueError("summary.requested disagrees with the asset list.")
        owned = sum(1 for f in self.created if f.classification == "cache_owned")
        if (
            self.summary.created_cache_owned != owned
            or self.summary.created_source_adjacent != len(self.created) - owned
        ):
            raise ValueError("summary created counts disagree with the list.")
        return self


_CACHE_ROOT_REL = ".godot"
_DEST_FILES_LINE = re.compile(r"^dest_files=(\[.*\])$", re.MULTILINE)
_INVALID_LINE = re.compile(r"^valid=false$", re.MULTILINE)
_RECEIPT_ASSIGNMENT_LINE = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*("(?:\\.|[^"\\])*")\s*(?:;.*)?$'
)
_IMPORTER_LINE = re.compile(r'^importer="([^"]*)"$', re.MULTILINE)
_UID_LINE = re.compile(r'^uid="[^"]*"$', re.MULTILINE)
_SOURCE_FILE_LINE = re.compile(r'^source_file="([^"]*)"$', re.MULTILINE)
_PATH_LINE = re.compile(r'^path[.\w]*="([^"]*)"$', re.MULTILINE)
_FILES_LINE = re.compile(r"^files=(\[.*\])$", re.MULTILINE)
# The engine keeps ONE `.md5` receipt per asset at `<import base>.md5`, where
# the import base is DERIVED FROM THE ASSET PATH — `.godot/imported/
# <filename>-<md5 of the res:// path>` (ResourceFormatImporter::
# get_import_base_path) — independent of whether the sidecar declares any
# destinations. Deriving it the same way (verified against a real import's
# hash) is what lets the verdict follow the engine on a no-destination
# sidecar (#738 re-review 4).


def _parse_receipt_assignments(text: str) -> "dict[str, str] | None":
    """Parse gda's documented VariantParser-compatible receipt subset.

    Godot writes quoted-string assignments. Its parser also permits spacing,
    ``;`` comments, JSON-style escapes, and repeated keys; assignments are
    applied in order, so the last value wins. A broader Variant value returns
    ``None`` so the caller takes the contract's conservative no-pass direction
    — as does a lone UTF-16 surrogate escape, which json accepts but
    VariantParser rejects (the engine's parse-error skip).
    """
    assignments: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        assignment = _RECEIPT_ASSIGNMENT_LINE.match(line)
        if assignment is None:
            return None
        try:
            value = json.loads(assignment.group(2))
        except (TypeError, ValueError):
            return None
        if any("\ud800" <= ch <= "\udfff" for ch in value):
            # json.loads accepts a LONE UTF-16 surrogate escape; VariantParser
            # rejects it ("unpaired lead/trail surrogate", TK_ERROR) — the
            # engine's deliberate skip. Paired surrogates decode to a real
            # code point on both sides, so any surrogate left in the decoded
            # value is lone by construction. Stay on the no-pass side.
            return None
        assignments[assignment.group(1)] = value
    return assignments


def _asset_res_path(project: Path, raw: str) -> "str | Failure":
    """Normalize one requested asset to its res:// path, or the refusal.

    ONE containment question, asked once, for BOTH accepted input forms (#763).
    :func:`path_outside_project` — ADR-0006's authority — answers it: for a
    filesystem path by its resolved + lexical double reading (so a legitimately
    symlinked-in file is accepted and a ``..``-through-a-symlink escape is not),
    anchored the way the engine would anchor it (:func:`project_anchored`); for a
    ``res://`` address by the shared lexical rule, which canonicalizes the spelling
    exactly as ``String::simplify_path`` does and refuses only what is still
    climbing above the namespace root afterwards.

    That replaces this gate's own ``".." in rel.parts`` check, which was a
    DIFFERENT rule wearing the same name, and wrong in both directions:

    - it refused ``res://foo/../bar.png``, which collapses net-INSIDE and is an
      address the engine resolves happily — the same spelling ``script validate``
      and ``script run`` both accept, so one input had two verdicts (pinned by
      ``tests/project/test_project.py`` as this issue's to-reconcile);
    - it split on ``PurePosixPath`` parts, so ``res://..\\x.png`` was ONE segment
      carrying no ``..`` at all and passed. On POSIX the later ``is_file()`` check
      happened to stop it; on native Windows ``\\`` IS a separator and the join
      reaches the parent directory. The shared canonicalizer folds ``\\`` to ``/``
      first, as the engine does, so the escape is refused on every platform by the
      one rule instead of by a platform accident (#763, PR #766 round-2 review).

    The refusal is also the shared one now: ``target_outside_project``, the code
    ``script validate`` and ``script run`` report for the same condition, in place
    of a third spelling of a generic ``invalid_params``.

    Ownership (:func:`~gda.project.owning_project`) is asked here too, for the
    engine's own reason: ``EditorFileSystem::_should_skip_directory``
    (``editor/file_system/editor_file_system.cpp:3482``) SKIPS a directory holding
    a nested ``project.godot`` — "Skip if another project inside this" — so an
    asset in one cannot be imported into the outer project at all. Without the
    check gda accepted the request, spent an engine pass, and returned
    ``not_importable``, while ``--dry-run`` predicted a sidecar that would never
    appear. Refusing before the pass, naming the project that CAN import it, is
    both cheaper and truer (#697 re-review).

    What remains this gate's own is what is genuinely about ASSETS: ``user://`` and
    ``uid://`` are engine-virtual but not the project's ``res://`` namespace, so
    they cannot name a project asset at all, and the mapping from an accepted
    filesystem path back to the ``res://`` address the engine will import.
    """
    if is_engine_virtual_path(raw) and not raw.startswith(RES_PREFIX):
        # user:// / uid:// are engine-virtual but NOT the project's res://
        # namespace: gda cannot address them as project assets, and passing
        # them on would misread them as literal filesystem names (#738
        # re-review 2).
        return make_failure(
            "invalid_params",
            f"asset {raw!r} is not a project asset: only res:// paths or "
            "filesystem paths inside the project are accepted.",
            "",
        )
    # One coordinate system for BOTH sides before any comparison: a relative
    # --project must not meet an absolute candidate (#738 re-review 2 — the
    # mixed comparison raised a bare ValueError on the lexical fallback). This
    # local is for the res:// MAPPING further down, which needs the same absolute
    # root the gate below reads. Not a two-places-must-agree coupling: there is one
    # normalization RULE — `project_absolute` — and both sites call it, so the only
    # cost of asking twice is a second `Path.cwd()` (#807 review).
    project_abs = project_absolute(project)
    # ONE call for ownership-then-containment and both refusal envelopes (#802).
    # What used to stand here — the two probes, their order, the four coordinates
    # and the resolved root each refusal reports — now lives on ADR-0006's path
    # authority, so this gate keeps only what is genuinely about ASSETS.
    refusal = containment_refusal(raw, project)
    if refusal is not None:
        return refusal
    if raw.startswith(RES_PREFIX):
        # Already in the engine's namespace: canonicalize the spelling and stop.
        # Reading it lexically is what the engine does too — a symlink inside the
        # project stays as spelled, because Godot walks the project directory.
        return canonical_res_path(raw)
    anchored = project_anchored(raw, project_abs)
    try:
        rel_fs = anchored.resolve().relative_to(project_abs.resolve())
    except ValueError:
        try:
            # Contained by the lexical reading only (a symlinked-in file):
            # keep the caller's spelling, normalized lexically.
            rel_fs = Path(os.path.normpath(anchored)).relative_to(
                Path(os.path.normpath(project_abs))
            )
        except ValueError:
            # Total by construction — the shared gate said "inside", so one
            # of the two readings must relate — but a refusal beats a bare
            # traceback if that invariant is ever disturbed.
            return make_failure(
                "invalid_params",
                f"asset {raw!r} could not be addressed inside the project {project}.",
                "",
            )
    # Through the SAME canonicalizer as the res:// form, so both input spellings
    # of one asset produce one address — `.` (the project root, from `foo/..`)
    # included, which `PurePosixPath` used to hand on as the bogus `res://.`.
    return canonical_res_path(RES_PREFIX + rel_fs.as_posix())


def run_resource_load_operation(
    project: Path, path: str | Path, *, godot: str | None = None
) -> ResourceLoadResult | Failure:
    """Ask Godot to load one project asset and return a bounded observation.

    This is the returning host-operation seam for composite workflows. It keeps
    project ownership and containment in gda, then uses the ordinary sentinel
    runner and classifier without emitting a CLI envelope or exiting.
    """
    addressed = _asset_res_path(project, str(path))
    if isinstance(addressed, Failure):
        return addressed
    return _execute_resource_load(
        ResourceLoadParams(path=addressed),
        godot=godot,
        project=project,
    )


def run_resource_inspect_model_operation(
    project: Path, params: ResourceInspectModelParams, *, godot: str | None = None
) -> ResourceInspectModelResult | Failure:
    """Return the same model facts for a composite consumer, without CLI emission."""
    addressed = _asset_res_path(project, params.path)
    if isinstance(addressed, Failure):
        return addressed
    return RESOURCE_INSPECT_MODEL_COMMAND.execute(
        params.model_copy(update={"path": addressed}), godot=godot, project=project
    )


def _package_input(package: Path, paths: list[str]) -> Failure | tuple[Path, list[str]]:
    selected = package.expanduser().absolute()
    if selected.suffix.lower() != ".pck":
        return make_failure(
            "invalid_params", "package inspection supports .pck files only", ""
        )
    if not selected.is_file():
        return make_failure("path_not_found", f"package not found: {selected}", "")
    normalized: list[str] = []
    for path in paths:
        if (
            not path.startswith("res://")
            or path == "res://"
            or "\\" in path
            or ":" in path[6:]
            or any(part in {"", ".", ".."} for part in path[6:].split("/"))
        ):
            return make_failure(
                "invalid_path",
                f"package resource must be an exact normalized res:// path: {path}",
                "",
            )
        normalized.append(path)
    return selected, normalized


def run_package_inspect_model_operation(
    package: Path,
    params: ResourceInspectModelParams,
    *,
    godot: str | None = None,
    make_runner: PackageRunnerFactory | None = None,
) -> ResourceInspectModelResult | Failure:
    """Inspect one PackedScene through an exported PCK's isolated res:// view."""
    admitted = _package_input(package, [str(params.path)])
    if isinstance(admitted, Failure):
        return admitted
    selected_package, paths = admitted
    factory = make_runner or make_package_runner
    try:
        binary = resolve_godot_binary(godot)
    except ValueError as exc:
        return unresolvable_binary_failure(str(exc))
    runner = factory(binary, selected_package)
    if isinstance(runner, Failure):
        return runner
    outcome = RESOURCE_INSPECT_MODEL_COMMAND.execute(
        params.model_copy(update={"path": paths[0]}),
        godot=str(binary),
        project=None,
        make_runner=lambda _binary, _project: runner,
    )
    if isinstance(outcome, Failure):
        return outcome
    if outcome.path != paths[0] or outcome.subtree != params.subtree:
        return make_failure(
            "contract_violation",
            "package inspector returned a different resource path or subtree",
            "",
        )
    return outcome


def run_package_resource_presence_operation(
    package: Path,
    params: PackageResourcePresenceParams,
    *,
    godot: str | None = None,
    make_runner: PackageRunnerFactory | None = None,
) -> PackageResourcePresenceResult | Failure:
    """Return native loadability presence for exact resource paths in one PCK."""
    admitted = _package_input(package, [str(path) for path in params.paths])
    if isinstance(admitted, Failure):
        return admitted
    selected_package, paths = admitted
    factory = make_runner or make_package_runner
    try:
        binary = resolve_godot_binary(godot)
    except ValueError as exc:
        return unresolvable_binary_failure(str(exc))
    runner = factory(binary, selected_package)
    if isinstance(runner, Failure):
        return runner
    outcome = PACKAGE_RESOURCE_PRESENCE_COMMAND.execute(
        params.model_copy(update={"paths": paths}),
        godot=str(binary),
        project=None,
        make_runner=lambda _binary, _project: runner,
    )
    if isinstance(outcome, Failure):
        return outcome
    if [item.path for item in outcome.resources] != paths:
        return make_failure(
            "contract_violation",
            "package presence result does not match the requested exact paths",
            "",
        )
    return outcome


def run_resource_inspect_model_content_operation(
    project: Path,
    params: ResourceInspectModelContentParams,
    *,
    godot: str | None = None,
    make_runner: RunnerFactory | None = None,
) -> ResourceInspectModelContentResult | Failure:
    """Return bounded GLB content facts without emitting or exiting."""
    addressed = _asset_res_path(project, params.path)
    if isinstance(addressed, Failure):
        return addressed
    if Path(addressed).suffix.lower() != ".glb":
        return make_failure(
            "invalid_params", "inspect-model-content supports GLB resources only", ""
        )
    selected = params.model_copy(update={"path": addressed})
    if make_runner is None:
        return RESOURCE_INSPECT_MODEL_CONTENT_COMMAND.execute(
            selected, godot=godot, project=project
        )
    return RESOURCE_INSPECT_MODEL_CONTENT_COMMAND.execute(
        selected, godot=godot, project=project, make_runner=make_runner
    )


def _asset_state(project: Path, res_path: str) -> ResourceImportAsset:
    """One asset's evidence state, read as the engine's own reimport test reads it.

    A faithful adaptation of ``EditorFileSystem::_test_for_reimport`` (#738
    review), in the engine's own order: an unparseable or ``valid=false``
    sidecar is ``invalid`` (the engine SKIPS these rather than retrying), and
    so is an unparseable ``.md5`` receipt — the engine's receipt parse-error
    branch is the same deliberate skip, never a re-import (#738 re-review 5);
    gda's receipt grammar covers the quoted-string assignments the engine
    writes plus VariantParser spacing, ``;`` comments, JSON-style escapes
    (lone UTF-16 surrogates excluded, as VariantParser rejects them), and
    repeated assignments (the last value wins). Broader Variant value syntax errs
    toward ``invalid``, the no-pass direction the contract sanctions; a
    ``keep``/``skip`` importer is ``cached``; the pre-UID format, a missing
    remap/destination file, a ``source_file`` naming a different source (a
    copied sidecar), a missing ``.md5`` receipt (located at the PATH-derived
    import base, as the engine locates it), or a ``source_md5`` /
    ``dest_md5`` disagreeing with the actual bytes are all ``stale`` (the
    engine WOULD re-import). ``cached`` needs POSITIVE evidence: a keep/skip
    importer, or the path-derived receipt present and matching — with any
    DECLARED destinations also present and digest-checked; a sidecar
    declaring none but carrying a matching receipt passes the same checks
    (#738 re-review 4; the engine's own pass leaves it untouched when the
    declared remainder below is controlled — verified live). A sidecar with no importer line proves nothing
    and is conservatively ``stale`` (#738 re-review 2). The checks the engine makes
    from its own state — whether the DECLARED importer still exists (its
    registry is open: import plugins add names, so no offline list can be
    authoritative), its format version, its project-settings validity, and
    the editor cache's expected sidecar MD5 — cannot be read from the
    project's artifacts, so a sidecar drifted in those dimensions can look
    ``cached`` here until any pass runs; the contract names that remainder,
    and its direction: it can delay a re-import until the next pass, never
    spend a pass the engine would not.
    """
    rel = res_path[len("res://") :]
    sidecar_fs = project / (rel + ".import")
    if not sidecar_fs.is_file():
        return ResourceImportAsset(path=res_path, status="missing")
    sidecar_res = res_path + ".import"
    declared_importer: str | None = None
    declared_source_file: str | None = None

    def state(
        status: AssetStatus, dests: "list[str] | None" = None
    ) -> ResourceImportAsset:
        return ResourceImportAsset(
            path=res_path,
            status=status,
            sidecar=sidecar_res,
            dest_files=dests or [],
            declared_importer=declared_importer,
            declared_source_file=declared_source_file,
        )

    try:
        text = sidecar_fs.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # The engine's parse-error branch: skip, never auto-reimport.
        return state("invalid")
    importer_match = _IMPORTER_LINE.search(text)
    source_file_match = _SOURCE_FILE_LINE.search(text)
    declared_importer = importer_match.group(1) if importer_match is not None else None
    declared_source_file = (
        source_file_match.group(1) if source_file_match is not None else None
    )
    if _INVALID_LINE.search(text):
        return state("invalid")
    if declared_importer is None:
        # No importer DECLARED: nothing proves this sidecar's cache.
        # Conservatively stale (#738 re-review 2). Whether a declared name
        # still RESOLVES is engine state (an open registry) — part of the
        # declared remainder, not decidable here.
        return state("stale")
    if declared_importer in ("keep", "skip"):
        return state("cached")
    dest_match = _DEST_FILES_LINE.search(text)
    dests: list[str] = []
    if dest_match is not None:
        try:
            dests = [str(d) for d in json.loads(dest_match.group(1))]
        except ValueError:
            return state("invalid")
    if _UID_LINE.search(text) is None:
        return state("stale", dests)  # pre-UID format: the engine re-imports
    # Every remap/destination reference must exist (path=, path.<variant>=,
    # files=[...], dest_files=[...] — the engine's to_check set).
    to_check = list(dests)
    to_check.extend(_PATH_LINE.findall(text))
    files_match = _FILES_LINE.search(text)
    if files_match is not None:
        try:
            to_check.extend(str(f) for f in json.loads(files_match.group(1)))
        except ValueError:
            return state("invalid")
    for ref in to_check:
        if ref.startswith("res://") and not (project / ref[len("res://") :]).is_file():
            return state("stale", dests)
    if declared_source_file is not None and declared_source_file != res_path:
        return state("stale", dests)  # a copied sidecar names another source
    # The engine's one .md5 receipt per asset, at the path-derived import
    # base — read whether or not destinations are declared, exactly as
    # _test_for_reimport reads it. A missing receipt is what the engine
    # re-imports; a present, matching one is the POSITIVE evidence a cached
    # verdict needs — including for a sidecar that declares no destinations,
    # which the engine leaves untouched (#738 re-review 4, verified live).
    receipt = (
        project
        / ".godot"
        / "imported"
        / (
            Path(rel).name
            + "-"
            + hashlib.md5(res_path.encode("utf-8")).hexdigest()
            + ".md5"
        )
    )
    if not receipt.is_file():
        return state("stale", dests)
    receipt_text = receipt.read_text(encoding="utf-8", errors="replace")
    # The engine parses the receipt with VariantParser, and ANY parse error
    # is the same deliberate skip as a valid=false sidecar ("skip and let
    # user attempt manual reimport to avoid reimport loop") — never a
    # re-import (#738 re-review 5). Parse assignments in engine order: Godot's
    # VariantParser applies every assignment, so repeated keys are last-write-
    # wins (#738 re-review 6). The engine writes quoted-string values; accept
    # that public subset plus its spacing/comments/escapes, while broader
    # Variant values conservatively take the sanctioned no-pass direction.
    assignments = _parse_receipt_assignments(receipt_text)
    if assignments is None:
        return state("invalid", dests)
    recorded_source = assignments.get("source_md5")
    if recorded_source is None:
        # Parseable but lacking source_md5: the engine's "Lacks md5, so
        # just reimport" — a pass state, unlike the parse error above.
        return state("stale", dests)
    if hashlib.md5((project / rel).read_bytes()).hexdigest() != recorded_source:
        return state("stale", dests)
    recorded_dest = assignments.get("dest_md5")
    if dests and recorded_dest:
        # The engine's multi-file digest: one MD5 over every destination's
        # bytes, in the sidecar's order (FileAccess::get_multiple_md5).
        ctx = hashlib.md5()
        for dest in dests:
            dest_fs = project / dest[len("res://") :]
            if dest_fs.is_file():
                ctx.update(dest_fs.read_bytes())
        if ctx.hexdigest() != recorded_dest:
            return state("stale", dests)
    return state("cached", dests)


def _project_files(project: Path) -> set[str]:
    """Every file under the project (relative posix paths), .git excluded."""
    files: set[str] = set()
    for path in project.rglob("*"):
        rel = path.relative_to(project)
        if rel.parts and rel.parts[0] == ".git":
            continue
        if path.is_file():
            files.add(rel.as_posix())
    return files


# The two marker files the engine's scan skips a directory on. Named here, not
# spelled inline, because the same two literals are declared a second time in
# ``operations.gd`` (``NESTED_PROJECT_MARKER`` / ``GDIGNORE_MARKER``) for the walk
# — one rule, two languages. ``test_the_two_spellings_of_the_skip_markers_agree``
# reads both files and fails if they drift apart (#808 review).
NESTED_PROJECT_MARKER = "project.godot"
GDIGNORE_MARKER = ".gdignore"


def _engine_skips_directory_of(project: Path, rel: str) -> bool:
    """Whether the engine's own scan never reaches ``rel`` (#804).

    Two clauses of ``EditorFileSystem``'s scan decide this, and the prediction
    needs BOTH because the scan asks them in order:

    * ``_scan_new_dir`` drops every **dot-prefixed directory** before it
      consults the skip rule at all (``editor/file_system/
      editor_file_system.cpp:1157-1168``, line numbers from the 4.6.3-stable
      tag) — so ``res://.hidden/h.png`` is unreachable however ordinary it
      looks. This clause subsumes the ``.godot`` cache and a ``.git`` checkout,
      at any depth rather than at the project root alone;
    * ``_should_skip_directory`` (same file, ``3460-3480``) then skips a
      directory holding a ``project.godot`` — another project inside this one —
      or a ``.gdignore`` marker.

    Every directory ABOVE ``rel`` up to (but never including) the project root
    is asked, because one marker hides the whole subtree.

    **This is not the walk's rule, and must not be read as it.** The same two
    markers gate ``_should_descend`` in ``operations.gd``, but that walk answers
    a different question — what gda ENUMERATES — and deliberately keeps hidden
    and dot-prefixed directories in (#54, #712). This predicate answers what the
    ENGINE reaches, so it drops them. Two further divergences are known and
    stated rather than chased: ``Path.rglob`` does not descend a symlinked
    directory while the walk does (#760), so a stale asset behind a link is not
    predicted — an omission, never a false promise, and the real run's
    ``created`` list stays authoritative; and the OS "hidden" attribute the
    engine also honours (``DirAccess::current_is_hidden``) has no portable
    Python reading, so only the dot-prefix half of that clause is modelled.

    Cost: the ancestors are re-probed per sidecar and memoized nowhere — 2000
    sidecars at depth 4 cost ~16k ``stat`` calls, measured at 0.11 s. A cache
    was declined for the same reason the walk declines one: the state would buy
    nothing at this size.
    """
    parts = Path(rel).parent.parts
    for depth in range(1, len(parts) + 1):
        if parts[depth - 1].startswith("."):
            return True
        directory = project.joinpath(*parts[:depth])
        if (directory / NESTED_PROJECT_MARKER).is_file():
            return True
        if (directory / GDIGNORE_MARKER).is_file():
            return True
    return False


def _project_import_gaps(project: Path, requested: set[str]) -> list[str]:
    """Other assets the project-wide pass WILL re-import (#738 review).

    The dry-run inventory's project-wide half: every asset OUTSIDE the request
    whose committed sidecar fails an engine check (``stale``) — the states the
    engine's own reimport test acts on. ``invalid`` sidecars are EXCLUDED: the
    engine deliberately skips a previously failed import (verified against a
    live pass — the invalid sidecar's bytes stay untouched). Assets with NO
    sidecar (and the ``.uid`` sidecars the pass may generate) cannot be
    predicted from here — the engine decides those — so the real run's
    ``created`` list stays the authoritative inventory, and the contract says
    so.

    An asset the engine's scan never reaches is not a gap either (#804): the
    pass skips a nested project's, a ``.gdignore``d and a dot-prefixed
    directory's contents, so predicting a re-import there promised work the
    engine will not do. That one predicate replaced the ``.godot``/``.git``
    prefix test this loop used to make, which was the same clause spelled for
    two directories at the project root only (#808 review).
    """
    gaps: list[str] = []
    for sidecar in sorted(project.rglob("*.import")):
        rel = sidecar.relative_to(project).as_posix()
        if _engine_skips_directory_of(project, rel):
            continue
        res_path = "res://" + rel[: -len(".import")]
        if res_path in requested:
            continue
        source = project / rel[: -len(".import")]
        if not source.is_file():
            continue
        if _asset_state(project, res_path).status == "stale":
            gaps.append(res_path)
    return gaps


def _summarize(
    assets: list[ResourceImportAsset], created: list[ImportCreatedFile]
) -> ResourceImportSummary:
    owned = sum(1 for f in created if f.classification == "cache_owned")
    return ResourceImportSummary(
        requested=len(assets),
        cached=sum(1 for a in assets if a.status == "cached"),
        missing=sum(1 for a in assets if a.status == "missing"),
        stale=sum(1 for a in assets if a.status == "stale"),
        invalid=sum(1 for a in assets if a.status == "invalid"),
        imported=sum(1 for a in assets if a.status == "imported"),
        not_importable=sum(1 for a in assets if a.status == "not_importable"),
        failed=sum(1 for a in assets if a.status == "failed"),
        created_cache_owned=owned,
        created_source_adjacent=len(created) - owned,
    )


def run_resource_import_operation(
    project: Optional[Path],
    params: ResourceImportParams,
    *,
    godot: Optional[str] = None,
    options_changed: bool = False,
    _observe_pass: Callable[[RunResult], None] | None = None,
) -> "ResourceImportResult | Failure":
    """Decide per asset, run the engine pass only when needed, account for it all.

    The recipe: normalize + verify the requested assets, take their cache
    verdicts, and — unless everything is cached or this is a dry run — run the
    engine's project-wide ``--import`` pass through the shared launch primitive,
    then re-verdict the assets and classify every created file against the
    cache root. ``options_changed`` is the reimport caller's known configuration
    change: cached artifact evidence then also requests a pass, since it does
    not check importer options. This does not bypass invalid evidence or add
    a per-file engine primitive; ordinary resource import leaves it false.
    The internal pass observer lets reimport retain diagnostics for a later
    adoption failure without adding fields to the public import result.
    """
    assert project is not None  # a project-using recipe; dispatch resolved it
    res_paths: list[str] = []
    for raw in params.assets:
        res_path = _asset_res_path(project, raw)
        if isinstance(res_path, Failure):
            return res_path
        source = project / res_path[len("res://") :]
        if not source.is_file():
            return make_failure(
                "invalid_params",
                f"asset {res_path} does not exist in the project.",
                "",
            )
        res_paths.append(res_path)
    # A repeated asset is idempotent; normalize it away, order preserved.
    res_paths = list(dict.fromkeys(res_paths))

    assets = [_asset_state(project, res_path) for res_path in res_paths]
    cache_root = "res://" + _CACHE_ROOT_REL
    # The pass runs for what the engine would act on: missing and stale.
    # An invalid request never triggers it — the engine skips a previously
    # failed import and an unparseable artifact (delete the sidecar to
    # retry) — so it settles to failed
    # without spending a pass.
    needs_pass = any(
        asset.status in ("missing", "stale")
        or (options_changed and asset.status == "cached")
        for asset in assets
    )

    if params.dry_run:
        predicted = [
            asset.path + ".import"
            for asset in assets
            if asset.status == "missing" and asset.sidecar is None
        ]
        return ResourceImportResult(
            dry_run=True,
            cache_root=cache_root,
            engine_pass=needs_pass,
            assets=assets,
            predicted_source_adjacent=predicted,
            pass_will_also_import=(
                _project_import_gaps(project, set(res_paths)) if needs_pass else []
            ),
            summary=_summarize(assets, []),
        )

    created: list[ImportCreatedFile] = []
    if needs_pass:
        binary = resolve_godot_binary(godot)
        before = _project_files(project)
        # Module-global lookup (the one launch seam): tests patch
        # `gda.commands.resource.launch`, the scene/script channels' pattern.
        raw = launch(
            binary,
            ["--path", str(project), "--import"],
            cwd=None,
            timeout=params.timeout,
            timeout_label="Godot import",
        )
        if _observe_pass is not None:
            _observe_pass(raw)
        prefix = classify_launch_or_crash(raw, binary)
        if prefix is not None:
            return prefix
        if raw.exit_code != 0:
            return make_failure(
                "operation_failed",
                f"the engine import pass exited {raw.exit_code}",
                raw.stderr,
            )
        after = _project_files(project)
        created = [
            ImportCreatedFile(
                path="res://" + rel,
                classification=(
                    "cache_owned"
                    if rel == _CACHE_ROOT_REL or rel.startswith(_CACHE_ROOT_REL + "/")
                    else "source_adjacent"
                ),
            )
            for rel in sorted(after - before)
        ]
    # Settle every evidence state (whether or not a pass ran): a re-read
    # answering cached means the pass imported it; no sidecar after a pass
    # means the engine decided the type needs no import; anything else —
    # including every invalid request, which the pass deliberately skips —
    # is failed.
    settled: list[ResourceImportAsset] = []
    for asset in assets:
        if asset.status == "cached" and not options_changed:
            settled.append(asset)
            continue
        now = _asset_state(project, asset.path)
        if now.status == "cached":
            settled.append(now.model_copy(update={"status": "imported"}))
        elif now.sidecar is None or not needs_pass:
            settled.append(
                now.model_copy(
                    update={
                        "status": (
                            "not_importable" if now.sidecar is None else "failed"
                        )
                    }
                )
            )
        else:
            settled.append(now.model_copy(update={"status": "failed"}))
    assets = settled

    return ResourceImportResult(
        dry_run=False,
        cache_root=cache_root,
        engine_pass=needs_pass,
        assets=assets,
        created=created,
        summary=_summarize(assets, created),
    )


class RootScaleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_scale: float = Field(
        alias="nodes/root_scale",
        strict=True,
        allow_inf_nan=False,
        ge=ROOT_SCALE_MIN,
        le=ROOT_SCALE_MAX,
        description="Positive uniform scale for the built-in scene importer.",
    )


class ResourceReimportParams(BaseModel):
    path: NormalizedPath = Field(
        description="An already imported GLB source in the project."
    )
    updates: RootScaleUpdate = Field(
        description="Supported importer edits; currently nodes/root_scale only."
    )
    dry_run: bool = Field(
        default=False,
        description="Check the patch without target writes, loading, or an import pass.",
    )
    timeout: float = Field(
        default=300.0,
        gt=0,
        allow_inf_nan=False,
        description="Seconds to allow the project-wide import pass; sentinel queries retain their normal timeout.",
    )


class ImportOptionChange(BaseModel):
    name: str
    before: float
    requested: float


_SCALE_REL_TOLERANCE = 0.00001
_SCALE_ABS_TOLERANCE = 0.0001


class RootScaleVerification(BaseModel):
    before: ModelBounds
    after: ModelBounds
    scale_ratio: float
    effective_root_scale: float | None = Field(
        description="Configured scale supported by this size comparison; null when verification fails."
    )
    matched: bool
    compared_axes: list[int] = Field(
        description="Size axes above 0.0001 before scaling; 0=x, 1=y, 2=z."
    )
    measurement: Literal["static_mesh_aabb_size"] = "static_mesh_aabb_size"
    relative_tolerance: float = _SCALE_REL_TOLERANCE
    absolute_tolerance: float = _SCALE_ABS_TOLERANCE


class ResourceReimportResult(BaseModel):
    path: str
    dry_run: bool
    status: Literal["checked", "unchanged", "applied", "failed"]
    changes: list[ImportOptionChange]
    sidecar_changed: bool = False
    import_result: ResourceImportResult | None = None
    engine_pass_attempted: bool = False
    verification: RootScaleVerification | None = None
    mutation_scope: str = "Selected source-adjacent .import options; actual import work is project-wide. Verification loads trusted project code."


class _ImportConfigEditParams(BaseModel):
    sidecar: str
    original: str
    root_scale: float


class _ImportConfigEditResult(BaseModel):
    root_scale: float
    changed_unselected_options: list[str] = Field(default_factory=list)


_IMPORT_CONFIG_PATCH = HeadlessCommand(
    operation="resource-import-config-patch",
    input_model=_ImportConfigEditParams,
    output_model=_ImportConfigEditResult,
    render=lambda result: str(result.root_scale),
)
_IMPORT_CONFIG_CHECK = HeadlessCommand(
    operation="resource-import-config-check",
    input_model=_ImportConfigEditParams,
    output_model=_ImportConfigEditResult,
    render=lambda result: str(result.root_scale),
)


def _reimport_bounds(
    project: Path, path: str, godot: str | None
) -> ModelBounds | Failure:
    inspected = run_resource_inspect_model_operation(
        project,
        ResourceInspectModelParams(path=path, max_nodes=4096, max_items=1),
        godot=godot,
    )
    if isinstance(inspected, Failure):
        return inspected
    if inspected.bounds is None or any(
        item.reason == "node_limit" for item in inspected.omissions
    ):
        return make_failure(
            "invalid_params",
            "root-scale verification needs complete static mesh bounds within 4096 nodes",
            "",
        )
    return inspected.bounds


def _reimport_failure(failure: Failure, result: ResourceReimportResult) -> Failure:
    result.status = "failed"
    failure.error = failure.error.model_copy(
        update={"partial_result": result.model_dump(mode="json")}
    )
    return failure


def _sizes_match(
    before: ModelBounds, after: ModelBounds, ratio: float, axes: list[int]
) -> bool:
    return all(
        math.isclose(
            after.size[i],
            before.size[i] * ratio,
            rel_tol=_SCALE_REL_TOLERANCE,
            abs_tol=_SCALE_ABS_TOLERANCE,
        )
        for i in axes
    )


def run_resource_reimport_operation(
    project: Path, params: ResourceReimportParams, *, godot: str | None = None
) -> ResourceReimportResult | Failure:
    options = run_resource_import_options_operation(
        project, ResourceImportOptionsParams(path=params.path), godot=godot
    )
    if isinstance(options, Failure):
        return options
    current = {option.name: option for option in options.configured_options}
    scale = current.get("nodes/root_scale")
    apply_scale = current.get("nodes/apply_root_scale")
    if (
        scale is None
        or scale.value_type != "float"
        or not isinstance(scale.value, (int, float))
        or not ROOT_SCALE_MIN <= scale.value <= ROOT_SCALE_MAX
        or apply_scale is None
        or apply_scale.value_type != "bool"
    ):
        return make_failure(
            "invalid_params",
            "supported scene root-scale configuration is unavailable",
            "",
        )
    evidence = _asset_state(project_absolute(project), options.path)
    if evidence.status == "invalid":
        return make_failure(
            "invalid_params",
            "import evidence is invalid; inspect resource import --dry-run and repair it explicitly before changing options",
            "",
        )
    requested = params.updates.root_scale
    changes = (
        []
        if scale.value == requested
        else [
            ImportOptionChange(
                name="nodes/root_scale", before=scale.value, requested=requested
            )
        ]
    )
    result = ResourceReimportResult(
        path=options.path,
        dry_run=params.dry_run,
        status="checked" if params.dry_run else "unchanged",
        changes=changes,
    )
    if params.dry_run or not changes:
        return result
    if evidence.status != "cached":
        return make_failure(
            "invalid_params",
            "import the source explicitly before comparing its configured scale with a new value",
            "",
        )
    source = project_absolute(project) / options.path[len(RES_PREFIX) :]
    sidecar = source.with_name(source.name + ".import")
    original = sidecar.read_bytes()
    with source.open("rb") as stream:
        source_digest = hashlib.file_digest(stream, "sha256").digest()
    before = _reimport_bounds(project, options.path, godot)
    if isinstance(before, Failure):
        return before
    axes = [i for i, extent in enumerate(before.size) if extent > _SCALE_ABS_TOLERANCE]
    if not axes:
        return make_failure(
            "invalid_params", "model has no measurable size axis above 0.0001", ""
        )
    ratio = requested / scale.value
    if _sizes_match(before, before, ratio, axes):
        return make_failure(
            "invalid_params",
            "requested size change is below verification tolerance; unchanged geometry could pass",
            "",
        )
    import_stderr = ""

    def retain_import_stderr(raw: RunResult) -> None:
        nonlocal import_stderr
        import_stderr = captured_output_tail(raw.stderr)

    with _import_config_project() as scratch:
        reference = scratch / "original.import"
        reference.write_bytes(original)
        edit = _ImportConfigEditParams(
            sidecar=str(sidecar), original=str(reference), root_scale=requested
        )
        patched = _IMPORT_CONFIG_PATCH.execute(edit, project=scratch, godot=godot)
        # A timeout or save failure may still have changed the file.
        result.sidecar_changed = (
            not sidecar.is_file() or sidecar.read_bytes() != original
        )
        if isinstance(patched, Failure):
            return _reimport_failure(patched, result)
        result.engine_pass_attempted = True
        imported = run_resource_import_operation(
            project,
            ResourceImportParams(assets=[options.path], timeout=params.timeout),
            godot=godot,
            options_changed=True,
            _observe_pass=retain_import_stderr,
        )
        if isinstance(imported, Failure):
            return _reimport_failure(imported, result)
        result.import_result = imported
        if imported.summary.failed or not imported.engine_pass:
            return _reimport_failure(
                make_failure(
                    "operation_failed",
                    "updated options remain on disk, but import did not succeed",
                    "",
                ),
                result,
            )
        checked = _IMPORT_CONFIG_CHECK.execute(edit, project=scratch, godot=godot)
        if isinstance(checked, Failure):
            return _reimport_failure(checked, result)
        if checked.root_scale != requested or checked.changed_unselected_options:
            return _reimport_failure(
                make_failure(
                    "operation_failed",
                    "engine changed unselected import options or did not retain root_scale: "
                    + ", ".join(checked.changed_unselected_options),
                    "",
                ),
                result,
            )
    after = _reimport_bounds(project, options.path, godot)
    if isinstance(after, Failure):
        return _reimport_failure(after, result)
    result.verification = RootScaleVerification(
        before=before,
        after=after,
        scale_ratio=ratio,
        effective_root_scale=None,
        compared_axes=axes,
        matched=_sizes_match(before, after, ratio, axes)
        and not _sizes_match(before, after, 1.0, axes),
    )
    with source.open("rb") as stream:
        source_unchanged = (
            hashlib.file_digest(stream, "sha256").digest() == source_digest
        )
    if not source_unchanged or not result.verification.matched:
        import_explanation = (
            " The project-wide import pass completed and its cache reread reported "
            f"{imported.summary.imported} imported asset(s); that count does not prove adoption. "
            "Existing cache artifacts can remain loadable after a rejected import. "
        )
        diagnostic_explanation = (
            "Diagnostics contain the last 16 KiB of project-wide import stderr; "
            "these lines alone do not establish this asset's cause."
            if import_stderr
            else "No stderr was captured from the import pass; a native cause was not established."
        )
        return _reimport_failure(
            make_failure(
                "operation_failed",
                "loaded dimensions do not verify the requested scale on unchanged source bytes; "
                "updated options remain on disk and no rollback was attempted."
                + import_explanation
                + diagnostic_explanation,
                import_stderr,
            ),
            result,
        )
    result.verification.effective_root_scale = requested
    result.status = "applied"
    return result


def _resource_reimport_recipe(params, *, project, godot):
    return run_resource_reimport_operation(project, params, godot=godot)


def render_resource_reimport(result: ResourceReimportResult) -> str:
    text = f"{result.path}: {result.status}, {len(result.changes)} option change(s)"
    if result.import_result is not None:
        text += "\n" + render_resource_import(result.import_result)
    if result.verification is not None:
        text += f"\n  loaded size scale verified: {result.verification.scale_ratio:g}x"
    return text


RESOURCE_REIMPORT_COMMAND: HeadlessCommand[ResourceReimportResult] = HeadlessCommand(
    operation="resource-reimport",
    input_model=ResourceReimportParams,
    output_model=ResourceReimportResult,
    render=render_resource_reimport,
    kind=ExecutionKind.COMPOSITE,
    recipe=_resource_reimport_recipe,
)


@_app.command(name="reimport", cls=RESOURCE_REIMPORT_COMMAND.command_class())
def resource_reimport(
    path: str = typer.Argument(..., help="The imported GLB to update."),
    updates: str = typer.Option(
        ..., "--updates-json", help="JSON object of supported import-option edits."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate without changing target files or running an import pass.",
    ),
    timeout: float = typer.Option(
        300.0, min=0.001, help="Seconds to allow the project-wide import pass."
    ),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_REIMPORT_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Validate a supported option edit, reimport and verify the loaded model."""
    try:
        parsed_updates = json.loads(updates)
    except ValueError as exc:
        raise typer.BadParameter("updates-json must be a JSON object") from exc
    params = params_or_bad_parameter(
        ResourceReimportParams,
        path=path,
        updates=parsed_updates,
        dry_run=dry_run,
        timeout=timeout,
    )
    dispatch_recipe(
        RESOURCE_REIMPORT_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


def _resource_import_recipe(params, *, project, godot):
    return run_resource_import_operation(project, params, godot=godot)


def render_resource_import(outcome: "ResourceImportResult") -> str:
    """Render the verdicts, the pass, and the created-file accounting (#668)."""
    mode = "dry run" if outcome.dry_run else "import"
    ran = (
        ("pass would run" if outcome.dry_run else "pass ran")
        if outcome.engine_pass
        else "no pass needed"
    )
    header = (
        f"resource {mode}: {outcome.summary.requested} asset(s), {ran} "
        f"(cache root {outcome.cache_root})"
    )
    lines = [f"  {asset.status:>14}  {asset.path}" for asset in outcome.assets]
    if any(asset.status == "invalid" for asset in outcome.assets):
        lines.append(
            "  invalid: no pass runs for a failed import, a parse error, or "
            "unsupported receipt syntax; delete the asset's .import sidecar "
            "to retry (the pass rewrites the sidecar and its .md5 receipt)"
        )
    if outcome.pass_will_also_import:
        lines.append("  the pass will also re-import:")
        lines.extend(f"    {path}" for path in outcome.pass_will_also_import)
    if outcome.created:
        lines.append(
            f"  created: {outcome.summary.created_cache_owned} cache-owned, "
            f"{outcome.summary.created_source_adjacent} source-adjacent"
        )
        lines.extend(
            f"    {f.classification:>15}  {f.path}"
            for f in outcome.created
            if f.classification == "source_adjacent"
        )
    if outcome.predicted_source_adjacent:
        lines.append("  a real run would create beside the sources:")
        lines.extend(f"    {p}" for p in outcome.predicted_source_adjacent)
    return "\n".join([header, *lines])


# `resource import` is a recipe command (ADR-0023): its outcome is decided
# CLI-side (cache verdicts, the pass decision, the before/after accounting) and
# its engine call is the shared launch primitive with the project-wide
# `--import` argv — not a sentinel op, like `export run`'s native channel.
RESOURCE_IMPORT_COMMAND: HeadlessCommand[ResourceImportResult] = HeadlessCommand(
    operation="resource-import",
    input_model=ResourceImportParams,
    output_model=ResourceImportResult,
    render=render_resource_import,
    kind=ExecutionKind.IMPORT,
    recipe=_resource_import_recipe,
)


@_app.command(name="import", cls=RESOURCE_IMPORT_COMMAND.command_class())
def resource_import(
    assets: list[str] = typer.Argument(
        ...,
        help=(
            "The assets to ensure are imported: res:// paths, or filesystem "
            "paths inside the project (relative means project-relative)."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Report the per-asset cache verdicts and the predicted mutations "
            "without running the engine pass or writing anything."
        ),
    ),
    timeout: float = typer.Option(
        300.0,
        "--timeout",
        min=0.001,
        help="Seconds to allow the engine import pass.",
    ),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_IMPORT_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Ensure assets are imported into the project cache (clean-worktree loading).

    A clean worktree has the sources and their committed .import sidecars but
    not the gitignored .godot/ cache, so a one-shot run's preload() of e.g. a
    PNG fails with "no recognized resource loader" (GDA-DF-010). This command
    reads each requested asset's evidence state as the engine's own reimport
    test reads its artifacts (`cached` / `missing` / `stale` / `invalid`) and,
    only when a request is missing or stale, runs the engine's import pass —
    which is PROJECT-WIDE, the engine's one scriptable import primitive; an
    invalid request settles `failed` without a pass (the engine skips failed
    imports and parse errors; gda conservatively skips unsupported receipt
    syntax — delete the sidecar to retry). It then reports
    every file the pass created, classified against the cache root
    (cache-owned under .godot/ vs source-adjacent, e.g. .import and .uid
    sidecars). `--dry-run` reports the states and the decidable predictions
    (including `pass_will_also_import`) and writes nothing. Plain `gda script run` never triggers an import pass. The pass
    executes engine importer code over project content (the Trusted project
    assumption, ADR-0009).
    """
    params = params_or_bad_parameter(
        ResourceImportParams, assets=assets, dry_run=dry_run, timeout=timeout
    )
    dispatch_recipe(
        RESOURCE_IMPORT_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``resource`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="resource")
