"""The ``resource`` command group: Godot resource files (.tres) as the domain object.

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderers, its ``HeadlessCommand`` descriptors
(ADR-0023), and its Typer command bodies, and mounts them on the root app through
:func:`register`. It imports the shared machinery downward — the dispatch tail
(``gda.surface.dispatch``), the descriptor machinery (``gda.surface.descriptor``), the
cross-command contract core (``gda.core.contract``, for the shared
:class:`~gda.core.contract.values.NodeProperty` shape), the shared render helpers
(``gda.core.contract.render``) and the import-evidence adapter
(``gda.core.project.import_evidence``, whose engine-parity contract this group used to
carry inline, #741) — and is imported by nothing but the composition root (``gda.cli``).

:class:`~gda.commands.project.ResourceReference` is NOT this group's model
despite its name: it is the ``project find-references`` result shape, so it
lives with its single consumer in the ``project`` group (ADR-0040 §5).
"""

import re
import os
from pathlib import Path
from typing import Any, Literal, Optional, get_args

import typer
from pydantic import BaseModel, Field, model_validator

from gda.surface.dispatch import dispatch_command, params_or_bad_parameter
from gda.core.failure.catalog import containment_refusal, Failure, make_failure
from gda.core.failure.classify import resolve_godot_binary_or_failure
from gda.core.engine.execution import ExecutionKind
from gda.surface.descriptor import HeadlessCommand
from gda.surface.options import (
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.core.project.import_evidence import (
    CACHE_ROOT_REL,
    CreatedFileClass,
    EvidenceReason,
    asset_state,
    project_import_gaps,
)
from gda.core.contract.values import (
    CREATED_DIRS_DESC,
    NodeProperty,
    NormalizedPath,
    OBJECT_SET_ECHO_DESC,
    projected_value_schema_extra,
)
from gda.core.project.paths import (
    RES_PREFIX,
    canonical_res_path,
    is_engine_virtual_path,
    project_absolute,
    project_anchored,
)
from gda.core.project.project_tree import ProjectTreeInventory
from gda.core.steps.editor_context import run_editor_operation
from gda.core.contract.render import render_property_lines, render_set_echo


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
    created_dirs: list[str] = Field(description=CREATED_DIRS_DESC)


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
    typed ``NodeProperty`` (the same projection ``node get`` reports), so a
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
    return render_property_lines(got.path, got.type, got.properties)


def render_resource_set(was_set: "ResourceSetResult") -> str:
    """Render a set property as ``set <path>.<property> (<type>) = <value>``."""
    return render_set_echo(was_set.path, was_set.property, was_set.type, was_set.value)


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
    dispatch_command(
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
    dispatch_command(
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
    dispatch_command(
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
    dispatch_command(
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
    dispatch_command(
        RESOURCE_UID_COMMAND,
        ResourceUidParams(target=target),
        json_output=json_output,
        godot=godot,
        project=project,
    )


# --- resource import (scoped import surface, #668) -----------------------------
#
# Clean-worktree resource loading (GDA-DF-010): a fresh checkout carries the
# sources and their committed `.import` sidecars but not the gitignored
# `.godot/` cache, so a one-shot run's `preload()` of a PNG dies with "no
# recognized resource loader" although the imported project loads it fine. The
# engine imports in the editor's filesystem scan, which is project-wide: gda runs
# it as the boot scan of one `Editor context` launch (ADR-0048), which imports
# every missing or stale asset of the project — so gda's scoping is in the
# DECISION and the REPORT, not the import: it starts the editor only when a
# requested asset is missing or stale, and it reports everything the run
# touched, each created file classified against the explicit cache root. Plain
# `script run` is untouched (#668's guarantee: gda adds no import to it). Per the issue's triage decisions the command lives
# under `resource` (no near-synonym `asset` group), and the importer-execution
# point joins CONTEXT.md's Project-code execution surface — within the Trusted
# project assumption (ADR-0009), no new trust axis.


class ResourceImportParams(BaseModel):
    """The params of ``gda resource import``: ensure assets are importable (#668).

    ``assets`` are the requested dependencies, as ``res://`` paths or filesystem
    paths inside the project (a relative filesystem path is read as
    project-relative; other engine-virtual schemes like ``user://`` are
    refused). gda reads each asset's EVIDENCE STATE the way the engine's own
    reimport test reads its artifacts — ``cached`` / ``missing`` / ``stale`` /
    ``invalid`` (see ``ResourceImportAsset``) — and starts the editor, whose
    boot scan imports project-wide, only when a request is ``missing`` or
    ``stale`` (an ``invalid`` one takes the conservative no-run path and settles
    ``failed``; see ``ResourceImportAsset``);
    ``dry_run`` reports the states and the decidable predictions without
    running anything or writing anything.
    """

    assets: list[NormalizedPath] = Field(
        min_length=1,
        description=(
            "The assets to ensure are imported (repeatable): res:// paths, or "
            "filesystem paths inside the project (relative means "
            "project-relative)."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description=(
            "Report the per-asset cache verdicts and the predicted mutation "
            "inventory without starting the engine or writing anything."
        ),
    )
    timeout: float = Field(
        default=300.0,
        gt=0,
        description=(
            "Seconds to allow the editor run (its boot scan imports every "
            "missing or stale asset in the project, not only the requested "
            "ones)."
        ),
    )


AssetStatus = Literal[
    "cached", "missing", "stale", "invalid", "imported", "not_importable", "failed"
]

AssetReason = Literal[
    "sidecar_unparsable",
    "sidecar_marked_invalid",
    "receipt_unsupported",
    "dest_missing_after_pass",
]
"""Which check decided an ``invalid`` or ``failed`` verdict (#853).

The three ARTIFACT checks are :data:`~gda.core.project.import_evidence.EvidenceReason`, read
before the engine runs and carried through unchanged when the settlement turns an
``invalid`` into a ``failed`` — the engine never retries one, so the check that
refused it is still the answer. ``dest_missing_after_pass`` is the settlement's
own and the command's alone to decide: no artifact check refused this asset,
an engine ran in this request, and the engine holds no valid import of the
asset. A single guard test pins the two enums against drift across the
commands -> core seam.
"""

ENGINE_OUTPUT_LINE_CAP = 20
"""How many of the editor run's stderr lines one failed asset carries (#853).

#665's bounded-stream rule, without its spill file: an asset's verdict must not
become an unbounded payload when the engine floods the log. Past the cap the
record says so (``engine_output_truncated``) and the whole stream stays where it
already was — the engine's log when ``--user-data-root`` keeps it, and the
``operation_failed`` diagnostics of a run that exited non-zero.
"""

PAYLOAD_DIAG_PREFIX = "gda: "
"""The prefix of gda's own stderr lines in the editor payload (``DIAG_PREFIX``).

A line with it is gda's, not the engine's, so it is never an asset's
``engine_output``, even when it names the asset (ADR-0048 decision 5). The
Python half of a cross-language constant: a test pins it against the payload's
value.
"""


class ResourceImportAsset(BaseModel):
    """One requested asset's import verdict (#668).

    Before the engine runs (and on a dry run) the status is an EVIDENCE state,
    read from the same project artifacts the engine's reimport test reads (#738
    review): ``cached`` (every ARTIFACT-level check passes — the engine-state
    checks it cannot read are a declared remainder, see below), ``missing`` (no
    sidecar — a new asset the engine would import), ``stale`` (the sidecar is
    present but an engine check fails — a destination or `.md5` receipt
    absent, the recorded `source_md5`/`dest_md5` disagreeing with the bytes,
    `source_file` naming a different source, or the pre-UID format — the engine
    WOULD re-import it), or ``invalid`` (the engine marked the last import
    `valid=false`, or the sidecar does not parse, or the `.md5` receipt falls
    outside gda's documented engine-written assignment subset; the engine
    deliberately SKIPS parse errors and gda conservatively skips unsupported
    receipt syntax — delete the sidecar to retry, which heals a malformed
    receipt too, because the engine rewrites both). The receipt subset accepts
    quoted-string assignments, whitespace, ``;`` comments, JSON-style escapes
    (lone UTF-16 surrogates excluded — VariantParser rejects them), and
    repeated assignments; as in the engine, the final value wins. Broader
    Variant values take the conservative no-run direction. The declared
    remainder: the checks the engine makes from its OWN state — importer
    availability and format version, import-settings validity, and the editor
    cache's expected sidecar MD5 — are not readable from the project's
    artifacts, so an asset the engine would still re-import (e.g. a sidecar
    whose recorded importer no longer exists) can read ``cached`` here until
    an engine runs; the next run converges it, and none of these can make gda
    ask for a re-import the engine would not make.

    A real run settles each non-cached state from the engine's answer, read in
    the editor process after its boot scan (ADR-0048), in this order:
    ``not_importable`` when the asset has no ``.import`` sidecar after the run
    (the engine decided the type needs no import — e.g. a script; the engine's
    import validity is true for such a file too, so it cannot decide this);
    else ``imported`` when the evidence state was ``missing`` or ``stale`` and
    the engine holds a valid import of the asset
    (``EditorFileSystemDirectory.get_file_import_is_valid``); else ``failed``.
    Every ``invalid`` request settles ``failed``, because the engine does not
    retry it.

    An ``invalid`` or ``failed`` verdict also says WHY (#853): ``reason`` names
    the check that decided it and ``detail`` the offending line or path when
    there is one, both read BEFORE the engine runs. ``engine_output`` is the
    other half and answers to nothing but the engine: its stderr lines that
    name this asset, whenever this request ran it. Every other status leaves
    the three empty.
    """

    path: str = Field(description="The asset's res:// path.")
    status: AssetStatus = Field(
        description="The verdict for this asset (see the class docstring)."
    )
    sidecar: str | None = Field(
        default=None,
        description=(
            "The asset's source-adjacent .import sidecar (res:// path), null "
            "when the asset has none."
        ),
    )
    dest_files: list[str] = Field(
        default_factory=list,
        description=(
            "The cache files the sidecar declares (res://.godot/imported/…); "
            "empty when there is no sidecar or it declares none (importer=keep)."
        ),
    )
    reason: AssetReason | None = Field(
        default=None,
        description=(
            "Which check decided an `invalid` or `failed` verdict; null on "
            "every other status. An `invalid` reason survives the settlement, "
            "so a real run's `failed` still names the check that refused it "
            "before the engine ran; `dest_missing_after_pass` is the "
            "settlement's own — no check refused the asset, an engine ran in "
            "this request, and the engine holds no valid import of the asset "
            "(read `engine_output` for what the engine said)."
        ),
    )
    detail: str | None = Field(
        default=None,
        description=(
            "The offending line or path behind `reason`, when the check knows "
            "one that is not already on this record: the malformed dest_files= "
            "or files= line, or the .md5 receipt's res:// path. Null otherwise."
        ),
    )
    engine_output: list[str] = Field(
        default_factory=list,
        max_length=ENGINE_OUTPUT_LINE_CAP,
        description=(
            "The editor run's stderr lines that name this asset's res:// "
            "path as a whole path token — the engine's own quoting decides "
            "where a path ends, so a neighbour whose path extends this one is "
            "never this asset's evidence — verbatim and in order, for a "
            "`failed` asset when this "
            f"request ran an engine; at most {ENGINE_OUTPUT_LINE_CAP}. Only the "
            "engine's lines: a line with gda's `gda: ` prefix is not one. Empty "
            "on every other status, and when no engine ran. Independent of "
            "`reason`: that is gda's evidence from before the run, this is what "
            "the engine said, and the engine also names an asset it then skips."
        ),
    )
    engine_output_truncated: bool = Field(
        default=False,
        description="Whether more lines named this asset than `engine_output` carries.",
    )


class ImportCreatedFile(BaseModel):
    """One file the editor run created, classified (#668).

    ``classification`` is ``cache_owned`` for a file under the explicit cache
    root (the project's ``.godot/``) and ``source_adjacent`` for anything else
    the run wrote beside the sources (an asset's ``.import`` sidecar, a
    script's ``.uid``) — the DF-038 noise an unattended admission must account
    for, file by file.
    """

    path: str = Field(description="The created file's res:// path.")
    classification: CreatedFileClass = Field(
        description="cache_owned (under .godot/) or source_adjacent."
    )


class ResourceImportSummary(BaseModel):
    """The machine-readable completion summary of ``gda resource import`` (#668)."""

    requested: int = Field(description="Assets requested.")
    cached: int = Field(
        description=(
            "Assets the artifacts show the engine would leave as is "
            "(subject to the declared engine-state remainder)."
        )
    )
    missing: int = Field(
        description="Assets with no sidecar yet (nonzero only on a dry run)."
    )
    stale: int = Field(
        description=(
            "Assets whose sidecar fails an engine check (nonzero only on a dry run)."
        )
    )
    invalid: int = Field(
        description=(
            "Assets whose last import the engine marked failed, whose sidecar "
            "does not parse, or whose .md5 receipt falls outside gda's "
            "documented engine-written assignment subset (nonzero only on a "
            "dry run; the engine does not retry these)."
        )
    )
    imported: int = Field(
        description="Assets the engine imported: it holds a valid import of each."
    )
    not_importable: int = Field(
        description="Assets with no .import sidecar after the run: the engine "
        "decided they need no import."
    )
    failed: int = Field(description="Assets the engine did not import.")
    created_cache_owned: int = Field(
        description="Files the run created under the cache root."
    )
    created_source_adjacent: int = Field(
        description="Files the run created beside the sources."
    )


class ResourceImportResult(BaseModel):
    """The result of ``gda resource import`` (#668).

    The report IS the scoping: the engine's import is project-wide (the
    editor's boot scan), so gda starts the editor only when a requested asset's
    evidence state is ``missing`` or ``stale`` (``engine_pass``; an ``invalid``
    request settles ``failed`` without a run — the engine skips failed imports
    and parse errors, while
    gda conservatively skips unsupported receipt syntax), and accounts
    for everything it touched — ``created`` lists every new file, classified
    against ``cache_root``, and ``skipped`` says how much of the tree the
    inventory could not see. On a dry run nothing runs and nothing is written:
    ``assets`` carry the ``cached`` / ``missing`` / ``stale`` / ``invalid``
    states, ``engine_pass`` says whether a real run WOULD start the engine,
    ``predicted_source_adjacent`` lists the requested assets' sidecars-to-be,
    and ``pass_will_also_import`` the other stale assets the boot scan will
    re-import (the remaining inventory — engine hash-named cache files under
    ``cache_root``, sidecars for no-sidecar assets, generated ``.uid`` files —
    is the engine's to decide, and the real run's ``created`` is the
    authoritative list, complete when its ``skipped`` is 0). The mode's field
    set is validated, not merely described.
    """

    dry_run: bool = Field(description="Whether this was a dry run.")
    cache_root: str = Field(
        description="The explicit cache root created files are classified against "
        "(res://.godot)."
    )
    engine_pass: bool = Field(
        description=(
            "Whether an engine ran: the editor, whose boot scan imports every "
            "missing or stale asset in the project (dry run: whether it WOULD "
            "run)."
        )
    )
    assets: list[ResourceImportAsset] = Field(
        description="Per requested asset: the import verdict."
    )
    created: list[ImportCreatedFile] = Field(
        default_factory=list,
        description=(
            "Every file the run created, classified; the list is complete "
            "when `skipped` is 0; empty on a dry run."
        ),
    )
    skipped: int = Field(
        default=0,
        description=(
            "What `created` could not account for: entries that are not regular "
            "files, or could not be read, including a directory whose whole "
            "subtree is then uncovered. A count only, 0 on a dry run; repair the "
            "tree and run again for a complete record."
        ),
    )
    predicted_source_adjacent: list[str] = Field(
        default_factory=list,
        description=(
            "Dry run only: the .import sidecars a real run would create for the "
            "requested assets."
        ),
    )
    pass_will_also_import: list[str] = Field(
        default_factory=list,
        description=(
            "Dry run only: OTHER assets whose committed sidecar fails an "
            "engine check (stale) — the editor's project-wide boot scan WILL "
            "re-import "
            "these. Invalid assets are excluded (the engine skips them), and "
            "assets with no sidecar or generated .uid sidecars cannot be "
            "predicted; the real run's `created` list is the authoritative "
            "inventory, complete when its `skipped` is 0."
        ),
    )
    summary: ResourceImportSummary

    @model_validator(mode="after")
    def _mode_fields(self) -> "ResourceImportResult":
        # The #732 lesson: the mode's field set is validated. A dry run writes
        # nothing, so it reports nothing created; a real run predicts nothing,
        # it reports what happened. The summary counts must match the lists.
        if self.dry_run:
            if self.created:
                raise ValueError("a dry run creates nothing.")
            if self.skipped:
                raise ValueError("a dry run walks nothing, so it skips nothing.")
            if any(
                asset.status in ("imported", "not_importable", "failed")
                for asset in self.assets
            ):
                raise ValueError("a dry run reports evidence states, not settlements.")
            if any(
                asset.engine_output or asset.engine_output_truncated
                for asset in self.assets
            ):
                raise ValueError("a dry run runs no pass, so it captures no output.")
        else:
            if self.predicted_source_adjacent or self.pass_will_also_import:
                raise ValueError("a real run reports created files, not predictions.")
            if any(
                asset.status in ("missing", "stale", "invalid") for asset in self.assets
            ):
                raise ValueError(
                    "evidence states are dry-run verdicts; a real run settles them."
                )
        counted = {
            "cached": self.summary.cached,
            "missing": self.summary.missing,
            "stale": self.summary.stale,
            "invalid": self.summary.invalid,
            "imported": self.summary.imported,
            "not_importable": self.summary.not_importable,
            "failed": self.summary.failed,
        }
        for status, expected in counted.items():
            actual = sum(1 for a in self.assets if a.status == status)
            if actual != expected:
                raise ValueError(f"summary.{status} disagrees with the asset list.")
        if self.summary.requested != len(self.assets):
            raise ValueError("summary.requested disagrees with the asset list.")
        owned = sum(1 for f in self.created if f.classification == "cache_owned")
        if (
            self.summary.created_cache_owned != owned
            or self.summary.created_source_adjacent != len(self.created) - owned
        ):
            raise ValueError("summary created counts disagree with the list.")
        return self


def _asset_res_path(project: Path, raw: str) -> "str | Failure":
    """Normalize one requested asset to its res:// path, or the refusal.

    ONE containment question, asked once, for BOTH accepted input forms (#763).
    :func:`path_outside_project` — ADR-0006's authority — answers it: for a
    filesystem path by its resolved + lexical double reading (so a legitimately
    symlinked-in file is accepted and a ``..``-through-a-symlink escape is not),
    anchored the way the engine would anchor it (:func:`project_anchored`); for a
    ``res://`` address by the shared lexical rule, which canonicalizes the spelling
    exactly as ``String::simplify_path`` does and refuses only what is still
    climbing above the namespace root afterwards.

    That replaces this gate's own ``".." in rel.parts`` check, which was a
    DIFFERENT rule wearing the same name, and wrong in both directions:

    - it refused ``res://foo/../bar.png``, which collapses net-INSIDE and is an
      address the engine resolves happily — the same spelling ``script validate``
      and ``script run`` both accept, so one input had two verdicts (pinned by
      ``tests/project/test_project.py`` as this issue's to-reconcile);
    - it split on ``PurePosixPath`` parts, so ``res://..\\x.png`` was ONE segment
      carrying no ``..`` at all and passed. On POSIX the later ``is_file()`` check
      happened to stop it; on native Windows ``\\`` IS a separator and the join
      reaches the parent directory. The shared canonicalizer folds ``\\`` to ``/``
      first, as the engine does, so the escape is refused on every platform by the
      one rule instead of by a platform accident (#763, PR #766 round-2 review).

    The refusal is also the shared one now: ``target_outside_project``, the code
    ``script validate`` and ``script run`` report for the same condition, in place
    of a third spelling of a generic ``invalid_params``.

    Ownership (:func:`~gda.core.project.paths.owning_project`) is asked here too, for the
    engine's own reason: ``EditorFileSystem::_should_skip_directory``
    (``editor/file_system/editor_file_system.cpp:3482``) SKIPS a directory holding
    a nested ``project.godot`` — "Skip if another project inside this" — so an
    asset in one cannot be imported into the outer project at all. Without the
    check gda accepted the request, spent an engine pass, and returned
    ``not_importable``, while ``--dry-run`` predicted a sidecar that would never
    appear. Refusing before the pass, naming the project that CAN import it, is
    both cheaper and truer (#697 re-review).

    What remains this gate's own is what is genuinely about ASSETS: ``user://`` and
    ``uid://`` are engine-virtual but not the project's ``res://`` namespace, so
    they cannot name a project asset at all, and the mapping from an accepted
    filesystem path back to the ``res://`` address the engine will import.
    """
    if is_engine_virtual_path(raw) and not raw.startswith(RES_PREFIX):
        # user:// / uid:// are engine-virtual but NOT the project's res://
        # namespace: gda cannot address them as project assets, and passing
        # them on would misread them as literal filesystem names (#738
        # re-review 2).
        return make_failure(
            "invalid_params",
            f"asset {raw!r} is not a project asset: only res:// paths or "
            "filesystem paths inside the project are accepted.",
            "",
        )
    # One coordinate system for BOTH sides before any comparison: a relative
    # --project must not meet an absolute candidate (#738 re-review 2 — the
    # mixed comparison raised a bare ValueError on the lexical fallback). This
    # local is for the res:// MAPPING further down, which needs the same absolute
    # root the gate below reads. Not a two-places-must-agree coupling: there is one
    # normalization RULE — `project_absolute` — and both sites call it, so the only
    # cost of asking twice is a second `Path.cwd()` (#807 review).
    project_abs = project_absolute(project)
    # ONE call for ownership, then containment, then the spelling, and all three
    # refusal envelopes (#802, #845). What used to stand here — the two probes,
    # their order, the four coordinates and the resolved root each refusal reports
    # — now lives on ADR-0006's path authority, so this gate keeps only what is
    # genuinely about ASSETS.
    refusal = containment_refusal(raw, project)
    if refusal is not None:
        return refusal
    if raw.startswith(RES_PREFIX):
        # Already in the engine's namespace: canonicalize the spelling and stop.
        # Reading it lexically is what the engine does too — a symlink inside the
        # project stays as spelled, because Godot walks the project directory.
        return canonical_res_path(raw)
    anchored = project_anchored(raw, project_abs)
    try:
        rel_fs = anchored.resolve().relative_to(project_abs.resolve())
    except ValueError:
        try:
            # Contained by the lexical reading only (a symlinked-in file):
            # keep the caller's spelling, normalized lexically.
            rel_fs = Path(os.path.normpath(anchored)).relative_to(
                Path(os.path.normpath(project_abs))
            )
        except ValueError:
            # Total by construction — the shared gate said "inside", so one
            # of the two readings must relate — but a refusal beats a bare
            # traceback if that invariant is ever disturbed.
            return make_failure(
                "invalid_params",
                f"asset {raw!r} could not be addressed inside the project {project}.",
                "",
            )
    # Through the SAME canonicalizer as the res:// form, so both input spellings
    # of one asset produce one address — `.` (the project root, from `foo/..`)
    # included, which `PurePosixPath` used to hand on as the bogus `res://.`.
    return canonical_res_path(RES_PREFIX + rel_fs.as_posix())


def _asset_record(project: Path, res_path: str) -> ResourceImportAsset:
    """Address one asset's evidence: the core adapter's verdict, in the wire shape.

    The command's whole share of the reimport test (#741) — ``gda.core.project.import_evidence``
    reads the artifacts and returns the four EVIDENCE states; this maps them onto
    ``ResourceImportAsset``, whose vocabulary also carries the settlements a real
    run adds afterwards, and the one ``reason`` only a settlement can decide.
    """
    evidence = asset_state(project, res_path)
    return ResourceImportAsset(
        path=res_path,
        status=evidence.status,
        sidecar=evidence.sidecar,
        dest_files=list(evidence.dest_files),
        reason=evidence.reason,
        detail=evidence.detail,
    )


# How an engine line delimits a path, measured on the 4.6 sources (fourth and
# fifth reviews of PR #937). QUOTED — ``'%s'`` in ``Error importing``, ``Cannot
# open file``, ``Error opening file``, ``Cannot open import file '%s.import'``, the
# editor's ``'%s.import:%d'`` / ``'%s.import.md5:%d'`` sidecar records; ``"%s"`` in
# the UID warnings — the path runs from the opening quote to the SAME quote
# character, whatever it holds in between (a path can carry the other quote, or
# this one). BARE — followed by whitespace, the end of the line, a sentence-final
# period (``Failed loading resource: %s.``), a following ``(`` (``Resource file
# not found: %s (expected type: …)``) or ``:<line>`` (the core
# ``ResourceFormatImporter::load - %s.import:%d error:``). gda never has to cut
# an UNKNOWN path out of the line — a path's alphabet holds every character a
# cut could stop at, which is what defeated a substring, a lookahead and a
# tokenizer in turn — because it KNOWS the path it is looking for: it finds that
# spelling in the line and checks the two boundaries the engine's delimiting
# fixes. The one shape this cannot decide is declared rather than chased: a
# bare path that itself contains whitespace, or a quoted neighbour whose path
# continues after a quote character identical to its delimiter — both read as
# this asset, and the engine quotes a path in every import-pass message
# measured.
_BARE_PATH_END = re.compile(r"\s|$|\.(?:\s|$)|:\d+\b")


def _names_asset(line: str, res_path: str) -> bool:
    """Whether ``line`` names ``res_path`` (or its sidecar) as the engine delimits a path."""
    for needle in (res_path, f"{res_path}.import", f"{res_path}.import.md5"):
        at = line.find(needle)
        while at != -1:
            before = line[at - 1] if at else ""
            after = line[at + len(needle) :]
            if before in ("'", '"'):
                # A quoted path closes with the SAME quote; a sidecar record may
                # carry its ``:<line>`` inside the quotes.
                match = re.match(r"(?::\d+)?" + re.escape(before), after)
            else:
                match = _BARE_PATH_END.match(after)
            if match:
                return True
            at = line.find(needle, at + 1)
    return False


def _engine_output(stderr: "str | None", res_path: str) -> "tuple[list[str], bool]":
    """The editor run's stderr lines that NAME one asset, bounded (#853).

    A line names the asset when :func:`_names_asset` finds the asset's ``res://``
    path — or its sidecar (``.import`` / ``.import.md5``, either with the
    ``:<line>`` the engine appends when it reports a parse position) — spelled
    whole and delimited as the engine delimits a path. Never a substring, a
    prefix with a lookahead, or a token cut by a character class: a legal
    neighbouring path can carry any punctuation inside it, and a legal asset
    path can carry a quote. Deliberately literal otherwise: a broader needle
    (the filename, the filesystem path) would attribute a neighbour's error to
    this asset, and evidence that over-claims is worse than evidence that is
    short. The engine's ``at:`` continuation lines name a source file, not the
    asset, so they stay out, and so does a line of gda's own payload
    (:data:`PAYLOAD_DIAG_PREFIX`).

    Returns the kept lines and whether any were dropped.
    """
    if not stderr:
        return [], False
    matched = [
        line
        for line in stderr.splitlines()
        if not line.startswith(PAYLOAD_DIAG_PREFIX) and _names_asset(line, res_path)
    ]
    return matched[:ENGINE_OUTPUT_LINE_CAP], len(matched) > ENGINE_OUTPUT_LINE_CAP


class _ResourceImportEngineRead(BaseModel):
    """The ``resource-import`` op's sentinel payload — internal, never published.

    The requested paths whose file the editor's filesystem holds with a valid
    import after its boot scan (``get_file_import_is_valid``, ADR-0048). The
    settlement reads it; the result carries the per-asset statuses instead.
    """

    valid_imports: list[str]


def _summarize(
    assets: list[ResourceImportAsset], created: list[ImportCreatedFile]
) -> ResourceImportSummary:
    owned = sum(1 for f in created if f.classification == "cache_owned")
    return ResourceImportSummary(
        requested=len(assets),
        cached=sum(1 for a in assets if a.status == "cached"),
        missing=sum(1 for a in assets if a.status == "missing"),
        stale=sum(1 for a in assets if a.status == "stale"),
        invalid=sum(1 for a in assets if a.status == "invalid"),
        imported=sum(1 for a in assets if a.status == "imported"),
        not_importable=sum(1 for a in assets if a.status == "not_importable"),
        failed=sum(1 for a in assets if a.status == "failed"),
        created_cache_owned=owned,
        created_source_adjacent=len(created) - owned,
    )


def run_resource_import_operation(
    project: Optional[Path],
    params: ResourceImportParams,
    *,
    godot: Optional[str] = None,
) -> "ResourceImportResult | Failure":
    """Decide per asset, start the engine only when needed, account for it all.

    The recipe: normalize + verify the requested assets, take their cache
    verdicts, and — unless no asset is missing or stale, or this is a dry run —
    run the ``resource-import`` op in the ``Editor context`` (ADR-0048), whose
    boot scan imports project-wide, then settle the assets from the engine's
    answer and classify every created file against the cache root.
    """
    assert project is not None  # a project-using recipe; dispatch resolved it
    res_paths: list[str] = []
    for raw in params.assets:
        res_path = _asset_res_path(project, raw)
        if isinstance(res_path, Failure):
            return res_path
        source = project / res_path[len("res://") :]
        if not source.is_file():
            return make_failure(
                "invalid_params",
                f"asset {res_path} does not exist in the project.",
                "",
            )
        res_paths.append(res_path)
    # A repeated asset is idempotent; normalize it away, order preserved.
    res_paths = list(dict.fromkeys(res_paths))

    assets = [_asset_record(project, res_path) for res_path in res_paths]
    cache_root = "res://" + CACHE_ROOT_REL
    # The engine runs for what it would act on: missing and stale. An invalid
    # request never triggers it — the engine skips a previously failed import
    # and an unparseable artifact (delete the sidecar to retry) — so it settles
    # to failed without spending a run. The same list is what the payload is
    # asked about, so only a missing or stale asset can settle imported.
    asked = [asset.path for asset in assets if asset.status in ("missing", "stale")]
    needs_pass = bool(asked)

    if params.dry_run:
        predicted = [
            asset.path + ".import"
            for asset in assets
            if asset.status == "missing" and asset.sidecar is None
        ]
        return ResourceImportResult(
            dry_run=True,
            cache_root=cache_root,
            engine_pass=needs_pass,
            assets=assets,
            predicted_source_adjacent=predicted,
            pass_will_also_import=(
                project_import_gaps(project, set(res_paths)) if needs_pass else []
            ),
            summary=_summarize(assets, []),
        )

    created: list[ImportCreatedFile] = []
    skipped = 0
    # What the engine said, kept for the settlement: a failed asset's own lines
    # are read out of it there, per asset (#853). None means no engine ran.
    pass_stderr: "str | None" = None
    valid_imports: set[str] = set()
    if needs_pass:
        # Resolved only when the engine runs, so a dry run or an all-cached request
        # never refuses an empty ``--godot ""``. Here it is the shared step's
        # binary_not_found failure, not a traceback (#33).
        binary = resolve_godot_binary_or_failure(godot)
        if isinstance(binary, Failure):
            return binary
        # The `Project tree inventory` (:mod:`gda.core.project.project_tree`, #985): the same
        # walk `export run` reports its mutations from, around an engine run that
        # imports the same way. This command used to walk the tree itself with
        # `Path.rglob("*")`, which does NOT descend a directory link — so a file the
        # engine created under a linked-in library was invisible here while `export
        # run` reported it. It asks for no artifact (the run writes none) and for no
        # rewrite detection (`created` is the whole question, and the hash the other
        # command pays for buys nothing here).
        inventory = ProjectTreeInventory.capture(project, detect_rewrites=False)
        # The shared step (`gda.core.steps.editor_context`, ADR-0048) runs the op and
        # applies ADR-0002's #803 child-stderr rule to it: a failure carries the run's
        # stderr on `child_stderr`, a success has forwarded it by the time it returns.
        # `engine_output` below is the per-asset extract, not the stream — a line about
        # an unrequested asset reaches the caller only through the forwarded stream.
        ran = run_editor_operation(
            binary,
            project,
            "resource-import",
            {"assets": asked},
            timeout=params.timeout,
            output_model=_ResourceImportEngineRead,
        )
        if isinstance(ran, Failure):
            return ran
        read, pass_stderr = ran
        valid_imports = set(read.valid_imports)
        # Both halves of the settlement are published: `created` is the list,
        # and `skipped` says how much of the tree the inventory could not see —
        # the one field #990 adds, so an unconditional `created` is verifiable
        # from the result instead of taken on trust (#985 left the count
        # computed and discarded).
        settlement = inventory.settle()
        skipped = settlement.skipped
        created = [
            ImportCreatedFile(
                path="res://" + entry.rel,
                classification=entry.classification,
            )
            for entry in settlement.created
        ]
    # Settle every evidence state (whether or not an engine ran), from the
    # engine's answer (#1256, ADR-0048): no sidecar after the run means the
    # engine decided the type needs no import — the engine's import validity is
    # true for such a file too, so it cannot decide this; a missing or stale
    # asset the engine holds with a valid import is imported; anything else —
    # including every invalid request, which the engine deliberately skips — is
    # failed. For a missing asset, the new sidecar shows that this run imported
    # it; for a stale one, `Import evidence` reports stale only where the engine
    # re-imports (its one-way remainder). `resources_reimported` decides
    # nothing: the editor also imports an asset that a `@tool` autoload preloads
    # at startup, and that path emits no signal (measured on 4.6.3).
    #
    # The re-read supplies the CURRENT artifacts (sidecar, destinations); the
    # `reason` comes from the PRE-PASS record instead, because that is what
    # #853 asks the settlement to preserve: an artifact check refused this
    # asset before the run, the engine never retried it, so that check is still
    # the answer. Where no check refused it, the settlement decides the reason
    # itself.
    #
    # `engine_output` does NOT follow the reason, and the two must not be made
    # to gate each other: `reason` is gda's PRE-PASS evidence, `engine_output`
    # is what the ENGINE said about this asset during this request's run. PR
    # #937 round 1 gated the lines on a settlement-decided reason, on the
    # assumption that the engine says nothing about an asset it skips; round 2
    # disproved that on 4.6.3 — an unparsable sidecar draws two
    # `ResourceFormatImporter::load - 'res://x.png.import:8'` errors naming the
    # asset BEFORE the skip (observed from `_test_for_reimport` and
    # `_get_import_dest_paths`, `editor/file_system/editor_file_system.cpp`),
    # and a receipt outside gda's narrower subset is re-imported by the engine
    # and prints its own failure. So the rule is the literal one #853 states:
    # the engine's lines that name the asset, whenever this request ran it.
    settled: list[ResourceImportAsset] = []
    for asset in assets:
        if asset.status == "cached":
            settled.append(asset)
            continue
        now = _asset_record(project, asset.path)
        if now.sidecar is None:
            settled.append(now.model_copy(update={"status": "not_importable"}))
            continue
        if asset.path in valid_imports:
            settled.append(
                now.model_copy(
                    update={"status": "imported", "reason": None, "detail": None}
                )
            )
            continue
        lines, truncated = _engine_output(pass_stderr, asset.path)
        settled.append(
            now.model_copy(
                update={
                    "status": "failed",
                    "reason": asset.reason or "dest_missing_after_pass",
                    "detail": asset.detail,
                    "engine_output": lines,
                    "engine_output_truncated": truncated,
                }
            )
        )
    assets = settled

    return ResourceImportResult(
        dry_run=False,
        cache_root=cache_root,
        engine_pass=needs_pass,
        assets=assets,
        created=created,
        skipped=skipped,
        summary=_summarize(assets, created),
    )


def _resource_import_recipe(params, *, project, godot):
    return run_resource_import_operation(project, params, godot=godot)


# The reasons an ARTIFACT check decides, as the wire spells them: the same set
# `gda.core.project.import_evidence.EvidenceReason` names, and the one the sidecar-deleting
# remedy answers. `dest_missing_after_pass` is not one — no sidecar edit helps
# an import the engine attempted and failed.
_ARTIFACT_REASONS = frozenset(get_args(EvidenceReason))


def _reason_suffix(asset: ResourceImportAsset) -> str:
    """What decided an ``invalid`` or ``failed`` line, for the human render (#853).

    Empty for every status that needs no explanation, so the listing keeps its
    shape. The offending line or path follows the reason when there is one.
    """
    if asset.reason is None:
        return ""
    detail = f": {asset.detail}" if asset.detail else ""
    return f"  ({asset.reason}{detail})"


def render_resource_import(outcome: "ResourceImportResult") -> str:
    """Render the verdicts, the pass, and the created-file accounting (#668)."""
    mode = "dry run" if outcome.dry_run else "import"
    ran = (
        ("pass would run" if outcome.dry_run else "pass ran")
        if outcome.engine_pass
        else "no pass needed"
    )
    header = (
        f"resource {mode}: {outcome.summary.requested} asset(s), {ran} "
        f"(cache root {outcome.cache_root})"
    )
    lines = [
        f"  {asset.status:>14}  {asset.path}{_reason_suffix(asset)}"
        for asset in outcome.assets
    ]
    if any(asset.reason in _ARTIFACT_REASONS for asset in outcome.assets):
        # The remedy belongs to the artifact CHECK, not to the `invalid` state:
        # a real run settles that state to `failed` and carries the check with
        # it, so the hint had to follow (PR #937 review round 2).
        lines.append(
            "  invalid: no pass runs for a failed import, a parse error, or "
            "unsupported receipt syntax; delete the asset's .import sidecar "
            "to retry (the pass rewrites the sidecar and its .md5 receipt)"
        )
    if outcome.pass_will_also_import:
        lines.append("  the pass will also re-import:")
        lines.extend(f"    {path}" for path in outcome.pass_will_also_import)
    if outcome.created or outcome.skipped:
        # The count rides the created line, and the line is printed for the count
        # alone: a record that could not read part of the tree must not print as
        # a complete one (#990, `export run`'s rule for the same fact).
        unreadable = f", {outcome.skipped} unreadable" if outcome.skipped else ""
        lines.append(
            f"  created: {outcome.summary.created_cache_owned} cache-owned, "
            f"{outcome.summary.created_source_adjacent} source-adjacent{unreadable}"
        )
        lines.extend(
            f"    {f.classification:>15}  {f.path}"
            for f in outcome.created
            if f.classification == "source_adjacent"
        )
    if outcome.predicted_source_adjacent:
        lines.append("  a real run would create beside the sources:")
        lines.extend(f"    {p}" for p in outcome.predicted_source_adjacent)
    return "\n".join([header, *lines])


# `resource import` is a recipe command (ADR-0023): its outcome is decided
# CLI-side (cache verdicts, the run decision, the before/after accounting) and
# its engine call is the `Editor context` step's `resource-import` op
# (ADR-0048), not the sentinel channel.
RESOURCE_IMPORT_COMMAND: HeadlessCommand[ResourceImportResult] = HeadlessCommand(
    operation="resource-import",
    input_model=ResourceImportParams,
    output_model=ResourceImportResult,
    render=render_resource_import,
    kind=ExecutionKind.EDITOR,
    recipe=_resource_import_recipe,
)


@_app.command(name="import", cls=RESOURCE_IMPORT_COMMAND.command_class())
def resource_import(
    assets: list[str] = typer.Argument(
        ...,
        help=(
            "The assets to ensure are imported: res:// paths, or filesystem "
            "paths inside the project (relative means project-relative)."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Report the per-asset cache verdicts and the predicted mutations "
            "without starting the engine or writing anything."
        ),
    ),
    timeout: float = typer.Option(
        300.0,
        "--timeout",
        min=0.001,
        help="Seconds to allow the editor run.",
    ),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_IMPORT_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Ensure assets are imported into the project cache (clean-worktree loading).

    A clean worktree has the sources and their committed .import sidecars but
    not the gitignored .godot/ cache, so a one-shot run's preload() of e.g. a
    PNG fails with "no recognized resource loader" (GDA-DF-010). This command
    reads each requested asset's evidence state as the engine's own reimport
    test reads its artifacts (`cached` / `missing` / `stale` / `invalid`) and,
    only when a request is missing or stale, runs one headless editor process,
    whose filesystem scan imports PROJECT-WIDE: every missing or stale asset,
    not only the requested ones. An invalid request settles `failed` without a
    run (the engine skips failed imports and parse errors; gda conservatively
    skips unsupported receipt syntax — delete the sidecar to retry). The engine
    decides the settlement: an asset with no .import sidecar after the run is
    `not_importable`, a missing or stale asset the engine holds with a valid
    import is `imported`, and any other is `failed`. The result reports
    every file the run created, classified against the cache root
    (cache-owned under .godot/ vs source-adjacent, e.g. .import and .uid
    sidecars) — a list `skipped` qualifies: it counts what the inventory could not
    read, so `created` is complete when `skipped` is 0. An `invalid` or
    `failed` asset says why: `reason` names the
    check that decided it (an invalid one survives into the settled `failed`),
    `detail` the offending line or path when there is one, and `engine_output`
    the engine's own stderr lines naming that asset when this request ran it
    (at most 20, with `engine_output_truncated` when more matched; empty when
    no engine ran). `--dry-run` reports the states and the decidable predictions
    (including `pass_will_also_import`) and writes nothing. An asset whose CASE does
    not match the stored file is refused with `path_case_mismatch` naming the stored
    res:// spelling, because such a path opens on a case-insensitive filesystem and
    fails on a case-sensitive one. Plain `gda script
    run` never triggers an import.

    The editor runs project code: importer code and import plugins, every @tool
    autoload, enabled editor plugins, and the @tool scripts of scenes the editor
    reopens (the Trusted project assumption, ADR-0009). The project's other
    autoloads do not run. The editor's data, config and cache directories are a
    private directory for each call, removed after it, unless --user-data-root
    names one.
    """
    params = params_or_bad_parameter(
        ResourceImportParams, assets=assets, dry_run=dry_run, timeout=timeout
    )
    dispatch_command(
        RESOURCE_IMPORT_COMMAND,
        params,
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
