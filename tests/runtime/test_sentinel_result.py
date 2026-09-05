"""The ADR-0002 sentinel result builders and the daemon reply builders (#260).

These pin the behavior-preserving consolidation: ``gda.parser.build_result`` is the
write-twin of ``parse_result`` (round-trips), ``error_envelope`` is the one error
payload shape, and ``gda.daemon.protocol.result_reply`` / ``error_reply`` produce the
exact reply dicts the four hand-rolled copies used to build. The asserted strings are
literal so a drift in the emitted bytes is caught here, not only end-to-end.
"""

import json

import pytest

from gda.daemon.protocol import error_reply, result_reply
from gda.exit_codes import EXIT_LIVE
from gda.parser import (
    RESULT_BEGIN,
    RESULT_END,
    build_result,
    error_envelope,
    parse_result,
)


def test_build_result_wraps_payload_in_the_sentinel_with_trailing_newline():
    payload = {"value": 42, "name": "Player"}
    # Byte-identical to the f-string every emitter used before this was shared.
    assert build_result(payload) == f"{RESULT_BEGIN}{json.dumps(payload)}{RESULT_END}\n"


def test_build_result_round_trips_through_parse_result():
    # The write side is the exact inverse of the read side.
    for payload in (
        {},
        {"a": 1},
        {"error": {"code": "x", "message": "m"}},
        {"l": [1, 2]},
    ):
        assert parse_result(build_result(payload)) == payload


def test_error_envelope_is_the_operation_error_payload_shape():
    assert error_envelope("node_not_found", "no such node") == {
        "error": {"code": "node_not_found", "message": "no such node"}
    }


def test_the_envelope_carries_probe_only_when_one_is_supplied():
    # #667 review: the live channel may carry structured host-probe context, so the
    # builder grew ONE optional key. It must be OMITTED (never null) when absent —
    # that is what keeps every GDScript-emitted headless envelope and every other
    # live reply byte-identical, and what lets the strict headless
    # OperationErrorEnvelope keep rejecting extras.
    probe = {"name": "CGSessionCopyCurrentDictionary", "platform": "darwin"}

    assert error_envelope("live_windowed_permission_denied", "denied", probe) == {
        "error": {
            "code": "live_windowed_permission_denied",
            "message": "denied",
            "probe": probe,
        }
    }
    assert "probe" not in error_envelope("node_not_found", "no such node")["error"]


def test_the_headless_sentinel_model_still_rejects_the_live_probe_key():
    # The two channels keep DIFFERENT models on purpose: a GDScript operation has no
    # host probe to report, so the headless sentinel stays strict and probe-less. Only
    # the live envelope accepts the key.
    import pytest
    from pydantic import ValidationError

    from gda.models import LiveErrorEnvelope, OperationErrorEnvelope

    payload = error_envelope(
        "live_windowed_permission_denied",
        "denied",
        {"name": "CGSessionCopyCurrentDictionary", "platform": "darwin"},
    )

    with pytest.raises(ValidationError):
        OperationErrorEnvelope.model_validate(payload)

    assert LiveErrorEnvelope.model_validate(payload).error.probe is not None


def test_result_reply_carries_the_sentinel_payload_at_exit_zero():
    payload = {"lines": ["a", "b"]}
    assert result_reply(payload) == {
        "stdout": build_result(payload),
        "stderr": "",
        "exit_code": 0,
    }


def test_the_exit_invariant_is_owned_by_the_builders_not_the_caller():
    # result_reply is success-only (exit 0) and error_reply is the only live-error
    # path (EXIT_LIVE): the public seam has no exit_code knob, so a caller cannot
    # pair a success payload with a non-zero exit (#261 review hardening).
    assert result_reply({"ok": True})["exit_code"] == 0
    assert error_reply("engine_disconnected", "dropped")["exit_code"] == EXIT_LIVE


def test_error_reply_is_a_live_error_envelope_at_exit_live():
    # The single builder the daemon and the live client both synthesize from; the
    # envelope is sentinel-wrapped and carries the live exit code.
    reply = error_reply(
        "engine_disconnected", "the engine session dropped the connection"
    )
    assert reply == {
        "stdout": build_result(
            {
                "error": {
                    "code": "engine_disconnected",
                    "message": "the engine session dropped the connection",
                }
            }
        ),
        "stderr": "",
        "exit_code": EXIT_LIVE,
    }
    # And it parses back to the error envelope a classifier reads.
    assert parse_result(reply["stdout"]) == error_envelope(
        "engine_disconnected", "the engine session dropped the connection"
    )


def test_live_client_error_result_matches_the_daemon_error_reply():
    # The live client's synthesized RunResult is the object form of the SAME dict the
    # daemon sends, so a client-side failure classifies identically to a relayed one.
    from gda.live_runner import _live_error_result

    result = _live_error_result("daemon_not_running", "no daemon")
    reply = error_reply("daemon_not_running", "no daemon")
    assert result.stdout == reply["stdout"]
    assert result.stderr == reply["stderr"]
    assert result.exit_code == reply["exit_code"]


@pytest.mark.parametrize("missing", ["no sentinel here", ""])
def test_parse_result_still_rejects_non_sentinel_output(missing):
    # The read side is unchanged by the consolidation.
    with pytest.raises(ValueError):
        parse_result(missing)
