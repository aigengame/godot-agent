"""The ExportRun operation — ``gda export run``'s resolve → preflight → run recipe.

Unlike every other Phase-1 capability, an export cannot run through
``operations.gd``: the Godot export subsystem is editor-only C++, unreachable
from a ``--headless --script`` SceneTree run, so the export itself is a native
``--export-<mode>`` invocation (ADR-0010, :mod:`gda.export_runner`). ``export
run`` therefore hand-orchestrates a multi-phase recipe rather than the shared
sentinel pipeline:

1. **resolve** the preset via the existing ``export-get`` sentinel op — reusing
   #114's clean preset/project errors;
2. **structured preflight** (effective destination + template readiness + output
   parent dirs, ADR-0010) that fails fast — ``export_path_unset`` /
   ``export_templates_missing`` / ``invalid_path`` — with NO native run;
3. the native ``--export-<mode>`` run, whose raw outcome
   :func:`gda.errors.classify_export_run` turns into the typed result.

This module is the recipe's home. :func:`run_export_operation` RETURNS its
outcome (``ExportRunResult | Failure``) instead of emitting the public result or
exiting — so the CLI command (``gda.cli.run_export``) shrinks to the same thin
shape as every other command and the recipe gets its own engine-free test
surface (driven with the two injected seams; see
``tests/test_export_run_operation.py``). It is not side-effect-free: phase 1's
``HeadlessCommand.execute`` still forwards the ``export-get`` engine stderr to
this process's stderr as advisory diagnostics; only the public result/error
envelope and the process exit are deferred to the CLI caller.

``EXPORT_GET_COMMAND`` lives here — a plain sentinel command this operation drives
directly (``export get`` resolves the preset), so co-locating it avoids an
``export_run ↔ cli`` import cycle. ``EXPORT_RUN_COMMAND`` does NOT: its recipe needs
the CLI runner seams, so it is registered in ``gda.cli`` (the dispatch composition
root) beside that recipe, where it is the command's single fully-bound descriptor
(ADR-0023).
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from gda.binary import resolve_godot_binary
from gda.errors import (
    Failure,
    classify_export_run,
    export_output_parent_failure,
    export_path_unset_failure,
    export_templates_missing_failure,
)
from gda.export_runner import ExportRunner, make_subprocess_export_runner
from gda.harness.install import HARNESS_FILE, HARNESS_RES_DIR, uninstall_harness
from gda.headless import HeadlessCommand, RunnerFactory, make_subprocess_runner
from gda.models import (
    ExportGetParams,
    ExportGetResult,
    ExportRunMode,
    ExportRunResult,
)
from gda.render import render_export_get

# The factory seam for the native export runner — the ``export run``-only twin of
# the sentinel channel's ``RunnerFactory``. Spelled here (not in ``headless``)
# because only the export recipe spawns a native ``--export-<mode>`` process.
ExportRunnerFactory = Callable[[Path, Optional[Path]], ExportRunner]


@dataclass(frozen=True)
class _HarnessSnapshot:
    """The EXACT pre-export state of the two files the export strip touches.

    Restoring from this snapshot leaves the dev project byte-identical (ADR-0028's
    "untouched" guarantee) — unlike a fresh ``install_harness``, which would
    canonicalize a noncanonical autoload, rewrite a stale harness body to the
    current version, or ADD a ``GdaHarness`` autoload for a stray harness file that
    had none. Captured before the strip; replayed in the ``finally`` after the
    native export.
    """

    project_godot: Path
    project_godot_bytes: Optional[bytes]
    harness_file: Path
    harness_file_bytes: Optional[bytes]

    @classmethod
    def capture(cls, project: Path) -> "_HarnessSnapshot":
        project_godot = project / "project.godot"
        harness_file = project / HARNESS_RES_DIR / HARNESS_FILE
        return cls(
            project_godot,
            project_godot.read_bytes() if project_godot.exists() else None,
            harness_file,
            harness_file.read_bytes() if harness_file.exists() else None,
        )

    def restore(self) -> None:
        """Put both files back to their captured bytes, writing only when changed.

        A file absent at capture is left absent (the strip removed it); otherwise its
        exact bytes are rewritten, but only if the current on-disk state differs — so
        the common no-harness export touches nothing (no spurious ``project.godot``
        mtime bump against a concurrent editor, ADR-0018).
        """
        for path, before in (
            (self.project_godot, self.project_godot_bytes),
            (self.harness_file, self.harness_file_bytes),
        ):
            if before is None:
                path.unlink(missing_ok=True)
            elif not path.exists() or path.read_bytes() != before:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(before)


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
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        return str(expanded)
    base = Path.cwd() if project is None else project
    if not base.is_absolute():
        base = Path.cwd() / base
    return str(base / expanded)


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
    this process's stderr as advisory diagnostics; only the public result/error
    envelope and the exit are deferred to the caller. ``output_override`` is the
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
    #    uncreatable parent is a structured invalid_path.
    if not output_path:
        return export_path_unset_failure(got.name)
    if mode is not ExportRunMode.PACK and not got.templates_installed:
        return export_templates_missing_failure(got.name, got.templates_version)
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
    snapshot = _HarnessSnapshot.capture(project) if project is not None else None
    if project is not None:
        uninstall_harness(project)
    try:
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
