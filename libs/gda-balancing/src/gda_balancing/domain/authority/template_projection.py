"""Derive fixed Template containers without owning their authored member payloads."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.contract_projection import (
    _contract_schema,
    artifact_envelope_contract,
)


def template_protocol_schema(
    kernel: dict[str, Any], protocol_role: str, artifact_kind: str
) -> dict[str, Any]:
    """Compose the release and instantiation frames from their single owner."""
    meta = kernel["meta_format"]
    structure = meta["language_definitions"]["wire_schema_protocol_roles"][
        "template_structure"
    ]
    if set(structure) != {
        "release",
        "member",
        "member_collection",
        "command_input",
        "receipt",
    }:
        raise ValueError("Kernel Template structure has missing or unknown parts")
    envelope = artifact_envelope_contract(kernel, artifact_kind)
    member = deepcopy(structure["member"])
    if (
        set(member) != {"type", "closed", "required_members", "field_types"}
        or member["type"] != "closed-object"
        or member["closed"] is not True
        or len(member["required_members"]) != len(set(member["required_members"]))
    ):
        raise ValueError("Kernel Template member is not a closed container")
    _contract_schema(member)
    if member["field_types"].get("payload") != {"type": "canonical-json"}:
        raise ValueError(
            "Template payload must retain its separate member Schema owner"
        )
    collection = structure["member_collection"]
    if set(collection) != {"type", "minItems"} or collection["type"] != "list-of":
        raise ValueError("Template member collection has an unknown owner")
    if protocol_role == "template-release":
        part = structure["release"]
        manifest = deepcopy(member)
        del manifest["field_types"]["payload"]
        manifest["required_members"].remove("payload")
        additions = {
            "manifest": {**collection, "items": manifest},
            "members": {**collection, "items": member},
        }
        groups = (envelope["field_types"], part["field_types"], additions)
    elif protocol_role == "template-instantiate-command-input":
        part = structure["command_input"]
        groups = (envelope["field_types"], part["field_types"])
    elif protocol_role == "template-instantiation-receipt":
        part = structure["receipt"]
        groups = (
            envelope["field_types"],
            structure["command_input"]["field_types"],
            part["field_types"],
        )
    else:
        raise ValueError("Unknown Template protocol container")
    for name in ("release", "command_input", "receipt"):
        if set(structure[name]) != {"required_members", "field_types"}:
            raise ValueError("Kernel Template container is incomplete")
        required = structure[name]["required_members"]
        if not isinstance(required, list) or len(required) != len(set(required)):
            raise ValueError("Kernel Template required members are malformed")
    if sum(map(len, groups)) != len(set().union(*groups)):
        raise ValueError("Template container repeats an envelope or payload owner")
    if not set(envelope["required_members"]) <= set(part["required_members"]):
        raise ValueError("Template container omits an Artifact envelope member")
    envelope["required_members"] = list(part["required_members"])
    envelope["field_types"] = {
        name: deepcopy(contract) for group in groups for name, contract in group.items()
    }
    return {
        "$schema": meta["language_definitions"]["collections"]["artifact_wire_schemas"][
            "field_types"
        ]["schema"]["dialect"],
        **_contract_schema(envelope),
    }


def project_template_protocol(kernel: dict[str, Any], language: dict[str, Any]) -> None:
    """Bind three fixed containers; keep every member Schema declaration authored."""
    for role in (
        "template-release",
        "template-instantiate-command-input",
        "template-instantiation-receipt",
    ):
        schemas = [
            row
            for row in language["artifact_wire_schemas"]
            if row.get("protocol_role") == role
        ]
        if len(schemas) != 1:
            raise ValueError("Template protocol role is missing or ambiguous")
        schema = schemas[0]
        contracts = [
            row
            for row in language["artifact_contracts"]
            if row["schema_kind"] == schema["artifact_kind"]
        ]
        if len(contracts) != 1:
            raise ValueError("Template artifact kind binding is missing or ambiguous")
        if "schema" in schema:
            raise ValueError(
                "Template container structure cannot be authored by an LDB"
            )
        schema["schema"] = template_protocol_schema(
            kernel, role, contracts[0]["artifact_kind"]
        )
