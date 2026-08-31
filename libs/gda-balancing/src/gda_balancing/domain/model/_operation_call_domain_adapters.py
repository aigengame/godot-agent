"""Source and RIR adapters for concrete Operation call-domain propagation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from gda_balancing.domain.authority.runtime_validation import (
    fixed_operation_value_contract,
    operation_literal_context_contract,
)
from gda_balancing.domain.formula.types import formula_contract_from_operation
from gda_balancing.domain.operation_call_domains import (
    ConcreteOperationCallDomainInput,
    OperationCoordinate,
    OperationSlotCoordinate,
)
from gda_balancing.domain.model._resolution import (
    _language,
    _operation_formula_slots,
    _operation_reference_node_ids,
)


def resolved_source_formula_call(
    formula: dict[str, Any],
    node: dict[str, Any],
    operation: dict[str, Any],
    declarations_by_source: dict[tuple[str, str], dict[str, Any]],
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
) -> dict[str, Any]:
    """Adapt one resolved source Formula Operation call into a concrete root."""
    parameters = {
        cast(str, parameter["id"]): parameter
        for parameter in cast(list[dict[str, Any]], formula["parameters"])
    }
    locals_by_id = {
        cast(str, item["id"]): cast(dict[str, Any], item["result"])
        for item in cast(
            list[dict[str, Any]], cast(dict[str, Any], formula["body"])["nodes"]
        )
    }
    ports = {
        cast(str, port["id"]): port
        for port in cast(list[dict[str, Any]], operation["inputs"])
    }
    resolved: dict[str, dict[str, Any]] = {}
    known_arguments: dict[str, Any] = {}
    literal_contract = _literal_contract_resolver(kernel, language_bundle)
    for argument in cast(list[dict[str, Any]], node["arguments"]):
        port_id = cast(str, argument["port"])
        operand = cast(dict[str, Any], argument["operand"])
        operand_kind = operand.get("kind")
        if operand_kind == "parameter":
            contract = parameters[cast(str, operand["parameter"])]
        elif operand_kind == "local":
            contract = locals_by_id[cast(str, operand["local"])]
        elif operand_kind == "symbol":
            symbol = cast(dict[str, str], operand["resolved_symbol"])
            contract = declarations_by_source[(symbol["module"], symbol["name"])]
        elif operand_kind == "literal":
            value = operand.get("value")
            contract = literal_contract(value, ports[port_id])
            if (
                contract is None
                or not isinstance(value, int)
                or isinstance(value, bool)
            ):
                raise ValueError("Formula literal has no concrete call-site contract")
            known_arguments[port_id] = value
        else:
            raise ValueError("Formula call operand has no concrete contract")
        resolved[port_id] = contract
    return {"arguments": resolved, "known_arguments": known_arguments}


def resolved_source_entrypoint_call(
    source_entrypoint: dict[str, Any],
    operation: dict[str, Any],
    declarations_by_source: dict[tuple[str, str], dict[str, Any]],
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
) -> dict[str, Any] | None:
    """Adapt one Model Source entrypoint into a concrete root call."""
    ports = {
        cast(str, port["id"]): port
        for port in cast(list[dict[str, Any]], operation["inputs"])
    }
    arguments: dict[str, dict[str, Any]] = {}
    known_arguments: dict[str, Any] = {}
    literal_contract = _literal_contract_resolver(kernel, language_bundle)
    for argument in cast(list[dict[str, Any]], source_entrypoint["arguments"]):
        port_id = cast(str, argument["port"])
        formal = ports.get(port_id)
        if formal is None:
            return None
        operand = cast(dict[str, Any], argument["operand"])
        if operand.get("kind") == "symbol":
            contract = declarations_by_source.get(
                (cast(str, operand.get("module")), cast(str, operand.get("symbol")))
            )
            if contract is None:
                return None
        elif operand.get("kind") == "literal":
            value = operand.get("value")
            contract = literal_contract(value, formal)
            if contract is None:
                return None
            known_arguments[port_id] = value
        elif operand.get("kind") == "event-reference":
            contract = _event_reference_contract(kernel)
            if contract is None:
                return None
        else:
            return None
        arguments[port_id] = contract
    if set(arguments) != set(ports):
        return None
    return {"arguments": arguments, "known_arguments": known_arguments}


def resolved_rir_formula_call(
    operation: dict[str, Any],
    arguments: list[Any],
    operand_contract: Callable[[Any], dict[str, Any] | None],
) -> dict[str, Any] | None:
    """Adapt one admitted RIR Formula Operation call into a concrete root."""
    ports = {
        cast(str, port["id"]): port
        for port in cast(list[dict[str, Any]], operation["inputs"])
    }
    call_arguments: dict[str, dict[str, Any]] = {}
    known_call_arguments: dict[str, Any] = {}
    for argument in arguments:
        if (
            not isinstance(argument, dict)
            or set(argument) != {"port", "operand"}
            or (contract := operand_contract(argument.get("operand"))) is None
        ):
            return None
        port_id = cast(str, argument["port"])
        if port_id not in ports:
            return None
        call_arguments[port_id] = contract
        operand = cast(dict[str, Any], argument["operand"])
        if operand.get("kind") == "literal":
            known_call_arguments[port_id] = operand.get("value")
    return {
        "arguments": call_arguments,
        "known_arguments": known_call_arguments,
    }


def resolved_rir_entrypoint_call(
    entrypoint: dict[str, Any],
    operation: dict[str, Any],
    declarations_by_symbol: dict[tuple[str, str], dict[str, Any]],
    kernel: dict[str, Any],
) -> dict[str, Any] | None:
    """Adapt one admitted RIR entrypoint into a concrete root call."""
    arguments = entrypoint.get("arguments")
    if not isinstance(arguments, list):
        return None
    call_arguments: dict[str, dict[str, Any]] = {}
    known_call_arguments: dict[str, Any] = {}
    ports = {
        cast(str, port["id"])
        for port in cast(list[dict[str, Any]], operation["inputs"])
    }
    for argument in arguments:
        if not isinstance(argument, dict) or not isinstance(argument.get("port"), dict):
            return None
        port_id = cast(str, argument["port"].get("name"))
        operand = argument.get("operand")
        if port_id not in ports or not isinstance(operand, dict):
            return None
        if operand.get("kind") == "symbol":
            symbol = operand.get("symbol")
            if not isinstance(symbol, dict):
                return None
            contract = declarations_by_symbol.get(
                (
                    cast(str, symbol.get("module")),
                    cast(str, symbol.get("name")),
                )
            )
        elif operand.get("kind") == "literal":
            context_type = operand.get("context_type")
            if not isinstance(context_type, dict):
                return None
            try:
                contract = cast(
                    dict[str, Any], formula_contract_from_operation(context_type)
                )
            except ValueError:
                return None
            value = operand.get("value")
            if isinstance(value, int) and not isinstance(value, bool):
                contract = {
                    **contract,
                    "domain_kind": "closed-interval",
                    "domain": {"minimum": value, "maximum": value},
                }
            known_call_arguments[port_id] = value
        elif operand.get("kind") == "event-reference":
            contract = _event_reference_contract(kernel)
        else:
            return None
        if not isinstance(contract, dict):
            return None
        call_arguments[port_id] = contract
    return {
        "arguments": call_arguments,
        "known_arguments": known_call_arguments,
    }


def build_operation_call_domain_input(
    operations: dict[OperationCoordinate, dict[str, Any]],
    roots: dict[OperationCoordinate, list[dict[str, Any]]],
    bindings: list[dict[str, Any]],
    declarations_by_symbol: dict[tuple[str, str], dict[str, Any]],
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
    conversion_policy: dict[str, Any],
) -> ConcreteOperationCallDomainInput:
    """Build one neutral projection input from normalized production shapes."""
    return ConcreteOperationCallDomainInput(
        operations=operations,
        roots=roots,
        formula_slot_bindings=_formula_slot_bindings(bindings, operations),
        operation_node_ids=frozenset(_operation_reference_node_ids(kernel)),
        conversion_policy=conversion_policy,
        literal_contract=_literal_contract_resolver(kernel, language_bundle),
        snapshot_contracts=_snapshot_contracts(operations, declarations_by_symbol),
        snapshot_operand_names=_snapshot_operand_names(operations),
    )


def _formula_slot_bindings(
    bindings: list[dict[str, Any]],
    operations: dict[OperationCoordinate, dict[str, Any]],
) -> frozenset[OperationSlotCoordinate]:
    selected: set[OperationSlotCoordinate] = set()
    for binding in bindings:
        site = binding.get("site") if isinstance(binding, dict) else None
        operation_ref = site.get("operation") if isinstance(site, dict) else None
        if (
            not isinstance(site, dict)
            or site.get("kind") != "operation-slot"
            or not isinstance(operation_ref, dict)
            or not isinstance(site.get("slot"), str)
            or not all(
                isinstance(operation_ref.get(member), str)
                for member in ("package", "version", "id")
            )
        ):
            continue
        coordinate = (
            cast(str, operation_ref["package"]),
            cast(str, operation_ref["version"]),
            cast(str, operation_ref["id"]),
        )
        operation = operations.get(coordinate)
        if operation is None or not any(
            slot.get("id") == site["slot"]
            for slot in _operation_formula_slots(operation)
        ):
            continue
        selected.add((*coordinate, cast(str, site["slot"])))
    return frozenset(selected)


def _snapshot_contracts(
    operations: dict[OperationCoordinate, dict[str, Any]],
    declarations_by_symbol: dict[tuple[str, str], dict[str, Any]],
) -> dict[OperationCoordinate, dict[str, dict[str, Any]]]:
    resolved: dict[OperationCoordinate, dict[str, dict[str, Any]]] = {}
    for coordinate, operation in operations.items():
        extensions = operation.get("extensions")
        snapshot_operands = (
            extensions.get("standard.snapshot-operands")
            if isinstance(extensions, dict)
            else None
        )
        if not isinstance(snapshot_operands, dict):
            continue
        contracts: dict[str, dict[str, Any]] = {}
        for operand in snapshot_operands.get("operands", []):
            if not isinstance(operand, dict) or not isinstance(
                operand.get("resolved_symbol"), dict
            ):
                continue
            resolved_symbol = cast(dict[str, Any], operand["resolved_symbol"])
            declaration = declarations_by_symbol.get(
                (
                    cast(str, resolved_symbol.get("module")),
                    cast(str, resolved_symbol.get("name")),
                )
            )
            if isinstance(operand.get("name"), str) and isinstance(declaration, dict):
                contracts[cast(str, operand["name"])] = declaration
        resolved[coordinate] = contracts
    return resolved


def _snapshot_operand_names(
    operations: dict[OperationCoordinate, dict[str, Any]],
) -> dict[OperationCoordinate, frozenset[str]]:
    names: dict[OperationCoordinate, frozenset[str]] = {}
    for coordinate, operation in operations.items():
        extensions = operation.get("extensions")
        snapshot_operands = (
            extensions.get("standard.snapshot-operands")
            if isinstance(extensions, dict)
            else None
        )
        if not isinstance(snapshot_operands, dict):
            continue
        names[coordinate] = frozenset(
            cast(str, operand["name"])
            for operand in snapshot_operands.get("operands", [])
            if isinstance(operand, dict) and isinstance(operand.get("name"), str)
        )
    return names


def _literal_contract_resolver(
    kernel: dict[str, Any], language_bundle: dict[str, Any]
) -> Callable[[Any, dict[str, Any]], dict[str, Any] | None]:
    profiles = {
        "literal_typing_profiles": [
            {"definition": profile}
            for profile in cast(
                list[dict[str, Any]],
                _language(language_bundle)["literal_typing_profiles"],
            )
        ]
    }

    def resolve(value: Any, formal: dict[str, Any]) -> dict[str, Any] | None:
        context = operation_literal_context_contract(value, formal, kernel, profiles)
        if context is None:
            return None
        contract = cast(dict[str, Any], formula_contract_from_operation(context))
        if isinstance(value, int) and not isinstance(value, bool):
            contract = {
                **contract,
                "domain_kind": "closed-interval",
                "domain": {"minimum": value, "maximum": value},
            }
        return contract

    return resolve


def _event_reference_contract(kernel: dict[str, Any]) -> dict[str, Any] | None:
    contract = fixed_operation_value_contract(kernel, "kernel-event-reference")
    if contract is None:
        return None
    return cast(dict[str, Any], formula_contract_from_operation(contract))
