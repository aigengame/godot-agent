"""Typed result models (ADR-0004).

Each command's result is carried by a Pydantic model rather than an ad-hoc
dict, so the same model both serializes the ``--json`` output now and produces
the ``--schema`` document later (``model_json_schema()``) without
hand-maintaining the contract twice.
"""

from enum import Enum
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from gda.execution import ExecutionKind
from gda.skill_targets import SkillProvider, SkillScope, resolve_skill_dir


class ErrorCategory(str, Enum):
    """The coarse buckets a ``gda`` operation can fail into (issue #3).

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
    LIVE is a Phase-2 live operation failing against ``gda-daemon`` / the engine
    session — no running daemon, a lost session, or a live timeout (ADR-0017,
    ADR-0021).
    """

    ENVIRONMENT = "environment"
    VERSION = "version"
    OPERATION = "operation"
    PARSE = "parse"
    LIVE = "live"


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


class SchemaAllParams(BaseModel):
    """The operation params of ``gda schema`` — none (ADR-0012).

    Like ``gda info``, ``gda schema`` takes no operation params, so its
    ``input`` schema is trivially empty. The model still exists so ``gda schema
    --schema`` is derived model-side rather than hand-written, keeping the meta
    command self-describing under the same ADR-0004 gate as every other command.
    """


class LiveStackConstraints(BaseModel):
    """The platform / Godot-version precondition a live-stack command needs (issue #233).

    A structured, machine-discoverable form of the constraint that ``gda``'s
    daemon/live stack carries — macOS/Linux only (Unix domain sockets) and, where
    a command launches/uses the engine, Godot 4.6+ (ADR-0021) — replacing the
    prose that used to live only in ``--help`` text and the manifest description.
    Present (non-``null``) only on commands that depend on the live stack: the
    LIVE-channel domain commands (``game …``) and the ``daemon`` lifecycle group;
    every other command's ``constraints`` is ``null``.

    Both facets come from the single :func:`gda.execution.live_stack_constraints`
    authority, so the structured field and the help/manifest prose cannot drift:

    - ``platforms`` is the uniform ``["linux", "macos"]`` (UDS) across the whole
      live-stack set.
    - ``min_godot_version`` is the dotted floor (``"4.6"``) only where a command
      launches/uses the engine (``game …``, ``daemon start``); ``None`` for
      ``daemon stop`` / ``daemon status``, which only talk to a running daemon
      over UDS and never touch the engine.

    Additive and ignored by gda-mcp, which maps only ``input`` / ``output`` /
    ``description`` (ADR-0012), so adding it is backward-compatible (ADR-0004).
    """

    platforms: list[str]
    # Required key, nullable value: the wrapper always supplies it (``None`` for
    # daemon stop/status), and the emitted objects always carry the key — so the
    # self-described schema marks it required, matching the actual ABI (issue #233,
    # PR #245 review). Not defaulted, or the schema would allow the key's omission.
    min_godot_version: str | None


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

    ``kind`` carries the command's static execution channel as the typed
    :class:`~gda.execution.ExecutionKind` (serialized as the lowercase value
    ``"headless"`` / ``"export"`` / ``"live"``), taken from the command
    descriptor's single source of truth (``HeadlessCommand.kind``), so an agent
    can branch on a command's channel without inferring it (issue #230, stories
    14/15/24). Typing it as the enum makes the value enum-constrained in any
    derived schema. It is additive: gda-mcp maps only ``input`` / ``output`` /
    ``description`` and ignores it, so adding it is backward-compatible
    (ADR-0012). It is ``None`` only when a self-description is emitted without a
    backing command (e.g. ``gda schema``); a real per-command ``--schema`` always
    carries a kind.

    ``constraints`` carries the command's :class:`LiveStackConstraints` — the
    platform / Godot-version precondition for gda's daemon/live stack — or
    ``None`` for a command with no live-stack dependence (issue #233). Both forms
    are sourced from the single :func:`gda.execution.live_stack_constraints`
    authority. Additive and ignored by gda-mcp (ADR-0012, ADR-0004).
    """

    input: dict[str, Any]
    output: dict[str, Any]
    error: dict[str, Any]
    kind: ExecutionKind | None = None
    constraints: LiveStackConstraints | None = None

    @classmethod
    def of(
        cls,
        input_model: type[BaseModel],
        output_model: type[BaseModel],
        kind: ExecutionKind | None = None,
        constraints: LiveStackConstraints | None = None,
    ) -> "CommandSchema":
        """Derive the contract from a command's params and result models.

        ``error`` is the shared failure-envelope schema, the same for every
        command, so it takes no per-command model argument. ``kind`` is the
        command's static :class:`~gda.execution.ExecutionKind` (issue #230); it
        serializes to its lowercase string because ``ExecutionKind`` subclasses
        ``str``. ``constraints`` is the command's live-stack precondition or
        ``None`` (issue #233), computed by the caller from the single
        :func:`gda.execution.live_stack_constraints` authority.
        """
        return cls(
            input=input_model.model_json_schema(),
            output=output_model.model_json_schema(),
            error=GdaErrorEnvelope.model_json_schema(),
            kind=kind,
            constraints=constraints,
        )


class CommandManifestEntry(BaseModel):
    """One command's entry in the aggregate surface manifest (ADR-0012).

    The whole-surface generalisation of a single command's :class:`CommandSchema`:
    it carries the same model-derived ``input`` / ``output`` / ``error`` halves,
    plus the two facts gda-mcp needs to register a tool — ``name`` (the
    ``<group> <command>`` MCP mapping basis, ADR-0005, e.g. ``scene create``;
    bare for a meta command such as ``info``) and the command's ``description``
    (its help text, which flows into the MCP tool description).

    ``kind`` mirrors :class:`CommandSchema`'s: the entry's static execution
    channel as the typed :class:`~gda.execution.ExecutionKind` (serialized
    ``"headless"`` / ``"export"`` / ``"live"``), taken from the same descriptor
    source of truth so the aggregate and per-command forms agree (issue #230).
    Additive and ignored by gda-mcp (ADR-0012). Unlike :class:`CommandSchema`'s
    optional ``kind``, here it is **required**: every aggregate entry is a
    dispatchable command with a backing descriptor, so the self-described surface
    schema (``gda schema --schema``) guarantees the field and constrains it to
    the execution-kind enum — a consumer can rely on it always being present.

    ``constraints`` mirrors :class:`CommandSchema`'s: the entry's
    :class:`LiveStackConstraints`, or ``None`` for a command with no live-stack
    dependence (issue #233), from the same single
    :func:`gda.execution.live_stack_constraints` authority so the aggregate and
    per-command forms agree. Unlike :class:`CommandSchema`'s defaulted field, the
    **key is required** here (every dispatchable entry is computed from a backing
    descriptor, so the self-described surface schema guarantees the key is
    present) while its **value is nullable** (``null`` for non-live-stack
    commands) — a consumer can rely on the key always being there to read.
    """

    name: str
    description: str
    input: dict[str, Any]
    output: dict[str, Any]
    error: dict[str, Any]
    kind: ExecutionKind
    constraints: LiveStackConstraints | None


class SurfaceManifest(BaseModel):
    """The whole ``gda`` command surface as one document (ADR-0012).

    What ``gda schema`` emits and gda-mcp introspects once at startup: one
    :class:`CommandManifestEntry` per command in every group. An object (rather
    than a bare array) leaves room for top-level metadata later and gives the
    manifest its own schema, so ``gda schema --schema`` self-describes.
    """

    commands: list[CommandManifestEntry]


def normalize_path(path: str) -> str:
    """Normalize a path argument (issue #32; ADR-0015 moves it model-side).

    Engine-resolved virtual paths (``res://``, ``user://``, ``uid://``) pass
    through untouched — the engine resolves them against the project. A
    filesystem path gets ``~`` expanded so a literal ``~`` works without a shell.

    Lives here, not at the CLI layer, so the argv path and the ``--params-json``
    path normalize identically (ADR-0015): the model is the single home of
    normalization, applied wherever the model is constructed.
    """
    if "://" in path:
        return path
    return str(Path(path).expanduser())


# The one reusable path-field type: a ``str`` whose value is run through
# ``normalize_path`` whenever the model is constructed (ADR-0015). Annotating a
# field with this is the single normalization mechanism shared by the argv and
# ``--params-json`` paths — no per-model ``@field_validator`` to maintain.
# ``AfterValidator`` (not Before): the value is validated as a ``str`` FIRST, so a
# wrong-typed ``--params-json`` value (e.g. ``{"path": 123}``) raises a
# ``ValidationError`` (→ structured ``invalid_params``) instead of ``normalize_path``
# hitting a ``TypeError`` on a non-string.
NormalizedPath = Annotated[str, AfterValidator(normalize_path)]


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


class NodeAddParams(BaseModel):
    """The operation params of ``gda node add`` (issue #53).

    ``path`` is the ``.tscn`` scene file to mutate. ``parent`` addresses the
    parent node by node path. ``type`` is resolved first as a built-in Godot
    node class, then as a ``class_name`` registered in the project's global
    class list. ``name`` is explicit so the operation never silently derives a
    name Godot later sanitizes; when the CLI caller omits ``--name``, it uses
    the type name.
    """

    path: NormalizedPath = Field(description="The .tscn scene file to mutate.")
    parent: str = Field(
        default=".",
        description=(
            "Parent node path, relative to the scene root: '.' addresses the "
            "root itself, 'Player/Arm' a nested node."
        ),
    )
    type: str = Field(
        description=(
            "Node type to add: a Godot node class (e.g. Sprite2D), or a "
            "class_name registered in the project's global class list."
        )
    )
    name: str | None = Field(
        default=None,
        description=(
            "Name for the new node. If omitted, the type name is used. Must be "
            "non-empty and must not contain '.', ':', '@', '/', '\"', or '%'."
        ),
    )

    @model_validator(mode="after")
    def _default_name(self) -> "NodeAddParams":
        # Derive the default node name from the type model-side (ADR-0015), so the
        # argv and --params-json paths agree instead of the CLI deriving it.
        if self.name is None:
            self.name = self.type
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
    type: str = Field(
        description="The property's declared Godot type the value was coerced to."
    )
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


class ScriptCreateParams(BaseModel):
    """The operation params of ``gda script create`` (issue #110).

    ``path`` is the target ``.gd`` script file, addressed by its ``res://`` or
    filesystem path (script-file addressing — by file path, not by
    ``class_name``). ``content`` supplies verbatim source; when omitted, the
    operation writes a minimal built-in template extending ``extends_type``.
    ``content`` and ``extends_type`` are mutually exclusive at the CLI: verbatim
    content is not templated, so a base class would have nowhere to go.
    """

    path: NormalizedPath = Field(description="Target .gd script path to write.")
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

    @model_validator(mode="after")
    def _content_xor_extends(self) -> "ScriptCreateParams":
        # Verbatim content is not templated, so a base class has nowhere to go:
        # the two are mutually exclusive. Enforced model-side (ADR-0015) so the
        # --params-json path rejects the conflict too, not just argv.
        if self.content is not None and self.extends_type is not None:
            raise ValueError("'content' and 'extends_type' are mutually exclusive.")
        return self


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
            "The class_name the written script declares, or null when it declares none."
        ),
    )
    extends: str | None = Field(
        default=None,
        description=(
            "The base class the written script extends, or null when it declares none."
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

    path: NormalizedPath = Field(description="The .gd script file to read.")


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

    path: NormalizedPath = Field(description="The .gd script file to delete.")


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


def resolve_set_mode(
    search: str | None,
    replace: str | None,
    start_line: int | None,
    end_line: int | None,
    content: str | None,
) -> ScriptSetMode:
    """Resolve a script/shader-set edit mode from the supplied params (issue #133).

    The single home of the edit-mode rule, shared by ``script set`` and ``shader
    set`` and by BOTH input paths (ADR-0015): exactly one of the three
    mutually-exclusive modes must be supplied. Raises ``ValueError`` on a
    violation — the CLI wrapper translates it to a usage error (exit 2) for argv,
    while the params models surface it as the structured ``invalid_params`` for
    ``--params-json``.
    """
    has_search = search is not None or replace is not None
    has_line_range = start_line is not None or end_line is not None

    if has_search:
        if search is None or replace is None:
            raise ValueError("'search' and 'replace' must be used together.")
        if content is not None or has_line_range:
            raise ValueError(
                "'search'/'replace' cannot be combined with 'content', "
                "'start_line', or 'end_line'."
            )
        return ScriptSetMode.SEARCH_REPLACE

    if has_line_range:
        if content is None:
            raise ValueError("'start_line'/'end_line' require 'content'.")
        if start_line is None:
            raise ValueError("'end_line' requires 'start_line'.")
        return ScriptSetMode.LINE_RANGE

    if content is None:
        raise ValueError(
            "a set command needs an edit: 'search'/'replace', 'start_line' "
            "(+ 'content'), or 'content' (full overwrite)."
        )
    return ScriptSetMode.FULL


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

    path: NormalizedPath = Field(description="The .gd script file to edit.")
    mode: ScriptSetMode | None = Field(
        default=None,
        description=(
            "The resolved edit mode, the single source of truth the operation "
            "dispatches on (issue #133). Derived model-side from the supplied "
            "edit params (ADR-0015); a value passed in is ignored."
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

    @model_validator(mode="after")
    def _resolve_mode(self) -> "ScriptSetParams":
        # Derive the edit mode from the supplied params (ADR-0015), so the argv
        # and --params-json paths agree and a JSON caller cannot pass a mode
        # inconsistent with the other edit fields.
        self.mode = resolve_set_mode(
            self.search, self.replace, self.start_line, self.end_line, self.content
        )
        return self


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
            "The class_name the edited source declares, or null when it declares none."
        ),
    )
    extends: str | None = Field(
        default=None,
        description=(
            "The base class the edited source extends, or null when it declares none."
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

    path: NormalizedPath = Field(description="The .tscn scene file to mutate.")
    node: str = Field(
        description=(
            "Node path relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        )
    )
    script: NormalizedPath = Field(
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

    path: NormalizedPath = Field(description="The .gd script file to validate.")


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

    path: NormalizedPath = Field(description="Target .tres resource path to write.")
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

    target: NormalizedPath = Field(
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

    target: NormalizedPath = Field(
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


class ExportRunMode(str, Enum):
    """The export flavor ``gda export run`` produces (issue #121, selectable #170).

    Maps to Godot's native export flags (ADR-0001). ``release``/``debug`` produce
    a full platform binary and require the matching export templates to be
    installed; ``pack`` produces project data only — a PCK/ZIP, chosen by the
    output path's extension — and needs no platform templates.

    Issue #121 fixed the mode to ``release`` (the common intent — a complete
    export); follow-up #170 exposes ``--mode`` so an agent can select
    ``debug``/``pack``. ``release`` stays the default.
    """

    RELEASE = "release"
    DEBUG = "debug"
    PACK = "pack"


class ExportRunParams(BaseModel):
    """The operation params of ``gda export run`` (issue #121, overrides #170).

    ``preset`` addresses the export preset by its display name (as ``export
    list`` reports it); an unknown name is the ``export_preset_not_found``
    failure. ``mode`` selects the export flavor (``release`` default; #170).
    ``output`` overrides the preset's *configured* ``export_path`` (#170); when
    omitted the export targets the configured path (an empty configured path with
    no override is the ``export_path_unset`` failure). The project is process
    context (``--project``, ADR-0006).
    """

    preset: str = Field(
        description="The export preset's display name, as 'gda export list' reports it."
    )
    mode: ExportRunMode = Field(
        default=ExportRunMode.RELEASE,
        description="The export flavor to run (release/debug/pack); default release.",
    )
    output: NormalizedPath | None = Field(
        default=None,
        description="Override the preset's configured export_path; write the artifact here instead.",
    )


class ExportRunResult(BaseModel):
    """The result of ``gda export run``: the artifact that was produced (issue #121).

    Echoes the addressed preset's ``preset`` name and target ``platform`` (read
    from ``export_presets.cfg``), the ``mode`` that was run (the selected flavor,
    ``release`` by default; #170), and the ``output_path`` the artifact was
    written to — the effective destination, i.e. the ``--output`` override when
    given, else the preset's *configured* ``export_path`` (#170).
    ``warnings`` carries the engine's non-fatal export warnings (e.g. a missing
    optional icon), parsed best-effort from the export's stderr; an export that
    succeeds cleanly reports ``warnings == []``. Unlike the sentinel operations,
    ``export run`` is a native Godot export (the export subsystem is editor-only,
    ADR-0002 sentinels do not apply), so this result is synthesized by ``gda``
    from the export's exit code + stderr.
    """

    preset: str = Field(description="The export preset's display name.")
    platform: str = Field(
        description="The preset's target platform (e.g. Linux/X11, Web, macOS)."
    )
    mode: ExportRunMode = Field(description="The export flavor that was run.")
    output_path: str = Field(description="The path the export artifact was written to.")
    warnings: list[str] = Field(
        default_factory=list,
        description="The engine's non-fatal export warnings, parsed from stderr; empty on a clean export.",
    )


class ScriptRunParams(BaseModel):
    """The operation params of ``gda script run`` (issue #343, ADR-0031).

    ``path`` is the ``res://`` path of the user script to run as a one-shot
    ``godot --headless --path <project> --script <res://…>``. It is res://-only
    (a res:// path resolves against the ``--project`` context, ADR-0006): an
    absolute or non-``res://`` path is the ``invalid_path`` failure. A plain
    ``str`` (NOT ``NormalizedPath``) because a res:// path is an engine-virtual
    address, not a filesystem path — filesystem normalization would collapse the
    ``res://`` double slash. The project is process context (``--project``), not
    an operation param.
    """

    path: str = Field(
        description="The res:// path of the script to run (e.g. res://tests/logic.gd)."
    )


class ScriptRunResult(BaseModel):
    """The result of ``gda script run``: the user script's own run, passed through (ADR-0031).

    This is the **public promotion of the internal Raw-run shape**
    (:class:`gda.runner.RunResult`): a THIN boundary DTO built from a ``RunResult``
    by dropping its ``launch_failure`` axis (that becomes the Error envelope) and
    renaming ``exit_code`` → ``exit_status``. Unlike every other command,
    ``script run`` does not interpret the user script's semantics — a deliberate
    ``quit(1)`` is meaningful data the agent reads, not a gda failure — so this is
    the **one** command whose *success* result can carry a non-zero
    ``exit_status``. Agents must read ``exit_status`` and must not assume
    ``success == zero``.

    NOTE: a second passthrough consumer should promote this to a shared
    ``RawRunResult`` model. Do NOT build that shared abstraction now: there is only
    one consumer today (``export run`` returns a different domain shape — the
    produced artifact — and does not reuse the raw run).
    """

    exit_status: int = Field(
        description=(
            "The user script's own process exit code, passed through verbatim — "
            "non-zero (e.g. a deliberate quit(1)) is still a SUCCESS result, not a "
            "gda failure (ADR-0031)."
        )
    )
    stdout: str = Field(description="The script's standard output, captured verbatim.")
    stderr: str = Field(description="The script's standard error, captured verbatim.")


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

    path: NormalizedPath = Field(description="Target .gdshader path to write.")
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

    @model_validator(mode="after")
    def _content_xor_shader_type(self) -> "ShaderCreateParams":
        # Same rule as script create: verbatim content is not templated, so a
        # shader type has nowhere to go. Enforced model-side (ADR-0015) so the
        # --params-json path rejects the conflict, not just argv.
        if self.content is not None and self.shader_type is not None:
            raise ValueError("'content' and 'shader_type' are mutually exclusive.")
        return self


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

    path: NormalizedPath = Field(description="The .tres resource file to read.")


class ShaderGetParams(BaseModel):
    """The operation params of ``gda shader get``: the shader file to read (issue #115).

    ``path`` addresses the ``.gdshader`` by its ``res://`` or filesystem path.
    The source is read as raw text — the operation itself never loads or compiles
    the shader (the read boundary of issue #30). That bounds the operation, not
    the run: like every command it goes through the headless runner, so resolving
    ``--project`` still constructs the project's autoloads at engine startup
    (ADR-0009).
    """

    path: NormalizedPath = Field(description="The .gdshader file to read.")


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
            "value coercion'); an uncoercible value is a clean error."
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
        description="The coerced value as JSON, as the resource now holds it."
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

    path: NormalizedPath = Field(description="The .gdshader file to edit.")
    mode: ScriptSetMode | None = Field(
        default=None,
        description=(
            "The resolved edit mode, the single source of truth the operation "
            "dispatches on (issue #133). Derived model-side from the supplied "
            "edit params (ADR-0015); a value passed in is ignored. The same edit "
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

    @model_validator(mode="after")
    def _resolve_mode(self) -> "ShaderSetParams":
        # Derive the edit mode from the supplied params (ADR-0015), so the argv
        # and --params-json paths agree and a JSON caller cannot pass a mode
        # inconsistent with the other edit fields.
        self.mode = resolve_set_mode(
            self.search, self.replace, self.start_line, self.end_line, self.content
        )
        return self


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
            "The shader_type the edited source declares, or null when it declares none."
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
    kind: str = Field(description="How the resource is referenced (ext_resource).")


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
    path: str = Field(
        description="The autoload's res:// path (enable marker stripped)."
    )


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


class SkillParams(BaseModel):
    """The operation params of ``gda skill`` (ADR-0024, extended ADR-0027).

    ``gda skill`` is a pure emitter meta command: it reads the bundled
    ``SKILL.md`` from the package and emits or installs it — no Godot is spawned.
    ``install`` writes the manifest to a target instead of printing it. The target
    is named one of two ways: a caller-supplied ``install_dir`` (the neutral path,
    ADR-0024 — core carries no default location), or a known ``provider`` whose
    skills directory is resolved at ``scope`` (the opt-in convenience, ADR-0027).
    The two are mutually exclusive; ``provider`` normalizes to ``install_dir`` here so
    the argv and ``--params-json`` paths resolve identically (ADR-0015).
    """

    install: bool = Field(
        default=False,
        description="If true, WRITE the bundled SKILL.md to the target "
        "instead of returning it; the result then reports the written path.",
    )
    install_dir: str | None = Field(
        default=None,
        description="The skills directory to install into (caller-supplied; the neutral "
        "path, no default). Parent dirs are created and an existing file is overwritten. "
        "Providing it implies an install (ADR-0015 parity with argv --dir). Mutually "
        "exclusive with provider.",
    )
    provider: SkillProvider | None = Field(
        default=None,
        description="Install into a KNOWN agent's skills directory instead of a "
        "caller-supplied install_dir: resolves that agent's directory at scope "
        "(ADR-0027). Mutually exclusive with install_dir; providing it implies an install.",
    )
    scope: SkillScope = Field(
        default=SkillScope.USER,
        description="With provider, whether to install into the agent's per-project "
        "(committed) or per-user (all projects) skills directory; default user.",
    )

    @model_validator(mode="after")
    def _resolve_install_target(self) -> "SkillParams":
        # Single source of truth (ADR-0015): normalize the target HERE, in the model, so
        # argv and a --params-json object agree. A named provider resolves to its known
        # skills dir (ADR-0027) — but provider and an explicit install_dir name the SAME
        # thing two ways, so giving both is ambiguous and rejected. Then, whichever way a
        # target was named, naming one means "install there".
        if self.provider is not None:
            if self.install_dir is not None:
                raise ValueError(
                    "provider and install_dir are mutually exclusive: name an agent "
                    "(--provider) OR a directory (--dir), not both"
                )
            self.install_dir = resolve_skill_dir(self.provider, self.scope)
        if self.install_dir is not None:
            self.install = True
        return self


class SkillResult(BaseModel):
    """The result of ``gda skill``: the bundled Skill, version-locked (ADR-0024).

    ``name``/``version``/``content`` carry the manifest's identity, the installed
    ``gda`` version (from ``importlib.metadata``, so the guidance cannot skew from
    the CLI it describes), and the full ``SKILL.md`` text. ``installed_path`` is the
    path written on ``--install`` and ``None`` for a plain emit, so one model serves
    both the emit and install paths.
    """

    name: str
    version: str
    content: str
    installed_path: Path | None = None


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

    name: str = Field(
        description="The project name (ProjectSettings application/config/name)."
    )
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
            "The project setting's full section/key name, e.g. application/config/name."
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


class ProjectListParams(BaseModel):
    """The operation params of ``gda project list`` (issue #312).

    Enumerates the project's ``ProjectSettings`` keys so an agent can DISCOVER
    which settings exist — the list half of the ``list → get → set`` workflow
    (``get``/``set`` both require you to already know the ``section/key``).
    ``include_defaults`` (the CLI ``--all`` flag) widens the listing from only the
    project's customized (non-default) settings to the engine's built-in defaults
    too; ``section`` restricts it to keys whose name begins with that ``section/``
    prefix (e.g. ``application/``, ``display/``), and the two compose. The project
    is process context (``--project``), not an operation param (ADR-0006).
    """

    include_defaults: bool = Field(
        default=False,
        description=(
            "Also list the engine's built-in default settings, not just the "
            "project's customized (non-default) ones. The CLI --all flag."
        ),
    )
    section: str | None = Field(
        default=None,
        description=(
            "Restrict the listing to keys whose name begins with this section/ "
            "prefix, e.g. application/ or display/. Null lists every section."
        ),
    )


class ListedProjectSetting(BaseModel):
    """One enumerated project setting of ``gda project list`` (issue #312).

    Reuses the same ``{setting, type, value}`` projection ``project get`` reports
    for a single setting — so a listed entry round-trips through ``project get`` —
    plus ``is_default``: ``false`` when the key is customized (written in
    ``project.godot``), ``true`` when it is at the engine's built-in default.
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
    is_default: bool = Field(
        description=(
            "True when the setting is at the engine's built-in default; false when "
            "it is customized in project.godot."
        )
    )


class ProjectListResult(BaseModel):
    """The result of ``gda project list``: the project's enumerated settings (#312).

    ``settings`` is the discovered keys, each a ``{setting, type, value,
    is_default}`` entry sorted by name. A project with no customized settings and
    no ``include_defaults`` is a valid, EMPTY listing — ``settings == []`` — not a
    failure. Internal engine-bookkeeping and non-setting properties are filtered
    out, so only real ``ProjectSettings`` keys appear.
    """

    settings: list[ListedProjectSetting]


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
            "The project setting's full section/key name, e.g. application/config/name."
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
    type: str = Field(
        description="The setting's declared Godot type the value was coerced to."
    )
    value: Any = Field(
        description="The coerced value as JSON, as ProjectSettings now holds it."
    )


class ProjectAddAutoloadParams(BaseModel):
    """The operation params of ``gda project add-autoload`` (issue #119).

    Registers an autoload singleton: ``name`` is the global accessor name (the key
    under the ``autoload/`` section of ``project.godot``); ``path`` is the res://
    path to the script or scene to autoload. The operation stores it in the
    enabled-singleton form (a leading ``*`` prefix) and saves ``project.godot``.
    The project is process context (``--project``), not an operation param
    (ADR-0006), so only ``name`` and ``path`` are inputs.
    """

    name: str = Field(
        description=(
            "The autoload singleton's global name — the accessor it is reached by "
            "and the key under the project's autoload/ section."
        )
    )
    path: NormalizedPath = Field(
        description=(
            "The res:// path to the script or scene to autoload, e.g. res://global.gd."
        )
    )


class ProjectAddAutoloadResult(BaseModel):
    """The result of ``gda project add-autoload``: the autoload it registered.

    Echoes the autoload's ``name`` and the ``path`` exactly as it was persisted to
    ``project.godot`` — the enabled-singleton form with the leading ``*`` prefix
    (e.g. ``*res://global.gd``), the same value a ``project get`` of
    ``autoload/<name>`` reads back, so an add round-trips through a get.
    """

    name: str = Field(description="The registered autoload's global name.")
    path: str = Field(
        description=(
            "The autoload value as persisted to project.godot, in enabled-singleton "
            "form with the leading * prefix (e.g. *res://global.gd)."
        )
    )


class ProjectRemoveAutoloadParams(BaseModel):
    """The operation params of ``gda project remove-autoload`` (issue #119).

    Unregisters an autoload singleton by its global ``name`` (the key under the
    ``autoload/`` section), then saves ``project.godot``. The project is process
    context (``--project``), not an operation param (ADR-0006), so only ``name``
    is an input.
    """

    name: str = Field(
        description="The global name of the autoload singleton to unregister."
    )


class ProjectRemoveAutoloadResult(BaseModel):
    """The result of ``gda project remove-autoload``: the autoload it removed.

    Echoes the ``name`` of the autoload that was unregistered, so an agent can
    confirm which singleton was removed; a subsequent ``project get`` of
    ``autoload/<name>`` reports ``unknown_setting``.
    """

    name: str = Field(description="The unregistered autoload's global name.")


class GameNode(BaseModel):
    """One node of the RUNNING game's runtime scene tree (Phase 2, ADR-0019).

    The runtime counterpart of :class:`SceneNode`: ``gda game tree`` reports the
    live ``SceneTree`` after ``_ready`` and dynamic instantiation, so it carries
    the runtime node ``path`` alongside ``name``/``type``/``children``. Distinct
    from the on-disk ``.tscn`` read by ``scene get`` (a different object, ADR-0019).
    """

    name: str
    type: str
    path: str
    children: list["GameNode"] = []


class GameTreeParams(BaseModel):
    """The params of ``gda game tree``: read the running game's runtime scene tree.

    Empty — it reads the whole runtime tree of the engine session held by
    ``gda-daemon`` (a subtree root may be added by a later slice).
    """


class GameTreeResult(BaseModel):
    """The result of ``gda game tree``: the running game's runtime scene tree."""

    root: GameNode


# The runtime node address: ABSOLUTE, as ``game tree`` reports it via the live
# tree's ``Node.get_path()``. This is the live counterpart of the node group's
# root-relative ``node`` param — the headless resolver rejects absolute paths,
# so the live layer addresses off the running SceneTree root instead (ADR-0019).
_RUNTIME_NODE_DESC = (
    "Runtime node path as `game tree` reports it (absolute, e.g. /root/Main/Player)."
)


class GameGetParams(BaseModel):
    """The params of ``gda game get``: read a running node's runtime properties (#220).

    The live counterpart of :class:`NodeGetParams`, addressed by the runtime
    (absolute) node path rather than a ``.tscn`` file + root-relative node path:
    there is no file, only the live SceneTree of the engine session. ``property``
    optionally narrows the read to one property.
    """

    node: str = Field(description=_RUNTIME_NODE_DESC)
    property: str | None = Field(
        default=None,
        description="If set, read only this one property instead of the whole storage surface.",
    )


class GameGetResult(BaseModel):
    """The result of ``gda game get``: a running node's runtime properties (#220).

    The live counterpart of :class:`NodeGetResult` (no ``scene_path`` — there is
    no file): echoes the addressed node (runtime ``path``/``name``/``type``) and
    its storage properties, each a typed :class:`NodeProperty`, so an agent reads
    the running node's live state and can feed any property back into ``game set``.
    """

    path: str = Field(description="The addressed node's runtime (absolute) path.")
    name: str
    type: str = Field(description="The node's engine class (e.g. CharacterBody2D).")
    properties: list[NodeProperty]


class GameSetParams(BaseModel):
    """The params of ``gda game set``: mutate a running node's runtime property (#220).

    The live counterpart of :class:`NodeSetParams`, addressed by the runtime
    (absolute) node path. ``property`` names the property; ``value`` is the CLI
    string value, coerced to the property's declared Godot type by the gda harness
    (the SAME coercion table headless ``node set`` uses) and applied at a frame
    boundary (ADR-0020). The mutation is bound to the session, not persisted.
    """

    node: str = Field(description=_RUNTIME_NODE_DESC)
    property: str = Field(description="The property to set (e.g. position, visible).")
    value: str = Field(
        description=(
            "The value to set, as a string. The gda harness coerces it to the "
            "property's declared Godot type (the same coercion the node group "
            "established; see the command catalog's 'Property value coercion'); "
            "an uncoercible value is a clean error."
        )
    )


class GameSetResult(BaseModel):
    """The result of ``gda game set``: the one runtime property it set (#220).

    The live counterpart of :class:`NodeSetResult` (no ``scene_path``): echoes the
    addressed node's runtime ``path``, the ``property`` set, the declared ``type``
    the CLI value was coerced to, and the coerced ``value`` as JSON — the
    projection ``game get`` reports, so a ``set`` round-trips through a ``get``.
    """

    path: str = Field(description="The addressed node's runtime (absolute) path.")
    property: str
    type: str = Field(
        description="The property's declared Godot type the value was coerced to."
    )
    value: Any = Field(
        description="The coerced value as JSON, as the running node now holds it."
    )


# The `diag` command group (Phase 2, ADR-0019): the RUNNING game's runtime
# diagnostics — its errors and its output log — served LIVE but daemon-served:
# the daemon reads the Session log it launched the engine with (`--log-file`),
# not the harness, and serves it even after the session process has died so a
# crash stays diagnosable (#224). The introspection-only counterpart to `perf`.
_DIAG_LIMIT_DESC = (
    "If set, tail only the most recent N entries (newest last); must be >= 1. "
    "Omit for all entries."
)


class SourceFrame(BaseModel):
    """A source location ``{function, file, line}`` (ADR-0026, #283).

    A small, generic frame model: a function name, the source path it lives in,
    and the line, each ``null`` when the source did not carry it. Shared by a
    :class:`LogRecord`'s ``source`` (the engine's ``at:`` follow-on) and the
    ordered ``callstack`` frames of a :class:`DiagError` (best-effort, never a
    parse failure).
    """

    function: str | None = Field(
        default=None, description="The frame's function name, if known."
    )
    file: str | None = Field(
        default=None,
        description="The frame's source path (e.g. res://main.gd), if known.",
    )
    line: int | None = Field(
        default=None, description="The frame's source line, if known."
    )


class DiagError(BaseModel):
    """One structured runtime error/warning of the running game (#224).

    Parsed from Godot's two-line log format. ``level`` normalizes the engine's
    ``<TYPE>`` (``error`` / ``warning`` / ``script_error`` / ``shader_error``) so
    an agent branches on the severity without parsing prose — warnings are
    included, told apart by ``level``. The location (``function``/``file``/
    ``line``) is filled from the ``   at:`` follow-on when present; a bare error
    leaves them ``null`` (best-effort, never a parse failure). A runtime GDScript
    error additionally carries its ordered ``callstack`` of frames (#283); a bare
    push_error / warning has no backtrace, so ``callstack`` is empty.
    """

    level: str = Field(
        description="Normalized severity: error / warning / script_error / shader_error."
    )
    message: str = Field(description="The error/warning message the engine logged.")
    function: str | None = Field(
        default=None,
        description="The reporting function, if the log had an `at:` line.",
    )
    file: str | None = Field(
        default=None, description="The source path (e.g. res://main.gd), if known."
    )
    line: int | None = Field(default=None, description="The source line, if known.")
    callstack: list[SourceFrame] = Field(
        default_factory=list,
        description=(
            "The ordered call stack (most-recent-first) when the engine emitted a "
            "GDScript backtrace; frame [0] equals the top {function,file,line}. "
            "Empty for a bare push_error / warning."
        ),
    )


class DiagErrorsParams(BaseModel):
    """The params of ``gda diag errors``: read the running game's runtime errors (#224).

    Reads the current Engine session's captured errors. ``limit`` tails the most
    recent N (constrained ``>= 1``); v1 returns the current session's log with no
    incremental offset. Omitting ``limit`` returns all entries.
    """

    limit: int | None = Field(default=None, ge=1, description=_DIAG_LIMIT_DESC)


class DiagErrorsResult(BaseModel):
    """The result of ``gda diag errors``: the running game's structured errors (#224).

    An empty ``errors`` list is a successful empty read (the game logged nothing),
    not an error.
    """

    errors: list[DiagError]


# The `logger` command group (Phase 2, ADR-0019, ADR-0026, #281): the running
# game's STRUCTURED runtime-log stream, daemon-served from the Session log like
# `diag` (`--log-file`, ADR-0022) and so crash-survivable. The passive,
# non-invasive floor of the structured-log protocol — `diag log` (raw) is
# SUPERSEDED by `gda logger tail`, whose default output is structured records.


class LogLevel(str, Enum):
    """The closed, ordered severity of a :class:`LogRecord` (ADR-0026).

    ``debug < info < warning < error`` — a TOTAL order, so ``--level <min>``
    filtering is a well-defined ``>=`` contract (ADR-0004). The engine's finer
    kinds collapse onto it (``WARNING`` -> ``warning``; ``ERROR`` / ``SCRIPT
    ERROR`` / ``SHADER ERROR`` -> ``error``), with the sub-kind kept in
    :class:`LogRecord.origin`.
    """

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class LogOrigin(str, Enum):
    """Where a typed :class:`LogRecord` came from — the sub-kind (ADR-0026).

    Preserves the distinction the closed :class:`LogLevel` collapses: an engine
    error vs a script error vs a shader error (all ``error`` level) vs an opt-in
    ``gda_log()`` record (#282). ``null`` on a plain ``info`` line that carries no
    engine/app origin.
    """

    ENGINE = "engine"
    SCRIPT = "script"
    SHADER = "shader"
    GDA_LOG = "gda_log"


class LogRecord(BaseModel):
    """One structured record of the running game's runtime log (ADR-0026, #281).

    The typed unit of the structured runtime-log channel, parsed from the
    daemon-owned Session log. ``seq`` is a monotonic ordinal in capture order.
    ``level`` is the closed, ordered :class:`LogLevel`. ``message`` is the logged
    text. ``source`` is the ``{function, file, line}`` frame when the engine
    recorded an ``at:`` location (engine errors/warnings), else ``null``.
    ``origin`` names the sub-kind the closed level collapses (``engine`` /
    ``script`` / ``shader`` / ``gda_log``), else ``null`` for a plain ``info``
    line. ``fields`` is an app-supplied structured object — empty here (the passive
    floor); populated only by the opt-in ``gda_log()`` protocol (#282).
    """

    seq: int = Field(description="Monotonic ordinal in capture order (0-based).")
    level: LogLevel = Field(
        description="Closed, ordered severity: debug < info < warning < error."
    )
    message: str = Field(description="The logged message text.")
    source: SourceFrame | None = Field(
        default=None,
        description="The {function, file, line} location when known (engine errors), else null.",
    )
    origin: LogOrigin | None = Field(
        default=None,
        description=(
            "The sub-kind the closed level collapses (engine / script / shader / "
            "gda_log), or null for a plain info line."
        ),
    )
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "App-supplied structured fields; empty for a passively-parsed record, "
            "populated only by the opt-in gda_log() protocol (#282)."
        ),
    )


class LoggerTailParams(BaseModel):
    """The params of ``gda logger tail``: read the running game's structured log (#281).

    Reads the current Engine session's captured log as structured records.
    ``level`` filters by minimum severity over the closed ordering
    ``debug < info < warning < error`` (e.g. ``warning`` excludes ``info`` /
    ``debug``); omit for all severities. ``limit`` tails the most recent N records
    (constrained ``>= 1``) AFTER the level filter; omit for all. ``raw`` skips
    classification, returning every captured line as a verbatim ``info`` record
    (the view the superseded ``diag log`` returned), still as ``LogRecord[]``.
    """

    level: LogLevel | None = Field(
        default=None,
        description=(
            "If set, return only records at or above this minimum severity over the "
            "closed ordering debug < info < warning < error. Omit for all."
        ),
    )
    limit: int | None = Field(default=None, ge=1, description=_DIAG_LIMIT_DESC)
    raw: bool = Field(
        default=False,
        description=(
            "If set, skip classification: return every captured line as a verbatim "
            "`info` record (the superseded `diag log` view), still as LogRecord[]. "
            "Otherwise lines are classified into typed records."
        ),
    )


class LoggerTailResult(BaseModel):
    """The result of ``gda logger tail``: the running game's structured log (#281).

    ``records`` is the whole captured Session log as ``LogRecord[]`` — one record
    per line: engine errors/warnings typed (their ``at:`` folded into ``source``),
    every other line a plain ``info`` record (ADR-0026 decision 2, amended #281).
    With ``--raw`` the same shape carries every line as an unclassified ``info``
    record holding its verbatim text (the view the superseded ``diag log``
    returned). It mirrors how ``diag errors`` delivers ``DiagError[]`` as
    ``DiagErrorsResult.errors``. An empty read is a successful empty result, not an
    error.
    """

    records: list[LogRecord] = Field(
        default_factory=list,
        description="The whole Session log as structured records (LogRecord[]).",
    )


# The per-window frame ceiling a time-windowed live op may request (#223). A
# window collects exactly one sample per frame, so an unbounded N would block the
# one-shot RPC for an unbounded time; this is the same generous ceiling the gda
# harness enforces (``MAX_WINDOW_FRAMES`` in ``harness/gda_harness.gd``). Mirrored
# here so ``PerfMonitorParams.frames`` rejects an over-range value model-side
# (ADR-0015) — the model is the input source of truth for BOTH argv and
# ``--params-json``, so the bound is checked before a request ever reaches the
# harness, which therefore no longer clamps. The mirror is asserted by a harness-
# const test (``tests/test_error_registry.py``).
MAX_WINDOW_FRAMES = 600


class PerfMonitor(BaseModel):
    """One performance monitor as ``gda perf monitors`` snapshots it (Phase 2, #223).

    A single counter from the running game's ``Performance`` singleton: its public
    ``name`` (e.g. ``fps``, ``static_memory``), the Godot ``type`` of the sampled
    value (``float``, as ``Performance.get_monitor`` returns), and its ``value`` as
    JSON. Carried uniformly so an agent reads every monitor through one shape.
    """

    name: str
    type: str = Field(description="The sampled value's Godot type (e.g. float).")
    value: Any = Field(description="The monitor's value as JSON.")


class PerfMonitorsParams(BaseModel):
    """The params of ``gda perf monitors``: none — snapshot all monitors at once.

    Empty: ``perf monitors`` reads the whole instantaneous monitor set of the
    engine session held by ``gda-daemon`` in a single frame (frame-coherent,
    ADR-0020); there is nothing to select.
    """


class PerfMonitorsResult(BaseModel):
    """The result of ``gda perf monitors``: a one-frame performance snapshot (#223).

    The running game's instantaneous ``Performance`` counters — timing, memory,
    object/node counts, render stats, active physics/navigation objects — keyed by
    monitor name, plus the engine ``timestamp`` (ms since session start) the
    snapshot was taken at. Read in one frame, so the values are mutually coherent.
    """

    timestamp: int = Field(
        description="Engine time the snapshot was taken (ms, Time.get_ticks_msec)."
    )
    monitors: dict[str, PerfMonitor] = Field(
        description="The performance monitors, keyed by name."
    )


class PerfMonitorParams(BaseModel):
    """The params of ``gda perf monitor``: watch one node over a frame window (#223).

    Time-windowed: the gda harness collects a per-frame timeline over ``frames``
    frames and returns it as one blocking payload (ADR-0017 one-shot RPC, ADR-0020
    multi-frame). Exactly one of ``property`` / ``signal`` selects what to watch:
    ``property`` records the property's value each frame; ``signal`` records the
    signal's emissions over the window. The node is addressed by its runtime
    (absolute) path, as ``game tree`` reports it.

    The selector rule and the ``frames`` bound are enforced model-side
    (ADR-0015) so BOTH the argv path and ``--params-json`` reject a malformed
    request with the structured ``invalid_params`` error rather than the harness
    silently preferring one selector or clamping an over-range ``frames``.
    """

    node: str = Field(description=_RUNTIME_NODE_DESC)
    property: str | None = Field(
        default=None,
        description="The property to sample each frame (mutually exclusive with --signal).",
    )
    signal: str | None = Field(
        default=None,
        description="The signal whose emissions to record over the window (mutually exclusive with --property).",
    )
    frames: int = Field(
        default=60,
        ge=1,
        le=MAX_WINDOW_FRAMES,
        description=(
            "The number of frames to collect over, 1.."
            f"{MAX_WINDOW_FRAMES} (the gda harness's per-window ceiling). An "
            "over-range value is rejected, not clamped."
        ),
    )

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> "PerfMonitorParams":
        # Exactly one of property/signal selects what to watch. Enforced model-side
        # (ADR-0015) so the argv and --params-json paths agree and the harness is
        # never handed an ambiguous request (it would otherwise silently prefer the
        # signal). Neither set or both set is a usage/invalid-params error.
        if self.property is None and self.signal is None:
            raise ValueError(
                "perf monitor needs exactly one of --property or --signal "
                "(neither was given)."
            )
        if self.property is not None and self.signal is not None:
            raise ValueError(
                "--property and --signal are mutually exclusive; pass exactly one."
            )
        return self


class PerfPropertySample(BaseModel):
    """One per-frame sample of a watched property (``gda perf monitor --property``, #223)."""

    frame: int = Field(description="The 0-based frame index within the window.")
    timestamp: int = Field(description="Engine time the sample was taken (ms).")
    value: Any = Field(description="The property's value as JSON at that frame.")


class PerfSignalEmission(BaseModel):
    """One recorded emission of a watched signal (``gda perf monitor --signal``, #223)."""

    frame: int = Field(description="The frame index the emission landed in.")
    timestamp: int = Field(description="Engine time the emission was recorded (ms).")
    args: list[Any] = Field(
        default_factory=list, description="The emission's arguments as JSON."
    )


class PerfMonitorResult(BaseModel):
    """The result of ``gda perf monitor``: a collected per-frame timeline (#223).

    Carries the watched ``node`` (runtime path), the ``kind`` of timeline
    (``property`` or ``signal``), and the number of ``frames`` collected. For a
    property watch, ``samples`` is the per-frame value timeline and ``emissions``
    is empty; for a signal watch, ``emissions`` is the recorded emissions over the
    window and ``samples`` is empty. The harness reports exactly one of the two.
    """

    node: str = Field(description="The watched node's runtime (absolute) path.")
    kind: str = Field(description="The timeline kind: 'property' or 'signal'.")
    frames: int = Field(description="The number of frames the window collected over.")
    property: str | None = Field(
        default=None, description="The watched property (a property watch only)."
    )
    signal: str | None = Field(
        default=None, description="The watched signal (a signal watch only)."
    )
    samples: list[PerfPropertySample] = Field(
        default_factory=list,
        description="The per-frame property timeline (a property watch only).",
    )
    emissions: list[PerfSignalEmission] = Field(
        default_factory=list,
        description="The recorded signal emissions over the window (a signal watch only).",
    )


# --- input (runtime input simulation into the running game, #221) -------------
#
# Live input injection into the RUNNING game's engine session via the gda harness
# (ADR-0017, ADR-0019). Key/mouse events ride the game's real input flow via the
# root viewport's push_input; actions go through Input.action_press/release. Every
# rule that bounds a request — the modifier set, the mouse button enum, the action
# strength range, and the well-formedness of a sequence event — is enforced
# MODEL-SIDE (ADR-0015), so the argv path and the --params-json path reject the
# same malformed request with one source of truth, before it ever reaches the
# harness. Only two failures are deferred to the harness because they need the
# live engine to decide: a key name the engine cannot resolve to a keycode
# (live_invalid_key) and an action the running InputMap does not declare
# (live_unknown_action). A sequence event whose type the harness does not
# recognize is live_invalid_event_spec — the defensive arm for a request that
# reached the harness without passing the model (a direct daemon caller).

# The keyboard modifier names a key/sequence event may carry, mapped to the
# InputEventKey modifier flag the harness sets. Bounding the set model-side means a
# typo'd modifier ("control" for "ctrl") is a clean usage/invalid_params error, not
# a silently-dropped flag.
INPUT_MODIFIERS = ("shift", "ctrl", "alt", "meta")


class MouseButton(str, Enum):
    """The mouse button a ``gda input mouse-click`` targets (#221).

    The CLI-facing names map to Godot's ``MOUSE_BUTTON_*`` indices harness-side;
    bounding them as an enum makes an unknown button a usage/invalid_params error
    rather than a silently-ignored value.
    """

    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


def _validate_modifiers(modifiers: list[str]) -> list[str]:
    """Reject any modifier outside the known set (the single home of the rule).

    Shared by ``InputKeyParams`` and a sequence key event so the argv and
    ``--params-json`` paths — and a sequence event nested in a JSON object —
    validate modifiers identically (ADR-0015).
    """
    unknown = [m for m in modifiers if m not in INPUT_MODIFIERS]
    if unknown:
        raise ValueError(
            f"unknown modifier(s) {unknown}; allowed: {list(INPUT_MODIFIERS)}."
        )
    return modifiers


class InputKeyParams(BaseModel):
    """The params of ``gda input key``: inject one key event (#221).

    Pushes an ``InputEventKey`` for ``key`` (with any ``modifiers``) into the
    running game's root viewport, so it rides the game's real input flow. ``key``
    is a Godot key name (e.g. ``Right``, ``A``, ``Space``, ``Escape``) the harness
    resolves with ``OS.find_keycode_from_string``; an unresolvable name is the
    typed ``live_invalid_key`` error. By default the event is a press; ``released``
    makes it a release. The modifier set is bounded model-side (ADR-0015).
    """

    key: str = Field(
        min_length=1,
        description="A Godot key name to inject (e.g. Right, A, Space, Escape).",
    )
    modifiers: list[str] = Field(
        default_factory=list,
        description=(
            "Modifier keys held with the key, any of: shift, ctrl, alt, meta."
        ),
    )
    released: bool = Field(
        default=False,
        description="Inject a key RELEASE instead of a press (default: press).",
    )

    @model_validator(mode="after")
    def _check_modifiers(self) -> "InputKeyParams":
        _validate_modifiers(self.modifiers)
        return self


class InputKeyResult(BaseModel):
    """The result of ``gda input key``: the key event the harness injected (#221).

    Echoes the resolved ``keycode`` (so an agent can confirm the name mapped as
    intended), the ``key`` name, the ``modifiers`` applied, and whether it was a
    ``pressed`` event — the live counterpart's confirmation that the event was
    pushed at a frame boundary (ADR-0020).
    """

    kind: str = Field(default="key", description="The injected event kind ('key').")
    key: str = Field(description="The key name that was injected.")
    keycode: int = Field(description="The Godot keycode the name resolved to.")
    modifiers: list[str] = Field(
        default_factory=list, description="The modifier keys held with the key."
    )
    pressed: bool = Field(description="True for a press event, false for a release.")


class InputMouseClickParams(BaseModel):
    """The params of ``gda input mouse-click``: inject a mouse button click (#221).

    Pushes an ``InputEventMouseButton`` at viewport position ``(x, y)`` into the
    running game's root viewport. ``button`` selects which button (left/right/
    middle); ``double`` marks the event a double click. A single-frame op (the
    press is injected at one frame boundary, ADR-0020).
    """

    x: float = Field(description="The click's x position in the viewport.")
    y: float = Field(description="The click's y position in the viewport.")
    button: MouseButton = Field(
        default=MouseButton.LEFT,
        description="Which mouse button to click: left, right, or middle.",
    )
    double: bool = Field(default=False, description="Mark the event a double click.")


class InputMouseMoveParams(BaseModel):
    """The params of ``gda input mouse-move``: inject a mouse motion event (#221).

    Pushes an ``InputEventMouseMotion`` to viewport position ``(x, y)`` into the
    running game's root viewport — the runtime counterpart of moving the cursor
    over the game. A single-frame op.
    """

    x: float = Field(description="The motion's target x position in the viewport.")
    y: float = Field(description="The motion's target y position in the viewport.")


class InputMouseResult(BaseModel):
    """The result of a ``gda input mouse-click`` / ``mouse-move`` op: the mouse event injected (#221).

    Echoes the event ``kind`` (``mouse_click`` or ``mouse_move``), the viewport
    ``position`` it was pushed at as ``[x, y]``, and — for a click — the ``button``
    and whether it was a ``double`` click (both null for a move).
    """

    kind: str = Field(
        description="The injected event kind: 'mouse_click' or 'mouse_move'."
    )
    position: list[float] = Field(
        description="The viewport position the event was injected at, as [x, y]."
    )
    button: str | None = Field(
        default=None, description="The clicked button (a click only); null for a move."
    )
    double: bool | None = Field(
        default=None,
        description="Whether the click was a double click; null for a move.",
    )


class InputActionParams(BaseModel):
    """The params of ``gda input action``: press or release an input action (#221).

    Drives ``Input.action_press`` / ``Input.action_release`` for the named action,
    so the running game observes it through its ``InputMap`` exactly as a real
    binding would fire. ``action`` MUST be declared in the running ``InputMap`` —
    an unknown action is the typed ``live_unknown_action`` error (validated
    harness-side via ``InputMap.has_action``). By default the action is pressed;
    ``release`` releases it instead. ``strength`` is the analog strength of a press,
    0..1; it is ignored on a release.
    """

    action: str = Field(
        min_length=1, description="The input action name (must be in the InputMap)."
    )
    release: bool = Field(
        default=False, description="Release the action instead of pressing it."
    )
    strength: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="The analog press strength, 0..1 (ignored on a release).",
    )


class InputActionResult(BaseModel):
    """The result of ``gda input action``: the action event the harness applied (#221).

    Echoes the ``action`` driven, whether it was a ``pressed`` event, and the
    ``strength`` applied (the press strength; 0.0 on a release) — confirmation the
    action fired against the running ``InputMap`` at a frame boundary (ADR-0020).
    """

    kind: str = Field(
        default="action", description="The injected event kind ('action')."
    )
    action: str = Field(description="The action name that was driven.")
    pressed: bool = Field(description="True for a press, false for a release.")
    strength: float = Field(
        description="The press strength applied (0.0 on a release)."
    )


# The event types a `gda input sequence` may carry. A sequence event reuses the
# single-frame ops' shapes (key / mouse click / mouse move / action) plus a `frame`
# delay; the harness applies each event at its relative frame index. Bounding the
# type model-side keeps an unknown type a usage/invalid_params error rather than a
# request the harness must defend against (it still does, as live_invalid_event_spec).
class InputEventType(str, Enum):
    """The kind of one event in a ``gda input sequence`` (#221)."""

    KEY = "key"
    MOUSE_CLICK = "mouse_click"
    MOUSE_MOVE = "mouse_move"
    ACTION = "action"


class InputSequenceEvent(BaseModel):
    """One event in a ``gda input sequence``, applied at its relative frame (#221).

    A tagged union over the single-frame ops: ``type`` selects the event shape and
    ``frame`` is its 0-based relative frame offset within the window (events due at
    the same frame index are applied together). The type-specific fields mirror the
    single-frame params — ``key``/``modifiers``/``released`` for a key, ``x``/``y``/
    ``button``/``double`` for a mouse click, ``x``/``y`` for a mouse move,
    ``action``/``release``/``strength`` for an action. The required fields per type
    and the shared bounds (modifier set, button enum, strength range) are validated
    model-side (ADR-0015) so a malformed event is rejected before the harness runs.
    """

    model_config = ConfigDict(extra="forbid")

    type: InputEventType = Field(description="The event kind.")
    frame: int = Field(
        default=0,
        ge=0,
        description="The 0-based relative frame offset to apply this event at.",
    )
    # key fields
    key: str | None = Field(default=None, description="A key event's key name.")
    modifiers: list[str] = Field(
        default_factory=list, description="A key event's modifier keys."
    )
    released: bool = Field(
        default=False, description="A key event: inject a release instead of a press."
    )
    # mouse fields
    x: float | None = Field(default=None, description="A mouse event's x position.")
    y: float | None = Field(default=None, description="A mouse event's y position.")
    button: MouseButton | None = Field(
        default=None, description="A mouse-click event's button."
    )
    double: bool = Field(
        default=False, description="A mouse-click event: mark it a double click."
    )
    # action fields
    action: str | None = Field(
        default=None, description="An action event's action name."
    )
    release: bool = Field(
        default=False, description="An action event: release instead of press."
    )
    strength: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="An action event's press strength, 0..1.",
    )

    @model_validator(mode="after")
    def _check_event_shape(self) -> "InputSequenceEvent":
        # Each event type requires its own fields; the shared bounds (modifier set,
        # strength range, button enum) are enforced by the fields above. Enforced
        # model-side (ADR-0015) so the argv JSON and --params-json paths reject the
        # same malformed event before it reaches the harness.
        if self.type is InputEventType.KEY:
            if not self.key:
                raise ValueError("a 'key' sequence event requires 'key'.")
            _validate_modifiers(self.modifiers)
        elif self.type is InputEventType.MOUSE_CLICK:
            if self.x is None or self.y is None:
                raise ValueError("a 'mouse_click' sequence event requires 'x' and 'y'.")
        elif self.type is InputEventType.MOUSE_MOVE:
            if self.x is None or self.y is None:
                raise ValueError("a 'mouse_move' sequence event requires 'x' and 'y'.")
        elif self.type is InputEventType.ACTION:
            if not self.action:
                raise ValueError("an 'action' sequence event requires 'action'.")
        return self


class InputSequenceParams(BaseModel):
    """The params of ``gda input sequence``: inject events across frames (#221).

    A multi-frame op (the time-windowed harness base, #223): ``events`` is a list of
    :class:`InputSequenceEvent`, each applied at its relative ``frame`` index, and
    the whole sequence returns as ONE blocking result (ADR-0017 one-shot RPC). The
    window runs for as many frames as the largest event ``frame`` requires (at least
    one). ``events`` must be non-empty; each event is validated model-side
    (ADR-0015).

    The window the sequence requests — ``max(frame) + 1`` frames — is bounded
    model-side to ``MAX_WINDOW_FRAMES`` (#223). The time-windowed harness base has
    no harness-side timeout (it relies on its driver's model bounds, as
    ``PerfMonitorParams`` enforces via ``frames``), so an unbounded event ``frame``
    would let a single valid request monopolise the serialised live session until
    ``live_timeout``. Rejecting it here makes it a structured ``invalid_params`` on
    ``--params-json`` and a usage error (exit 2) on argv, never a live stall
    (ADR-0015).
    """

    events: list[InputSequenceEvent] = Field(
        min_length=1,
        description="The events to inject, each at its relative frame offset.",
    )

    @model_validator(mode="after")
    def _check_window(self) -> "InputSequenceParams":
        # The window spans one past the largest event frame (mirrors the harness's
        # `max_frame + 1`). Bounding it to MAX_WINDOW_FRAMES — the same per-window
        # ceiling perf enforces — keeps a sequence from holding the single-writer
        # live session for an unbounded number of frames.
        window = max(event.frame for event in self.events) + 1
        if window > MAX_WINDOW_FRAMES:
            raise ValueError(
                f"the sequence requests a {window}-frame window (one past its "
                f"largest event frame), exceeding the maximum of "
                f"{MAX_WINDOW_FRAMES} (the gda harness's per-window ceiling). "
                "Use smaller relative frame offsets."
            )
        return self


class InputSequenceResult(BaseModel):
    """The result of ``gda input sequence``: what the harness injected (#221).

    Echoes the number of ``events`` applied and the number of ``frames`` the window
    spanned (one past the largest event frame), confirming the whole sequence was
    injected over the window at frame boundaries (ADR-0020).
    """

    kind: str = Field(default="sequence", description="The op kind ('sequence').")
    events: int = Field(description="The number of events injected.")
    frames: int = Field(description="The number of frames the window spanned.")


# --- screen (runtime viewport capture, #222) ----------------------------------
# Capture the running game's viewport over the LIVE channel. The harness reads
# `get_viewport().get_texture().get_image()`, PNG-encodes it, and base64s the PNG
# into the ADR-0002 UTF-8 sentinel reply; the CLI decodes it and WRITES the PNG
# under the agent's control. The default return is a written file PATH + dims +
# bytes + format — a 1080p base64 inline is ~MBs of JSON and an N-frame sequence
# would blow the agent's context — so `screen capture` adds `--inline` for the
# base64 and `screen frames` is path-only. The capture needs a windowed session
# (`gda daemon start --windowed`); a headless one is `live_display_unavailable`.


class ScreenCaptureParams(BaseModel):
    """The params of ``gda screen capture``: where to write one viewport frame (#222).

    Captures the running game's current viewport in one frame (frame-coherent,
    ADR-0020). ``output`` is part of the public input contract (ADR-0004) and the
    single source of truth for both the emitted ``input`` schema and ``--params-json``
    parsing (ADR-0015): the CLI decodes the harness's encoded pixels and writes them
    there. It is ``~``-normalized once at the boundary (ADR-0006). The harness op
    itself carries none of these fields — the recipe writes the file CLI-side.
    """

    output: NormalizedPath = Field(
        description="The filesystem path to write the captured PNG frame to."
    )
    inline: bool = Field(
        default=False,
        description="Also embed the base64-encoded PNG in the result (default: path only).",
    )


class ScreenCaptureResult(BaseModel):
    """The result of ``gda screen capture``: a written PNG frame (#222).

    The default return: the ``path`` the decoded PNG was written to, its ``width`` /
    ``height`` in pixels, the on-disk ``bytes``, and the ``format`` (``png``).
    ``inline`` carries the base64 PNG only when ``--inline`` was passed (otherwise
    null) — a single capture may be embedded for an in-context preview, but it is
    opt-in so the default reply stays small.
    """

    path: str = Field(description="The filesystem path the PNG frame was written to.")
    width: int = Field(description="The captured frame's width in pixels.")
    height: int = Field(description="The captured frame's height in pixels.")
    bytes: int = Field(description="The written PNG's size in bytes.")
    format: str = Field(default="png", description="The image format (png).")
    inline: str | None = Field(
        default=None,
        description="The base64-encoded PNG, present only when --inline was passed.",
    )


class ScreenFramesParams(BaseModel):
    """The params of ``gda screen frames``: capture a window of viewport frames (#222).

    Time-windowed (the gda harness's multi-frame base, #223): one viewport frame is
    captured at each of ``frames`` frame boundaries and the whole sequence returns
    as one blocking payload (ADR-0017 one-shot RPC, ADR-0020 multi-frame).
    ``frames`` is bounded to ``MAX_WINDOW_FRAMES`` model-side (ADR-0015) — the same
    per-window ceiling ``perf monitor`` enforces — so an over-range request is a
    structured ``invalid_params`` on both the argv and ``--params-json`` paths, never
    a request the harness must clamp.
    """

    frames: int = Field(
        default=2,
        ge=1,
        le=MAX_WINDOW_FRAMES,
        description=(
            "The number of viewport frames to capture, 1.."
            f"{MAX_WINDOW_FRAMES} (the gda harness's per-window ceiling). An "
            "over-range value is rejected, not clamped."
        ),
    )
    output_dir: NormalizedPath = Field(
        description=(
            "The directory to write the captured PNG frames into (frame_NNNN.png). "
            "Part of the input contract (ADR-0004/ADR-0015), ~-normalized (ADR-0006)."
        )
    )


class ScreenFrame(BaseModel):
    """One captured frame in a ``gda screen frames`` sequence (#222).

    The path-only per-frame projection: the ``path`` the decoded PNG was written
    to, its ``width`` / ``height``, on-disk ``bytes``, and ``format``. No base64 —
    an N-frame sequence is path-only so it never blows the agent's context.
    """

    path: str = Field(
        description="The filesystem path this frame's PNG was written to."
    )
    width: int = Field(description="The frame's width in pixels.")
    height: int = Field(description="The frame's height in pixels.")
    bytes: int = Field(description="The written PNG's size in bytes.")
    format: str = Field(default="png", description="The image format (png).")


class ScreenFramesResult(BaseModel):
    """The result of ``gda screen frames``: the written PNG sequence (#222).

    Carries the ``count`` of frames captured and the per-frame ``frames`` list, each
    a written PNG path (path-only, ADR-0019 distinct output schema from the single
    ``screen capture``). The window collects one frame per frame boundary over the
    requested count (ADR-0020 multi-frame).
    """

    count: int = Field(description="The number of frames captured over the window.")
    frames: list[ScreenFrame] = Field(
        description="The captured frames, in window order, each a written PNG path."
    )


class DaemonStartParams(BaseModel):
    """The params of ``gda daemon start``: its engine session's display mode and scene.

    The project is the ``--project`` context. ``windowed`` is a START-TIME declared
    mode (ADR-0017 refined by #222) — the daemon launches its engine session windowed
    (no ``--headless``) so a ``screen`` capture op has a real ``DisplayServer`` to read
    pixels from; default false keeps the cheap non-visual sessions (``game tree``,
    ``perf``, ``diag``) headless. ``scene`` is a START-TIME selector (ADR-0017 amended
    by #278): when set the daemon boots the session on that chosen scene via Godot's
    ``--scene`` engine option (before ``--path``) instead of the project's
    ``main_scene``; default null runs ``main_scene`` unchanged. Both modes are fixed
    for the session's life (ADR-0020 single session) — NOT switched mid-session.
    """

    windowed: bool = Field(
        default=False,
        description=(
            "Launch the engine session windowed (no --headless) so `screen` capture "
            "ops have a display; default headless. Requires a display/Xvfb on a "
            "headless host."
        ),
    )
    scene: str | None = Field(
        default=None,
        description=(
            "Boot the engine session on this scene (a `res://…` path or a `uid://…` "
            "value, per Godot's `--scene`) instead of the project's main_scene; "
            "default null runs main_scene unchanged. A non-existent scene is a typed "
            "`live_scene_not_found` error, never a silent fall back to main_scene."
        ),
    )


class DaemonStartResult(BaseModel):
    """The result of ``gda daemon start``: the live context it brought up (ADR-0017)."""

    pid: int = Field(description="The gda-daemon process id.")
    socket_path: str = Field(
        description="The per-project CLI socket the daemon listens on."
    )
    installed_harness: bool = Field(
        description="Whether this start installed or updated the harness autoload (ADR-0018)."
    )
    harness_synced: bool = Field(
        default=False,
        description=(
            "Whether this start re-materialized the harness to the running gda's "
            "version because the installed copy declared an older one — true only "
            "on a real version-mismatch rewrite, not merely adding the autoload "
            "entry (#225, ADR-0018)."
        ),
    )
    harness_version: str = Field(
        default="",
        description="The gda harness version now installed in the project (#225).",
    )
    windowed: bool | None = Field(
        default=None,
        description=(
            "Whether the engine session was launched windowed (no --headless), the "
            "mode a `screen` capture op requires. The launched mode on a fresh start; "
            "**null** on an idempotent already-running start, which does not relaunch "
            "the session and cannot re-derive the running daemon's launch-time mode "
            "from the pidfile — null means 'not determined here', not 'headless' "
            "(#222, PR #248 review)."
        ),
    )
    already_running: bool = Field(
        description="Whether a daemon was already running, so start was a no-op."
    )


class DaemonStopParams(BaseModel):
    """The params of ``gda daemon stop``: none."""


class DaemonStopResult(BaseModel):
    """The result of ``gda daemon stop``: whether a running daemon was torn down."""

    stopped: bool = Field(
        description="Whether a running daemon was stopped (False if none was running)."
    )
    pid: int | None = Field(
        default=None, description="The stopped daemon's pid, if one was running."
    )


class DaemonStatusParams(BaseModel):
    """The params of ``gda daemon status``: none."""


class DaemonStatusResult(BaseModel):
    """The result of ``gda daemon status``: whether a per-project daemon is up."""

    running: bool = Field(
        description="Whether a gda-daemon is running for the project."
    )
    pid: int | None = Field(
        default=None, description="The running daemon's pid, if any."
    )
    socket_path: str = Field(description="The per-project CLI socket path.")
    windowed: bool | None = Field(
        default=None,
        description=(
            "Whether the running daemon was launched windowed (no --headless), the "
            "mode a `screen` capture op requires — read over the daemon's STATUS_OP, "
            "the running daemon being the authority for its launch-time mode (#251). "
            "**null** when the mode is undetermined: either no daemon is running "
            "(alongside `running: false`), or a daemon is running (`running: true`) "
            "but its bounded STATUS_OP round trip missed transiently."
        ),
    )


class DaemonUninstallParams(BaseModel):
    """The params of ``gda daemon uninstall``: none (the project is the --project context)."""


class DaemonUninstallResult(BaseModel):
    """The result of ``gda daemon uninstall``: the paired harness removal (ADR-0018, #225)."""

    removed: bool = Field(
        description=(
            "Whether the harness autoload and files were removed; False is the "
            "idempotent no-op when no harness was installed (mirrors daemon stop)."
        )
    )
