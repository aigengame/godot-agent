"""The Godot runner seam.

Given an operation name and JSON params, a runner spawns a one-shot
``godot --headless --script`` process and returns its raw
``{stdout, stderr, exit_code}``. The seam is a Protocol so that commands can be
exercised against a fake runner without touching a real engine (ADR-0001).
"""

import enum
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# The codes the runner synthesizes when it never got a result from the engine.
# Defined once in gda.exit_codes (the full exit-code ABI); imported here because
# the runner is what produces them (issue #3).
from gda.exit_codes import EXIT_NOT_FOUND, EXIT_TIMEOUT

# The bundled GDScript operations payload, dispatched by operation name.
OPERATIONS_GD = Path(__file__).parent / "ops" / "operations.gd"

# A headless one-shot operation should be quick; this bounds a hung engine so
# the CLI fails loudly instead of blocking forever.
DEFAULT_TIMEOUT_SECONDS = 60.0


class LaunchFailure(enum.Enum):
    """Why the runner never obtained a result from the engine (issue #15).

    Set *only* by the runner when it synthesizes a result without the engine
    returning one, so classification keys environment failures on this typed
    reason rather than on shell-convention exit codes that a real engine or
    wrapper can itself genuinely return.
    """

    NOT_FOUND = "not_found"  # the binary could not be launched
    TIMEOUT = "timeout"  # launched, but did not return before the runner timeout


@dataclass
class RunResult:
    """The raw result of a one-shot headless Godot invocation."""

    stdout: str
    stderr: str
    exit_code: int
    # Set only when the runner synthesized this result (binary missing, timed
    # out) instead of the engine returning one; ``None`` means the exit_code is
    # the engine's own (issue #15).
    launch_failure: "LaunchFailure | None" = None


class GodotRunner(Protocol):
    """Spawns a headless Godot operation and returns its raw output."""

    def run(self, operation: str, params: dict) -> RunResult: ...


@dataclass
class SubprocessGodotRunner:
    """A GodotRunner that spawns a one-shot ``godot --headless --script`` process.

    It dispatches the operation to the bundled ``operations.gd`` payload and
    returns the process's raw stdout/stderr/exit code unparsed — extracting the
    result from the noise is the parser's job (ADR-0002). When ``project`` is
    set it is passed as ``--path`` so the engine runs against that project and
    ``res://`` resolves there (issue #32); otherwise the engine runs projectless.
    """

    binary: Path
    project: Path | None = None
    script: Path = OPERATIONS_GD
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def run(self, operation: str, params: dict) -> RunResult:
        # Everything after `--` is delivered to the script verbatim via
        # OS.get_cmdline_user_args(), so the payload is decoupled from however
        # Godot orders its own engine arguments.
        cmd = [str(self.binary), "--headless"]
        if self.project is not None:
            cmd += ["--path", str(self.project)]
        cmd += [
            "--script",
            str(self.script),
            "--",
            operation,
            json.dumps(params),
        ]
        try:
            # Capture raw bytes (no ``text=True``): Godot's ``JSON.stringify``
            # emits UTF-8, but ``text=True`` would decode with the host locale,
            # which mojibakes or raises ``UnicodeDecodeError`` on a non-UTF-8
            # locale (e.g. Windows cp1252/cp936) for a non-ASCII node name or
            # echoed path. We decode UTF-8 explicitly below so user content
            # round-trips regardless of locale (issue #33).
            proc = subprocess.run(cmd, capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return RunResult(
                stdout="",
                stderr=f"gda: Godot timed out after {self.timeout}s\n",
                exit_code=EXIT_TIMEOUT,
                launch_failure=LaunchFailure.TIMEOUT,
            )
        except OSError as exc:
            # The configured binary could not be launched. ``FileNotFoundError``
            # (missing), ``PermissionError`` (a directory like ``Godot.app`` — a
            # natural $GDA_GODOT mistake — or a non-executable file), and any
            # other ``OSError`` from ``exec`` are all the same environment
            # failure: there was no engine to run (issue #33). They synthesize
            # the typed ``NOT_FOUND`` reason so the classifier keys environment
            # on it, not on the overloaded exit code (issue #15). ``OSError``
            # does not subsume ``TimeoutExpired`` (a ``SubprocessError``), so the
            # timeout path above is preserved. The original OS message is kept as
            # advisory stderr to disambiguate which of the three modes occurred.
            return RunResult(
                stdout="",
                stderr=f"gda: Godot binary could not be launched: {self.binary} ({exc})\n",
                exit_code=EXIT_NOT_FOUND,
                launch_failure=LaunchFailure.NOT_FOUND,
            )
        return RunResult(
            # Decode the engine's bytes as UTF-8 with a replacement policy: a
            # well-behaved operation emits valid UTF-8, so ``replace`` only ever
            # fires on genuinely malformed bytes — and the runner never crashes
            # on engine output. A malformed result then surfaces as a structured
            # ``contract_violation`` downstream rather than an escaping
            # ``UnicodeDecodeError`` traceback (ADR-0002).
            stdout=proc.stdout.decode("utf-8", errors="replace"),
            stderr=proc.stderr.decode("utf-8", errors="replace"),
            exit_code=proc.returncode,
        )
