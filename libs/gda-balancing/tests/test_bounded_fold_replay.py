"""Real fold refusals must survive independent replay, not claimed path chasing."""

from copy import deepcopy
import inspect

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import (
    runtime_terminal_audit_members,
    validate_experiment_artifact_set,
    validate_experiment_member,
)
from gda_balancing.domain.model import (
    CheckedModel,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
)
from gda_balancing.domain.runtime.execution import (
    EvaluationArtifacts,
    PreparedExperiment,
    RuntimeRefusalOutcome,
    evaluate_prepared_experiment,
    prepare_experiment,
)
from gda_balancing.domain.runtime import execution as runtime_execution
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _bind_package_vector_set
from test_bounded_fold_public import _OWNER, _source, _specification
from test_bounded_fold_terminal_audit import _assert_reidentified_audit_refuses
from schema2_bootstrap_production_support import _reidentify_graph_root

_MAX = (1 << 63) - 1


@pytest.mark.parametrize("target_order", [1234, 4321], ids=["verdict", "success"])
def test_fold_artifacts_reject_a_real_reversed_execution_post_state(target_order):
    context = admit_authority_context(*mutable_authorities())
    assert isinstance(context, AdmittedAuthorityContext), context
    model = check_model_source_value(_source(), authority_context=context)
    assert isinstance(model, CheckedModel), model
    rir = compile_checked_model(model)["rir-semantic-payload"]
    program = admit_rir(rir, authority_context=context)
    checked = check_experiment_value(
        _specification(rir, [1, 2, 3, 4], order=target_order),
        program,
        authority_context=context,
    )
    assert isinstance(checked, CheckedExperiment), checked
    prepared = prepare_experiment(checked)
    assert isinstance(prepared, PreparedExperiment), prepared
    control = evaluate_prepared_experiment(prepared)
    assert isinstance(control, EvaluationArtifacts), control
    assert control.accepted is (target_order == 1234)
    control_members = {
        name: deepcopy(member.value) for name, member in control.members.items()
    }
    assert validate_experiment_artifact_set(checked, control_members)
    control_event = next(
        row
        for row in control_members["event-trace"]["events"]
        if row["operation"] is not None
    )
    control_state = {row["name"]: row["value"] for row in control_event["state_after"]}
    assert control_state["ordered_value"] == 1234
    assert control_state["selected_items"]["value"] == [1, 2]

    # Change only the production traversal. The admitted program, input, producer
    # artifact construction and independent validator remain the real controls.
    source = inspect.getsource(evaluate_prepared_experiment)
    traversal = "for item_index, item in enumerate(collection[value_member]):"
    assert source.count(traversal) == 1
    mutant_source = source.replace(
        traversal,
        "for item_index, item in enumerate(reversed(collection[value_member])):",
    )
    namespace = dict(vars(runtime_execution))
    exec(compile(mutant_source, "<reverse-fold-runtime-mutant>", "exec"), namespace)
    mutant = namespace["evaluate_prepared_experiment"](prepared)
    assert isinstance(mutant, EvaluationArtifacts), mutant
    assert mutant.accepted is (target_order == 4321)
    members = {name: deepcopy(member.value) for name, member in mutant.members.items()}
    assert ("evaluation-run" if mutant.accepted else "experiment-verdict") in members
    event = next(
        row for row in members["event-trace"]["events"] if row["operation"] is not None
    )
    state = {row["name"]: row["value"] for row in event["state_after"]}
    assert state["ordered_value"] == 4321
    assert state["selected_items"]["value"] == [2, 1]
    assert all(
        validate_experiment_member(checked, name, value)
        for name, value in members.items()
    )
    assert not validate_experiment_artifact_set(checked, members)


def test_fold_post_state_replay_accepts_a_business_rollback_after_writes():
    kernel, language = mutable_authorities()
    package = next(
        row for row in language["language"]["packages"] if row["id"] == _OWNER
    )
    operation = next(
        row
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for row in closure["definitions"]
        if row["id"] == "bounded-fold-v1"
    )
    # The failed business precondition follows all three real state writes.
    operation["body"].append(
        {
            "node": "precondition-greater-than-or-equal",
            "left": "zero",
            "right": "counted",
            "outcome": "fold-declined",
        }
    )
    operation["outcomes"].append(
        {
            "id": "fold-declined",
            "kind": "gameplay-alternative",
            "state_policy": "rollback",
        }
    )
    operation["resource_bounds"]["max_steps"] += 1
    vectors = next(
        row
        for row in language.package_conformance_vector_sets
        if row["package_id"] == _OWNER
    )
    for vector in vectors["vector_definitions"]:
        if vector["id"] == "bounded-fold.bounded-fold-v1.body":
            vector["expect"] = deepcopy(operation["body"])
        elif vector["id"] == "bounded-fold.bounded-fold-v1.resource-bound":
            vector["expect"] = operation["resource_bounds"]["max_steps"]
    _bind_package_vector_set(package, vectors)
    _reidentify_graph_root(language)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    model = check_model_source_value(_source(), authority_context=context)
    assert isinstance(model, CheckedModel), model
    rir = compile_checked_model(model)["rir-semantic-payload"]
    program = admit_rir(rir, authority_context=context)
    specification = _specification(rir, [1, 2, 3, 4], count=0, order=0)
    specification["runtime"]["required_evaluator"]["instruction_nodes"].append(
        "precondition-greater-than-or-equal"
    )
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    prepared = prepare_experiment(checked)
    assert isinstance(prepared, PreparedExperiment), prepared
    outcome = evaluate_prepared_experiment(prepared)
    assert isinstance(outcome, EvaluationArtifacts), outcome
    assert outcome.accepted
    members = {name: deepcopy(member.value) for name, member in outcome.members.items()}
    event = next(
        row for row in members["event-trace"]["events"] if row["operation"] is not None
    )
    assert event["outcome"] == {
        "id": "fold-declined",
        "kind": "gameplay-alternative",
    }
    assert event["state_after"] == event["state_before"]
    assert validate_experiment_artifact_set(checked, members)


def _fold_case(*, variant: str = "ordinary", limit: int | None = None, items=None):
    kernel, language = mutable_authorities()
    package = next(
        row for row in language["language"]["packages"] if row["id"] == _OWNER
    )
    operations = {
        row["id"]: row
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for row in closure["definitions"]
        if row["id"].startswith("bounded")
    }
    root = operations["bounded-fold-v1"]
    order = operations["bounded.order-step"]
    if variant == "empty":
        count = operations["bounded.count-step"]
        count["body"] = []
        count["result"]["source"] = {"kind": "port", "name": "count"}
        count["resource_bounds"]["max_steps"] = 1
    elif variant == "pure-invoke":
        order["body"][-1] = {
            "node": "invoke",
            "site": "x/@0",
            "operation": {"package": "core.quantity", "id": "quantity.add"},
            "arguments": [
                {"port": "left", "operand": {"kind": "port", "port": "item"}},
                {"port": "right", "operand": {"kind": "literal", "literal": 1}},
            ],
            "result": {"kind": "local", "name": "next-order"},
            "outcomes": [],
        }
        order["resource_bounds"]["max_steps"] = 4
        root["resource_bounds"]["max_steps"] = 56
    elif variant == "nested":
        order["inputs"].append(
            {
                "access": "read",
                "id": "again",
                "value_kind": "nominal-structured",
                "type": {"package": _OWNER, "id": "IntList4"},
            }
        )
        order["body"] = [
            {
                "node": "fold",
                "site": "again",
                "target": "next-order",
                "value": "again",
                "initial": "accumulator",
                "operation": {"package": _OWNER, "id": "bounded.count-step"},
                "accumulator_port": "count",
                "item_port": "item",
                "arguments": [],
            }
        ]
        order["resource_bounds"]["max_steps"] = 13
        root["body"][4]["arguments"] = [
            {"port": "again", "operand": {"kind": "port", "port": "items"}}
        ]
        root["resource_bounds"]["max_steps"] = 92
    elif variant == "escaped":
        root["body"][4]["site"] = "x/@0~"
    else:
        assert variant == "ordinary"
    vectors = next(
        row
        for row in language.package_conformance_vector_sets
        if row["package_id"] == _OWNER
    )
    for vector in vectors["vector_definitions"]:
        for operation in operations.values():
            if vector["id"] == f"bounded-fold.{operation['id']}.body":
                vector["expect"] = deepcopy(operation["body"])
            elif vector["id"] == f"bounded-fold.{operation['id']}.resource-bound":
                vector["expect"] = operation["resource_bounds"]["max_steps"]
    _bind_package_vector_set(package, vectors)
    if limit is not None:
        runtime_package = next(
            row
            for row in language["language"]["packages"]
            if row["id"] == "standard.runtime"
        )
        profile = next(
            row
            for closure in runtime_package["semantic_closure"]
            if closure["authority_path"] == "language.runtime_profiles"
            for row in closure["definitions"]
            if row["id"] == "standard.exact-int64-event-v1"
        )
        profile["resource_bounds"]["max_event_steps"] = limit
        runtime_vectors = next(
            row
            for row in language.package_conformance_vector_sets
            if row["package_id"] == "standard.runtime"
        )
        _bind_package_vector_set(runtime_package, runtime_vectors)
    _reidentify_graph_root(language)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    source = _source()
    if variant == "escaped":
        source["entrypoints"][0]["id"] = "root/~@0"
    model = check_model_source_value(source, authority_context=context)
    assert isinstance(model, CheckedModel), model
    artifacts = compile_checked_model(model)
    rir = artifacts["rir-semantic-payload"]
    program = admit_rir(rir, authority_context=context)
    specification = _specification(rir, [_MAX, 1] if items is None else items)
    if variant == "escaped":
        specification["scenarios"][0]["event_plan"][0]["entrypoint"] = "root/~@0"
    if variant == "nested":
        specification["runtime"]["required_evaluator"]["instruction_nodes"].remove(
            "multiply"
        )
    if variant == "pure-invoke":
        specification["runtime"]["required_evaluator"]["instruction_nodes"].append(
            "invoke"
        )
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    prepared = prepare_experiment(checked)
    assert isinstance(prepared, PreparedExperiment), prepared
    outcome = evaluate_prepared_experiment(prepared)
    assert isinstance(outcome, RuntimeRefusalOutcome), outcome
    members = {
        name: deepcopy(member.value)
        for name, member in runtime_terminal_audit_members(
            checked,
            outcome,
            evaluator=prepared.evaluator,
            resolved_runtime=prepared.resolved_runtime,
        ).items()
    }
    assert validate_experiment_artifact_set(checked, members)
    return checked, members


@pytest.fixture(scope="module")
def ordered_overflow():
    checked, members = _fold_case()
    audit = members["runtime-terminal-audit"]
    assert audit["refusing_event"]["call_path"] == "fold/ordered-items/@1"
    assert audit["refusing_event"]["instruction_index"] == 1
    assert audit["refusing_event"]["attempted_calls"] == []
    assert audit["budget_counters"]["node_steps"] == 23
    return checked, members


@pytest.mark.parametrize(
    "path",
    [
        "forged/ordered-items/@1",
        "fold/ordered-items/@01",
        "fold/ordered-items/@-1",
        "fold/ordered-items/@2",
        "fold/ordered-items",
        "fold/ordered-items/@1/@0",
    ],
)
def test_fold_audit_rejects_unexecuted_dynamic_path(ordered_overflow, path):
    checked, members = ordered_overflow
    audit = deepcopy(members["runtime-terminal-audit"])
    audit["refusing_event"]["call_path"] = path
    _assert_reidentified_audit_refuses(checked, members, audit)


def test_fold_audit_rejects_a_different_selected_nonstep_reason(ordered_overflow):
    checked, members = ordered_overflow
    reason = next(
        row["definition"]
        for row in checked.rir["selected_semantics"]["diagnostic_reasons"]
        if row["definition"].get("signal") == "structured-list-capacity-exceeded"
    )
    audit = deepcopy(members["runtime-terminal-audit"])
    assert audit["diagnostic"]["code"] != reason["diagnostic"]
    audit["diagnostic"]["code"] = reason["diagnostic"]
    audit["refusing_event"]["reason"] = reason["diagnostic"]
    _assert_reidentified_audit_refuses(checked, members, audit)


@pytest.mark.parametrize(
    ("limit", "path", "index", "charge"),
    [
        (2, "fold", 2, 3),
        (3, "fold/filter-items/@0", 0, 4),
        (4, "fold/filter-items/@0", 0, 5),
    ],
)
def test_fold_setup_iteration_and_first_instruction_have_distinct_attempts(
    limit, path, index, charge
):
    checked, members = _fold_case(limit=limit, items=[1])
    audit = members["runtime-terminal-audit"]
    assert audit["refusing_event"]["call_path"] == path
    assert audit["refusing_event"]["instruction_index"] == index
    assert audit["refusing_event"]["call_site_identity"] is None
    assert audit["refusing_event"]["attempted_calls"] == []
    assert audit["budget_counters"]["event_steps"] == charge
    assert audit["budget_counters"]["node_steps"] == charge
    forged = deepcopy(audit)
    forged["budget_counters"]["event_steps"] += 1
    forged["budget_counters"]["node_steps"] += 1
    _assert_reidentified_audit_refuses(checked, members, forged)


def test_fold_empty_step_entry_refusal_has_no_executed_instruction_or_call_row():
    checked, members = _fold_case(variant="empty", limit=8, items=[1])
    audit = members["runtime-terminal-audit"]
    step = next(
        row["definition"]
        for row in checked.rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "bounded.count-step"
    )
    assert not step["body"]
    assert audit["refusing_event"]["call_path"] == "fold/count-selected/@0"
    assert audit["refusing_event"]["instruction_index"] == 0
    assert audit["refusing_event"]["attempted_calls"] == []
    assert audit["budget_counters"]["node_steps"] == 9
    forged = deepcopy(audit)
    forged["refusing_event"]["instruction_index"] = 1
    _assert_reidentified_audit_refuses(checked, members, forged)


def test_nested_fold_refusal_replays_both_actual_item_frames():
    checked, members = _fold_case(variant="nested", limit=21, items=[1, 2])
    audit = members["runtime-terminal-audit"]
    assert audit["refusing_event"]["call_path"] == "fold/ordered-items/@0/again/@0"
    assert audit["refusing_event"]["instruction_index"] == 0
    assert audit["refusing_event"]["call_site_identity"] is None
    assert audit["budget_counters"]["node_steps"] == 22
    forged = deepcopy(audit)
    forged["refusing_event"]["call_path"] = "fold/ordered-items/@1/again/@0"
    _assert_reidentified_audit_refuses(checked, members, forged)


def test_pure_invocation_requires_static_identity_without_an_event_outcome_row():
    checked, members = _fold_case(variant="pure-invoke", items=[_MAX])
    audit = members["runtime-terminal-audit"]
    site = next(row for row in checked.rir["call_sites"] if row["site"] == "x/@0")
    assert not site["outcomes"]
    assert audit["refusing_event"]["call_path"] == "fold/ordered-items/@0/x~1@0"
    assert audit["refusing_event"]["call_site_identity"] == site["identity"]
    assert audit["refusing_event"]["instruction_index"] == 0
    assert audit["refusing_event"]["attempted_calls"] == []
    forged = deepcopy(audit)
    forged["refusing_event"]["call_site_identity"] = None
    _assert_reidentified_audit_refuses(checked, members, forged)
    forged = deepcopy(audit)
    forged["refusing_event"]["attempted_calls"] = [
        {
            "site": "fold/ordered-items/@0/x~1@0",
            "call_site_identity": site["identity"],
            "operation": site["operation"],
            "outcome": {"id": "invented", "identity": site["identity"]},
            "arguments": [
                {
                    "formal_port_identity": row["port"]["identity"],
                    "actual_operand_identity": row["operand"]["identity"],
                }
                for row in site["arguments"]
            ],
            "result_identity": site["result"]["identity"],
        }
    ]
    _assert_reidentified_audit_refuses(checked, members, forged)


def test_dynamic_path_escapes_root_and_static_fold_site_reversibly():
    checked, members = _fold_case(variant="escaped")
    audit = members["runtime-terminal-audit"]
    assert audit["refusing_event"]["call_path"] == "root~1~0@0/x~1@0~0/@1"
    forged = deepcopy(audit)
    forged["refusing_event"]["call_path"] = "root/~@0/x/@0~/@1"
    _assert_reidentified_audit_refuses(checked, members, forged)


def test_independent_fold_admission_does_not_call_runtime_or_append_executor(
    ordered_overflow, monkeypatch
):
    from gda_balancing.domain import structured_values
    from gda_balancing.domain.runtime import execution

    checked, members = ordered_overflow

    def forbidden(*args, **kwargs):
        raise AssertionError("independent admission called the production executor")

    monkeypatch.setattr(execution, "_execute_value_instruction", forbidden)
    monkeypatch.setattr(structured_values, "append_typed_value", forbidden)
    assert validate_experiment_artifact_set(checked, members)


def test_intrinsic_fold_entry_rejects_a_real_but_inapplicable_static_call_identity():
    checked, members = _fold_case(variant="pure-invoke", limit=3, items=[1])
    audit = members["runtime-terminal-audit"]
    assert audit["refusing_event"]["call_path"] == "fold/filter-items/@0"
    assert audit["refusing_event"]["call_site_identity"] is None
    site = next(row for row in checked.rir["call_sites"] if row["site"] == "x/@0")
    forged = deepcopy(audit)
    forged["refusing_event"]["call_site_identity"] = site["identity"]
    _assert_reidentified_audit_refuses(checked, members, forged)
