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

# A headless one-shot operation should be quick; this bounds a hung engine so
# the CLI fails loudly instead of blocking forever.
DEFAULT_TIMEOUT_SECONDS = 60.0

# Non-zero exit codes used when the engine never produced its own (shell
# conventions: 124 = timed out, 127 = command not found).
_EXIT_TIMEOUT = 124
_EXIT_NOT_FOUND = 127


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
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def run(self, operation: str, params: dict) -> RunResult:
        # Everything after `--` is delivered to the script verbatim via
        # OS.get_cmdline_user_args(), so the payload is decoupled from however
        # Godot orders its own engine arguments.
        cmd = [
            str(self.binary),
            "--headless",
            "--script",
            str(self.script),
            "--",
            operation,
            json.dumps(params),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                stdout="",
                stderr=f"gda: Godot timed out after {self.timeout}s\n",
                exit_code=_EXIT_TIMEOUT,
            )
        except FileNotFoundError:
            return RunResult(
                stdout="",
                stderr=f"gda: Godot binary not found: {self.binary}\n",
                exit_code=_EXIT_NOT_FOUND,
            )
        return RunResult(
            stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode
        )
