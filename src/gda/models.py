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

    ``gda-mcp`` later maps ``input`` → ``input_schema`` and ``output`` →
    ``output_schema`` (success / ``structured_content``) mechanically. The
    ``error`` half is kept OUT of ``output``: a non-zero-exit failure maps to
    MCP's separate ``is_error`` channel, so the adapter must not fold ``error``
    into ``output_schema``.

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


# The one read-side value projection every value gda emits goes through
# (ADR-0035): the shared field description for the dynamically-shaped `value`
# fields. The field itself stays `Any` — a value's shape is not statically
# knowable, a deliberate, bounded exception to ADR-0004's model-driven-output
# rule — so the stable parts are surfaced here and by the two named projection
# models (ReferenceProjection / InlineValueProjection) below.
_VALUE_PROJECTION_DESC = (
    "Rendered through the one recursive read-side value projection "
    "(ADR-0035): a scalar for a scalar type; a flat number list for a "
    "fixed-shape type (Vector2 → [x, y], Color → [r, g, b, a]); a JSON "
    "object for a Dictionary (keys stringified); a JSON array for an Array "
    "or packed array (elements re-projected). An Object value renders as a "
    "ReferenceProjection ({type, resource_path}) for a Resource with a "
    "res:// path, an InlineValueProjection ({type, …storage properties}) "
    "for a whitelisted path-less value Object (InputEvent subclasses), or "
    "its str() form for any other Object — branch on the presence of "
    "resource_path."
)

# The set-echo variant: the set commands echo the value they set through the
# SAME projection (they read it back off the subject and _jsonify it).
_SET_ECHO_VALUE_DESC = (
    "The coerced value as JSON, in the same recursive value projection the "
    "corresponding get reports (ADR-0035)."
)

_LIVE_SET_READ_BACK_VALUE_DESC = (
    "The observed read-back value as JSON, in the same recursive value projection "
    "that game get reports (ADR-0035)."
)

# node/resource set additionally have the ADR-0033 Object-typed set path;
# its echo flows through the same projection, so the assigned resource echoes
# as the reference projection a subsequent get reads back.
_OBJECT_SET_ECHO_DESC = _SET_ECHO_VALUE_DESC + (
    " Setting an Object-typed property by res:// path (ADR-0033) echoes the "
    "assigned resource as a ReferenceProjection ({type, resource_path}) — "
    "the same shape a subsequent get reads back."
)


class ReferenceProjection(BaseModel):
    """A Resource value named by type and ``res://`` path (ADR-0035).

    The read-side mirror of ADR-0033's write-side ``res://`` reference: a
    value that is a ``Resource`` with a ``res://`` ``resource_path`` projects
    to ``{type, resource_path}`` — never inlined, so a resource-valued read
    stays a small, bounded payload and read/write name an external resource
    the same way. Distinguished from :class:`InlineValueProjection` by the
    PRESENCE of ``resource_path`` (an inline projection excludes the Resource
    base bookkeeping, so it never carries one).
    """

    type: str = Field(
        description="The referenced resource's engine class (e.g. RectangleShape2D)."
    )
    resource_path: str = Field(
        description=(
            "The res:// path naming the resource; a sub-resource path "
            "(res://scene.tscn::id) counts as a reference too."
        )
    )


class InlineValueProjection(BaseModel):
    """A whitelisted path-less value Object projected inline (ADR-0035).

    A small path-less value ``Object`` on the projection whitelist
    (``InputEvent`` subclasses initially — e.g. the ``InputEventKey`` entries
    of an InputMap action) projects to ``{"type": <Class>, <its storage
    properties, each re-projected>}``. The ``Object``/``Resource`` base
    bookkeeping (``resource_path``, ``resource_name``,
    ``resource_local_to_scene``, ``script``) is excluded — so an inline
    projection never masquerades as a :class:`ReferenceProjection` — and the
    ``type`` discriminator is assigned last, shadowing any storage property of
    that name. The storage properties vary per class, hence ``extra="allow"``.
    """

    model_config = ConfigDict(extra="allow")

    type: str = Field(
        description="The value Object's engine class (e.g. InputEventKey)."
    )


def _projected_value_schema_extra(schema: dict[str, Any]) -> None:
    """Attach the named Object-projection shapes to a projected ``value`` field.

    A projected ``value`` stays ``Any`` — its shape is not statically knowable,
    the ADR-0035 bounded exception to ADR-0004 — so the stable projection
    shapes cannot ride along as the field's type (a union would materialize
    matching dicts as model instances and change the runtime payload).
    Attaching their schemas as the field's ``$defs`` keeps ReferenceProjection
    and InlineValueProjection named and consumable in every emitted command
    schema (``--schema`` / gda-mcp) instead of prose-only.
    """
    schema["$defs"] = {
        "ReferenceProjection": ReferenceProjection.model_json_schema(),
        "InlineValueProjection": InlineValueProjection.model_json_schema(),
    }


class NodeProperty(BaseModel):
    """One of a node's properties as ``gda node get`` reports it (issue #55).

    ``type`` is the property's declared Godot type name (``int``, ``Vector2``,
    ``Color``, …). ``value`` is the property's value in its recursive JSON
    value projection (ADR-0035) — left as arbitrary JSON so every Godot type
    is carried uniformly through one field: a scalar stays a scalar, a Vector2
    becomes ``[x, y]``, a Dictionary a JSON object, an Object a
    :class:`ReferenceProjection` / :class:`InlineValueProjection` / ``str()``
    fallback.

    Stays in the shared core (ADR-0040 §4): three groups read the SAME typed
    property shape — ``node get``, ``resource get`` and the live ``game get`` —
    so it is a cross-command contract, not one group's model.
    """

    name: str
    type: str = Field(
        description="The property's declared Godot type name (e.g. int, Vector2, Color)."
    )
    value: Any = Field(
        description="The property's value as JSON. " + _VALUE_PROJECTION_DESC,
        json_schema_extra=_projected_value_schema_extra,
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

    Stays in the shared core (ADR-0040 §4): its name says ``Resource`` but its
    group does not — it is ``project find-references``'s result shape, so it
    belongs beside :class:`ProjectFindReferencesResult`, not in the ``resource``
    group's module.
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


# Stays in the shared core (ADR-0040 §4): two groups read the SAME engine-version
# shape — the ``info`` meta command and ``project info`` — so it is a
# cross-command contract, not one group's model.
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


class GameNode(BaseModel):
    """One node of the RUNNING game's runtime scene tree (Phase 2, ADR-0019).

    The runtime counterpart of :class:`~gda.commands.scene.SceneNode`: ``gda game
    tree`` reports the live ``SceneTree`` after ``_ready`` and dynamic
    instantiation, so it carries the runtime node ``path`` alongside
    ``name``/``type``/``children``. Distinct from the on-disk ``.tscn`` read by
    ``scene get`` (a different object, ADR-0019).
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
    """The params of ``gda game get``: read a running node's runtime properties (#220, #422).

    The live counterpart of :class:`NodeGetParams`, addressed by the runtime
    (absolute) node path rather than a ``.tscn`` file + root-relative node path:
    there is no file, only the live SceneTree of the engine session. ``property``
    optionally narrows the read to one property. When explicitly named, a plain
    attached-script variable is addressable after storage properties are checked;
    unfiltered reads still list only the storage-property surface.
    """

    node: str = Field(description=_RUNTIME_NODE_DESC)
    property: str | None = Field(
        default=None,
        description=(
            "If set, read only this one property. Explicit names first match the "
            "storage surface, then attached-script variables; unset keeps the "
            "default storage-property listing."
        ),
    )


class GameGetResult(BaseModel):
    """The result of ``gda game get``: a running node's runtime properties (#220, #422).

    The live counterpart of :class:`NodeGetResult` (no ``scene_path`` — there is
    no file): echoes the addressed node (runtime ``path``/``name``/``type``) and
    its storage properties, each a typed :class:`NodeProperty`; an explicitly named
    plain attached-script variable can also appear as the single returned property.
    Each value goes through the same recursive value projection the headless reads
    use (ADR-0035): compound values arrive structured, and a whitelisted value Object
    (an ``InputEvent`` subclass) as an :class:`InlineValueProjection` — while a
    NON-whitelisted runtime Object (e.g. a live ``Node``-valued property) stays the
    ``str()`` fallback, the whitelist being the boundary that keeps the shared
    projection safe on the live side.
    """

    path: str = Field(description="The addressed node's runtime (absolute) path.")
    name: str
    type: str = Field(description="The node's engine class (e.g. CharacterBody2D).")
    properties: list[NodeProperty]


class GameRectParams(BaseModel):
    """The params of ``gda game rect``: read a running Control's rendered rect (#419).

    Addressed by the same runtime (absolute) node path as ``game get``. The
    command is intentionally Control-specific: layout-dependent geometry is not
    a storage-property read and must come from ``Control.get_global_rect()`` in
    the running SceneTree.
    """

    node: str = Field(description=_RUNTIME_NODE_DESC)


class GameRectResult(BaseModel):
    """The result of ``gda game rect``: a Control's rendered viewport-space rect.

    ``position`` and ``size`` are the two Vector2 projections from
    ``Control.get_global_rect()``; no Rect2 projection is added to the shared
    value projection surface.
    """

    path: str = Field(description="The addressed node's runtime (absolute) path.")
    name: str
    type: str = Field(description="The node's engine class (e.g. VBoxContainer).")
    position: list[float] = Field(
        description="The rendered viewport-space top-left point, as [x, y]."
    )
    size: list[float] = Field(
        description="The rendered viewport-space size, as [width, height]."
    )


class GameSetParams(BaseModel):
    """The params of ``gda game set``: mutate a running node's runtime property (#220, #422).

    The live counterpart of :class:`NodeSetParams`, addressed by the runtime
    (absolute) node path. ``property`` names the property; ``value`` is the CLI
    string value, coerced to the property's declared or inferred target Godot type
    by the gda harness (the SAME coercion table headless ``node set`` uses) and
    applied at a frame boundary (ADR-0020). Explicit names first target storage
    properties, then plain attached-script variables; script-variable mutations
    are bound to the session, not persisted.
    """

    node: str = Field(description=_RUNTIME_NODE_DESC)
    property: str = Field(
        description=(
            "The property to set (e.g. position, visible). Explicit names first "
            "target storage properties, then attached-script variables."
        )
    )
    value: str = Field(
        description=(
            "The value to set, as a string. The gda harness coerces it to the "
            "property's declared or inferred target Godot type (the same coercion "
            "the node group established, including JSON objects for Dictionary and "
            "JSON arrays for Array; see the command catalog's 'Property value "
            "coercion'). For Dictionary/Array JSON values, JSON integer literals "
            "stay int and JSON float literals stay float; typed containers assign "
            "entries through their declared container type. An uncoercible value "
            "is a clean error."
        )
    )


class GameSetResult(BaseModel):
    """The result of ``gda game set``: the one runtime property it set (#220).

    The live counterpart of :class:`NodeSetResult` (no ``scene_path``): echoes the
    addressed node's runtime ``path``, the ``property`` set, the declared ``type``
    the CLI value was coerced to, and the observed read-back ``value`` as JSON —
    the projection ``game get`` reports. ``verified`` reports whether that
    observed value equals the coerced value requested by this command.
    """

    path: str = Field(description="The addressed node's runtime (absolute) path.")
    property: str
    type: str = Field(
        description="The property's declared or inferred target Godot type the value was coerced to."
    )
    value: Any = Field(
        description=(
            "The observed read-back value as JSON, as the running node now holds it. "
            + _LIVE_SET_READ_BACK_VALUE_DESC
        ),
        json_schema_extra=_projected_value_schema_extra,
    )
    verified: bool = Field(
        description=(
            "True when the observed read-back value equals the coerced value requested "
            "by this command; false when the live set completed but the observed "
            "read-back value differs."
        )
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
# root viewport's push_input; actions go through Input.action_press/release. Mouse
# event.position is the reliable injected coordinate; Godot does not expose a
# reliable daemon-session seam for updating Viewport.get_mouse_position() /
# Node2D.get_global_mouse_position(), so those tracked positions may stay stale. Every
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
    press is injected at one frame boundary, ADR-0020). The injected coordinate is
    reliable as ``InputEventMouseButton.position``. Godot does not reliably update
    the engine-tracked mouse position in daemon sessions, so
    ``Viewport.get_mouse_position()`` / ``Node2D.get_global_mouse_position()`` may
    remain stale; read the mouse event position for the injected coordinate.
    """

    x: float = Field(
        description=(
            "The click's x position in the viewport. Read it from the mouse event; "
            "engine-tracked mouse positions may remain stale."
        )
    )
    y: float = Field(
        description=(
            "The click's y position in the viewport. Read it from the mouse event; "
            "engine-tracked mouse positions may remain stale."
        )
    )
    button: MouseButton = Field(
        default=MouseButton.LEFT,
        description="Which mouse button to click: left, right, or middle.",
    )
    double: bool = Field(default=False, description="Mark the event a double click.")


class InputMouseMoveParams(BaseModel):
    """The params of ``gda input mouse-move``: inject a mouse motion event (#221).

    Pushes an ``InputEventMouseMotion`` to viewport position ``(x, y)`` into the
    running game's root viewport — the runtime counterpart of moving the cursor
    over the game. A single-frame op. The injected coordinate is reliable as
    ``InputEventMouseMotion.position``. Godot does not reliably update the
    engine-tracked mouse position in daemon sessions, so
    ``Viewport.get_mouse_position()`` / ``Node2D.get_global_mouse_position()`` may
    remain stale; read the mouse event position for the injected coordinate.
    """

    x: float = Field(
        description=(
            "The motion's target x position in the viewport. Read it from the "
            "mouse event; engine-tracked mouse positions may remain stale."
        )
    )
    y: float = Field(
        description=(
            "The motion's target y position in the viewport. Read it from the "
            "mouse event; engine-tracked mouse positions may remain stale."
        )
    )


class InputMouseResult(BaseModel):
    """The result of a ``gda input mouse-click`` / ``mouse-move`` op: the mouse event injected (#221).

    Echoes the event ``kind`` (``mouse_click`` or ``mouse_move``), the viewport
    ``position`` it was pushed at as ``[x, y]``, and — for a click — the ``button``
    and whether it was a ``double`` click (both null for a move). This echoed
    position mirrors the mouse event's position; engine-tracked mouse positions may
    remain stale.
    """

    kind: str = Field(
        description="The injected event kind: 'mouse_click' or 'mouse_move'."
    )
    position: list[float] = Field(
        description=(
            "The viewport position the event was injected at, as [x, y]. This "
            "mirrors event.position; engine-tracked mouse positions may remain stale."
        )
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
# single-frame ops' shapes (key / mouse click / mouse move / action), plus a
# sequence-only mouse-button phase for press-drag-release gestures, and either a
# process-clock `frame` offset (the original #221 behavior) or a physics-clock
# `physics_frame` offset (#391). Bounding the type model-side keeps an unknown type
# a usage/invalid_params error rather than a request the harness must defend
# against (it still does, as live_invalid_event_spec).
class InputEventType(str, Enum):
    """The kind of one event in a ``gda input sequence`` (#221)."""

    KEY = "key"
    MOUSE_CLICK = "mouse_click"
    MOUSE_BUTTON = "mouse_button"
    MOUSE_MOVE = "mouse_move"
    ACTION = "action"


class InputSequenceEvent(BaseModel):
    """One event in a ``gda input sequence``, applied at its relative clock offset.

    A tagged union over the single-frame ops: ``type`` selects the event shape and
    either ``frame`` or ``physics_frame`` places it within the window. ``frame`` is
    the original harness/process-frame clock, advanced by the harness ``_process``
    loop; it is not Godot's fixed physics clock. ``physics_frame`` is the explicit
    physics-clock offset, advanced by Godot ``_physics_process`` ticks, for sequences
    that need deterministic simulation-duration input holds. Events due at the same
    clock index are applied together. The type-specific fields mirror the
    single-frame params — ``key``/``modifiers``/``released`` for a key, ``x``/``y``/
    ``button``/``double`` for a mouse click, ``x``/``y``/``button`` plus exactly one
    ``pressed``/``release`` phase for a mouse-button event, ``x``/``y`` for a mouse
    move, ``action``/``release``/``strength`` for an action. The required fields per
    type and the shared bounds (modifier set, button enum, strength range) are
    validated model-side (ADR-0015) so a malformed event is rejected before the
    harness runs.
    Mouse event coordinates are reliable as the event's ``position``; engine-tracked
    mouse positions may remain stale for sequence mouse events too.
    """

    model_config = ConfigDict(extra="forbid")

    type: InputEventType = Field(description="The event kind.")
    frame: int | None = Field(
        default=None,
        ge=0,
        description=(
            "The 0-based relative harness/process-frame offset to apply this event at. "
            "This is the original `input sequence` clock, driven by the harness "
            "`_process` loop; it is not Godot's fixed physics clock. Omit both "
            "`frame` and `physics_frame` to use process frame 0."
        ),
    )
    physics_frame: int | None = Field(
        default=None,
        ge=0,
        description=(
            "The 0-based relative physics-frame offset to apply this event at, driven "
            "by Godot `_physics_process` ticks. Use this instead of `frame` when an "
            "input hold must map to a deterministic physics simulation duration."
        ),
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
    x: float | None = Field(
        default=None,
        description=(
            "A mouse event's x position. Read it from the event; engine-tracked "
            "mouse positions may remain stale."
        ),
    )
    y: float | None = Field(
        default=None,
        description=(
            "A mouse event's y position. Read it from the event; engine-tracked "
            "mouse positions may remain stale."
        ),
    )
    button: MouseButton | None = Field(
        default=None,
        description=(
            "A mouse-click or mouse-button event's button; defaults to left for "
            "mouse-button events."
        ),
    )
    double: bool = Field(
        default=False, description="A mouse-click event: mark it a double click."
    )
    pressed: bool | None = Field(
        default=None,
        description=(
            "A mouse-button event: press the button. Use exactly one of `pressed` "
            "or `release`."
        ),
    )
    # action fields
    action: str | None = Field(
        default=None, description="An action event's action name."
    )
    release: bool = Field(
        default=False,
        description=(
            "An action event: release instead of press. A mouse-button event: "
            "release the button; use exactly one of `pressed` or `release`."
        ),
    )
    strength: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="An action event's press strength, 0..1.",
    )

    @model_validator(mode="after")
    def _check_event_shape(self) -> "InputSequenceEvent":
        # Each event uses exactly one clock. No supplied clock keeps the original
        # shorthand: process frame 0. Enforced model-side (ADR-0015) so argv JSON and
        # --params-json reject the same malformed event before it reaches the harness.
        if self.frame is not None and self.physics_frame is not None:
            raise ValueError(
                "a sequence event cannot set both 'frame' and 'physics_frame'."
            )
        if self.frame is None and self.physics_frame is None:
            self.frame = 0
        if self.type is not InputEventType.MOUSE_BUTTON and self.pressed is not None:
            raise ValueError(
                "'pressed' is only valid on a 'mouse_button' sequence event."
            )
        # Each event type requires its own fields; the shared bounds (modifier set,
        # strength range, button enum) are enforced by the fields above.
        if self.type is InputEventType.KEY:
            if not self.key:
                raise ValueError("a 'key' sequence event requires 'key'.")
            _validate_modifiers(self.modifiers)
        elif self.type is InputEventType.MOUSE_CLICK:
            if self.x is None or self.y is None:
                raise ValueError("a 'mouse_click' sequence event requires 'x' and 'y'.")
        elif self.type is InputEventType.MOUSE_BUTTON:
            if self.x is None or self.y is None:
                raise ValueError(
                    "a 'mouse_button' sequence event requires 'x' and 'y'."
                )
            if self.pressed is None and not self.release:
                raise ValueError(
                    "a 'mouse_button' sequence event requires 'pressed' or 'release'."
                )
            if self.pressed is False:
                raise ValueError(
                    "a 'mouse_button' sequence event uses 'pressed: true' to press; "
                    "use 'release: true' to release."
                )
            if self.pressed is True and self.release:
                raise ValueError(
                    "a 'mouse_button' sequence event cannot set both 'pressed' and "
                    "'release'."
                )
            if self.release:
                self.pressed = False
            if self.button is None:
                self.button = MouseButton.LEFT
        elif self.type is InputEventType.MOUSE_MOVE:
            if self.x is None or self.y is None:
                raise ValueError("a 'mouse_move' sequence event requires 'x' and 'y'.")
        elif self.type is InputEventType.ACTION:
            if not self.action:
                raise ValueError("an 'action' sequence event requires 'action'.")
        return self


class InputSequenceParams(BaseModel):
    """The params of ``gda input sequence``: inject events across process or physics frames.

    A multi-frame op (the time-windowed harness base, #223): ``events`` is a list of
    :class:`InputSequenceEvent`, each applied at either its relative ``frame`` index
    (the original harness/process-frame clock) or its relative ``physics_frame``
    index (the explicit Godot physics clock added for #391), and the whole sequence
    returns as ONE blocking result (ADR-0017 one-shot RPC). A sequence must use one
    clock throughout; mixing ``frame`` and ``physics_frame`` in the same request is
    rejected. The window runs for as many selected-clock frames as the largest event
    offset requires (at least one). ``events`` must be non-empty; each event is
    validated model-side (ADR-0015).

    The window the sequence requests — ``max(offset) + 1`` frames on the selected
    clock — is bounded model-side to ``MAX_WINDOW_FRAMES`` (#223). The time-windowed
    harness base has no harness-side timeout (it relies on its driver's model
    bounds, as ``PerfMonitorParams`` enforces via ``frames``), so an unbounded event
    offset would let a single valid request monopolise the serialised live session
    until ``live_timeout``. Rejecting it here makes it a structured
    ``invalid_params`` on ``--params-json`` and a usage error (exit 2) on argv, never
    a live stall (ADR-0015).
    """

    events: list[InputSequenceEvent] = Field(
        min_length=1,
        description=(
            "The events to inject, each at its relative process-clock `frame` "
            "offset or physics-clock `physics_frame` offset."
        ),
    )

    @model_validator(mode="after")
    def _check_window(self) -> "InputSequenceParams":
        # The window spans one past the largest event offset on exactly one clock
        # (mirrors the harness's `max_offset + 1`). Bounding it to MAX_WINDOW_FRAMES
        # — the same per-window ceiling perf enforces — keeps a sequence from
        # holding the single-writer live session for an unbounded number of frames.
        uses_physics = [event.physics_frame is not None for event in self.events]
        if any(uses_physics) and not all(uses_physics):
            raise ValueError(
                "a sequence cannot mix process-clock 'frame' events with "
                "physics-clock 'physics_frame' events."
            )
        selected_clock = "physics_frame" if all(uses_physics) else "frame"
        window = (
            max(
                (
                    event.physics_frame
                    if selected_clock == "physics_frame"
                    else event.frame
                )
                or 0
                for event in self.events
            )
            + 1
        )
        if window > MAX_WINDOW_FRAMES:
            raise ValueError(
                f"the sequence requests a {window}-frame window (one past its "
                f"largest {selected_clock} offset), exceeding the maximum of "
                f"{MAX_WINDOW_FRAMES} (the gda harness's per-window ceiling). "
                "Use smaller relative offsets."
            )
        return self


class InputSequenceResult(BaseModel):
    """The result of ``gda input sequence``: what the harness injected (#221).

    Echoes the ``clock`` used (``process`` for the original harness/process-frame
    clock, ``physics`` for the explicit Godot physics clock), the number of
    ``events`` applied, and the number of ``frames`` the window spanned on that
    clock (one past the largest selected offset), confirming the whole sequence was
    injected over the window at frame boundaries (ADR-0020).
    """

    kind: str = Field(default="sequence", description="The op kind ('sequence').")
    clock: str = Field(
        default="process",
        description=(
            "The sequence clock: 'process' for harness/process-frame offsets, or "
            "'physics' for Godot physics-frame offsets."
        ),
    )
    events: int = Field(description="The number of events injected.")
    frames: int = Field(
        description="The number of selected-clock frames the window spanned."
    )


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
