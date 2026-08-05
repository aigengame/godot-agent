"""The closed envelope's field law (bADR-0008), pinned as executable tests.

`category`/`message` required everywhere; `refusal` requires non-empty
`refusals` + `truncated` and forbids an envelope-level `code`;
`usage`/`internal` require `code` and forbid `refusals`/`truncated`; the
schema is closed — no other member is permitted.
"""

import jsonschema
import pytest
from pydantic import ValidationError as PydanticValidationError

from gda_balancing.interfaces.cli.envelope import (
    CLI_ERROR_CODES,
    ERROR_ENVELOPE_SCHEMA,
    INTERNAL_ERROR,
    REFUSAL_BOUND,
    USAGE_CODES,
    internal_envelope,
    usage_envelope,
)
from _legacy_design_adapters import refusal_envelope
from gda_balancing.schema.refusal import Refusal, RefusalReport


def _valid(payload: dict) -> None:
    jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)


def _invalid(payload: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        _valid(payload)


REFUSAL_ITEM = {"code": "some_refusal", "path": "/attributes/0", "detail": "why"}


def test_builders_emit_schema_valid_envelopes():
    _valid(usage_envelope("missing_command", "no command named"))
    _valid(internal_envelope("it broke"))
    _valid(internal_envelope("it broke", diagnostics="Traceback ..."))
    _valid(
        refusal_envelope(
            RefusalReport(
                refusals=(Refusal(code="c", path="/attributes/0", detail="d"),),
                truncated=True,
            )
        )
    )


def test_builders_reject_unregistered_codes():
    with pytest.raises(ValueError):
        usage_envelope("not_a_code", "nope")


def test_refusal_field_law():
    base = {"category": "refusal", "message": "rejected"}
    _valid({"error": {**base, "refusals": [REFUSAL_ITEM], "truncated": False}})
    _invalid({"error": {**base, "refusals": [], "truncated": False}})  # non-empty
    _invalid({"error": {**base, "refusals": [REFUSAL_ITEM]}})  # truncated required
    _invalid(
        {  # envelope-level code forbidden for refusal
            "error": {
                **base,
                "refusals": [REFUSAL_ITEM],
                "truncated": False,
                "code": "invalid_argument",
            }
        }
    )


def test_refusal_outcome_models_make_invalid_reports_unconstructible():
    # The constraints live on the outcome models themselves (same constants
    # as the published schema), so a handler outcome that constructs is
    # guaranteed to emit schema-valid stdout — handlers consume the model
    # types, not the schema.
    ok = Refusal(code="c", path="/attributes/0", detail="d")
    with pytest.raises(PydanticValidationError):
        Refusal(code="c", path="not-a-pointer", detail="d")
    with pytest.raises(PydanticValidationError):
        RefusalReport(refusals=(), truncated=False)
    at_bound = (ok,) * REFUSAL_BOUND
    _valid(refusal_envelope(RefusalReport(refusals=at_bound, truncated=True)))
    with pytest.raises(PydanticValidationError):
        RefusalReport(refusals=at_bound + (ok,), truncated=True)


def test_refusal_envelope_projects_items_exactly():
    # A Refusal subclass with extra fields must not widen the closed item
    # schema: the builder projects code/path/detail explicitly, so the
    # envelope's shape is owned by the builder, not the runtime item type.
    class SneakyRefusal(Refusal):
        extra: int = 7

    report = RefusalReport(
        refusals=(SneakyRefusal(code="c", path="/a", detail="d"),),
        truncated=False,
    )
    env = refusal_envelope(report)
    assert env["error"]["refusals"] == [{"code": "c", "path": "/a", "detail": "d"}]
    _valid(env)


def test_refusal_report_is_bounded():
    base = {"category": "refusal", "message": "rejected", "truncated": True}
    at_bound = [REFUSAL_ITEM] * REFUSAL_BOUND
    _valid({"error": {**base, "refusals": at_bound}})
    _invalid({"error": {**base, "refusals": at_bound + [REFUSAL_ITEM]}})


def test_refusal_path_is_a_json_pointer():
    base = {"category": "refusal", "message": "rejected", "truncated": False}
    whole_document = {"code": "c", "path": "", "detail": "d"}
    _valid({"error": {**base, "refusals": [whole_document]}})
    not_a_pointer = {"code": "c", "path": "not-a-pointer", "detail": "d"}
    _invalid({"error": {**base, "refusals": [not_a_pointer]}})


def test_lone_newline_path_is_rejected_by_model_and_schema():
    # Engine-divergence regression: Python `re` lets the terminal `$` match
    # before a trailing newline, so a lone "\n" satisfied the bare pointer
    # pattern on the jsonschema side while pydantic's Rust engine rejected
    # it. The published schema now encodes RFC 6901's empty-or-leading-"/"
    # shape without relying on `$`; both sides must reject.
    with pytest.raises(PydanticValidationError):
        Refusal(code="c", path="\n", detail="d")
    base = {"category": "refusal", "message": "rejected", "truncated": False}
    _invalid(
        {"error": {**base, "refusals": [{"code": "c", "path": "\n", "detail": "d"}]}}
    )
    # A newline INSIDE a token stays legal on both sides (RFC 6901 allows
    # any non-`/`/`~` character in a reference token).
    embedded = Refusal(code="c", path="/a\nb", detail="d")
    _valid(
        {
            "error": {
                **base,
                "refusals": [embedded.model_dump(mode="json")],
            }
        }
    )


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
                "refusals": [REFUSAL_ITEM],
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
