"""Derive fixed Model binding containers from their single Kernel owner."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.contract_projection import (
    _contract_schema,
    artifact_envelope_contract,
)


def model_protocol_schema(
    kernel: dict[str, Any], protocol_role: str, artifact_kind: str
) -> dict[str, Any]:
    """Bind the actual Artifact kind without redefining compiled Model facts."""
    meta = kernel["meta_format"]
    structure = deepcopy(
        meta["language_definitions"]["wire_schema_protocol_roles"]["model_structure"]
    )
    if set(structure) != {"containers", "debug_entry"}:
        raise ValueError("Kernel Model structure has unknown or missing parts")
    part = structure["containers"][protocol_role]
    if set(part) != {"required_members", "field_types"}:
        raise ValueError("Kernel Model container has unknown or missing members")
    common = artifact_envelope_contract(kernel, artifact_kind)
    fields = {
        name: _contract_schema(value) for name, value in common["field_types"].items()
    }
    if set(fields) & set(part["field_types"]):
        raise ValueError("Model container duplicates the Artifact envelope")
    fields.update(
        {name: _contract_schema(value) for name, value in part["field_types"].items()}
    )
    if protocol_role == "debug-map":
        if "entries" in fields:
            raise ValueError("Debug entries have two structural owners")
        fields["entries"] = {
            "type": "array",
            "items": _contract_schema(structure["debug_entry"]),
        }
    required = part["required_members"]
    if (
        not isinstance(required, list)
        or not all(isinstance(name, str) for name in required)
        or len(required) != len(set(required))
        or set(required) != set(fields)
    ):
        raise ValueError("Kernel Model container membership is incomplete")
    return {
        "$schema": meta["language_definitions"]["collections"]["artifact_wire_schemas"][
            "field_types"
        ]["schema"]["dialect"],
        "type": "object",
        "properties": fields,
        "required": list(required),
        "unevaluatedProperties": False,
    }


def project_model_protocols(kernel: dict[str, Any], language: dict[str, Any]) -> None:
    """Populate Model wire views without accepting physical Schema overrides."""
    try:
        containers = kernel["meta_format"]["language_definitions"][
            "wire_schema_protocol_roles"
        ]["model_structure"]["containers"]
        for role in containers:
            definitions = [
                row
                for row in language["artifact_wire_schemas"]
                if row.get("protocol_role") == role
            ]
            if len(definitions) != 1:
                raise ValueError("Model protocol role is missing or ambiguous")
            definition = definitions[0]
            contracts = [
                row
                for row in language["artifact_contracts"]
                if row["schema_kind"] == definition["artifact_kind"]
            ]
            if len(contracts) != 1 or "schema" in definition:
                raise ValueError("Model container has an ambiguous or authored owner")
            definition["schema"] = model_protocol_schema(
                kernel, role, contracts[0]["artifact_kind"]
            )
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError(
            "Kernel Model structure or artifact binding is incomplete"
        ) from error
