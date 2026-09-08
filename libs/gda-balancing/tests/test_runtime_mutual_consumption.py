"""Independent Runtime execution consumes selected RIR before sharing results."""

from copy import deepcopy

import pytest

from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_operation_execution_independent_support import (
    ReferenceEventFrame,
    reference_execute_event,
)
from test_bounded_fold_public import _source, _specification
from test_schema2_model_lowerer_conformance import (
    _reference_check_source,
    _reference_semantic_artifacts,
)


@pytest.fixture(scope="module")
def independent_fold():
    kernel, language = mutable_authorities()
    assert _consumer_b(kernel, language)["admitted"]
    checked = _reference_check_source(_source(), kernel, language)
    assert not isinstance(checked, tuple), checked
    artifacts = _reference_semantic_artifacts(checked)
    return kernel, checked, artifacts["rir-semantic-payload"]


def _fold_frame(rir, specification):
    scenario = specification["scenarios"][0]
    values = {
        tuple(
            row["target"][member] for member in ("model", "module", "name")
        ): deepcopy(row["value"])
        for row in scenario["assignments"]
    }
    return ReferenceEventFrame(
        values=values,
        rng_states={},
        rng_indices={},
        node_steps=0,
        ordering_key={
            "logical_time": 0,
            "phase": "transition",
            "priority": 0,
            "enqueue_sequence": 0,
        },
    )


def _fold_event(kernel, rir, specification, frame):
    entrypoint = rir["entrypoints"][0]
    operations = {
        (row["package"], row["definition"]["id"]): row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    coordinate = (entrypoint["operation"]["package"], entrypoint["operation"]["id"])
    return reference_execute_event(
        kernel,
        operations[coordinate],
        operations,
        specification["scenarios"][0],
        seed=specification["seed"]["value"],
        resolved_entrypoint=entrypoint,
        resolved_declarations=rir["declarations"],
        resolved_call_sites=rir["call_sites"],
        root_operation_coordinate=coordinate,
        selected_semantics=rir["selected_semantics"],
        include_execution_evidence=True,
        frame=frame,
    )


@pytest.mark.parametrize("items,ordered", [([1, 2, 3, 4], 1234), ([4, 3, 2, 1], 4321)])
def test_independent_events_use_native_nominal_rir_and_committed_frames(
    independent_fold, items, ordered
):
    kernel, _, rir = independent_fold
    specification = _specification(rir, items)
    first = _fold_event(kernel, rir, specification, _fold_frame(rir, specification))
    assert "refusal" not in first
    after = {row["name"]: row["value"] for row in first["state_after"]}
    assert after["selected_items"]["value"] == [value for value in items if value < 3]
    assert after["selected_count"] == 2
    assert after["ordered_value"] == ordered
    continuation = first["continuation"]
    assert continuation.node_steps == 46
    second = _fold_event(kernel, rir, specification, continuation)
    assert second["state_before"] == first["state_after"]
    assert second["state_after"] == first["state_after"]
    assert second["continuation"].node_steps == 92
    assert first["execution_evidence"]["resource_charge"] == 46
    assert second["execution_evidence"]["resource_charge"] == 46


def test_independent_nominal_support_does_not_default_missing_quantity_bounds(
    independent_fold,
):
    kernel, _, original = independent_fold
    rir = deepcopy(original)
    declaration = next(
        row for row in rir["declarations"] if row["symbol"] == "ordered_value"
    )
    del declaration["domain_kind"]
    specification = _specification(rir, [1, 2, 3, 4])
    with pytest.raises(KeyError, match="domain_kind"):
        _fold_event(kernel, rir, specification, _fold_frame(rir, specification))
