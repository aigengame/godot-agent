"""The active shared usage/internal envelope and its closed field law.

Typed language refusals use descriptor-owned schemas, exercised by the
current authority and CLI conformance tests.
"""

import jsonschema
import pytest

from gda_balancing.interfaces.cli.envelope import (
    CLI_ERROR_CODES,
    ERROR_ENVELOPE_SCHEMA,
    INTERNAL_ERROR,
    USAGE_CODES,
    internal_envelope,
    usage_envelope,
)


def _valid(payload: dict) -> None:
    jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)


def _invalid(payload: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        _valid(payload)


def test_builders_emit_schema_valid_envelopes():
    _valid(usage_envelope("missing_command", "no command named"))
    _valid(internal_envelope("it broke"))
    _valid(internal_envelope("it broke", diagnostics="Traceback ..."))


def test_builders_reject_unregistered_codes():
    with pytest.raises(ValueError):
        usage_envelope("not_a_code", "nope")


def test_usage_carries_no_reproduction():
    # Usage errors resolve at binding, before execution — a seed can never
    # have been drawn, so the usage branch has no `reproduction` member.
    _invalid(
        {
            "error": {
                "category": "usage",
                "code": "unknown_command",
                "message": "m",
                "reproduction": {"seed": 1, "toolkit_version": "0.0.0"},
            }
        }
    )
    _valid(
        {
            "error": {
                "category": "internal",
                "code": INTERNAL_ERROR,
                "message": "m",
                "reproduction": {"seed": 1, "toolkit_version": "0.0.0"},
            }
        }
    )


def test_usage_and_internal_field_law():
    _valid({"error": {"category": "usage", "code": "unknown_command", "message": "m"}})
    _invalid({"error": {"category": "usage", "message": "m"}})  # code required
    _invalid(
        {  # refusals forbidden for usage
            "error": {
                "category": "usage",
                "code": "unknown_command",
                "message": "m",
                "refusals": [{}],
            }
        }
    )
    _invalid(
        {  # usage code must resolve against the registry
            "error": {"category": "usage", "code": "not_a_code", "message": "m"}
        }
    )
    _invalid(
        {  # internal carries the single fixed code
            "error": {"category": "internal", "code": "unknown_command", "message": "m"}
        }
    )


def test_the_schema_is_closed():
    _invalid(
        {
            "error": {
                "category": "usage",
                "code": "unknown_command",
                "message": "m",
                "extra": True,
            }
        }
    )
    _invalid(
        {
            "error": {"category": "usage", "code": "unknown_command", "message": "m"},
            "result": {},
        }
    )


def test_the_registry_is_the_usage_family_plus_the_fixed_internal_code():
    assert CLI_ERROR_CODES == USAGE_CODES | {INTERNAL_ERROR}
    assert USAGE_CODES == {
        "missing_command",
        "unknown_command",
        "unknown_argument",
        "argument_conflict",
        "invalid_argument",
        "invocation_key_conflict",
        "unreadable_input",
        "unwritable_output",
    }
