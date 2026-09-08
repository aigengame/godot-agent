"""Pure projections of Kernel closed value contracts into JSON Schema."""

from typing import Any, cast


def _contract_schema(contract: dict[str, Any]) -> dict[str, object]:
    if "const" in contract:
        return {"const": contract["const"]}
    if "enum" in contract:
        values = contract["enum"]
        if not isinstance(values, list):
            raise ValueError("Kernel enum contract is not a list")
        return {"enum": values}
    value_type = contract.get("type")
    if value_type == "non-empty-string":
        schema: dict[str, object] = {"type": "string", "minLength": 1}
        pattern = contract.get("pattern")
        if isinstance(pattern, str):
            schema["pattern"] = pattern
        return schema
    if value_type == "positive-signed-int64":
        return {"type": "integer", "minimum": 1, "maximum": 2**63 - 1}
    if value_type == "signed-int64":
        return {"type": "integer", "minimum": -(2**63), "maximum": 2**63 - 1}
    if value_type in {"boolean", "null", "integer", "string"}:
        return {
            "type": value_type,
            **{
                key: contract[key]
                for key in ("pattern", "maxLength")
                if key in contract
            },
        }
    if value_type == "canonical-json":
        return {}
    if value_type == "one-of":
        return {
            "oneOf": [
                _contract_schema(alternative)
                for alternative in contract["alternatives"]
            ]
        }
    if value_type == "object":
        return {"type": "object"}
    if value_type == "string-list":
        return {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        }
    if value_type == "list":
        return {"type": "array"}
    if value_type == "list-of":
        items = contract.get("items")
        if not isinstance(items, dict):
            raise ValueError("Kernel list-of contract has no item contract")
        return {"type": "array", "items": _contract_schema(items)}
    if value_type == "closed-object":
        return _closed_contract_schema(contract)
    raise ValueError(f"unsupported Kernel package contract type: {value_type!r}")


def _closed_contract_schema(contract: dict[str, Any]) -> dict[str, object]:
    required = contract.get("required_members")
    optional = contract.get("optional_members", [])
    field_types = contract.get("field_types", {})
    nested_members = contract.get("nested_members", {})
    nested_field_types = contract.get("nested_field_types", {})
    if (
        contract.get("closed") is not True
        or not isinstance(required, list)
        or not all(isinstance(member, str) for member in required)
        or not isinstance(optional, list)
        or not all(isinstance(member, str) for member in optional)
        or set(required) & set(optional)
        or not isinstance(field_types, dict)
        or not isinstance(nested_members, dict)
        or not isinstance(nested_field_types, dict)
        or set(field_types) | set(nested_members) != set(required) | set(optional)
        or set(nested_members) != set(nested_field_types)
    ):
        raise ValueError("Kernel package object contract is incomplete")
    properties = {
        name: _contract_schema(cast(dict[str, Any], member_contract))
        for name, member_contract in field_types.items()
    }
    for name, members in nested_members.items():
        member_types = nested_field_types.get(name)
        if (
            not isinstance(members, list)
            or not all(isinstance(member, str) for member in members)
            or not isinstance(member_types, dict)
            or set(member_types) != set(members)
        ):
            raise ValueError(f"Kernel nested package contract is incomplete: {name}")
        properties[name] = {
            "type": "object",
            "properties": {
                member: _contract_schema(cast(dict[str, Any], member_types[member]))
                for member in members
            },
            "required": members,
            "unevaluatedProperties": False,
        }
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "unevaluatedProperties": False,
    }
