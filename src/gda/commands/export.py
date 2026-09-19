"""The ``export`` command group: the project's export presets and artifacts.

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, the ``ExportRun`` operation (formerly ``gda.export_run``),
its native-export classifier, its human renderers, its ``HeadlessCommand``
descriptors (ADR-0023) — ``EXPORT_GET_COMMAND`` and ``EXPORT_RUN_COMMAND`` both
now at home here — and its Typer command bodies, and mounts them on the root app
through :func:`register`. It imports the shared machinery downward — the
dispatch tail (``gda.dispatch``), the descriptor machinery (``gda.headless``),
the shared failure taxonomy (``gda.errors``), the cross-command contract core
(``gda.models``) and the native-export runner seam (``gda.export_runner``) — and
is imported by nothing but the composition root (``gda.cli``).

``export list`` / ``export get`` are read-only discovery (issue #114): they parse
``export_presets.cfg`` and check the filesystem, never running an actual export.
``export run`` does, through a native ``--export-<mode>`` invocation rather than
``operations.gd``, because the export subsystem is editor-only — see the operation
section below. ``export smoke`` (ADR-0042) does not go through ``operations.gd``
either, for a different reason: what it runs is the exported game itself.
"""

import os
import plistlib
import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import Annotated, Optional
from xml.parsers.expat import ExpatError

import typer
from pydantic import AfterValidator, BaseModel, Field, model_validator

from gda import dispatch
from gda.binary import resolve_godot_binary
from gda.completed_run import (
    DEFAULT_COMPLETED_RUN_TIMEOUT_SECONDS,
    STDOUT_CAP,
    CompletedRunResult,
    bounded_stdout,
    render_completed_run,
)
from gda.dispatch import dispatch_domain, dispatch_recipe, params_or_bad_parameter
from gda.errors import (
    Failure,
    make_failure,
    classify_launch_or_crash,
    export_artifact_not_found_failure,
    export_artifact_not_runnable_failure,
    export_output_parent_failure,
    export_path_unset_failure,
    export_templates_missing_failure,
    smoke_exit_status_failure,
)
from gda.execution import ExecutionKind
from gda.export_runner import ExportRunner, make_subprocess_export_runner
from gda.harness.install import HarnessSnapshot, uninstall_harness
from gda.headless import (
    HeadlessCommand,
    RunnerFactory,
    godot_option,
    json_option,
    make_subprocess_runner,
    params_json_option,
    project_option,
)
from gda.import_evidence import (
    CACHE_ROOT_REL,
    CreatedFileClass,
)
from gda.project import expand_user
from gda.project_tree import (
    ProjectTreeInventory,
    ProjectTreeSettlement,
)
from gda.runner import (
    LaunchFn,
    RunResult,
    engine_data_path,
    launch,
    resolve_user_data_root,
)
from gda.script_errors import (
    ScriptError,
    leaked_at_exit,
    parse_script_errors,
)


def _absolute_filesystem_path(path: str) -> str:
    """``path`` with ``~`` expanded and, if relative, joined to the invocation cwd.

    The half both of this module's path fields share (#403): a relative path that
    reaches a result, a message or a subprocess unchanged is an unlocatable string
    for anyone not standing where the caller stood. Absolute, not canonical —
    ``..`` is not folded and a symlink is not resolved, because the path stays the
    one the caller named.

    It is only the half. What differs is whether the field has a VIRTUAL-path
    concept at all, and that difference belongs to the two wrappers below, not to
    a flag here.

    **Total: it never raises.** ``Path.expanduser()`` raises ``RuntimeError`` for a
    ``~unknownuser/…`` prefix it cannot resolve, which escaped ``export run
    --output`` as a traceback at exit 1 with no envelope at all — the same
    invariant the bundle's NUL refusal restores, since every gda failure is a
    typed envelope (ADR-0002 / ADR-0004). A ``~`` gda cannot expand names no user,
    so the value is simply not a home-relative path:
    :func:`gda.project.expand_user` keeps it as the caller wrote it, it is
    absolutized if relative, and the ordinary resolution answers —
    ``export_artifact_not_found`` for an artifact that does not exist under that
    literal name, an ordinary write destination under the invocation cwd for
    ``--output``. That is :func:`gda.models.normalize_path`'s precedent, total by
    construction for exactly this input (#699): normalization is a convenience, and
    whether a path is usable is decided by whoever consumes it. The rule lives HERE,
    on the shared half, so both wrappers state it once (#988 — the smoke guarded
    itself alone while ``--output`` still crashed).
    """
    expanded = expand_user(Path(path))
    if expanded.is_absolute():
        return str(expanded)
    return str(Path.cwd() / expanded)


def normalize_export_output_path(path: str) -> str:
    """Normalize an ``export run --output`` artifact path (#403).

    Export runs the native Godot export with cwd set to the project directory.
    A relative ``--output`` must therefore be made absolute against the invoker's
    cwd before the runner sees it, or Godot writes into the project tree while
    the result echoes an unlocatable relative string. Virtual paths keep the
    shared path convention and pass through unchanged.
    """
    if "://" in path:
        return path
    return _absolute_filesystem_path(path)


def normalize_smoke_artifact_path(path: str) -> str:
    """Normalize an ``export smoke`` artifact path (ADR-0042).

    The SAME absolutization ``--output`` gets, without the virtual-path branch,
    because this command has nowhere to resolve a virtual path FROM: it is
    projectless by decision, so ``res://`` and the rest name nothing here. Reusing
    ``export run``'s normalizer gave the smoke that branch by inheritance, and a
    real POSIX file addressed as ``foo://game`` then kept its relative spelling
    all the way into ``artifact`` and ``executable`` — contradicting #979's and
    CONTEXT's unconditional "a relative artifact path resolves against the
    invocation cwd" (external review, PR #987).

    The remedy is the deletion of that inherited exception for this command, not a
    second rule laid over it: one shared half above, two annotations, and the
    smoke's own one has no exception to apply. A ``://`` string is simply a
    filesystem path here, and an artifact that does not exist under that name is
    the ordinary ``export_artifact_not_found``.

    The shared half above is total for an unresolvable ``~user``. The guard this
    wrapper carried alone (#979) lives there now, so ``--output`` gets the same one
    rule (#988).
    """
    return _absolute_filesystem_path(path)


ExportOutputPath = Annotated[str, AfterValidator(normalize_export_output_path)]
SmokeArtifactPath = Annotated[str, AfterValidator(normalize_smoke_artifact_path)]


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


def resolve_host_data_path() -> str | None:
    """The host's Godot data directory, resolved over gda's OWN environment (#840).

    The value stamped on :attr:`ExportGetParams.host_data_path`, and the whole mechanism
    behind #840's disclosure. ``--user-data-root`` redirects the CHILD engine's
    data directory, never gda's own environment, so this stays the directory an
    unredirected run would use — exactly the one the engine cannot see from inside
    the redirect, and therefore the one worth passing in.

    ``None`` when the platform's own variable is unset, which is what
    :func:`gda.runner.engine_data_path` answers rather than fabricating a path; the
    operation then reports no host directory instead of comparing against a guess.
    """
    resolved = engine_data_path()
    return str(resolved) if resolved is not None else None


class ExportGetParams(BaseModel):
    """The operation params of ``gda export get`` (issue #114, #840).

    ``preset`` addresses an export preset by its display name (as ``export
    list`` reports it). An unknown name is the ``export_preset_not_found``
    failure. The project is process context (``--project``, ADR-0006).

    ``host_data_path`` is a COMPUTED param, the same shape ``script set``'s
    ``mode`` has: the model stamps it from the host environment so the engine-side
    check can name templates a ``--user-data-root`` redirect hid (#840), and a
    value passed in is ignored. Computed model-side rather than pasted in by the
    argv body because ADR-0015 makes the model the single source of truth for a
    request's shape — a ``--params-json`` caller that names only ``preset`` has to
    reach the operation with the identical params, and it is not a fact a caller
    is in any position to supply.
    """

    preset: str = Field(
        description="The export preset's display name, as 'gda export list' reports it."
    )
    host_data_path: str | None = Field(
        default=None,
        description=(
            "The host's Godot data directory, so the check can name export "
            "templates a --user-data-root redirect hides. Resolved model-side "
            "from gda's own environment; a value passed in is ignored."
        ),
    )

    @model_validator(mode="after")
    def _resolve_host_data_path(self) -> "ExportGetParams":
        # Stamped on BOTH input channels (ADR-0015): the argv body and
        # `--params-json` build this same model, so neither can reach the operation
        # without the host directory and neither can reach it with a caller's guess
        # at one.
        self.host_data_path = resolve_host_data_path()
        return self


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

    ``templates_root`` says WHERE it looked (#840) — the export-templates
    directory that holds the version directory. It is reported because that
    location is not fixed: Godot reads the templates from its data directory, and
    ``--user-data-root`` relocates exactly that, so a redirected run reports none
    installed on a host whose templates are correctly installed.
    ``templates_root_host`` names the host's directory in that case and ONLY in
    that case, so the two situations — hidden by a redirect, versus genuinely not
    installed anywhere — are told apart before an export is ever attempted.
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
    templates_root: str = Field(
        description=(
            "The export-templates directory that was checked; the "
            "templates_version directory is looked up inside it."
        )
    )
    templates_root_host: str | None = Field(
        description=(
            "The host's export-templates directory, when a --user-data-root "
            "redirect hid templates that ARE installed there; null otherwise."
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
    output: ExportOutputPath | None = Field(
        default=None,
        description=(
            "Override the preset's configured export_path; a relative filesystem "
            "path is resolved against the invoker's current working directory "
            "before export."
        ),
    )


class ExportCreatedFile(BaseModel):
    """One file the export run added to the project tree (#839).

    ``classification`` is :func:`gda.import_evidence.classify_created_file`'s
    verdict — the same ``cache_owned`` / ``source_adjacent`` vocabulary ``resource
    import`` reports, from the same function, because the native export runs the
    same editor import pass. ``size`` is what the file holds after the export, and
    the entries' sizes add up to ``created_bytes``.
    """

    path: str = Field(description="The created file's res:// path.")
    classification: CreatedFileClass = Field(
        description="cache_owned (under the cache root) or source_adjacent."
    )
    size: int = Field(description="The created file's size in bytes.")


class ExportModifiedFile(BaseModel):
    """One pre-existing project file the export run rewrote (#839).

    Content, never timestamps: the import pass touches files it does not rewrite,
    and that noise would bury the few generated resources the record is about.
    ``size_before`` is the fact only the pre-export walk can state — after the
    export the earlier bytes are gone.
    """

    path: str = Field(description="The rewritten file's res:// path.")
    size: int = Field(description="The file's size in bytes after the export.")
    size_before: int = Field(description="The file's size in bytes before the export.")


class ProjectTreeMutations(BaseModel):
    """The project-tree mutation report of one ``gda export run`` (#839).

    The native export runs the editor import pass over the project, so an export
    against a cold cache creates the whole cache tree plus the sidecars beside the
    sources, and can rewrite generated resources that are tracked in git. None of
    that was observable in the result before (GDA-DF-067: about 14,000 new files
    and two to four rewritten ``.translation`` resources appeared on disk while
    ``warnings`` stayed empty). The report is DISCLOSURE — the export deletes and
    restores nothing — so an agent can review, stage or restore the tree without a
    manual git snapshot.

    What it covers, and what it deliberately leaves out:

    * ``created`` is every file the tree gained, ANYWHERE under the project,
      classified against ``cache_root`` so the cache half can be cleaned as one
      unit. A directory link is walked as the engine reads it, once each: the
      shared assets directory a monorepo links in is content the import pass
      writes into.
    * ``modified`` is every pre-existing file OUTSIDE ``cache_root`` whose CONTENT
      changed. A pre-existing file is a CANDIDATE only when its size or timestamp
      moved, so a rewrite that preserves both is not seen. A pre-existing cache
      file stays out altogether: the cache is reported as one unit, a warm export
      rewrites its bookkeeping files on every run, and hashing it beforehand would
      cost far more than the fact is worth (the dogfooding case holds about
      1.1 GiB there). So an unchanged ``modified`` says nothing about the cache.
    * The artifact and everything under it are out of both lists — a directory
      artifact such as a macOS ``.app`` bundle included — and so is a top-level
      ``.git`` directory, which the engine never writes to. The exclusion stops
      there: a file the export writes BESIDE the artifact (a Linux binary with
      ``binary_format/embed_pck=false`` gets a ``game.pck`` next to it) is a
      created file like any other.
    * Deletions are not reported: the pass adds and rewrites.
    * ``skipped`` counts what neither walk could account for — an entry that is
      not a regular file (a FIFO, a socket, a device), a vanished or unreadable
      file, a dangling symlink, a directory that cannot be listed (whose whole
      subtree is then outside both lists). gda never opens a non-regular entry.
      None of it fails an export that succeeded; it is a COUNT, not a path list,
      so the remedy is to repair the tree and run again for a complete record.

    The report covers the engine's DEFAULT cache directory. A project that sets
    ``application/config/use_hidden_project_data_directory=false`` keeps its cache
    under ``godot/``, whose files then read as ``source_adjacent``; that case is
    out of scope for this report (#839).
    """

    cache_root: str = Field(
        default="res://" + CACHE_ROOT_REL,
        description=(
            f"The cache root created files are classified against "
            f"(res://{CACHE_ROOT_REL})."
        ),
    )
    created: list[ExportCreatedFile] = Field(
        default_factory=list,
        description=(
            "Every file the export added anywhere under the project, classified, "
            "ordered by path. Directory links are walked as the engine reads "
            "them, once each."
        ),
    )
    modified: list[ExportModifiedFile] = Field(
        default_factory=list,
        description=(
            "Every pre-existing file outside the cache root whose content the "
            "export rewrote, ordered by path. Only a file whose size or timestamp "
            "moved is compared, so a rewrite that preserves both is not reported; "
            "rewrites inside the cache root are not reported at all."
        ),
    )
    created_count: int = Field(default=0, description="Files the export created.")
    created_cache_owned: int = Field(
        default=0, description="Created files under the cache root."
    )
    created_source_adjacent: int = Field(
        default=0, description="Created files beside the sources."
    )
    created_bytes: int = Field(
        default=0, description="Total size in bytes of the created files."
    )
    modified_count: int = Field(default=0, description="Files the export rewrote.")
    modified_bytes: int = Field(
        default=0,
        description="Total size in bytes of the rewritten files after the export.",
    )
    skipped: int = Field(
        default=0,
        description=(
            "What neither list could account for: entries that are not regular "
            "files, or could not be read — including a directory whose whole "
            "subtree is then uncovered. A count only; repair the tree and run "
            "again for a complete record."
        ),
    )

    @model_validator(mode="after")
    def _counts_match_the_lists(self) -> "ProjectTreeMutations":
        # gda's own invariant, not input validation: the counts exist so a caller
        # can read the summary without walking a list that holds thousands of cache
        # files, which is only worth anything while the two agree (the #732 lesson,
        # as `resource import` pins it for its own summary).
        owned = sum(
            1 for entry in self.created if entry.classification == "cache_owned"
        )
        if (
            self.created_count,
            self.created_cache_owned,
            self.created_source_adjacent,
            self.created_bytes,
            self.modified_count,
            self.modified_bytes,
        ) != (
            len(self.created),
            owned,
            len(self.created) - owned,
            sum(entry.size for entry in self.created),
            len(self.modified),
            sum(entry.size for entry in self.modified),
        ):
            raise ValueError("the mutation counts must match the reported lists.")
        return self


class ExportRunResult(BaseModel):
    """The result of ``gda export run``: the artifact that was produced (issue #121).

    Echoes the addressed preset's ``preset`` name and target ``platform`` (read
    from ``export_presets.cfg``), the ``mode`` that was run (the selected flavor,
    ``release`` by default; #170), and the resolved absolute ``output_path`` the
    artifact was written to — the effective destination, i.e. the ``--output``
    override when given, else the preset's configured ``export_path`` resolved
    against the project directory (#403). ``created_dirs`` lists output parent
    directories created before the native export, from outermost to innermost
    (#402).
    ``warnings`` carries the engine's non-fatal export warnings (e.g. a missing
    optional icon), parsed best-effort from the export's stderr; an export that
    succeeds cleanly reports ``warnings == []``. Unlike the sentinel operations,
    ``export run`` is a native Godot export (the export subsystem is editor-only,
    ADR-0002 sentinels do not apply), so this result is synthesized by ``gda``
    from the export's exit code + stderr.

    ``project_tree_mutations`` reports what the export did to the PROJECT (#839) —
    the cache and sidecars it created, the generated resources it rewrote — which
    ``warnings`` never said and never will: that key keeps its own meaning, the
    engine's advisories.
    """

    preset: str = Field(description="The export preset's display name.")
    platform: str = Field(
        description="The preset's target platform (e.g. Linux/X11, Web, macOS)."
    )
    mode: ExportRunMode = Field(description="The export flavor that was run.")
    output_path: str = Field(
        description="The resolved absolute path the export artifact was written to."
    )
    created_dirs: list[str] = Field(
        description=(
            "Output parent directories created before export, from outermost to innermost."
        )
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="The engine's non-fatal export warnings, parsed from stderr; empty on a clean export.",
    )
    project_tree_mutations: ProjectTreeMutations = Field(
        default_factory=ProjectTreeMutations,
        description=(
            "What the export changed in the project tree: the files it created "
            "(classified) and the pre-existing files it rewrote, with counts and "
            "total bytes. The report is the difference between gda's walk before "
            "the export and its walk after; gda assumes it is the project's sole "
            "driver during the export (ADR-0018), so a change another writer makes "
            "in that interval is attributed to the export."
        ),
    )


def render_export_list(listed: "ExportListResult") -> str:
    """Render the enumerated presets as ``name (platform) [runnable]`` lines."""
    if not listed.presets:
        return "(no presets)"
    lines = []
    for preset in listed.presets:
        runnable = " [runnable]" if preset.runnable else ""
        lines.append(f"{preset.name} ({preset.platform}){runnable}")
    return "\n".join(lines)


def render_export_get(got: "ExportGetResult") -> str:
    """Render one preset's details plus its export-template readiness.

    The template line names the directory that was checked, and — when a
    ``--user-data-root`` redirect hid installed templates — a second line names
    where they really are (#840), so the human channel says exactly what the JSON
    one does.
    """
    runnable = " [runnable]" if got.runnable else ""
    header = f"{got.name} ({got.platform}){runnable}"
    state = "installed" if got.templates_installed else "missing"
    lines = [
        header,
        f"  export_path: {got.export_path}",
        f"  templates {state} ({got.templates_version}) in {got.templates_root}",
    ]
    if got.templates_root_host:
        lines.append(
            "  hidden by the user-data redirect (--user-data-root / "
            f"$GDA_USER_DATA_ROOT); host templates: {got.templates_root_host}"
        )
    return "\n".join(lines)


def _render_mutations(mutations: "ProjectTreeMutations") -> str:
    """Summarize the project-tree mutation report in one line (#839).

    Counts only: the lists hold one entry per created cache file, which is
    thousands of them on a cold cache, and a human channel that printed them
    would bury the export it is reporting. The JSON result carries the entries.

    The quiet line says "unchanged OUTSIDE the cache root" rather than
    "unchanged", because that is the scope the report vouches for: a warm export
    rewrites its own cache bookkeeping on every run, and those rewrites are
    deliberately outside what the walks compare. An unreadable path is named on
    either line — a record that could not read part of the tree must not print
    as a clean one.
    """
    if mutations.created or mutations.modified:
        parts = [
            f"{mutations.created_count} created "
            f"({mutations.created_cache_owned} under {mutations.cache_root}, "
            f"{mutations.created_source_adjacent} beside the sources, "
            f"{mutations.created_bytes} bytes)",
            f"{mutations.modified_count} rewritten ({mutations.modified_bytes} bytes)",
        ]
    else:
        parts = [f"unchanged outside {mutations.cache_root}"]
    if mutations.skipped:
        parts.append(f"{mutations.skipped} unreadable")
    return "  project tree: " + ", ".join(parts)


def render_export_run(ran: "ExportRunResult") -> str:
    """Render a completed export as ``exported <preset> (<platform>, <mode>) -> <path>``.

    Echoes the artifact that was produced, then one ``warning: …`` line per
    non-fatal engine warning, then the one-line project-tree mutation summary
    (#839) — appended last so the warning block keeps the shape it had.
    """
    header = (
        f"exported {ran.preset} ({ran.platform}, {ran.mode.value}) -> {ran.output_path}"
    )
    return "\n".join(
        [
            header,
            *[f"  warning: {w}" for w in ran.warnings],
            _render_mutations(ran.project_tree_mutations),
        ]
    )


# A non-fatal export warning the engine prints to stderr. WARNING is Godot's
# WARN_PRINT prefix; these never fail the export (it still exits 0) but are
# surfaced advisorily on the success result (ADR-0002: stderr is advisory for
# success diagnostics), so an agent sees e.g. a missing optional icon.
_EXPORT_WARNING_LINE = re.compile(
    r"^[ \t]*WARNING:[ \t]*(?P<message>.+?)[ \t]*$", re.MULTILINE
)


def parse_export_warnings(stderr: str) -> list[str]:
    """Parse advisory export warnings from a native export's stderr (issue #121).

    A pure function: the engine's ``WARN_PRINT`` lines are advisory-only (they
    never determine the success/failure outcome — a warned export still exits 0),
    so they are surfaced as best-effort diagnostics on the success result.
    Returns ``[]`` when the export was clean.
    """
    return [m.group("message") for m in _EXPORT_WARNING_LINE.finditer(stderr)]


# --- The project-tree mutation report's inventory (#839, #985) ---------------
#
# The walk and the two-capture settlement are NOT here: they are the `Project
# tree inventory` (:mod:`gda.project_tree`), which `resource import` reads too —
# one Python enumeration of the project's files, under one set of rules, for the
# two results each command's own engine pass produces. What stays here is what
# only the export knows: the artifact it asked the engine to write (passed to
# the walk as the one thing to keep out), and the shape of the published report.


# The one virtual scheme that names a path INSIDE the project (ADR-0006). Both
# `--output res://out.pck` and a preset `export_path` may spell the destination
# this way, and the engine resolves it against the project root — so the report
# has to resolve it the same way before the walk can keep it out (#981 round 3).
_RES_SCHEME = "res://"


def _artifact_to_exclude(project: Path, output_path: str) -> Path | None:
    """The artifact THIS export writes, resolved as the engine resolves it (#839).

    Export output-path POLICY, so it belongs to the group that owns the
    destination rather than to the shared inventory, which takes a ``Path`` and
    knows only how to keep it out (#985; PR #989 external review). A ``res://``
    destination is relative to the project; another virtual scheme cannot name an
    artifact in this tree; a relative filesystem path resolves against the
    project and an absolute one is taken as given, since a destination outside
    the project can still be visible through a directory link inside it.

    What the inventory then does with the answer is its own rule: it excludes the
    file by its PARENT's filesystem identity and this name, not by comparing two
    path strings, so the destination's spelling need not be the one the walk
    reaches it by — and an ``.app`` subtree is excluded without hiding the files
    beside it.
    """
    if output_path.startswith(_RES_SCHEME):
        rest = output_path[len(_RES_SCHEME) :].lstrip("/")
        return project / rest if rest else None
    if not output_path or "://" in output_path:
        return None
    path = Path(output_path)
    return path if path.is_absolute() else project / path


def _mutation_report(settlement: ProjectTreeSettlement) -> ProjectTreeMutations:
    """The published report of one settled `Project tree inventory` (#839).

    A rendering, not a second rule: the entries take the ``res://`` spelling the
    result publishes, and the counts are derived here — they are this result's
    own summary of its own lists, which the model's validator then pins to them.
    """
    created = [
        ExportCreatedFile(
            path="res://" + entry.rel,
            classification=entry.classification,
            size=entry.size,
        )
        for entry in settlement.created
    ]
    modified = [
        ExportModifiedFile(
            path="res://" + entry.rel,
            size=entry.size,
            size_before=entry.size_before,
        )
        for entry in settlement.modified
    ]
    owned = sum(1 for entry in created if entry.classification == "cache_owned")
    return ProjectTreeMutations(
        created=created,
        modified=modified,
        created_count=len(created),
        created_cache_owned=owned,
        created_source_adjacent=len(created) - owned,
        created_bytes=sum(entry.size for entry in created),
        modified_count=len(modified),
        modified_bytes=sum(entry.size for entry in modified),
        skipped=settlement.skipped,
    )


def classify_export_run(
    output: RunResult,
    binary: Path,
    *,
    preset: str,
    platform: str,
    mode: ExportRunMode,
    output_path: str,
    created_dirs: list[str],
    inventory: "ProjectTreeInventory | None" = None,
) -> ExportRunResult | Failure:
    """Classify a native Godot export into a typed result or a ``Failure`` (issue #121).

    ``export run`` is the one command that does NOT emit an ADR-0002 sentinel —
    the export subsystem is editor-only, so the artifact is produced by a native
    ``--export-<mode>`` invocation. gda synthesizes the structured outcome from
    the subprocess's **exit code** instead (ADR-0010): a clean exit is success
    (with any advisory warnings parsed off stderr); a non-zero exit is the
    classifier-source ``export_failed``. Crucially, this does NOT parse stderr to
    *choose* the code — that would violate ADR-0002's "stderr is never parsed for
    stable codes". The distinct ``export_templates_missing`` mode is decided
    *before* the native run by the CLI's structured preflight (``export get``'s
    ``templates_installed``), not here; on a non-zero export stderr is surfaced
    only as the advisory ``message`` / diagnostics.

    The decision tree shares :func:`classify_launch_or_crash`'s env/crash prefix
    so a missing binary or hung export is reported identically across both
    channels (#185); only the non-zero-exit tail differs from the sentinel
    channel (synthesize-from-exit-code, no sentinel parse).

    The project-tree mutation report is SETTLED here, on the success branch only
    (#839): the second walk is work a failed export should not pay for, and the
    report is a property of a completed export — a failure answers through the
    `Error envelope`, which carries no such record. ``inventory`` is the
    pre-export walk :func:`run_export_operation` takes for every resolved project;
    ``None`` is reachable only without a project, and then there is no tree to
    report on.
    """
    prefix = classify_launch_or_crash(output, binary)
    if prefix is not None:
        return prefix
    if output.exit_code != 0:
        # Templates are checked structurally BEFORE this call (the CLI preflights
        # export get's templates_installed), so a missing-templates run never
        # reaches here. Every non-zero native export is therefore the generic
        # classifier-source export_failed; the engine's stderr is preserved only
        # as advisory diagnostics (ADR-0002), never parsed to pick the code.
        return make_failure(
            "export_failed",
            f'export of preset "{preset}" failed',
            output.stderr,
        )
    return ExportRunResult(
        preset=preset,
        platform=platform,
        mode=mode,
        output_path=output_path,
        created_dirs=created_dirs,
        warnings=parse_export_warnings(output.stderr),
        project_tree_mutations=(
            _mutation_report(inventory.settle())
            if inventory is not None
            else ProjectTreeMutations()
        ),
    )


# --- The ExportRun operation — ``gda export run``'s resolve → preflight → run
# recipe ---------------------------------------------------------------------
#
# Unlike every other Phase-1 capability, an export cannot run through
# ``operations.gd``: the Godot export subsystem is editor-only C++, unreachable
# from a ``--headless --script`` SceneTree run, so the export itself is a native
# ``--export-<mode>`` invocation (ADR-0010, :mod:`gda.export_runner`). ``export
# run`` therefore hand-orchestrates a multi-phase recipe rather than the shared
# sentinel pipeline:
#
# 1. **resolve** the preset via the existing ``export-get`` sentinel op — reusing
#    #114's clean preset/project errors;
# 2. **structured preflight** (effective destination + template readiness + output
#    parent dirs, ADR-0010) that fails fast — ``export_path_unset`` /
#    ``export_templates_missing`` / ``export_output_parent_failed`` — with NO
#    native run;
# 3. the native ``--export-<mode>`` run, whose raw outcome
#    :func:`classify_export_run` turns into the typed result.
#
# :func:`run_export_operation` RETURNS its outcome (``ExportRunResult | Failure``)
# instead of emitting the public result or exiting — so the command body below
# shrinks to the same thin shape as every other command and the recipe gets its
# own engine-free test surface (driven with the two injected seams; see
# ``tests/export/test_export_run_operation.py``). It is not side-effect-free: phase 1's
# ``HeadlessCommand.execute`` still forwards the ``export-get`` engine stderr to
# this process's stderr as advisory diagnostics, and phase 3 emits a native-export
# progress line to stderr; only the public result/error envelope and the process
# exit are deferred to the CLI caller.


# The factory seam for the native export runner — the ``export run``-only twin of
# the sentinel channel's ``RunnerFactory``. Spelled here (not in ``headless``)
# because only the export recipe spawns a native ``--export-<mode>`` process.
ExportRunnerFactory = Callable[[Path, Optional[Path]], ExportRunner]


EXPORT_GET_COMMAND: HeadlessCommand[ExportGetResult] = HeadlessCommand(
    operation="export-get",
    input_model=ExportGetParams,
    output_model=ExportGetResult,
    render=render_export_get,
)


def _resolve_configured_export_path(path: str, project: Optional[Path]) -> str:
    """Resolve a preset export_path to the absolute artifact path (#403)."""
    if not path or "://" in path:
        return path
    configured = Path(path)
    if configured.is_absolute():
        return str(configured)
    base = Path.cwd() if project is None else project
    if not base.is_absolute():
        base = Path.cwd() / base
    return str(base / configured)


def _ensure_output_parent_dirs(output_path: str) -> list[str] | Failure:
    """Create the export destination's missing filesystem parent dirs (#402)."""
    if "://" in output_path:
        return []

    parent = Path(output_path).parent
    if str(parent) in {"", "."}:
        return []
    if parent.exists():
        if parent.is_dir():
            return []
        return export_output_parent_failure(output_path, str(parent))

    missing: list[Path] = []
    cursor = parent
    while not cursor.exists():
        missing.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent

    if cursor.exists() and not cursor.is_dir():
        return export_output_parent_failure(output_path, str(cursor))

    created_dirs = [str(path) for path in reversed(missing)]
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return export_output_parent_failure(output_path, str(parent))
    if not parent.is_dir():
        return export_output_parent_failure(output_path, str(parent))
    return created_dirs


def run_export_operation(
    *,
    preset: str,
    mode: ExportRunMode,
    output_override: Optional[str],
    godot: Optional[str],
    project: Optional[Path],
    make_runner: RunnerFactory = make_subprocess_runner,
    make_export_runner: ExportRunnerFactory = make_subprocess_export_runner,
) -> ExportRunResult | Failure:
    """Run ``export run``'s resolve → preflight → native-run → classify recipe.

    Returns its outcome instead of emitting or exiting: the typed
    ``ExportRunResult`` on success or a ``Failure`` at any phase — the CLI layer
    owns the public emit/exit channel. Not side-effect-free, though: phase 1's
    ``HeadlessCommand.execute`` still forwards the ``export-get`` engine stderr to
    this process's stderr as advisory diagnostics, and this recipe writes the
    native export progress line to stderr; only the public result/error envelope
    and the exit are deferred to the caller. ``output_override`` is the
    already-CLI-normalized
    ``--output`` value (ADR-0006 path normalization stays at the CLI); both
    engine-touching seams (``make_runner`` for ``export-get``, ``make_export_runner``
    for the native export) are injected, so the recipe is fully testable without a
    real engine.
    """
    # Phase 1 (resolve): the preset via the existing export-get sentinel op. This
    # reuses #114's clean structured errors — an unknown preset is
    # export_preset_not_found, a project with no export_presets.cfg is
    # export_presets_not_found — returned as a Failure before any native export.
    got = EXPORT_GET_COMMAND.execute(
        ExportGetParams(preset=preset),
        godot=godot,
        project=project,
        make_runner=make_runner,
    )
    if isinstance(got, Failure):
        return got

    # Resolve the effective destination: --output (already CLI-normalized and
    # invoker-cwd absolute for relative filesystem paths, #403) wins over the
    # preset's configured export_path (#170). A configured relative export_path
    # keeps Godot's project-relative convention, but we pass/report the absolute
    # artifact path so the result is self-describing for consumers.
    output_path = (
        output_override
        if output_override is not None
        else _resolve_configured_export_path(got.export_path, project)
    )

    # Phase 2 (structured preflight, BEFORE any native run; ADR-0010). The first
    # two fail-fast checks are decided from export get's structured fields rather
    # than from the engine's stderr (which ADR-0002 forbids parsing for codes):
    #
    #  - There must be a destination, for EVERY mode. --output supplies one
    #    directly (#170); only when no override is given AND the configured
    #    export_path is empty is there nowhere to write — export_path_unset.
    #    Checked first because it is a config/argument error independent of the
    #    engine's template state, so it stays deterministic whether or not
    #    templates happen to be installed.
    #  - Templates for the running engine version must be installed — but ONLY
    #    for release/debug, never for pack (#170). release/debug produce a full
    #    platform binary and need the matching platform export templates; pack
    #    produces project data only (a PCK/ZIP via Godot's native --export-pack)
    #    and needs no platform templates (ExportRunMode's docstring; confirmed on
    #    Godot 4.6.3, where a template-less --export-pack writes a .pck). Gating
    #    pack out lets template-less environments use the mode that works there.
    #    export get reports template readiness structurally (templates_installed)
    #    — the readiness check built for exactly this — so a release/debug export
    #    against an uninstalled template version is the distinct
    #    export_templates_missing, decided here rather than by string-matching the
    #    engine's "due to configuration errors" stderr (which also fires for a
    #    merely-misconfigured preset).
    #  - Once the export is otherwise runnable, create the destination's missing
    #    parent directories before the native export so a missing directory never
    #    falls through to locale/version-dependent engine prose (#402). An
    #    uncreatable parent is a structured export_output_parent_failed.
    if not output_path:
        return export_path_unset_failure(got.name)
    if mode is not ExportRunMode.PACK and not got.templates_installed:
        # Both directories ride the failure (#840): the one the engine checked, and
        # — when a --user-data-root redirect hid installed templates — the host's,
        # which is what turns "install the templates" into "you already have them,
        # this run cannot see them".
        return export_templates_missing_failure(
            got.name,
            got.templates_version,
            got.templates_root,
            got.templates_root_host,
        )
    created_dirs = _ensure_output_parent_dirs(output_path)
    if isinstance(created_dirs, Failure):
        return created_dirs

    # Phase 3 (native run + classify): run the native export and classify its raw
    # outcome. The export-get resolved name (got.name) is authoritative throughout
    # — it is what the engine exports and what the result echoes — so the native
    # invocation, not the raw --preset string, is keyed on it.
    binary = resolve_godot_binary(godot)
    export_runner = make_export_runner(binary, project)
    # The dev-only harness must never reach the artifact (ADR-0028): an export
    # cannot strip a project.godot autoload after the fact (it is serialized whole
    # into project.binary), so the only reliable guarantee is that the harness is
    # already gone before the native export reads the project. SNAPSHOT the exact
    # pre-export state, paired-uninstall the harness (autoload entry + files,
    # crash-safe ordering) so the export sees a clean project, then restore the
    # snapshot — byte-for-byte, NOT a fresh install (which would add/canonicalize an
    # autoload or rewrite stale bytes, mutating a project that was not cleanly
    # installed). The dev project is thus left byte-identical and the step is
    # forget-proof (no `gda daemon uninstall` needed). A no-op when no harness is
    # present; if gda dies mid-export the project is left harness-ABSENT (the safe
    # direction — no dangling autoload), and the next `daemon start` reinstalls it.
    #
    # The strip runs INSIDE the guarded region, not before it (PR #680 review): the
    # strip is itself a multi-step mutation — entry, script, sidecar, directory — so
    # a failure PART WAY THROUGH it (an unlink that hits a permission error, say) is
    # exactly the case the restore exists for. Capturing outside and stripping inside
    # means the `finally` covers a partial strip too, not just a failed export.
    #
    # The mutation report's pre-export walk (#839) is taken HERE, outside the
    # guarded region: the snapshot restores the harness byte for byte, so its
    # files are present in both walks with equal content and the restore's fresh
    # timestamps meet the content rule rather than the timestamp. Capturing inside
    # would instead make gda's own strip a mutation of the project it is reporting
    # on. The destination is known by now, so the artifact is excluded from the
    # first walk rather than filtered out of the second.
    inventory = (
        ProjectTreeInventory.capture(
            project,
            artifact=_artifact_to_exclude(project, output_path),
            detect_rewrites=True,
        )
        if project is not None
        else None
    )
    snapshot = HarnessSnapshot.capture(project) if project is not None else None
    try:
        if project is not None:
            uninstall_harness(project)
        print(
            f'gda: exporting preset "{got.name}" ({mode.value}) ...',
            file=sys.stderr,
        )
        export_output = export_runner.run(got.name, mode.value, output_path)
    finally:
        if snapshot is not None:
            snapshot.restore()
    return classify_export_run(
        export_output,
        binary,
        preset=got.name,
        platform=got.platform,
        mode=mode,
        output_path=output_path,
        created_dirs=created_dirs,
        inventory=inventory,
    )


EXPORT_LIST_COMMAND: HeadlessCommand[ExportListResult] = HeadlessCommand(
    operation="export-list",
    input_model=ExportListParams,
    output_model=ExportListResult,
    render=render_export_list,
)


# The ``export run`` recipe channel (ADR-0023): it PRODUCES the outcome — run the
# CLI-side operation over the ALREADY-resolved ``project`` (resolution happens once in
# :func:`gda.dispatch.dispatch_recipe`, kept CLI-side per ADR-0006, so an invalid
# --project is a structured project_not_found before the recipe runs, #353) — and
# RETURNS the typed result or a Failure; emission stays the shared tail, so this
# command renders exactly like a sentinel one. Both runner seams (``dispatch.make_*``)
# are referenced at call time — as attributes on the module, never imported by name —
# so test monkeypatches on ``gda.dispatch.make_runner`` /
# ``gda.dispatch.make_export_runner`` still bind. ``params`` is the built model — the
# single source of truth (ADR-0015), identical on the argv and ``--params-json`` paths
# — so preset/mode/output are read off it, never special-cased.
def _export_run_recipe(params, *, project, godot):
    return run_export_operation(
        preset=params.preset,
        mode=params.mode,
        output_override=params.output,
        godot=godot,
        project=project,
        make_runner=dispatch.make_runner,
        make_export_runner=dispatch.make_export_runner,
    )


# ``export-run`` does NOT route through operations.gd: the Godot export subsystem is
# editor-only C++, so the export is a native --export-<mode> invocation driven by
# :func:`run_export_operation` above. Its descriptor is the single fully-bound
# registration (ADR-0023). It used to live in ``gda.cli`` because its recipe needs the
# runner seams; those now sit in ``gda.dispatch`` and are reached late (as module
# attributes), so descriptor, recipe and operation are all at home in this group
# module (ADR-0040) — as is its sibling ``EXPORT_GET_COMMAND``, the plain sentinel
# command ``run_export_operation`` drives directly.
EXPORT_RUN_COMMAND: HeadlessCommand[ExportRunResult] = HeadlessCommand(
    operation="export-run",
    input_model=ExportRunParams,
    output_model=ExportRunResult,
    kind=ExecutionKind.EXPORT,
    render=render_export_run,
    recipe=_export_run_recipe,
)


# --- The ArtifactSmoke operation — ``gda export smoke``'s bounded headless run of
# a caller-selected `Export artifact` (ADR-0042).
#
# ``export run`` reports whether Godot CONSTRUCTED an artifact; it does not run it.
# GDA-DF-072 is why that is not enough: the first exported candidate loaded the
# whole game and then reported four leaked WAV resources at exit, while ``export
# run`` had returned ``warnings: []``. The defect was observable only by launching
# the exported game, so this command launches it — once, headless, bounded — and
# returns the completed process as evidence.
#
# It is the SECOND executable source of the shared `Headless launch` (the first
# being the configured editor binary every other Phase-1 channel uses): the Godot
# executable resolved inside the artifact. Everything else about the launch is the
# primitive's — spawn, streaming capture, timeout, the gda-owned ``--log-file``,
# UTF-8 decoding, normalized launch failures — so this section owns only what the
# primitive cannot know: how to resolve an artifact to an executable, where to put
# a private ``user://`` for a caller-selected game, and the two-trigger ``--strict``
# gate.
#
# It is PROJECTLESS (descriptor ``inherits_project=False``, no ``--project``): the
# artifact is a path the caller selected, and gda holds no fact tying it to a
# resolved `Trusted project`, which is also why it is a separate caller-artifact
# execution point rather than part of the `Project-code execution surface`.

# The DEFAULT ceiling on one ``export smoke``, when the caller states none. This
# channel's public name for the shared completed-run ceiling
# (:data:`gda.completed_run.DEFAULT_COMPLETED_RUN_TIMEOUT_SECONDS`), which owns the
# number and the reasoning. An alias, not a second literal: this command's help,
# its params description and the catalog all state that it is the same ceiling
# ``script run`` uses, and two equal literals would let an edit to either silently
# falsify all three (#979 review).
DEFAULT_SMOKE_TIMEOUT_SECONDS = DEFAULT_COMPLETED_RUN_TIMEOUT_SECONDS

# How a timeout NAMES this launch, beside "Godot script" / "Godot export" /
# "Godot import" / "Godot scene preflight" (#714).
SMOKE_TIMEOUT_LABEL = "Godot artifact smoke"

# Where a macOS bundle declares the executable to run, and the directory that
# executable sits in. Read with ``plistlib`` (stdlib, and it reads both the XML and
# the binary plist Godot writes); nothing else in the bundle is inspected.
_BUNDLE_SUFFIX = ".app"
_BUNDLE_PLIST_REL = ("Contents", "Info.plist")
_BUNDLE_EXECUTABLE_KEY = "CFBundleExecutable"
_BUNDLE_MACOS_REL = ("Contents", "MacOS")


def _is_runnable_file(path: Path) -> bool:
    """Is ``path`` a regular file this host may execute?

    ``os.stat`` follows links, so a symlink to a runnable file IS one — the same
    symlink-agnostic reading the rest of gda's path handling uses. Anything that is
    not a regular file (a directory, a FIFO, a socket, a device) is not runnable
    here whatever its mode bits say, and neither is a regular file without the
    execute permission this process would need.
    """
    try:
        return S_ISREG(os.stat(path).st_mode) and os.access(path, os.X_OK)
    except (OSError, ValueError):
        # ``ValueError`` is the syscall refusing the STRING, not the filesystem
        # refusing the file — an embedded NUL is the one shape that reaches it.
        # A path the host cannot even ask about is honestly "not runnable", and
        # answering so here closes the class rather than one instance of it: it
        # must never escape this resolver as a traceback (external review, PR #987).
        return False


def _one_filename(name: str) -> bool:
    """Is ``name`` ONE filename — a single component under the bundle's MacOS dir?

    The rule the resolver PUBLISHES is that a `.app` runs
    ``Contents/MacOS/<CFBundleExecutable>``, and `Path.joinpath` does not enforce
    it: an absolute value (`/bin/echo`) replaces the whole prefix and a `..` value
    climbs out of it, so gda would launch a program outside the artifact the
    caller selected and publish it as ``executable`` (external review, PR #987).
    The bundle's own metadata is the caller's input here, not gda's.

    So this is a plain filename test, and nothing more: no sandbox, no
    containment check on the joined result, no identity or provenance notion —
    one usable filename is the whole rule, and every other value is the existing
    ``export_artifact_not_runnable`` refusal. A blank value names nothing, and a
    NUL is a string the syscall cannot even carry.
    """
    if not name.strip() or "\x00" in name:
        return False
    if "/" in name or os.sep in name:
        return False
    return name not in (".", "..")


def resolve_artifact_executable(artifact: str) -> "Path | Failure":
    """Resolve a caller's `Export artifact` to the executable to launch (ADR-0042).

    Two accepted shapes and no third. A regular file the host may execute is
    accepted AS GIVEN. A macOS ``.app`` bundle names its own main executable in
    ``Contents/Info.plist`` under ``CFBundleExecutable``, and the resolved path is
    ``Contents/MacOS/<that name>``, which must itself be a regular file the host
    may execute. Everything else is refused: any other directory, a bundle without
    that plist, key or file, and a file the host may not execute.

    Nothing else is inspected. gda classifies no export platform and models no
    artifact format (ADR-0042 rejected both); whether the resolved file is a Godot
    build at all is what the RUN shows, not what this decides. The bundle rule is
    not gated on the host platform either, for the same reason: it reads a layout
    the artifact declares, and gating it would be a platform classification of the
    kind this command does not make.

    A confirmed absent path is ``export_artifact_not_found``. A path the host
    cannot inspect is ``export_artifact_not_runnable``: its absence has not been
    established, and no runnable executable can be resolved from it.
    """
    path = Path(artifact)
    try:
        mode = os.stat(path).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return export_artifact_not_found_failure(artifact)
    except (OSError, ValueError) as error:
        return export_artifact_not_runnable_failure(
            artifact, f"it could not be inspected ({error})"
        )
    if not S_ISDIR(mode):
        if _is_runnable_file(path):
            return path
        return export_artifact_not_runnable_failure(
            artifact, "it is not a regular file this host may execute"
        )
    if path.suffix != _BUNDLE_SUFFIX:
        return export_artifact_not_runnable_failure(
            artifact,
            f"it is a directory and not a macOS {_BUNDLE_SUFFIX} bundle; name the "
            "runnable file inside it",
        )
    plist = path.joinpath(*_BUNDLE_PLIST_REL)
    try:
        with plist.open("rb") as handle:
            declared = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError, ExpatError) as error:
        return export_artifact_not_runnable_failure(
            artifact, f"its {plist.name} could not be read ({error})"
        )
    name = declared.get(_BUNDLE_EXECUTABLE_KEY) if isinstance(declared, dict) else None
    if not isinstance(name, str) or not name:
        return export_artifact_not_runnable_failure(
            artifact, f"its {plist.name} declares no {_BUNDLE_EXECUTABLE_KEY}"
        )
    if not _one_filename(name):
        return export_artifact_not_runnable_failure(
            artifact,
            f"the {_BUNDLE_EXECUTABLE_KEY} it declares ({name!r}) is not one "
            f"filename: it must name a single file directly under "
            f"{'/'.join(_BUNDLE_MACOS_REL)}, so a value carrying a path "
            "separator, '.' or '..', or a NUL is refused",
        )
    executable = path.joinpath(*_BUNDLE_MACOS_REL, name)
    if not _is_runnable_file(executable):
        return export_artifact_not_runnable_failure(
            artifact,
            f"the {_BUNDLE_EXECUTABLE_KEY} it declares ({name}) is not a regular "
            "file this host may execute",
        )
    return executable


class ExportSmokeParams(BaseModel):
    """The operation params of ``gda export smoke`` (ADR-0042).

    ``artifact`` is a filesystem path the CALLER selected — normally the
    ``output_path`` a previous ``export run`` reported. It carries this module's
    own :data:`SmokeArtifactPath` rather than the plain ``NormalizedPath`` the
    other path fields use: a ``~`` prefix expands AND a relative path is made
    absolute against the invocation cwd, identically on the argv and
    ``--params-json`` paths (ADR-0015), and it happens HERE, before the artifact
    is resolved. Unlike ``--output``'s :data:`ExportOutputPath` it has no
    virtual-path exception, because a projectless command has nothing to resolve
    a ``res://`` against: every input is a filesystem path, ``://`` or not. That ordering is the point — ``executable``, both refusal
    messages and the ``smoke_failed`` message all derive from this value, so none
    of them can echo a relative string that a consumer outside the invocation cwd
    cannot locate; that is the same defect #403 fixed for ``export run --output``
    in this file. Absolute, not canonical: ``..`` is not folded and a symlink is
    not resolved, because the artifact stays the path the caller named. There is
    no project param and no ``--project``: the command is projectless (ADR-0042).
    """

    artifact: SmokeArtifactPath = Field(
        description=(
            "The exported artifact to run: a file this host can execute, or a "
            "macOS .app bundle, whose Contents/Info.plist CFBundleExecutable file "
            "is run. A relative path resolves against the current working "
            "directory. Normally the output_path a previous 'gda export run' "
            "reported."
        )
    )
    args: list[str] = Field(
        default_factory=list,
        description=(
            "Arguments to hand the game, in order, after Godot's '--' separator — "
            "the values it reads back with OS.get_cmdline_user_args(). Repeat "
            "--arg per value on the command line; they are never interpreted by "
            "gda or by the engine."
        ),
    )
    quit_after: int = Field(
        default=0,
        ge=0,
        description=(
            "Ask the engine to end its main loop normally after this many process "
            "frames, so engine cleanup and its exit-time diagnostics run (Godot's "
            "own --quit-after, placed before '--'). 0 — the default — adds no "
            "engine flag and the game ends only by itself or at the timeout. This "
            "is NOT a completion assertion: it says nothing about whether the "
            "game's own work finished."
        ),
    )
    timeout: float = Field(
        default=DEFAULT_SMOKE_TIMEOUT_SECONDS,
        gt=0,
        allow_inf_nan=False,
        description=(
            "How many seconds to let the run take before gda ends it and reports "
            "'launch_timeout' with the output captured so far. Must be a FINITE "
            "positive number: JSON Schema cannot express finiteness, so a "
            "non-finite value is refused by validation rather than by the schema "
            f"below. Defaults to {DEFAULT_SMOKE_TIMEOUT_SECONDS}s, the same "
            "completed-run ceiling 'script run' uses. It is a HARD external bound, "
            "not a normal shutdown: a run it ends claims nothing about the "
            "diagnostics Godot emits only while shutting down cleanly."
        ),
    )
    strict: bool = Field(
        default=False,
        description=(
            "Treat a failed run as a gda failure: emit the error envelope with "
            "code 'smoke_failed' and exit 4, instead of the default passthrough "
            "success. TWO triggers, either one enough: the game exited non-zero, "
            "or the engine reported leaked objects or resources at exit (a "
            "'shutdown_leak' diagnostic), which a status-only gate cannot see "
            "because a game can choose 0 and still leave objects alive. Opt-in, "
            "for shell '&&' chains and CI gates that key on the process exit code. "
            "The envelope keeps the evidence, typed and as prose: "
            "'evidence.exit_status' is the CHILD's status (gda's own exit code "
            "stays 4) and 'evidence.script_errors' the parsed errors, while the "
            "'diagnostics' string carries BOTH of the run's streams under the "
            "fixed labels '--- artifact stdout ---' and '--- artifact stderr ---'."
        ),
    )


class ExportSmokeResult(CompletedRunResult):
    """The result of ``gda export smoke``: the exported game's own run (ADR-0042).

    The second public promotion of the internal `Raw run`
    (:class:`gda.runner.RunResult`), sharing its completed-run half with ``script
    run`` through :class:`gda.completed_run.CompletedRunResult`: the child's
    ``exit_status``, its stdout bounded at the shared cap with the spill metadata
    that bounds it, its ``stderr``, and the recognized ``diagnostics``. gda does
    not interpret the game's semantics, so a non-zero ``exit_status`` is data the
    agent reads, not a gda failure, unless ``--strict`` was passed — read
    ``exit_status``, do not assume ``success == zero``.

    What this result adds is only the two addresses: the ``artifact`` the caller
    selected and the ``executable`` gda resolved inside it. It publishes no
    placement — the private ``user://`` root is an internal safety mechanism that
    the command removes on the way out, so naming it would hand a caller a
    directory that no longer exists — and no digest, PCK listing, artifact-content
    inventory, provenance or receipt: ADR-0042 excluded every one of them, and gda
    makes no claim about the artifact's identity or contents.
    """

    artifact: str = Field(
        description=(
            "The artifact this run was asked for, as an absolute path — the "
            "caller's own path with '~' expanded and a relative path resolved "
            "against the invocation cwd. It is what 'executable' and every "
            "failure message are derived from."
        )
    )
    executable: str = Field(
        description=(
            "The executable gda actually launched: the artifact itself when it is "
            "a runnable file, or the Contents/MacOS file a macOS .app bundle's "
            "CFBundleExecutable names."
        )
    )
    exit_status: int = Field(
        description=(
            "The exported game's own process exit code, passed through verbatim — "
            "non-zero is still a SUCCESS result, not a gda failure, unless "
            "--strict was passed (ADR-0042)."
        )
    )
    stdout: str = Field(
        description=(
            "The game's standard output — verbatim up to the "
            f"{STDOUT_CAP // 1024} KiB cap: above it, this is the stream's "
            "leading cap bytes (cut on a UTF-8 boundary) and the COMPLETE stream "
            "is at 'stdout_file'. Read 'stdout_truncated' before treating this as "
            "the whole stream."
        )
    )
    stderr: str = Field(description="The game's standard error, captured verbatim.")
    stdout_bytes: int = Field(
        ge=0,
        description=(
            "The game's COMPLETE standard-output length in UTF-8 bytes — the full "
            "stream's size whether or not 'stdout' was truncated. Always present."
        ),
    )
    stdout_truncated: bool = Field(
        description=(
            "Whether 'stdout' is the truncated head of a stream above the "
            f"{STDOUT_CAP // 1024} KiB cap. False means 'stdout' IS the whole "
            "stream. Always present."
        ),
    )
    stdout_file: str | None = Field(
        description=(
            "The file holding the game's COMPLETE standard output when 'stdout' "
            "was truncated; null when it was not. Always present "
            "(required-but-nullable)."
        ),
    )
    diagnostics: list[ScriptError] = Field(
        default_factory=list,
        description=(
            "Recognized engine and script errors parsed out of the run's stderr, "
            "in emission order; empty when the run reported none. A "
            "'shutdown_leak' entry is the engine's exit-time report that the "
            "PROCESS left objects or resources alive — the one --strict fails on "
            "beside a non-zero status. Advisory and best-effort — the verbatim "
            "stream stays in 'stderr'."
        ),
    )


def render_export_smoke(ran: "ExportSmokeResult") -> str:
    """Render a smoked artifact: what ran, its exit status, then its captured output.

    The lead names the executable before the status, because the caller gave an
    artifact and gda chose what inside it to launch; everything after it is the
    shared completed-run tail (:func:`gda.completed_run.render_completed_run`),
    the same one ``script run`` shows.
    """
    return render_completed_run(
        ran,
        lead=[f"executable: {ran.executable}", f"exit_status: {ran.exit_status}"],
    )


def smoke_args(user_args: list[str], quit_after: int) -> list[str]:
    """This channel's argv TAIL: ``[(--quit-after N), --, *user_args]`` (ADR-0042).

    ``--quit-after`` is an ENGINE option, so it goes before Godot's ``--``
    separator; the probe behind ADR-0042 measured what happens otherwise — the
    same words after ``--`` became user arguments and the game did not exit. A
    zero or omitted value adds no flag at all, which is the engine's own default.
    The separator is always emitted, so a user argument that looks like an engine
    flag is never read as one.
    """
    args = ["--quit-after", str(quit_after)] if quit_after > 0 else []
    return [*args, "--", *user_args]


def run_export_smoke_operation(
    *,
    artifact: str,
    args: list[str],
    quit_after: int = 0,
    timeout: float = DEFAULT_SMOKE_TIMEOUT_SECONDS,
    strict: bool = False,
    make_launch: "LaunchFn | None" = None,
) -> "ExportSmokeResult | Failure":
    """Run ``export smoke``'s resolve → launch → classify recipe (ADR-0042).

    Returns its outcome instead of emitting or exiting, like every other recipe:
    the passthrough :class:`ExportSmokeResult` on a completed run (even a non-zero
    ``exit_status``), or a :class:`~gda.errors.Failure` — the two pre-launch
    artifact refusals, a ``classify_launch_or_crash`` env/crash outcome (a timeout
    included, with the partial capture preserved), a ``stdout_spill_failed`` for a
    stream gda could not bound, or — with ``strict`` — ``smoke_failed``.

    ``make_launch`` is the injected headless-launch seam; ``None`` (the default)
    uses the real deep module :func:`gda.runner.launch`, resolved at call time so
    a test can inject a fake OR patch ``gda.commands.export.launch``.

    **The private ``user://``.** A caller-selected exported game is not the
    resolved `Trusted project`, and gda will not let it write the host's real user
    directory by accident. The existing global ``--user-data-root`` /
    ``$GDA_USER_DATA_ROOT`` is honored where the caller named one — it is theirs,
    and this command neither replaces nor removes it. Where the caller named none,
    this creates a fresh private root AFTER the artifact resolves and BEFORE the
    launch, hands it to the primitive through the explicit placement input, and
    removes it in ``finally`` on every outcome that created it. That cleanup is
    best-effort internal hygiene: a root that will not delete never replaces the
    outcome and adds no result field, error code or evidence.
    """
    run_launch = make_launch or launch
    resolved = resolve_artifact_executable(artifact)
    if isinstance(resolved, Failure):
        return resolved
    try:
        configured = resolve_user_data_root()
    except ValueError:
        # An explicit but EMPTY --user-data-root. The caller named a root, badly;
        # supplying a private one instead would silently accept a mistaken flag, so
        # hand the primitive nothing and let its shared refusal stand.
        configured = None
        owned = None
    else:
        try:
            owned = (
                None
                if configured is not None
                else Path(tempfile.mkdtemp(prefix="gda-smoke-user-"))
            )
        except OSError as error:
            # The same unusable-placement outcome the primitive reports when IT
            # cannot make a private directory, under the same registered code —
            # reported before any spawn rather than as a traceback.
            return make_failure(
                "user_data_unwritable",
                "a private user:// root for this run could not be created "
                f"({error}); the launch was refused. Point TMPDIR at a writable "
                "directory, or pass --user-data-root <writable dir>",
                "",
            )
    try:
        raw = run_launch(
            resolved,
            smoke_args(args, quit_after),
            cwd=None,
            timeout=timeout,
            timeout_label=SMOKE_TIMEOUT_LABEL,
            user_data_root=owned,
        )
        # The shared env/crash prefix, exactly as the export and import channels
        # use it: a binary that could not be launched, a refused placement, the
        # timeout (whose envelope keeps the partial capture, the clock and the
        # ceiling this label names), or a signal death. Everything else — a clean
        # engine exit, INCLUDING a non-zero status — is a passthrough.
        crash = classify_launch_or_crash(raw, resolved)
        if crash is not None:
            return crash
        diagnostics = parse_script_errors(raw.stderr)
        # The game RAN. Its own status is data by default and a gda failure only
        # when the caller opted in with --strict, which fails on EITHER of two
        # triggers: a status-only gate cannot see a game that printed its results,
        # chose 0, and still left objects alive (GDA-DF-072).
        if strict and (raw.exit_code != 0 or leaked_at_exit(diagnostics) is not None):
            return smoke_exit_status_failure(
                str(resolved),
                raw.exit_code,
                raw.stdout,
                raw.stderr,
                diagnostics,
            )
        bounded = bounded_stdout(
            raw.stdout,
            raw.exit_code,
            subject="exported artifact",
            prefix="gda-smoke-stdout-",
        )
        if isinstance(bounded, Failure):
            return bounded
        stdout, full_bytes, truncated, spill = bounded
        return ExportSmokeResult(
            # Already absolute: the params model made it so BEFORE resolution, and
            # `resolved` derives from that same value (#403).
            artifact=artifact,
            executable=str(resolved),
            exit_status=raw.exit_code,
            stdout=stdout,
            stderr=raw.stderr,
            stdout_bytes=full_bytes,
            stdout_truncated=truncated,
            stdout_file=spill,
            diagnostics=diagnostics,
        )
    finally:
        if owned is not None:
            # Best-effort by contract (ADR-0042): the outcome above is already
            # decided, and a root that will not delete must not replace it.
            shutil.rmtree(owned, ignore_errors=True)


def _export_smoke_recipe(params, *, project, godot):
    # ``project`` is always None here and ``godot`` unused: the descriptor sets
    # ``inherits_project=False`` and the signature declares neither option, so the
    # dispatch tail resolves no project (an inherited invalid $GDA_PROJECT cannot
    # make this command fail) and the engine this runs is the artifact's own.
    return run_export_smoke_operation(
        artifact=params.artifact,
        args=params.args,
        quit_after=params.quit_after,
        timeout=params.timeout,
        strict=params.strict,
    )


# ``export smoke`` carries the sixth execution kind, ``ARTIFACT_SMOKE``: like
# ``SCRIPT_RUN`` and ``IMPORT`` it is self-description only (ADR-0004 / ADR-0012)
# — dispatch is by ``recipe`` (ADR-0023) and no runner-selection branch reads it —
# but the published kind must not claim the ``operations.gd`` sentinel pipeline
# this command never uses, nor ``script run``'s project-scoped shape.
EXPORT_SMOKE_COMMAND: HeadlessCommand[ExportSmokeResult] = HeadlessCommand(
    operation="export-smoke",
    input_model=ExportSmokeParams,
    output_model=ExportSmokeResult,
    kind=ExecutionKind.ARTIFACT_SMOKE,
    render=render_export_smoke,
    recipe=_export_smoke_recipe,
    # Projectless (ADR-0042): the artifact is a caller-selected path, and gda has
    # no fact tying it to a resolved project, so neither $GDA_PROJECT nor the cwd
    # is read as project context.
    inherits_project=False,
)


# The export command group (issue #114): read-only discovery of the project's
# export presets (from export_presets.cfg) and export-template readiness. Those
# two stay headless — they parse a config file and check the filesystem, never
# running an actual export; `export run` (issue #121) is the one that does,
# through the operation above.
_app = typer.Typer(
    help="Discover export presets and export-template status.", no_args_is_help=True
)


@_app.command(name="list", cls=EXPORT_LIST_COMMAND.command_class())
def list_presets(
    json_output: bool = json_option(),
    schema: bool = EXPORT_LIST_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Enumerate the resolved project's export presets (name, platform, runnable)."""
    dispatch_domain(
        EXPORT_LIST_COMMAND,
        ExportListParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="get", cls=EXPORT_GET_COMMAND.command_class())
def get_preset(
    preset: str = typer.Option(
        ...,
        "--preset",
        help="The export preset's display name, as 'gda export list' reports it.",
    ),
    json_output: bool = json_option(),
    schema: bool = EXPORT_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Report one preset's details plus export-template install status.

    ``templates_root`` names the export-templates directory that was checked.
    Godot reads the templates from its data directory and ``--user-data-root``
    relocates that, so a redirected run can report none installed on a host
    that has them; ``templates_root_host`` names the host's directory in
    exactly that case.
    """
    dispatch_domain(
        EXPORT_GET_COMMAND,
        ExportGetParams(preset=preset),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="run", cls=EXPORT_RUN_COMMAND.command_class())
def run_export(
    preset: str = typer.Option(
        ...,
        "--preset",
        help="The export preset's display name, as 'gda export list' reports it.",
    ),
    # --mode (#170): select the export flavor. A closed Enum so an unrecognized
    # value is a Typer usage error (exit 2) rather than reaching the runner;
    # release is the default, preserving #121's behavior when --mode is omitted.
    mode: ExportRunMode = typer.Option(
        ExportRunMode.RELEASE,
        "--mode",
        help="The export flavor to run (release/debug/pack); default release.",
    ),
    # --output (#170/#403): override the preset's configured export_path. A
    # filesystem path is normalized ONCE at the params-model layer: ~ expands and
    # relative paths resolve against the invoker's cwd before the native export
    # runner changes cwd to the project.
    output: Optional[str] = typer.Option(
        None,
        "--output",
        help=(
            "Override the preset's configured export_path; relative filesystem "
            "paths resolve against the invoker's current working directory."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = EXPORT_RUN_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Export a named preset to a destination and report the artifact.

    Unlike every other command, the export itself is a native ``--export-<mode>``
    invocation (the export subsystem is editor-only, so it cannot run through
    operations.gd). The recipe — ``export get`` resolves the preset's platform +
    configured ``export_path`` + template readiness (reusing #114's clean
    preset/project errors), a structured preflight fails fast when templates are
    missing or there is no destination, then the native ``ExportRunner`` performs
    the export and ``classify_export_run`` synthesizes the typed result from the
    subprocess's exit code — is owned by :func:`gda.commands.export.run_export_operation`
    (issue #187), so this command is the same thin shape as every other: build
    params → invoke the operation → emit.

    ``--mode`` selects the export flavor (release/debug/pack; default release).
    ``--output`` overrides the preset's configured ``export_path`` and resolves a
    relative filesystem path against the invoker's current working directory;
    preset ``export_path`` values keep Godot's project-relative convention. The
    reported ``output_path`` is the resolved artifact path, and missing output
    parent directories are created and reported in ``created_dirs`` (#402/#403).

    Export-template discovery follows ``--user-data-root``: Godot reads the
    templates from the data directory that option relocates, so a release or
    debug run under it finds none installed unless you put templates there.
    The failure then names both directories and the remedies; ``--mode pack``
    needs no export templates at all.

    The result also reports what the export did to the PROJECT
    (``project_tree_mutations``, #839). The native export runs the editor import
    pass, so an export against a cold cache creates the whole engine cache
    directory — the one the result names as ``cache_root`` — plus the ``.import``
    and ``.uid`` sidecars beside the sources, and a stale asset makes it rewrite
    the generated resources it owns. ``created`` carries every file the export
    added anywhere under the project, each classified ``cache_owned`` or
    ``source_adjacent`` against that root, so the cache half can be cleaned as one
    unit; directory links are walked as the engine reads them, once each.
    ``modified`` carries the pre-existing files OUTSIDE that root whose
    CONTENT changed, and only a file whose size or timestamp moved is compared;
    rewrites INSIDE the root are not reported at all, so an empty ``modified``
    says nothing about the cache. The artifact and everything under it stay out of
    both lists, and so does a top-level ``.git``; a file the export writes BESIDE
    the artifact is reported like any other created file.
    ``skipped`` counts what neither walk could account for — an entry that
    is not a regular file (a FIFO, a socket, a device), or one that could not be
    read, including a directory whose whole subtree is then uncovered — a count,
    not a path list, so repair the tree and run again for a complete record. The
    report is the difference between gda's walk before the export and its walk
    after; gda assumes it is the project's sole driver during the export
    (ADR-0018), so a change another writer makes in that interval is attributed to
    the export. The report is disclosure: gda deletes and restores nothing. A
    FAILED export carries no report; the failure answers through the error
    envelope instead.
    """
    # Build the params model from the argv options (the single source of truth,
    # ADR-0015): ExportRunParams.output is an ExportOutputPath, so argv and
    # --params-json normalize identically. Dispatch through the descriptor's
    # recipe (ADR-0023), exactly like every other recipe command.
    dispatch_recipe(
        EXPORT_RUN_COMMAND,
        ExportRunParams(preset=preset, mode=mode, output=output),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="smoke", cls=EXPORT_SMOKE_COMMAND.command_class())
def smoke_artifact(
    artifact: str = typer.Argument(
        ...,
        help=(
            "The exported artifact to run: a file this host can execute, or a "
            "macOS .app bundle (its Contents/Info.plist CFBundleExecutable file "
            "is run). A relative path resolves against the current working "
            "directory."
        ),
    ),
    args: list[str] = typer.Option(
        [],
        "--arg",
        help=(
            "An argument to hand the game, after Godot's '--' separator "
            "(repeatable; order is kept). The game reads them with "
            "OS.get_cmdline_user_args(); gda interprets none of them."
        ),
    ),
    quit_after: int = typer.Option(
        0,
        "--quit-after",
        help=(
            "Ask the engine to end its main loop normally after this many process "
            "frames (Godot's own --quit-after, placed before '--'), so engine "
            "cleanup and its exit-time diagnostics run. 0 (the default) adds no "
            "flag. It asserts NO project completion."
        ),
    ),
    timeout: float = typer.Option(
        DEFAULT_SMOKE_TIMEOUT_SECONDS,
        "--timeout",
        help=(
            "Seconds to let the run take before gda ends it and reports "
            "'launch_timeout' with the output captured so far, the elapsed time "
            "and the ceiling it reached. Default "
            f"{DEFAULT_SMOKE_TIMEOUT_SECONDS}s, the same ceiling 'script run' "
            "uses. A hard external bound, not a normal shutdown."
        ),
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Fail when the game exits non-zero, OR when the engine reports leaked "
            "objects or resources at exit (a 'shutdown_leak' diagnostic — a game "
            "can exit 0 and still leave objects alive): emit the 'smoke_failed' "
            "error envelope and exit 4 instead of the default passthrough "
            "success. For shell '&&' chains and CI gates. The envelope carries "
            "the child's status as 'evidence.exit_status' and the parsed errors "
            "as 'evidence.script_errors'; its diagnostics carry both streams, "
            "labelled '--- artifact stdout ---' / '--- artifact stderr ---'."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = EXPORT_SMOKE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
) -> None:
    """Run an exported artifact headless and pass its completed process through.

    ``export run`` says whether Godot BUILT the artifact; this runs it. The
    exported game loads its own project data, so a defect that only appears at
    startup or at shutdown — a leaked resource reported at exit, a missing
    dependency, a script error on the first frame — is visible here and nowhere
    in an export result (ADR-0042).

    Feed it the ``output_path`` a previous ``gda export run`` reported, or any
    other path you choose. A file this host can execute runs as given; a macOS
    ``.app`` bundle resolves to the ``Contents/MacOS`` file its
    ``Contents/Info.plist`` names in ``CFBundleExecutable``. An absent path is
    ``export_artifact_not_found``; anything else that resolves to no runnable file
    — another directory, a bundle missing that plist, key or file, a file without
    execute permission — is ``export_artifact_not_runnable``. gda inspects nothing
    else: it classifies no export platform, and whether the file is a Godot build
    is what the run shows.

    Bounded support: a macOS ``.app`` and a directly host-runnable file, with
    end-to-end evidence on macOS only. Linux and Windows behaviour is not measured
    and not promised.

    The command is PROJECTLESS: it takes no ``--project``, and neither
    ``$GDA_PROJECT`` nor the current directory is read as project context. A
    relative artifact path resolves against the current directory, so the absolute
    ``output_path`` from ``export run`` passes straight through.

    ``--arg`` values reach the game in order, after Godot's ``--`` separator,
    where it reads them with ``OS.get_cmdline_user_args()``. ``--quit-after N``
    asks the engine to end its main loop normally after N process frames so engine
    cleanup and its exit-time diagnostics run; it asserts nothing about the game's
    own work finishing. ``--timeout`` stays the external hard bound: a run gda
    ends reports ``launch_timeout`` with the partial capture and claims nothing
    about diagnostics Godot emits only during a normal shutdown.

    The result is the completed run: ``exit_status``, ``stdout`` verbatim up to a
    64 KiB cap (above it the leading cap bytes, with the COMPLETE stream in the
    file named by ``stdout_file``; a spill gda cannot write is the typed
    ``stdout_spill_failed``), ``stderr``, the recognized ``diagnostics``, and the
    two addresses — the ``artifact`` asked for and the ``executable`` that ran.
    A non-zero ``exit_status`` is DATA, not a failure: read it, do not assume
    ``success == zero``. Pass ``--strict`` to invert that one default and get the
    ``smoke_failed`` envelope (exit 4) for a shell ``&&`` chain or a CI gate;
    under it a run fails on either of two triggers — the non-zero status, or a
    ``shutdown_leak`` diagnostic, the engine reporting at exit that the process
    left objects or resources alive, which a status-only gate cannot see.

    The game runs against a PRIVATE ``user://``: gda creates a fresh root for it
    and removes it afterwards, so a smoked artifact cannot touch the host's real
    user directory. Pass the global ``--user-data-root DIR`` — it precedes the
    subcommand — to keep what the game writes; that directory is yours and gda
    does not remove it.
    """
    # The params model is the single authority for the bounds (ADR-0015): the
    # finite positive ceiling and the non-negative frame count are its field
    # constraints, enforced identically for --params-json — this argv body only
    # translates a model refusal into the Click usage error.
    dispatch_recipe(
        EXPORT_SMOKE_COMMAND,
        params_or_bad_parameter(
            ExportSmokeParams,
            artifact=artifact,
            args=list(args),
            quit_after=quit_after,
            timeout=timeout,
            strict=strict,
        ),
        json_output=json_output,
        godot=None,
        project=None,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``export`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="export")
