"""One-shot Godot editor runner against an isolated exported PCK."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from gda.parser import build_result, error_envelope
from gda.runner import (
    DEFAULT_TIMEOUT_SECONDS,
    GodotRunner,
    LaunchFn,
    RunResult,
    launch,
    sentinel_args,
)


PackageRunnerFactory = Callable[[Path, Path], GodotRunner]


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
            capability = self.make_launch(
                self.binary,
                ["--help"],
                cwd=cwd,
                timeout=self.timeout,
                timeout_label="Godot package inspector capability probe",
            )
            if capability.exit_code != 0 or capability.launch_failure is not None:
                return capability
            # `--editor` is compiled only under TOOLS_ENABLED. `--script` and
            # `--main-pack` alone are insufficient: path-enabled export templates
            # publish both as X options too.
            if "-e, --editor" not in capability.stdout:
                return RunResult(
                    stdout=build_result(
                        error_envelope(
                            "operation_failed",
                            "package inspection requires a Godot editor binary; "
                            "the configured binary is not an editor build",
                        )
                    ),
                    stderr="",
                    exit_code=1,
                )
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


def make_package_runner(binary: Path, package: Path) -> GodotRunner:
    return PackageGodotRunner(binary, package)
