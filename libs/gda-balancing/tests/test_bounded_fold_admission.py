"""Bounded pure collection composition through the actual authority judgment."""

from copy import deepcopy
import json
from pathlib import Path
from operator import setitem
from typing import Any, cast

import pytest

from gda_balancing.domain.authority.admission import project_operation_composition
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.operation_program import project_operation_program
from gda_balancing.domain.structured_values import (
    StructuredValueFault,
    append_typed_value,
    language_structured_value_index,
    list_type_contract,
)

_OWNER = "standard.conformance.structured"
_LIST = {"package": _OWNER, "id": "IntList4"}
_ROOT = (_OWNER, "bounded-fold-v1")


def _inputs():
    kernel, language = packaged_authority_context().mutable_pair()
    package = next(row for row in language.package_releases if row["id"] == _OWNER)
    definitions = next(
        row["definitions"]
        for row in package["semantic_closure"]
        if row["authority_path"] == "language.operations"
    )
    operations = {
        (_OWNER, row["id"]): row
        for row in definitions
        if row["id"].startswith("bounded")
    }
    return kernel, language, operations


def _judge(kernel, language, operations, **kwargs):
    return project_operation_composition(
        kernel, language, operations=operations, **kwargs
    )


def _program(operations, projection, root=_ROOT):
    return project_operation_program(
        root,
        operations,
        operation_node_ids={"invoke", "schedule", "fold"},
        invocation_node_ids={"invoke"},
        fold_input_bounds=projection.fold_input_bounds,
    )


def test_packaged_fold_derives_nominal_bounds_and_closed_reachability():
    kernel, language, operations = _inputs()
    projection = _judge(kernel, language, operations)
    assert projection.diagnostics == ()
    assert set(projection.fold_input_bounds.values()) == {4}
    assert len(projection.fold_input_bounds) == 3
    program = _program(operations, projection)
    assert program.resource_charge == 52
    assert program.reachable_operations == frozenset(operations)
    assert {"fold", "list-append", "less-than", "if"} <= program.node_ids
    with pytest.raises(TypeError):
        setitem(cast(Any, projection.fold_input_bounds), (_ROOT, "filter"), 0)


@pytest.mark.parametrize("bound, admitted", [(51, False), (52, True), (53, True)])
def test_fold_static_operation_budget_uses_transitive_work(bound, admitted):
    kernel, language, operations = _inputs()
    operations[_ROOT]["resource_bounds"]["max_steps"] = bound
    projection = _judge(kernel, language, operations)
    assert (projection.diagnostics == ()) is admitted
    if not admitted:
        assert projection.diagnostics == (
            f"language.operations.{_OWNER}.bounded-fold-v1.resource_bounds",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-step",
        "wrong-item",
        "wrong-initial",
        "same-port",
        "missing-environment",
        "wrong-environment",
        "writable-step",
        "event-step",
        "effect-step",
        "snapshot-step",
        "cycle",
        "wrong-append-item",
        "unpropagated-capacity",
        "duplicate-site",
        "extra-operand-member",
        "malformed-argument",
        "malformed-append-reference",
        "retired-callee-coordinate",
    ],
)
def test_fold_rejects_invalid_types_capture_effects_and_cycles(mutation):
    kernel, language, operations = _inputs()
    wrapper = operations[_ROOT]
    step = operations[(_OWNER, "bounded.filter-step")]
    fold = wrapper["body"][2]
    if mutation == "missing-step":
        del operations[(_OWNER, "bounded.filter-step")]
    elif mutation == "wrong-item":
        fold["item_port"] = "selected"
    elif mutation == "wrong-initial":
        fold["initial"] = "zero"
    elif mutation == "same-port":
        fold["accumulator_port"] = fold["item_port"]
    elif mutation == "missing-environment":
        fold["arguments"] = []
    elif mutation == "wrong-environment":
        fold["arguments"][0]["operand"] = {"kind": "port", "port": "items"}
    elif mutation == "writable-step":
        step["inputs"][0]["access"] = "read-write"
    elif mutation == "event-step":
        step["operation_kind"] = "event-program"
    elif mutation == "effect-step":
        step["effects"] = ["snapshot.commit"]
    elif mutation == "snapshot-step":
        step["extensions"] = {"standard.snapshot-operands": {"operands": []}}
    elif mutation == "cycle":
        step["body"] = [deepcopy(fold)]
        step["body"][0].update(
            value="selected", initial="selected", target="next-selected"
        )
        step["body"][0]["arguments"] = [
            {"port": "threshold", "operand": {"kind": "port", "port": "threshold"}}
        ]
    elif mutation == "wrong-append-item":
        step["body"][1]["item"] = "selected"
    elif mutation == "unpropagated-capacity":
        step["refusals"] = []
    elif mutation == "duplicate-site":
        wrapper["body"][3]["site"] = fold["site"]
    elif mutation == "extra-operand-member":
        fold["arguments"][0]["operand"]["ambient"] = True
    elif mutation == "malformed-argument":
        fold["arguments"] = [False]
    elif mutation == "malformed-append-reference":
        step["body"][1]["item"] = []
    elif mutation == "retired-callee-coordinate":
        fold["operation"]["version"] = "old"
    assert _judge(kernel, language, operations).diagnostics


def test_nested_fold_dag_uses_product_bound_without_unrolling():
    kernel, language, operations = _inputs()
    counter = operations[(_OWNER, "bounded.count-step")]
    inner = deepcopy(counter)
    inner["id"] = "nested.inner"
    inner["inputs"][1] = {
        "id": "item",
        "access": "read",
        "type": _LIST,
        "value_kind": "nominal-structured",
    }
    inner["body"] = [
        {
            "node": "fold",
            "site": "inner",
            "target": "next-count",
            "value": "item",
            "initial": "count",
            "operation": {"package": _OWNER, "id": counter["id"]},
            "accumulator_port": "count",
            "item_port": "item",
            "arguments": [],
        }
    ]
    inner["resource_bounds"]["max_steps"] = 13
    outer = deepcopy(inner)
    outer["id"] = "nested.outer"
    outer["inputs"][1]["type"] = {"kind": "list", "element": _LIST, "maximum_length": 2}
    outer["body"][0]["operation"]["id"] = inner["id"]
    outer["body"][0]["site"] = "outer"
    outer["resource_bounds"]["max_steps"] = 29
    operations[(_OWNER, inner["id"])] = inner
    operations[(_OWNER, outer["id"])] = outer
    projection = _judge(kernel, language, operations)
    assert projection.diagnostics == ()
    assert _program(operations, projection, (_OWNER, outer["id"])).resource_charge == 29
    outer["resource_bounds"]["max_steps"] = 28
    assert _judge(kernel, language, operations).diagnostics == (
        f"language.operations.{_OWNER}.nested.outer.resource_bounds",
    )


def test_event_snapshot_contract_is_explicit_and_pure_capture_still_refuses():
    kernel, language, operations = _inputs()
    wrapper = operations[_ROOT]
    threshold = wrapper["inputs"].pop()
    wrapper["extensions"] = {
        "standard.snapshot-operands": {
            "operands": [
                {
                    "name": "threshold",
                    "resolved_symbol": {"module": "fold", "symbol": "threshold"},
                }
            ]
        }
    }
    wrapper["body"][2]["arguments"][0]["operand"] = {
        "kind": "local",
        "local": "threshold",
    }
    assert _judge(kernel, language, operations).diagnostics
    assert (
        _judge(
            kernel,
            language,
            operations,
            snapshot_contracts={_ROOT: {"threshold": threshold}},
        ).diagnostics
        == ()
    )


@pytest.mark.parametrize(
    "values,item,expected",
    [([], 1, [1]), ([1, 1], 1, [1, 1, 1]), ([1, 2, 3], 4, [1, 2, 3, 4])],
)
def test_typed_append_preserves_nominal_owner_order_duplicates_and_input(
    values, item, expected
):
    kernel, language, _operations = _inputs()
    authority = language_structured_value_index(language, kernel=kernel)
    original = {"type": _LIST, "value": values}
    before = deepcopy(original)
    result = append_typed_value(original, item, authority=authority, resource_limit=100)
    assert result == {"type": _LIST, "value": expected}
    assert original == before
    assert list_type_contract(_LIST, authority=authority) == (
        {"package": "core.quantity", "id": "Quantity"},
        4,
    )


def test_typed_append_capacity_is_a_distinct_selected_runtime_refusal():
    kernel, language, _operations = _inputs()
    authority = language_structured_value_index(language, kernel=kernel)
    with pytest.raises(StructuredValueFault) as fault:
        append_typed_value(
            {"type": _LIST, "value": [1, 2, 3, 4]},
            5,
            authority=authority,
            resource_limit=100,
        )
    assert (fault.value.signal, fault.value.pointer) == (
        "structured-list-capacity-exceeded",
        "/value",
    )


def test_typed_append_rejects_bool_in_a_quantity_list_before_capacity():
    kernel, language, _operations = _inputs()
    authority = language_structured_value_index(language, kernel=kernel)
    with pytest.raises(StructuredValueFault) as fault:
        append_typed_value(
            {"type": _LIST, "value": [1, 2, 3, 4]},
            True,
            authority=authority,
            resource_limit=100,
        )
    assert fault.value.signal == "structured-value-type-mismatch"


@pytest.mark.parametrize("body_steps, expected_bound", [(0, 44), (1, 48)])
def test_fold_invocation_charge_does_not_consume_the_new_step_budget(
    body_steps, expected_bound
):
    kernel, language, operations = _inputs()
    step = operations[(_OWNER, "bounded.count-step")]
    step["body"] = [{"node": "copy", "target": "next-count", "value": "count"}]
    if body_steps == 0:
        step["body"] = []
        step["result"]["source"] = {"kind": "port", "name": "count"}
    step["resource_bounds"]["max_steps"] = 1
    step["refusals"] = []
    projection = _judge(kernel, language, operations)
    assert projection.diagnostics == ()
    assert _program(operations, projection).resource_charge == expected_bound


@pytest.mark.parametrize(
    "artifact_kind, owner_path",
    [
        ("capability-manifest", ("operations",)),
        ("package-lock", ("operations",)),
        ("package-lock", ("selected_semantics", "operations")),
        ("rir-semantic-payload", ("selected_semantics", "operations")),
    ],
)
@pytest.mark.parametrize("inside_guard", [False, True])
def test_operation_artifact_wires_admit_fold_and_append_with_closed_members(
    artifact_kind, owner_path, inside_guard
):
    import jsonschema

    _kernel, language, operations = _inputs()
    schema = next(
        row["schema"]
        for row in language["language"]["artifact_wire_schemas"]
        if row["artifact_kind"] == artifact_kind
    )
    for member in owner_path:
        schema = schema["properties"][member]
    body_schema = schema["items"]["properties"]["definition"]["properties"]["body"]
    if inside_guard:
        body_schema = body_schema["items"]["properties"]["body"]
    assert jsonschema.Draft202012Validator(body_schema).is_valid([])
    validator = jsonschema.Draft202012Validator(body_schema["items"])
    for instruction in (
        operations[_ROOT]["body"][2],
        operations[(_OWNER, "bounded.filter-step")]["body"][1],
    ):
        validator.validate(instruction)
        invalid = {**instruction, "undeclared_capture": "threshold"}
        with pytest.raises(jsonschema.ValidationError, match="Unevaluated properties"):
            validator.validate(invalid)


def test_selected_runtime_node_wire_covers_each_declared_law_with_closed_semantics():
    import jsonschema

    kernel, language, _operations = _inputs()
    rir = next(
        row["schema"]
        for row in language["language"]["artifact_wire_schemas"]
        if row["artifact_kind"] == "rir-semantic-payload"
    )
    schema = rir["properties"]["selected_semantics"]["properties"]["execution_laws"][
        "properties"
    ]["runtime_program"]["properties"]["nodes"]["items"]
    validator = jsonschema.Draft202012Validator(schema)
    nodes = kernel["meta_format"]["runtime_program"]["nodes"]
    assert [node["id"] for node in nodes if not validator.is_valid(node)] == []
    for node in nodes:
        invalid = deepcopy(node)
        invalid["semantics"]["undeclared_host_behavior"] = True
        assert not validator.is_valid(invalid), node["id"]


def test_guarded_fold_bounds_use_the_real_operation_frame():
    kernel, language, operations = _inputs()
    wrapper = operations[_ROOT]
    wrapper["body"] = [
        {"node": "constant", "target": "boundary-zero", "literal": 0},
        {
            "node": "less-than",
            "target": "enter",
            "left": "boundary-zero",
            "right": "threshold",
        },
        {
            "node": "guard-block",
            "condition": "enter",
            "body": wrapper["body"],
            "outcome": "folded",
        },
    ]
    wrapper["result"]["source"] = {"kind": "port", "name": "ordered_value"}
    wrapper["resource_bounds"]["max_steps"] = 55
    projection = _judge(kernel, language, operations)
    assert projection.diagnostics == ()
    assert {coordinate for coordinate, _site in projection.fold_input_bounds} == {_ROOT}
    assert len(projection.fold_input_bounds) == 3
    assert _program(operations, projection).resource_charge == 55


def test_transparent_guard_and_outer_body_cannot_reuse_one_call_site():
    kernel, language, operations = _inputs()
    wrapper = operations[_ROOT]
    filtering = deepcopy(wrapper["body"][2])
    ordering = deepcopy(wrapper["body"][4])
    ordering["site"] = filtering["site"]
    wrapper["body"] = [
        *wrapper["body"][:2],
        {"node": "less-than", "target": "enter", "left": "zero", "right": "threshold"},
        {
            "node": "guard-block",
            "condition": "enter",
            "body": [filtering],
            "outcome": "folded",
        },
        ordering,
    ]
    wrapper["resource_bounds"]["max_steps"] = 100
    projection = _judge(kernel, language, operations)
    assert projection.diagnostics == (
        f"language.operations.{_OWNER}.bounded-fold-v1.body.filter-items.site",
    )


def test_transparent_guard_and_outer_invoke_share_site_uniqueness():
    kernel, language, operations = _inputs()
    wrapper = operations[_ROOT]
    call = {
        "node": "invoke",
        "site": "count-items",
        "operation": {"package": _OWNER, "id": "bounded.count-step"},
        "arguments": [
            {"port": "count", "operand": {"kind": "port", "port": "selected_count"}},
            {"port": "item", "operand": {"kind": "port", "port": "threshold"}},
        ],
        "result": {"kind": "local", "name": "next-count"},
        "outcomes": [],
    }
    wrapper["body"] = [
        {"node": "constant", "target": "zero", "literal": 0},
        {"node": "less-than", "target": "enter", "left": "zero", "right": "threshold"},
        {
            "node": "guard-block",
            "condition": "enter",
            "body": [deepcopy(call)],
            "outcome": "folded",
        },
        call,
    ]
    wrapper["result"]["source"] = {"kind": "port", "name": "ordered_value"}
    wrapper["resource_bounds"]["max_steps"] = 9
    assert _judge(kernel, language, operations).diagnostics == (
        f"language.operations.{_OWNER}.bounded-fold-v1.body.count-items.site",
    )
    # A distinct site changes no type, call graph, or resource requirement.
    call["site"] = "outside-count"
    projection = _judge(kernel, language, operations)
    assert projection.diagnostics == ()
    assert _program(operations, projection).resource_charge == 9


def test_empty_pure_fold_step_survives_admitted_model_check_and_build():
    from gda_balancing.domain.authority.admission import admit_authorities
    from gda_balancing.domain.model import (
        CheckedModel,
        check_model_source_value,
        compile_checked_model,
    )
    from schema2_bootstrap_conformance_support import _bind_package_vector_set
    from schema2_bootstrap_production_support import _reidentify_graph_root

    kernel, language = packaged_authority_context().mutable_pair()
    package = next(
        row for row in language["language"]["packages"] if row["id"] == _OWNER
    )
    step = next(
        definition
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for definition in closure["definitions"]
        if definition["id"] == "bounded.count-step"
    )
    step["body"] = []
    step["result"]["source"] = {"kind": "port", "name": "count"}
    step["resource_bounds"]["max_steps"] = 1
    vectors = next(
        row
        for row in language.package_conformance_vector_sets
        if row["package_id"] == _OWNER
    )
    for vector in vectors["vector_definitions"]:
        if (
            vector.get("operation") == step["id"]
            and vector["kind"] == "operation-contract"
        ):
            if vector["probe"]["path"] == "body":
                vector["expect"] = []
            elif vector["probe"]["path"] == "resource_bounds.max_steps":
                vector["expect"] = 1
    _bind_package_vector_set(package, vectors)
    _reidentify_graph_root(language)
    admission = admit_authorities(kernel, language)
    assert admission.admitted, admission.diagnostics
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/bounded-fold/model-source.json"
        ).read_text()
    )
    checked = check_model_source_value(source, kernel=kernel, language_bundle=language)
    assert isinstance(checked, CheckedModel), checked
    artifacts = compile_checked_model(checked)
    assert set(artifacts) == {
        "build-receipt",
        "capability-manifest",
        "debug-map",
        "model-explanation",
        "package-lock",
        "resolution-receipt",
        "resolved-model",
        "rir-semantic-payload",
    }
    selected = cast(
        dict[str, Any], artifacts["rir-semantic-payload"]["selected_semantics"]
    )
    selected_step = next(
        row["definition"]
        for row in selected["operations"]
        if row["package"] == _OWNER and row["definition"]["id"] == step["id"]
    )
    assert selected_step["body"] == []
    assert selected_step["result"]["source"] == {"kind": "port", "name": "count"}
