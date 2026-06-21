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

from gda.error_codes import (
    ERROR_CODE_BY_CODE,
    LIVE_ERROR_CODES,
    OPERATION_ERROR_CODES,
)
from gda.models import (
    EngineVersion,
    ExportRunMode,
    ExportRunResult,
    GameTreeResult,
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


def _failure(code: str, message: str, stderr: str) -> Failure:
    """Build a ``Failure`` from the parts that actually vary per failure.

    Only ``code``, the per-occurrence ``message`` (it embeds the binary path,
    the timeout, the offending value, …), and the ``stderr`` diagnostics vary at
    a call site. The ``category`` and process ``exit_code`` are a stable property
    of the code, so they are derived from the single authoritative registry row
    (ADR-0002, #141) rather than re-stated — and re-checked — at each site. The
    ``GdaError`` wrapping lives here once, so the call sites read as the taxonomy
    itself: a ``(code, message)`` row per failure mode.
    """
    spec = ERROR_CODE_BY_CODE.get(code)
    if spec is None:
        raise RuntimeError(f"unregistered GdaError.code: {code}")
    return Failure(
        GdaError(
            category=spec.category,
            code=code,
            message=message,
            diagnostics=stderr,
        ),
        exit_code=spec.exit_code,
    )


M = TypeVar("M", bound=BaseModel)


def _is_too_deep(exc: ValidationError) -> bool:
    """Is this ValidationError purely pydantic-core's recursion-depth ceiling?

    pydantic-core reports breaching its recursive-validation depth limit with the
    ``recursion_loop`` error type — the same type a genuine cyclic reference
    raises. A deep-but-valid tree (issue #37) produces ONLY ``recursion_loop``
    errors, whereas a real shape violation that merely happens to also be deep
    mixes in other error types; so depth is the cause only when every reported
    error is ``recursion_loop``.
    """
    errors = exc.errors()
    return bool(errors) and all(error["type"] == "recursion_loop" for error in errors)


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


def unresolvable_binary_failure(reason: str) -> Failure:
    """The ``binary_not_found`` failure when the binary cannot even be resolved (issue #33).

    Binary resolution runs *before* a runner is built, so an unresolvable
    ``--godot`` value (an empty ``--godot ""`` / ``$GDA_GODOT`` mistake) raises
    instead of producing a launchable path. There is no engine to run — the same
    environment outcome the runner reports as ``LaunchFailure.NOT_FOUND`` — so it
    reuses the ``binary_not_found`` code rather than minting a new one (ADR-0002:
    reuse the exit code; discriminate via the envelope). Kept here beside the
    other environment failures so the whole taxonomy reads from one place.
    """
    return _failure(
        "binary_not_found",
        f"Godot binary could not be resolved: {reason}",
        "",
    )


def conflicting_params_input_failure() -> Failure:
    """``--params-json`` was combined with the individual arguments (ADR-0015).

    A CLI-side usage error reported *before* any engine launch, but the same
    failure mode the operation dispatcher reports as ``usage_error`` — the
    command was invoked incorrectly — so it reuses that code rather than minting
    a new one (ADR-0002: reuse the code; discriminate via the message).
    """
    return _failure(
        "usage_error",
        "--params-json is mutually exclusive with the individual arguments; "
        "pass the params as one JSON object OR as individual arguments, not both.",
        "",
    )


def invalid_params_json_failure(detail: str) -> Failure:
    """``--params-json`` was not a valid params object for the command (ADR-0015).

    Malformed JSON, or a well-formed object that fails the command's input
    schema. It is the same failure mode the operation dispatcher reports as
    ``invalid_params`` — params that do not match the command's contract — just
    detected CLI-side, so it reuses that code (ADR-0002).
    """
    return _failure(
        "invalid_params",
        f"--params-json is not a valid params object: {detail}",
        "",
    )


def classify_launch_or_crash(raw: RunResult, binary: Path) -> Failure | None:
    """The env/crash classifier prefix shared by both headless channels (#185).

    The single home of the launch-failure and signal-death mapping that the
    sentinel channel (``classify_run``) and the native-export channel
    (``classify_export_run``) both open with, so a missing binary, a hung run,
    or a signal death is classified identically across both (ADR-0010 — reuse
    the machinery rather than duplicate it). Returns the env/crash ``Failure``
    for the three modes below, or ``None`` to let the caller's channel-specific
    tail (sentinel parse+validate vs synthesize-from-exit-code) take over.

    Environment failures key on the runner's typed ``launch_failure`` reason,
    not the exit code, so an engine (or shell/AppImage wrapper) that *genuinely*
    returns 124/127 is classified as ``operation`` by the tail rather than
    mislabelled environment (issue #15).
    """
    if raw.launch_failure is LaunchFailure.NOT_FOUND:
        return _failure(
            "binary_not_found",
            f"Godot binary could not be launched: {binary}",
            raw.stderr,
        )
    if raw.launch_failure is LaunchFailure.TIMEOUT:
        return _failure(
            "launch_timeout",
            "Godot launched but did not return before the timeout",
            raw.stderr,
        )
    if raw.exit_code < 0:
        # subprocess reports a signal death as a negative return code; the
        # engine ran but was killed (e.g. SIGSEGV crash, OOM SIGKILL) rather
        # than the operation cleanly reporting an error.
        return _failure(
            "engine_crashed",
            f"Godot terminated abnormally (signal {-raw.exit_code})",
            raw.stderr,
        )
    return None


def classify_run(result: RunResult, binary: Path, output_model: type[M]) -> M | Failure:
    """Classify a raw headless run into the command's typed model or a ``Failure``.

    Command-agnostic: owns the env/operation/parse decision tree shared by all
    commands. Per-command classifiers layer their specific checks on top.
    """
    prefix = classify_launch_or_crash(result, binary)
    if prefix is not None:
        return prefix
    if result.exit_code != 0:
        # The engine ran but the operation itself reported an error and quit
        # non-zero (its own exit, not the runner's synthetic 124/127). When the
        # operation reported the failure structurally via the ADR-0002 sentinel
        # error envelope with a REGISTERED code, surface its registered finer
        # code. Every other non-zero exit — no structured envelope, or one
        # carrying an unregistered code — is the single generic operation_failed
        # fallback; the two only differ in the message they explain it with.
        payload_error = _operation_error_from_payload(result)
        if payload_error is not None:
            code, message = payload_error
            if code in OPERATION_ERROR_CODES:
                return _failure(
                    code,
                    message or "the headless operation reported an error",
                    result.stderr,
                )
            fallback_message = (
                f"headless operation reported unregistered error code: {code}"
            )
        else:
            fallback_message = (
                "the headless operation exited non-zero without a structured error"
            )
        return _failure("operation_failed", fallback_message, result.stderr)
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
        # pydantic-core caps recursive-model validation at a hardcoded ceiling
        # (~255 levels) and reports breaching it as a `recursion_loop` error —
        # the SAME error type as a genuine cyclic reference. A legitimately deep
        # scene tree (issue #37) trips this even though every node is valid and
        # the payload is contract-conformant: the limit is gda's own (wrapper
        # side), not the engine violating the output contract. Surface that as a
        # distinct `tree_too_deep` failure so it is never misclassified as
        # `contract_violation`. A mix of recursion_loop with other errors is a
        # real shape violation that merely happens to also be deep, so require
        # ALL errors to be recursion_loop before claiming depth as the cause.
        if isinstance(exc, ValidationError) and _is_too_deep(exc):
            return _failure(
                "tree_too_deep",
                "result tree nests too deep for gda to materialize "
                f"(exceeds the recursion limit on {output_model.__name__})",
                result.stderr,
            )
        return _failure(
            "contract_violation",
            f"structured-output contract violated: {exc}",
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
            "unsupported_version",
            f"Godot {version.string} is below the minimum supported version {minimum}",
            result.stderr,
        )

    return version


# Codes the daemon IPC client / the daemon surface through the live sentinel that
# classify_run would otherwise misroute. The LIVE codes are live-runtime failures;
# ``live_unsupported_platform`` is an ENVIRONMENT-category pre-launch precondition
# (ADR-0021) but still arrives via the live path, so classify_live must surface it
# too (else classify_run falls back to operation_failed for a non-operation code).
# ``project_not_found`` is deliberately NOT here — it is an operation-source code
# classify_run already maps, so it falls through to the shared decision tree.
_LIVE_CLIENT_CODES = LIVE_ERROR_CODES | {"live_unsupported_platform"}


def _live_error_from_payload(result: RunResult) -> Failure | None:
    """A live-channel error envelope on stdout becomes its registered ``Failure``.

    The daemon IPC client / the daemon report a live failure as the *same* ADR-0002
    error envelope a headless op uses, carrying a classifier-source code. This maps
    the daemon-channel codes to their registered ``Failure`` directly; any other
    envelope returns ``None`` so the shared ``classify_run`` decision tree handles
    it (e.g. ``project_not_found``).
    """
    pair = _operation_error_from_payload(result)
    if pair is None:
        return None
    code, message = pair
    if code in _LIVE_CLIENT_CODES:
        return _failure(code, message, result.stderr)
    return None


def classify_live(result: RunResult, binary: Path, output_model: type[M]) -> M | Failure:
    """Classify a live operation's raw result (ADR-0017).

    A live op returns the same ``RunResult`` + ADR-0002 sentinel a headless op
    does, so the success path is ``classify_run`` verbatim and the public contract
    is identical. The one addition is the LIVE error envelope
    (``daemon_not_running``, ``engine_disconnected``, …), surfaced here as its
    registered classifier-source code before the shared decision tree runs.
    """
    failure = _live_error_from_payload(result)
    if failure is not None:
        return failure
    return classify_run(result, binary, output_model)


def classify_game_tree(result: RunResult, binary: Path) -> GameTreeResult | Failure:
    """The per-command live classifier for ``gda game tree`` (mirrors ``classify_info``)."""
    return classify_live(result, binary, GameTreeResult)


# A non-fatal export warning the engine prints to stderr. WARNING is Godot's
# WARN_PRINT prefix; these never fail the export (it still exits 0) but are
# surfaced advisorily on the success result (ADR-0002: stderr is advisory for
# success diagnostics), so an agent sees e.g. a missing optional icon.
_EXPORT_WARNING_LINE = re.compile(
    r"^[ \t]*WARNING:[ \t]*(?P<message>.+?)[ \t]*$", re.MULTILINE
)


def parse_export_warnings(stderr: str) -> list[str]:
    """Parse advisory export warnings from a native export's stderr (issue #121).

    A pure function: the engine's ``WARN_PRINT`` lines are advisory-only (they
    never determine the success/failure outcome — a warned export still exits 0),
    so they are surfaced as best-effort diagnostics on the success result.
    Returns ``[]`` when the export was clean.
    """
    return [m.group("message") for m in _EXPORT_WARNING_LINE.finditer(stderr)]


def classify_export_run(
    output: RunResult,
    binary: Path,
    *,
    preset: str,
    platform: str,
    mode: ExportRunMode,
    output_path: str,
) -> ExportRunResult | Failure:
    """Classify a native Godot export into a typed result or a ``Failure`` (issue #121).

    ``export run`` is the one command that does NOT emit an ADR-0002 sentinel —
    the export subsystem is editor-only, so the artifact is produced by a native
    ``--export-<mode>`` invocation. gda synthesizes the structured outcome from
    the subprocess's **exit code** instead (ADR-0010): a clean exit is success
    (with any advisory warnings parsed off stderr); a non-zero exit is the
    classifier-source ``export_failed``. Crucially, this does NOT parse stderr to
    *choose* the code — that would violate ADR-0002's "stderr is never parsed for
    stable codes". The distinct ``export_templates_missing`` mode is decided
    *before* the native run by the CLI's structured preflight (``export get``'s
    ``templates_installed``), not here; on a non-zero export stderr is surfaced
    only as the advisory ``message`` / diagnostics.

    The decision tree shares :func:`classify_launch_or_crash`'s env/crash prefix
    so a missing binary or hung export is reported identically across both
    channels (#185); only the non-zero-exit tail differs from the sentinel
    channel (synthesize-from-exit-code, no sentinel parse).
    """
    prefix = classify_launch_or_crash(output, binary)
    if prefix is not None:
        return prefix
    if output.exit_code != 0:
        # Templates are checked structurally BEFORE this call (the CLI preflights
        # export get's templates_installed), so a missing-templates run never
        # reaches here. Every non-zero native export is therefore the generic
        # classifier-source export_failed; the engine's stderr is preserved only
        # as advisory diagnostics (ADR-0002), never parsed to pick the code.
        return _failure(
            "export_failed",
            f'export of preset "{preset}" failed',
            output.stderr,
        )
    return ExportRunResult(
        preset=preset,
        platform=platform,
        mode=mode,
        output_path=output_path,
        warnings=parse_export_warnings(output.stderr),
    )


def export_path_unset_failure(preset: str) -> Failure:
    """The ``export_path_unset`` failure for a preset with no effective destination (issue #121, #170).

    ``export run`` writes the artifact to the effective destination: the
    ``--output`` override if given (#170), else the preset's own configured
    ``export_path``. When neither supplies a destination — no ``--output`` AND an
    empty configured ``export_path`` — there is nowhere to write, so gda fails
    *before* spawning the export rather than letting the engine error obscurely.
    A pre-run classifier decision (the destination is resolved at the CLI from
    ``--output`` / ``export get``'s ``export_path``), kept here beside the other
    export failures so the whole taxonomy reads from one place.
    """
    return _failure(
        "export_path_unset",
        f'export preset "{preset}" has no destination: '
        "pass --output or set the preset's export_path",
        "",
    )


def export_templates_missing_failure(preset: str, templates_version: str) -> Failure:
    """The ``export_templates_missing`` failure from the structured preflight (issue #121, #170).

    A release/debug export needs the platform export templates for the running
    engine version installed (``pack`` does not — it produces project data only,
    so the preflight skips this check for ``--mode pack``; #170). ``export get``
    already reports template readiness structurally (``templates_installed``) —
    the readiness check built for exactly this — so gda decides this *before*
    spawning the native export, rather than string-matching the engine's "due to
    configuration errors" stderr (which ADR-0002 forbids, and which also fires for
    a merely-misconfigured preset). Names the ``templates_version`` directory the
    agent must install.
    """
    return _failure(
        "export_templates_missing",
        f'export preset "{preset}" cannot be exported: the export templates for '
        f"the running engine version ({templates_version}) are not installed",
        "",
    )
