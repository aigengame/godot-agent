"""The Godot runner seam.

Given an operation name and JSON params, a runner spawns a one-shot
``godot --headless --script`` process and returns its raw
``{stdout, stderr, exit_code}``. The seam is a Protocol so that commands can be
exercised against a fake runner without touching a real engine (ADR-0001).
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# The bundled GDScript operations payload, dispatched by operation name.
OPERATIONS_GD = Path(__file__).parent / "ops" / "operations.gd"


@dataclass
class RunResult:
    """The raw result of a one-shot headless Godot invocation."""

    stdout: str
    stderr: str
    exit_code: int


class GodotRunner(Protocol):
    """Spawns a headless Godot operation and returns its raw output."""

    def run(self, operation: str, params: dict) -> RunResult: ...


@dataclass
class SubprocessGodotRunner:
    """A GodotRunner that spawns a one-shot ``godot --headless --script`` process.

    It dispatches the operation to the bundled ``operations.gd`` payload and
    returns the process's raw stdout/stderr/exit code unparsed — extracting the
    result from the noise is the parser's job (ADR-0002).
    """

    binary: Path
    script: Path = OPERATIONS_GD

    def run(self, operation: str, params: dict) -> RunResult:
        cmd = [
            str(self.binary),
            "--headless",
            "--script",
            str(self.script),
            operation,
            json.dumps(params),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return RunResult(
            stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode
        )
