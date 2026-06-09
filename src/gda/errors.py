"""Failure classification for the headless ``info`` operation (issue #3).

This is the single home of ``gda``'s failure taxonomy: given the raw
``RunResult`` of a one-shot headless invocation, ``classify_info`` returns
either the parsed success result (``EngineVersion``) or a ``Failure`` — a stable
``GdaError`` plus the process exit code that distinguishes its category.

The classification is a pure function of the raw result, so every failure mode
is exercised by injecting a crafted ``RunResult`` without touching a real
engine. The decision tree, top to bottom (``code`` in parentheses; the four
``ErrorCategory`` buckets fan out to finer codes):

- exit 127  → environment / binary_not_found      (runner could not launch it)
- exit 124  → environment / launch_timeout        (launched, hung past timeout)
- exit < 0  → operation   / engine_crashed         (engine killed by a signal)
- exit ≠ 0  → operation   / operation_failed        (engine ran, operation errored)
- contract  → parse       / contract_violation      (sentinel/JSON/shape invalid)
- old       → version     / unsupported_version     (below the ADR-0003 minimum)

Exit codes come from the single registry in ``gda.exit_codes``: environment
reuses the runner's shell-convention codes (124/127); version/operation/parse
get distinct small codes so a shell consumer can tell categories apart without
parsing the JSON error.
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from gda.exit_codes import (
    EXIT_NOT_FOUND,
    EXIT_OPERATION,
    EXIT_PARSE,
    EXIT_TIMEOUT,
    EXIT_VERSION,
)
from gda.models import EngineVersion, ErrorCategory, GdaError
from gda.parser import parse_result
from gda.runner import RunResult

# The minimum supported Godot version (ADR-0003): the floor where the modern
# features gda relies on exist. Resolved from the version gda info reports.
MIN_GODOT_VERSION = (4, 4)


@dataclass
class Failure:
    """A classified failure: the stable error shape plus its process exit code."""

    error: GdaError
    exit_code: int


def _failure(
    category: ErrorCategory,
    code: str,
    message: str,
    exit_code: int,
    stderr: str,
) -> Failure:
    """Build a ``Failure`` from the four parts that actually vary per failure.

    The ``GdaError`` wrapping and ``diagnostics=stderr`` are identical at every
    call site, so they live here once: the call sites then read as the taxonomy
    itself — a (category, code, message, exit_code) row per failure mode.
    """
    return Failure(
        GdaError(category=category, code=code, message=message, diagnostics=stderr),
        exit_code=exit_code,
    )


def classify_info(result: RunResult, binary: Path) -> EngineVersion | Failure:
    """Classify the raw ``info`` result into a success model or a ``Failure``."""
    if result.exit_code == EXIT_NOT_FOUND:
        return _failure(
            ErrorCategory.ENVIRONMENT,
            "binary_not_found",
            f"Godot binary could not be launched: {binary}",
            EXIT_NOT_FOUND,
            result.stderr,
        )
    if result.exit_code == EXIT_TIMEOUT:
        return _failure(
            ErrorCategory.ENVIRONMENT,
            "launch_timeout",
            "Godot launched but did not return before the timeout",
            EXIT_TIMEOUT,
            result.stderr,
        )
    if result.exit_code < 0:
        # subprocess reports a signal death as a negative return code; the
        # engine ran but was killed (e.g. SIGSEGV crash, OOM SIGKILL) rather
        # than the operation cleanly reporting an error.
        return _failure(
            ErrorCategory.OPERATION,
            "engine_crashed",
            f"Godot terminated abnormally (signal {-result.exit_code})",
            EXIT_OPERATION,
            result.stderr,
        )
    if result.exit_code != 0:
        # The engine ran but the operation itself reported an error and quit
        # non-zero (its own exit, not the runner's synthetic 124/127).
        return _failure(
            ErrorCategory.OPERATION,
            "operation_failed",
            "the headless operation reported an error",
            EXIT_OPERATION,
            result.stderr,
        )

    try:
        # The sentinel block must be present, hold valid JSON, AND match the
        # result shape. A missing/empty sentinel or malformed JSON raises
        # ValueError from parse_result; a well-formed-JSON-but-wrong-shape
        # payload raises pydantic ValidationError. All three are the same
        # violation of the structured-output contract (ADR-0002), distinct from
        # an operation error — and must surface as a structured parse error
        # rather than escape as a traceback.
        version = EngineVersion.model_validate(parse_result(result.stdout))
    except (ValueError, ValidationError) as exc:
        return _failure(
            ErrorCategory.PARSE,
            "contract_violation",
            f"structured-output contract violated: {exc}",
            EXIT_PARSE,
            result.stderr,
        )

    if (version.major, version.minor) < MIN_GODOT_VERSION:
        # The engine ran fine but is older than gda supports (ADR-0003), making
        # "version too old" a programmatically detectable failure rather than an
        # implicit one — distinct from the environment-error case.
        minimum = ".".join(str(part) for part in MIN_GODOT_VERSION)
        return _failure(
            ErrorCategory.VERSION,
            "unsupported_version",
            f"Godot {version.string} is below the minimum supported version {minimum}",
            EXIT_VERSION,
            result.stderr,
        )

    return version
