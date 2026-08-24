"""The ``resource`` command group: Godot resource files (.tres) as the domain object.

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderers, its ``HeadlessCommand`` descriptors
(ADR-0023), and its Typer command bodies, and mounts them on the root app
through :func:`register`. It imports the shared machinery downward — the
dispatch tail (``gda.dispatch``), the descriptor machinery (``gda.headless``),
the cross-command contract core (``gda.models``, for the shared
:class:`~gda.models.NodeProperty` shape) and the shared render helpers
(``gda.render``) — and is imported by nothing but the composition root
(``gda.cli``).

:class:`~gda.commands.project.ResourceReference` is NOT this group's model
despite its name: it is the ``project find-references`` result shape, so it
lives with its single consumer in the ``project`` group (ADR-0040 §5).
"""

import json
import re
from pathlib import Path
from typing import Any, Literal, Optional

import typer
from pydantic import BaseModel, Field, model_validator

from gda.binary import resolve_godot_binary
from gda.dispatch import dispatch_domain, dispatch_recipe, params_or_bad_parameter
from gda.errors import Failure, classify_launch_or_crash, make_failure
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.models import (
    CREATED_DIRS_DESC,
    NodeProperty,
    NormalizedPath,
    OBJECT_SET_ECHO_DESC,
    projected_value_schema_extra,
)
from gda.render import render_property_lines, render_set_echo
from gda.runner import LaunchFn, launch


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
    dispatch_domain(
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
    dispatch_domain(
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
    dispatch_domain(
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
    dispatch_domain(
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
    dispatch_domain(
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
# engine's ONE scriptable import primitive is the project-wide
# `godot --headless --import` pass (a per-file reimport exists only inside the
# editor process; `--script` requires a MainLoop, verified against the engine
# source) — so gda's scoping is in the DECISION and the REPORT, not the pass:
# it runs the pass only when a requested asset's cache is missing, and it
# reports everything the pass touched, each created file classified against the
# explicit cache root. Plain `script run` is untouched (#668's guarantee: gda
# adds no import pass). Per the issue's triage decisions the command lives
# under `resource` (no near-synonym `asset` group), and the importer-execution
# point joins CONTEXT.md's Project-code execution surface — within the Trusted
# project assumption (ADR-0009), no new trust axis.


class ResourceImportParams(BaseModel):
    """The params of ``gda resource import``: ensure assets are importable (#668).

    ``assets`` are the requested dependencies, as ``res://`` paths or filesystem
    paths inside the project (a relative filesystem path is read as
    project-relative). gda decides per asset whether its import cache is intact
    (``cached``) or not (``missing``), and runs the engine's project-wide import
    pass only when something is missing; ``dry_run`` reports the decision and
    the predicted mutations without running anything or writing anything.
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
            "inventory without running the engine pass or writing anything."
        ),
    )
    timeout: float = Field(
        default=300.0,
        gt=0,
        description=(
            "Seconds to allow the engine import pass (it imports every missing "
            "asset in the project, not only the requested ones)."
        ),
    )


class ResourceImportAsset(BaseModel):
    """One requested asset's import verdict (#668).

    ``status`` is ``cached`` (the sidecar's destination files all exist — the
    cache hit), ``missing`` (dry-run only: no sidecar, or a destination is
    absent), ``imported`` (was missing; the pass produced its cache),
    ``not_importable`` (was missing; the pass decided the type needs no import
    — e.g. a script), or ``failed`` (was missing; the pass ran and its cache is
    still incomplete).
    """

    path: str = Field(description="The asset's res:// path.")
    status: Literal["cached", "missing", "imported", "not_importable", "failed"] = (
        Field(description="The verdict for this asset (see the class docstring).")
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


class ImportCreatedFile(BaseModel):
    """One file the engine import pass created, classified (#668).

    ``classification`` is ``cache_owned`` for a file under the explicit cache
    root (the project's ``.godot/``) and ``source_adjacent`` for anything else
    the pass wrote beside the sources (an asset's ``.import`` sidecar, a
    script's ``.uid``) — the DF-038 noise an unattended admission must account
    for, file by file.
    """

    path: str = Field(description="The created file's res:// path.")
    classification: Literal["cache_owned", "source_adjacent"] = Field(
        description="cache_owned (under .godot/) or source_adjacent."
    )


class ResourceImportSummary(BaseModel):
    """The machine-readable completion summary of ``gda resource import`` (#668)."""

    requested: int = Field(description="Assets requested.")
    cached: int = Field(description="Assets whose cache was already intact.")
    missing: int = Field(
        description="Assets found missing (nonzero only on a dry run)."
    )
    imported: int = Field(description="Assets the pass imported.")
    not_importable: int = Field(description="Assets the pass decided need no import.")
    failed: int = Field(description="Assets still without an intact cache.")
    created_cache_owned: int = Field(
        description="Files the pass created under the cache root."
    )
    created_source_adjacent: int = Field(
        description="Files the pass created beside the sources."
    )


class ResourceImportResult(BaseModel):
    """The result of ``gda resource import`` (#668).

    The report IS the scoping: the engine's import primitive is project-wide,
    so gda runs it only when a requested asset's cache is missing
    (``engine_pass``), and accounts for everything it touched — ``created``
    lists every new file, classified against ``cache_root``. On a dry run
    nothing runs and nothing is written: ``assets`` carry the ``cached`` /
    ``missing`` verdicts, ``engine_pass`` says whether a real run WOULD run the
    pass, and ``predicted_source_adjacent`` lists the sidecars a real run would
    create for the requested assets (the pass's remaining inventory — engine
    hash-named cache files under ``cache_root``, plus project-wide sidecars for
    OTHER missing assets and scripts — is the engine's to decide, and the real
    run's ``created`` is the authoritative list). The mode's field set is
    validated, not merely described.
    """

    dry_run: bool = Field(description="Whether this was a dry run.")
    cache_root: str = Field(
        description="The explicit cache root created files are classified against "
        "(res://.godot)."
    )
    engine_pass: bool = Field(
        description=(
            "Whether the engine import pass ran (dry run: whether it WOULD run)."
        )
    )
    assets: list[ResourceImportAsset] = Field(
        description="Per requested asset: the import verdict."
    )
    created: list[ImportCreatedFile] = Field(
        default_factory=list,
        description="Every file the pass created, classified; empty on a dry run.",
    )
    predicted_source_adjacent: list[str] = Field(
        default_factory=list,
        description=(
            "Dry run only: the .import sidecars a real run would create for the "
            "requested assets."
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
        else:
            if self.predicted_source_adjacent:
                raise ValueError("a real run reports created files, not predictions.")
            if any(asset.status == "missing" for asset in self.assets):
                raise ValueError(
                    "'missing' is a dry-run verdict; a real run resolves it."
                )
        counted = {
            "cached": self.summary.cached,
            "missing": self.summary.missing,
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


_CACHE_ROOT_REL = ".godot"
_DEST_FILES_LINE = re.compile(r"^dest_files=(\[.*\])$", re.MULTILINE)


def _asset_res_path(project: Path, raw: str) -> str | None:
    """Normalize one requested asset to its res:// path, or None if outside."""
    if raw.startswith("res://"):
        rel = raw[len("res://") :]
    else:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = project / candidate
        try:
            rel = candidate.resolve().relative_to(project.resolve()).as_posix()
        except ValueError:
            return None
    return "res://" + rel


def _asset_state(project: Path, res_path: str) -> ResourceImportAsset:
    """One asset's pre-pass verdict, decided from its sidecar and cache files."""
    rel = res_path[len("res://") :]
    sidecar_fs = project / (rel + ".import")
    if not sidecar_fs.is_file():
        return ResourceImportAsset(path=res_path, status="missing")
    sidecar_res = res_path + ".import"
    text = sidecar_fs.read_text(encoding="utf-8", errors="replace")
    matched = _DEST_FILES_LINE.search(text)
    if matched is None:
        # importer=keep style: a sidecar that declares no cache output — the
        # source is loaded as-is, so there is nothing to be missing.
        return ResourceImportAsset(path=res_path, status="cached", sidecar=sidecar_res)
    try:
        dests = [str(d) for d in json.loads(matched.group(1))]
    except ValueError:
        return ResourceImportAsset(path=res_path, status="missing", sidecar=sidecar_res)
    missing = [d for d in dests if not (project / d[len("res://") :]).is_file()]
    return ResourceImportAsset(
        path=res_path,
        status="cached" if not missing else "missing",
        sidecar=sidecar_res,
        dest_files=dests,
    )


def _project_files(project: Path) -> set[str]:
    """Every file under the project (relative posix paths), .git excluded."""
    files: set[str] = set()
    for path in project.rglob("*"):
        rel = path.relative_to(project)
        if rel.parts and rel.parts[0] == ".git":
            continue
        if path.is_file():
            files.add(rel.as_posix())
    return files


def _summarize(
    assets: list[ResourceImportAsset], created: list[ImportCreatedFile]
) -> ResourceImportSummary:
    owned = sum(1 for f in created if f.classification == "cache_owned")
    return ResourceImportSummary(
        requested=len(assets),
        cached=sum(1 for a in assets if a.status == "cached"),
        missing=sum(1 for a in assets if a.status == "missing"),
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
    make_launch: Optional[LaunchFn] = None,
) -> "ResourceImportResult | Failure":
    """Decide per asset, run the engine pass only when needed, account for it all.

    The recipe: normalize + verify the requested assets, take their cache
    verdicts, and — unless everything is cached or this is a dry run — run the
    engine's project-wide ``--import`` pass through the shared launch primitive,
    then re-verdict the assets and classify every created file against the
    cache root.
    """
    assert project is not None  # a project-using recipe; dispatch resolved it
    res_paths: list[str] = []
    for raw in params.assets:
        res_path = _asset_res_path(project, raw)
        if res_path is None:
            return make_failure(
                "invalid_params",
                f"asset {raw!r} is outside the project {project}.",
                "",
            )
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

    assets = [_asset_state(project, res_path) for res_path in res_paths]
    cache_root = "res://" + _CACHE_ROOT_REL
    needs_pass = any(asset.status == "missing" for asset in assets)

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
            summary=_summarize(assets, []),
        )

    created: list[ImportCreatedFile] = []
    if needs_pass:
        # Module-global lookup, not a def-time default, so tests patch
        # `gda.commands.resource.launch` exactly as the scene/script channels'.
        run_launch = make_launch or launch
        binary = resolve_godot_binary(godot)
        before = _project_files(project)
        raw = run_launch(
            binary,
            ["--path", str(project), "--import"],
            cwd=None,
            timeout=params.timeout,
            timeout_label="Godot import",
        )
        prefix = classify_launch_or_crash(raw, binary)
        if prefix is not None:
            return prefix
        if raw.exit_code != 0:
            return make_failure(
                "operation_failed",
                f"the engine import pass exited {raw.exit_code}",
                raw.stderr,
            )
        after = _project_files(project)
        created = [
            ImportCreatedFile(
                path="res://" + rel,
                classification=(
                    "cache_owned"
                    if rel == _CACHE_ROOT_REL or rel.startswith(_CACHE_ROOT_REL + "/")
                    else "source_adjacent"
                ),
            )
            for rel in sorted(after - before)
        ]
        # Re-verdict: what the pass settled for each previously-missing asset.
        settled: list[ResourceImportAsset] = []
        for asset in assets:
            if asset.status != "missing":
                settled.append(asset)
                continue
            now = _asset_state(project, asset.path)
            if now.status == "cached":
                settled.append(now.model_copy(update={"status": "imported"}))
            elif now.sidecar is None:
                # The pass ran and still produced no sidecar: the engine
                # decided this type needs no import (e.g. a script).
                settled.append(now.model_copy(update={"status": "not_importable"}))
            else:
                settled.append(now.model_copy(update={"status": "failed"}))
        assets = settled

    return ResourceImportResult(
        dry_run=False,
        cache_root=cache_root,
        engine_pass=needs_pass,
        assets=assets,
        created=created,
        summary=_summarize(assets, created),
    )


def _resource_import_recipe(params, *, project, godot):
    return run_resource_import_operation(project, params, godot=godot)


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
    lines = [f"  {asset.status:>14}  {asset.path}" for asset in outcome.assets]
    if outcome.created:
        lines.append(
            f"  created: {outcome.summary.created_cache_owned} cache-owned, "
            f"{outcome.summary.created_source_adjacent} source-adjacent"
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
# CLI-side (cache verdicts, the pass decision, the before/after accounting) and
# its engine call is the shared launch primitive with the project-wide
# `--import` argv — not a sentinel op, like `export run`'s native channel.
RESOURCE_IMPORT_COMMAND: HeadlessCommand[ResourceImportResult] = HeadlessCommand(
    operation="resource-import",
    input_model=ResourceImportParams,
    output_model=ResourceImportResult,
    render=render_resource_import,
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
            "without running the engine pass or writing anything."
        ),
    ),
    timeout: float = typer.Option(
        300.0,
        "--timeout",
        min=0.001,
        help="Seconds to allow the engine import pass.",
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
    checks each requested asset's cache (hit: `cached`) and, only when
    something is missing, runs the engine's import pass — which is
    PROJECT-WIDE, the engine's one scriptable import primitive — then reports
    every file the pass created, classified against the cache root
    (cache-owned under .godot/ vs source-adjacent, e.g. .import and .uid
    sidecars). `--dry-run` reports the verdicts and predictions and writes
    nothing. Plain `gda script run` never triggers an import pass. The pass
    executes engine importer code over project content (the Trusted project
    assumption, ADR-0009).
    """
    params = params_or_bad_parameter(
        ResourceImportParams, assets=assets, dry_run=dry_run, timeout=timeout
    )
    dispatch_recipe(
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
