"""Failure classification for headless operations (issues #3, #14).

This is the single home of ``gda``'s failure classification, split into two layers
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
  hung past the timeout; the envelope carries the captured partial output, the
  ceiling it reached and the elapsed wall clock, #714)
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

import re
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from gda.core.engine.binary import resolve_godot_binary
from gda.core.engine.engine_log import parse_errors
from gda.core.failure.catalog import (
    Failure,
    M,
    _is_too_deep,
    launch_timeout_failure,
    make_failure,
    unresolvable_binary_failure,
)
from gda.core.failure.error_codes import LIVE_ERROR_CODES, OPERATION_ERROR_CODES
from gda.core.project.import_evidence import CACHE_ROOT_REL, CLASS_INDEX_FILE
from gda.core.contract.envelope import (
    FailureEvidence,
    LiveErrorEnvelope,
    OperationErrorEnvelope,
)
from gda.core.engine.sentinel import parse_result
from gda.core.engine.launch import LaunchFailure, RunResult


# The minimum supported Godot version (ADR-0003): the floor where the modern
# features gda relies on exist. Resolved from the version gda info reports; the
# gate that applies it is ``info``'s own classifier, in ``gda.commands.meta``.
MIN_GODOT_VERSION = (4, 4)


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


def resolve_godot_binary_or_failure(godot: str | None) -> Path | Failure:
    """Resolve the Godot binary, or return the ``binary_not_found`` failure (#1012).

    The one resolution step for every caller that takes a ``--godot`` value.
    :func:`gda.core.engine.binary.resolve_godot_binary` keeps its raising contract, and this
    step is the one place that catches its ``ValueError``, so a caller makes one
    call instead of copying a try/except. Each caller calls it at its own
    resolution point, so a path that resolves no binary (a dry run, a live op)
    is never refused.
    """
    try:
        return resolve_godot_binary(godot)
    except ValueError as exc:
        return unresolvable_binary_failure(str(exc))


def classify_launch_or_crash(raw: RunResult, binary: Path | None) -> Failure | None:
    """The env/crash classifier prefix shared by the headless channels (#185).

    The single home of the launch-failure and signal-death mapping that the
    sentinel channel (``classify_run``), the native-export channel
    (``classify_export_run``) and the import-pass step (``gda.import_pass``, the
    one pass ``resource import`` and ``project scan`` run) all open with, so a
    missing binary, a hung run, or a signal death is classified identically across
    every one of them (ADR-0010 — reuse the machinery rather than duplicate it).
    Returns the env/crash ``Failure`` for the three modes below, or ``None`` to let
    the caller's channel-specific tail (sentinel parse+validate vs
    synthesize-from-exit-code) take over.

    Being the single home is what makes the timeout evidence a property of every
    channel rather than of whichever one was fixed last: the hung-run branch is
    written ONCE, so all three report the same envelope (#714).

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
        return launch_timeout_failure(raw)
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


#: The four sentences the GDScript analyzer (4.6.3, ``gdscript_analyzer.cpp``) reports
#: when it cannot resolve a name as a global class. Each is matched with both
#: boundaries of the quoted name — the engine's fixed text before it and after it —
#: so the name itself is read, not guessed from an alphabet. Two variants of the
#: first sentence are left out on purpose: ``Could not find type "B" under base "A"``
#: and ``Could not find type "B" in "A"`` name a member of a type that DID resolve,
#: and no scan supplies a member. A sentence is read only as the WHOLE message of a
#: ``SCRIPT ERROR: Parse Error: …`` record — the form ``GDScript::reload`` prints a
#: compile error in (``gdscript.cpp``) — so a line a script printed, or a project's
#: own ``push_error`` that quotes one, is not compiler evidence.
_PARSE_ERROR_PREFIX = "Parse Error: "
_UNRESOLVED_CLASS = re.compile(
    r'Could not find type "(?P<type>[^"\n]+)" in the current scope\.'
    r'|Could not find base class "(?P<base>[^"\n]+)"\.'
    r'|Could not parse global class "(?P<parsed>[^"\n]+)" from "[^"\n]*"\.'
    r'|Could not resolve super class "(?P<super>[^"\n]+)"\.'
)


def unresolved_class_names(output: str) -> list[str]:
    """The class names the engine reported it could not resolve, first seen first."""
    names: dict[str, None] = {}
    for record in parse_errors(output):
        message = record["message"]
        if record["level"] != "script_error" or not message.startswith(
            _PARSE_ERROR_PREFIX
        ):
            continue
        match = _UNRESOLVED_CLASS.fullmatch(message[len(_PARSE_ERROR_PREFIX) :])
        if match is not None:
            name = next(group for group in match.groups() if group is not None)
            names.setdefault(name, None)
    return list(names)


def _class_resolution_sentence(names: Sequence[str], *, index_absent: bool) -> str:
    """The remedy sentence for ``names``, absolute or conditional (#1073).

    A scan does not settle every name: a ``class_name`` script that does not
    compile is still in the index after it (the engine then reports ``Could not
    parse global class``), so a name that still fails after a scan points at its
    declaration or its script, not only at a missing ``class_name``.
    """
    listed = ", ".join(names)
    one = len(names) == 1
    after = (
        f"if {listed} still fails after a scan, check its class_name declaration "
        "and that its script compiles"
        if one
        else "if one of them still fails after a scan, check its class_name "
        "declaration and that its script compiles"
    )
    if index_absent:
        return (
            f"the engine could not resolve {listed}, and the class index "
            f"res://{CACHE_ROOT_REL}/{CLASS_INDEX_FILE} does not exist: run "
            f"`gda project scan` and retry; {after}"
        )
    subject = f"{listed} is a class_name" if one else "they are class_names"
    return (
        f"the engine could not resolve {listed}: if {subject} in this project, "
        f"run `gda project scan` and retry; {after}"
    )


def class_resolution_remedy(failure: Failure, project: Path) -> Failure:
    """Add the `gda project scan` remedy to a failure the class index can explain.

    The ONE CLI-side seam of #1073. The engine's GDScript analyzer finds a project
    ``class_name`` only through the class index, which only the editor filesystem
    scan writes. So on a project the editor never opened — or after a class was
    added or renamed — an op fails with its own code (``unknown_property``,
    ``script_compile_failed``, ``uninstantiable_script``, …) and a message that does
    not point at the cause. This reads the engine's own class-resolution errors in
    the run's captured output and adds ONE fact gda can state exactly: whether the
    index file is absent under the cache root.

    * Absent: the message states that the index file does not exist, and the
      remedy is plain — run `gda project scan` and retry.
    * Present: the name can be a typo as much as a class the index misses, so the
      remedy is conditional on the name being a ``class_name`` in this project.

    Either way, a name that still fails after a scan sends the caller to its
    ``class_name`` declaration and its script: a script that does not compile keeps
    its index entry, so a scan does not prove the name is not a class here.

    The code stays the verdict, and the remedy is not a ``hint``: a hint is the
    invocation to run INSTEAD, while a scan is a step before the SAME invocation.
    The names ride ``evidence.unresolved_classes``, merged into whatever evidence
    the failure already carried. A failure with no such error comes back unchanged.

    Which channels may call it is the caller's decision, and the one caller states
    it: :func:`gda.dispatch.dispatch_command`, on the channels whose engine reads
    the index WITHOUT running the import pass (``project scan``, ``resource
    import`` and ``export run`` run the pass, and after it a class-resolution error
    is a real source error). The index is looked for at the engine's DEFAULT data
    directory only; a project that sets
    ``application/config/use_hidden_project_data_directory=false`` keeps it under
    ``godot/`` and reads as absent here.
    """
    error = failure.error
    names = unresolved_class_names(f"{failure.child_stderr}\n{error.diagnostics}")
    if not names:
        return failure
    index = project / CACHE_ROOT_REL / CLASS_INDEX_FILE
    sentence = _class_resolution_sentence(names, index_absent=not index.is_file())
    evidence = (
        FailureEvidence(unresolved_classes=names)
        if error.evidence is None
        else error.evidence.model_copy(update={"unresolved_classes": names})
    )
    remedied = make_failure(
        error.code,
        f"{error.message.rstrip('.')}; {sentence}",
        error.diagnostics,
        probe=error.probe,
        hint=error.hint,
        evidence=evidence,
    )
    remedied.child_stderr = failure.child_stderr
    return remedied
