"""Shared Formula value-contract resolution and compatibility rules."""

from __future__ import annotations

from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue


_FORMULA_CONTRACT_MEMBERS = (
    "representation",
    "kind",
    "unit",
    "domain_kind",
    "domain",
    "numeric_policy",
)


def formula_contract_matches(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    """Compare two resolved Formula value contracts exactly."""
    return actual.get("type_identity") == expected.get("type_identity") and all(
        actual.get(member) == expected.get(member)
        for member in _FORMULA_CONTRACT_MEMBERS
    )


def formula_contract_matches_operation(
    formula_contract: dict[str, Any],
    operation_contract: dict[str, Any],
) -> bool:
    """Compare a resolved Formula contract with an Operation formal contract."""
    formula_type = formula_contract.get("type_identity")
    operation_type = operation_contract.get("type")
    return (
        isinstance(formula_type, dict)
        and isinstance(operation_type, dict)
        and formula_type.get("package") == operation_type.get("package")
        and formula_type.get("version") == operation_type.get("version")
        and formula_type.get("symbol") == operation_type.get("id")
        and all(
            formula_contract.get(member) == operation_contract.get(member)
            for member in (
                "representation",
                "kind",
                "unit",
                "numeric_policy",
            )
        )
    )


def formula_contract_from_operation(
    operation_contract: dict[str, Any],
) -> dict[str, JsonValue]:
    """Project an Operation or literal-profile contract into Formula form."""
    contract_type = operation_contract.get("type")
    if not isinstance(contract_type, dict) or not all(
        isinstance(contract_type.get(member), str)
        for member in ("package", "version", "id")
    ):
        raise ValueError("Operation value contract has no exact type")
    return cast(
        dict[str, JsonValue],
        {
            member: operation_contract[member]
            for member in _FORMULA_CONTRACT_MEMBERS
            if member in operation_contract
        }
        | {
            "type_identity": {
                "package": contract_type["package"],
                "version": contract_type["version"],
                "symbol": contract_type["id"],
            }
        },
    )


def resolve_formula_contract(
    source_contract: dict[str, Any],
    imports: dict[str, dict[str, str]],
    kernel: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, JsonValue]:
    """Resolve one source or already-resolved Formula value contract."""
    resolved_type = source_contract.get("type_identity")
    if isinstance(resolved_type, dict):
        return cast(
            dict[str, JsonValue],
            {
                key: value
                for key, value in source_contract.items()
                if key not in {"id", "symbol", "role", "value_policy"}
            },
        )
    alias = source_contract.get("type")
    imported = imports.get(alias) if isinstance(alias, str) else None
    fixed_aliases = [
        row
        for row in cast(list[dict[str, Any]], policy["fixed_value_type_aliases"])
        if row.get("alias") == alias
    ]
    if imported is not None and fixed_aliases:
        raise ValueError("Formula value-contract type alias is ambiguous")
    if imported is None and len(fixed_aliases) == 1:
        fixed_contracts = cast(
            dict[str, dict[str, JsonValue]],
            kernel["meta_format"]["runtime_program"]["fixed_value_contracts"],
        )
        fixed = fixed_contracts.get(cast(str, fixed_aliases[0].get("contract")))
        if fixed is None:
            raise ValueError("Formula fixed value-contract alias is unresolved")
        expected_members = {key: value for key, value in fixed.items() if key != "type"}
        if any(
            source_contract.get(member) != value
            for member, value in expected_members.items()
        ):
            raise ValueError("Formula fixed value-contract does not match authority")
        fixed_type = cast(dict[str, str], fixed["type"])
        return {
            **expected_members,
            "type_identity": {
                "package": fixed_type["package"],
                "version": fixed_type["version"],
                "symbol": fixed_type["id"],
            },
        }
    if imported is None or fixed_aliases:
        raise ValueError("Formula value-contract type alias is unresolved")
    return cast(
        dict[str, JsonValue],
        {
            key: value
            for key, value in source_contract.items()
            if key not in {"id", "symbol", "role", "type", "value_policy"}
        }
        | {
            "type_identity": {
                "package": imported["package"],
                "version": imported["version"],
                "symbol": imported["symbol"],
            }
        },
    )
