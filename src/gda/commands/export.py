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

import re
import sys
from collections.abc import Callable
from enum import Enum
from pathlib import Path
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
            f"  hidden by --user-data-root; host templates: {got.templates_root_host}"
        )
    return "\n".join(lines)


def render_export_run(ran: "ExportRunResult") -> str:
    """Render a completed export as ``exported <preset> (<platform>, <mode>) -> <path>``.

    Echoes the artifact that was produced, then one ``warning: …`` line per
    non-fatal engine warning (a clean export prints just the header line).
    """
    header = (
        f"exported {ran.preset} ({ran.platform}, {ran.mode.value}) -> {ran.output_path}"
    )
    if not ran.warnings:
        return header
    return "\n".join([header, *[f"  warning: {w}" for w in ran.warnings]])


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


def classify_export_run(
    output: RunResult,
    binary: Path,
    *,
    preset: str,
    platform: str,
    mode: ExportRunMode,
    output_path: str,
    created_dirs: list[str],
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
