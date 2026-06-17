"""The native-export runner seam for ``gda export run`` (issue #121).

Unlike every other Phase-1 operation, an export cannot run through the bundled
``operations.gd`` payload: Godot's export subsystem (``EditorExportPlatform`` and
friends) is editor-only C++, unreachable from a ``--headless --script`` SceneTree
run. The export is instead a *native* Godot invocation —
``--export-release`` / ``--export-debug`` / ``--export-pack`` — that runs the
editor export pipeline and writes the artifact. It emits no ADR-0002 sentinel, so
``gda`` synthesizes the structured result from the subprocess's exit code and
stderr (see :func:`gda.errors.classify_export_run`).

This module owns only the *seam*: spawn the native export and return its raw
``{stdout, stderr, exit_code}`` as the shared :class:`~gda.runner.RunResult`.
Classification lives in ``gda.errors`` so the mapping from raw output to typed
result / ``GdaError`` is a pure function exercised without a real engine, exactly
like the sentinel pipeline.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gda.runner import RunResult, launch

# An export packs the whole project and may invoke platform toolchains, so it is
# far slower than a one-shot headless op. Give it a generous ceiling distinct
# from the operation runner's tighter bound.
DEFAULT_EXPORT_TIMEOUT_SECONDS = 600.0

# The native flag for each export mode (ADR-0001 maps a mode to the Godot CLI).
# release/debug produce a full platform binary (need templates); pack produces
# project data only (PCK/ZIP by output extension). Issue #121 only ever runs
# "release"; "debug"/"pack" stay mapped here so follow-up #170 can expose --mode
# without reshaping the runner seam.
EXPORT_MODE_FLAGS: dict[str, str] = {
    "release": "--export-release",
    "debug": "--export-debug",
    "pack": "--export-pack",
}


class ExportRunner(Protocol):
    """Spawns a native Godot export and returns its raw output."""

    def run(self, preset: str, mode: str, output_path: str) -> RunResult: ...


@dataclass
class SubprocessExportRunner:
    """An ExportRunner that spawns ``godot --headless --export-<mode>``.

    Builds ``<godot> --headless --path <project> --export-<mode> "<preset>"
    <output_path>`` and returns the process's raw stdout/stderr/exit code. The
    export subsystem requires an editor (tools) build; a non-tools binary lacks
    these flags entirely and the engine reports it as a usage error, surfaced as a
    generic export failure by the classifier.

    The process is spawned with ``cwd = <project>`` when a project is resolved.
    Godot writes the export artifact via ``FileAccess``/``DirAccess`` with NO
    project globalization (verified against the engine source), so a *relative*
    output path — the common case, since a preset's configured ``export_path`` is
    stored project-relative (e.g. ``build/game.x86_64``) — resolves against the
    process CWD. Running from the project root makes that relative path land
    inside the project, exactly as the editor resolves it (issue #121).
    """

    binary: Path
    project: Path | None = None
    timeout: float = DEFAULT_EXPORT_TIMEOUT_SECONDS

    def run(self, preset: str, mode: str, output_path: str) -> RunResult:
        # Build only this channel's argv tail and the export-only cwd (see the
        # class docstring), then delegate the spawn / timeout / OSError /
        # UTF-8-decode handling to the shared launch primitive (#185).
        flag = EXPORT_MODE_FLAGS[mode]
        args: list[str] = []
        if self.project is not None:
            args += ["--path", str(self.project)]
        args += [flag, preset, output_path]
        # Pass the export-specific timeout label: on a timeout the primitive's
        # stderr is carried into GdaError.diagnostics and serialized in
        # `export run --json`, so it is part of the public error envelope and must
        # stay byte-compatible with the pre-#185 "Godot export timed out" wording.
        return launch(
            self.binary,
            args,
            cwd=self.project,
            timeout=self.timeout,
            timeout_label="Godot export",
        )


def make_subprocess_export_runner(
    binary: Path, project: Path | None = None
) -> ExportRunner:
    """Build the default real native-export runner for ``binary`` and ``project``."""
    return SubprocessExportRunner(binary, project=project)
