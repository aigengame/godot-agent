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
