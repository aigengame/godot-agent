"""The ``node`` command group: nodes WITHIN a scene file (.tscn).

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderers, its ``HeadlessCommand`` descriptors
(ADR-0023), and its Typer command bodies, and mounts them on the root app
through :func:`register`. Besides the shared machinery it imports downward, it
takes the ONE sanctioned sibling edge of ADR-0040 §5 — ``gda.commands.scene``
for ``SceneNode`` (the tree shape ``ListedNode`` extends) and
``derive_scene_root_name`` (the filename-stem default an ``--instance``
addition reuses). The edge is one-way: ``scene`` never imports ``node``.
"""

from typing import Any, Optional

import typer
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from gda.commands.scene import SceneNode, derive_scene_root_name
from gda.dispatch import dispatch_domain, params_or_bad_parameter
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
from gda.render import format_value, render_node_tree


class NodeAddParams(BaseModel):
    """The operation params of ``gda node add`` (issue #53; instancing #399).

    ``path`` is the ``.tscn`` scene file to mutate. ``parent`` addresses the
    parent node by node path. Exactly one of ``type``/``instance`` selects what
    is added: ``type`` is resolved first as a built-in Godot node class, then
    as a ``class_name`` registered in the project's global class list;
    ``instance`` composes an existing scene as an instanced child (#399).
    ``name`` is explicit so the operation never silently derives a name Godot
    later sanitizes; when the CLI caller omits ``--name``, it uses the type
    name, or the instanced scene's filename stem.
    """

    path: NormalizedPath = Field(description="The .tscn scene file to mutate.")
    parent: str = Field(
        default=".",
        description=(
            "Parent node path, relative to the scene root: '.' addresses the "
            "root itself, 'Player/Arm' a nested node."
        ),
    )
    type: str | None = Field(
        default=None,
        description=(
            "Node type to add: a Godot node class (e.g. Sprite2D), or a "
            "class_name registered in the project's global class list. "
            "Exactly one of type/instance must be given."
        ),
    )
    instance: NormalizedPath | None = Field(
        default=None,
        description=(
            "Scene file to add as an instanced child (e.g. res://hud.tscn) — "
            "composes the scene under the parent, serialized as an "
            "instance=ExtResource(...) entry. Exactly one of type/instance "
            "must be given."
        ),
    )
    name: str | None = Field(
        default=None,
        description=(
            "Name for the new node. If omitted, the type name (or the "
            "instanced scene's filename stem) is used. Must be non-empty and "
            "must not contain '.', ':', '@', '/', '\"', or '%'."
        ),
    )
    index: int | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Optional 0-based sibling index under the parent where the new "
            "child is inserted. Omit to append. Valid runtime range is "
            "0..child_count before insertion, so child_count appends."
        ),
    )

    @model_validator(mode="after")
    def _exactly_one_mode_and_default_name(self) -> "NodeAddParams":
        # Exactly one of type/instance selects what is added (#399). Enforced
        # model-side (ADR-0015) so the argv and --params-json paths agree: the
        # argv path converts the ValueError to a usage error, --params-json
        # surfaces it as a structured invalid_params.
        if self.type is None and self.instance is None:
            raise ValueError(
                "node add needs exactly one of --type or --instance "
                "(neither was given)."
            )
        if self.type is not None and self.instance is not None:
            raise ValueError(
                "--type and --instance are mutually exclusive; pass exactly one."
            )
        # Derive the default node name model-side too, so the CLI never
        # derives it: the type name, or the instanced scene's filename stem.
        if self.name is None:
            self.name = (
                self.type
                if self.type is not None
                else derive_scene_root_name(self.instance or "")
            )
        return self


class NodeAddResult(BaseModel):
    """The result of ``gda node add``: the created node and where it landed.

    ``path`` is the created node's node path relative to the scene root, so an
    agent can address the node in follow-up node commands without re-listing.
    """

    scene_path: str
    path: str = Field(
        description="The created node's node path, relative to the scene root."
    )
    name: str
    type: str = Field(
        description=(
            "The created node's engine class (e.g. Node2D) — for a class_name "
            "addition, the script's base class."
        )
    )
    script_class: str | None = Field(
        default=None,
        description=(
            "The class_name of the script attached to the created node, when "
            "the requested type resolved to a script class; null for a "
            "built-in type."
        ),
    )
    instance: str | None = Field(
        default=None,
        description=(
            "The res:// path of the scene this node instances, when the node "
            "was added via --instance (#399); null for a type addition. For "
            "an instance, `type` reports the instanced scene's root class."
        ),
    )


class ListedNode(SceneNode):
    """One node of ``gda node list``'s tree: name, type, node path, children.

    Like ``SceneNode`` but each node also carries its node path relative to the
    scene root ('.' for the root itself) — the address an agent feeds back into
    other node commands (e.g. ``node add --parent``).
    """

    # Subclasses ``SceneNode`` so the recursive tree shape (name/type/children)
    # has one source of truth; ``children`` is re-declared as ``list[ListedNode]``
    # — not the inherited ``list[SceneNode]`` — so a listed node's children are
    # themselves listed nodes (carrying ``path``), keeping the tree self-recursive
    # on ``ListedNode``. The ``--json``/``--schema`` output stays SEMANTICALLY
    # unchanged (same fields, same ``required``, same recursion) but is NOT byte-
    # identical: inheriting name/type/children and appending ``path`` orders the
    # properties name,type,children,path rather than the prior name,type,path,
    # children. JSON property order is insignificant — consumers parse by key and
    # the ``--schema`` → MCP generation is order-insensitive — so this is a safe
    # trade for the single-source-of-truth tree shape.
    path: str = Field(
        description=(
            "The node's node path relative to the scene root: '.' for the root "
            "itself, 'Player/Arm' for a nested node."
        )
    )
    children: list["ListedNode"] = []


class NodeListParams(BaseModel):
    """The operation params of ``gda node list``: the ``.tscn`` file to read."""

    path: NormalizedPath = Field(description="The .tscn scene file to read.")


class NodeListResult(BaseModel):
    """The result of ``gda node list``: the scene's node tree with node paths."""

    scene_path: str
    root: ListedNode


class NodeGetParams(BaseModel):
    """The operation params of ``gda node get`` (issue #55).

    ``path`` is the ``.tscn`` scene file to read; ``node`` addresses the node by
    its node path relative to the scene root ('.' is the root itself).
    """

    path: NormalizedPath = Field(description="The .tscn scene file to read.")
    node: str = Field(
        description=(
            "Node path relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        )
    )


class NodeGetResult(BaseModel):
    """The result of ``gda node get``: a node's properties as typed JSON (issue #55).

    Echoes the addressed node (``path``/``name``/``type``) and its storage
    properties — the ones that serialize into the ``.tscn`` — each as a typed
    :class:`NodeProperty`, so an agent reads a node's state without parsing the
    scene file and can feed any property straight back into ``node set``.
    """

    scene_path: str
    path: str = Field(
        description="The addressed node's node path, relative to the scene root."
    )
    name: str
    type: str = Field(description="The node's engine class (e.g. Sprite2D).")
    properties: list[NodeProperty]


class NodeSetParams(BaseModel):
    """The operation params of ``gda node set`` (issue #55).

    ``path`` is the ``.tscn`` scene file to mutate; ``node`` addresses the node
    by node path relative to the scene root. ``property`` names the property to
    set; ``value`` is the CLI string value, coerced to the property's declared
    Godot type by the operation before the scene is re-packed and saved.
    """

    path: NormalizedPath = Field(description="The .tscn scene file to mutate.")
    node: str = Field(
        description=(
            "Node path relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        )
    )
    property: str = Field(description="The property to set (e.g. position, visible).")
    value: str = Field(
        description=(
            "The value to set, as a string. The operation coerces it to the "
            "property's declared Godot type (see the command catalog's "
            "'Property value coercion'). For Dictionary/Array JSON values, JSON "
            "integer literals stay int and JSON float literals stay float; typed "
            "containers assign entries through their declared container type. An "
            "uncoercible value is a clean error."
        )
    )


class NodeSetResult(BaseModel):
    """The result of ``gda node set``: the one property it set (issue #55).

    Echoes the addressed node's ``path``, the ``property`` set, the declared
    ``type`` the CLI value was coerced to, and the coerced ``value`` as JSON —
    the projection ``node get`` reports, so a ``set`` round-trips through a
    ``get`` without re-reading the file.
    """

    scene_path: str
    path: str = Field(
        description="The addressed node's node path, relative to the scene root."
    )
    property: str
    type: str = Field(
        description="The property's declared Godot type the value was coerced to."
    )
    value: Any = Field(
        description=(
            "The coerced value as JSON, as the node now holds it. "
            + OBJECT_SET_ECHO_DESC
        ),
        json_schema_extra=projected_value_schema_extra,
    )


class NodeRemoveParams(BaseModel):
    """The operation params of ``gda node remove`` (issue #56).

    ``path`` is the ``.tscn`` scene file to mutate; ``node`` addresses the node
    to delete by its node path relative to the scene root. The scene root ('.')
    has no parent to be removed from, so removing it is refused rather than
    emptying the scene.
    """

    path: NormalizedPath = Field(description="The .tscn scene file to mutate.")
    node: str = Field(
        description=(
            "Node path relative to the scene root: 'Player/Arm' a nested node. "
            "The root ('.') cannot be removed."
        )
    )


class NodeRemoveResult(BaseModel):
    """The result of ``gda node remove``: the node and subtree it deleted (issue #56).

    Echoes the removed node's ``path`` (its node path relative to the scene
    root), ``name``, and ``type``, captured off the tree before the re-save —
    so the result names the content removed, not just the path.
    """

    scene_path: str
    path: str = Field(
        description="The removed node's node path, relative to the scene root."
    )
    name: str
    type: str = Field(description="The removed node's engine class (e.g. Sprite2D).")


class NodeDuplicateParams(BaseModel):
    """The operation params of ``gda node duplicate`` (issue #56).

    ``path`` is the ``.tscn`` scene file to mutate; ``node`` addresses the node
    to copy by its node path relative to the scene root. The copy (and its whole
    subtree) lands under the source node's own parent with a fresh,
    non-colliding name. The scene root ('.') has no parent to host a sibling
    copy, so duplicating it is refused.
    """

    path: NormalizedPath = Field(description="The .tscn scene file to mutate.")
    node: str = Field(
        description=(
            "Node path relative to the scene root: 'Player/Arm' a nested node. "
            "The copy lands under this node's own parent; the root ('.') cannot "
            "be duplicated."
        )
    )


class NodeDuplicateResult(BaseModel):
    """The result of ``gda node duplicate``: the new copy and where it landed (issue #56).

    Echoes the ``source_path`` it copied and the new copy's ``path`` (its node
    path relative to the scene root), ``name``, and ``type`` — the fresh,
    non-colliding name the operation assigned — so an agent can address the
    duplicate in follow-up node commands without re-listing.
    """

    scene_path: str
    source_path: str = Field(
        description="The copied node's node path, relative to the scene root."
    )
    path: str = Field(
        description="The new copy's node path, relative to the scene root."
    )
    name: str = Field(description="The fresh, non-colliding name assigned to the copy.")
    type: str = Field(description="The copy's engine class (e.g. Sprite2D).")


class NodeMoveParams(BaseModel):
    """The operation params of ``gda node move`` (issue #56).

    ``path`` is the ``.tscn`` scene file to mutate; ``node`` addresses the node
    to reparent by its node path relative to the scene root; ``to`` addresses the
    new parent the same way. The move is refused when the target is invalid (no
    such parent, or a name collision at the destination) or **cyclic** — moving a
    node under itself or one of its own descendants would detach the subtree from
    the scene. The scene root ('.') has no parent to be reparented out of.
    """

    path: NormalizedPath = Field(description="The .tscn scene file to mutate.")
    node: str = Field(
        description=(
            "Node path of the node to reparent, relative to the scene root: "
            "'Player/Arm' a nested node. The root ('.') cannot be moved."
        )
    )
    to: str = Field(
        description=(
            "Node path of the new parent, relative to the scene root: '.' "
            "addresses the root itself, 'Enemies' a nested node. Must not be the "
            "moved node itself or one of its descendants (a cyclic target)."
        )
    )
    index: int | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Optional final 0-based sibling index under the destination parent. "
            "Omit to preserve existing behavior: same-parent move is a no-op, "
            "and cross-parent move appends. With the same parent, valid runtime "
            "range is 0..child_count-1; with a different parent, 0..target_child_count "
            "before the move, so target_child_count appends."
        ),
    )


class NodeMoveResult(BaseModel):
    """The result of ``gda node move``: the reparented node's new home (issue #56).

    Echoes the ``source_path`` it moved, the ``new_parent`` it landed under, and
    the node's new ``path`` (its node path relative to the scene root after the
    move), ``name``, and ``type`` — so an agent can address the moved node in
    follow-up node commands without re-listing.
    """

    scene_path: str
    source_path: str = Field(
        description="The moved node's original node path, relative to the scene root."
    )
    new_parent: str = Field(
        description="The new parent's node path, relative to the scene root."
    )
    path: str = Field(
        description="The moved node's new node path, relative to the scene root."
    )
    name: str
    type: str = Field(description="The moved node's engine class (e.g. Sprite2D).")


# A signal→method connection's four parts (issue #57): a source node's signal
# wired to a target node's method, the shape of a ``.tscn`` ``[connection]``.
# ``from`` is the source node's node path and ``to`` the target's, both relative
# to the scene root — the same node-path addressing as the rest of the node
# group (#53/#66). ``from`` is a Python keyword, so the source field is named
# ``from_node`` and aliased to the wire key ``from``, matching the ``[connection]``
# key the engine writes; populate-by-name lets the CLI build the model with the
# Python name while ``--json``/``--schema`` keep the ``from`` wire key.
_FROM_FIELD = Field(
    alias="from",
    description=(
        "Source node path, relative to the scene root: '.' addresses the root "
        "itself, 'Player/Arm' a nested node."
    ),
)
_SIGNAL_FIELD = Field(description="The signal name on the source node.")
_TO_FIELD = Field(
    description=(
        "Target node path, relative to the scene root: '.' addresses the root "
        "itself, 'Player/Arm' a nested node."
    )
)
_METHOD_FIELD = Field(description="The method name on the target node.")


class NodeConnectSignalParams(BaseModel):
    """The operation params of ``gda node connect-signal`` (issue #57).

    Records a connection from a source node's signal to a target node's method,
    persisted into the ``.tscn`` as a ``[connection]``. As a scene mutation it
    instantiates the scene (the same trust boundary as ``node set``, ADR-0009).
    ``path`` is the scene file; ``from``/``signal`` address the source node's
    signal, ``to``/``method`` the target node's method, by the node group's
    node-path addressing (#53/#66).

    Contract (issue #57's design decision): the SIGNAL must exist on the source
    node — a typo or wrong node is a clean ``signal_not_found`` error. The target
    METHOD need NOT exist: a ``.tscn`` ``[connection]`` is persisted data, and
    Godot's own editor lets you wire a signal to a not-yet-written method, so the
    handler can be authored after the wiring — a dangling method is allowed.
    """

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    path: NormalizedPath = Field(description="The .tscn scene file to mutate.")
    from_node: str = _FROM_FIELD
    signal: str = _SIGNAL_FIELD
    to: str = _TO_FIELD
    method: str = _METHOD_FIELD


class NodeConnectSignalResult(BaseModel):
    """The result of ``gda node connect-signal``: the connection it recorded (issue #57).

    Echoes the ``scene_path`` and the four parts of the connection — source node
    (``from``), ``signal``, target node (``to``), ``method`` — verifiable by
    reading the saved scene back: the ``[connection]`` now appears in the file.
    """

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    scene_path: str
    from_node: str = _FROM_FIELD
    signal: str = _SIGNAL_FIELD
    to: str = _TO_FIELD
    method: str = _METHOD_FIELD


class NodeDisconnectSignalParams(BaseModel):
    """The operation params of ``gda node disconnect-signal`` (issue #57).

    Removes an existing signal→method connection from the ``.tscn``. As a scene
    mutation it instantiates the scene (the same trust boundary as ``node set``,
    ADR-0009). The four parts address the connection exactly as ``connect-signal``
    recorded it; a connection that does not exist is a clean ``connection_not_found``
    error rather than a silent no-op.
    """

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    path: NormalizedPath = Field(description="The .tscn scene file to mutate.")
    from_node: str = _FROM_FIELD
    signal: str = _SIGNAL_FIELD
    to: str = _TO_FIELD
    method: str = _METHOD_FIELD


class NodeDisconnectSignalResult(BaseModel):
    """The result of ``gda node disconnect-signal``: the connection it removed (issue #57).

    Echoes the ``scene_path`` and the four parts of the removed connection — the
    same shape as ``connect-signal``'s result — verifiable by reading the saved
    scene back: the ``[connection]`` is gone from the file.
    """

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    scene_path: str
    from_node: str = _FROM_FIELD
    signal: str = _SIGNAL_FIELD
    to: str = _TO_FIELD
    method: str = _METHOD_FIELD


def render_node_add(added: "NodeAddResult") -> str:
    """Render an added node as ``added <path> (<type>) to <scene>``.

    A composition (#399) names its source too:
    ``added <path> (<type>, instance of <src>) to <scene>``.
    """
    what = added.type
    if added.instance is not None:
        what = f"{added.type}, instance of {added.instance}"
    return f"added {added.path} ({what}) to {added.scene_path}"


def render_node_list(listed: "NodeListResult") -> str:
    """Render a listed scene's node tree (with node paths)."""
    return render_node_tree(listed.root)


def render_node_properties(got: "NodeGetResult") -> str:
    """Render a node's properties as ``name (Type) = value`` lines for humans."""
    header = f"{got.path} ({got.type})"
    lines = [
        f"  {prop.name} ({prop.type}) = {format_value(prop.value)}"
        for prop in got.properties
    ]
    return "\n".join([header, *lines])


def render_node_set(was_set: "NodeSetResult") -> str:
    """Render a set property as ``set <path>.<prop> (<type>) = <value>``."""
    return (
        f"set {was_set.path}.{was_set.property} ({was_set.type}) = "
        f"{format_value(was_set.value)}"
    )


def render_node_remove(removed: "NodeRemoveResult") -> str:
    """Render a removed node as ``removed <path> (<type>) from <scene>``."""
    return f"removed {removed.path} ({removed.type}) from {removed.scene_path}"


def render_node_duplicate(duplicated: "NodeDuplicateResult") -> str:
    """Render a duplicated node as ``duplicated <source> to <path> (<type>)``."""
    return (
        f"duplicated {duplicated.source_path} to {duplicated.path} ({duplicated.type})"
    )


def render_node_move(moved: "NodeMoveResult") -> str:
    """Render a moved node as ``moved <source> to <path> (<type>)``."""
    return f"moved {moved.source_path} to {moved.path} ({moved.type})"


def render_node_connect_signal(connected: "NodeConnectSignalResult") -> str:
    """Render a wired connection as ``connected <from>.<signal> -> <to>.<method>``."""
    return (
        f"connected {connected.from_node}.{connected.signal} -> "
        f"{connected.to}.{connected.method}"
    )


def render_node_disconnect_signal(disconnected: "NodeDisconnectSignalResult") -> str:
    """Render an unwired connection as ``disconnected <from>.<signal> -> <to>.<method>``."""
    return (
        f"disconnected {disconnected.from_node}.{disconnected.signal} -> "
        f"{disconnected.to}.{disconnected.method}"
    )


NODE_ADD_COMMAND: HeadlessCommand[NodeAddResult] = HeadlessCommand(
    operation="node-add",
    input_model=NodeAddParams,
    output_model=NodeAddResult,
    render=render_node_add,
)

NODE_LIST_COMMAND: HeadlessCommand[NodeListResult] = HeadlessCommand(
    operation="node-list",
    input_model=NodeListParams,
    output_model=NodeListResult,
    render=render_node_list,
)

NODE_GET_COMMAND: HeadlessCommand[NodeGetResult] = HeadlessCommand(
    operation="node-get",
    input_model=NodeGetParams,
    output_model=NodeGetResult,
    render=render_node_properties,
)

NODE_SET_COMMAND: HeadlessCommand[NodeSetResult] = HeadlessCommand(
    operation="node-set",
    input_model=NodeSetParams,
    output_model=NodeSetResult,
    render=render_node_set,
)

NODE_REMOVE_COMMAND: HeadlessCommand[NodeRemoveResult] = HeadlessCommand(
    operation="node-remove",
    input_model=NodeRemoveParams,
    output_model=NodeRemoveResult,
    render=render_node_remove,
)

NODE_DUPLICATE_COMMAND: HeadlessCommand[NodeDuplicateResult] = HeadlessCommand(
    operation="node-duplicate",
    input_model=NodeDuplicateParams,
    output_model=NodeDuplicateResult,
    render=render_node_duplicate,
)

NODE_MOVE_COMMAND: HeadlessCommand[NodeMoveResult] = HeadlessCommand(
    operation="node-move",
    input_model=NodeMoveParams,
    output_model=NodeMoveResult,
    render=render_node_move,
)

NODE_CONNECT_SIGNAL_COMMAND: HeadlessCommand[NodeConnectSignalResult] = HeadlessCommand(
    operation="node-connect-signal",
    input_model=NodeConnectSignalParams,
    output_model=NodeConnectSignalResult,
    render=render_node_connect_signal,
)

NODE_DISCONNECT_SIGNAL_COMMAND: HeadlessCommand[NodeDisconnectSignalResult] = (
    HeadlessCommand(
        operation="node-disconnect-signal",
        input_model=NodeDisconnectSignalParams,
        output_model=NodeDisconnectSignalResult,
        render=render_node_disconnect_signal,
    )
)

# The node command group (issue #53): commands acting on nodes WITHIN a scene
# file (load → locate → mutate → pack → save), so they stay headless.
_app = typer.Typer(
    help="Act on nodes within a scene file (.tscn).", no_args_is_help=True
)


@_app.command(cls=NODE_ADD_COMMAND.command_class())
def add(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node_type: Optional[str] = typer.Option(
        None,
        "--type",
        help=(
            "Node type to add: a Godot node class (e.g. Sprite2D), or a "
            "class_name registered in the project's global class list. "
            "Exactly one of --type/--instance must be given."
        ),
    ),
    instance: Optional[str] = typer.Option(
        None,
        "--instance",
        help=(
            "Scene file to add as an instanced child (e.g. res://hud.tscn). "
            "Exactly one of --type/--instance must be given."
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
        help=(
            "Name for the new node. Defaults to the type name, or the "
            "instanced scene's filename stem."
        ),
    ),
    index: Optional[int] = typer.Option(
        None,
        "--index",
        help=(
            "0-based sibling index under the parent where the child is inserted. "
            "Omit to append; child_count appends."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_ADD_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Add a node to a scene file under the given parent node path."""
    # The exactly-one-of --type/--instance rule lives on the model (ADR-0015);
    # the argv path keeps usage-error ergonomics (exit 2), --params-json
    # surfaces the same rule as a structured invalid_params.
    params = params_or_bad_parameter(
        NodeAddParams,
        path=path,
        parent=parent,
        type=node_type,
        instance=instance,
        name=name,
        index=index,
    )
    dispatch_domain(
        NODE_ADD_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="list", cls=NODE_LIST_COMMAND.command_class())
def list_nodes(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = json_option(),
    schema: bool = NODE_LIST_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """List a scene's node tree with each node's path relative to the root."""
    dispatch_domain(
        NODE_LIST_COMMAND,
        NodeListParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(cls=NODE_GET_COMMAND.command_class())
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
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a node's properties (by node path) as typed JSON."""
    dispatch_domain(
        NODE_GET_COMMAND,
        NodeGetParams(path=path, node=node),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="set", cls=NODE_SET_COMMAND.command_class())
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
            "Godot type: Vector2/Vector2i/Color take comma-separated components "
            '(e.g. "48,72", "0.2,0.6,1,1"), and a property expecting a Resource '
            "(sub)class takes a res:// path to an existing Resource of that class. "
            "An uncoercible value is a clean error."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_SET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Set a node property, coercing the value to its declared Godot type."""
    dispatch_domain(
        NODE_SET_COMMAND,
        NodeSetParams(path=path, node=node, property=property, value=value),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="remove", cls=NODE_REMOVE_COMMAND.command_class())
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
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Remove a node (and its subtree) from a scene file by node path."""
    dispatch_domain(
        NODE_REMOVE_COMMAND,
        NodeRemoveParams(path=path, node=node),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="duplicate", cls=NODE_DUPLICATE_COMMAND.command_class())
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
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Duplicate a node (and its subtree) under its parent with a fresh name."""
    dispatch_domain(
        NODE_DUPLICATE_COMMAND,
        NodeDuplicateParams(path=path, node=node),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="move", cls=NODE_MOVE_COMMAND.command_class())
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
    index: Optional[int] = typer.Option(
        None,
        "--index",
        help=(
            "Final 0-based sibling index under --to. Omit to append on "
            "cross-parent moves and no-op on same-parent moves."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_MOVE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Reparent a node (and its subtree) under a new parent node path."""
    dispatch_domain(
        NODE_MOVE_COMMAND,
        NodeMoveParams(path=path, node=node, to=to, index=index),
        json_output=json_output,
        godot=godot,
        project=project,
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


@_app.command(name="connect-signal", cls=NODE_CONNECT_SIGNAL_COMMAND.command_class())
def connect_signal(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    from_node: str = _from_option(),
    signal: str = _signal_option(),
    to: str = _to_option(),
    method: str = _method_option(),
    json_output: bool = json_option(),
    schema: bool = NODE_CONNECT_SIGNAL_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Wire a source node's signal to a target node's method, persisted in the scene."""
    dispatch_domain(
        NODE_CONNECT_SIGNAL_COMMAND,
        NodeConnectSignalParams(
            path=path,
            from_node=from_node,
            signal=signal,
            to=to,
            method=method,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(
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
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Unwire an existing signal→method connection; errors if it is absent."""
    dispatch_domain(
        NODE_DISCONNECT_SIGNAL_COMMAND,
        NodeDisconnectSignalParams(
            path=path,
            from_node=from_node,
            signal=signal,
            to=to,
            method=method,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``node`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="node")
