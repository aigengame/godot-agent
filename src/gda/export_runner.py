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
``{stdout, stderr, exit_code}``. Classification lives in ``gda.errors`` so the
mapping from raw output to typed result / ``GdaError`` is a pure function exercised
without a real engine, exactly like the sentinel pipeline.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gda.exit_codes import EXIT_NOT_FOUND, EXIT_TIMEOUT
from gda.runner import LaunchFailure

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


@dataclass
class ExportRunOutput:
    """The raw result of a native Godot export invocation.

    Mirrors :class:`gda.runner.RunResult` for the export channel: the unparsed
    process output plus a ``launch_failure`` set only when the runner synthesized
    the result (binary missing, timed out) rather than the engine returning one.
    """

    stdout: str
    stderr: str
    exit_code: int
    launch_failure: "LaunchFailure | None" = None


class ExportRunner(Protocol):
    """Spawns a native Godot export and returns its raw output."""

    def run(self, preset: str, mode: str, output_path: str) -> ExportRunOutput: ...


@dataclass
class SubprocessExportRunner:
    """An ExportRunner that spawns ``godot --headless --export-<mode>``.

    Builds ``<godot> --headless --path <project> --export-<mode> "<preset>"
    <output_path>`` and returns the process's raw stdout/stderr/exit code. The
    export subsystem requires an editor (tools) build; a non-tools binary lacks
    these flags entirely and the engine reports it as a usage error, surfaced as a
    generic export failure by the classifier.
    """

    binary: Path
    project: Path | None = None
    timeout: float = DEFAULT_EXPORT_TIMEOUT_SECONDS

    def run(self, preset: str, mode: str, output_path: str) -> ExportRunOutput:
        flag = EXPORT_MODE_FLAGS[mode]
        cmd = [str(self.binary), "--headless"]
        if self.project is not None:
            cmd += ["--path", str(self.project)]
        cmd += [flag, preset, output_path]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired:
            return ExportRunOutput(
                stdout="",
                stderr=f"gda: Godot export timed out after {self.timeout}s\n",
                exit_code=EXIT_TIMEOUT,
                launch_failure=LaunchFailure.TIMEOUT,
            )
        except FileNotFoundError:
            return ExportRunOutput(
                stdout="",
                stderr=f"gda: Godot binary not found: {self.binary}\n",
                exit_code=EXIT_NOT_FOUND,
                launch_failure=LaunchFailure.NOT_FOUND,
            )
        return ExportRunOutput(
            stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode
        )


def make_subprocess_export_runner(
    binary: Path, project: Path | None = None
) -> ExportRunner:
    """Build the default real native-export runner for ``binary`` and ``project``."""
    return SubprocessExportRunner(binary, project=project)
