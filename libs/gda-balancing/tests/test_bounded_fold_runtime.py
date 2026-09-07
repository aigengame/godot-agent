"""Actual pure-frame execution and metering through compiled Operation harnesses.

The existing vector harness admits Source and RIR, then supplies its synthetic
terminal metric directly to CheckedExperiment. These tests own Runtime behavior;
the public fold suite separately owns complete Experiment/CLI admission.
"""

from copy import deepcopy
from dataclasses import replace

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
    packaged_authority_context,
)
from gda_balancing.domain.experiment import derive_scenario_program_requirements
from gda_balancing.domain.model import (
    CheckedModel,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
)
from gda_balancing.domain.runtime import execution
from gda_balancing.domain.runtime.execution import (
    EvaluationArtifacts,
    RuntimeRefusalOutcome,
)
from test_schema2_model_cli import _reidentify_language_bundle
from schema2_operation_execution_production_support import (
    OperationExecutionHarness,
    _candidate_model_source,
    _checked_vector_experiment,
)

_OWNER = "standard.conformance.structured"
_ROOT = "bounded-fold-v1"
_LIST = {"type": {"package": _OWNER, "id": "IntList4"}, "value": []}


def _candidate(mutate, *, event_limit=None, run_limit=None):
    kernel, language = packaged_authority_context().mutable_pair()
    operations = {
        row["id"]: row
        for row in language["language"]["operations"]
        if row["id"].startswith("bounded")
    }
    mutate(operations)
    profile = next(
        row
        for row in language["language"]["runtime_profiles"]
        if row["id"] == operations[_ROOT]["runtime_profile"]
    )
    if event_limit is not None:
        profile["resource_bounds"]["max_event_steps"] = event_limit
    if run_limit is not None:
        profile["resource_bounds"]["max_node_steps"] = run_limit
    # These vectors describe exact authored contracts, not execution oracles.
    # Rebind changed candidate bodies/bounds before asking real authority admission.
    for vector in language["vectors"]:
        if (
            vector.get("kind") == "operation-contract"
            and vector.get("operation") in operations
        ):
            value = operations[vector["operation"]]
            for member in vector["probe"]["path"].split("."):
                value = value[member]
            vector["expect"] = deepcopy(value)
    _reidentify_language_bundle(language)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    return context, operations[_ROOT]


def _checked(context, operation, *, items=(1,), root="root/~@0", count=0, threshold=3):
    coordinate = (_OWNER, _ROOT)
    source, result_name = _candidate_model_source(context, coordinate, operation, root)
    model = check_model_source_value(source, authority_context=context)
    assert isinstance(model, CheckedModel), model
    artifacts = compile_checked_model(model)
    program = admit_rir(artifacts["rir-semantic-payload"], authority_context=context)
    requirements, streams = derive_scenario_program_requirements(
        program.artifact(),
        root,
        operation["runtime_profile"],
        context.kernel["meta_format"]["runtime_program"]["named_rng"]["algorithm"],
    )
    harness = OperationExecutionHarness(
        coordinate, source, program, result_name, requirements, streams, root
    )
    values = {
        "items": {**_LIST, "value": list(items)},
        "selected_items": _LIST,
        "selected_count": count,
        "ordered_value": 0,
        "threshold": threshold,
    }
    checked, _result_name = _checked_vector_experiment(
        context,
        coordinate,
        operation,
        {
            "id": "bounded-runtime",
            "input": {
                "seed": 1,
                "values": [
                    {"name": name, "value": value} for name, value in values.items()
                ],
            },
        },
        harness=harness,
    )
    return checked


def _execute(checked, monkeypatch):
    budgets = []
    constructor = execution._OperationBudget

    def record_budget(limit):
        result = constructor(limit)
        budgets.append(result)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(execution, "_OperationBudget", record_budget)
        outcome = execution.evaluate_experiment(checked)
    return outcome, [(budget.limit, budget.used) for budget in budgets]


def _state(outcome):
    assert isinstance(outcome, EvaluationArtifacts), outcome
    trace = outcome.members["event-trace"].value
    assert trace["events"][0]["calls"] == []
    return {row["name"]: row["value"] for row in trace["events"][0]["state_after"]}


def _single_fold(operations, *, empty=False):
    step = operations["bounded.count-step"]
    step["body"] = (
        [] if empty else [{"node": "copy", "target": "next-count", "value": "count"}]
    )
    step["result"]["source"] = (
        {"kind": "port", "name": "count"}
        if empty
        else {"kind": "local", "name": "next-count"}
    )
    step["resource_bounds"]["max_steps"] = 1
    root = operations[_ROOT]
    fold = deepcopy(root["body"][3])
    fold.update(value="items", site="fold/~@0")
    root["body"] = [root["body"][1], fold, root["body"][6]]
    root["result"]["source"] = {"kind": "local", "name": "counted"}
    root["resource_bounds"]["max_steps"] = 7 if empty else 11


@pytest.mark.parametrize("empty,actual", [(False, 5), (True, 4)])
def test_iteration_attempt_precedes_zeroed_step_frame(empty, actual, monkeypatch):
    context, operation = _candidate(
        lambda operations: _single_fold(operations, empty=empty)
    )
    outcome, budgets = _execute(_checked(context, operation), monkeypatch)
    assert _state(outcome)["selected_count"] == 0
    assert budgets == [(7 if empty else 11, actual), (1, 0 if empty else 1)]
    assert isinstance(outcome, EvaluationArtifacts)
    assert (
        outcome.members["snapshot-series"].value["snapshots"][1]["continuation"][
            "resource_ledger"
        ]["event_steps"]
        == actual
    )


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("scope", ["event", "run"])
def test_iteration_attempt_refusal_has_no_new_step_frame(empty, scope, monkeypatch):
    context, operation = _candidate(
        lambda operations: _single_fold(operations, empty=empty),
        event_limit=2 if scope == "event" else None,
        run_limit=2 if scope == "run" else None,
    )
    outcome, budgets = _execute(_checked(context, operation), monkeypatch)
    assert isinstance(outcome, RuntimeRefusalOutcome), outcome
    assert outcome.refusing_call_path == "root~1~0@0/fold~1~0@0/@0"
    assert outcome.refusing_operation == "bounded.count-step"
    assert outcome.refusing_call_site_identity is None
    assert outcome.refusing_instruction_index == 0
    assert outcome.budget_counters["event_steps"] == 3
    assert outcome.budget_counters["node_steps"] == 3
    assert len(budgets) == 1
    assert budgets[0][1] == 3
    assert outcome.refusing_attempted_calls == ()


def test_first_step_instruction_refusal_has_created_frame(monkeypatch):
    context, operation = _candidate(_single_fold, event_limit=3)
    outcome, budgets = _execute(_checked(context, operation), monkeypatch)
    assert isinstance(outcome, RuntimeRefusalOutcome), outcome
    assert outcome.refusing_call_path == "root~1~0@0/fold~1~0@0/@0"
    assert outcome.refusing_instruction_index == 0
    assert outcome.budget_counters["event_steps"] == 4
    assert budgets == [(11, 4), (1, 1)]


@pytest.mark.parametrize("site", ["@0", "x/@0", "x~1@0"])
def test_ordinary_pure_invoke_has_static_identity_and_no_event_call(site, monkeypatch):
    def mutate(operations):
        step = operations["bounded.order-step"]
        step["body"][-1] = {
            "node": "invoke",
            "site": site,
            "operation": {"package": "core.quantity", "id": "quantity.add"},
            "arguments": [
                {"port": "left", "operand": {"kind": "local", "local": "shifted"}},
                {"port": "right", "operand": {"kind": "port", "port": "item"}},
            ],
            "result": {"kind": "local", "name": "next-order"},
            "outcomes": [],
        }
        step["resource_bounds"]["max_steps"] = 4
        operations[_ROOT]["resource_bounds"]["max_steps"] = 56

    context, operation = _candidate(mutate)
    checked = _checked(context, operation, items=(1, 2, 3, 4))
    outcome, budgets = _execute(checked, monkeypatch)
    assert _state(outcome)["ordered_value"] == 1234
    assert budgets[0] == (56, 50)
    assert budgets.count((4, 4)) == 4
    assert budgets.count((1, 1)) == 4
    assert [call["site"] for call in checked.rir["call_sites"]] == [site]


def test_pure_frame_rejects_forged_snapshot_capture(monkeypatch):
    context, operation = _candidate(_single_fold)
    checked = _checked(context, operation)
    rir = deepcopy(checked.rir)
    step = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "bounded.count-step"
    )
    step["extensions"] = {"standard.snapshot-operands": {"operands": []}}
    # Deliberately bypass Model admission to test the private pure boundary.
    forged = replace(checked, rir=rir)
    with pytest.raises(ValueError, match="pure Operation cannot capture Snapshot"):
        _execute(forged, monkeypatch)


def test_nested_folds_charge_every_active_operation(monkeypatch):
    def mutate(operations):
        _single_fold(operations)
        root = operations[_ROOT]
        outer = operations["bounded.count-step"]
        outer["inputs"].append(deepcopy(root["inputs"][0]))
        outer["body"] = [
            {
                "node": "fold",
                "site": "inner/@0",
                "target": "next-count",
                "value": "items",
                "initial": "count",
                "operation": {"package": _OWNER, "id": "bounded.order-step"},
                "accumulator_port": "accumulator",
                "item_port": "item",
                "arguments": [],
            }
        ]
        outer["resource_bounds"]["max_steps"] = 17
        root["body"][1]["arguments"] = [
            {"port": "items", "operand": {"kind": "port", "port": "items"}},
        ]
        root["resource_bounds"]["max_steps"] = 75

    context, operation = _candidate(mutate)
    outcome, budgets = _execute(_checked(context, operation, items=(1, 2)), monkeypatch)
    assert _state(outcome)["selected_count"] == 1212
    assert budgets == [(75, 23), (17, 9), (3, 3), (3, 3), (17, 9), (3, 3), (3, 3)]


@pytest.mark.parametrize("entered,actual", [(False, 4), (True, 12)])
def test_guard_shares_its_operation_frame(entered, actual, monkeypatch):
    def mutate(operations):
        root = operations[_ROOT]
        fold = deepcopy(root["body"][3])
        fold["value"] = "items"
        fold["target"] = "guard-count"
        write = {
            "node": "write-state",
            "symbol": "selected_count",
            "value": "guard-count",
        }
        root["body"] = [
            root["body"][1],
            {"node": "copy", "target": "counted", "value": "zero"},
            {
                "node": "less-than",
                "target": "enter",
                "left": "zero" if entered else "threshold",
                "right": "threshold" if entered else "zero",
            },
            {
                "node": "guard-block",
                "condition": "enter",
                "outcome": "folded",
                "body": [fold, write],
            },
        ]
        root["result"]["source"] = {"kind": "local", "name": "counted"}
        root["resource_bounds"]["max_steps"] = 18

    context, operation = _candidate(mutate)
    outcome, budgets = _execute(_checked(context, operation, items=(1, 2)), monkeypatch)
    assert _state(outcome)["selected_count"] == (2 if entered else 0)
    assert budgets == [(18, actual), *(([(2, 2)] * 2) if entered else [])]


def _pure_state_value(operations, site="read-state/~@0"):
    root = operations[_ROOT]
    root["body"] = [
        {
            "node": "invoke",
            "site": site,
            "operation": {"package": "core.quantity", "id": "quantity.add"},
            "arguments": [
                {
                    "port": "left",
                    "operand": {"kind": "port", "port": "selected_count"},
                },
                {"port": "right", "operand": {"kind": "port", "port": "threshold"}},
            ],
            "result": {"kind": "local", "name": "sum"},
            "outcomes": [],
        },
        {"node": "write-state", "symbol": "selected_count", "value": "sum"},
    ]
    root["result"]["source"] = {"kind": "local", "name": "sum"}
    root["resource_bounds"]["max_steps"] = 3


def test_pure_invoke_receives_explicit_state_value_without_alias_capture(monkeypatch):
    context, operation = _candidate(_pure_state_value)
    checked = _checked(context, operation)
    outcome, budgets = _execute(checked, monkeypatch)
    assert _state(outcome)["selected_count"] == 3
    assert budgets == [(3, 3), (1, 1)]


@pytest.mark.parametrize(
    "site,encoded",
    [
        ("@0", "@0"),
        ("x/@0", "x~1@0"),
        ("x~1@0", "x~01@0"),
        ("read-state/~@0", "read-state~1~0@0"),
    ],
)
def test_pure_numeric_refusal_preserves_static_identity_and_dynamic_path(
    site, encoded, monkeypatch
):
    context, operation = _candidate(
        lambda operations: _pure_state_value(operations, site)
    )
    checked = _checked(context, operation, count=2**63 - 1, threshold=1)
    outcome, budgets = _execute(checked, monkeypatch)
    assert isinstance(outcome, RuntimeRefusalOutcome), outcome
    assert outcome.refusing_call_path == "root~1~0@0/" + encoded
    assert outcome.refusing_operation == "quantity.add"
    assert outcome.refusing_instruction_index == 0
    assert checked.rir["call_sites"][0]["site"] == site
    assert (
        outcome.refusing_call_site_identity == checked.rir["call_sites"][0]["identity"]
    )
    assert outcome.budget_counters["event_steps"] == 2
    assert outcome.budget_counters["node_steps"] == 2
    assert outcome.refusing_attempted_calls == ()
    assert outcome.state_before == outcome.state_after
    assert budgets == [(3, 2), (1, 1)]
