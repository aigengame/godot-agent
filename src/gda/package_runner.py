"""One-shot Godot editor runner against an isolated exported PCK."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import struct
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

_PCK_V3_HEADER_BYTES = 40
_PCK_V3_FORMAT = 3


def _incomplete_v3_package(package: Path) -> Failure | None:
    """Refuse the V3 header state left before Godot writes a PCK directory."""
    try:
        with package.open("rb") as stream:
            header = stream.read(_PCK_V3_HEADER_BYTES)
    except OSError:
        # Input admission already established a regular file. Preserve the prior
        # engine-owned outcome if that file changes before this narrow read.
        return None
    if len(header) < _PCK_V3_HEADER_BYTES or header[:4] != b"GDPC":
        return None
    format_version = struct.unpack_from("<I", header, 4)[0]
    directory_offset = struct.unpack_from("<Q", header, 32)[0]
    if format_version != _PCK_V3_FORMAT or directory_offset != 0:
        return None
    return make_failure(
        "operation_failed",
        "package inspection refused an incomplete Godot PCK",
        "\n".join(
            (
                f"package: {package}",
                f"format version: {format_version}",
                f"directory offset: {directory_offset}",
                "The V3 header has no file-directory offset. This matches a partial "
                "artifact left by a failed export; rebuild the package and inspect "
                "only output from a successful export.",
            )
        ),
    )


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
    incomplete = _incomplete_v3_package(package)
    if incomplete is not None:
        return incomplete
    return PackageGodotRunner(binary, package, make_launch=make_launch)
