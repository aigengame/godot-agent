"""Independent admission and execution witnesses for bounded pure traversal."""

from copy import deepcopy

import pytest

from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_operation_composition_subjects,
    _consumer_b_runtime_authority_is_closed,
)
from schema2_bootstrap_production_support import _authority_candidate

OWNER = "standard.conformance.structured"
ROOT = (OWNER, "bounded-fold-v1")


def _independent_fixture():
    authority = _authority_candidate()
    kernel, language = authority["kernel"], authority["language_bundle"]
    operations = {
        (package["id"], operation["id"]): deepcopy(operation)
        for package in language["language"]["packages"]
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.operations"
        for operation in entry["definitions"]
    }
    return kernel, language, operations


def test_independent_bootstrap_admits_complete_fold_graph():
    kernel, language, _operations = _independent_fixture()
    result = _consumer_b(kernel, language)
    assert result["admitted"], result["diagnostics"]


def test_independent_fold_bounds_come_from_list_type_and_transitive_steps():
    kernel, language, operations = _independent_fixture()
    bounds, closures = {}, {}
    assert not _consumer_b_operation_composition_subjects(
        kernel,
        language,
        selected_operations=operations,
        fold_input_bounds=bounds,
        closed_operations=closures,
    )
    assert {
        bounds[(ROOT, site)]
        for site in ("filter-items", "count-selected", "ordered-items")
    } == {4}
    # Eight root instructions, plus N attempts and actual step bounds 3, 2 and 3.
    assert closures[ROOT][2] == 8 + 4 * (1 + 3) + 4 * (1 + 2) + 4 * (1 + 3)
    operations[ROOT]["resource_bounds"]["max_steps"] = closures[ROOT][2] - 1
    assert _consumer_b_operation_composition_subjects(
        kernel, language, selected_operations=operations
    )


def test_independent_fold_accepts_empty_port_return_step():
    kernel, language, operations = _independent_fixture()
    step = operations[(OWNER, "bounded.count-step")]
    step["body"] = []
    step["result"]["source"] = {"kind": "port", "name": "count"}
    step["resource_bounds"]["max_steps"] = 1
    closures = {}
    assert not _consumer_b_operation_composition_subjects(
        kernel,
        language,
        selected_operations=operations,
        closed_operations=closures,
    )
    assert closures[(OWNER, "bounded.count-step")][2] == 0
    assert closures[ROOT][2] == 8 + 4 * 4 + 4 * 1 + 4 * 4


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-item",
        "wrong-accumulator",
        "missing-explicit-argument",
        "repeated-site",
        "effectful-step",
        "transitive-cycle",
        "ambient-snapshot",
        "wrong-append-element",
    ],
)
def test_independent_fold_refuses_invalid_composition(mutation):
    kernel, language, operations = _independent_fixture()
    root = operations[ROOT]
    fold = root["body"][2]
    step = operations[(OWNER, "bounded.filter-step")]
    if mutation == "wrong-item":
        fold["item_port"] = "threshold"
    elif mutation == "wrong-accumulator":
        fold["initial"] = "zero"
    elif mutation == "missing-explicit-argument":
        fold["arguments"] = []
    elif mutation == "repeated-site":
        root["body"][3]["site"] = fold["site"]
    elif mutation == "effectful-step":
        step["inputs"][0]["access"] = "write"
    elif mutation == "transitive-cycle":
        fold["operation"] = {"package": OWNER, "id": ROOT[1]}
    elif mutation == "ambient-snapshot":
        step["extensions"] = {"standard.snapshot-operands": {"operands": []}}
    else:
        step["body"][1]["item"] = "accept"
    assert _consumer_b_operation_composition_subjects(
        kernel, language, selected_operations=operations
    )


@pytest.mark.parametrize(
    "member,replacement",
    [
        ("invocation_budget_owner", "new-step-frame"),
        ("step_budget_entry", "one-before-body"),
        ("empty_result", "no-result"),
        ("iteration_order", "right-to-left"),
    ],
)
def test_independent_bootstrap_refuses_changed_fold_law(member, replacement):
    kernel, language, _operations = _independent_fixture()
    kernel = deepcopy(kernel)
    node = next(
        node
        for node in kernel["meta_format"]["runtime_program"]["nodes"]
        if node["id"] == "fold"
    )
    node["semantics"][member] = replacement
    assert not _consumer_b_runtime_authority_is_closed(kernel, language)


def _run_independent(
    items, *, threshold=3, initial=None, mutate=None, resource_limit=None
):
    from schema2_operation_execution_independent_support import reference_execute_event

    kernel, language, operations = _independent_fixture()
    if mutate:
        mutate(operations)

    def envelope(values):
        return {"type": {"package": OWNER, "id": "IntList4"}, "value": values}

    return reference_execute_event(
        kernel,
        operations[ROOT],
        operations,
        {
            "id": "independent-fold",
            "values": [
                {"name": "items", "value": envelope(items)},
                {"name": "selected_items", "value": envelope(initial or [])},
                {"name": "selected_count", "value": 0},
                {"name": "ordered_value", "value": 0},
                {"name": "threshold", "value": threshold},
            ],
        },
        seed=0,
        state_names={"selected_items", "selected_count", "ordered_value"},
        root_operation_coordinate=ROOT,
        language_bundle=language,
        include_execution_evidence=True,
        include_attempt_evidence=True,
        resource_limit=resource_limit,
    )


@pytest.mark.parametrize(
    "items", [[], [1], [1, 2, 3, 4], [1, 2, 3, 5], [4, 3, 2, 1], [3, 4], [1, 2, 1, 2]]
)
def test_independent_fold_executes_varied_values_and_actual_work(items):
    event = _run_independent(items)
    assert "refusal" not in event
    selected = [item for item in items if item < 3]
    state = {row["name"]: row["value"] for row in event["state_after"]}
    assert state["selected_items"]["value"] == selected
    assert state["selected_count"] == len(selected)
    assert state["ordered_value"] == sum(
        value * 10 ** (len(items) - position - 1)
        for position, value in enumerate(items)
    )
    assert event["execution_evidence"]["resource_charge"] == 8 + 8 * len(
        items
    ) + 3 * len(selected)
    # Every attempted append copies the accumulator prefix, including rejected branches.
    copies = sum(
        sum(previous < 3 for previous in items[:position])
        for position in range(len(items))
    )
    assert event["construction"] == {
        "copied_cells": copies,
        "allocated_slots": copies + len(items),
    }
    assert not event.get("calls")


def test_independent_fold_eager_append_refuses_before_later_work():
    def nonempty(operations):
        operations[ROOT]["body"][2]["initial"] = "selected_items"

    event = _run_independent([9], initial=[1, 2, 3, 4], mutate=nonempty)
    assert "capacity" in event["refusal"]["reason"]
    assert event["refusal"]["call_path"] == "filter-items/@0"
    assert event["refusal"]["instruction_index"] == 1
    assert event["refusal"]["call_site_identity"] is None
    assert event["execution_evidence"]["resource_charge"] == 6
    assert event["state_after"] == event["state_before"]
    assert len(event["attempts"]) == 6


def test_independent_fold_preserves_first_numeric_refusal():
    event = _run_independent([(1 << 63) - 1, 1])
    assert event["refusal"]["reason"] == "runtime.numeric_overflow"
    assert event["refusal"]["call_path"] == "ordered-items/@1"
    assert event["refusal"]["instruction_index"] == 1
    assert event["execution_evidence"]["resource_charge"] == 23
    assert event["state_after"] == event["state_before"]


@pytest.mark.parametrize(
    "limit,last_kind", [(3, "fold-invocation"), (4, "instruction")]
)
def test_independent_fold_distinguishes_attempt_from_first_body_charge(
    limit, last_kind
):
    event = _run_independent([1], resource_limit=limit)
    assert event["refusal"]["reason"] == "runtime.step_limit_exceeded"
    assert event["refusal"]["call_path"] == "filter-items/@0"
    assert event["refusal"]["instruction_index"] == 0
    assert event["attempts"][-1]["kind"] == last_kind
    assert event["execution_evidence"]["resource_charge"] == limit + 1
    assert event["attempts"][-1]["operation_steps"] == ([4] if limit == 3 else [5, 1])


@pytest.mark.parametrize("empty", [False, True])
def test_independent_fold_new_step_budget_starts_at_zero(empty):
    def change_step(operations):
        step = operations[(OWNER, "bounded.count-step")]
        step["body"] = (
            []
            if empty
            else [{"node": "copy", "target": "same-count", "value": "count"}]
        )
        step["result"]["source"] = (
            {"kind": "port", "name": "count"}
            if empty
            else {"kind": "local", "name": "same-count"}
        )
        step["resource_bounds"]["max_steps"] = 1

    event = _run_independent([1], mutate=change_step)
    assert "refusal" not in event
    assert event["execution_evidence"]["resource_charge"] == (17 if empty else 18)
    attempts = [
        row for row in event["attempts"] if row["operation"] == "bounded.count-step"
    ]
    assert attempts[0]["kind"] == "fold-invocation"
    assert len(attempts[0]["operation_steps"]) == 1
    if not empty:
        assert attempts[1]["operation_steps"][-1] == 1


def test_independent_guard_fold_bounds_belong_to_enclosing_operation():
    kernel, language, operations = _independent_fixture()
    root = operations[ROOT]
    root["body"] = [
        {
            "node": "equal",
            "left": "threshold",
            "right": "threshold",
            "target": "enabled",
        },
        {
            "node": "guard-block",
            "condition": "enabled",
            "body": root["body"],
            "outcome": root["default_outcome"],
        },
    ]
    root["resource_bounds"]["max_steps"] = 54
    root["result"]["source"] = {"kind": "port", "name": "ordered_value"}
    bounds = {}
    assert not _consumer_b_operation_composition_subjects(
        kernel, language, selected_operations=operations, fold_input_bounds=bounds
    )
    assert {(owner, site, bound) for (owner, site), bound in bounds.items()} == {
        (ROOT, "filter-items", 4),
        (ROOT, "count-selected", 4),
        (ROOT, "ordered-items", 4),
    }
    duplicate = deepcopy(root["body"][1]["body"][2])
    duplicate["target"] = "duplicate-result"
    root["body"].append(duplicate)
    assert _consumer_b_operation_composition_subjects(
        kernel, language, selected_operations=operations
    )


def test_independent_pure_invoke_shares_value_boundary_without_event_outcome():
    def invoke(operations):
        step = operations[(OWNER, "bounded.count-step")]
        step["body"] = [
            {
                "node": "invoke",
                "site": "identity/with~escape",
                "operation": {"package": "core.quantity", "id": "quantity.identity"},
                "arguments": [
                    {"port": "value", "operand": {"kind": "port", "port": "count"}}
                ],
                "result": {"kind": "local", "name": "next-count"},
                "outcomes": [],
            }
        ]
        step["resource_bounds"]["max_steps"] = 2

    kernel, language, operations = _independent_fixture()
    invoke(operations)
    assert not _consumer_b_operation_composition_subjects(
        kernel, language, selected_operations=operations
    )
    event = _run_independent([1], mutate=invoke)
    assert "refusal" not in event
    assert event["execution_evidence"]["resource_charge"] == 19
    nested = [
        row for row in event["attempts"] if row["operation"] == "quantity.identity"
    ]
    assert len(nested) == 1
    assert nested[0]["call_path"] == "count-selected/@0/identity~1with~0escape"
    assert nested[0]["operation_steps"][-2:] == [2, 1]
    assert not event.get("calls")


def test_independent_nested_fold_multiplies_static_bounds_and_actual_attempts():
    def nested(operations):
        child = deepcopy(operations[(OWNER, "bounded.count-step")])
        child["id"] = "nested-count"
        child["inputs"].append(
            {**operations[ROOT]["inputs"][0], "id": "captured-items"}
        )
        child["body"] = [
            {
                "node": "fold",
                "site": "inner",
                "target": "next-count",
                "value": "captured-items",
                "initial": "count",
                "operation": {"package": OWNER, "id": "bounded.count-step"},
                "accumulator_port": "count",
                "item_port": "item",
                "arguments": [],
            }
        ]
        child["resource_bounds"]["max_steps"] = 1 + 4 * (1 + 2)
        operations[(OWNER, child["id"])] = child
        outer = operations[ROOT]["body"][3]
        outer["operation"]["id"] = child["id"]
        outer["arguments"] = [
            {
                "port": "captured-items",
                "operand": {"kind": "port", "port": "items"},
            }
        ]
        operations[ROOT]["resource_bounds"]["max_steps"] = 96

    kernel, language, operations = _independent_fixture()
    nested(operations)
    bounds, closures = {}, {}
    assert not _consumer_b_operation_composition_subjects(
        kernel,
        language,
        selected_operations=operations,
        fold_input_bounds=bounds,
        closed_operations=closures,
    )
    assert bounds[((OWNER, "nested-count"), "inner")] == 4
    assert closures[(OWNER, "nested-count")][2] == 13
    assert closures[ROOT][2] == 8 + 4 * 4 + 4 * (1 + 13) + 4 * 4
    operations[ROOT]["resource_bounds"]["max_steps"] = 95
    assert _consumer_b_operation_composition_subjects(
        kernel, language, selected_operations=operations
    )
    event = _run_independent([1, 2], mutate=nested)
    assert "refusal" not in event
    assert {row["name"]: row["value"] for row in event["state_after"]}[
        "selected_count"
    ] == 4
    assert event["execution_evidence"]["resource_charge"] == 40
    inner_attempts = [
        row
        for row in event["attempts"]
        if row["operation"] == "bounded.count-step"
        and row["kind"] == "fold-invocation"
    ]
    assert [row["call_path"] for row in inner_attempts] == [
        f"count-selected/@{outer}/inner/@{inner}"
        for outer in range(2)
        for inner in range(2)
    ]
    assert all(len(row["operation_steps"]) == 2 for row in inner_attempts)


@pytest.mark.parametrize("items", [[], [1, 2, 3, 4], [4, 3, 2, 1]])
def test_maintained_fold_source_agrees_between_compilers_and_evaluators(items):
    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
    from gda_balancing.domain.model import (
        AdmittedRir,
        CheckedModel,
        admit_rir,
        check_model_source_value,
    )
    from gda_balancing.domain.model._compilation import lower_checked_model
    from gda_balancing.domain.model._resolution import ModelSourceContext
    from gda_balancing.domain.runtime.execution import (
        EvaluationArtifacts,
        evaluate_experiment,
    )
    from test_bounded_fold_public import _source, _specification
    from test_schema2_model_lowerer_conformance import (
        _reference_check_source,
        _reference_semantic_artifacts,
    )

    kernel, language, _operations = _independent_fixture()
    source = _source()
    independent_model = _reference_check_source(source, kernel, language)
    assert isinstance(independent_model, ModelSourceContext)
    independent_artifacts = _reference_semantic_artifacts(independent_model)
    production_model = check_model_source_value(
        source, kernel=kernel, language_bundle=language
    )
    assert isinstance(production_model, CheckedModel)
    production_artifacts = lower_checked_model(production_model)
    for name, artifact in independent_artifacts.items():
        assert production_artifacts[name] == artifact

    # The expected execution is independently interpreted from the same selected
    # Operation definitions and values; the production trace never supplies it.
    expected = _run_independent(items)
    expected_values = {row["name"]: row["value"] for row in expected["state_after"]}
    rir = independent_artifacts["rir-semantic-payload"]
    assert all(
        "vectors" in row["definition"]
        for row in independent_artifacts["package-lock"]["operations"]
    )
    assert all(
        "vectors" not in row["definition"]
        for row in rir["selected_semantics"]["operations"]
    )
    assert all(
        "vectors" not in definition
        for closure in rir["selected_semantics"]["package_semantic_closures"]
        for entry in closure["definitions"]
        if entry["authority_path"] == "language.operations"
        for definition in entry["definitions"]
    )
    specification = _specification(
        rir,
        items,
        count=expected_values["selected_count"],
        order=expected_values["ordered_value"],
    )
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext)
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir)
    experiment = check_experiment_value(
        specification, program, authority_context=context
    )
    assert isinstance(experiment, CheckedExperiment)
    execution = evaluate_experiment(experiment)
    assert isinstance(execution, EvaluationArtifacts)
    members = {name: member.value for name, member in execution.members.items()}
    actual = next(
        row
        for row in members["event-trace"]["events"]
        if row["observation"] is None
    )
    for member in ("state_before", "state_after", "outcome"):
        assert actual[member] == expected[member]
    assert actual["calls"] == expected.get("calls", [])
    assert members["snapshot-series"]["snapshots"][-1]["continuation"][
        "resource_ledger"
    ]["node_steps"] == expected["execution_evidence"]["resource_charge"]
