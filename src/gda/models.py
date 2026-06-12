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
    """A command's self-description: its ``input`` and ``output`` JSON Schemas (ADR-0004).

    ``--schema`` emits this. Both halves are derived from the command's typed
    models via :meth:`of`, so the contract is never hand-maintained: ``input``
    from the params model, ``output`` from the same result model that backs
    ``--json``. ``gda-mcp`` later maps ``input`` → ``inputSchema`` and ``output``
    → ``outputSchema`` mechanically.
    """

    input: dict[str, Any]
    output: dict[str, Any]

    @classmethod
    def of(
        cls, input_model: type[BaseModel], output_model: type[BaseModel]
    ) -> "CommandSchema":
        """Derive the contract from a command's params and result models."""
        return cls(
            input=input_model.model_json_schema(),
            output=output_model.model_json_schema(),
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


class ListedNode(BaseModel):
    """One node of ``gda node list``'s tree: name, type, node path, children.

    Like ``SceneNode`` but each node also carries its node path relative to the
    scene root ('.' for the root itself) — the address an agent feeds back into
    other node commands (e.g. ``node add --parent``).
    """

    name: str
    type: str
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


class EngineVersion(BaseModel):
    """The Godot engine version, as reported by ``Engine.get_version_info()``.

    This is the result model of ``gda info``.
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
