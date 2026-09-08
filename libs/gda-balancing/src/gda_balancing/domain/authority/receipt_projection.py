"""Derive receipt framing and transport-independent identity from one Kernel owner."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.contract_projection import (
    _contract_schema,
    artifact_envelope_contract,
)


def _receipt_structure(meta_format: dict[str, Any]) -> dict[str, Any]:
    structure = meta_format["language_definitions"]["wire_schema_protocol_roles"][
        "receipt_structure"
    ]
    if (
        not isinstance(structure, dict)
        or set(structure) != {"required_members", "bindings", "transport"}
        or not isinstance(structure["bindings"], dict)
        or not isinstance(structure["transport"], dict)
        or not structure["bindings"]
        or not structure["transport"]
    ):
        raise ValueError("Kernel receipt binding and transport structure is incomplete")
    return structure


def receipt_protocol_schema(
    kernel: dict[str, Any], artifact_kind: str
) -> dict[str, Any]:
    """Project the exact fixed receipt encoding, with the actual selected kind."""
    meta = kernel["meta_format"]
    structure = _receipt_structure(meta)
    envelope = artifact_envelope_contract(kernel, artifact_kind)
    groups = (envelope["field_types"], structure["bindings"], structure["transport"])
    if sum(len(group) for group in groups) != len(set().union(*groups)):
        raise ValueError("Receipt structure duplicates an envelope or payload owner")
    envelope["field_types"] = {
        name: deepcopy(contract) for group in groups for name, contract in group.items()
    }
    required = structure["required_members"]
    if not isinstance(required, list) or len(required) != len(set(required)):
        raise ValueError("Receipt required members are malformed")
    envelope["required_members"] = list(required)
    # These required arrays are the receipt's existing identified encoding. The
    # general ordering of newly derived protocols would change its wire identity.
    return {
        "$schema": meta["language_definitions"]["collections"]["artifact_wire_schemas"][
            "field_types"
        ]["schema"]["dialect"],
        **_contract_schema(envelope),
    }


def _receipt_binding(language: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    schemas = [
        row
        for row in language["artifact_wire_schemas"]
        if row.get("protocol_role") == "artifact-set-receipt"
    ]
    if len(schemas) != 1:
        raise ValueError("Receipt protocol role is not unique")
    contracts = [
        row
        for row in language["artifact_contracts"]
        if row["schema_kind"] == schemas[0]["artifact_kind"]
    ]
    if len(contracts) != 1:
        raise ValueError("Receipt artifact binding is not unique")
    return schemas[0], contracts[0]


def project_receipt_protocol(kernel: dict[str, Any], language: dict[str, Any]) -> None:
    """Generate a private identity projection; authored overrides always refuse."""
    contracts = language["artifact_contracts"]
    if any("identity_excluded_members" in row for row in contracts):
        raise ValueError("Artifact identity exclusions cannot be authored by an LDB")
    schema, receipt = _receipt_binding(language)
    if "schema" in schema:
        raise ValueError("Receipt structure cannot be authored by an LDB")
    schema["schema"] = receipt_protocol_schema(kernel, receipt["artifact_kind"])
    transport = list(_receipt_structure(kernel["meta_format"])["transport"])
    for contract in contracts:
        contract["identity_excluded_members"] = transport if contract is receipt else []


def artifact_contract_declarations(
    meta_format: dict[str, Any], language: dict[str, Any]
) -> list[dict[str, Any]]:
    """Check generated projection values before applying the authored grammar.

    The same private snapshot member is present on every derived ArtifactContract.
    Physical inputs cannot supply it: project_receipt_protocol refuses re-entry.
    """
    _, receipt = _receipt_binding(language)
    transport = list(_receipt_structure(meta_format)["transport"])
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
