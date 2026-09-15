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
``export run`` does, and it is the one command that cannot go through
``operations.gd`` — see the operation section below.
"""

import hashlib
import os
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from stat import S_ISREG
from typing import Annotated, Optional

import typer
from pydantic import AfterValidator, BaseModel, Field, model_validator

from gda import dispatch
from gda.binary import resolve_godot_binary
from gda.dispatch import dispatch_domain, dispatch_recipe
from gda.errors import (
    Failure,
    make_failure,
    classify_launch_or_crash,
    export_output_parent_failure,
    export_path_unset_failure,
    export_templates_missing_failure,
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
    classify_created_file,
)
from gda.runner import RunResult, engine_data_path


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
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        return str(expanded)
    return str(Path.cwd() / expanded)


ExportOutputPath = Annotated[str, AfterValidator(normalize_export_output_path)]


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
    and two to four rewritten ``.translation`` resources, reported as
    ``warnings: []``). The report is DISCLOSURE — the export deletes and restores
    nothing — so an agent can review, stage or restore the tree without a manual
    git snapshot.

    What it covers, and what it deliberately leaves out:

    * ``created`` is every file the tree gained, ANYWHERE under the project,
      classified against ``cache_root`` so the cache half can be cleaned as one
      unit.
    * ``modified`` is every pre-existing file OUTSIDE ``cache_root`` whose CONTENT
      changed. A pre-existing file is a CANDIDATE only when its size or timestamp
      moved, so a rewrite that preserves both is not seen. A pre-existing cache
      file stays out altogether: the cache is reported as one unit, a warm export
      rewrites its bookkeeping files on every run, and hashing it beforehand would
      cost far more than the fact is worth (the dogfooding case holds about
      1.1 GiB there). So an unchanged ``modified`` says nothing about the cache.
    * The artifact, the parent directories gda created for it, and everything
      under the output path are out of both lists; so is a top-level ``.git``
      directory, which the engine never writes to.
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
            "ordered by path."
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
            "total bytes."
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


# --- The project-tree mutation report's two walks (#839) ---------------------
#
# `resource import` walks the same tree for the same reason and keeps its own
# walker (#741, open item 9): the SHARED part is the classification — both take it
# from `gda.import_evidence`, which is also where the cache root is spelled — not
# the walk. This one differs where the export differs. It hashes, because a
# rewritten file's earlier bytes exist only before the run; it excludes the
# artifact gda asked the engine to write; and it runs around a native export
# instead of around a sentinel launch.

# Read in chunks so a large asset costs no memory. The digest decides ONE thing —
# whether a file's bytes changed between the two walks — and is never published,
# so blake2b is gda's own choice here rather than a contract with anybody.
_HASH_CHUNK = 1 << 20

# The top-level directory both walks drop, on the same ground `resource import`'s
# walker drops it: the engine never writes there, and hashing an object database
# would dominate the cost of a report about the project's own files. The rule is
# stated twice, once per walk, because #741's open item 9 keeps the two walks
# separate — the shared part is the classification, not the walk.
_VCS_DIR = ".git"


@dataclass(frozen=True)
class _FileFacts:
    """What the pre-export walk records about one file (#839).

    ``digest`` is ``None`` for a file under the cache root — those are never
    hashed, so they can never enter ``modified``; the cache is reported as one
    unit. Everything else is hashed, because ``modified`` means the content
    changed and the earlier content is gone once the export has run.
    """

    size: int
    mtime_ns: int
    digest: str | None


def _digest_file(path: Path) -> str:
    """The content digest the two walks compare (#839)."""
    digest = hashlib.blake2b(digest_size=16)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_facts(path: Path, *, digest: bool) -> "_FileFacts | None":
    """One REGULAR file's facts, or ``None`` when there are none to take (#839).

    A file that vanished between the walk and the read, a dangling symlink, an
    unreadable one: none of them is a reason to fail an export that SUCCEEDED, so
    the caller counts it as skipped and reports nothing about it.

    An entry that is not a regular file takes that same path, and the check comes
    BEFORE the open: a FIFO in the project tree blocks ``open()`` until a writer
    appears, which hung the whole command outside any timeout (PR #981 review
    round 2) — no result, no envelope, no exit. A socket or a device answers with
    an ``OSError`` instead, so the family reached the skipped channel by two
    different routes and one of them was unbounded. The rule is now the same for
    every non-regular entry, whatever its kind: gda never opens it, and the report
    counts it. ``Path.stat()`` follows a symlink, so a link to a regular file is
    still inventoried as one.
    """
    try:
        st = path.stat()
        if not S_ISREG(st.st_mode):
            return None
        content = _digest_file(path) if digest else None
    except OSError:
        return None
    return _FileFacts(size=st.st_size, mtime_ns=st.st_mtime_ns, digest=content)


def _excluded_prefixes(
    project: Path, output_path: str, created_dirs: list[str]
) -> tuple[str, ...]:
    """The project-relative paths neither walk reports (#839).

    The artifact, the parent directories gda created for it (#402), and — a macOS
    export writes an ``.app`` DIRECTORY — everything under them: that is the
    export's own output, not a mutation of the project. A destination outside the
    project is dropped here, since the walk never reaches it; so is a virtual
    (``://``) path, which no walk can resolve.
    """
    prefixes = [_VCS_DIR]
    root = project.resolve()
    for raw in [output_path, *created_dirs]:
        if not raw or "://" in raw:
            continue
        try:
            rel = Path(raw).resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        if rel not in ("", "."):
            prefixes.append(rel)
    return tuple(prefixes)


def _excluded(rel: str, prefixes: tuple[str, ...]) -> bool:
    """Whether ``rel`` is one of ``prefixes`` or sits under one."""
    return any(rel == prefix or rel.startswith(prefix + "/") for prefix in prefixes)


def _walk_project(
    project: Path,
    excluded: tuple[str, ...],
    on_unreadable_dir: "Callable[[str], None] | None" = None,
) -> Iterator[tuple[str, Path]]:
    """Every file under ``project`` as ``(project-relative posix path, path)``.

    The cache root is walked like anything else — its files are what ``created``
    classifies as ``cache_owned`` — while an excluded subtree is PRUNED rather
    than filtered out per file: an ``.app`` bundle holds thousands of files, and
    walking it would spend the report's budget on entries it then drops.

    ``on_unreadable_dir`` receives the project-relative path of a directory the
    walk cannot list. ``os.walk`` swallows that error by default, which would drop
    the whole subtree from the report AND from its skipped count — the one channel
    that says the record is incomplete (PR #981 review). The caller decides what
    to do with the path; this function still yields everything it CAN read,
    because an unreadable corner of the tree is not a reason to fail an export
    that succeeded.
    """

    def note(error: OSError) -> None:
        if on_unreadable_dir is None:
            return
        filename = getattr(error, "filename", None)
        if filename is None:
            return
        try:
            on_unreadable_dir(Path(filename).relative_to(project).as_posix())
        except ValueError:
            return

    for dirpath, dirnames, filenames in os.walk(project, onerror=note):
        base = Path(dirpath)
        rel_dir = base.relative_to(project).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = [
            name for name in dirnames if not _excluded(prefix + name, excluded)
        ]
        for name in filenames:
            rel = prefix + name
            if not _excluded(rel, excluded):
                yield rel, base / name


@dataclass(frozen=True)
class _PreExportInventory:
    """The pre-export walk of the project tree, and its settlement (#839).

    Captured before the export, settled after it: :meth:`settle` walks the tree a
    second time and reports the difference. The two halves live in one object
    because the second walk is meaningless without the first — a file is
    ``created`` only against a recorded tree, and ``modified`` only against a
    recorded digest.
    """

    project: Path
    excluded: tuple[str, ...]
    files: dict[str, _FileFacts]
    unreadable: frozenset[str]
    # The directories the pre-export walk could not list, kept apart from the
    # rest because they are PREFIXES: the settlement must pass over everything
    # beneath one. A file under such a directory existed before the export, so
    # reporting it as created once the directory becomes readable would state a
    # fact the walks never observed (PR #981 review).
    unlistable_dirs: tuple[str, ...]

    @classmethod
    def capture(
        cls, project: Path, *, output_path: str, created_dirs: list[str]
    ) -> "_PreExportInventory":
        """Record the tree as it stands before the native export (#839)."""
        excluded = _excluded_prefixes(project, output_path, created_dirs)
        files: dict[str, _FileFacts] = {}
        unreadable: set[str] = set()
        unlistable: set[str] = set()
        for rel, path in _walk_project(project, excluded, unlistable.add):
            # The shared classifier decides what to hash, asked of a file that
            # already exists: `cache_owned` is "under the cache root", the one
            # thing this walk needs to know about it. Asking it here is what keeps
            # the cache-root rule spelled once (#741) — the export path states no
            # rule of its own, here or in the settlement below.
            facts = _file_facts(
                path, digest=classify_created_file(rel) != "cache_owned"
            )
            if facts is None:
                unreadable.add(rel)
            else:
                files[rel] = facts
        return cls(
            project=project,
            excluded=excluded,
            files=files,
            unreadable=frozenset(unreadable | unlistable),
            unlistable_dirs=tuple(sorted(unlistable)),
        )

    def settle(self) -> ProjectTreeMutations:
        """Walk the tree again and report what the export changed (#839).

        The rules, in the order the loop asks them: a path the pre-export walk
        could not read is accounted for as skipped and nothing more (calling it
        created would be a guess); a path that was not there is ``created`` and
        carries the shared classifier's verdict; a pre-existing cache file is
        passed over, because the cache is reported as one unit; and a pre-existing
        file elsewhere is a CANDIDATE only when its size or mtime moved, and
        enters ``modified`` only when its digest then differs. The candidate rule
        is what bounds the cost — the import pass touches far more files than it
        rewrites — and it is also this report's one blind spot: a rewrite that
        preserves both the size and the timestamp is not seen.

        A directory neither walk could list is counted once, and everything
        beneath it is passed over: the pre-export walk never read those files, so
        the settlement can state nothing about them either way.
        """
        created: list[ExportCreatedFile] = []
        modified: list[ExportModifiedFile] = []
        skipped = set(self.unreadable)
        for rel, path in _walk_project(self.project, self.excluded, skipped.add):
            if rel in skipped or _excluded(rel, self.unlistable_dirs):
                continue
            before = self.files.get(rel)
            if before is None:
                facts = _file_facts(path, digest=False)
                if facts is None:
                    skipped.add(rel)
                    continue
                created.append(
                    ExportCreatedFile(
                        path="res://" + rel,
                        classification=classify_created_file(rel),
                        size=facts.size,
                    )
                )
                continue
            if classify_created_file(rel) == "cache_owned":
                continue
            after = _file_facts(path, digest=False)
            if after is None:
                skipped.add(rel)
                continue
            if (after.size, after.mtime_ns) == (before.size, before.mtime_ns):
                continue
            hashed = _file_facts(path, digest=True)
            if hashed is None or hashed.digest is None:
                skipped.add(rel)
                continue
            if hashed.digest == before.digest:
                continue
            modified.append(
                ExportModifiedFile(
                    path="res://" + rel,
                    size=hashed.size,
                    size_before=before.size,
                )
            )
        created.sort(key=lambda entry: entry.path)
        modified.sort(key=lambda entry: entry.path)
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
            skipped=len(skipped),
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
    inventory: "_PreExportInventory | None" = None,
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
            inventory.settle() if inventory is not None else ProjectTreeMutations()
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
        _PreExportInventory.capture(
            project, output_path=output_path, created_dirs=created_dirs
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
    unit. ``modified`` carries the pre-existing files OUTSIDE that root whose
    CONTENT changed, and only a file whose size or timestamp moved is compared;
    rewrites INSIDE the root are not reported at all, so an empty ``modified``
    says nothing about the cache. The artifact, the directories gda created for
    it, everything under the output path and a top-level ``.git`` stay out of both
    lists. ``skipped`` counts what neither walk could account for — an entry that
    is not a regular file (a FIFO, a socket, a device), or one that could not be
    read, including a directory whose whole subtree is then uncovered — a count,
    not a path list, so repair the tree and run again for a complete record. The report is disclosure: gda
    deletes and restores nothing. A FAILED export carries no report; the failure
    answers through the error envelope instead.
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


def register(root: typer.Typer) -> None:
    """Mount the ``export`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="export")
