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
