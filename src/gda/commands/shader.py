"""The ``shader`` command group: Godot shader files (.gdshader) as the domain object.

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderers, its ``HeadlessCommand`` descriptors
(ADR-0023), and its Typer command bodies, and mounts them on the root app
through :func:`register`. Besides the shared machinery it imports downward —
the dispatch tail (``gda.dispatch``), the descriptor machinery (``gda.headless``)
and the cross-command contract core (``gda.models``) — it takes one sanctioned
sibling edge of ADR-0040 §5: ``gda.commands.script`` for the ``ScriptSetMode``
edit interface (``shader set`` reuses ``script set``'s three mutually-exclusive
edit modes rather than re-deriving them, issue #115). The edge is one-way:
``script`` never imports ``shader``.
"""

from typing import Optional, Protocol, runtime_checkable

import typer
from pydantic import BaseModel, Field, model_validator

from gda.commands.script import ScriptSetMode, resolve_set_mode
from gda.dispatch import dispatch_domain, params_or_bad_parameter
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.models import CREATED_DIRS_DESC, NormalizedPath


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
    created_dirs: list[str] = Field(description=CREATED_DIRS_DESC)


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


@runtime_checkable
class ShaderMetadata(Protocol):
    """The shared human-facing surface of every shader result type.

    A structural (typing-only) interface over the ``path``/``shader_type`` that
    :class:`ShaderCreateResult`, :class:`ShaderGetResult`
    and :class:`ShaderSetResult` all carry, so the shader-metadata
    renderer types against one surface rather than a three-way union (mirrors
    :class:`~gda.commands.script.ScriptMetadata`).
    """

    path: str
    shader_type: str | None


def render_shader_metadata(shader: ShaderMetadata) -> str:
    """Render a shader's path plus its shader_type for humans.

    Reads the shared :class:`ShaderMetadata` surface, so it serves every shader
    result type without naming the union.
    """
    if shader.shader_type is not None:
        return f"{shader.path} (shader_type {shader.shader_type})"
    return shader.path


def render_shader_create(created: "ShaderCreateResult") -> str:
    """Render a created shader as ``created <metadata>``."""
    return f"created {render_shader_metadata(created)}"


def render_shader_get(got: "ShaderGetResult") -> str:
    """Render a read shader as its metadata line followed by its source."""
    return "\n".join([render_shader_metadata(got), got.source])


def render_shader_set(edited: "ShaderSetResult") -> str:
    """Render an edited shader as ``set <metadata>``."""
    return f"set {render_shader_metadata(edited)}"


SHADER_CREATE_COMMAND: HeadlessCommand[ShaderCreateResult] = HeadlessCommand(
    operation="shader-create",
    input_model=ShaderCreateParams,
    output_model=ShaderCreateResult,
    render=render_shader_create,
)

SHADER_GET_COMMAND: HeadlessCommand[ShaderGetResult] = HeadlessCommand(
    operation="shader-get",
    input_model=ShaderGetParams,
    output_model=ShaderGetResult,
    render=render_shader_get,
)

SHADER_SET_COMMAND: HeadlessCommand[ShaderSetResult] = HeadlessCommand(
    operation="shader-set",
    input_model=ShaderSetParams,
    output_model=ShaderSetResult,
    render=render_shader_set,
)


# The asset-file groups (issue #115): headless authoring of the asset-file types.
# A .gdshader is plain shader source authored as text (create / get / set author
# the file directly and never load or compile the shader at the operation level),
# while theme create (gda.commands.theme) produces a loadable .tres Theme resource
# (engine-backed) — the same file-level vs engine-backed split the script group
# draws between create/get/set and attach/validate. This bounds the operation, not
# the run: every command still goes through the headless runner, so resolving
# --project still constructs the project's autoloads at engine startup (ADR-0009).
_app = typer.Typer(help="Act on shader files (.gdshader).", no_args_is_help=True)


@_app.command(cls=SHADER_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .gdshader path to write."),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help=(
            "Verbatim shader source to write. Mutually exclusive with "
            "--shader-type; when omitted, a minimal template declaring the "
            "--shader-type is written."
        ),
    ),
    shader_type: Optional[str] = typer.Option(
        None,
        "--shader-type",
        help=(
            "Shader type for the built-in template's 'shader_type' line (e.g. "
            "canvas_item, spatial). Defaults to canvas_item. Ignored — and "
            "rejected — with --content."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SHADER_CREATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .gdshader from a template or verbatim --content."""
    if content is not None and shader_type is not None:
        raise typer.BadParameter("--content and --shader-type are mutually exclusive.")
    dispatch_domain(
        SHADER_CREATE_COMMAND,
        ShaderCreateParams(
            path=path,
            content=content,
            shader_type=shader_type,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="get", cls=SHADER_GET_COMMAND.command_class())
def get_shader(
    path: str = typer.Argument(..., help="The .gdshader file to read."),
    json_output: bool = json_option(),
    schema: bool = SHADER_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a shader's source and report its shader_type metadata."""
    dispatch_domain(
        SHADER_GET_COMMAND,
        ShaderGetParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="set", cls=SHADER_SET_COMMAND.command_class())
def set_shader(
    path: str = typer.Argument(..., help="The .gdshader file to edit."),
    search: Optional[str] = typer.Option(
        None,
        "--search",
        help=(
            "search-replace mode: literal substring to find (not regex); all "
            "occurrences are replaced. Requires --replace."
        ),
    ),
    replace: Optional[str] = typer.Option(
        None,
        "--replace",
        help="search-replace mode: literal replacement text. Requires --search.",
    ),
    start_line: Optional[int] = typer.Option(
        None,
        "--start-line",
        help=(
            "line-range mode: first line to replace (1-based, inclusive). "
            "Requires --content."
        ),
    ),
    end_line: Optional[int] = typer.Option(
        None,
        "--end-line",
        help=(
            "line-range mode: last line to replace (1-based, inclusive); "
            "defaults to --start-line. Requires --content and --start-line."
        ),
    ),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help=(
            "Replacement text: the line span in line-range mode, or the whole "
            "file (full mode) when --start-line is omitted."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SHADER_SET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Edit a .gdshader via search-replace, line-range, or full overwrite."""
    # shader set reuses the script set edit-mode interface (issue #115): the same
    # mutual-exclusion resolver decides the single ScriptSetMode discriminator.
    # The model owns that rule and the argv body does not restate it: the shared
    # builder turns any model-construction failure into the Click usage error
    # (exit 2), so the rule runs once per invocation on both input paths
    # (ADR-0015, issue #713).
    dispatch_domain(
        SHADER_SET_COMMAND,
        params_or_bad_parameter(
            ShaderSetParams,
            path=path,
            search=search,
            replace=replace,
            start_line=start_line,
            end_line=end_line,
            content=content,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``shader`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="shader")
