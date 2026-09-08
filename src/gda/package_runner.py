"""One-shot Godot editor runner against an isolated exported PCK."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from gda.errors import Failure, classify_launch_or_crash, make_failure
from gda.runner import (
    DEFAULT_TIMEOUT_SECONDS,
    GodotRunner,
    LaunchFn,
    RunResult,
    launch,
    sentinel_args,
)


PackageRunnerFactory = Callable[[Path, Path], GodotRunner | Failure]


@dataclass
class PackageGodotRunner:
    """Run a bundled sentinel payload with the PCK as the only res:// authority."""

    binary: Path
    package: Path
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    make_launch: LaunchFn = launch

    def run(self, operation: str, params: dict) -> RunResult:
        with TemporaryDirectory(prefix="gda-package-inspect-") as directory:
            cwd = Path(directory)
            return self.make_launch(
                self.binary,
                [
                    "--main-pack",
                    str(self.package),
                    *sentinel_args(operation, params, project=None),
                ],
                cwd=cwd,
                timeout=self.timeout,
                timeout_label="Godot package inspection",
            )


def make_package_runner(
    binary: Path,
    package: Path,
    *,
    make_launch: LaunchFn = launch,
) -> GodotRunner | Failure:
    """Admit a desktop editor before any package payload can be launched."""
    with TemporaryDirectory(prefix="gda-package-capability-") as directory:
        capability = make_launch(
            binary,
            ["--help"],
            cwd=Path(directory),
            timeout=DEFAULT_TIMEOUT_SECONDS,
            timeout_label="Godot package inspector capability probe",
        )
    failed = classify_launch_or_crash(capability, binary)
    if failed is not None:
        return failed
    diagnostics = "\n".join(
        part for part in (capability.stdout.strip(), capability.stderr.strip()) if part
    )
    if capability.exit_code != 0:
        return make_failure(
            "operation_failed",
            "Godot package inspector capability probe failed",
            diagnostics,
        )
    # `--editor` is compiled only under TOOLS_ENABLED. Mentions of `--script`
    # or `--main-pack` alone do not prove the editor APIs this operation reports.
    if "-e, --editor" not in capability.stdout:
        return make_failure(
            "operation_failed",
            "package inspection requires a Godot desktop editor binary; "
            "the configured binary is not an editor build",
            diagnostics,
        )
    return PackageGodotRunner(binary, package, make_launch=make_launch)
