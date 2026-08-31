"""Concrete value-domain propagation through admitted Operation call graphs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from gda_balancing.domain.formula.inference import (
    infer_formula_operation_local_contract,
    infer_formula_operation_result,
    infer_formula_slot_parameter_contract,
)
from gda_balancing.domain.formula.types import formula_contract_from_operation


OperationCoordinate = tuple[str, str, str]
OperationSlotCoordinate = tuple[str, str, str, str]
LiteralContractResolver = Callable[[Any, dict[str, Any]], dict[str, Any] | None]


class ConcreteOperationCallDomainError(ValueError):
    """One typed failure while propagating a concrete Operation call domain."""

    def __init__(
        self,
        code: str,
        message: str,
        coordinate: OperationCoordinate | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.coordinate = coordinate


@dataclass(frozen=True)
class ConcreteOperationCallDomainInput:
    """Neutral input for one production Operation call-domain projection."""

    operations: dict[OperationCoordinate, dict[str, Any]]
    roots: dict[OperationCoordinate, list[dict[str, Any]]]
    formula_slot_bindings: frozenset[OperationSlotCoordinate]
    operation_node_ids: frozenset[str]
    conversion_policy: dict[str, Any]
    literal_contract: LiteralContractResolver
    snapshot_contracts: dict[OperationCoordinate, dict[str, dict[str, Any]]]
    snapshot_operand_names: dict[OperationCoordinate, frozenset[str]]


@dataclass(frozen=True)
class ConcreteOperationCallDomainProjection:
    """Concrete calls and Formula-slot parameter contracts reached from roots."""

    calls: dict[OperationCoordinate, list[dict[str, Any]]]
    slot_parameter_contracts: dict[
        OperationSlotCoordinate, list[dict[str, dict[str, Any]]]
    ]


def project_concrete_operation_call_domains(
    projection_input: ConcreteOperationCallDomainInput,
) -> ConcreteOperationCallDomainProjection:
    """Propagate exact contracts to every bound Operation Formula-slot call site."""
    operations = projection_input.operations
    projected = {
        coordinate: [call.copy() for call in calls]
        for coordinate, calls in projection_input.roots.items()
    }
    slot_coordinates = {
        cast(OperationCoordinate, coordinate[:3])
        for coordinate in projection_input.formula_slot_bindings
    }
    if not slot_coordinates:
        return ConcreteOperationCallDomainProjection(projected, {})
    reaches_slot_cache: dict[OperationCoordinate, bool] = {}

    def reaches_formula_slot(
        coordinate: OperationCoordinate,
        stack: tuple[OperationCoordinate, ...] = (),
    ) -> bool:
        cached = reaches_slot_cache.get(coordinate)
        if cached is not None:
            return cached
        if coordinate in stack:
            return False
        if coordinate in slot_coordinates:
            reaches_slot_cache[coordinate] = True
            return True
        operation = operations.get(coordinate)
        if operation is None:
            reaches_slot_cache[coordinate] = False
            return False

        def body_reaches_slot(instructions: list[dict[str, Any]]) -> bool:
            for instruction in instructions:
                nested = instruction.get("body")
                if (
                    isinstance(nested, list)
                    and all(isinstance(row, dict) for row in nested)
                    and body_reaches_slot(cast(list[dict[str, Any]], nested))
                ):
                    return True
                operation_ref = instruction.get("operation")
                if instruction.get(
                    "node"
                ) not in projection_input.operation_node_ids or not isinstance(
                    operation_ref, dict
                ):
                    continue
                if not all(
                    isinstance(operation_ref.get(member), str)
                    for member in ("package", "version", "id")
                ):
                    raise ConcreteOperationCallDomainError(
                        "malformed_operation_reference",
                        "nested Operation reference is malformed",
                        coordinate,
                    )
                child_coordinate = (
                    cast(str, operation_ref["package"]),
                    cast(str, operation_ref["version"]),
                    cast(str, operation_ref["id"]),
                )
                if reaches_formula_slot(child_coordinate, (*stack, coordinate)):
                    return True
            return False

        body = operation.get("body")
        if not isinstance(body, list) or not all(
            isinstance(instruction, dict) for instruction in body
        ):
            raise ConcreteOperationCallDomainError(
                "malformed_operation_body",
                "concrete Operation call is unresolved",
                coordinate,
            )
        reaches = body_reaches_slot(cast(list[dict[str, Any]], body))
        reaches_slot_cache[coordinate] = reaches
        return reaches

    def visit(
        coordinate: OperationCoordinate,
        call: dict[str, Any],
        stack: tuple[OperationCoordinate, ...],
        *,
        resolve_result: bool,
    ) -> dict[str, Any]:
        if coordinate in stack:
            raise ConcreteOperationCallDomainError(
                "operation_call_cycle",
                "concrete Operation call graph contains a cycle",
                coordinate,
            )
        operation = operations.get(coordinate)
        arguments = call.get("arguments")
        if operation is None or not isinstance(arguments, dict):
            raise ConcreteOperationCallDomainError(
                "unresolved_operation_call",
                "concrete Operation call is unresolved",
                coordinate,
            )
        ports = [
            cast(str, port["id"])
            for port in cast(list[dict[str, Any]], operation["inputs"])
        ]
        if set(arguments) != set(ports):
            raise ConcreteOperationCallDomainError(
                "incomplete_arguments",
                "concrete Operation call arguments are incomplete",
                coordinate,
            )
        operand_contracts = [cast(dict[str, Any], arguments[port]) for port in ports]
        known_arguments = cast(dict[str, Any], call.get("known_arguments", {}))
        local_contracts = {
            name: contract.copy()
            for name, contract in projection_input.snapshot_contracts.get(
                coordinate, {}
            ).items()
        }
        if not projection_input.snapshot_operand_names.get(
            coordinate, frozenset()
        ) <= set(local_contracts):
            raise ConcreteOperationCallDomainError(
                "unresolved_snapshot_contract",
                "specialized Formula snapshot contract is unresolved",
                coordinate,
            )
        local_values: dict[str, Any] = {}
        local_intervals: dict[str, tuple[int, int]] = {}
        result_by_site: dict[str, dict[str, Any]] = {}

        def literal_contract(value: Any, formal: dict[str, Any]) -> dict[str, Any]:
            try:
                contract = projection_input.literal_contract(value, formal)
            except (KeyError, TypeError, ValueError) as error:
                raise ConcreteOperationCallDomainError(
                    "unresolved_literal_contract",
                    "nested Operation literal has no concrete contract",
                    coordinate,
                ) from error
            if not isinstance(contract, dict):
                raise ConcreteOperationCallDomainError(
                    "unresolved_literal_contract",
                    "nested Operation literal has no concrete contract",
                    coordinate,
                )
            return contract

        def local_contract(name: str, formal: dict[str, Any]) -> dict[str, Any]:
            contract = local_contracts.get(name)
            if contract is not None:
                return contract
            if name in local_values:
                contract = literal_contract(local_values[name], formal)
            elif name in local_intervals:
                minimum, maximum = local_intervals[name]
                contract = {
                    **cast(dict[str, Any], formula_contract_from_operation(formal)),
                    "domain_kind": "closed-interval",
                    "domain": {"minimum": minimum, "maximum": maximum},
                }
            else:
                try:
                    contract = infer_formula_operation_local_contract(
                        operation,
                        ports,
                        operand_contracts,
                        name,
                        cast(dict[str, Any], formula_contract_from_operation(formal)),
                        projection_input.conversion_policy,
                        {},
                        known_operand_values=known_arguments,
                        known_local_contracts=local_contracts,
                        ignore_unmatched_instructions=True,
                    )
                except ValueError as error:
                    raise ConcreteOperationCallDomainError(
                        "unresolved_local",
                        f"concrete Operation local {coordinate!r}.{name} is unresolved",
                        coordinate,
                    ) from error
            local_contracts[name] = contract
            return contract

        def walk(instructions: list[dict[str, Any]]) -> None:
            for instruction in instructions:
                node = instruction.get("node")
                target = instruction.get("target")
                if node == "constant" and isinstance(target, str):
                    local_values[target] = instruction.get("literal")
                elif node == "draw" and isinstance(target, str):
                    minimum = instruction.get("minimum")
                    maximum = instruction.get("maximum")
                    if (
                        isinstance(minimum, int)
                        and not isinstance(minimum, bool)
                        and isinstance(maximum, int)
                        and not isinstance(maximum, bool)
                    ):
                        local_intervals[target] = (minimum, maximum)
                nested = instruction.get("body")
                if isinstance(nested, list) and all(
                    isinstance(row, dict) for row in nested
                ):
                    walk(cast(list[dict[str, Any]], nested))
                operation_ref = instruction.get("operation")
                if node not in projection_input.operation_node_ids or not isinstance(
                    operation_ref, dict
                ):
                    continue
                if not all(
                    isinstance(operation_ref.get(member), str)
                    for member in ("package", "version", "id")
                ):
                    raise ConcreteOperationCallDomainError(
                        "malformed_operation_reference",
                        "nested Operation reference is malformed",
                        coordinate,
                    )
                child_coordinate = (
                    cast(str, operation_ref["package"]),
                    cast(str, operation_ref["version"]),
                    cast(str, operation_ref["id"]),
                )
                child = operations.get(child_coordinate)
                if child is None:
                    raise ConcreteOperationCallDomainError(
                        "unresolved_operation_target",
                        "nested Operation call target is unresolved",
                        child_coordinate,
                    )
                child_ports = {
                    cast(str, port["id"]): port
                    for port in cast(list[dict[str, Any]], child["inputs"])
                }
                child_arguments: dict[str, dict[str, Any]] = {}
                child_known_arguments: dict[str, Any] = {}
                for authored in cast(list[dict[str, Any]], instruction["arguments"]):
                    port_id = cast(str, authored["port"])
                    formal = child_ports[port_id]
                    operand = cast(dict[str, Any], authored["operand"])
                    if operand.get("kind") == "port":
                        parent_port = cast(str, operand["port"])
                        contract = cast(dict[str, Any], arguments[parent_port])
                        if parent_port in known_arguments:
                            child_known_arguments[port_id] = known_arguments[
                                parent_port
                            ]
                    elif operand.get("kind") == "local":
                        name = cast(str, operand["local"])
                        contract = local_contract(name, formal)
                        if name in local_values:
                            child_known_arguments[port_id] = local_values[name]
                    elif operand.get("kind") == "literal":
                        value = operand.get("literal")
                        contract = literal_contract(value, formal)
                        child_known_arguments[port_id] = value
                    else:
                        raise ConcreteOperationCallDomainError(
                            "unresolved_nested_operand",
                            "nested Operation operand has no concrete contract",
                            coordinate,
                        )
                    child_arguments[port_id] = contract
                child_call = {
                    "arguments": child_arguments,
                    "known_arguments": child_known_arguments,
                }
                projected.setdefault(child_coordinate, []).append(child_call)
                result = instruction.get("result")
                result_kind = result.get("kind") if isinstance(result, dict) else None
                child_result = visit(
                    child_coordinate,
                    child_call,
                    (*stack, coordinate),
                    resolve_result=result_kind in {"local", "operation-result"},
                )
                site = instruction.get("site")
                if isinstance(site, str):
                    result_by_site[site] = child_result
                if isinstance(result, dict) and result.get("kind") == "local":
                    local_contracts[cast(str, result["name"])] = child_result

        body = operation.get("body")
        if not isinstance(body, list) or not all(
            isinstance(instruction, dict) for instruction in body
        ):
            raise ConcreteOperationCallDomainError(
                "malformed_operation_body",
                "concrete Operation call is unresolved",
                coordinate,
            )
        try:
            walk(cast(list[dict[str, Any]], body))
            result = cast(dict[str, Any], operation["result"])
        except ConcreteOperationCallDomainError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise ConcreteOperationCallDomainError(
                "malformed_operation_call",
                "concrete Operation call is unresolved",
                coordinate,
            ) from error
        if not resolve_result:
            return cast(dict[str, Any], formula_contract_from_operation(result))
        declared_domain = result.get("domain")
        if (
            isinstance(declared_domain, dict)
            and declared_domain.get("kind") != "actual"
        ):
            return cast(dict[str, Any], formula_contract_from_operation(result))
        source = result.get("source")
        if not isinstance(source, dict):
            raise ConcreteOperationCallDomainError(
                "unresolved_result_source",
                "concrete Operation result source is unresolved",
                coordinate,
            )
        if source.get("kind") == "local":
            return local_contract(cast(str, source["name"]), result)
        if source.get("kind") == "operation-result":
            resolved = result_by_site.get(cast(str, source.get("site")))
            if resolved is None:
                raise ConcreteOperationCallDomainError(
                    "unresolved_nested_result",
                    "nested Operation result is unresolved",
                    coordinate,
                )
            return resolved
        if source.get("kind") == "unit":
            return cast(dict[str, Any], formula_contract_from_operation(result))
        try:
            return infer_formula_operation_result(
                operation,
                ports,
                operand_contracts,
                cast(dict[str, Any], formula_contract_from_operation(result)),
                projection_input.conversion_policy,
                {},
            )
        except ValueError as error:
            raise ConcreteOperationCallDomainError(
                "unresolved_result",
                "concrete Operation result is unresolved",
                coordinate,
            ) from error

    initial_roots = [
        (coordinate, call)
        for coordinate, calls in projection_input.roots.items()
        for call in list(calls)
    ]
    for coordinate, call in initial_roots:
        if reaches_formula_slot(coordinate):
            visit(coordinate, call, (), resolve_result=False)

    slot_parameter_contracts: dict[
        OperationSlotCoordinate, list[dict[str, dict[str, Any]]]
    ] = {}
    for slot_coordinate in sorted(projection_input.formula_slot_bindings):
        coordinate = cast(OperationCoordinate, slot_coordinate[:3])
        operation = operations.get(coordinate)
        if operation is None:
            raise ConcreteOperationCallDomainError(
                "unresolved_formula_slot",
                "Formula Operation slot is unresolved",
                coordinate,
            )
        extensions = operation.get("extensions")
        slots = (
            extensions.get("standard.formula-slots")
            if isinstance(extensions, dict)
            else None
        )
        slot = next(
            (
                item
                for item in slots or []
                if isinstance(item, dict) and item.get("id") == slot_coordinate[3]
            ),
            None,
        )
        if not isinstance(slot, dict) or not isinstance(slot.get("parameters"), list):
            raise ConcreteOperationCallDomainError(
                "unresolved_formula_slot",
                "Formula Operation slot is unresolved",
                coordinate,
            )
        projections: list[dict[str, dict[str, Any]]] = []
        for call in projected.get(coordinate, []):
            parameter_contracts: dict[str, dict[str, Any]] = {}
            for parameter in cast(list[dict[str, Any]], slot["parameters"]):
                parameter_id = cast(str, parameter["id"])
                try:
                    parameter_contracts[parameter_id] = (
                        infer_formula_slot_parameter_contract(
                            operation,
                            parameter,
                            call,
                            projection_input.conversion_policy,
                        )
                    )
                except ValueError as error:
                    raise ConcreteOperationCallDomainError(
                        "unresolved_formula_slot_parameter",
                        str(error),
                        coordinate,
                    ) from error
            projections.append(parameter_contracts)
        slot_parameter_contracts[slot_coordinate] = projections
    return ConcreteOperationCallDomainProjection(
        projected,
        slot_parameter_contracts,
    )
