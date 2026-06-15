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
