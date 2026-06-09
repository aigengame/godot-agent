"""Failure classification for the headless ``info`` operation (issue #3).

This is the single home of ``gda``'s failure taxonomy: given the raw
``RunResult`` of a one-shot headless invocation, ``classify_info`` returns
either the parsed success result (``EngineVersion``) or a ``Failure`` — a stable
``GdaError`` plus the process exit code that distinguishes its category.

The classification is a pure function of the raw result, so every failure mode
is exercised by injecting a crafted ``RunResult`` without touching a real
engine. The decision tree, top to bottom:

- exit 127 → environment / binary_not_found   (runner could not launch it)
- exit 124 → environment / launch_timeout      (launched, hung past the timeout)
- exit ≠ 0 → operation  / operation_failed      (engine ran, operation errored)
- contract → parse      / contract_violation    (sentinel missing/malformed JSON)
- old      → version    / unsupported_version   (below the ADR-0003 minimum)

Exit codes: environment reuses the runner's shell-convention codes (124/127);
version/operation/parse get distinct small codes so a shell consumer can tell
categories apart without parsing the JSON error.
"""

from dataclasses import dataclass
from pathlib import Path

from gda.models import EngineVersion, ErrorCategory, GdaError
from gda.parser import parse_result
from gda.runner import EXIT_NOT_FOUND, EXIT_TIMEOUT, RunResult

EXIT_VERSION = 3
EXIT_OPERATION = 4
EXIT_PARSE = 5

# The minimum supported Godot version (ADR-0003): the floor where the modern
# features gda relies on exist. Resolved from the version gda info reports.
MIN_GODOT_VERSION = (4, 4)


@dataclass
class Failure:
    """A classified failure: the stable error shape plus its process exit code."""

    error: GdaError
    exit_code: int


def classify_info(result: RunResult, binary: Path) -> EngineVersion | Failure:
    """Classify the raw ``info`` result into a success model or a ``Failure``."""
    if result.exit_code == EXIT_NOT_FOUND:
        return Failure(
            GdaError(
                category=ErrorCategory.ENVIRONMENT,
                code="binary_not_found",
                message=f"Godot binary could not be launched: {binary}",
                diagnostics=result.stderr,
            ),
            exit_code=EXIT_NOT_FOUND,
        )
    if result.exit_code == EXIT_TIMEOUT:
        return Failure(
            GdaError(
                category=ErrorCategory.ENVIRONMENT,
                code="launch_timeout",
                message="Godot launched but did not return before the timeout",
                diagnostics=result.stderr,
            ),
            exit_code=EXIT_TIMEOUT,
        )
    if result.exit_code != 0:
        # The engine ran but the operation itself reported an error and quit
        # non-zero (its own exit, not the runner's synthetic 124/127).
        return Failure(
            GdaError(
                category=ErrorCategory.OPERATION,
                code="operation_failed",
                message="the headless operation reported an error",
                diagnostics=result.stderr,
            ),
            exit_code=EXIT_OPERATION,
        )

    try:
        payload = parse_result(result.stdout)
    except ValueError as exc:
        # The sentinel block is missing, or the payload between sentinels is
        # malformed JSON — a violation of the structured-output contract
        # (ADR-0002), distinct from an operation error.
        return Failure(
            GdaError(
                category=ErrorCategory.PARSE,
                code="contract_violation",
                message=f"structured-output contract violated: {exc}",
                diagnostics=result.stderr,
            ),
            exit_code=EXIT_PARSE,
        )

    version = EngineVersion.model_validate(payload)

    if (version.major, version.minor) < MIN_GODOT_VERSION:
        # The engine ran fine but is older than gda supports (ADR-0003), making
        # "version too old" a programmatically detectable failure rather than an
        # implicit one — distinct from the environment-error case.
        minimum = ".".join(str(part) for part in MIN_GODOT_VERSION)
        return Failure(
            GdaError(
                category=ErrorCategory.VERSION,
                code="unsupported_version",
                message=(
                    f"Godot {version.string} is below the minimum "
                    f"supported version {minimum}"
                ),
                diagnostics=result.stderr,
            ),
            exit_code=EXIT_VERSION,
        )

    return version
