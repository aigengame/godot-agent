"""Derive fixed Model binding containers from their single Kernel owner."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.contract_projection import (
    _contract_schema,
    artifact_envelope_contract,
)
from gda_balancing.domain.authority.rir_projection import _owned_contract_schema


def _record(
    fields: dict[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields) if required is None else required,
        "unevaluatedProperties": False,
    }


def _items(schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": schema}


def _copied_contract_schema(contract: dict[str, Any]) -> dict[str, Any]:
    """Project transport shape; delegated authored content keeps its real owner.

    Lock admission compares these values with the selected Authority definitions.
    This projection does not replace Schema, rule or Operation semantic admission.
    """
    kind = contract.get("type")
    if kind in {"canonical-value", "closed-json-schema", "object"}:
        return {}
    if kind == "list":
        return _items({})
    if kind == "path-segments":
        return {**_items({"type": "string", "minLength": 1}), "minItems": 1}
    if kind == "list-of":
        return {
            **_items(_copied_contract_schema(contract["items"])),
            **{
                name: contract[name]
                for name in ("minItems", "uniqueItems")
                if name in contract
            },
        }
    if kind == "closed-discriminated-object":
        return {
            "oneOf": [
                _copied_contract_schema(value)
                for value in contract["variants"].values()
            ]
        }
    if kind == "closed-object" or (kind is None and "required_members" in contract):
        fields = contract["field_types"]
        required = contract["required_members"]
        if set(fields) != set(required) | set(contract.get("optional_members", [])):
            raise ValueError("copied Authority definition contract is incomplete")
        return _record(
            {name: _copied_contract_schema(value) for name, value in fields.items()},
            required,
        )
    return _owned_contract_schema(contract)


def _namespace_schemas(kernel: dict[str, Any]) -> dict[str, Any]:
    """Derive Namespace transport records from the existing semantic owners."""
    meta = kernel["meta_format"]
    roles = meta["language_definitions"]["wire_schema_protocol_roles"]
    law = roles["model_structure"]["namespace_structure"]
    if law["content_validation"] != "exact-selected-authority-definitions":
        raise ValueError("Model namespace content has no semantic admission owner")
    text = {"type": "string", "minLength": 1}

    def record(name: str, supplied: dict[str, Any] | None = None) -> dict[str, Any]:
        contract = law["records"][name]
        fields = {
            key: _copied_contract_schema(value)
            for key, value in contract["field_types"].items()
        }
        supplied = supplied or {}
        if fields.keys() & supplied.keys():
            raise ValueError("Model Namespace record duplicates a semantic owner")
        fields.update(supplied)
        if set(fields) != set(contract["required_members"]):
            raise ValueError("Model Namespace record is incomplete")
        return _record(fields, contract["required_members"])

    reason = meta["diagnostic_reason"]
    reason_schema = _record(
        {
            **{
                name: _copied_contract_schema(value)
                for name, value in reason["member_types"].items()
            },
            "predicate": {
                "oneOf": [
                    _record(
                        {
                            name: _copied_contract_schema(value)
                            for name, value in predicate["member_types"].items()
                        },
                        predicate["required_members"],
                    )
                    for predicate in reason["predicate_schemas"]
                ]
            },
        },
        reason["required_members"],
    )
    diagnostic = deepcopy(meta["admitted_language_index"]["diagnostic"])
    for name, value in diagnostic["field_types"].items():
        if value.get("type") == "refusal-stage":
            diagnostic["field_types"][name] = {
                "enum": kernel["admission"]["refusal_stages"]
            }
    rule = meta["rule"]
    rule_schema = _record(
        {
            "id": text,
            "phase": {"enum": rule["phases"]},
            "judgment": text,
            # These maps are interpreted by the existing Fact/Term rule owner.
            "premises": _items(
                _record(
                    {"bind": {}, "fact_kind": text}, rule["premise_required_members"]
                )
            ),
            "conclusion": _record(
                {"fact_kind": text, "fields": {}}, rule["conclusion_required_members"]
            ),
        },
        rule["required_members"],
    )
    definitions = {
        "diagnostics": _copied_contract_schema(diagnostic),
        "language.reasons": reason_schema,
        "language.rules": rule_schema,
    }
    for entry in meta["package_release"]["semantic_closure"]["projections"]:
        path = entry["authority_path"]
        if path in definitions:
            continue
        parts = path.split(".")
        owner = meta["language_definitions"]
        if parts[:2] == ["language", "quantity"]:
            owner = owner["quantity"]
        elif len(parts) != 2 or parts[0] != "language":
            raise ValueError("Package closure has no Kernel definition owner")
        contract = owner["collections"][parts[-1]]
        definitions[path] = _copied_contract_schema(
            {"type": contract["item_type"]} if "item_type" in contract else contract
        )
    shared: dict[str, Any] = {}
    for name in law["shared_collections"]:
        if name == "language_rules":
            shared[name] = _items(text)
            continue
        binding = roles["rir_structure"]["selected_collections"][name]
        source = binding["source"]
        if source["kind"] == "namespace-member":
            if source["member"] == "types":
                item = _record(
                    {
                        **_copied_contract_schema(
                            meta["package_release"]["type_export"]
                        )["properties"],
                        "package": text,
                    }
                )
            elif source["member"] == "capability_bindings":
                item = _copied_contract_schema(
                    roles["rir_structure"]["containers"]["capability_binding"]
                )
            else:
                raise ValueError("Model Namespace source has no structural owner")
        else:
            item = definitions[source["authority_path"]]
            if binding["shape"] == "package-definition":
                item = _record({"package": text, "definition": item})
        shared[name] = _items(item)
    closure_entries = _items(
        {
            "oneOf": [
                _record(
                    {"authority_path": {"const": path}, "definitions": _items(item)},
                    meta["package_release"]["semantic_closure"]["entry_members"],
                )
                for path, item in sorted(definitions.items())
            ]
        }
    )
    closure = _items(record("package_closure", {"definitions": closure_entries}))
    selected = {
        **shared,
        "packages": _items(record("semantic_package")),
        "package_semantic_closures": closure,
    }
    return {
        "shared": shared,
        "package-lock": {
            **shared,
            "resolution_profile": definitions["language.resolution_profiles"],
            "packages": _items(record("locked_package")),
            "dependency_edges": _items(record("dependency_edge")),
            "package_semantic_closures": closure,
            "diagnostic_reasons": _items(reason_schema),
            "selected_semantics": _record(
                {name: selected[name] for name in law["selected_members"]},
                law["selected_members"],
            ),
        },
        "capability-manifest": {
            **shared,
            "packages": _items(record("capability_package")),
        },
    }


def model_protocol_schema(
    kernel: dict[str, Any], protocol_role: str, artifact_kind: str
) -> dict[str, Any]:
    """Bind the actual Artifact kind without redefining compiled Model facts."""
    meta = kernel["meta_format"]
    structure = deepcopy(
        meta["language_definitions"]["wire_schema_protocol_roles"]["model_structure"]
    )
    if set(structure) != {"containers", "debug_entry", "namespace_structure"}:
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
    if protocol_role in {"package-lock", "capability-manifest"}:
        derived = _namespace_schemas(kernel)[protocol_role]
        if fields.keys() & derived.keys():
            raise ValueError("Model container duplicates its Namespace source")
        fields.update(derived)
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
    return deepcopy(
        {
            "$schema": meta["language_definitions"]["collections"][
                "artifact_wire_schemas"
            ]["field_types"]["schema"]["dialect"],
            "type": "object",
            "properties": fields,
            "required": list(required),
            "unevaluatedProperties": False,
        }
    )


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
