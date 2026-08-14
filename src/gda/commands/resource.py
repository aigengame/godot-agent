"""The ``resource`` command group: Godot resource files (.tres) as the domain object.

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderers, its ``HeadlessCommand`` descriptors
(ADR-0023), and its Typer command bodies, and mounts them on the root app
through :func:`register`. It imports the shared machinery downward — the
dispatch tail (``gda.dispatch``), the descriptor machinery (``gda.headless``),
the cross-command contract core (``gda.models``, for the shared
:class:`~gda.models.NodeProperty` shape) and the shared render helpers
(``gda.render``) — and is imported by nothing but the composition root
(``gda.cli``).

:class:`~gda.models.ResourceReference` is NOT this group's model: it is the
``project find-references`` result shape, so it stays in the shared core
(ADR-0040 §4) rather than moving here on the strength of its name.
"""

from typing import Any, Optional

import typer
from pydantic import BaseModel, Field

from gda.dispatch import dispatch_domain
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.models import (
    NodeProperty,
    NormalizedPath,
    OBJECT_SET_ECHO_DESC,
    projected_value_schema_extra,
)
from gda.render import format_value


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
    created_dirs: list[str] = Field(
        description=(
            "Parent directories created before saving, from outermost to innermost."
        )
    )


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
    header = f"{got.path} ({got.type})"
    lines = [
        f"  {prop.name} ({prop.type}) = {format_value(prop.value)}"
        for prop in got.properties
    ]
    return "\n".join([header, *lines])


def render_resource_set(was_set: "ResourceSetResult") -> str:
    """Render a set property as ``set <path>.<property> (<type>) = <value>``."""
    return (
        f"set {was_set.path}.{was_set.property} ({was_set.type}) = "
        f"{format_value(was_set.value)}"
    )


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


def register(root: typer.Typer) -> None:
    """Mount the ``resource`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="resource")
