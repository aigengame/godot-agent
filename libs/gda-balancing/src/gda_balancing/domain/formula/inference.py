"""Authority-driven local-result inference for Formula notation conversion."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from gda_balancing.domain.formula.types import formula_contract_from_operation


def infer_formula_operation_local_contract(
    operation: dict[str, Any],
    ports: list[str],
    operand_contracts: list[dict[str, Any]],
    local: str,
    fallback: dict[str, Any],
    conversion_policy: dict[str, Any],
    source_type_aliases: dict[tuple[str, str], str],
    known_operand_values: dict[str, Any] | None = None,
    known_local_contracts: dict[str, dict[str, Any]] | None = None,
    ignore_unmatched_instructions: bool = False,
) -> dict[str, Any]:
    """Infer one Operation local by interpreting compiler-owned transfer rules."""
    rules = conversion_policy.get("local_result_inference")
    if not isinstance(rules, list):
        raise ValueError("Formula notation inference policy is malformed")
    rules_by_node = {
        row.get("node"): row
        for row in rules
        if isinstance(row, dict) and isinstance(row.get("node"), str)
    }
    if len(rules_by_node) != len(rules):
        raise ValueError("Formula notation inference rules are ambiguous")

    contextual = next(iter(operand_contracts), fallback)
    values = {
        port: deepcopy(contract)
        for port, contract in zip(ports, operand_contracts, strict=True)
    }
    values.update(deepcopy(known_local_contracts or {}))
    known_values = deepcopy(known_operand_values or {})
    if not set(known_values) <= set(ports):
        raise ValueError("Formula known operand is not an Operation port")

    def interval(contract: dict[str, Any]) -> tuple[int, int] | None:
        domain = contract.get("domain")
        if (
            contract.get("domain_kind") != "closed-interval"
            or not isinstance(domain, dict)
            or not isinstance(domain.get("minimum"), int)
            or isinstance(domain["minimum"], bool)
            or not isinstance(domain.get("maximum"), int)
            or isinstance(domain["maximum"], bool)
        ):
            return None
        return cast(int, domain["minimum"]), cast(int, domain["maximum"])

    def with_interval(
        contract: dict[str, Any], bounds: tuple[int, int]
    ) -> dict[str, Any]:
        inferred = deepcopy(contract)
        inferred["domain_kind"] = "closed-interval"
        inferred["domain"] = {
            "minimum": max(bounds[0], -(2**63)),
            "maximum": min(bounds[1], 2**63 - 1),
        }
        return inferred

    body = operation.get("body")
    if not isinstance(body, list):
        raise ValueError("Formula operation has no inferable body")
    for instruction in body:
        if not isinstance(instruction, dict):
            raise ValueError("Formula operation body is malformed")
        rule = rules_by_node.get(instruction.get("node"))
        if not isinstance(rule, dict):
            if ignore_unmatched_instructions:
                continue
            raise ValueError("Formula operation body has no admitted type inference")
        target_member = rule.get("target_member")
        target = (
            instruction.get(target_member) if isinstance(target_member, str) else None
        )
        if not isinstance(target, str):
            raise ValueError("Formula operation body has no inference target")
        rule_id = rule.get("rule")
        if rule_id == "literal-closed-interval":
            literal_member = rule.get("literal_member")
            literal = (
                instruction.get(literal_member)
                if isinstance(literal_member, str)
                else None
            )
            if not isinstance(literal, int) or isinstance(literal, bool):
                raise ValueError("Formula literal inference source is malformed")
            values[target] = with_interval(contextual, (literal, literal))
            known_values[target] = literal
        elif rule_id == "copy-contract":
            source_member = rule.get("source_member")
            source = (
                instruction.get(source_member)
                if isinstance(source_member, str)
                else None
            )
            if not isinstance(source, str) or source not in values:
                raise ValueError("Formula copy inference source is unresolved")
            values[target] = deepcopy(values[source])
            if source in known_values:
                known_values[target] = known_values[source]
        elif rule_id in {
            "closed-interval-add",
            "closed-interval-floor-divide",
            "closed-interval-maximum",
            "closed-interval-multiply",
            "closed-interval-select",
            "closed-interval-subtract",
        }:
            operand_members = rule.get("operand_members")
            if (
                not isinstance(operand_members, list)
                or len(operand_members) != 2
                or not all(isinstance(member, str) for member in operand_members)
            ):
                raise ValueError("Formula interval inference policy is malformed")
            operands = [instruction.get(member) for member in operand_members]
            if not all(
                isinstance(value, str) and value in values for value in operands
            ):
                raise ValueError("Formula interval inference source is unresolved")
            left = values[cast(str, operands[0])]
            right = values[cast(str, operands[1])]
            left_interval, right_interval = interval(left), interval(right)
            condition = instruction.get("condition")
            if (
                rule_id == "closed-interval-select"
                and isinstance(condition, str)
                and isinstance(known_values.get(condition), bool)
            ):
                selected = (
                    cast(str, operands[0])
                    if known_values[condition]
                    else cast(str, operands[1])
                )
                values[target] = deepcopy(values[selected])
                if selected in known_values:
                    known_values[target] = known_values[selected]
            elif left_interval is None or right_interval is None:
                values[target] = deepcopy(left)
            elif rule_id == "closed-interval-add":
                values[target] = with_interval(
                    left,
                    (
                        left_interval[0] + right_interval[0],
                        left_interval[1] + right_interval[1],
                    ),
                )
            elif rule_id == "closed-interval-subtract":
                values[target] = with_interval(
                    left,
                    (
                        left_interval[0] - right_interval[1],
                        left_interval[1] - right_interval[0],
                    ),
                )
            elif rule_id == "closed-interval-multiply":
                products = tuple(
                    left_value * right_value
                    for left_value in left_interval
                    for right_value in right_interval
                )
                values[target] = with_interval(left, (min(products), max(products)))
            elif rule_id == "closed-interval-floor-divide":
                if right_interval[0] <= 0:
                    raise ValueError(
                        "Formula floor-divide divisor domain is not positive"
                    )
                quotients = tuple(
                    left_value // right_value
                    for left_value in left_interval
                    for right_value in right_interval
                )
                values[target] = with_interval(left, (min(quotients), max(quotients)))
            elif rule_id == "closed-interval-select":
                values[target] = with_interval(
                    left,
                    (
                        min(left_interval[0], right_interval[0]),
                        max(left_interval[1], right_interval[1]),
                    ),
                )
            else:
                values[target] = with_interval(
                    left,
                    (
                        max(left_interval[0], right_interval[0]),
                        max(left_interval[1], right_interval[1]),
                    ),
                )
        elif rule_id == "declared-result-contract":
            result = operation.get("result")
            if not isinstance(result, dict):
                raise ValueError("Formula declared result contract is malformed")
            declared = cast(dict[str, Any], formula_contract_from_operation(result))
            if "type_identity" not in contextual:
                identity = cast(dict[str, str], declared.pop("type_identity"))
                alias = source_type_aliases.get(
                    (
                        identity["package"],
                        identity["id"],
                    )
                )
                if alias is None:
                    raise ValueError("Formula declared result type alias is unresolved")
                declared["type"] = alias
            values[target] = declared
        else:
            raise ValueError("Formula notation inference rule is unknown")
        if target == local:
            return values[target]

    raise ValueError("Formula operation local source is unresolved")


def infer_formula_slot_parameter_contract(
    operation: dict[str, Any],
    slot_parameter: dict[str, Any],
    concrete_call: dict[str, Any],
    conversion_policy: dict[str, Any],
) -> dict[str, Any]:
    """Project one Formula-slot parameter at a concrete Operation call site."""
    source = slot_parameter.get("source")
    arguments = concrete_call.get("arguments")
    if not isinstance(source, dict) or not isinstance(arguments, dict):
        raise ValueError("Formula slot source is unresolved")
    name = source.get("name")
    if not isinstance(name, str):
        raise ValueError("Formula slot source has no name")
    if source.get("kind") == "port":
        contract = arguments.get(name)
        if not isinstance(contract, dict):
            raise ValueError("Formula slot port source is unresolved")
        return contract
    if source.get("kind") != "local":
        raise ValueError("Formula slot source kind is not admitted")

    ports = [
        port.get("id") for port in operation.get("inputs", []) if isinstance(port, dict)
    ]
    if (
        not ports
        or not all(isinstance(port, str) for port in ports)
        or set(ports) != set(arguments)
    ):
        raise ValueError("Formula slot call arguments are incomplete")
    contracts = [arguments[port] for port in ports]
    if not all(isinstance(contract, dict) for contract in contracts):
        raise ValueError("Formula slot call contract is malformed")
    return infer_formula_operation_local_contract(
        operation,
        cast(list[str], ports),
        cast(list[dict[str, Any]], contracts),
        name,
        cast(dict[str, Any], contracts[0]),
        conversion_policy,
        {},
        cast(dict[str, Any], concrete_call.get("known_arguments", {})),
    )


def infer_formula_operation_result(
    operation: dict[str, Any],
    ports: list[str],
    operand_contracts: list[dict[str, Any]],
    fallback: dict[str, Any],
    conversion_policy: dict[str, Any],
    source_type_aliases: dict[tuple[str, str], str],
) -> dict[str, Any]:
    """Infer one Operation-call result by interpreting compiler-owned transfer rules."""
    result_source_policy = conversion_policy.get("operation_result_source")
    if not isinstance(result_source_policy, dict):
        raise ValueError("Formula notation inference policy is malformed")

    result = operation.get("result")
    source_member = result_source_policy.get("source_member")
    expected_kind = result_source_policy.get("kind")
    name_member = result_source_policy.get("name_member")
    source = (
        result.get(source_member)
        if isinstance(result, dict) and isinstance(source_member, str)
        else None
    )
    name = (
        source.get(name_member)
        if isinstance(source, dict) and isinstance(name_member, str)
        else None
    )
    if (
        not isinstance(source, dict)
        or source.get("kind") != expected_kind
        or not isinstance(name, str)
    ):
        raise ValueError("Formula operation result source is unresolved")
    return infer_formula_operation_local_contract(
        operation,
        ports,
        operand_contracts,
        name,
        fallback,
        conversion_policy,
        source_type_aliases,
    )
