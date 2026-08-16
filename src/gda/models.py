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
)

from gda.execution import ExecutionKind
from gda.project import is_engine_virtual_path


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

    Which paths are engine-virtual is ADR-0006's rule, owned by
    :func:`gda.project.is_engine_virtual_path` — the same test the project
    containment check reads, so the two cannot disagree about what ``res://``
    means.
    """
    if is_engine_virtual_path(path):
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
VALUE_PROJECTION_DESC = (
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
SET_ECHO_VALUE_DESC = (
    "The coerced value as JSON, in the same recursive value projection the "
    "corresponding get reports (ADR-0035)."
)

# node/resource set additionally have the ADR-0033 Object-typed set path;
# its echo flows through the same projection, so the assigned resource echoes
# as the reference projection a subsequent get reads back.
OBJECT_SET_ECHO_DESC = SET_ECHO_VALUE_DESC + (
    " Setting an Object-typed property by res:// path (ADR-0033) echoes the "
    "assigned resource as a ReferenceProjection ({type, resource_path}) — "
    "the same shape a subsequent get reads back."
)

# Stays in the shared core (ADR-0040 §4): FIVE groups report the SAME
# parent-directory side effect on their create results — ``scene``, ``script``,
# ``resource``, ``shader`` and ``theme`` — so the wording is a cross-command
# contract, not one group's constant. (``export run`` reports a DIFFERENT thing:
# the OUTPUT parent directories it made, so it keeps its own description.)
CREATED_DIRS_DESC = (
    "Parent directories created before saving, from outermost to innermost."
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


def projected_value_schema_extra(schema: dict[str, Any]) -> None:
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


# Stays in the shared core (ADR-0040 §4): three groups read the SAME typed
# property shape — ``node get``, ``resource get`` and the live ``game get`` — so
# it is a cross-command contract, not one group's model.
class NodeProperty(BaseModel):
    """One of a node's properties as ``gda node get`` reports it (issue #55).

    ``type`` is the property's declared Godot type name (``int``, ``Vector2``,
    ``Color``, …). ``value`` is the property's value in its recursive JSON
    value projection (ADR-0035) — left as arbitrary JSON so every Godot type
    is carried uniformly through one field: a scalar stays a scalar, a Vector2
    becomes ``[x, y]``, a Dictionary a JSON object, an Object a
    :class:`ReferenceProjection` / :class:`InlineValueProjection` / ``str()``
    fallback.
    """

    name: str
    type: str = Field(
        description="The property's declared Godot type name (e.g. int, Vector2, Color)."
    )
    value: Any = Field(
        description="The property's value as JSON. " + VALUE_PROJECTION_DESC,
        json_schema_extra=projected_value_schema_extra,
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


# Stays in the shared core (ADR-0040 §4): TWO groups address a runtime node with
# the SAME description — ``game`` (get/rect/set) and ``perf`` (monitor) — so it is
# a cross-command contract, not one group's constant.
# The runtime node address: ABSOLUTE, as ``game tree`` reports it via the live
# tree's ``Node.get_path()``. This is the live counterpart of the node group's
# root-relative ``node`` param — the headless resolver rejects absolute paths,
# so the live layer addresses off the running SceneTree root instead (ADR-0019).
RUNTIME_NODE_DESC = (
    "Runtime node path as `game tree` reports it (absolute, e.g. /root/Main/Player)."
)


# Stays in the shared core (ADR-0040 §4): THREE groups bound a request against the
# SAME per-window ceiling — ``perf`` (monitor --frames), ``input`` (the sequence
# window) and ``screen`` (frames --frames) — so it is a cross-command contract, not
# one group's constant.
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
