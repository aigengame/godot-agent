"""Derive Runtime output containers from the active execution contract owners."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.contract_projection import (
    _contract_schema,
    artifact_envelope_contract,
)


def _active_profile_schema(kernel: dict[str, Any]) -> dict[str, Any]:
    meta = kernel["meta_format"]
    active = deepcopy(meta["runtime_profile_definition"]["active_runtime"])
    if set(active) != {
        "required_members",
        "optional_members",
        "runtime_member_bindings",
        "rng_member_bindings",
        "budget_scopes",
        "resource_bounds",
    }:
        raise ValueError("Active Runtime profile contract is incomplete")
    source = meta["language_definitions"]["collections"]["runtime_profiles"]
    required, optional = active["required_members"], active["optional_members"]
    fields = deepcopy(source["field_types"])
    if set(fields) != set(required) | set(optional):
        raise ValueError("Active Runtime profile has an unowned field")

    def runtime_value(path: str) -> Any:
        value = meta["runtime_program"]
        for part in path.split("."):
            value = value[part]
        return deepcopy(value)

    for name, path in active["runtime_member_bindings"].items():
        if name not in fields or name in {"rng", "budget_scopes", "resource_bounds"}:
            raise ValueError("Runtime profile binding has no distinct field owner")
        fields[name] = {"const": runtime_value(path)}

    def record(values: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "closed-object",
            "closed": True,
            "required_members": list(values),
            "field_types": values,
        }

    fields["rng"] = record(
        {
            name: {"const": runtime_value(path)}
            for name, path in active["rng_member_bindings"].items()
        }
    )
    fields["budget_scopes"] = record(
        {name: {"const": scope} for name, scope in active["budget_scopes"].items()}
    )
    bounds = active["resource_bounds"]
    if (
        set(bounds) != {"members", "value_contract"}
        or bounds["value_contract"] != "positive-integer"
    ):
        raise ValueError("Runtime profile resource bounds have no supported contract")
    if len(bounds["members"]) != len(set(bounds["members"])):
        raise ValueError("Runtime resource bound has duplicate owners")
    fields["resource_bounds"] = record(
        {name: {"type": "integer", "minimum": 1} for name in bounds["members"]}
    )
    if len(required) != len(set(required)) or len(optional) != len(set(optional)):
        raise ValueError("Active Runtime profile membership is ambiguous")
    return _contract_schema(
        {
            "type": "closed-object",
            "closed": True,
            "required_members": required,
            "optional_members": optional,
            "field_types": fields,
        }
    )


def runtime_output_schema(
    kernel: dict[str, Any], protocol_role: str, artifact_kind: str
) -> dict[str, Any]:
    """Bind fixed framing without treating required capabilities as support."""
    meta = kernel["meta_format"]
    law = deepcopy(
        meta["language_definitions"]["wire_schema_protocol_roles"][
            "runtime_capability_structure"
        ]
    )
    if set(law) != {"manifest", "resolved_profile"}:
        raise ValueError("Runtime output structure has missing or unknown parts")
    if protocol_role == "evaluator-capability-manifest":
        part = law["manifest"]
        derived = {}
    elif protocol_role == "resolved-runtime-profile":
        part = law["resolved_profile"]
        derived = {"runtime_profile": _active_profile_schema(kernel)}
    else:
        raise ValueError("Unknown Runtime output role")
    if set(part) != {"required_members", "field_types"}:
        raise ValueError("Runtime output container is incomplete")
    envelope = artifact_envelope_contract(kernel, artifact_kind)
    groups = (envelope["field_types"], part["field_types"])
    if groups[0].keys() & groups[1].keys():
        raise ValueError("Runtime output duplicates an Artifact envelope field")
    fields = {
        name: _contract_schema(value)
        for group in groups
        for name, value in group.items()
    }
    if fields.keys() & derived.keys():
        raise ValueError("Runtime output duplicates the active profile owner")
    fields.update(derived)
    required = part["required_members"]
    if (
        not isinstance(required, list)
        or len(required) != len(set(required))
        or set(required) != set(fields)
    ):
        raise ValueError("Runtime output membership does not close")
    return {
        "$schema": meta["language_definitions"]["collections"]["artifact_wire_schemas"][
            "field_types"
        ]["schema"]["dialect"],
        "type": "object",
        "properties": fields,
        "required": list(required),
        "unevaluatedProperties": False,
    }


def project_runtime_outputs(kernel: dict[str, Any], language: dict[str, Any]) -> None:
    """Reject authored shadows and project the two actual selected output kinds."""
    for role in ("evaluator-capability-manifest", "resolved-runtime-profile"):
        schemas = [
            row
            for row in language["artifact_wire_schemas"]
            if row.get("protocol_role") == role
        ]
        if len(schemas) != 1:
            raise ValueError("Runtime output role is missing or ambiguous")
        schema = schemas[0]
        contracts = [
            row
            for row in language["artifact_contracts"]
            if row["schema_kind"] == schema["artifact_kind"]
        ]
        if len(contracts) != 1:
            raise ValueError("Runtime output kind binding is missing or ambiguous")
        if "schema" in schema:
            raise ValueError("Runtime output structure cannot be authored by an LDB")
        schema["schema"] = runtime_output_schema(
            kernel, role, contracts[0]["artifact_kind"]
        )
