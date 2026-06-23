"""ADR-0002 error-code registry drift checks."""

import re
from pathlib import Path

import pytest

from gda.error_codes import (
    ERROR_CODE_BY_CODE,
    ERROR_CODES,
    OPERATION_ERROR_CODES,
    ErrorCodeSource,
)
from gda.errors import _failure
from gda.exit_codes import EXIT_LIVE
from gda.models import ErrorCategory

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
)

ROOT = Path(__file__).resolve().parents[1]
ADR_0002 = ROOT / "docs" / "adr" / "0002-headless-structured-output-contract.md"
OPERATIONS_GD = ROOT / "src" / "gda" / "ops" / "operations.gd"
GDA_HARNESS_GD = ROOT / "src" / "gda" / "harness" / "gda_harness.gd"

ADR_REGISTRY_ROW = re.compile(r"^\| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \| `(\d+)` \|")
GDSCRIPT_OPERATION_CODE = re.compile(r'^const OP_ERROR_[A-Z_]+ := "([a-z_]+)"$', re.MULTILINE)
GDSCRIPT_HARNESS_LIVE_CODE = re.compile(
    r'^const LIVE_ERROR_[A-Z_]+ := "([a-z_]+)"$', re.MULTILINE
)
BARE_FAIL_CODE = re.compile(r'_fail\(\s*"[a-z_]+"')

# The per-operation LIVE failures the gda harness reports in-band (#220, #223, #221).
# The generic daemon-channel LIVE codes (daemon_not_running, …) are surfaced by the
# Python daemon client, NOT the harness, so they are not mirrored in GDScript.
HARNESS_LIVE_ERROR_CODES = (
    "live_node_not_found",
    "live_unknown_property",
    "live_uncoercible_value",
    "live_perf_node_not_found",
    "live_perf_property_not_found",
    "live_perf_signal_not_found",
    "live_invalid_key",
    "live_unknown_action",
    "live_invalid_event_spec",
)


def _adr_registry() -> dict[str, tuple[str, str, int]]:
    rows: dict[str, tuple[str, str, int]] = {}
    for line in ADR_0002.read_text(encoding="utf-8").splitlines():
        match = ADR_REGISTRY_ROW.match(line)
        if match:
            code, category, source, exit_code = match.groups()
            rows[code] = (category, source, int(exit_code))
    return rows


def _python_registry() -> dict[str, tuple[str, str, int]]:
    return {
        spec.code: (spec.category.value, spec.source.value, spec.exit_code)
        for spec in ERROR_CODES
    }


def test_python_error_registry_has_no_duplicate_codes():
    assert len(ERROR_CODES) == len(ERROR_CODE_BY_CODE)


def test_failure_derives_exit_code_from_registry():
    for spec in ERROR_CODES:
        failure = _failure(spec.code, "message", "")
        assert failure.exit_code == spec.exit_code
        assert failure.error.category is spec.category
        assert failure.error.code == spec.code


def test_failure_builder_rejects_unregistered_public_codes():
    with pytest.raises(RuntimeError, match="unregistered GdaError.code"):
        _failure(
            "not_registered",
            "message",
            "",
        )


def test_adr_registry_matches_python_authoritative_registry():
    assert _adr_registry() == _python_registry()


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
    r'^const MAX_WINDOW_FRAMES := (\d+)$', re.MULTILINE
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
