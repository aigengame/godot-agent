"""Failure classification for headless operations (issues #3, #14).

This is the single home of ``gda``'s failure taxonomy, split into two layers
(issue #14):

- ``classify_run`` — command-agnostic: given the raw ``RunResult`` of a
  one-shot headless invocation and the command's typed output model, it owns
  the environment/operation/parse decision tree shared by every command and
  returns either the validated model or a ``Failure`` — a stable ``GdaError``
  plus the process exit code that distinguishes its category.
- thin per-command classifiers (``classify_info``) — layer command-specific
  checks (e.g. ``info``'s ADR-0003 version gate) on top of ``classify_run``.

The classification is a pure function of the raw result, so every failure mode
is exercised by injecting a crafted ``RunResult`` without touching a real
engine. The decision tree, top to bottom (``code`` in parentheses; the four
``ErrorCategory`` buckets fan out to finer codes):

- launch NOT_FOUND → environment / binary_not_found  (runner could not launch it)
- launch TIMEOUT   → environment / launch_timeout     (runner launched it but it
  hung past the timeout)
- exit < 0  → operation   / engine_crashed         (engine killed by a signal)
- exit ≠ 0  → operation   / <operation code>        (operation reported a structured
  failure via the ADR-0002 error envelope — e.g. path_not_found)
- exit ≠ 0  → operation   / operation_failed        (engine ran, operation errored
  without a valid registered error envelope)
- contract  → parse       / contract_violation      (sentinel/JSON/shape invalid)
- old       → version     / unsupported_version     (below the ADR-0003 minimum,
  ``info``'s per-command layer)

Environment failures are keyed on the runner's typed ``launch_failure`` reason,
not the exit code, so an engine (or shell/AppImage wrapper) that *genuinely*
returns 124/127 is classified as ``operation`` rather than mislabelled
environment (issue #15). The synthesized environment failures still *exit* with
the shell-convention codes 124/127; version/operation/parse get distinct small
codes so a shell consumer can tell categories apart without parsing the JSON error.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from gda.error_codes import ERROR_CODE_BY_CODE, OPERATION_ERROR_CODES
from gda.exit_codes import (
    EXIT_NOT_FOUND,
    EXIT_OPERATION,
    EXIT_PARSE,
    EXIT_TIMEOUT,
    EXIT_VERSION,
)
from gda.models import (
    EngineVersion,
    ErrorCategory,
    GdaError,
    OperationErrorEnvelope,
    ScriptDiagnostic,
    ScriptValidateResult,
)
from gda.parser import parse_result
from gda.runner import LaunchFailure, RunResult

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
    spec = ERROR_CODE_BY_CODE.get(code)
    if spec is None:
        raise RuntimeError(f"unregistered GdaError.code: {code}")
    if spec.category is not category:
        raise RuntimeError(
            f"GdaError.code {code!r} is registered as {spec.category.value}, "
            f"not {category.value}"
        )
    return Failure(
        GdaError(category=category, code=code, message=message, diagnostics=stderr),
        exit_code=exit_code,
    )


M = TypeVar("M", bound=BaseModel)


def _operation_error_from_payload(result: RunResult) -> tuple[str, str] | None:
    """Extract a minimal operation error envelope from stdout, if present."""
    try:
        payload = parse_result(result.stdout)
    except ValueError:
        return None
    try:
        envelope = OperationErrorEnvelope.model_validate(payload)
    except ValidationError:
        return None
    return envelope.error.code, envelope.error.message


def classify_run(result: RunResult, binary: Path, output_model: type[M]) -> M | Failure:
    """Classify a raw headless run into the command's typed model or a ``Failure``.

    Command-agnostic: owns the env/operation/parse decision tree shared by all
    commands. Per-command classifiers layer their specific checks on top.
    """
    if result.launch_failure is LaunchFailure.NOT_FOUND:
        return _failure(
            ErrorCategory.ENVIRONMENT,
            "binary_not_found",
            f"Godot binary could not be launched: {binary}",
            EXIT_NOT_FOUND,
            result.stderr,
        )
    if result.launch_failure is LaunchFailure.TIMEOUT:
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
        # non-zero (its own exit, not the runner's synthetic 124/127). When the
        # operation reported the failure structurally via the ADR-0002 sentinel
        # error envelope, surface its registered finer code; otherwise fall
        # back to the generic operation_failed.
        payload_error = _operation_error_from_payload(result)
        if payload_error is not None:
            code, message = payload_error
            if code not in OPERATION_ERROR_CODES:
                return _failure(
                    ErrorCategory.OPERATION,
                    "operation_failed",
                    f"headless operation reported unregistered error code: {code}",
                    EXIT_OPERATION,
                    result.stderr,
                )
            return _failure(
                ErrorCategory.OPERATION,
                code,
                message or "the headless operation reported an error",
                EXIT_OPERATION,
                result.stderr,
            )
        return _failure(
            ErrorCategory.OPERATION,
            "operation_failed",
            "the headless operation exited non-zero without a structured error",
            EXIT_OPERATION,
            result.stderr,
        )
    try:
        # The sentinel block must be present, hold valid JSON, AND match the
        # command's result shape. A missing/empty sentinel or malformed JSON
        # raises ValueError from parse_result; a well-formed-JSON-but-wrong-shape
        # payload raises pydantic ValidationError. All three are the same
        # violation of the structured-output contract (ADR-0002), distinct from
        # an operation error — and must surface as a structured parse failure
        # rather than escape as a traceback.
        return output_model.model_validate(parse_result(result.stdout))
    except (ValueError, ValidationError) as exc:
        return _failure(
            ErrorCategory.PARSE,
            "contract_violation",
            f"structured-output contract violated: {exc}",
            EXIT_PARSE,
            result.stderr,
        )


# A `SCRIPT ERROR: <message>` line and the `GDScript::reload (...:<line>)` frame
# that follows it carry, between them, the one advisory diagnostic the engine
# emits for a failed validate (issue #118). The line number is the final `:`
# part of the reload frame; there is NO column on the standard build.
# `[ \t]` (not `\s`) bounds the message capture so it cannot span newlines — an
# empty SCRIPT ERROR message must not swallow the following reload frame.
# Backtrace frames (`[n] _initialize (...)`) are operations.gd's own lines, not
# the validated script's, so they are deliberately not matched.
_SCRIPT_ERROR_LINE = re.compile(
    r"^[ \t]*SCRIPT ERROR:[ \t]*(?P<message>.*?)[ \t]*$", re.MULTILINE
)
_RELOAD_FRAME = re.compile(r"GDScript::reload \([^)]*:(?P<line>\d+)\)")


def parse_validate_diagnostics(stderr: str) -> list[ScriptDiagnostic]:
    """Parse advisory ``script validate`` diagnostics from the engine's stderr.

    A pure function (no engine, no I/O): the line/message of a failed
    ``GDScript.reload()`` are available only from stderr, not from any bound API
    (ADR-0002's stderr is advisory only — it is never parsed for the stable
    success/failure outcome or error codes, only surfaced here as best-effort
    diagnostics). ``column`` is always null (the engine exposes none).

    The validate op does exactly ONE ``reload()``, so the only legitimate
    ``GDScript::reload`` frame in stderr is the validated script's. Each
    ``SCRIPT ERROR: <message>`` line is paired with a reload frame found ONLY in
    the window up to the next ``SCRIPT ERROR`` line, and a ``SCRIPT ERROR`` with
    no reload frame in that window is dropped: bounding the search keeps a later
    error's frame from being mis-attributed to an earlier message, and the
    frame requirement excludes unrelated engine ``SCRIPT ERROR`` noise — e.g. an
    autoload's own startup error under ``--project``, whose frame is its
    ``_init``/``_ready``, not ``GDScript::reload``. Returns ``[]`` when nothing
    matches.
    """
    matches = list(_SCRIPT_ERROR_LINE.finditer(stderr))
    diagnostics: list[ScriptDiagnostic] = []
    for index, match in enumerate(matches):
        window_end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(stderr)
        )
        frame = _RELOAD_FRAME.search(stderr, match.end(), window_end)
        if frame is None:
            continue
        diagnostics.append(
            ScriptDiagnostic(
                line=int(frame.group("line")),
                column=None,
                message=match.group("message"),
            )
        )
    return diagnostics


def classify_script_validate(
    result: RunResult, binary: Path
) -> ScriptValidateResult | Failure:
    """Classify the raw ``script validate`` result (issue #118).

    The per-command layer for ``script validate``: the shared decision tree comes
    from ``classify_run`` (an op error — missing path, wrong extension,
    unreadable file — is still a ``Failure``). For a SUCCESSFUL op reporting an
    invalid script (``valid=false``), the line/message diagnostics are not in the
    sentinel — they live only in the engine's stderr — so this layer parses them
    in and attaches them to the result.
    """
    outcome = classify_run(result, binary, ScriptValidateResult)
    if isinstance(outcome, Failure):
        return outcome
    if not outcome.valid:
        outcome.diagnostics = parse_validate_diagnostics(result.stderr)
    return outcome


def classify_info(result: RunResult, binary: Path) -> EngineVersion | Failure:
    """Classify the raw ``info`` result into a success model or a ``Failure``.

    The per-command layer for ``info``: the shared decision tree comes from
    ``classify_run``; only the ADR-0003 minimum-version gate is ``info``'s own.
    """
    outcome = classify_run(result, binary, EngineVersion)
    if isinstance(outcome, Failure):
        return outcome
    version = outcome

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
