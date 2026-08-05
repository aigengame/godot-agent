"""CLI response-schema projections for Package Release commands."""

from typing import Any, cast

from gda_balancing.domain.authority.context import packaged_authority_context


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
    if value_type == "boolean":
        return {"type": "boolean"}
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
    field_types = contract.get("field_types", {})
    nested_members = contract.get("nested_members", {})
    nested_field_types = contract.get("nested_field_types", {})
    if (
        contract.get("closed") is not True
        or not isinstance(required, list)
        or not all(isinstance(member, str) for member in required)
        or not isinstance(field_types, dict)
        or not isinstance(nested_members, dict)
        or not isinstance(nested_field_types, dict)
        or set(field_types) | set(nested_members) != set(required)
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


def _package_contracts() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    context = packaged_authority_context()
    kernel = context.kernel
    language_bundle = context.language_bundle
    meta_format = cast(dict[str, Any], kernel["meta_format"])
    language_bundle_contract = cast(dict[str, Any], meta_format["language_bundle"])
    return (
        cast(
            dict[str, Any], language_bundle_contract["member_types"]["content_identity"]
        ),
        cast(dict[str, Any], language_bundle_contract["package_descriptor"]),
        cast(dict[str, Any], meta_format["package_release"]),
        cast(dict[str, Any], meta_format["package_conformance_vector_set"]),
        meta_format,
        language_bundle,
    )


def package_list_success_schema() -> dict[str, object]:
    (
        identity_contract,
        descriptor_contract,
        _release_contract,
        _vector_set_contract,
        _meta_format,
        _language_bundle,
    ) = _package_contracts()
    return {
        "type": "object",
        "properties": {
            "language_bundle_identity": _contract_schema(identity_contract),
            "packages": {
                "type": "array",
                "items": _closed_contract_schema(descriptor_contract),
            },
        },
        "required": ["language_bundle_identity", "packages"],
        "unevaluatedProperties": False,
    }
