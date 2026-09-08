"""Derive the compiled RIR protocol from its actual Kernel and language owners."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.contract_projection import (
    _contract_schema,
    artifact_envelope_contract,
    ordered_protocol_schema,
)
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.program_reachability import formula_lifecycle_phases


def _object(
    fields: dict[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields) if required is None else required,
        "unevaluatedProperties": False,
    }


def _array(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def _path(value: Any, segments: list[str]) -> Any:
    for member in segments:
        value = value[member]
    return value


def _owned_contract_schema(contract: dict[str, Any]) -> dict[str, Any]:
    """Project existing language/fact contracts, including their semantic holes."""
    value_type = contract.get("type")
    if value_type == "canonical-value":
        # This is an explicit delegation in the existing semantic contract,
        # not a fallback for unknown compiled record forms.
        return {}
    if value_type in {"inventory-member", "inventory-list-path", "signed-int64-path"}:
        return {"type": "string", "minLength": 1}
    if value_type == "closed-int64-interval":
        integer = _contract_schema({"type": "signed-int64"})
        return _object({"minimum": integer, "maximum": integer})
    if value_type == "path-segments":
        return _array({"type": "string", "minLength": 1})
    if value_type == "closed-discriminated-object":
        return {
            "oneOf": [
                _owned_contract_schema(value) for value in contract["variants"].values()
            ]
        }
    if value_type == "list-of":
        return _array(_owned_contract_schema(contract["items"]))
    if value_type == "one-of":
        return {
            "oneOf": [
                _owned_contract_schema(value) for value in contract["alternatives"]
            ]
        }
    if value_type == "closed-object" or (
        value_type is None and "required_members" in contract
    ):
        fields = contract["field_types"]
        required = contract["required_members"]
        optional = contract.get("optional_members", [])
        if set(fields) != set(required) | set(optional):
            raise ValueError("RIR source record contract is incomplete")
        return _object(
            {name: _owned_contract_schema(value) for name, value in fields.items()},
            list(required),
        )
    return _contract_schema(contract)


def rir_collection_output(
    kernel: dict[str, Any], source: dict[str, Any]
) -> tuple[str, str, tuple[str, ...]] | None:
    """Bind an actual semantic source to its fixed compiled output role."""
    fields = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["rir_structure"]["selected_collections"]
    matches = [
        (name, role["shape"], tuple(role.get("excluded_members", [])))
        for name, role in fields.items()
        if all(source.get(key) == value for key, value in role["source"].items())
    ]
    if len(matches) > 1:
        raise ValueError("RIR semantic source has multiple compiled output owners")
    return matches[0] if matches else None


def rir_protocol_schema(
    kernel: dict[str, Any], language_bundle: dict[str, Any], artifact_kind: str
) -> dict[str, Any]:
    """Project one complete RIR role without an independently authored schema."""
    meta = kernel["meta_format"]
    language = language_bundle["language"]
    law = meta["language_definitions"]["wire_schema_protocol_roles"]["rir_structure"]
    containers = law["containers"]
    text = {"type": "string", "minLength": 1}
    boolean = {"type": "boolean"}

    def record(name: str, supplied: dict[str, Any] | None = None) -> dict[str, Any]:
        contract = containers[name]
        fields = {
            member: _owned_contract_schema(value)
            for member, value in contract["field_types"].items()
        }
        supplied = supplied or {}
        if fields.keys() & supplied.keys():
            raise ValueError(f"RIR container duplicates a semantic owner: {name}")
        fields.update(supplied)
        required = contract["required_members"]
        optional = contract.get("optional_members", [])
        if set(fields) != set(required) | set(optional):
            raise ValueError(f"RIR compiled container is incomplete: {name}")
        return _object(fields, list(required))

    profiles = [
        row for row in language["resolution_profiles"] if row.get("default") is True
    ]
    if len(profiles) != 1:
        raise ValueError("RIR has no unique default Resolution profile")
    profile = profiles[0]
    lowering_candidates = [
        row
        for row in language["model_lowerings"]
        if row["id"] == profile["model_lowering"]
        and row["resolution_profile"] == profile["id"]
    ]
    if len(lowering_candidates) != 1:
        raise ValueError("RIR Resolution profile has no unique Model lowering")
    lowering = lowering_candidates[0]
    formula_policy = profile["formula_resolution"]
    runtime = meta["runtime_program"]
    integer = {
        "type": "integer",
        "minimum": runtime["numeric"]["minimum"],
        "maximum": runtime["numeric"]["maximum"],
    }
    invocation = runtime["invocation_contract"]
    fact_fields = meta["fact"]["field_contracts"]
    rules = {row["id"]: row for row in language["rules"]}
    terminal_contracts = {}
    for chain in ("rule_chain", "structured_rule_chain"):
        fact_kind = rules[lowering[chain][-1]["rule"]]["conclusion"]["fact_kind"]
        matches = [row for row in meta["fact"]["schemas"] if row["kind"] == fact_kind]
        if len(matches) != 1:
            raise ValueError("RIR terminal rule has no unique fact contract")
        terminal_contracts[chain] = fact_fields[matches[0]["field_contract"]]
    quantity_fields = terminal_contracts["rule_chain"]
    structured_fields = terminal_contracts["structured_rule_chain"]
    target = _owned_contract_schema(quantity_fields["resolved_symbol"])
    if canonical_bytes(quantity_fields["resolved_symbol"]) != canonical_bytes(
        structured_fields["resolved_symbol"]
    ):
        raise ValueError("RIR Symbol roles disagree on their coordinate contract")
    coordinate = _owned_contract_schema(quantity_fields["type_identity"])
    identified_coordinate = _object({**coordinate["properties"], "identity": text})
    typed = meta["literal_typing"]["typed_envelope_profile"]
    typed_value = _object({typed["type_member"]: coordinate, typed["value_member"]: {}})
    runtime_value = {"oneOf": [integer, boolean, typed_value]}
    initializer_value = {"oneOf": [integer, typed_value]}
    quantity_value = _object(
        {
            member: _owned_contract_schema(quantity_fields[member])
            for member in law["value_signature"]["quantity_members"]
        }
    )
    nominal_value = _object(
        {
            member: _owned_contract_schema(structured_fields[member])
            for member in law["value_signature"]["nominal_members"]
        }
    )
    fixed_literal = {"const": runtime["fixed_value_contracts"]["kernel-boolean"]}
    value_contract = {
        "oneOf": [
            quantity_value,
            nominal_value,
            *[
                {
                    "const": {
                        ("type_identity" if key == "type" else key): value
                        for key, value in row.items()
                    }
                }
                for row in runtime["fixed_value_contracts"].values()
            ],
        ]
    }
    resource_bounds = _owned_contract_schema(
        meta["language_definitions"]["collections"]["operations"]["field_types"][
            "resource_bounds"
        ]
    )
    context_schema = {
        "oneOf": [
            _object({"phase": {"const": phase}})
            for phase in formula_lifecycle_phases(runtime)
        ]
    }
    operation_context = _object(
        {
            "phase": {
                "const": runtime["runtime_configuration"]["lifecycle_roles"]["active"]
            },
        }
    )
    formula_operands = {
        kind: record(
            "formula_" + kind + "_operand",
            {"resolved_symbol": target}
            if kind == "symbol"
            else {"value": integer}
            if kind == "literal"
            else {},
        )
        for kind in meta["formula_resolution"]["operand_kinds"]
    }
    formula_operand = {"oneOf": list(formula_operands.values())}
    formula_reference = _owned_contract_schema(
        meta["language_definitions"]["wire_schema_protocol_roles"]["formula_reference"]
    )
    parameter_alternatives = []
    for signature in value_contract["oneOf"]:
        fields = signature.get("properties")
        if fields is None:
            fields = {
                name: {"const": value} for name, value in signature["const"].items()
            }
        parameter_alternatives.append(_object({"id": text, **fields}))
    formula_parameter = {"oneOf": parameter_alternatives}
    nodes = []
    for kind in meta["formula_resolution"]["body_nodes"]:
        fields: dict[str, Any] = {"node": {"const": kind}, "result": value_contract}
        if kind in {
            row["node"] for row in meta["formula_resolution"]["static_callees"]
        }:
            is_formula = kind == "formula-call"
            callee = "formula" if is_formula else "operation"
            argument_name = "parameter" if is_formula else "port"
            fields[callee] = formula_reference if is_formula else identified_coordinate
            fields["arguments"] = _array(
                _object({argument_name: text, "operand": formula_operand})
            )
        elif kind == "conditional":
            fields.update(
                record(
                    "conditional_operands",
                    {
                        member: formula_operand
                        for member in containers["conditional_operands"][
                            "required_members"
                        ]
                    },
                )["properties"]
            )
        else:
            raise ValueError("RIR Formula node has no compiled representation")
        common = record(
            "formula_node", {"node": fields.pop("node"), "result": fields.pop("result")}
        )
        nodes.append(_object({**common["properties"], **fields}))
    formula = record(
        "formula",
        {
            "parameters": _array(formula_parameter),
            "result": value_contract,
            "body": record(
                "formula_body",
                {"nodes": _array({"oneOf": nodes}), "result": formula_operand},
            ),
            "closure": record("formula_closure", {"resource_charge": resource_bounds}),
        },
    )
    derived_site = record(
        "derived_site",
        {
            "kind": {"const": "derived-symbol"},
            "resolved_symbol": target,
            "context": context_schema,
        },
    )
    operation_site = record(
        "operation_site",
        {
            "kind": {"const": "operation-slot"},
            "operation": identified_coordinate,
            "context": operation_context,
        },
    )
    binding = record(
        "formula_binding",
        {
            "arguments": _array(
                record(
                    "binding_argument",
                    {
                        "operand": {
                            "oneOf": [
                                record("binding_slot_operand")
                                if kind == "slot-parameter"
                                else formula_operands[kind]
                                for kind in law["operand_contexts"]["binding"]
                            ]
                        }
                    },
                )
            ),
            "formula": formula_reference,
            "site": {"oneOf": [derived_site, operation_site]},
        },
    )
    transfers = formula_policy["notation_conversion"]["local_result_inference"]
    eligible = {row["node"] for row in transfers}
    runtime_nodes = {row["id"]: row for row in runtime["nodes"]}
    if not eligible <= runtime_nodes.keys():
        raise ValueError("RIR value-program instruction has no Kernel node owner")
    instructions = []
    for name in sorted(eligible):
        node = runtime_nodes[name]
        if node["family"] != "expression":
            raise ValueError("Formula transfer selected a non-value node")
        fields = {
            member: (
                {"const": name}
                if member == "node"
                else integer
                if member == "literal"
                else text
            )
            for member in node["required_members"]
        }
        instructions.append(_object(fields))
    program = record(
        "value_program",
        {
            "site": {"derived-symbol": derived_site, "operation-slot": operation_site}[
                law["initialization_site"]
            ],
            "target": target,
            "inputs": _array(
                record(
                    "program_input",
                    {
                        "operand": {
                            "oneOf": [
                                formula_operands[kind]
                                for kind in law["operand_contexts"]["initialization"]
                            ]
                        }
                    },
                )
            ),
            "body": _array(
                record("program_instruction", {"instruction": {"oneOf": instructions}})
            ),
            "result": record("program_result"),
            "resource_bounds": resource_bounds,
        },
    )
    symbol_operand = record("entrypoint_symbol_operand", {"symbol": target})
    # Compiled contextual literals carry the formal Type using its authored
    # `type` role; Formula value contracts instead carry resolved type_identity.
    literal_fields = meta["language_definitions"]["collections"][
        "literal_typing_profiles"
    ]["field_types"]
    formal_quantity = _object(
        {
            "id": _owned_contract_schema(literal_fields["id"]),
            **{
                member: _owned_contract_schema(literal_fields[member])
                for member in meta["literal_typing"]["match_members"]
            },
        }
    )
    formal_nominal = _object(
        {
            member: _owned_contract_schema(literal_fields[member])
            for member in ("id", "type", "value_kind")
        }
    )
    literal_operand = record(
        "contextual_literal_operand",
        {
            "context_type": {"oneOf": [formal_quantity, formal_nominal, fixed_literal]},
            "value": runtime_value,
        },
    )
    entry_operands = {
        "symbol": symbol_operand,
        "literal": literal_operand,
        "event-reference": record("event_reference_operand"),
    }
    entry_operand = {
        "oneOf": [
            entry_operands[kind] for kind in law["operand_contexts"]["entrypoint"]
        ]
    }
    port = record("formal_port", {"operation": coordinate})
    alias_policy = meta["language_definitions"]["collections"]["operations"][
        "field_types"
    ]["alias_policy"]["field_types"]
    alias = record(
        "alias",
        {
            "policy": {
                "enum": [
                    alias_policy["read_only"]["const"],
                    alias_policy["writable_groups"]["items"]["field_types"][
                        "semantics"
                    ]["const"],
                ]
            }
        },
    )
    call_operands = [
        literal_operand if kind == "literal" else record("call_" + kind + "_operand")
        for kind in law["operand_contexts"]["call"]
    ]
    call_site = record(
        "call_site",
        {
            "operation": coordinate,
            "parent_operation": coordinate,
            "arguments": _array(
                record("argument", {"port": port, "operand": {"oneOf": call_operands}})
            ),
            "aliases": _array(alias),
            "closure": record("call_closure"),
            "result": record(
                "call_result",
                {
                    "binding": {
                        "oneOf": [
                            _object(
                                {
                                    "kind": {"const": kind},
                                    **({"name": text} if kind == "local" else {}),
                                }
                            )
                            for kind in invocation["result_binding_kinds"]
                        ]
                    }
                },
            ),
            "outcomes": _array(
                record(
                    "call_outcome",
                    {
                        "action": {
                            "oneOf": [
                                _object(
                                    {
                                        "kind": {"const": kind},
                                        **(
                                            {"outcome": text}
                                            if kind == "propagate"
                                            else {}
                                        ),
                                    }
                                )
                                for kind in invocation["outcome_actions"]
                            ]
                        }
                    },
                )
            ),
        },
    )
    mode_fields = meta["language_definitions"]["collections"]["model_lowerings"][
        "field_types"
    ]["assignment_policy"]["field_types"]["roles"]["items"]["field_types"]["modes"][
        "items"
    ]["field_types"]

    def cardinality(member: str) -> dict[str, Any]:
        return {
            "enum": [
                value for value in mode_fields[member]["enum"] if value != "forbidden"
            ]
        }

    entrypoint = record(
        "entrypoint",
        {
            "operation": coordinate,
            "arguments": _array(
                record("argument", {"port": port, "operand": entry_operand})
            ),
            "result": {
                "oneOf": [
                    symbol_operand,
                    record("entrypoint_discard_result"),
                ]
            },
            "aliases": _array(alias),
            "resource_bounds": resource_bounds,
            "scenario_input_contract": record(
                "scenario_inputs",
                {
                    "initializers": _array(
                        record(
                            "initializer",
                            {"target": target, "value": initializer_value},
                        )
                    ),
                    "targets": _array(
                        record(
                            "scenario_target",
                            {
                                "target": target,
                                "cardinality": cardinality("experiment_cardinality"),
                            },
                        )
                    ),
                },
            ),
            "event_local_payload_contract": record(
                "event_inputs",
                {
                    "targets": _array(
                        record(
                            "event_target",
                            {
                                "target": target,
                                "cardinality": cardinality("event_payload_cardinality"),
                            },
                        )
                    ),
                    "event_references": _array(record("event_reference")),
                },
            ),
            "external_fact_contract": record(
                "external_inputs",
                {
                    "targets": _array(
                        record(
                            "external_target",
                            {
                                "target": target,
                                "value_contract": {
                                    "oneOf": [quantity_value, nominal_value]
                                },
                                "cardinality": cardinality("external_fact_cardinality"),
                            },
                        )
                    )
                },
            ),
        },
    )
    selected = _selected_semantics_schema(kernel, lowering, law, record)
    # The actual terminal fact contracts own declaration items; the Kernel
    # compiled container owns the declaration protocol field.
    declarations = {
        "oneOf": [
            _object(
                {
                    member: _owned_contract_schema(value)
                    for member, value in fields.items()
                }
            )
            for fields in terminal_contracts.values()
        ]
    }
    envelope = record(
        "envelope",
        {
            "formulas": _array(formula),
            "formula_bindings": _array(binding),
            "initialization_programs": _array(program),
            "entrypoints": _array(entrypoint),
            "call_sites": _array(call_site),
            "selected_semantics": selected,
            "declarations": _array(declarations),
        },
    )
    common = artifact_envelope_contract(kernel, artifact_kind)
    common_fields = {
        name: _owned_contract_schema(value)
        for name, value in common["field_types"].items()
    }
    if common_fields.keys() & envelope["properties"].keys():
        raise ValueError("RIR payload duplicates a common Artifact envelope field")
    envelope["properties"] = {**common_fields, **envelope["properties"]}
    envelope["required"] = common["required_members"] + envelope["required"]
    return ordered_protocol_schema(
        kernel,
        {
            "$schema": meta["language_definitions"]["collections"][
                "artifact_wire_schemas"
            ]["field_types"]["schema"]["dialect"],
            **envelope,
        },
    )


def _selected_semantics_schema(kernel, lowering, law, record):
    """Derive selected row shapes from existing source and execution contracts."""
    meta = kernel["meta_format"]
    definition_contracts = meta["language_definitions"]
    text = {"type": "string", "minLength": 1}
    selected = {}
    source_items = {}
    for collection in lowering["runtime_projection"]["collections"]:
        source = collection["source"]
        if source["kind"] != "semantic-closure":
            continue
        authority_path = source["authority_path"]
        parts = authority_path.split(".")
        if parts[0] != "language":
            raise ValueError("RIR semantic source has no language contract")
        owner = definition_contracts
        if len(parts) == 3 and parts[1] == "quantity":
            owner = owner["quantity"]
        elif len(parts) != 2:
            raise ValueError("RIR semantic source path is unsupported")
        contract = deepcopy(owner["collections"][parts[-1]])
        if "item_type" in contract:
            contract = {"type": contract["item_type"]}
        output_role = rir_collection_output(kernel, source)
        excluded = output_role[2] if output_role is not None else ()
        if excluded:
            if not set(excluded) <= contract["field_types"].keys():
                raise ValueError("RIR member exclusion has no semantic field owner")
            contract["field_types"] = {
                key: value
                for key, value in contract["field_types"].items()
                if key not in excluded
            }
            contract["required_members"] = [
                key for key in contract["required_members"] if key not in excluded
            ]
            if "optional_members" in contract:
                contract["optional_members"] = [
                    key for key in contract["optional_members"] if key not in excluded
                ]
        if authority_path in source_items:
            raise ValueError("RIR field has multiple source projections")
        source_items[authority_path] = _owned_contract_schema(contract)
    for name, role in law["selected_collections"].items():
        source = role["source"]
        if source["kind"] == "namespace-member":
            if source["member"] == "types":
                item = _object(
                    {
                        **_owned_contract_schema(
                            meta["package_release"]["type_export"]
                        )["properties"],
                        "package": text,
                    }
                )
            elif source["member"] == "capability_bindings":
                item = record("capability_binding")
            else:
                raise ValueError("RIR namespace source has no compiled role")
        else:
            item = source_items[source["authority_path"]]
            if role["shape"] == "package-definition":
                item = _object({"package": text, "definition": item})
        selected[name] = _array(item)
    selected["packages"] = _array(record("namespace_package"))
    closure = meta["runtime_projection"]["execution_closure"]
    laws = {}
    for selector in closure["law_selectors"]:
        cursor = laws
        for segment in selector["output_path"][:-1]:
            cursor = cursor.setdefault(segment, {})
        cursor[selector["output_path"][-1]] = {
            "const": _path(meta, selector["source_path"])
        }
    nodes = closure["nodes"]
    cursor = laws
    for segment in nodes["output_path"][:-1]:
        cursor = cursor.setdefault(segment, {})
    cursor[nodes["output_path"][-1]] = _array(
        {"enum": _path(meta, nodes["source_path"])}
    )
    if "runtime_program" in laws:
        laws["runtime_program"] = _object(laws["runtime_program"], ["nodes"])
    selected["execution_laws"] = _object(laws, ["runtime_program"])
    selected["execution_resources"] = _object(
        {
            row["output_member"]: _owned_contract_schema(
                meta["admitted_language_index"]["resources"]["field_types"][
                    row["source_member"]
                ]
            )
            for row in closure["resources"]
        },
        [],
    )
    reason = meta["diagnostic_reason"]
    predicates = []
    for predicate in reason["predicate_schemas"]:
        predicates.append(
            _object(
                {
                    key: _owned_contract_schema(value)
                    for key, value in predicate["member_types"].items()
                },
                predicate["required_members"],
            )
        )
    reasons = _object(
        {
            **{
                key: _owned_contract_schema(value)
                for key, value in reason["member_types"].items()
            },
            "predicate": {"oneOf": predicates},
        },
        reason["required_members"],
    )
    selected["diagnostic_reasons"] = _array(
        _object({"package": text, "definition": reasons})
    )
    diagnostic = deepcopy(meta["admitted_language_index"]["diagnostic"])
    for name, value in diagnostic["field_types"].items():
        if value.get("type") == "refusal-stage":
            diagnostic["field_types"][name] = {
                "enum": kernel["admission"]["refusal_stages"]
            }
    selected["diagnostics"] = _array(
        _object({"package": text, "definition": _owned_contract_schema(diagnostic)})
    )
    source_items[closure["reasons"]["authority_path"]] = reasons
    source_items[closure["reasons"]["diagnostic_authority_path"]] = (
        _owned_contract_schema(diagnostic)
    )
    closure_entries = [
        _object(
            {
                "authority_path": {"const": path},
                "definitions": _array(item),
            },
            meta["package_release"]["semantic_closure"]["entry_members"],
        )
        for path, item in sorted(source_items.items())
    ]
    selected["package_semantic_closures"] = _array(
        record("namespace_closure", {"definitions": _array({"oneOf": closure_entries})})
    )
    return _object(selected)


def project_rir_schema(kernel: dict[str, Any], language: dict[str, Any]) -> None:
    """Derive RIR grammar and structural identity projection in the lookup index."""
    try:
        for definition in language["artifact_wire_schemas"]:
            if definition.get("protocol_role") != "rir-semantic-payload":
                continue
            if "schema" in definition:
                raise ValueError("RIR structure cannot be authored by an LDB")
            contracts = [
                row
                for row in language["artifact_contracts"]
                if row["schema_kind"] == definition["artifact_kind"]
            ]
            if len(contracts) != 1:
                raise ValueError("RIR artifact binding is not unique")
            contract = contracts[0]
            if "semantic_identity_projection" in contract:
                raise ValueError(
                    "RIR structural identity projection cannot be authored by an LDB"
                )
            contract["semantic_identity_projection"] = deepcopy(
                kernel["meta_format"]["language_definitions"][
                    "wire_schema_protocol_roles"
                ]["rir_structure"]["semantic_projection"]
            )
            definition["schema"] = rir_protocol_schema(
                kernel, {"language": language}, contract["artifact_kind"]
            )
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError(
            "Kernel RIR structure or artifact binding is incomplete"
        ) from error
