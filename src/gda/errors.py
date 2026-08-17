"""Failure classification for headless operations (issues #3, #14).

This is the single home of ``gda``'s failure taxonomy, split into two layers
(issue #14):

- ``classify_run`` — command-agnostic: given the raw ``RunResult`` of a
  one-shot headless invocation and the command's typed output model, it owns
  the environment/operation/parse decision tree shared by every command and
  returns either the validated model or a ``Failure`` — a stable ``GdaError``
  plus the process exit code that distinguishes its category.
- thin per-command classifiers (``gda.commands.meta.classify_info``) — layer
  command-specific checks (e.g. ``info``'s ADR-0003 version gate) on top of
  ``classify_run``.

The classification is a pure function of the raw result, so every failure mode
is exercised by injecting a crafted ``RunResult`` without touching a real
engine. The decision tree, top to bottom (``code`` in parentheses; the four
``ErrorCategory`` buckets fan out to finer codes):

- launch NOT_FOUND → environment / binary_not_found  (runner could not launch it)
- launch TIMEOUT   → environment / launch_timeout     (runner launched it but it
  hung past the timeout)
- launch USER_DATA_UNWRITABLE → environment / user_data_unwritable (the engine log
  target gda owns could not be created, so the launch was refused, #653)
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
    EnvironmentProbe,
    GdaError,
    LiveErrorEnvelope,
    OperationErrorEnvelope,
)
from gda.parser import parse_result
from gda.runner import LaunchFailure, RunResult

# The minimum supported Godot version (ADR-0003): the floor where the modern
# features gda relies on exist. Resolved from the version gda info reports; the
# gate that applies it is ``info``'s own classifier, in ``gda.commands.meta``.
MIN_GODOT_VERSION = (4, 4)


@dataclass
class Failure:
    """A classified failure: the stable error shape plus its process exit code."""

    error: GdaError
    exit_code: int


def make_failure(
    code: str,
    message: str,
    stderr: str,
    probe: EnvironmentProbe | None = None,
) -> Failure:
    """Build a ``Failure`` from the parts that actually vary per failure.

    Only ``code``, the per-occurrence ``message`` (it embeds the binary path,
    the timeout, the offending value, …), and the ``stderr`` diagnostics vary at
    a call site. The ``category`` and process ``exit_code`` are a stable property
    of the code, so they are derived from the single authoritative registry row
    (ADR-0002, #141) rather than re-stated — and re-checked — at each site. The
    ``GdaError`` wrapping lives here once, so the call sites read as the taxonomy
    itself: a ``(code, message)`` row per failure mode.

    ``probe`` is the optional :class:`EnvironmentProbe` context (ADR-0004
    amendment, #667): the host call that decided an ENVIRONMENT failure gda
    resolved by probing the machine rather than by running the engine. It stays
    ``None`` — and so out of the emitted JSON entirely — for every other failure.
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
            probe=probe,
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
    return make_failure(
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
    return make_failure(
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
    return make_failure(
        "invalid_params",
        f"--params-json is not a valid params object: {detail}",
        "",
    )


def classify_launch_or_crash(raw: RunResult, binary: Path | None) -> Failure | None:
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
        return make_failure(
            "binary_not_found",
            f"Godot binary could not be launched: {binary}",
            raw.stderr,
        )
    if raw.launch_failure is LaunchFailure.TIMEOUT:
        return make_failure(
            "launch_timeout",
            "Godot launched but did not return before the timeout",
            raw.stderr,
        )
    if raw.launch_failure is LaunchFailure.USER_DATA_UNWRITABLE:
        # Refused before the spawn (issue #653): the engine builds its file logger
        # ahead of any project code and dies with signal 11 when it cannot open the
        # log, so this environment problem would otherwise arrive as an
        # `engine_crashed` backtrace. The runner's diagnostics name the binary, the
        # user-data directory, and the log path.
        return make_failure(
            "user_data_unwritable",
            "the log or user data placement for this launch is not usable; "
            "the launch was refused",
            raw.stderr,
        )
    if raw.exit_code < 0:
        # subprocess reports a signal death as a negative return code; the
        # engine ran but was killed (e.g. SIGSEGV crash, OOM SIGKILL) rather
        # than the operation cleanly reporting an error.
        return make_failure(
            "engine_crashed",
            f"Godot terminated abnormally (signal {-raw.exit_code})",
            raw.stderr,
        )
    return None


def classify_run(
    result: RunResult, binary: Path | None, output_model: type[M]
) -> M | Failure:
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
                return make_failure(
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
        return make_failure("operation_failed", fallback_message, result.stderr)
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
            return make_failure(
                "tree_too_deep",
                "result tree nests too deep for gda to materialize "
                f"(exceeds the recursion limit on {output_model.__name__})",
                result.stderr,
            )
        return make_failure(
            "contract_violation",
            f"structured-output contract violated: {exc}",
            result.stderr,
        )


# Codes the daemon IPC client / the daemon surface through the live sentinel that
# classify_run would otherwise misroute. The LIVE codes are live-runtime failures;
# ``live_unsupported_platform``, ``live_windowed_unavailable`` and
# ``live_windowed_permission_denied`` are ENVIRONMENT-category pre-launch
# preconditions but still arrive via the live path (both windowed codes are raised at
# the daemon's session-launch boundary and relayed as a live reply, #345/#667), so
# classify_live must surface them too — else classify_run falls back to
# operation_failed for a non-operation code.
# ``project_not_found`` is deliberately NOT here — it is an operation-source code
# classify_run already maps, so it falls through to the shared decision tree.
_LIVE_CLIENT_CODES = LIVE_ERROR_CODES | {
    "live_unsupported_platform",
    "live_windowed_unavailable",
    "live_windowed_permission_denied",
}


def _live_error_from_payload(result: RunResult) -> Failure | None:
    """A live-channel error envelope on stdout becomes its registered ``Failure``.

    The daemon IPC client / the daemon report a live failure as the *same* ADR-0002
    error envelope a headless op uses, carrying a classifier-source code. This maps
    the daemon-channel codes to their registered ``Failure`` directly; any other
    envelope returns ``None`` so the shared ``classify_run`` decision tree handles
    it (e.g. ``project_not_found``).

    Parsed with :class:`LiveErrorEnvelope` rather than the headless
    ``OperationErrorEnvelope`` because the live channel may carry the optional
    ``probe`` context (#667) — the strict headless model would reject that envelope
    outright and drop the whole failure to ``operation_failed``. The probe rides
    through to the public envelope, so a windowed refusal from the daemon's
    authoritative launch boundary reports exactly what the CLI fail-fast reports.
    """
    try:
        payload = parse_result(result.stdout)
    except ValueError:
        return None
    try:
        envelope = LiveErrorEnvelope.model_validate(payload)
    except ValidationError:
        return None
    error = envelope.error
    if error.code in _LIVE_CLIENT_CODES:
        return make_failure(error.code, error.message, result.stderr, probe=error.probe)
    return None


def classify_live(
    result: RunResult, binary: Path | None, output_model: type[M]
) -> M | Failure:
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


def export_output_parent_failure(output_path: str, parent_path: str) -> Failure:
    """The classifier-source failure for an uncreatable export output parent (#402)."""
    return make_failure(
        "export_output_parent_failed",
        "export output parent directory is not creatable: "
        f"{parent_path} (for output path {output_path})",
        "",
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
    return make_failure(
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
    return make_failure(
        "export_templates_missing",
        f'export preset "{preset}" cannot be exported: the export templates for '
        f"the running engine version ({templates_version}) are not installed",
        "",
    )


def script_path_invalid_failure(path: str) -> Failure:
    """The ``invalid_path`` failure for a non-project-scoped ``script run`` path (ADR-0031, #675).

    ``script run`` is project-scoped: it takes the two PORTABLE forms — a
    project-relative path and a ``res://`` address — which both resolve against the
    ``--project`` context (ADR-0006). It refuses four shapes, all decided at the
    CLI *before* any engine launch, never as a crash or a raw engine failure (an
    explicit ABI edge of ADR-0031): an **absolute** path, **another engine scheme**
    (``user://``, ``uid://``), a path naming the project **root** (``""``, ``"."``),
    and a path **escaping above the root** (``".."``, ``"../outside.gd"``). The
    message names the accepted forms rather than the rejected shape, so it reads the
    same for all four.

    Absolute stays refused for two verified reasons, not merely as deferred scope.
    The engine reports a failed run under the ``res://`` spelling even when launched
    with an absolute in-project path, so accepting one without also mapping it back
    to ``res://`` would break the canonical-identity match the never-ran verdict
    depends on (#651) and reopen the phantom success it closed. And ``--script``
    with an absolute path OUTSIDE the project really does execute, so accepting
    absolute would widen the Project-code execution surface past ADR-0009's Trusted
    project — a trust decision that needs its own ADR. Note ``script validate`` does
    accept an absolute path today; the asymmetry is deliberate, and bounded to the
    two portable forms.

    Kept beside the other pre-run failures so the whole taxonomy reads from one place.
    """
    return make_failure(
        "invalid_path",
        f"script run requires a project-relative or res:// script path, got: {path!r}",
        "",
    )


def script_run_project_not_found_failure() -> Failure:
    """The ``project_not_found`` failure for a ``script run`` with no resolved project (ADR-0031).

    ``script run`` requires a resolved Godot project (ADR-0006): a res:// script
    path needs a project to resolve against. When none resolves (no ``--project``,
    no ``$GDA_PROJECT``, and the cwd is not a project), gda fails *before* spawning
    the engine with this structured failure rather than launching projectless —
    the other explicit ABI edge of ADR-0031.
    """
    return make_failure(
        "project_not_found",
        "script run requires a resolved Godot project: pass --project, set "
        "$GDA_PROJECT, or run from a project directory",
        "",
    )


def script_outside_project_failure(location: Path, project: Path) -> Failure:
    """The ``project_not_found`` refusal for a target outside the resolved project (#658).

    ADR-0006 resolves ONE project per call (``--project`` > ``$GDA_PROJECT`` >
    cwd) and deliberately does not derive it from the target path. A target that
    lies outside that project would still be compiled against it, so every
    ``res://`` dependency it names resolves against the wrong root: the engine
    reports a cascade of missing-file and derived type errors for a file that is
    perfectly valid in its own project, and the single project-context mistake is
    buried under them. gda therefore refuses *before* the target is parsed and
    reports the mismatch itself, naming both sides so the reader can see which
    one is wrong.

    It reuses ``project_not_found`` rather than minting a code: the failure is
    that no project usable for this target was resolved, and the remedy is the
    project context (``--project``) — the same class of mistake, and the same
    branch an agent takes, as ``script run``'s projectless edge (ADR-0031).
    """
    return make_failure(
        "project_not_found",
        f"{location} is outside the resolved Godot project {project}: its res:// "
        "dependencies would resolve against the wrong root, so nothing was "
        "parsed. Pass --project for the project that owns this file, or name a "
        "file inside the resolved one.",
        "",
    )


def script_did_not_run_failure(
    code: str, script: str, detail: str, stderr: str
) -> Failure:
    """The ``script run`` verdict for an entry script that never ran (#651).

    ADR-0031 passes a completed run's exit status through verbatim, because gda
    does not know the user script's semantics. That reasoning does not reach a run
    where the script never STARTED: Godot reports a missing or non-compiling
    ``--script`` entry point on stderr and still exits ``0``, so passing that
    status through reports a phantom success for a failure no reading of the
    contract calls one. gda is the authority on whether the engine ran what it was
    asked to, so this is a classifier decision, keyed on the parsed stderr evidence
    (:func:`gda.script_errors.entry_load_failure`) rather than on the exit code.

    ``code`` is the registered verdict (``script_not_found`` /
    ``script_compile_failed``), ``detail`` the engine's own sentence, kept in the
    message so the agent sees WHY without parsing ``diagnostics``.
    """
    return make_failure(
        code,
        f"script run: {script} did not run — {detail}",
        stderr,
    )


# The section headers of a `script_failed` envelope's ``diagnostics`` (#651). The
# layout is fixed and both sections are ALWAYS emitted — an empty stream yields an
# empty section rather than a missing one — so a consumer can split on the headers
# without first discovering which streams the script happened to write to.
SCRIPT_OUTPUT_STDOUT_HEADER = "--- script stdout ---"
SCRIPT_OUTPUT_STDERR_HEADER = "--- script stderr ---"


def _labelled_script_output(stdout: str, stderr: str) -> str:
    """Both of the child's streams as one labelled ``diagnostics`` string (#651).

    ``GdaError.diagnostics`` is a free-form ``str`` (ADR-0004), and for a failure
    that IS the script's own — ``script_failed`` — the script's own output is the
    diagnostic. A GDScript test runner reports through ``print()``, i.e. stdout, so
    carrying stderr alone would hand a ``--strict`` CI caller a failure with no
    content. Both streams are labelled rather than concatenated so the caller can
    still tell which is which.
    """
    parts = []
    for header, stream in (
        (SCRIPT_OUTPUT_STDOUT_HEADER, stdout),
        (SCRIPT_OUTPUT_STDERR_HEADER, stderr),
    ):
        # Keep each section's payload verbatim, only guaranteeing the newline that
        # puts the next header on its own line.
        body = stream if stream.endswith("\n") or not stream else stream + "\n"
        parts.append(f"{header}\n{body}")
    return "".join(parts)


def script_exit_status_failure(
    script: str, exit_status: int, stdout: str, stderr: str
) -> Failure:
    """The ``script run --strict`` verdict for a non-zero script exit (#651).

    Opt-in only. The default remains ADR-0031's passthrough — a deliberate
    ``quit(1)`` is data the agent reads — so ``--strict`` is how a caller says "for
    THIS run, treat the script's own failure as mine": the shell-chain and CI case,
    where a zero gda exit silently accepts a failed test suite. The child status is
    NOT propagated as the process exit code; it is mapped onto the registered
    ``script_failed``/exit ``4`` so a script's ``quit(3)`` cannot alias an unrelated
    registry code (``EXIT_VERSION``).

    The evidence the caller needs is preserved: the status stays readable in the
    message, and ``diagnostics`` carries BOTH of the script's streams under fixed
    labels. Carrying stderr alone would defeat the flag's own use case — a GDScript
    test runner reports through ``print()``. The status survives only as message
    prose; a structured status field on the failure channel would need an ADR-0004
    envelope change, deferred to that decision (#655).
    """
    return make_failure(
        "script_failed",
        f"script run --strict: {script} exited with status {exit_status}",
        _labelled_script_output(stdout, stderr),
    )


# How much of each stream a gda-ENDED ``script run`` carries into its
# ``diagnostics`` (#655). A run gda cut short can have produced arbitrarily much
# output — a test suite that looped for two minutes — and ``diagnostics`` is
# serialized inline in the JSON result, so it is bounded. The cap is FIXED rather
# than an option: one more knob to reason about buys nothing an agent wants, and a
# stated constant is something a caller can rely on. The TAIL is kept, not the
# head: the interesting part of a run that did not finish is where it got to.
#
# The bound is in **UTF-8 bytes**, not characters, because bytes are what actually
# costs: a character cap of the same number let non-ASCII output through at up to
# 3-4x the intended size (16Ki CJK characters encode to ~48KiB), so a bound meant to
# keep a result payload small silently did not. Bytes also make the stated figure
# mean one thing to a reader measuring the JSON.
SCRIPT_OUTPUT_TAIL_CAP_BYTES = 16 * 1024


def _tail(stream: str) -> str:
    """The last :data:`SCRIPT_OUTPUT_TAIL_CAP_BYTES` UTF-8 bytes of a stream.

    Slicing bytes can land inside a multi-byte sequence, so the decode uses
    ``errors="ignore"`` to drop a leading partial character rather than emit a
    replacement character for it: the truncation is gda's own doing, and inventing a
    ``U+FFFD`` would misreport the engine's output as malformed. Only that boundary
    is affected — anything genuinely malformed was already replaced when the capture
    was decoded, and survives here as the replacement character it became.
    """
    encoded = stream.encode("utf-8")
    if len(encoded) <= SCRIPT_OUTPUT_TAIL_CAP_BYTES:
        return stream
    return encoded[-SCRIPT_OUTPUT_TAIL_CAP_BYTES:].decode("utf-8", errors="ignore")


def _ended_run_diagnostics(
    what: str, script_errors: str, stdout: str, stderr: str
) -> str:
    """The ``diagnostics`` prose shared by the two gda-ended ``script run`` verdicts.

    ADR-0004's ``GdaError.diagnostics`` is a free-form ``str``, so everything a
    failure reports about a run gda ended is PROSE: the recognized script errors,
    then both streams under the same fixed labels ``--- script stdout ---`` /
    ``--- script stderr ---`` that ``--strict`` already uses, so one consumer split
    reads every ``script run`` failure. Promoting the elapsed time, the termination
    phase and these error lines to structured envelope FIELDS would change the
    uniform failure ABI; **#687 owns that decision** and ADR-0031's amendment
    already records that this issue's envelope adopts its outcome. String
    diagnostics are the deliberate first step, not an oversight — do not add
    envelope fields here.

    ``what`` names the moment ("the timeout", "the abort") so the error block reads
    as a statement about this run. A run with no recognized errors says so
    explicitly: the ABSENCE is itself the diagnosis — a hang with a clean error
    stream is an unfinished run, not a broken script.
    """
    header = (
        f"gda: recognized script errors seen before {what}:\n{script_errors}"
        if script_errors
        else f"gda: no recognized script errors appeared before {what}\n"
    )
    return header + _labelled_script_output(_tail(stdout), _tail(stderr))


def script_run_timeout_failure(
    script: str,
    *,
    timeout: float,
    elapsed: float,
    phase: str,
    script_errors: str,
    stdout: str,
    stderr: str,
) -> Failure:
    """The ``launch_timeout`` verdict for a ``script run`` gda stopped waiting for (#655).

    The code is REUSED, not minted: the condition is exactly the one
    ``launch_timeout`` names — Godot launched and did not return before the timeout
    — and ADR-0031 already records this path under it. What changes is that the
    envelope now carries evidence instead of only announcing the wait. Dogfooding
    (GDA-DF-012) hit a run whose script error Godot had already PRINTED, discarded
    by a buffered capture that kept nothing; and (GDA-DF-032) a healthy suite that
    grew past the fixed ceiling, indistinguishable from a hang because the envelope
    reported neither how long it ran nor how far it got.

    So the message carries the three numbers a caller acts on — the ``--timeout``
    that was reached, the elapsed wall clock, and the termination ``phase`` — plus
    the stated output cap, and the diagnostics carry the captured tail. An agent
    reading only ``message`` can already tell "raise ``--timeout``" from "this run
    is stuck".
    """
    return make_failure(
        "launch_timeout",
        f"script run: {script} did not return before the --timeout of {timeout}s "
        f"(elapsed {elapsed:.2f}s, termination phase '{phase}'). The captured "
        f"output is in diagnostics, truncated to the last "
        f"{SCRIPT_OUTPUT_TAIL_CAP_BYTES} UTF-8 bytes (16 KiB) of each stream; raise "
        f"--timeout for a run that is merely slow, or declare "
        f"--completion-marker to end an aborted run early.",
        _ended_run_diagnostics("the timeout", script_errors, stdout, stderr),
    )


def script_run_aborted_failure(
    script: str,
    *,
    marker: str | None,
    timeout: float,
    elapsed: float,
    silence: float,
    phase: str,
    script_errors: str,
    stdout: str,
    stderr: str,
) -> Failure:
    """The ``script_aborted`` verdict for a run gda ended early (#655).

    The failure GDA-DF-012 actually describes: a script error aborted the run
    before its ``quit()``, the engine stayed alive, and gda waited out the full
    ceiling to report a timeout with nothing in it. The error was on stderr within
    a second. This verdict returns it in seconds instead.

    It is a DISTINCT registered code rather than a reused one, because none of the
    candidates names this condition. ``launch_timeout`` would be untrue — gda did
    not wait for the timeout, it decided not to. ``script_failed`` means "your
    script ran to completion and chose a non-zero status", is documented as never
    reported without ``--strict``, and an agent branches on it differently: there
    the remedy is to read an exit status, here it is to read an error the script
    never survived. ADR-0002 reuses a code when the CONDITION matches; this one
    does not.

    The message names why gda stopped rather than merely that it did: the marker
    the caller declared, the silence window that elapsed after the error, and the
    ``--timeout`` that was NOT reached — so the bound is legible as a bound and not
    mistaken for the ceiling.

    ``marker`` is typed optional only so this stays a report rather than a crash: the
    abort is unreachable without a declared marker, and naming the condition without
    quoting the string is a better answer to an impossible state than an assertion
    that would kill the command (and be stripped under ``-O``).
    """
    declared = (
        f"the --completion-marker {marker!r}"
        if marker is not None
        else "the declared completion marker"
    )
    return make_failure(
        "script_aborted",
        f"script run: {script} was ended after {elapsed:.2f}s — an error naming the "
        f"entry script appeared, {declared} did not, neither stream produced output "
        f"for {silence}s, and the process then consumed no measurable CPU over a "
        f"further {silence}s (so it was idle, not working quietly). "
        f"The --timeout of {timeout}s was not reached. The captured "
        f"output is in diagnostics, truncated to the last "
        f"{SCRIPT_OUTPUT_TAIL_CAP_BYTES} UTF-8 bytes (16 KiB) of each stream; "
        f"termination phase '{phase}'.",
        _ended_run_diagnostics("the abort", script_errors, stdout, stderr),
    )


def invalid_project_failure(reason: str) -> Failure:
    """The ``project_not_found`` failure for an explicit ``--project``/``$GDA_PROJECT``
    that is empty or is not a Godot project (#353).

    ``resolve_project_dir`` raises ``ValueError`` with a descriptive ``reason`` (the
    offending path, the missing ``project.godot``, or an empty value). Converting it
    to this structured envelope at the shared CLI dispatch layer — the single place
    project resolution happens (ADR-0006) — means *every* channel yields the
    structured ``project_not_found`` error instead of leaking the raise as a Rich/
    Python traceback. It is the general, cross-cutting form of ``script run``'s own
    projectless ABI edge (#343); the two share the one ``project_not_found`` code.
    """
    return make_failure("project_not_found", reason, "")
