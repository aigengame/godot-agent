from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.formula.types import formula_contract_from_operation
from gda_balancing.domain.model._operation_call_domain_adapters import (
    resolved_rir_entrypoint_call,
    resolved_source_entrypoint_call,
)
from gda_balancing.domain.model._resolution import _formula_policy
from gda_balancing.domain.operation_call_domains import (
    ConcreteOperationCallDomainError,
    ConcreteOperationCallDomainInput,
    project_concrete_operation_call_domains,
)


ROOT = ("test.calls", "1.0.0", "root")
MIDDLE = ("test.calls", "1.0.0", "middle")
LEAF = ("test.calls", "1.0.0", "leaf")
LEAF_SLOT = (*LEAF, "scale-policy")


def test_projects_nested_schedule_guard_results_literals_and_snapshot_domains() -> None:
    projection = project_concrete_operation_call_domains(_projection_input())

    assert list(projection.calls) == [ROOT, MIDDLE, LEAF]
    assert len(projection.calls[LEAF]) == 2
    assert projection.calls[LEAF][0]["known_arguments"] == {"factor": 2}
    assert projection.slot_parameter_contracts[LEAF_SLOT] == [
        {"scaled": _quantity_formula_contract(8, 12)},
        {"scaled": _quantity_formula_contract(24, 36)},
    ]


def test_projects_the_reproduced_nested_formula_domain_mismatch() -> None:
    projection = project_concrete_operation_call_domains(_projection_input())
    actual = projection.slot_parameter_contracts[LEAF_SLOT][1]["scaled"]

    assert actual["domain"] == {"minimum": 24, "maximum": 36}
    assert not (0 <= actual["domain"]["minimum"] and actual["domain"]["maximum"] <= 20)


@pytest.mark.parametrize(
    ("mutate", "expected_code", "expected_coordinate"),
    [
        (
            lambda inp: inp.roots[ROOT][0].update({"arguments": {}}),
            "incomplete_arguments",
            ROOT,
        ),
        (
            lambda inp: inp.operations[MIDDLE]["body"].insert(
                0,
                {
                    "node": "invoke",
                    "site": "cycle",
                    "operation": _operation_ref(ROOT),
                    "arguments": [
                        {
                            "port": "value",
                            "operand": {"kind": "port", "port": "value"},
                        }
                    ],
                    "result": {"kind": "local", "name": "cycle_result"},
                },
            ),
            "operation_call_cycle",
            ROOT,
        ),
        (
            lambda inp: inp.operations[MIDDLE]["body"][0].update(
                {"operation": "malformed"}
            ),
            "malformed_operation_reference",
            MIDDLE,
        ),
        (
            lambda inp: inp.operations[MIDDLE]["body"][0].update(
                {"operation": _operation_ref(LEAF) | {"extra": "member"}}
            ),
            "malformed_operation_reference",
            MIDDLE,
        ),
        (
            lambda inp: inp.operations[MIDDLE]["body"][0].update(
                {"operation": _operation_ref(LEAF) | {"id": ""}}
            ),
            "malformed_operation_reference",
            MIDDLE,
        ),
    ],
)
def test_returns_typed_failures_with_stable_operation_coordinates(
    mutate: Any,
    expected_code: str,
    expected_coordinate: tuple[str, str, str],
) -> None:
    projection_input = _projection_input()
    mutate(projection_input)

    with pytest.raises(ConcreteOperationCallDomainError) as failure:
        project_concrete_operation_call_domains(projection_input)

    assert failure.value.code == expected_code
    assert failure.value.coordinate == expected_coordinate


def test_source_and_rir_adapters_resolve_the_same_event_reference_contract() -> None:
    context = packaged_authority_context()
    operation = {"inputs": [{"id": "event"}]}
    source_call = resolved_source_entrypoint_call(
        {"arguments": [{"port": "event", "operand": {"kind": "event-reference"}}]},
        operation,
        {},
        context.kernel,
        context.language_bundle,
    )
    rir_call = resolved_rir_entrypoint_call(
        {
            "arguments": [
                {
                    "port": {"name": "event"},
                    "operand": {"kind": "event-reference"},
                }
            ]
        },
        operation,
        {},
        context.kernel,
    )

    assert source_call is not None
    assert rir_call is not None
    assert source_call["arguments"] == rir_call["arguments"]
    assert source_call["known_arguments"] == rir_call["known_arguments"] == {}


def _projection_input() -> ConcreteOperationCallDomainInput:
    context = packaged_authority_context()
    operations = _operations()
    return ConcreteOperationCallDomainInput(
        operations=operations,
        roots={
            ROOT: [
                {
                    "arguments": {"value": _quantity_formula_contract(4, 6)},
                    "known_arguments": {},
                }
            ]
        },
        formula_slot_bindings=frozenset({LEAF_SLOT}),
        operation_node_ids=frozenset({"invoke", "schedule"}),
        conversion_policy=deepcopy(
            _formula_policy(context.language_bundle)["notation_conversion"]
        ),
        literal_contract=_literal_contract,
        snapshot_contracts={MIDDLE: {"bonus": _quantity_formula_contract(3, 3)}},
        snapshot_operand_names={MIDDLE: frozenset({"bonus"})},
    )


def _operations() -> dict[tuple[str, str, str], dict[str, Any]]:
    leaf = {
        "id": LEAF[2],
        "inputs": [
            _quantity_operation_contract("value"),
            _quantity_operation_contract("factor"),
        ],
        "body": [
            {
                "node": "multiply",
                "left": "value",
                "right": "factor",
                "target": "scaled",
            }
        ],
        "result": {
            **_quantity_operation_contract("result"),
            "source": {"kind": "local", "name": "scaled"},
        },
        "extensions": {
            "standard.formula-slots": [
                {
                    "id": LEAF_SLOT[3],
                    "parameters": [
                        {
                            **_quantity_operation_contract("scaled"),
                            "source": {"kind": "local", "name": "scaled"},
                        }
                    ],
                }
            ]
        },
    }
    middle = {
        "id": MIDDLE[2],
        "inputs": [_quantity_operation_contract("value")],
        "body": [
            {
                "node": "invoke",
                "site": "literal-scale",
                "operation": _operation_ref(LEAF),
                "arguments": [
                    {
                        "port": "value",
                        "operand": {"kind": "port", "port": "value"},
                    },
                    {
                        "port": "factor",
                        "operand": {"kind": "literal", "literal": 2},
                    },
                ],
                "result": {"kind": "local", "name": "first"},
            },
            {
                "node": "invoke",
                "site": "snapshot-scale",
                "operation": _operation_ref(LEAF),
                "arguments": [
                    {
                        "port": "value",
                        "operand": {"kind": "local", "local": "first"},
                    },
                    {
                        "port": "factor",
                        "operand": {"kind": "local", "local": "bonus"},
                    },
                ],
                "result": {"kind": "local", "name": "final"},
            },
        ],
        "result": {
            **_quantity_operation_contract("result"),
            "source": {"kind": "local", "name": "final"},
        },
        "extensions": {
            "standard.snapshot-operands": {
                "operands": [
                    {
                        "name": "bonus",
                        "resolved_symbol": {"module": "test", "name": "bonus"},
                    }
                ]
            }
        },
    }
    root = {
        "id": ROOT[2],
        "inputs": [_quantity_operation_contract("value")],
        "body": [
            {
                "node": "guard",
                "body": [
                    {
                        "node": "schedule",
                        "site": "scheduled-middle",
                        "operation": _operation_ref(MIDDLE),
                        "arguments": [
                            {
                                "port": "value",
                                "operand": {"kind": "port", "port": "value"},
                            }
                        ],
                        "result": {"kind": "local", "name": "scheduled"},
                    }
                ],
            }
        ],
        "result": {
            **_quantity_operation_contract("result"),
            "source": {"kind": "local", "name": "scheduled"},
        },
    }
    return {ROOT: root, MIDDLE: middle, LEAF: leaf}


def _operation_ref(coordinate: tuple[str, str, str]) -> dict[str, str]:
    return {
        "package": coordinate[0],
        "version": coordinate[1],
        "id": coordinate[2],
    }


def _quantity_operation_contract(name: str) -> dict[str, Any]:
    return {
        "id": name,
        "type": {
            "package": "core.quantity",
            "version": "2.2.0",
            "id": "Quantity",
        },
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain": {"kind": "actual"},
        "numeric_policy": "exact-int64",
    }


def _quantity_formula_contract(minimum: int, maximum: int) -> dict[str, Any]:
    return {
        "type_identity": {
            "package": "core.quantity",
            "version": "2.2.0",
            "symbol": "Quantity",
        },
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": minimum, "maximum": maximum},
        "numeric_policy": "exact-int64",
    }


def _literal_contract(value: Any, formal: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return {
        **formula_contract_from_operation(formal),
        "domain_kind": "closed-interval",
        "domain": {"minimum": value, "maximum": value},
    }
