"""Derive one closed publication protocol from its Kernel-owned structure."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.contract_projection import (
    _contract_schema,
    artifact_envelope_contract,
)


def _publication_structure(meta_format: dict[str, Any]) -> dict[str, Any]:
    protocols = meta_format["language_definitions"]["wire_schema_protocol_roles"]
    structure = protocols["publication_structure"]
    if (
        "receipt_structure" in protocols
        or not isinstance(structure, dict)
        or set(structure) != {"manifest", "receipt", "index"}
    ):
        raise ValueError("Kernel publication structure is incomplete")
    for name in ("manifest", "index"):
        part = structure[name]
        if (
            not isinstance(part, dict)
            or set(part) != {"required_members", "field_types"}
            or not isinstance(part["field_types"], dict)
            or not part["field_types"]
        ):
            raise ValueError("Kernel publication payload is incomplete")
    receipt = structure["receipt"]
    if (
        not isinstance(receipt, dict)
        or set(receipt) != {"required_members", "bindings", "transport"}
        or not isinstance(receipt["bindings"], dict)
        or not isinstance(receipt["transport"], dict)
        or not receipt["bindings"]
        or not receipt["transport"]
    ):
        raise ValueError("Kernel receipt binding and transport structure is incomplete")
    return structure


def publication_protocol_schema(
    kernel: dict[str, Any], protocol_role: str, artifact_kind: str
) -> dict[str, Any]:
    """Project one of the three fixed publication parts with its actual kind."""
    meta = kernel["meta_format"]
    structure = _publication_structure(meta)
    envelope = artifact_envelope_contract(kernel, artifact_kind)
    if protocol_role == "artifact-set-manifest":
        part = structure["manifest"]
        groups = (envelope["field_types"], part["field_types"])
    elif protocol_role == "publication-index":
        part = structure["index"]
        groups = (envelope["field_types"], part["field_types"])
    elif protocol_role == "artifact-set-receipt":
        part = structure["receipt"]
        groups = (envelope["field_types"], part["bindings"], part["transport"])
    else:
        raise ValueError("Unknown publication protocol part")
    if sum(len(group) for group in groups) != len(set().union(*groups)):
        raise ValueError(
            "Publication structure duplicates an envelope or payload owner"
        )
    envelope["field_types"] = {
        name: deepcopy(contract) for group in groups for name, contract in group.items()
    }
    required = part["required_members"]
    if (
        not isinstance(required, list)
        or not all(isinstance(name, str) for name in required)
        or len(required) != len(set(required))
    ):
        raise ValueError("Publication required members are malformed")
    envelope["required_members"] = list(required)
    # Preserve the existing retained fields' identified array encoding. Generic
    # ordering of newly derived protocols would add unrelated identity changes.
    return {
        "$schema": meta["language_definitions"]["collections"]["artifact_wire_schemas"][
            "field_types"
        ]["schema"]["dialect"],
        **_contract_schema(envelope),
    }


def _publication_binding(
    language: dict[str, Any], protocol_role: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    schemas = [
        row
        for row in language["artifact_wire_schemas"]
        if row.get("protocol_role") == protocol_role
    ]
    if len(schemas) != 1:
        raise ValueError("Publication protocol role is not unique")
    contracts = [
        row
        for row in language["artifact_contracts"]
        if row["schema_kind"] == schemas[0]["artifact_kind"]
    ]
    if len(contracts) != 1:
        raise ValueError("Publication artifact binding is not unique")
    return schemas[0], contracts[0]


def project_publication_protocol(
    kernel: dict[str, Any], language: dict[str, Any]
) -> None:
    """Generate all three parts and their private, closed identity projections."""
    contracts = language["artifact_contracts"]
    if any("identity_excluded_members" in row for row in contracts):
        raise ValueError("Artifact identity exclusions cannot be authored by an LDB")
    for role in ("artifact-set-manifest", "artifact-set-receipt", "publication-index"):
        schema, contract = _publication_binding(language, role)
        if "schema" in schema:
            raise ValueError("Publication structure cannot be authored by an LDB")
        schema["schema"] = publication_protocol_schema(
            kernel, role, contract["artifact_kind"]
        )
    _, receipt = _publication_binding(language, "artifact-set-receipt")
    transport = list(
        _publication_structure(kernel["meta_format"])["receipt"]["transport"]
    )
    for contract in contracts:
        contract["identity_excluded_members"] = transport if contract is receipt else []


def artifact_contract_declarations(
    meta_format: dict[str, Any], language: dict[str, Any]
) -> list[dict[str, Any]]:
    """Check generated projection values before applying the authored grammar.

    The same private snapshot member is present on every derived ArtifactContract.
    Physical inputs cannot supply it: project_publication_protocol refuses re-entry.
    """
    _, receipt = _publication_binding(language, "artifact-set-receipt")
    transport = list(_publication_structure(meta_format)["receipt"]["transport"])
    declarations = []
    for contract in language["artifact_contracts"]:
        expected = transport if contract is receipt else []
        if contract.get("identity_excluded_members") != expected:
            raise ValueError(
                "Artifact identity projection differs from its Kernel owner"
            )
        declarations.append(
            {
                key: value
                for key, value in contract.items()
                if key != "identity_excluded_members"
            }
        )
    return declarations
