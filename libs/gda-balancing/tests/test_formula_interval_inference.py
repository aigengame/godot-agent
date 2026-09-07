"""Actual Formula transfer rules checked against concrete integer selections."""

from itertools import product
from typing import cast

import pytest

from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.graph import LanguageBundleIndex
from gda_balancing.domain.formula.inference import infer_formula_operation_result
from gda_balancing.domain.formula.notation import (
    FormulaNotationRefusal,
    parse_formula_expression,
)
from gda_balancing.domain.formula.types import formula_contract_from_operation


MINIMUM, MAXIMUM = -(1 << 63), (1 << 63) - 1


@pytest.fixture(scope="module")
def inference_authority():
    context = packaged_authority_context()
    profile = next(
        row
        for row in context.language_bundle["language"]["resolution_profiles"]
        if row.get("default") is True
    )
    return (
        profile["extensions"]["standard.formula"]["notation_conversion"],
        formula_contract_from_operation(
            context.kernel["meta_format"]["runtime_program"]["fixed_value_contracts"][
                "kernel-boolean"
            ]
        ),
    )


def _contract(bounds):
    return {
        "domain": {"minimum": bounds[0], "maximum": bounds[1]},
        "domain_kind": "closed-interval",
        "kind": "scalar",
        "unit": "1",
        "representation": "Int",
        "numeric_policy": "exact-int64",
        "type_identity": {"package": "core.quantity", "id": "Quantity"},
    }


def _selection(true_name, false_name, *, relation="independent", inverse=False):
    body = []
    compared = "y"
    if relation == "same":
        compared = "x"
    elif relation == "copy":
        body.append({"node": "copy", "value": "x", "target": "copied"})
        compared = "copied"
    body.append(
        {"node": "less-than", "left": "x", "right": compared, "target": "condition"}
    )
    body.append(
        {
            "node": "if",
            "condition": "condition",
            "target": "result",
            "when_true": false_name if inverse else true_name,
            "when_false": true_name if inverse else false_name,
        }
    )
    return {"body": body, "result": {"source": {"kind": "local", "name": "result"}}}


def _inferred(operation, x, y, authority, z=(-1, 1)):
    policy, boolean = authority
    contracts = [_contract(bounds) for bounds in (x, y, z)]
    result = infer_formula_operation_result(
        operation,
        ["x", "y", "z"],
        contracts,
        contracts[0],
        policy,
        {},
        boolean_contract=boolean,
    )
    assert {k: v for k, v in result.items() if k != "domain"} == {
        k: v for k, v in contracts[0].items() if k != "domain"
    }
    return result["domain"]["minimum"], result["domain"]["maximum"]


def _concrete(x, y, selected_true, selected_false, relation, inverse=False, z=(-1, 1)):
    # This oracle enumerates actual independent input values. It has no transfer
    # functions, inference imports, saturation or extremum-pattern recognition.
    values = []
    for a, b, c in product(
        range(x[0], x[1] + 1), range(y[0], y[1] + 1), range(z[0], z[1] + 1)
    ):
        condition = a < (b if relation == "independent" else a)
        selected = selected_true if condition != inverse else selected_false
        values.append({"x": a, "y": b, "z": c, "copied": a}[selected])
    return min(values), max(values)


def test_production_selection_intervals_match_finite_concrete_enumeration(
    inference_authority,
):
    intervals = [(lo, hi) for lo in range(-2, 3) for hi in range(lo, 3)]
    checked = 0
    for x, y, when_true, when_false, inverse in product(
        intervals, intervals, ("x", "y", "z"), ("x", "y", "z"), (False, True)
    ):
        operation = _selection(when_true, when_false, inverse=inverse)
        actual = _inferred(operation, x, y, inference_authority)
        expected = _concrete(x, y, when_true, when_false, "independent", inverse)
        assert actual == expected, (
            x,
            y,
            when_true,
            when_false,
            inverse,
            actual,
            expected,
        )
        checked += 1
    assert checked == 4050


@pytest.mark.parametrize("relation", ("same", "copy", "independent"))
def test_operand_origins_remain_sound_without_aliasing_equal_domains(
    inference_authority, relation
):
    x, y = (-2, 2), (-2, 2)
    operation = _selection("z", "x", relation=relation)
    expected = _concrete(x, y, "z", "x", relation, z=(100, 100))
    actual = _inferred(operation, x, y, inference_authority, z=(100, 100))
    assert actual[0] <= expected[0] <= expected[1] <= actual[1]
    if relation == "same":
        assert actual == (-2, 2)
    elif relation == "independent":
        assert actual == (-2, 100)
    # Copy-related inputs may conservatively retain the unreachable branch;
    # equality of contracts alone must never be promoted to value identity.


@pytest.mark.parametrize(
    ("x", "y", "true_name", "false_name", "expected"),
    [
        ((-1000, 4040), (0, 0), "y", "x", (0, 4040)),
        ((-10, 5), (0, 10), "x", "y", (-10, 5)),
        ((-5, -2), (4, 7), "y", "x", (4, 7)),
        ((0, 0), (0, 0), "z", "x", (0, 0)),
        ((MINIMUM, MAXIMUM), (MINIMUM, MAXIMUM), "y", "x", (MINIMUM, MAXIMUM)),
        ((MINIMUM, MINIMUM), (MINIMUM, MINIMUM), "z", "x", (MINIMUM, MINIMUM)),
        ((MAXIMUM, MAXIMUM), (MAXIMUM, MAXIMUM), "z", "x", (MAXIMUM, MAXIMUM)),
        ((MAXIMUM - 1, MAXIMUM), (MAXIMUM, MAXIMUM), "y", "x", (MAXIMUM, MAXIMUM)),
        ((MINIMUM, MINIMUM + 1), (MINIMUM, MINIMUM), "y", "x", (MINIMUM, MINIMUM + 1)),
    ],
    ids=[
        "cross-zero-floor",
        "different-minimum",
        "disjoint-maximum",
        "unreachable-singleton",
        "full-int64",
        "minimum-unreachable",
        "maximum-unreachable",
        "adjacent-maximum",
        "adjacent-minimum",
    ],
)
def test_production_selection_extreme_and_unreachable_bounds(
    inference_authority, x, y, true_name, false_name, expected
):
    assert (
        _inferred(_selection(true_name, false_name), x, y, inference_authority)
        == expected
    )


def test_rebinding_a_compared_local_does_not_reuse_its_previous_predicate(
    inference_authority,
):
    operation = _selection("y", "x")
    operation["body"].insert(1, {"node": "constant", "literal": 100, "target": "x"})
    # Original inputs x=-1 or 1, y=0: the captured condition chooses 0 or the
    # newly assigned 100. Treating the comparison as x=100 < 0 would lose 0.
    assert _inferred(operation, (-1, 1), (0, 0), inference_authority) == (0, 100)


@pytest.mark.parametrize("axis", ("nominal", "unit", "numeric"))
@pytest.mark.parametrize("condition_true", (False, True))
def test_public_formula_selection_refuses_mixed_contracts_even_for_unreachable_branch(
    axis, condition_true
):
    context = packaged_authority_context()
    quantity = _contract((0, 1))
    quantity.pop("type_identity")
    quantity["type"] = "quantity"
    low, high = ((0, 0), (1, 1)) if condition_true else ((1, 1), (0, 0))
    request = {
        "schema_version": "2.0.0",
        "package_requirements": ["core.quantity"],
        "module": {
            "id": "main",
            "imports": [
                {"alias": "quantity", "package": "core.quantity", "symbol": "Quantity"}
            ],
        },
        "formula": {
            "id": "mixed",
            "parameters": [
                {
                    "id": "low",
                    **quantity,
                    "domain": {"minimum": low[0], "maximum": low[1]},
                },
                {
                    "id": "high",
                    **quantity,
                    "domain": {"minimum": high[0], "maximum": high[1]},
                },
                {"id": "left", **quantity},
                {"id": "other", **quantity},
            ],
            "result": quantity,
            "expression": "let condition = low < high;\nlet selected = if condition then left else other;\nselected",
        },
    }
    assert parse_formula_expression(request, context)["result"] == {
        "kind": "local",
        "local": "selected",
    }
    incompatible = request["formula"]["parameters"][-1]
    if axis == "nominal":
        boolean = formula_contract_from_operation(
            context.kernel["meta_format"]["runtime_program"]["fixed_value_contracts"][
                "kernel-boolean"
            ]
        )
        boolean.pop("type_identity")
        incompatible.clear()
        incompatible.update({"id": "other", "type": "Boolean", **boolean})
    elif axis == "unit":
        incompatible["unit"] = "turn"
    else:
        incompatible["numeric_policy"] = "exact-bool"
    with pytest.raises(FormulaNotationRefusal) as refused:
        parse_formula_expression(request, context)
    assert refused.value.reason_id == "model.reason.formula-type-mismatch"


def test_narrow_inference_does_not_hide_an_eager_unselected_overflow(
    inference_authority,
):
    from schema2_value_program_production_support import evaluate_value_program_vector
    from schema2_value_program_reference_support import (
        reference_evaluate_value_program_vector,
    )

    context = packaged_authority_context()
    vector = next(
        vector
        for vector_set in cast(
            LanguageBundleIndex, context.language_bundle
        ).package_conformance_vector_sets
        if vector_set["package_id"] == "standard.runtime"
        for vector in vector_set["vector_definitions"]
        if vector["id"] == "formula.runtime.selection.eager-unselected-overflow"
    )
    operands = vector["input"]["operands"]
    contracts = [_contract((row["value"], row["value"])) for row in operands]
    policy, boolean = inference_authority
    result = infer_formula_operation_result(
        {
            "body": [row["instruction"] for row in vector["input"]["instructions"]],
            "result": {"source": {"kind": "local", "name": "result"}},
        },
        [row["name"] for row in operands],
        contracts,
        contracts[0],
        policy,
        {},
        boolean_contract=boolean,
    )
    assert result["domain"] == {"minimum": 0, "maximum": 0}
    assert vector["expect"] == {
        "cache_entries": 0,
        "charge": 3,
        "outcome": "refused",
        "result": None,
        "result_artifact": False,
        "signal": "numeric-overflow",
        "site": "value-site.selection.eager-unselected-overflow.overflow",
    }
    assert reference_evaluate_value_program_vector(vector) == vector["expect"]
    for phase in ("initialization", "event", "observation"):
        assert (
            evaluate_value_program_vector(context.kernel, vector, phase=phase)
            == vector["expect"]
        )
