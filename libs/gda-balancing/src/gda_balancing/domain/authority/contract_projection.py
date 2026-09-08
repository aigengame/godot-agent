"""Pure projections of Kernel closed value contracts into JSON Schema."""

import re
from copy import deepcopy
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
                for key in ("pattern", "minLength", "maxLength", "minimum", "maximum")
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
        schema = {"type": "array", "items": _contract_schema(items)}
        if "minItems" in contract:
            minimum = contract["minItems"]
            if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
                raise ValueError("Kernel list minimum cardinality is malformed")
            schema["minItems"] = minimum
        return schema
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


def _candidate_hex_pattern(candidate_encoding: Any) -> str:
    if (
        not isinstance(candidate_encoding, dict)
        or candidate_encoding.get("radix") != 16
        or candidate_encoding.get("case") != "lowercase"
        or candidate_encoding.get("zero_pad") is not True
        or not isinstance(candidate_encoding.get("alphabet"), str)
        or not candidate_encoding["alphabet"]
        or not isinstance(candidate_encoding.get("width_bits"), int)
        or candidate_encoding["width_bits"] % 4 != 0
    ):
        raise ValueError("Kernel RNG candidate encoding is incomplete")
    candidate_width = candidate_encoding["width_bits"] // 4
    return f"^[{re.escape(candidate_encoding['alphabet'])}]{{{candidate_width}}}$"


def artifact_envelope_contract(
    kernel: dict[str, Any], artifact_kind: str
) -> dict[str, Any]:
    """Bind the actual kind to the single common compiled Artifact envelope."""
    contract = deepcopy(
        kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
            "artifact_envelope"
        ]
    )
    fields = contract["field_types"]
    if "artifact_kind" in fields:
        raise ValueError("Artifact envelope duplicates the actual Contract kind")
    fields["artifact_kind"] = {"const": artifact_kind}
    # This checks the complete required/optional membership before payloads merge.
    _closed_contract_schema(contract)
    return contract


def ordered_protocol_schema(
    kernel: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any]:
    """Canonicalize only generated Schema sets, preserving every ordered payload."""
    from gda_balancing.domain.canonical import canonical_bytes

    law = kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "derived_schema_order"
    ]
    if law != {
        "required": "unicode-lexicographic",
        "alternatives": "canonical-bytes",
        "enum_values": "opaque-canonical-bytes",
        "duplicates": "preserve",
        "const": "opaque",
    }:
        raise ValueError("unsupported derived protocol Schema ordering")

    def visit(value: dict[str, Any]) -> dict[str, Any]:
        # A Schema node can share a caller-owned object with opaque const/enum
        # data. Replace this node without mutating that other occurrence.
        result = dict(value)
        if "required" in result:
            result["required"] = sorted(result["required"])
        if "properties" in result:
            result["properties"] = {
                name: visit(child) for name, child in result["properties"].items()
            }
        if "items" in result:
            result["items"] = visit(result["items"])
        for keyword in ("oneOf", "anyOf"):
            if keyword in result:
                result[keyword] = sorted(
                    (visit(child) for child in result[keyword]), key=canonical_bytes
                )
        if "enum" in result:
            # Values are canonical JSON data, not Schema. In particular a nested
            # Operation body or array under an enum value keeps its exact order.
            result["enum"] = sorted(result["enum"], key=canonical_bytes)
        return result

    return visit(deepcopy(schema))
