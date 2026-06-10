"""S2: the result parser implements the ADR-0002 sentinel contract."""

import json

import pytest

from gda.parser import parse_result


def test_extracts_json_ignoring_engine_noise():
    # Real headless stdout interleaves the engine banner, warnings and stray
    # print() output around the single sentinel-delimited result block.
    stdout = (
        "Godot Engine v4.6.3.stable.official - https://godotengine.org\n"
        "WARNING: something benign happened\n"
        "stray print from user script\n"
        "<<<GDA:RESULT>>>"
        '{"major": 4, "minor": 6, "patch": 3, "status": "stable"}'
        "<<<GDA:END>>>\n"
        "trailing engine noise after the result\n"
    )

    result = parse_result(stdout)

    assert result == {"major": 4, "minor": 6, "patch": 3, "status": "stable"}


def test_empty_payload_raises_descriptive_error():
    # A contract violation: the GDScript emitted adjacent sentinels with no
    # payload. The parser should say so, not leak an opaque JSONDecodeError.
    stdout = "noise\n<<<GDA:RESULT>>>   <<<GDA:END>>>\n"

    with pytest.raises(ValueError, match="empty GDA result payload"):
        parse_result(stdout)


def test_payload_containing_end_sentinel_round_trips():
    # issue #34: the result payload echoes user-controlled content (a path, and
    # later node names / script source). If that content contains the literal
    # end sentinel, extraction must still recover the whole payload — the real
    # terminator is the LAST end sentinel, not the first.
    payload = {"path": "res://weird<<<GDA:END>>>name.tscn", "root_type": "Node2D"}
    stdout = f"<<<GDA:RESULT>>>{json.dumps(payload)}<<<GDA:END>>>\n"

    assert parse_result(stdout) == payload
