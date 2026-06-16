"""Typed result models (ADR-0004).

Each command's result is carried by a Pydantic model rather than an ad-hoc
dict, so the same model both serializes the ``--json`` output now and produces
the ``--schema`` document later (``model_json_schema()``) without
hand-maintaining the contract twice.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorCategory(str, Enum):
    """The four coarse buckets a ``gda`` operation can fail into (issue #3).

    This is the coarse axis; each category fans out to one or more finer,
    stable ``GdaError.code`` values (e.g. ENVIRONMENT → ``binary_not_found`` /
    ``launch_timeout``; OPERATION → ``operation_failed`` / ``engine_crashed``).
    See ``gda.errors.classify_run`` for the category→code decision tree.

    ENVIRONMENT covers everything before the operation produces a result — the
    binary not launching, or launching and hanging past the timeout. VERSION is
    a launched engine below the supported minimum (ADR-0003). OPERATION is a
    launched engine that failed to deliver a result (the operation reported an
    error, or the engine crashed). PARSE is a violation of the structured-output
    contract (ADR-0002): a missing/malformed sentinel or a wrong-shape payload.
    """

    ENVIRONMENT = "environment"
    VERSION = "version"
    OPERATION = "operation"
    PARSE = "parse"


class GdaError(BaseModel):
    """A structured, stable failure of a ``gda`` operation (issue #3).

    Emitted as ``{"error": <this>}`` on stdout so an agent reacts to failure
    modes programmatically without parsing prose. ``category`` is the coarse,
    process-exit-code-aligned bucket; ``code`` is the finer, stable identifier;
    ``diagnostics`` carries the engine/script stderr surfaced per ADR-0002.
    """

    category: ErrorCategory
    code: str
    message: str
    diagnostics: str = ""


class GdaErrorEnvelope(BaseModel):
    """The ``{"error": {...}}`` wrapper that discriminates a failure from a result.

    The success result (``EngineVersion``) is emitted bare, so the presence of
    the top-level ``error`` key is the stable success/failure discriminator.
    """

    error: GdaError


class OperationError(BaseModel):
    """The minimal operation-reported failure payload (ADR-0002).

    Headless operations only report the part they own: a registered operation
    error ``code`` and a human-readable ``message``. The Python classifier adds
    category and diagnostics when it builds the public ``GdaError``.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class OperationErrorEnvelope(BaseModel):
    """The sentinel payload shape for a headless operation failure."""

    model_config = ConfigDict(extra="forbid")

    error: OperationError


class InfoParams(BaseModel):
    """The operation params of ``gda info`` — none (ADR-0004).

    ``gda info`` takes no operation params, so its ``input`` schema is trivially
    empty; this is expected, not an error. The model still exists so the
    ``--schema`` document is derived model-side rather than hand-written.
    """


class CommandSchema(BaseModel):
    """A command's self-description: its ``input``, ``output`` and ``error`` JSON Schemas (ADR-0004).

    ``--schema`` emits this. ``input`` and ``output`` are derived from the
    command's own typed models via :meth:`of`, so the contract is never
    hand-maintained: ``input`` from the params model, ``output`` from the same
    *success* result model that backs ``--json``. ``error`` is the **uniform**
    failure-envelope schema, identical for every command, produced from the one
    shared :class:`GdaErrorEnvelope` model — zero per-command maintenance (#43).

    ``gda-mcp`` later maps ``input`` → ``inputSchema`` and ``output`` →
    ``outputSchema`` (success / structuredContent) mechanically. The ``error``
    half is kept OUT of ``output``: a non-zero-exit failure maps to MCP's
    separate ``isError`` channel, so the future adapter must not fold ``error``
    into ``outputSchema``.
    """

    input: dict[str, Any]
    output: dict[str, Any]
    error: dict[str, Any]

    @classmethod
    def of(
        cls, input_model: type[BaseModel], output_model: type[BaseModel]
    ) -> "CommandSchema":
        """Derive the contract from a command's params and result models.

        ``error`` is the shared failure-envelope schema, the same for every
        command, so it takes no per-command model argument.
        """
        return cls(
            input=input_model.model_json_schema(),
            output=output_model.model_json_schema(),
            error=GdaErrorEnvelope.model_json_schema(),
        )


class SceneCreateParams(BaseModel):
    """The operation params of ``gda scene create`` (issue #18).

    ``path`` is the target ``.tscn`` file; ``root_type`` the Godot node class
    of the new scene's root (e.g. ``Node2D``). ``root_name`` is explicit so the
    operation never silently derives a name Godot later sanitizes; when the CLI
    caller omits ``--root-name``, it derives this from the target filename
    without the final extension.
    """

    path: str
    root_type: str
    root_name: str | None = Field(
        default=None,
        description=(
            "Root node name to write. If omitted by the CLI, it is derived from "
            "the target filename without its final extension. Must be non-empty "
            "and must not contain '.', ':', '@', '/', '\"', or '%'."
        ),
    )


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
    created_dirs: list[str] = Field(
        description=(
            "Parent directories created before saving, from outermost to innermost."
        )
    )


class SceneNode(BaseModel):
    """One node of a scene's structured tree: name, type, nested children.

    Recursive on purpose — the tree IS the contract: ``gda scene get`` reports
    arbitrarily nested scenes through this one shape.
    """

    name: str
    type: str
    children: list["SceneNode"] = []


class SceneGetParams(BaseModel):
    """The operation params of ``gda scene get``: the ``.tscn`` file to read."""

    path: str


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
    property's current value in the same JSON projection ``node get`` reports — a
    scalar for a scalar type, a list for a packed type (Vector2 → ``[x, y]``) —
    which on a freshly-instantiated node is the export's default.
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
            "node): a scalar for a scalar type, a list for a packed type "
            "(Vector2 → [x, y], Color → [r, g, b, a])."
        )
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

    path: str


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
        description="The scene root node's type, or null if the file could not be loaded as a scene.",
    )


class SceneListResult(BaseModel):
    """The result of ``gda scene list``: the project's enumerated ``.tscn`` scenes.

    An empty project is a valid, empty listing — ``scenes == []`` — not a
    failure.
    """

    scenes: list[ListedScene]


class SceneDeleteParams(BaseModel):
    """The operation params of ``gda scene delete``: the ``.tscn`` file to remove."""

    path: str


class SceneDeleteResult(BaseModel):
    """The result of ``gda scene delete``: what was removed.

    Echoes the deleted scene's path and its root node's name/type (read from the
    scene's stored state before deletion), so the result names the content
    removed, not just the file path.
    """

    path: str
    root_name: str
    root_type: str


class NodeAddParams(BaseModel):
    """The operation params of ``gda node add`` (issue #53).

    ``path`` is the ``.tscn`` scene file to mutate. ``parent`` addresses the
    parent node by node path. ``type`` is resolved first as a built-in Godot
    node class, then as a ``class_name`` registered in the project's global
    class list. ``name`` is explicit so the operation never silently derives a
    name Godot later sanitizes; when the CLI caller omits ``--name``, it uses
    the type name.
    """

    path: str
    parent: str = Field(
        default=".",
        description=(
            "Parent node path, relative to the scene root: '.' addresses the "
            "root itself, 'Player/Arm' a nested node."
        ),
    )
    type: str
    name: str | None = Field(
        default=None,
        description=(
            "Name for the new node. If omitted by the CLI, the type name is "
            "used. Must be non-empty and must not contain '.', ':', '@', '/', "
            "'\"', or '%'."
        ),
    )


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

    path: str


class NodeListResult(BaseModel):
    """The result of ``gda node list``: the scene's node tree with node paths."""

    scene_path: str
    root: ListedNode


class NodeProperty(BaseModel):
    """One of a node's properties as ``gda node get`` reports it (issue #55).

    ``type`` is the property's declared Godot type name (``int``, ``Vector2``,
    ``Color``, …). ``value`` is the property's value in its JSON projection —
    left as arbitrary JSON so every Godot type is carried uniformly through one
    field: a scalar stays a scalar, a Vector2 becomes ``[x, y]``, a Color
    ``[r, g, b, a]`` — the same projection ``node set`` accepts back.
    """

    name: str
    type: str = Field(
        description="The property's declared Godot type name (e.g. int, Vector2, Color)."
    )
    value: Any = Field(
        description=(
            "The property's value as JSON: a scalar for a scalar type, a list "
            "for a packed type (Vector2 → [x, y], Color → [r, g, b, a])."
        )
    )


class NodeGetParams(BaseModel):
    """The operation params of ``gda node get`` (issue #55).

    ``path`` is the ``.tscn`` scene file to read; ``node`` addresses the node by
    its node path relative to the scene root ('.' is the root itself).
    """

    path: str
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

    path: str
    node: str = Field(
        description=(
            "Node path relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        )
    )
    property: str
    value: str = Field(
        description=(
            "The value to set, as a string. The operation coerces it to the "
            "property's declared Godot type (see the command catalog's "
            "'Property value coercion'); an uncoercible value is a clean error."
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
    type: str = Field(description="The property's declared Godot type the value was coerced to.")
    value: Any = Field(
        description="The coerced value as JSON, as the node now holds it."
    )


class NodeRemoveParams(BaseModel):
    """The operation params of ``gda node remove`` (issue #56).

    ``path`` is the ``.tscn`` scene file to mutate; ``node`` addresses the node
    to delete by its node path relative to the scene root. The scene root ('.')
    has no parent to be removed from, so removing it is refused rather than
    emptying the scene.
    """

    path: str
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

    path: str
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
    name: str = Field(
        description="The fresh, non-colliding name assigned to the copy."
    )
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

    path: str
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

    path: str = Field(description="The .tscn scene file to mutate.")
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

    path: str = Field(description="The .tscn scene file to mutate.")
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


class ScriptCreateParams(BaseModel):
    """The operation params of ``gda script create`` (issue #110).

    ``path`` is the target ``.gd`` script file, addressed by its ``res://`` or
    filesystem path (script-file addressing — by file path, not by
    ``class_name``). ``content`` supplies verbatim source; when omitted, the
    operation writes a minimal built-in template extending ``extends_type``.
    ``content`` and ``extends_type`` are mutually exclusive at the CLI: verbatim
    content is not templated, so a base class would have nowhere to go.
    """

    path: str
    content: str | None = Field(
        default=None,
        description=(
            "Verbatim script source to write. When omitted, a minimal built-in "
            "template extending 'extends_type' is written instead. Mutually "
            "exclusive with the template's base class."
        ),
    )
    extends_type: str | None = Field(
        default=None,
        description=(
            "Base class for the built-in template's 'extends' line (e.g. Node, "
            "Node2D). Ignored when 'content' is supplied; defaults to 'Node' "
            "when neither is given."
        ),
    )


class ScriptCreateResult(BaseModel):
    """The result of ``gda script create``: what was written where (issue #110).

    Echoes the saved ``path`` and the ``class_name``/``extends`` the written
    source declares, so an agent can assert the effect without a second call.
    ``created_dirs`` lists parent directories the operation created before
    saving, from outermost to innermost. The ``class_name``/``extends`` are
    parsed from the written source.
    """

    path: str
    class_name: str | None = Field(
        default=None,
        description=(
            "The class_name the written script declares, or null when it "
            "declares none."
        ),
    )
    extends: str | None = Field(
        default=None,
        description=(
            "The base class the written script extends, or null when it "
            "declares none."
        ),
    )
    created_dirs: list[str] = Field(
        description=(
            "Parent directories created before saving, from outermost to innermost."
        )
    )


class ScriptGetParams(BaseModel):
    """The operation params of ``gda script get``: the script file to read (issue #110).

    ``path`` addresses the ``.gd`` script by its ``res://`` or filesystem path.
    The source is read as raw text — the script is never loaded or compiled, so
    reading it can never run project code (issue #30).
    """

    path: str


class ScriptGetResult(BaseModel):
    """The result of ``gda script get``: a script's source and metadata (issue #110).

    Echoes the ``path``, the full ``source`` read as raw text, and the
    ``class_name``/``extends`` the source declares (parsed from the text).
    Carrying the source verbatim makes a ``create`` verifiable end-to-end:
    ``create`` then ``get`` returns the same source.
    """

    path: str
    source: str
    class_name: str | None = Field(
        default=None,
        description=(
            "The class_name the script declares, or null when it declares none."
        ),
    )
    extends: str | None = Field(
        default=None,
        description=(
            "The base class the script extends, or null when it declares none."
        ),
    )


class ScriptListParams(BaseModel):
    """The operation params of ``gda script list`` — none (ADR-0004).

    ``script list`` enumerates the ``.gd`` scripts in the resolved project's
    ``res://`` tree; the project is process context (``--project``), not an
    operation param (ADR-0006), so the ``input`` schema is trivially empty.
    """


class ListedScript(BaseModel):
    """One enumerated script of ``gda script list``: its path and metadata.

    ``path`` is the script's ``res://`` path — the address an agent feeds back
    into other script commands. ``class_name``/``extends`` are parsed cheaply
    from the script's raw source (no compilation, issue #30); both are null when
    the script declares neither, so the entry still names a file the listing
    found rather than dropping it.
    """

    path: str
    class_name: str | None = Field(
        default=None,
        description="The class_name the script declares, or null when it declares none.",
    )
    extends: str | None = Field(
        default=None,
        description="The base class the script extends, or null when it declares none.",
    )


class ScriptListResult(BaseModel):
    """The result of ``gda script list``: the project's enumerated ``.gd`` scripts.

    An empty project is a valid, empty listing — ``scripts == []`` — not a
    failure.
    """

    scripts: list[ListedScript]


class ScriptDeleteParams(BaseModel):
    """The operation params of ``gda script delete``: the ``.gd`` file to remove."""

    path: str


class ScriptDeleteResult(BaseModel):
    """The result of ``gda script delete``: what was removed (issue #117).

    Echoes the deleted script's ``path`` and the ``class_name``/``extends`` its
    source declared (parsed from the raw text before deletion), so the result
    names the content removed, not just the file path.
    """

    path: str
    class_name: str | None = Field(
        default=None,
        description="The class_name the deleted script declared, or null when it declared none.",
    )
    extends: str | None = Field(
        default=None,
        description="The base class the deleted script extended, or null when it declared none.",
    )


class ScriptSetMode(str, Enum):
    """The edit mode of ``gda script set``, the single source of truth (issue #133).

    The CLI resolves exactly one mode from the supplied flags (its mutual-exclusion
    check) and stamps it here, so the operation dispatches on this explicit
    discriminator instead of re-inferring the mode from which params are present —
    the inference precedence can no longer drift from the CLI's exclusivity rule.

    - ``SEARCH_REPLACE`` — ``search``/``replace``: every literal (not regex)
      occurrence of ``search`` is replaced with ``replace``.
    - ``LINE_RANGE`` — ``start_line`` (+ optional ``end_line``) with ``content``:
      the given 1-based, inclusive line span is replaced with ``content``.
    - ``FULL`` — ``content`` only: the whole file is overwritten.
    """

    SEARCH_REPLACE = "search_replace"
    LINE_RANGE = "line_range"
    FULL = "full"


class ScriptSetParams(BaseModel):
    """The operation params of ``gda script set`` (issue #118).

    Edits an existing ``.gd`` script on disk as RAW TEXT — it never compiles or
    loads the script, so editing one can never run project code (the read trust
    boundary of issue #30). ``path`` addresses the script by its ``res://`` or
    filesystem path. The remaining params carry one of three mutually-exclusive
    edit modes; the CLI resolves which one and stamps it on ``mode`` (issue #133),
    so the operation dispatches on that explicit discriminator rather than
    re-inferring it from which params are present:

    - **search-replace** (``mode = search_replace``) — ``search``/``replace`` both
      present: every literal (not regex) occurrence of ``search`` is replaced with
      ``replace``.
    - **line-range** (``mode = line_range``) — ``start_line`` (+ optional
      ``end_line``) with ``content``: the given 1-based, inclusive line span is
      replaced with ``content``.
    - **full** (``mode = full``) — only ``content`` present: the whole file is
      overwritten.
    """

    path: str
    mode: ScriptSetMode = Field(
        description=(
            "The resolved edit mode, the single source of truth the operation "
            "dispatches on (issue #133). Set by the CLI from the supplied flags, "
            "not inferred by the operation from param presence."
        ),
    )
    search: str | None = Field(
        default=None,
        description=(
            "search-replace mode: the literal substring to find (NOT a regex). "
            "Every occurrence is replaced with 'replace'. Requires 'replace'."
        ),
    )
    replace: str | None = Field(
        default=None,
        description=(
            "search-replace mode: the literal text each occurrence of 'search' "
            "is replaced with. Requires 'search'."
        ),
    )
    start_line: int | None = Field(
        default=None,
        description=(
            "line-range mode: the first line to replace, 1-based and inclusive. "
            "Lines are the parts of the source split on '\\n', so a trailing "
            "newline yields a final empty part: 'a\\nb\\n' is 3 lines "
            "(['a', 'b', '']). Valid range is 1..N where N is that part count. "
            "Requires 'content'."
        ),
    )
    end_line: int | None = Field(
        default=None,
        description=(
            "line-range mode: the last line to replace, 1-based and inclusive; "
            "defaults to 'start_line' (a single-line replace). Must satisfy "
            "start_line <= end_line <= N (the line count). Requires 'content'."
        ),
    )
    content: str | None = Field(
        default=None,
        description=(
            "The replacement text. In line-range mode it replaces the "
            "start_line..end_line span; with no 'start_line' it overwrites the "
            "entire file (full mode)."
        ),
    )


class ScriptSetResult(BaseModel):
    """The result of ``gda script set``: the edited script's metadata (issue #118).

    Echoes the saved ``path`` and the ``class_name``/``extends`` re-parsed from
    the source as written, so an edit round-trips through ``script get`` (the
    verifier) without a second call — and an agent can assert the post-edit
    metadata directly.
    """

    path: str
    class_name: str | None = Field(
        default=None,
        description=(
            "The class_name the edited source declares, or null when it "
            "declares none."
        ),
    )
    extends: str | None = Field(
        default=None,
        description=(
            "The base class the edited source extends, or null when it "
            "declares none."
        ),
    )


class ScriptAttachParams(BaseModel):
    """The operation params of ``gda script attach`` (issue #118).

    Binds a ``.gd`` script to a node inside a ``.tscn`` scene: load the scene,
    resolve the node by node path, attach the script, then re-pack and save. As a
    scene mutation it instantiates the scene (the same inherent trust boundary as
    ``node set``, ADR-0009): instantiating runs the ``_init`` of scripts already
    attached in the scene, and for a script that compiles ``set_script``
    constructs an instance of the newly-attached script, running its ``_init``
    too. ``path`` is the scene; ``script`` is the ``.gd`` to attach. The script
    must COMPILE: the headless engine silently rejects a non-compiling script
    from ``set_script`` (it cannot be persisted into the scene), so attach
    refuses one with ``script_compile_failed`` rather than report a phantom
    success — check a script with ``script validate`` first.
    """

    path: str = Field(
        description="The .tscn scene file to mutate."
    )
    node: str = Field(
        description=(
            "Node path relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        )
    )
    script: str = Field(
        description="The .gd script file to attach to the node."
    )


class ScriptAttachResult(BaseModel):
    """The result of ``gda script attach``: what was bound where (issue #118).

    Echoes the ``scene_path``, the addressed ``node``, and the attached
    ``script``, plus the script's ``class_name`` when it declares a global one —
    the result an agent asserts to confirm the binding took effect, verifiable by
    reading the saved scene back (the script now appears on the node).

    ``attach`` is a mutation verb: it OVERWRITES an existing binding rather than
    refusing it (issue #132). ``replaced_script`` makes that displacement visible
    so the overwrite is never silent — an agent reads it to detect a clobber.
    """

    scene_path: str
    node: str = Field(
        description="The node path the script was attached to, relative to the scene root."
    )
    script: str = Field(description="The .gd script that was attached.")
    class_name: str | None = Field(
        default=None,
        description=(
            "The global class_name the attached script declares, or null when "
            "it declares none."
        ),
    )
    replaced_script: str | None = Field(
        default=None,
        description=(
            "The resource_path of the script this attach DISPLACED, reported "
            "verbatim — including a built-in/embedded script's sub-resource ref "
            "(e.g. 'res://scene.tscn::GDScript_xxx'). Non-null whenever the node "
            "already carried a script (attach overwrites-and-reports, issue "
            "#132); null only when the node had no prior script."
        ),
    )


class ScriptDiagnostic(BaseModel):
    """One advisory diagnostic from ``gda script validate`` (issue #118).

    Best-effort: parsed from the engine's stderr, not from a bound API, so it may
    carry only the FIRST parse error. ``line`` is 1-based when the engine
    reported it; ``column`` is ALWAYS null on the standard Godot build — the
    engine does not expose a column for a parse error — and is kept as a field
    only so the shape is stable if a future build ever does. ``message`` is the
    engine's error text with its ``SCRIPT ERROR:`` prefix stripped.
    """

    line: int | None = Field(
        default=None,
        description="The 1-based source line the error was reported at, or null when unknown.",
    )
    column: int | None = Field(
        default=None,
        description=(
            "Always null on the standard Godot build: the engine does not "
            "expose a column for a parse error."
        ),
    )
    message: str


class ScriptValidateParams(BaseModel):
    """The operation params of ``gda script validate``: the script to check (issue #118).

    ``path`` addresses the ``.gd`` script by its ``res://`` or filesystem path.
    Unlike the other script-file ops, validate DOES compile the script (it sets
    the source on a fresh ``GDScript`` and reloads it to learn whether it parses),
    but it never instantiates the script, so it does not run instance code. Pass
    ``--project`` when the script extends a project ``class_name`` or preloads a
    project resource and so needs project context to compile.
    """

    path: str


class ScriptValidateResult(BaseModel):
    """The result of ``gda script validate``: whether the script compiles (issue #118).

    Validating an INVALID script is a SUCCESSFUL operation — the command exits 0
    and reports ``valid=false`` rather than failing. ``error_string`` carries the
    engine's one-line summary of the compile error (null when valid).
    ``diagnostics`` is a best-effort list parsed from the engine's stderr (the
    only place line/message are available); it may hold only the first error, and
    is empty when the script is valid or nothing could be parsed.
    """

    path: str
    valid: bool = Field(
        description="True when the script compiles (GDScript.reload() == OK), false otherwise."
    )
    error_string: str | None = Field(
        default=None,
        description=(
            "The engine's one-line summary of the compile failure, or null when "
            "the script is valid."
        ),
    )
    diagnostics: list[ScriptDiagnostic] = Field(
        default_factory=list,
        description=(
            "Best-effort advisory diagnostics parsed from the engine's stderr "
            "(line + message). May hold only the first error; empty when valid."
        ),
    )


class ResourceCreateParams(BaseModel):
    """The operation params of ``gda resource create`` (issue #112).

    ``path`` is the target ``.tres`` resource file, addressed by its ``res://``
    or filesystem path (resource-file addressing — by file path). ``type`` is
    the Godot resource class to instantiate and save (e.g. ``Gradient``,
    ``Curve``); it must be an instantiable ``Resource`` subclass, mirroring
    ``scene create``'s ``root_type`` check against ``Node``.
    """

    path: str
    type: str = Field(
        description=(
            "The Godot resource class to create (e.g. Gradient, Curve). Must be "
            "an instantiable Resource subclass."
        )
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

    target: str = Field(
        description=(
            "The resolution target: a 'uid://…' value to resolve to its res:// "
            "path, or a 'res://…' / filesystem path to resolve to its 'uid://…'. "
            "The direction is chosen by whether 'target' begins with 'uid://'."
        )
    )


# --- project static-analysis reads (issue #116) -----------------------------
#
# Four read-only, project-wide analysis commands, all backed by a single static
# project scan: find-references, dependencies, find-unused-resources, statistics.
# The scan parses files as TEXT (.tscn/.tres ext_resource paths, .gd
# preload/load/class_name references) — it never instantiates a scene or loads a
# script, so it honors the read trust boundary (issue #30). The only residual
# project-code execution is the engine constructing the project's autoloads at
# startup, inherent to any ``--project`` op (issue #61), documented on the params.


class ProjectFindReferencesParams(BaseModel):
    """The operation params of ``gda project find-references`` (issue #116).

    ``target`` is what to find references TO: a resource's ``res://`` path (a
    scene, script, image, ``.tres`` resource — anything addressable by path), or
    a script ``class_name``. The scan reads project files as TEXT and never
    instantiates a scene or loads a script (issue #30); the only project code that
    runs is the project's autoloads, constructed by the engine at startup on any
    ``--project`` op (issue #61).
    """

    target: str = Field(
        description=(
            "What to find references to: a resource's res:// path (scene, script, "
            "image, .tres, …) or a script class_name."
        )
    )


class ExportListParams(BaseModel):
    """The operation params of ``gda export list`` — none (ADR-0004).

    ``export list`` enumerates the export presets defined in the resolved
    project's ``export_presets.cfg``; the project is process context
    (``--project``), not an operation param (ADR-0006), so the ``input`` schema
    is trivially empty, exactly like ``scene list`` / ``script list``.
    """


class ListedPreset(BaseModel):
    """One enumerated export preset of ``gda export list`` (issue #114).

    Read cheaply from ``export_presets.cfg`` (a ``ConfigFile`` parse, no engine
    export run): ``name`` is the preset's display name — the address an agent
    feeds back into ``gda export get`` — ``platform`` the target platform (e.g.
    ``Linux/X11``, ``Web``), and ``runnable`` whether the preset is marked
    runnable (one-click deploy). ``index`` is the preset's 0-based position in
    the file (its ``preset.N`` section number), stable across a single read.
    """

    index: int = Field(
        description="The preset's 0-based position in export_presets.cfg (its preset.N section number)."
    )
    name: str = Field(description="The preset's display name.")
    platform: str = Field(
        description="The preset's target platform (e.g. Linux/X11, Web, macOS)."
    )
    runnable: bool = Field(
        description="Whether the preset is marked runnable (one-click deploy)."
    )


class ExportListResult(BaseModel):
    """The result of ``gda export list``: the project's enumerated export presets.

    A project whose ``export_presets.cfg`` exists but defines no presets is a
    valid, empty listing — ``presets == []`` — not a failure. A project with no
    ``export_presets.cfg`` at all is the ``export_presets_not_found`` failure
    (it has no export configuration), distinct from an empty one.
    """

    presets: list[ListedPreset]


class ExportGetParams(BaseModel):
    """The operation params of ``gda export get`` (issue #114).

    ``preset`` addresses an export preset by its display name (as ``export
    list`` reports it). An unknown name is the ``export_preset_not_found``
    failure. The project is process context (``--project``, ADR-0006).
    """

    preset: str = Field(
        description="The export preset's display name, as 'gda export list' reports it."
    )


class ExportGetResult(BaseModel):
    """The result of ``gda export get``: one preset's details + template readiness (issue #114).

    Echoes the addressed preset's ``index``/``name``/``platform``/``runnable``
    (read from ``export_presets.cfg``) plus its ``export_path`` (the output path
    the preset writes to, empty when unset). ``templates_installed`` reports
    whether the export templates for the running engine version are installed —
    the readiness check an agent makes before a future ``export run`` (issue
    #121); ``templates_version`` names the version directory that was checked
    (e.g. ``4.6.3.stable``), so the agent knows which templates to install when
    they are missing.
    """

    index: int = Field(
        description="The preset's 0-based position in export_presets.cfg (its preset.N section number)."
    )
    name: str = Field(description="The preset's display name.")
    platform: str = Field(
        description="The preset's target platform (e.g. Linux/X11, Web, macOS)."
    )
    runnable: bool = Field(
        description="Whether the preset is marked runnable (one-click deploy)."
    )
    export_path: str = Field(
        description="The output path the preset exports to, or empty when unset."
    )
    templates_installed: bool = Field(
        description=(
            "Whether the export templates for the running engine version are "
            "installed — the readiness check before an export run."
        )
    )
    templates_version: str = Field(
        description=(
            "The export-templates version directory checked for installation "
            "(e.g. 4.6.3.stable), matching the running engine version."
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


class ShaderCreateParams(BaseModel):
    """The operation params of ``gda shader create`` (issue #115).

    ``path`` is the target ``.gdshader`` file, addressed by its ``res://`` or
    filesystem path. A ``.gdshader`` is plain shader source authored as RAW
    TEXT — the create/get/set trio authors the file directly and never loads or
    compiles the shader AT THE OPERATION LEVEL (the same file-level boundary the
    script group's create/get/set honor, issue #30). This bounds the operation,
    not the run: like every command, a ``shader`` op still goes through the
    headless runner, so resolving ``--project`` still constructs the project's
    autoloads at engine startup (ADR-0009). ``content`` supplies verbatim shader
    source; when omitted, the operation writes a minimal ``shader_type`` template.
    """

    path: str
    content: str | None = Field(
        default=None,
        description=(
            "Verbatim shader source to write. When omitted, a minimal template "
            "declaring 'shader_type canvas_item' is written instead. Mutually "
            "exclusive with the template's shader type."
        ),
    )
    shader_type: str | None = Field(
        default=None,
        description=(
            "Shader type for the built-in template's 'shader_type' line (e.g. "
            "canvas_item, spatial, particles). Mutually exclusive with 'content' "
            "(supplying both is rejected); defaults to 'canvas_item' when neither "
            "is given."
        ),
    )


class ShaderCreateResult(BaseModel):
    """The result of ``gda shader create``: what was written where (issue #115).

    Echoes the saved ``path`` and the ``shader_type`` the written source
    declares, so an agent can assert the effect without a second call.
    ``created_dirs`` lists parent directories the operation created before
    saving, from outermost to innermost. The ``shader_type`` is parsed from the
    written source.
    """

    path: str
    shader_type: str | None = Field(
        default=None,
        description=(
            "The shader_type the written shader declares, or null when it "
            "declares none."
        ),
    )
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

    path: str


class ShaderGetParams(BaseModel):
    """The operation params of ``gda shader get``: the shader file to read (issue #115).

    ``path`` addresses the ``.gdshader`` by its ``res://`` or filesystem path.
    The source is read as raw text — the operation itself never loads or compiles
    the shader (the read boundary of issue #30). That bounds the operation, not
    the run: like every command it goes through the headless runner, so resolving
    ``--project`` still constructs the project's autoloads at engine startup
    (ADR-0009).
    """

    path: str


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


class ShaderGetResult(BaseModel):
    """The result of ``gda shader get``: a shader's source and metadata (issue #115).

    Echoes the ``path``, the full ``source`` read as raw text, and the
    ``shader_type`` the source declares (parsed from the text). Carrying the
    source verbatim makes a ``create`` verifiable end-to-end: ``create`` then
    ``get`` returns the same source.
    """

    path: str
    source: str
    shader_type: str | None = Field(
        default=None,
        description=(
            "The shader_type the shader declares, or null when it declares none."
        ),
    )


class ShaderSetParams(BaseModel):
    """The operation params of ``gda shader set`` (issue #115).

    Edits an existing ``.gdshader`` on disk as RAW TEXT — the operation itself
    never compiles or loads the shader (the edit boundary of issue #30). That
    bounds the operation, not the run: like every command it goes through the
    headless runner, so resolving ``--project`` still constructs the project's
    autoloads at engine startup (ADR-0009). ``path`` addresses the shader by its
    ``res://`` or filesystem path. The remaining params carry the SAME three
    mutually-exclusive edit modes as ``script set`` (issue #118) — the shader
    group reuses that edit interface rather than re-deriving it. The CLI resolves
    which mode and stamps it on ``mode`` (issue #133), so the operation dispatches
    on that explicit discriminator rather than re-inferring it from which params
    are present:

    - **search-replace** (``mode = search_replace``) — ``search``/``replace`` both
      present: every literal (not regex) occurrence of ``search`` is replaced with
      ``replace``.
    - **line-range** (``mode = line_range``) — ``start_line`` (+ optional
      ``end_line``) with ``content``: the given 1-based, inclusive line span is
      replaced with ``content``.
    - **full** (``mode = full``) — only ``content`` present: the whole file is
      overwritten.
    """

    path: str
    mode: ScriptSetMode = Field(
        description=(
            "The resolved edit mode, the single source of truth the operation "
            "dispatches on (issue #133). Set by the CLI from the supplied flags, "
            "not inferred by the operation from param presence. The same edit "
            "modes as script set (issue #118), reused here."
        ),
    )
    search: str | None = Field(
        default=None,
        description=(
            "search-replace mode: the literal substring to find (NOT a regex). "
            "Every occurrence is replaced with 'replace'. Requires 'replace'."
        ),
    )
    replace: str | None = Field(
        default=None,
        description=(
            "search-replace mode: the literal text each occurrence of 'search' "
            "is replaced with. Requires 'search'."
        ),
    )
    start_line: int | None = Field(
        default=None,
        description=(
            "line-range mode: the first line to replace, 1-based and inclusive. "
            "Lines are the parts of the source split on '\\n', so a trailing "
            "newline yields a final empty part: 'a\\nb\\n' is 3 lines "
            "(['a', 'b', '']). Valid range is 1..N where N is that part count. "
            "Requires 'content'."
        ),
    )
    end_line: int | None = Field(
        default=None,
        description=(
            "line-range mode: the last line to replace, 1-based and inclusive; "
            "defaults to 'start_line' (a single-line replace). Must satisfy "
            "start_line <= end_line <= N (the line count). Requires 'content'."
        ),
    )
    content: str | None = Field(
        default=None,
        description=(
            "The replacement text. In line-range mode it replaces the "
            "start_line..end_line span; with no 'start_line' it overwrites the "
            "entire file (full mode)."
        ),
    )


class ShaderSetResult(BaseModel):
    """The result of ``gda shader set``: the edited shader's metadata (issue #115).

    Echoes the saved ``path`` and the ``shader_type`` re-parsed from the source
    as written, so an edit round-trips through ``shader get`` (the verifier)
    without a second call — and an agent can assert the post-edit metadata
    directly.
    """

    path: str
    shader_type: str | None = Field(
        default=None,
        description=(
            "The shader_type the edited source declares, or null when it "
            "declares none."
        ),
    )


class ThemeCreateParams(BaseModel):
    """The operation params of ``gda theme create`` (issue #115).

    ``path`` is the target ``.tres`` file. Unlike the shader trio (plain
    file authoring), a Theme is an ENGINE-BACKED resource: the operation
    constructs a ``Theme`` and writes it through ``ResourceSaver`` so the result
    is a genuine, loadable ``.tres`` (verified by loading it back), not hand-
    written text. The split mirrors the script group: file-level ops author text;
    a resource-producing op goes through the engine.
    """

    path: str


class ThemeCreateResult(BaseModel):
    """The result of ``gda theme create``: the created Theme resource (issue #115).

    Echoes the saved ``path`` and the resource ``type`` written (``Theme``), so
    an agent can assert the effect without a second call. ``created_dirs`` lists
    parent directories the operation created before saving, from outermost to
    innermost.
    """

    path: str
    type: str = Field(
        description="The resource type written to the .tres (Theme)."
    )
    created_dirs: list[str] = Field(
        description=(
            "Parent directories created before saving, from outermost to innermost."
        )
    )


class ResourceReference(BaseModel):
    """One referencing site found by ``gda project find-references`` (issue #116).

    ``path`` is the ``res://`` path of the file that references the target — or
    ``project.godot`` for a project-level reference (an autoload or the main
    scene). ``kind`` names how it references it: ``ext_resource`` (a
    scene/resource ext_resource entry), ``preload``/``load`` (a script load
    call), ``class_extends`` (a script extending a base-class-by-path),
    ``class_reference`` (a ``.gd`` file using the target ``class_name`` as a bare
    identifier — best-effort, whole-word), or ``autoload``/``main_scene`` (a
    project-level reference in ``project.godot``). ``context`` is the matched
    line/snippet, best-effort, so an agent can locate the reference without
    re-reading the file.
    """

    path: str = Field(
        description=(
            "The res:// path of the referencing file, or 'project.godot' for a "
            "project-level reference."
        )
    )
    kind: str = Field(
        description=(
            "How the file references the target: ext_resource, preload, load, "
            "class_extends, class_reference, autoload, or main_scene."
        )
    )
    context: str = Field(
        description="The matched line or snippet that holds the reference."
    )


class ProjectFindReferencesResult(BaseModel):
    """The result of ``gda project find-references``: every site referencing the target.

    Echoes the ``target`` and the list of referencing sites. A target nothing
    references is a valid, empty result (``references == []``), not a failure —
    that emptiness is exactly what ``find-unused-resources`` keys on, so the two
    stay consistent (same reference graph).
    """

    target: str
    references: list[ResourceReference]


class ProjectDependenciesParams(BaseModel):
    """The operation params of ``gda project dependencies`` — none (ADR-0004).

    ``dependencies`` maps every scene/resource in the resolved project to the
    resources it references (its ``[ext_resource]`` entries). The project is
    process context (``--project``), not an operation param (ADR-0006), so the
    ``input`` schema is trivially empty.
    """


class Dependency(BaseModel):
    """One outgoing reference of a scene/resource (issue #116).

    ``path`` is the referenced resource's ``res://`` path; ``kind`` names how it
    is referenced (``ext_resource`` for a ``[ext_resource]`` entry).
    """

    path: str = Field(description="The res:// path of the referenced resource.")
    kind: str = Field(
        description="How the resource is referenced (ext_resource)."
    )


class ResourceDependencies(BaseModel):
    """One scene/resource and the resources it references (issue #116).

    ``path`` is the scene/resource's own ``res://`` path; ``depends_on`` lists the
    resources it references. A scene with no external references is reported with
    an empty ``depends_on``, not dropped.
    """

    path: str = Field(description="The res:// path of the scene/resource.")
    depends_on: list[Dependency]


class ProjectDependenciesResult(BaseModel):
    """The result of ``gda project dependencies``: the scene/resource → resource map.

    An empty project is a valid, empty map (``dependencies == []``), not a
    failure. Built from the same ext_resource parse as ``find-references``, so the
    two views of the reference graph stay consistent.
    """

    dependencies: list[ResourceDependencies]


class ProjectFindUnusedResourcesParams(BaseModel):
    """The operation params of ``gda project find-unused-resources`` — none (ADR-0004).

    Reports resource files that nothing references, built on the SAME reference
    graph as ``find-references``/``dependencies`` (acceptance criterion: the three
    must agree). The project is process context (``--project``), not an operation
    param (ADR-0006), so the ``input`` schema is trivially empty.
    """


class ProjectFindUnusedResourcesResult(BaseModel):
    """The result of ``gda project find-unused-resources``: the unreferenced resources.

    ``unused`` lists the ``res://`` paths of resource files that no other file
    references AND that are not project entry points (the main scene, an autoload
    script). A resource is unused exactly when ``find-references`` for it would
    return an empty list — the consistency the issue requires. An empty list means
    every resource is referenced (or an entry point).
    """

    unused: list[str]


class ProjectStatisticsParams(BaseModel):
    """The operation params of ``gda project statistics`` — none (ADR-0004).

    Reports file/line counts, autoloads and plugins for the resolved project. The
    project is process context (``--project``), not an operation param (ADR-0006),
    so the ``input`` schema is trivially empty.
    """


class ExtensionCount(BaseModel):
    """File/line counts for one file extension (issue #116).

    ``extension`` is the lowercased extension without the dot (``gd``, ``tscn``);
    ``files`` is how many files carry it; ``lines`` is their summed line count.
    """

    extension: str = Field(
        description="The lowercased file extension without the dot (e.g. gd, tscn)."
    )
    files: int
    lines: int


class Autoload(BaseModel):
    """One project autoload singleton (issue #116).

    ``name`` is the singleton name; ``path`` its ``res://`` script/scene path
    (with any leading ``*`` enable marker stripped). Read from ProjectSettings,
    not by executing the autoload.
    """

    name: str
    path: str = Field(description="The autoload's res:// path (enable marker stripped).")


class ProjectStatisticsResult(BaseModel):
    """The result of ``gda project statistics``: file/line counts, autoloads, plugins.

    ``total_files``/``total_lines`` are the project-wide totals; ``by_extension``
    breaks them down per extension. ``autoloads`` lists the project's autoload
    singletons (name + path, read from ProjectSettings); ``plugins`` lists the
    enabled editor plugins' ``plugin.cfg`` ``res://`` paths. ``scene_count`` /
    ``script_count`` / ``resource_count`` are convenience counts of ``.tscn`` /
    ``.gd`` / other-resource files. Line counts cover text files only; binary
    assets contribute to file counts but not line counts.
    """

    total_files: int
    total_lines: int
    by_extension: list[ExtensionCount]
    autoloads: list[Autoload]
    plugins: list[str] = Field(
        description="The res:// paths of the enabled editor plugins' plugin.cfg files."
    )
    scene_count: int
    script_count: int
    resource_count: int


class EngineVersion(BaseModel):
    """The Godot engine version, as reported by ``Engine.get_version_info()``.

    This is the result model of ``gda info``, and the ``engine_version`` carried
    by ``gda project info``.
    """

    major: int
    minor: int
    patch: int
    hex: int
    status: str
    build: str
    hash: str
    string: str
    timestamp: int


class ProjectInfoParams(BaseModel):
    """The operation params of ``gda project info`` — none (ADR-0004).

    ``project info`` reports the resolved project's metadata from its
    ``ProjectSettings``; the project is process context (``--project``), not an
    operation param (ADR-0006), so the ``input`` schema is trivially empty.
    """


class ProjectInfoResult(BaseModel):
    """The result of ``gda project info``: core project metadata (issue #111).

    Reports the project's ``name`` and ``main_scene`` from ``ProjectSettings``,
    its configured ``viewport_width``/``viewport_height``, and the ``engine_version``
    the project runs on (the same shape ``gda info`` reports). ``main_scene`` is the
    empty string for a project that has not set a main scene, and the viewport
    fields fall back to the engine's built-in defaults when the project never set
    them, so a brand-new project still reports a complete, valid result.
    """

    name: str = Field(description="The project name (ProjectSettings application/config/name).")
    main_scene: str = Field(
        description=(
            "The project's main scene path (application/run/main_scene), or the "
            "empty string when none is set."
        )
    )
    viewport_width: int = Field(
        description="The configured viewport width (display/window/size/viewport_width)."
    )
    viewport_height: int = Field(
        description="The configured viewport height (display/window/size/viewport_height)."
    )
    engine_version: EngineVersion = Field(
        description="The Godot engine version the project runs on."
    )


class ProjectGetParams(BaseModel):
    """The operation params of ``gda project get`` (issue #111).

    ``setting`` is the project setting's full ``section/key`` name (e.g.
    ``application/config/name``). The project is process context (``--project``),
    not an operation param (ADR-0006), so only ``setting`` is an input.
    """

    setting: str = Field(
        description=(
            "The project setting's full section/key name, e.g. "
            "application/config/name."
        )
    )


class ProjectGetResult(BaseModel):
    """The result of ``gda project get``: one setting as typed JSON (issue #111).

    Echoes the addressed ``setting``, its declared Godot ``type`` name, and its
    ``value`` in the same JSON projection ``node get`` reports for a node property
    (a scalar stays a scalar, a Vector2 becomes ``[x, y]``) — the projection
    ``project set`` accepts back, so a ``set`` round-trips through a ``get``.
    """

    setting: str
    type: str = Field(
        description="The setting's declared Godot type name (e.g. String, int, Vector2)."
    )
    value: Any = Field(
        description=(
            "The setting's value as JSON: a scalar for a scalar type, a list for "
            "a packed type (Vector2 → [x, y], Color → [r, g, b, a])."
        )
    )


class ProjectSetParams(BaseModel):
    """The operation params of ``gda project set`` (issue #111).

    ``setting`` is the project setting's full ``section/key`` name; ``value`` is
    the CLI string value, coerced to the setting's declared Godot type by the
    operation (the same coercion rules as ``node set``, #55) before
    ``project.godot`` is saved. ``set`` edits an EXISTING setting — an unknown key
    is a clean error, never a silent create — so the declared type to coerce to is
    always known (read off the setting's current value).
    """

    setting: str = Field(
        description=(
            "The project setting's full section/key name, e.g. "
            "application/config/name."
        )
    )
    value: str = Field(
        description=(
            "The value to set, as a string. The operation coerces it to the "
            "setting's declared Godot type (see the command catalog's 'Property "
            "value coercion'); an uncoercible value is a clean error."
        )
    )


class ProjectSetResult(BaseModel):
    """The result of ``gda project set``: the one setting it set (issue #111).

    Echoes the ``setting`` set, the declared ``type`` the CLI value was coerced
    to, and the coerced ``value`` as JSON — the same projection ``project get``
    reports, so a ``set`` round-trips through a ``get`` without re-reading
    ``project.godot``.
    """

    setting: str
    type: str = Field(description="The setting's declared Godot type the value was coerced to.")
    value: Any = Field(
        description="The coerced value as JSON, as ProjectSettings now holds it."
    )
