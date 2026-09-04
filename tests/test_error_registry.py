"""ADR-0002 error-code registry drift checks."""

import ast
import json
import re
from pathlib import Path
from typing import NamedTuple

import pytest

from gda.error_codes import (
    ERROR_CODE_BY_CODE,
    ERROR_CODES,
    OPERATION_ERROR_CODES,
    ErrorCodeSource,
)
import gda.errors as errors_module
from gda.errors import make_failure
from gda.exit_codes import EXIT_LIVE
from gda.models import ErrorCategory, GdaErrorEnvelope, TerminationPhase
from gda.runner import LaunchFailure, RunResult

# The live execution channel's failure codes (ADR-0017 / ADR-0021). Registered
# here as the first Phase-2 slice's error contract; emitted by the daemon IPC
# client and the daemon as the live capability lands.
LIVE_ERROR_CODES = (
    "daemon_not_running",
    "engine_session_not_running",
    "engine_disconnected",
    "live_timeout",
    # The harness-lifecycle refusal (#225): `daemon uninstall` is refused while a
    # daemon is running. Same shape as the other daemon-channel LIVE codes —
    # LIVE-category, classifier-source (the uninstall recipe emits it), exit 6,
    # NOT GDScript-mirrored.
    "daemon_running",
    # The session-scene-selection failure (#278): `daemon start --scene <bad>`
    # surfaces a typed not-found rather than silently running main_scene. The
    # harness verifies the ACTUALLY-LOADED scene against the requested selector at
    # launch; a mismatch is surfaced by the daemon as this daemon-channel
    # classifier-source LIVE code, NOT GDScript-mirrored.
    "live_scene_not_found",
    # The nothing-to-run refusal (#829): an empty `application/run/main_scene`
    # with no `--scene` selector is refused before any engine is spawned, at the
    # `daemon start` fail-fast and at the daemon's launch boundary — Godot would
    # otherwise block on a native alert (macOS, even headless). Classifier-source
    # (both sites mint it from the project file), NOT GDScript-mirrored.
    "live_main_scene_undefined",
    # The already-running + `--scene` refusal (#278 review): `--scene` only takes
    # effect at daemon start, so requesting it against a daemon that is already
    # running is a typed refusal rather than a silent no-op. Classifier-source (the
    # start recipe emits it), NOT GDScript-mirrored.
    "daemon_already_running",
)

ROOT = Path(__file__).resolve().parents[1]
ADR_0002 = ROOT / "docs" / "adr" / "0002-headless-structured-output-contract.md"
OPERATIONS_GD = ROOT / "src" / "gda" / "ops" / "operations.gd"
GDA_HARNESS_GD = ROOT / "src" / "gda" / "harness" / "gda_harness.gd"

ADR_REGISTRY_ROW = re.compile(
    r"^\| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \| `(\d+)` \| (.+?) \|$"
)
GDSCRIPT_OPERATION_CODE = re.compile(
    r'^const OP_ERROR_[A-Z_]+ := "([a-z_]+)"$', re.MULTILINE
)
GDSCRIPT_HARNESS_LIVE_CODE = re.compile(
    r'^const LIVE_ERROR_[A-Z_]+ := "([a-z_]+)"$', re.MULTILINE
)
BARE_FAIL_CODE = re.compile(r'_fail\(\s*"[a-z_]+"')

# The per-operation LIVE failures the gda harness reports in-band (#220, #223, #221).
# The generic daemon-channel LIVE codes (daemon_not_running, …) are surfaced by the
# Python daemon client, NOT the harness, so they are not mirrored in GDScript.
HARNESS_LIVE_ERROR_CODES = (
    "live_node_not_found",
    "live_not_control",
    "live_unknown_property",
    "live_uncoercible_value",
    "live_perf_node_not_found",
    "live_perf_property_not_found",
    "live_perf_signal_not_found",
    "live_invalid_key",
    "live_unknown_action",
    "live_invalid_event_spec",
    # #222: a `screen` capture op on a headless engine session — the dummy
    # DisplayServer cannot read pixels (the session was not started --windowed).
    "live_display_unavailable",
    # #661: a `screen capture --await-*` predicate that never held within its
    # declared frame bound.
    "live_predicate_unmet",
    # #673: the `game call` allowlist's three distinguishable refusals — a
    # method the node does not have, one it has but never declared callable,
    # and an argument count outside the declared method's range.
    "live_unknown_method",
    "live_method_not_allowlisted",
    "live_invalid_call_args",
)


# --- How a code's DESCRIPTION is compared across the two artifacts (#701) -----
#
# ADR-0002's table and `gda.error_codes` carry the same per-code description, and
# the equality pin below compares it. Two normalizations run first. Both are
# decisions with a stated reason, because a rule buried in a regex is a rule the
# next reader cannot tell from a bug. Counts below are a 2026-08-28 snapshot, not
# a contract — only the pin itself is asserted.
#
# 1. **Markdown prose vs a Python string.** The ADR cell is Markdown (`code
#    spans`, one long line); the registry is an implicitly-concatenated,
#    formatter-wrapped string. Backticks are dropped, whitespace runs collapse to
#    one space, and a trailing period is ignored — so a reflow or a code-span
#    added on one side is never a failure. Every other character must match.
#
# 2. **A citation is not part of a code's meaning.** 41 of the ADR's 91 rows end
#    with a parenthetical citing the decision or issue that put the row in the
#    contract: `(Phase 2, ADR-0017 / ADR-0021)`, `(ADR-0033, #363)`, `(#170)`.
#    Saying which decision added a row is the ADR's job as a decision record; the
#    registry's `description` is the code's MEANING — the sentence a caller reads
#    next to the code, where an unresolvable issue number is noise. So a trailing
#    parenthetical is stripped and not compared when it CITES at least one ADR or
#    issue and contains nothing but citation tokens. It is stripped on BOTH sides,
#    not just the ADR's: the two artifacts cite for different readers, and 5
#    registry descriptions carry one too (`usage_error`, `invalid_params`,
#    `ambiguous_class_name`, `script_failed`, `script_aborted` — each a pointer to
#    the ADR that governs it, worth keeping where it is).
#    Rejected alternative: have the registry adopt the ADR's refs. That copies 41
#    references an agent cannot resolve into the public code descriptions and makes
#    appending an issue number a standing obligation for every new code.
#
#    **Why a reference is REQUIRED, not merely allowed** (#755 review): a bare
#    `(Phase N)` is domain content, not a citation — CONTEXT.md defines Phase 1 /
#    Phase 2 as the order capabilities are delivered in. An earlier form of this
#    rule stripped any parenthetical built from the token set, so `(Phase 2)` and
#    `(Phase 1)` normalized alike and a mislabelled row would have passed the pin
#    silently — the exact drift class #701 exists to catch. A `Phase N` may still
#    ride INSIDE a citation cluster, because dropping it from the token set would
#    unstrip `(Phase 2, ADR-0017 / ADR-0021)` and turn a third of the cited rows
#    into false divergences.
#
#    Residual, stated exactly: a `Phase N` riding inside a citation cluster is
#    stripped with it and so is not compared. For 20 of the 23 rows carrying a
#    phase label the compared `Category` column pins the distinction indirectly —
#    `live` exists only in Phase 2 (ADR-0021) — but the other three are
#    ENVIRONMENT-category (`live_unsupported_platform`, `live_windowed_unavailable`,
#    `live_windowed_permission_denied`), so for those a phase mislabel inside a
#    citation cluster is caught by neither mechanism. Left that way deliberately:
#    three docs-only rows in a field with no runtime consumer do not justify the
#    27 rows of churn that closing the riding case would cost.
#
# The rule is deliberately narrow. A parenthetical that MIXES prose with a ref is
# not a citation and is compared verbatim, so content can never hide behind the
# rule. #701 found exactly that: `(pack needs no platform templates and is
# exempt; #170)` — a real exemption the registry had lost. It was reconciled into
# both artifacts, not normalized away.
#
# A new citation form (a date, a PR link) will fail this pin rather than being
# silently accepted. That is intended: widening the token set is a conscious edit.
CITATION_REF = r"(?:ADR-\d{4}(?: amendment)?|#\d+)"
CITATION_TOKEN = rf"(?:Phase \d+|{CITATION_REF})"
TRAILING_CITATION = re.compile(
    # The lookahead is the "at least one ADR or issue reference" requirement.
    rf"\s*\((?=[^()]*{CITATION_REF})"
    rf"{CITATION_TOKEN}(?:\s*[,/]\s*{CITATION_TOKEN})*\)\.?\s*$"
)


def _normalized_description(text: str) -> str:
    """The comparable part of a description — see the rule above."""
    flattened = " ".join(text.replace("`", "").split()).rstrip(". ")
    return TRAILING_CITATION.sub("", flattened).rstrip(". ")


class ErrorRow(NamedTuple):
    """One code's full public shape, as both artifacts must state it."""

    category: str
    source: str
    exit_code: int
    description: str


def _adr_registry() -> dict[str, ErrorRow]:
    rows: dict[str, ErrorRow] = {}
    for line in ADR_0002.read_text(encoding="utf-8").splitlines():
        match = ADR_REGISTRY_ROW.match(line)
        if match:
            code, category, source, exit_code, description = match.groups()
            rows[code] = ErrorRow(
                category, source, int(exit_code), _normalized_description(description)
            )
    return rows


def _python_registry() -> dict[str, ErrorRow]:
    return {
        spec.code: ErrorRow(
            spec.category.value,
            spec.source.value,
            spec.exit_code,
            _normalized_description(spec.description),
        )
        for spec in ERROR_CODES
    }


def test_python_error_registry_has_no_duplicate_codes():
    assert len(ERROR_CODES) == len(ERROR_CODE_BY_CODE)


def test_failure_derives_exit_code_from_registry():
    for spec in ERROR_CODES:
        failure = make_failure(spec.code, "message", "")
        assert failure.exit_code == spec.exit_code
        assert failure.error.category is spec.category
        assert failure.error.code == spec.code


def test_no_registered_code_grows_a_key_by_defaulting_the_optional_context():
    # The scope-defining regression for the ADR-0004 amendments (#667 `probe`, #670
    # `hint`, #687 `evidence`): each added an OPTIONAL key to the ONE shared failure
    # envelope, and the whole additive argument rests on a failure that sets none
    # emitting the same four keys it emitted before. Measured across the ENTIRE
    # registry rather than sampled, because that is the population the claim is about
    # — a fifth key defaulted to `{}` or `""` instead of `None` would pass any
    # single-code check and silently change every envelope gda emits.
    for spec in ERROR_CODES:
        emitted = json.loads(
            GdaErrorEnvelope(
                error=make_failure(spec.code, "message", "").error
            ).model_dump_json(exclude_none=True)
        )
        assert set(emitted["error"]) == {
            "category",
            "code",
            "message",
            "diagnostics",
        }, spec.code


#: The failure builders #687 admits to the evidence axis — the decision's recorded
#: boundary, mirrored from ADR-0004's `Amendment (2026-08-31, #687)`. The tree still
#: holds discards this decision did NOT adopt (`scene preflight`'s
#: `_ended_before_the_verdict`, `engine_crashed`'s signal, `resource import`'s and
#: `export run`'s child exit codes); the amendment records them as deliberately out of
#: scope, and this set is what lets a later reader tell that from an oversight.
#:
#: The last two arrive with #697/#763 and are the axis's first NON-run producers: the
#: two `target_outside_project` refusals report a project-context mismatch gda decides
#: before anything is launched, so their coordinates are the whole cause rather than a
#: run's residue. ADR-0004's paragraph carries the same two names.
_EVIDENCE_PRODUCERS = {
    "launch_timeout_failure",
    "script_did_not_run_failure",
    "script_exit_status_failure",
    "script_run_timeout_failure",
    "script_run_aborted_failure",
    "target_outside_project_failure",
    "target_owned_by_another_project_failure",
}


def test_only_the_recorded_producers_put_evidence_on_the_envelope():
    # A criterion in prose is not a boundary anyone can check (#687 review). Read out
    # of the source rather than kept by hand, so a sixth builder cannot join the axis
    # without this test — and the ADR paragraph it mirrors — being updated in the same
    # change. `make_failure` itself is excluded by construction: this looks only at
    # CALLS to it, and it is the one that forwards the parameter.
    module = ast.parse(Path(errors_module.__file__).read_text(encoding="utf-8"))

    producers = {
        node.name
        for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "make_failure"
            and any(keyword.arg == "evidence" for keyword in call.keywords)
            for call in ast.walk(node)
        )
    }

    assert producers == _EVIDENCE_PRODUCERS


def test_no_producer_can_emit_an_empty_evidence_object():
    # The fourth state the amendment's argument does not cover: `FailureEvidence()`
    # with every field unset serializes to `"evidence": {}` — a key that says nothing,
    # on a failure that byte-identity says should carry no key at all. Unreachable
    # through the five producers today, but only incidentally, so it is pinned rather
    # than assumed. Each producer is called with the LEAST it can be given.
    raw = RunResult(
        stdout="", stderr="", exit_code=124, launch_failure=LaunchFailure.TIMEOUT
    )
    emitted = [
        errors_module.launch_timeout_failure(raw),
        errors_module.script_did_not_run_failure(
            "script_not_found", "res://t.gd", "detail", "", []
        ),
        errors_module.script_exit_status_failure("res://t.gd", 3, "", "", []),
        errors_module.script_run_timeout_failure(
            "res://t.gd",
            timeout=1.0,
            elapsed=1.0,
            phase=TerminationPhase.LAUNCHED,
            script_errors=[],
            stdout="",
            stderr="",
        ),
        errors_module.script_run_aborted_failure(
            "res://t.gd",
            timeout=1.0,
            elapsed=1.0,
            silence=1.0,
            marker="done",
            phase=TerminationPhase.ABORTED_ON_ERROR,
            script_errors=[],
            stdout="",
            stderr="",
        ),
    ]

    for failure in emitted:
        evidence = json.loads(
            GdaErrorEnvelope(error=failure.error).model_dump_json(exclude_none=True)
        )["error"]["evidence"]
        assert evidence != {}, failure.error.code


def test_failure_builder_rejects_unregistered_public_codes():
    with pytest.raises(RuntimeError, match="unregistered GdaError.code"):
        make_failure(
            "not_registered",
            "message",
            "",
        )


def test_adr_registry_matches_python_authoritative_registry():
    # Every column of a code's public shape, the `Meaning` prose included (#701).
    # The description used to be parsed out of the ADR row and thrown away, so the
    # two artifacts could describe the same code differently and nothing noticed —
    # wave 2 shipped three PRs whose description edits had to be checked by eye,
    # and 15 rows had already drifted apart in substance (a producing condition the
    # registry omitted, an exemption it had lost, a remedy it stated incompletely).
    # Comparison rule: see `_normalized_description` above.
    assert _adr_registry() == _python_registry()


def test_description_normalization_ignores_only_citations():
    # Pins the boundary of the rule stated above, so widening it stays a conscious
    # edit rather than a side effect of a regex tweak.
    #
    # Ignored: markup, wrapping, a trailing period, and a trailing parenthetical
    # that cites an ADR or issue and holds nothing else.
    assert _normalized_description("A `code` span.") == "A code span"
    assert _normalized_description("Wrapped\n  text") == "Wrapped text"
    assert _normalized_description("Meaning (Phase 2, ADR-0017 / ADR-0021).") == (
        _normalized_description("Meaning.")
    )
    assert _normalized_description("Meaning (ADR-0031 amendment, #655).") == "Meaning"
    # NOT ignored: a parenthetical carrying prose, even when a ref rides along —
    # that is content, and dropping it is how a real divergence would hide.
    assert _normalized_description("Meaning (pack is exempt; #170).") == (
        "Meaning (pack is exempt; #170)"
    )
    # NOT ignored: a citation-looking parenthetical mid-sentence.
    assert _normalized_description("Meaning (#170) and more.") == (
        "Meaning (#170) and more"
    )


def test_a_bare_phase_label_is_compared_not_stripped():
    # #755 review: `Phase N` is domain content (CONTEXT.md — the order capabilities
    # are delivered in), so a parenthetical holding ONLY a phase label is not a
    # citation and must survive normalization. Before the fix both sides normalized
    # to the same string and a row mislabelled Phase 1 passed the pin silently.
    assert _normalized_description("Meaning (Phase 2).") == "Meaning (Phase 2)"
    assert _normalized_description("Meaning (Phase 2).") != (
        _normalized_description("Meaning (Phase 1).")
    )
    # The other direction, which is why `Phase \d+` stays in the token set: a phase
    # label riding inside a real citation is stripped with it. Removing the token
    # would unstrip these and turn a third of the cited rows into false
    # divergences.
    assert _normalized_description("Meaning (Phase 2, #220).") == "Meaning"
    assert _normalized_description("Meaning (Phase 2, ADR-0021).") == "Meaning"


def test_gdscript_operation_error_codes_mirror_python_operation_subset():
    gdscript = OPERATIONS_GD.read_text(encoding="utf-8")
    mirrored_codes = set(GDSCRIPT_OPERATION_CODE.findall(gdscript))

    python_operation_codes = {
        spec.code for spec in ERROR_CODES if spec.source is ErrorCodeSource.OPERATION
    }

    assert mirrored_codes == python_operation_codes
    assert mirrored_codes == set(OPERATION_ERROR_CODES)


def test_gdscript_fail_calls_do_not_use_literal_error_codes():
    gdscript = OPERATIONS_GD.read_text(encoding="utf-8")

    assert not BARE_FAIL_CODE.search(gdscript)


def test_live_failures_are_registered_classifier_live_codes():
    # A live operation's failure is a classifier-source LIVE code (ADR-0017 /
    # ADR-0021): the new LIVE category, the shared EXIT_LIVE exit, and — because
    # no headless operation reports it — NOT GDScript-mirrored (the mirror subset
    # below stays the operation-source set, so the drift test is unaffected).
    for code in LIVE_ERROR_CODES:
        spec = ERROR_CODE_BY_CODE[code]
        assert spec.category is ErrorCategory.LIVE
        assert spec.source is ErrorCodeSource.CLASSIFIER
        assert spec.exit_code == EXIT_LIVE
        assert spec.code not in OPERATION_ERROR_CODES


def test_live_windowed_unavailable_flows_through_classify_live():
    # #345 finding 1: live_windowed_unavailable is raised at the daemon's
    # session-launch boundary and relayed as a LIVE reply, so classify_live must
    # surface it — it is whitelisted in _LIVE_CLIENT_CODES alongside
    # live_unsupported_platform (both ENVIRONMENT-category codes arriving via the live
    # path). Without the whitelist, classify_run would misroute it to operation_failed.
    from gda.daemon.protocol import error_reply
    from gda.errors import _LIVE_CLIENT_CODES, Failure, classify_live
    from gda.commands.game import GameTreeResult
    from gda.runner import RunResult

    assert "live_windowed_unavailable" in _LIVE_CLIENT_CODES

    reply = error_reply(
        "live_windowed_unavailable", "no usable DisplayServer", diagnostics="why-here"
    )
    outcome = classify_live(RunResult(**reply), None, GameTreeResult)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "live_windowed_unavailable"
    # It resolves to its REGISTERED environment/127 shape (not the EXIT_LIVE the wire
    # reply carried, nor an operation_failed fallback).
    assert outcome.error.category is ErrorCategory.ENVIRONMENT
    assert outcome.exit_code == 127
    assert outcome.error.diagnostics == "why-here"


def test_live_windowed_permission_denied_flows_through_classify_live():
    # #667: the sandbox-denial sibling is raised at the same daemon launch boundary
    # and relayed the same way, so it needs the same whitelist entry — without it
    # classify_run would misroute an ENVIRONMENT code to operation_failed. It
    # resolves to its own registered environment/127 shape, distinct from
    # live_windowed_unavailable, so an agent can tell "retry outside the sandbox"
    # from "this host cannot show a window".
    from gda.daemon.protocol import error_reply
    from gda.errors import _LIVE_CLIENT_CODES, Failure, classify_live
    from gda.commands.game import GameTreeResult
    from gda.runner import RunResult

    assert "live_windowed_permission_denied" in _LIVE_CLIENT_CODES

    reply = error_reply(
        "live_windowed_permission_denied",
        "denied the window-server lookup",
        diagnostics="why-here",
    )
    outcome = classify_live(RunResult(**reply), None, GameTreeResult)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "live_windowed_permission_denied"
    assert outcome.error.category is ErrorCategory.ENVIRONMENT
    assert outcome.exit_code == 127
    assert outcome.error.diagnostics == "why-here"
    # No probe was put on this reply, so none comes out — the key is optional.
    assert outcome.error.probe is None


def test_a_relayed_windowed_refusal_carries_probe_to_the_public_json():
    # #667 review: the AUTHORITATIVE refusal is the daemon's lazy-launch guard, so the
    # probe context must survive the whole daemon-reply -> live-classifier -> public
    # envelope path, not just the CLI fail-fast. Walks that path end to end with the
    # REAL builders and the REAL emit serialization at both ends.
    import json

    from gda.daemon.protocol import error_reply
    from gda.errors import Failure, classify_live
    from gda.commands.game import GameTreeResult
    from gda.models import EnvironmentProbe, GdaErrorEnvelope
    from gda.runner import RunResult

    probe = EnvironmentProbe(
        name="bootstrap_look_up(com.apple.windowserver.active)", platform="darwin"
    )
    reply = error_reply(
        "live_windowed_permission_denied",
        "a windowed engine session cannot launch: denied",
        diagnostics="why-here",
        probe=probe,
    )

    outcome = classify_live(RunResult(**reply), None, GameTreeResult)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "live_windowed_permission_denied"
    assert outcome.error.category is ErrorCategory.ENVIRONMENT
    assert outcome.exit_code == 127
    assert outcome.error.probe is not None
    assert outcome.error.probe.name == (
        "bootstrap_look_up(com.apple.windowserver.active)"
    )
    assert outcome.error.probe.platform == "darwin"
    # And it survives to the public JSON an agent actually reads.
    emitted = json.loads(
        GdaErrorEnvelope(error=outcome.error).model_dump_json(exclude_none=True)
    )
    assert emitted["error"]["probe"] == {
        "name": "bootstrap_look_up(com.apple.windowserver.active)",
        "platform": "darwin",
    }


def test_harness_live_error_codes_are_registered_live_codes():
    # The per-op LIVE failures the gda harness reports (#220) are registered
    # LIVE-category classifier-source codes: because their category is LIVE,
    # ``LIVE_ERROR_CODES`` (and so ``classify_live``) maps them with no errors.py
    # change — the keystone routing that keeps a harness exit-0 op error off the
    # ``contract_violation`` fallthrough.
    for code in HARNESS_LIVE_ERROR_CODES:
        spec = ERROR_CODE_BY_CODE[code]
        assert spec.category is ErrorCategory.LIVE
        assert spec.source is ErrorCodeSource.CLASSIFIER
        assert spec.exit_code == EXIT_LIVE


def test_gdscript_harness_live_error_codes_mirror_python_harness_subset():
    # The harness mints the per-op LIVE codes itself, so each must have a matching
    # ``const LIVE_ERROR_* := "..."`` in gda_harness.gd. This is the harness twin
    # of the operations.gd OP_ERROR mirror, kept separate so the operations.gd
    # mirror test stays the operation-source set (the OP_ERROR drift test is
    # unaffected). The generic daemon-channel LIVE codes are NOT harness-mirrored.
    harness = GDA_HARNESS_GD.read_text(encoding="utf-8")
    mirrored_codes = set(GDSCRIPT_HARNESS_LIVE_CODE.findall(harness))

    assert mirrored_codes == set(HARNESS_LIVE_ERROR_CODES)
    for code in mirrored_codes:
        spec = ERROR_CODE_BY_CODE[code]
        assert spec.category is ErrorCategory.LIVE


HARNESS_MAX_WINDOW_FRAMES = re.compile(
    r"^const MAX_WINDOW_FRAMES := (\d+)$", re.MULTILINE
)


def test_max_window_frames_mirrors_the_harness_const():
    # The time-windowed frame ceiling is bounded model-side (PerfMonitorParams,
    # ADR-0015) by gda.models.MAX_WINDOW_FRAMES, mirroring the harness's
    # MAX_WINDOW_FRAMES const so the model rejects exactly what the harness would
    # otherwise have to defend against. Keep the two in sync.
    from gda.models import MAX_WINDOW_FRAMES

    harness = GDA_HARNESS_GD.read_text(encoding="utf-8")
    match = HARNESS_MAX_WINDOW_FRAMES.search(harness)
    assert match is not None, "MAX_WINDOW_FRAMES const missing from gda_harness.gd"
    assert int(match.group(1)) == MAX_WINDOW_FRAMES


# The harness's `_perf_monitors` table keys: every `"name": Performance.X,` row
# inside the dict literal assigned in _ready. The names are gda-owned constants
# (not engine-queried), so the CLI mirrors them (gda.commands.perf
# PERF_MONITOR_NAMES) to validate `perf sample --monitor` model-side (ADR-0015).
HARNESS_PERF_MONITOR_TABLE = re.compile(r"_perf_monitors = \{(.*?)\}", re.DOTALL)
HARNESS_PERF_MONITOR_NAME = re.compile(r'"([a-z0-9_]+)": Performance\.')


def test_perf_monitor_names_mirror_the_harness_table():
    # `perf sample --monitor` is bounded model-side by PERF_MONITOR_NAMES,
    # mirroring the harness's `_perf_monitors` table so an unknown name is a
    # usage/invalid_params error before it costs a live round trip — and so a
    # monitor added harness-side cannot silently stay unreachable from the CLI.
    from gda.commands.perf import PERF_MONITOR_NAMES

    harness = GDA_HARNESS_GD.read_text(encoding="utf-8")
    table = HARNESS_PERF_MONITOR_TABLE.search(harness)
    assert table is not None, "_perf_monitors table missing from gda_harness.gd"
    harness_names = HARNESS_PERF_MONITOR_NAME.findall(table.group(1))
    assert harness_names, "no monitor rows parsed from the _perf_monitors table"
    assert list(PERF_MONITOR_NAMES) == harness_names


HARNESS_LOG_MARKER = re.compile(r'^const LOG_MARKER := "(.*)"$', re.MULTILINE)


def test_log_marker_mirrors_the_harness_const():
    # The opt-in `gda_log()` protocol (#282, ADR-0026) emits a `<<<GDA:LOG>>>`
    # sentinel; the harness mints it (LOG_MARKER) and the Python parser recognises
    # it (gda.daemon.diag.LOG_BEGIN). Keep the two byte-identical so a real harness
    # line is always recognised by the parser.
    from gda.daemon.diag import LOG_BEGIN

    harness = GDA_HARNESS_GD.read_text(encoding="utf-8")
    match = HARNESS_LOG_MARKER.search(harness)
    assert match is not None, "LOG_MARKER const missing from gda_harness.gd"
    assert match.group(1) == LOG_BEGIN


def test_log_marker_is_distinct_from_the_result_sentinel():
    # ADR-0026: the `<<<GDA:LOG>>>` marker is a separate marker family from
    # ADR-0002's single `<<<GDA:RESULT>>>`, so a log line can never be mistaken for
    # an op result (and vice versa).
    from gda.daemon.diag import LOG_BEGIN
    from gda.parser import RESULT_BEGIN, RESULT_END

    assert LOG_BEGIN != RESULT_BEGIN
    assert LOG_BEGIN != RESULT_END
    assert RESULT_BEGIN not in LOG_BEGIN
    assert LOG_BEGIN not in RESULT_BEGIN
