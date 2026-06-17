"""The ExportRun operation — ``gda export run``'s resolve → preflight → run recipe.

Unlike every other Phase-1 capability, an export cannot run through
``operations.gd``: the Godot export subsystem is editor-only C++, unreachable
from a ``--headless --script`` SceneTree run, so the export itself is a native
``--export-<mode>`` invocation (ADR-0010, :mod:`gda.export_runner`). ``export
run`` therefore hand-orchestrates a multi-phase recipe rather than the shared
sentinel pipeline:

1. **resolve** the preset via the existing ``export-get`` sentinel op — reusing
   #114's clean preset/project errors;
2. **structured preflight** (effective destination + template readiness,
   ADR-0010) that fails fast — ``export_path_unset`` / ``export_templates_missing``
   — with NO native run;
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

The two ``EXPORT_GET_COMMAND`` / ``EXPORT_RUN_COMMAND`` :class:`HeadlessCommand`
definitions live here, not in ``cli.py``, so the operation can drive ``export
get`` without an ``export_run ↔ cli`` import cycle; ``cli.py`` imports both from
here.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Optional

from gda.binary import resolve_godot_binary
from gda.errors import (
    Failure,
    classify_export_run,
    export_path_unset_failure,
    export_templates_missing_failure,
)
from gda.export_runner import ExportRunner, make_subprocess_export_runner
from gda.headless import HeadlessCommand, RunnerFactory, make_subprocess_runner
from gda.models import (
    ExportGetParams,
    ExportGetResult,
    ExportRunMode,
    ExportRunParams,
    ExportRunResult,
)

# The factory seam for the native export runner — the ``export run``-only twin of
# the sentinel channel's ``RunnerFactory``. Spelled here (not in ``headless``)
# because only the export recipe spawns a native ``--export-<mode>`` process.
ExportRunnerFactory = Callable[[Path, Optional[Path]], ExportRunner]

EXPORT_GET_COMMAND: HeadlessCommand[ExportGetResult] = HeadlessCommand(
    operation="export-get",
    input_model=ExportGetParams,
    output_model=ExportGetResult,
)

# export run is the one command that does NOT route through operations.gd: the
# Godot export subsystem is editor-only C++, unreachable from a --script
# SceneTree run, so the export itself is a native --export-<mode> invocation
# (gda.export_runner). This HeadlessCommand is used only for its --schema /
# --json model plumbing; the recipe is run by run_export_operation below —
# export-get resolves the preset + path, the native ExportRunner exports,
# classify_export_run turns the subprocess outcome into the typed result —
# rather than the shared sentinel pipeline.
EXPORT_RUN_COMMAND: HeadlessCommand[ExportRunResult] = HeadlessCommand(
    operation="export-run",
    input_model=ExportRunParams,
    output_model=ExportRunResult,
)


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

    # Resolve the effective destination: --output (already CLI-normalized) wins
    # over the preset's configured export_path (#170). This is what the native
    # export writes to AND what the result reports as output_path.
    output_path = output_override if output_override is not None else got.export_path

    # Phase 2 (structured preflight, BEFORE any native run; ADR-0010). Two
    # fail-fast checks, both decided from export get's structured fields rather
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
    if not output_path:
        return export_path_unset_failure(got.name)
    if mode is not ExportRunMode.PACK and not got.templates_installed:
        return export_templates_missing_failure(got.name, got.templates_version)

    # Phase 3 (native run + classify): run the native export and classify its raw
    # outcome. The export-get resolved name (got.name) is authoritative throughout
    # — it is what the engine exports and what the result echoes — so the native
    # invocation, not the raw --preset string, is keyed on it.
    binary = resolve_godot_binary(godot)
    export_runner = make_export_runner(binary, project)
    export_output = export_runner.run(got.name, mode.value, output_path)
    return classify_export_run(
        export_output,
        binary,
        preset=got.name,
        platform=got.platform,
        mode=mode,
        output_path=output_path,
    )
