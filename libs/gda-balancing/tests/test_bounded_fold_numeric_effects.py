"""Admitted scalar fold results compose with Event numeric consumers."""

import pytest

from gda_balancing.domain.experiment import (
    CheckedExperiment,
    check_experiment_value,
    derive_scenario_program_requirements,
)
from gda_balancing.domain.model import (
    AdmittedRir,
    CheckedModel,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
)
from gda_balancing.domain.runtime.execution import (
    EvaluationArtifacts,
    evaluate_experiment,
)
from schema2_operation_execution_independent_support import reference_execute_event
from test_bounded_fold_public import _source, _specification
from test_bounded_fold_runtime import _candidate, _single_fold

_OWNER = "standard.conformance.structured"
_ROOT = (_OWNER, "bounded-fold-v1")


@pytest.mark.parametrize("consumer", ["subtract-state", "write-state", "precondition"])
def test_admitted_fold_item_result_composes_with_numeric_event_consumers(consumer):
    def mutate(operations):
        _single_fold(operations, empty=True)
        # An empty pure step may return its explicit item port. List iteration
        # supplies that scalar in its admitted typed Quantity representation.
        operations["bounded.count-step"]["result"]["source"] = {
            "kind": "port",
            "name": "item",
        }
        root = operations["bounded-fold-v1"]
        if consumer == "precondition":
            root["body"].insert(
                2,
                {
                    "node": "precondition-greater-than-or-equal",
                    "left": "counted",
                    "right": "zero",
                    "outcome": "blocked",
                },
            )
            root["outcomes"].append(
                {
                    "id": "blocked",
                    "kind": "gameplay-alternative",
                    "state_policy": "rollback",
                }
            )
            root["resource_bounds"]["max_steps"] = 8
        else:
            root["body"][-1]["node"] = consumer

    context, operation = _candidate(mutate)
    source = _source()
    model = check_model_source_value(source, authority_context=context)
    assert isinstance(model, CheckedModel), model
    artifacts = compile_checked_model(model)
    assert len(artifacts) == 8
    rir = artifacts["rir-semantic-payload"]
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir), program
    rir = program.artifact()
    specification = _specification(rir, [1], count=1, order=0)
    for row in specification["scenarios"][0]["assignments"]:
        if row["target"]["name"] == "selected_count":
            row["value"] = 2
    requirements, _streams = derive_scenario_program_requirements(
        rir,
        "fold",
        operation["runtime_profile"],
        context.kernel["meta_format"]["runtime_program"]["named_rng"]["algorithm"],
    )
    specification["runtime"]["required_evaluator"] = requirements
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked

    # The independent interpreter reads the same admitted selected definitions;
    # it does not derive its expected state from the production result.
    kernel, language = context.mutable_pair()
    selected = {
        (row["package"], row["definition"]["id"]): row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    reference = reference_execute_event(
        kernel,
        selected[_ROOT],
        selected,
        {
            "id": "numeric-effect",
            "values": [
                {"name": row["target"]["name"], "value": row["value"]}
                for row in specification["scenarios"][0]["assignments"]
            ]
            + [
                {
                    "name": "threshold",
                    "value": source["entrypoints"][0]["arguments"][-1]["operand"][
                        "value"
                    ],
                }
            ],
        },
        seed=specification["seed"]["value"],
        state_names={"selected_items", "selected_count", "ordered_value"},
        language_bundle=language,
        root_operation_coordinate=_ROOT,
        include_execution_evidence=True,
    )
    assert {row["name"]: row["value"] for row in reference["state_after"]}[
        "selected_count"
    ] == 1

    result = evaluate_experiment(checked)
    assert isinstance(result, EvaluationArtifacts), result
    event = result.members["event-trace"].value["events"][0]
    for member in ("state_before", "state_after", "outcome"):
        assert event[member] == reference[member]
    assert event["calls"] == []
    ledger = result.members["snapshot-series"].value["snapshots"][-1]["continuation"][
        "resource_ledger"
    ]
    assert ledger["node_steps"] == reference["execution_evidence"]["resource_charge"]
    assert ledger["node_steps"] == (5 if consumer == "precondition" else 4)
