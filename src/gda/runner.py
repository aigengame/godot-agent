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


def launch(
    binary: Path,
    args: list[str],
    *,
    cwd: Path | None,
    timeout: float,
) -> RunResult:
    """Spawn one ``godot --headless`` process and normalize its raw outcome.

    The single home of the headless-launch primitive: it builds
    ``[binary, --headless, *args]``, runs it with a timeout capturing raw
    *bytes*, and returns a normalized :class:`RunResult`. Both Phase-1 channels
    — the sentinel op-dispatch runner and the native-export runner — build only
    their channel-specific argv tail (and the export-only ``cwd``) and delegate
    the spawn/timeout/``OSError``/decode handling here, so a launch-handling fix
    lands in one place rather than two copies (issue #185, ADR-0010).

    The mapping, identical for both channels:

    - ``subprocess.TimeoutExpired`` → a synthesized ``EXIT_TIMEOUT`` result
      flagged ``LaunchFailure.TIMEOUT``: launched, but did not return before the
      timeout (a hung engine bounded so the CLI fails loudly, #15);
    - ``OSError`` → a synthesized ``EXIT_NOT_FOUND`` result flagged
      ``LaunchFailure.NOT_FOUND``: the configured binary could not be launched —
      ``FileNotFoundError`` (missing), ``PermissionError`` (a directory like
      ``Godot.app`` — a natural ``$GDA_GODOT`` mistake — or a non-executable
      file), and any other ``OSError`` from ``exec`` are the one environment
      failure of there being no engine to run (#33). The synthesized typed
      reason lets the classifier key environment on it, not on the overloaded
      exit code (#15). ``OSError`` does not subsume ``TimeoutExpired`` (a
      ``SubprocessError``), so the timeout path above is preserved. The OS
      message is kept as advisory stderr to disambiguate which mode occurred;
    - otherwise → the engine's own ``returncode`` with ``launch_failure=None``,
      and stdout/stderr decoded as UTF-8 with ``errors="replace"`` (see below).
    """
    cmd = [str(binary), "--headless", *args]
    try:
        # Capture raw bytes (no ``text=True``): Godot's ``JSON.stringify`` emits
        # UTF-8, but ``text=True`` would decode with the host locale, which
        # mojibakes or raises ``UnicodeDecodeError`` on a non-UTF-8 locale (e.g.
        # Windows cp1252/cp936) for a non-ASCII node name or echoed path. We
        # decode UTF-8 explicitly below so user content round-trips regardless of
        # locale (issue #33).
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            # Pass the working directory as a string (not a Path): the export
            # channel resolves a relative output path against this CWD, and the
            # spawn shape stays byte-identical to the pre-#185 ``str(project)``.
            cwd=str(cwd) if cwd is not None else None,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            stdout="",
            stderr=f"gda: Godot timed out after {timeout}s\n",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
        )
    except OSError as exc:
        return RunResult(
            stdout="",
            stderr=f"gda: Godot binary could not be launched: {binary} ({exc})\n",
            exit_code=EXIT_NOT_FOUND,
            launch_failure=LaunchFailure.NOT_FOUND,
        )
    return RunResult(
        # Decode the engine's bytes as UTF-8 with a replacement policy: a
        # well-behaved operation emits valid UTF-8, so ``replace`` only ever
        # fires on genuinely malformed bytes — and the runner never crashes on
        # engine output. A malformed result then surfaces as a structured
        # ``contract_violation`` downstream rather than an escaping
        # ``UnicodeDecodeError`` traceback (ADR-0002).
        stdout=proc.stdout.decode("utf-8", errors="replace"),
        stderr=proc.stderr.decode("utf-8", errors="replace"),
        exit_code=proc.returncode,
    )


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
        # Build only this channel's argv tail and delegate the spawn / timeout /
        # OSError / UTF-8-decode handling to the shared launch primitive (#185).
        # Everything after `--` is delivered to the script verbatim via
        # OS.get_cmdline_user_args(), so the payload is decoupled from however
        # Godot orders its own engine arguments.
        args: list[str] = []
        if self.project is not None:
            args += ["--path", str(self.project)]
        args += [
            "--script",
            str(self.script),
            "--",
            operation,
            json.dumps(params),
        ]
        # A sentinel op runs projectless or against --path; it never needs a
        # working directory, so cwd is always the default.
        return launch(self.binary, args, cwd=None, timeout=self.timeout)
