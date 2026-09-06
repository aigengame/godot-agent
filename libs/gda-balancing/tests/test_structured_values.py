"""Focused tests for authority-driven structured value operations."""

import pytest

from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.structured_values import (
    StructuredValueFault,
    admit_typed_value,
    language_structured_value_index,
    lookup_typed_value,
)


def _authority():
    kernel, language_bundle = packaged_authority_context().mutable_pair()
    return language_structured_value_index(language_bundle, kernel=kernel)


def test_tagged_nominal_reference_is_canonicalized_by_the_selected_profile():
    admitted = admit_typed_value(
        {
            "type": {
                "id": "CandidateKind",
                "kind": "nominal",
                "package": "standard.conformance.structured",
                "version": "2.0.0",
            },
            "value": "primary",
        },
        authority=_authority(),
        resource_limit=10,
    )

    assert admitted == {
        "type": {
            "id": "CandidateKind",
            "package": "standard.conformance.structured",
            "version": "2.0.0",
        },
        "value": "primary",
    }


def test_nominal_reference_refuses_members_outside_the_selected_profile():
    with pytest.raises(StructuredValueFault) as fault:
        admit_typed_value(
            {
                "type": {
                    "id": "CandidateKind",
                    "package": "standard.conformance.structured",
                    "scope": "unexpected",
                    "version": "2.0.0",
                },
                "value": "primary",
            },
            authority=_authority(),
            resource_limit=10,
        )

    assert fault.value.code == "language.structured_value_type_mismatch"


def test_record_lookup_returns_its_declared_fixed_nominal_field_type():
    result = lookup_typed_value(
        {
            "type": {
                "id": "SelectionResult",
                "package": "standard.conformance.structured",
                "version": "2.0.0",
            },
            "value": {
                "kind": "primary",
                "rank": 4,
                "selected": {"key": "candidate_a"},
            },
        },
        "rank",
        authority=_authority(),
        resource_limit=100,
    )

    assert result == {
        "type": {
            "id": "Quantity",
            "package": "core.quantity",
            "version": "2.2.0",
        },
        "value": 4,
    }


def test_record_lookup_consumes_the_declared_structured_operation_bound():
    index = _authority()
    operation = index.operations["standard.schema.record-field-v1"]
    operation["resource_bounds"]["max_steps"] = 0

    with pytest.raises(StructuredValueFault) as fault:
        lookup_typed_value(
            {
                "type": {
                    "id": "SelectionResult",
                    "package": "standard.conformance.structured",
                    "version": "2.0.0",
                },
                "value": {
                    "kind": "primary",
                    "rank": 4,
                    "selected": {"key": "candidate_a"},
                },
            },
            "rank",
            authority=index,
            resource_limit=100,
        )

    assert fault.value.code == "language.structured_value_type_mismatch"
    assert fault.value.pointer == "/type"
