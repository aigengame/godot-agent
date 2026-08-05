"""Standard Schema 2.0 Package Release CLI contracts (bADR-0021/0023)."""

import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationInfo,
    field_validator,
)
from pydantic.json_schema import (
    DEFAULT_REF_TEMPLATE,
    GenerateJsonSchema,
    JsonSchemaMode,
)

from gda_balancing.application.package_get import get_package
from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.interfaces.cli.package_contracts import (
    _closed_contract_schema,
    _contract_schema,
    _package_contracts,
    package_list_success_schema as package_list_success_schema,
)
from gda_balancing.schema2.authority import (
    AuthorityContextProvider,
    AuthorityLoadError,
    packaged_authority_context,
)
from gda_balancing.schema2.bootstrap import BOOTSTRAP_REFUSAL_CATALOG
from gda_balancing.schema2.diagnostics import Schema2RefusalReport


def _package_coordinate_contracts() -> dict[str, dict[str, Any]]:
    kernel = packaged_authority_context().kernel
    field_types = (
        kernel.get("meta_format", {})
        .get("language_bundle", {})
        .get("package_descriptor", {})
        .get("field_types")
    )
    if not isinstance(field_types, dict):
        raise ValueError("Kernel package-coordinate contracts are absent")
    contracts: dict[str, dict[str, Any]] = {}
    for name in ("id", "version"):
        contract = field_types.get(name)
        if (
            not isinstance(contract, dict)
            or contract.get("type") != "non-empty-string"
            or not isinstance(contract.get("pattern"), str)
            or not contract["pattern"]
        ):
            raise ValueError(f"Kernel package-coordinate contract is invalid: {name}")
        contracts[name] = contract
    return contracts


class PackageGetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    member: Literal["release", "conformance-vectors"] = "release"

    @field_validator("id", "version")
    @classmethod
    def _validate_kernel_coordinate(cls, value: str, info: ValidationInfo) -> str:
        field_name = info.field_name
        if field_name not in {"id", "version"}:
            raise ValueError("package-coordinate validator reached an unknown field")
        try:
            contract = _package_coordinate_contracts()[field_name]
        except AuthorityLoadError:
            return value
        if re.fullmatch(cast(str, contract["pattern"]), value) is None:
            raise ValueError(f"value does not match the Kernel {field_name} contract")
        return value

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = "validation",
        *,
        union_format: Literal["any_of", "primitive_type_array"] = "any_of",
    ) -> dict[str, Any]:
        schema = super().model_json_schema(
            by_alias=by_alias,
            ref_template=ref_template,
            schema_generator=schema_generator,
            mode=mode,
            union_format=union_format,
        )
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("PackageGetInput schema has no properties")
        for name, contract in _package_coordinate_contracts().items():
            field_schema = properties.get(name)
            if not isinstance(field_schema, dict):
                raise ValueError(f"PackageGetInput schema has no {name} field")
            field_schema["pattern"] = contract["pattern"]
        return schema


class PackageArtifact(RootModel[dict[str, Any]]):
    """One admitted package inventory or exact Package Release."""


def package_get_handler(
    provider: AuthorityContextProvider,
) -> Callable[[PackageGetInput], PackageArtifact | Schema2RefusalReport]:
    def _run(inp: PackageGetInput) -> PackageArtifact | Schema2RefusalReport:
        result = get_package(provider, inp.id, inp.version, inp.member)
        if isinstance(result, Schema2RefusalReport):
            return result
        return PackageArtifact(root=result.root)

    return _run


def _non_empty_string_schema() -> dict[str, object]:
    return {"type": "string", "minLength": 1}


def _opaque_object_schema() -> dict[str, object]:
    """Describe a Kernel-validated object without claiming its member contract.

    Model-program fixtures intentionally carry malformed source/template objects
    for refusal vectors.  Their surrounding fixture is closed here, while the
    Bootstrap owns validation of the opaque object's members.
    """
    return {"type": ["object"]}


def _signed_int64_schema() -> dict[str, object]:
    return {
        "type": "integer",
        "minimum": -(2**63),
        "maximum": 2**63 - 1,
    }


def _closed_named_value_schema(members: list[str]) -> dict[str, object]:
    properties: dict[str, object] = {
        member: (
            _non_empty_string_schema() if member == "name" else _signed_int64_schema()
        )
        for member in members
    }
    return {
        "type": "object",
        "properties": properties,
        "required": members,
        "unevaluatedProperties": False,
    }


def _json_pointer_schema(meta_format: dict[str, Any]) -> dict[str, object]:
    contract = meta_format.get("json_pointer")
    schema = contract.get("schema") if isinstance(contract, dict) else None
    if (
        not isinstance(contract, dict)
        or contract.get("encoding") != "RFC6901"
        or contract.get("target_policy") != "existing-target"
        or not isinstance(schema, dict)
    ):
        raise ValueError("Kernel JSON Pointer contract is incomplete")
    return deepcopy(cast(dict[str, object], schema))


def _package_vector_schemas(meta_format: dict[str, Any]) -> list[dict[str, object]]:
    contract = meta_format.get("package_vector")
    runtime = meta_format.get("runtime_program")
    named_rng = runtime.get("named_rng") if isinstance(runtime, dict) else None
    candidate_encoding = (
        named_rng.get("candidate_encoding") if isinstance(named_rng, dict) else None
    )
    categories = contract.get("categories") if isinstance(contract, dict) else None
    kinds = contract.get("kinds") if isinstance(contract, dict) else None
    if (
        not isinstance(contract, dict)
        or contract.get("closed") is not True
        or not isinstance(categories, list)
        or not categories
        or not all(isinstance(category, str) for category in categories)
        or not isinstance(kinds, list)
        or not kinds
    ):
        raise ValueError("Kernel package-vector contract is incomplete")
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
    candidate_pattern = (
        f"^[{re.escape(candidate_encoding['alphabet'])}]{{{candidate_width}}}$"
    )

    variants: list[dict[str, object]] = []
    for kind in kinds:
        if not isinstance(kind, dict):
            raise ValueError("Kernel package-vector kind is not an object")
        kind_id = kind.get("id")
        required = kind.get("required_members")
        if (
            not isinstance(kind_id, str)
            or not kind_id
            or not isinstance(required, list)
            or not all(isinstance(member, str) for member in required)
        ):
            raise ValueError("Kernel package-vector kind is incomplete")
        properties: dict[str, object] = {
            "category": {"enum": categories},
            "expect": {},
            "id": _non_empty_string_schema(),
            "kind": {"const": kind_id},
        }
        if "operation" in required:
            properties["operation"] = _non_empty_string_schema()
        probe_members = kind.get("probe_members")
        if "probe" in required:
            if not isinstance(probe_members, list) or not all(
                isinstance(member, str) for member in probe_members
            ):
                raise ValueError("Kernel package-vector probe contract is incomplete")
            if kind_id == "operation-relation":
                operators = kind.get("operators")
                declaration_extension = kind.get("declaration_extension")
                declaration_members = kind.get("declaration_members")
                integer_range_members = kind.get("integer_range_members")
                policy_authority_path = kind.get("policy_authority_path")
                policy_contract_members = kind.get("policy_contract_members")
                policy_extension = kind.get("policy_extension")
                policy_members = kind.get("policy_members")
                schedule_projection_members = kind.get("schedule_projection_members")
                if (
                    set(required)
                    != {"category", "id", "kind", "operation", "probe", "role"}
                    or set(probe_members)
                    != {"left_path", "operator", "right_path", "right_value"}
                    or not isinstance(operators, list)
                    or not operators
                    or not all(isinstance(operator, str) for operator in operators)
                    or not isinstance(declaration_extension, str)
                    or not declaration_extension
                    or declaration_members != ["id", "probe"]
                    or integer_range_members != ["start_path", "stop_path", "step_path"]
                    or policy_authority_path != "language.capabilities"
                    or policy_contract_members != ["expect", "path"]
                    or policy_extension != "standard.operation-relation-policy"
                    or policy_members != ["contract", "operation", "relations"]
                    or schedule_projection_members != ["logical_time", "operation"]
                ):
                    raise ValueError(
                        "Kernel operation-relation vector contract is incomplete"
                    )
                range_members = cast(list[str], integer_range_members)
                properties.pop("expect")
                properties["role"] = _non_empty_string_schema()
                member_path_schema: dict[str, object] = {
                    "type": "array",
                    "items": _non_empty_string_schema(),
                    "minItems": 1,
                }
                properties["probe"] = {
                    "type": "object",
                    "properties": {
                        "left_path": member_path_schema,
                        "operator": {"enum": operators},
                        "right_path": {},
                        "right_value": {},
                    },
                    "required": probe_members,
                    "oneOf": [
                        {
                            "properties": {
                                "operator": {
                                    "enum": [
                                        operator
                                        for operator in operators
                                        if operator != "integer-range-equal"
                                    ]
                                },
                                "right_path": member_path_schema,
                                "right_value": {"type": "null"},
                            }
                        },
                        {
                            "properties": {
                                "operator": {
                                    "enum": [
                                        operator
                                        for operator in operators
                                        if operator != "integer-range-equal"
                                    ]
                                },
                                "right_path": {"type": "null"},
                                "right_value": {
                                    "type": [
                                        "array",
                                        "boolean",
                                        "integer",
                                        "object",
                                        "string",
                                    ]
                                },
                            }
                        },
                        {
                            "properties": {
                                "operator": {"const": "integer-range-equal"},
                                "right_path": {"type": "null"},
                                "right_value": {
                                    "type": "object",
                                    "properties": {
                                        member: member_path_schema
                                        for member in range_members
                                    },
                                    "required": range_members,
                                    "unevaluatedProperties": False,
                                },
                            }
                        },
                    ],
                    "unevaluatedProperties": False,
                }
                if set(properties) != set(required):
                    raise ValueError(
                        f"Kernel package-vector kind is not closed: {kind_id}"
                    )
                variants.append(
                    {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "unevaluatedProperties": False,
                    }
                )
                continue
            properties["probe"] = {
                "type": "object",
                "properties": {
                    member: _non_empty_string_schema() for member in probe_members
                },
                "required": probe_members,
                "unevaluatedProperties": False,
            }
        input_members = kind.get("input_members")
        if "input" in required:
            if not isinstance(input_members, list):
                raise ValueError("Kernel package-vector input contract is incomplete")
            if kind_id == "value-program":
                expect_members = kind.get("expect_members")
                instruction_nodes = kind.get("instruction_nodes")
                runtime_nodes = (
                    runtime.get("nodes") if isinstance(runtime, dict) else None
                )
                if (
                    set(input_members)
                    != {
                        "cache",
                        "evaluations",
                        "instructions",
                        "numeric",
                        "operands",
                        "resource_limit",
                        "result",
                        "site",
                    }
                    or not isinstance(expect_members, list)
                    or not isinstance(instruction_nodes, list)
                    or not instruction_nodes
                    or not isinstance(runtime_nodes, list)
                ):
                    raise ValueError(
                        "Kernel value-program vector contract is incomplete"
                    )
                runtime_nodes_by_id = {
                    row["id"]: row
                    for row in runtime_nodes
                    if isinstance(row, dict) and isinstance(row.get("id"), str)
                }
                instruction_variants = []
                for node_id in instruction_nodes:
                    node_contract = runtime_nodes_by_id.get(node_id)
                    node_members = (
                        node_contract.get("required_members")
                        if isinstance(node_contract, dict)
                        else None
                    )
                    if (
                        not isinstance(node_id, str)
                        or not isinstance(node_members, list)
                        or not all(isinstance(member, str) for member in node_members)
                    ):
                        raise ValueError(
                            "Kernel value-program instruction contract is incomplete"
                        )
                    instruction_variants.append(
                        {
                            "type": "object",
                            "properties": {
                                member: (
                                    {"const": node_id}
                                    if member == "node"
                                    else (
                                        _signed_int64_schema()
                                        if member == "literal"
                                        else _non_empty_string_schema()
                                    )
                                )
                                for member in node_members
                            },
                            "required": node_members,
                            "unevaluatedProperties": False,
                        }
                    )
                properties["input"] = {
                    "type": "object",
                    "properties": {
                        "cache": {"type": "boolean"},
                        "evaluations": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 2**63 - 1,
                        },
                        "instructions": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "evaluation_site_identity": (
                                        _non_empty_string_schema()
                                    ),
                                    "instruction": {"oneOf": instruction_variants},
                                },
                                "required": [
                                    "evaluation_site_identity",
                                    "instruction",
                                ],
                                "unevaluatedProperties": False,
                            },
                        },
                        "numeric": {
                            "type": "object",
                            "properties": {
                                "maximum": _signed_int64_schema(),
                                "minimum": _signed_int64_schema(),
                            },
                            "required": ["maximum", "minimum"],
                            "unevaluatedProperties": False,
                        },
                        "operands": {
                            "type": "array",
                            "items": _closed_named_value_schema(["name", "value"]),
                        },
                        "resource_limit": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 2**63 - 1,
                        },
                        "result": _non_empty_string_schema(),
                        "site": _non_empty_string_schema(),
                    },
                    "required": input_members,
                    "unevaluatedProperties": False,
                }
                if set(expect_members) != {
                    "cache_entries",
                    "charge",
                    "outcome",
                    "result",
                    "result_artifact",
                    "signal",
                    "site",
                }:
                    raise ValueError(
                        "Kernel value-program expectation contract is incomplete"
                    )
                expectation_base: dict[str, object] = {
                    "cache_entries": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 2**63 - 1,
                    },
                    "charge": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 2**63 - 1,
                    },
                    "site": _non_empty_string_schema(),
                }
                properties["expect"] = {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {
                                **expectation_base,
                                "outcome": {"const": "admitted"},
                                "result": _signed_int64_schema(),
                                "result_artifact": {"const": True},
                                "signal": {"type": "null"},
                            },
                            "required": expect_members,
                            "unevaluatedProperties": False,
                        },
                        {
                            "type": "object",
                            "properties": {
                                **expectation_base,
                                "outcome": {"const": "refused"},
                                "result": {"type": "null"},
                                "result_artifact": {"const": False},
                                "signal": {"enum": ["numeric-overflow", "step-limit"]},
                            },
                            "required": expect_members,
                            "unevaluatedProperties": False,
                        },
                    ]
                }
                if set(properties) != set(required):
                    raise ValueError(
                        f"Kernel package-vector kind is not closed: {kind_id}"
                    )
                variants.append(
                    {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "unevaluatedProperties": False,
                    }
                )
                continue
            if kind_id == "scheduler-scenario":
                mutation_detectors = kind.get("mutation_detectors")
                if (
                    not isinstance(mutation_detectors, list)
                    or mutation_detectors != sorted(set(mutation_detectors))
                    or not all(
                        isinstance(detector, str) and detector
                        for detector in mutation_detectors
                    )
                ):
                    raise ValueError(
                        "Kernel scheduler-vector mutation detector contract is incomplete"
                    )
                properties["detects_mutation"] = {
                    "oneOf": [{"enum": mutation_detectors}, {"type": "null"}]
                }
                expect_members = kind.get("expect_members")
                event_members = kind.get("event_members")
                observation_members = kind.get("observation_members")
                state_members = kind.get("state_value_members")
                target_states = kind.get("target_states")
                scheduler = (
                    runtime.get("scheduler") if isinstance(runtime, dict) else None
                )
                ordering = (
                    scheduler.get("ordering") if isinstance(scheduler, dict) else None
                )
                phase_order = (
                    next(
                        (
                            row.get("rank")
                            for row in ordering
                            if isinstance(row, dict) and row.get("member") == "phase"
                        ),
                        None,
                    )
                    if isinstance(ordering, list)
                    else None
                )
                if (
                    set(input_members)
                    != {"events", "initial_states", "terminal_condition"}
                    or not isinstance(expect_members, list)
                    or set(expect_members)
                    != {
                        "event_order",
                        "observations",
                        "outcome",
                        "signal",
                        "terminal_reason",
                        "terminal_states",
                    }
                    or not isinstance(event_members, list)
                    or set(event_members)
                    != {
                        "cancel_requested",
                        "enqueue_sequence",
                        "id",
                        "logical_time",
                        "parent_id",
                        "phase",
                        "priority",
                        "scenario",
                        "state_delta",
                        "status",
                    }
                    or not isinstance(observation_members, list)
                    or set(observation_members)
                    != {"event_id", "scenario", "state_after", "state_before"}
                    or not isinstance(state_members, list)
                    or set(state_members) != {"scenario", "value"}
                    or not isinstance(target_states, list)
                    or not target_states
                    or not all(isinstance(state, str) for state in target_states)
                    or not isinstance(phase_order, list)
                    or not phase_order
                    or not all(isinstance(phase, str) for phase in phase_order)
                ):
                    raise ValueError("Kernel scheduler-vector contract is incomplete")
                state_schema = {
                    "type": "object",
                    "properties": {
                        "scenario": _non_empty_string_schema(),
                        "value": _signed_int64_schema(),
                    },
                    "required": state_members,
                    "unevaluatedProperties": False,
                }
                properties["input"] = {
                    "type": "object",
                    "properties": {
                        "events": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "cancel_requested": {"type": "boolean"},
                                    "enqueue_sequence": {
                                        "type": "integer",
                                        "minimum": 0,
                                        "maximum": 2**63 - 1,
                                    },
                                    "id": _non_empty_string_schema(),
                                    "logical_time": _signed_int64_schema(),
                                    "parent_id": {
                                        "oneOf": [
                                            _non_empty_string_schema(),
                                            {"type": "null"},
                                        ]
                                    },
                                    "phase": {"enum": phase_order},
                                    "priority": _signed_int64_schema(),
                                    "scenario": _non_empty_string_schema(),
                                    "state_delta": _signed_int64_schema(),
                                    "status": {"enum": target_states},
                                },
                                "required": event_members,
                                "unevaluatedProperties": False,
                            },
                        },
                        "initial_states": {
                            "type": "array",
                            "items": state_schema,
                        },
                        "terminal_condition": _non_empty_string_schema(),
                    },
                    "required": input_members,
                    "unevaluatedProperties": False,
                }
                properties["expect"] = {
                    "type": "object",
                    "properties": {
                        "event_order": {
                            "type": "array",
                            "items": _non_empty_string_schema(),
                        },
                        "observations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "event_id": _non_empty_string_schema(),
                                    "scenario": _non_empty_string_schema(),
                                    "state_after": _signed_int64_schema(),
                                    "state_before": _signed_int64_schema(),
                                },
                                "required": observation_members,
                                "unevaluatedProperties": False,
                            },
                        },
                        "outcome": _non_empty_string_schema(),
                        "signal": {
                            "oneOf": [_non_empty_string_schema(), {"type": "null"}]
                        },
                        "terminal_reason": {
                            "oneOf": [_non_empty_string_schema(), {"type": "null"}]
                        },
                        "terminal_states": {
                            "type": "array",
                            "items": state_schema,
                        },
                    },
                    "required": expect_members,
                    "unevaluatedProperties": False,
                }
                if set(properties) != set(required):
                    raise ValueError(
                        f"Kernel package-vector kind is not closed: {kind_id}"
                    )
                variants.append(
                    {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "unevaluatedProperties": False,
                    }
                )
                continue
            if set(input_members) != {"seed", "state_names", "values"}:
                raise ValueError("Kernel runtime-vector input contract is incomplete")
            state_members = kind.get("state_value_members")
            if not isinstance(state_members, list):
                raise ValueError("Kernel runtime-vector state contract is incomplete")
            properties["input"] = {
                "type": "object",
                "properties": {
                    "seed": _signed_int64_schema(),
                    "state_names": {
                        "type": "array",
                        "items": _non_empty_string_schema(),
                        "uniqueItems": True,
                    },
                    "values": {
                        "type": "array",
                        "items": _closed_named_value_schema(state_members),
                    },
                },
                "required": input_members,
                "unevaluatedProperties": False,
            }
            expect_members = kind.get("expect_members")
            rng_draw_members = kind.get("rng_draw_members")
            if not isinstance(expect_members, list) or not isinstance(
                rng_draw_members, list
            ):
                raise ValueError(
                    "Kernel runtime-vector expectation contract is incomplete"
                )
            properties["expect"] = {
                "type": "object",
                "properties": {
                    "outcome": _non_empty_string_schema(),
                    "rng_draws": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "candidate_hex": {
                                    "type": "string",
                                    "pattern": candidate_pattern,
                                },
                                "index": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 2**63 - 1,
                                },
                                "stream": _non_empty_string_schema(),
                                "value": _signed_int64_schema(),
                            },
                            "required": rng_draw_members,
                            "unevaluatedProperties": False,
                        },
                    },
                    "state_after": {
                        "type": "array",
                        "items": _closed_named_value_schema(state_members),
                    },
                },
                "required": expect_members,
                "unevaluatedProperties": False,
            }
        if set(properties) != set(required):
            raise ValueError(f"Kernel package-vector kind is not closed: {kind_id}")
        variants.append(
            {
                "type": "object",
                "properties": properties,
                "required": required,
                "unevaluatedProperties": False,
            }
        )
    return variants


def _rule_vector_schema(meta_format: dict[str, Any]) -> dict[str, object]:
    rule_contract = meta_format.get("rule")
    fact_contract = meta_format.get("fact")
    if not isinstance(rule_contract, dict) or not isinstance(fact_contract, dict):
        raise ValueError("Kernel rule-vector contract is incomplete")
    phases = rule_contract.get("phases")
    fact_members = fact_contract.get("required_members")
    if (
        not isinstance(phases, list)
        or not phases
        or not all(isinstance(phase, str) for phase in phases)
        or not isinstance(fact_members, list)
        or set(fact_members) != {"fields", "kind"}
    ):
        raise ValueError("Kernel rule-vector fact contract is incomplete")
    fact_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "fields": {},
            "kind": _non_empty_string_schema(),
        },
        "required": fact_members,
        "unevaluatedProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "expect": fact_schema,
            "id": _non_empty_string_schema(),
            "input": {
                "type": "object",
                "properties": {
                    "facts": {"type": "array", "items": fact_schema},
                    "judgment": _non_empty_string_schema(),
                    "phase": {"enum": phases},
                },
                "required": ["facts", "judgment", "phase"],
                "unevaluatedProperties": False,
            },
            "rule": _non_empty_string_schema(),
        },
        "required": ["expect", "id", "input", "rule"],
        "unevaluatedProperties": False,
    }


def _diagnostic_vector_schema(meta_format: dict[str, Any]) -> dict[str, object]:
    contract = meta_format.get("diagnostic_reason")
    if not isinstance(contract, dict):
        raise ValueError("Kernel diagnostic-vector contract is incomplete")
    required = contract.get("vector_required_members")
    member_types = contract.get("vector_member_types")
    if (
        not isinstance(required, list)
        or not all(isinstance(member, str) for member in required)
        or not isinstance(member_types, dict)
        or set(member_types) != set(required) - {"input"}
    ):
        raise ValueError("Kernel diagnostic-vector members are incomplete")
    properties = {
        member: _contract_schema(cast(dict[str, Any], member_types[member]))
        for member in member_types
    }
    properties["input"] = {}
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "unevaluatedProperties": False,
    }


def _model_program_vector_schemas(
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> list[dict[str, object]]:
    contract = meta_format.get("model_program_vector")
    pointer_schema = _json_pointer_schema(meta_format)
    if not isinstance(contract, dict):
        raise ValueError("Kernel model-program vector contract is incomplete")
    required = contract.get("required_members")
    categories = contract.get("categories")
    category_outcomes = contract.get("category_outcomes")
    category_relations = contract.get("category_relations")
    fixture_modes = contract.get("fixture_modes")
    expect_members = contract.get("expect_members")
    diagnostic_members = contract.get("diagnostic_members")
    relation_kinds = contract.get("relation_kinds")
    lock_members = contract.get("lock_oracle_members")
    if (
        not isinstance(required, list)
        or set(required) != {"category", "expect", "id", "source_fixture"}
        or not isinstance(categories, list)
        or not isinstance(category_outcomes, dict)
        or not isinstance(category_relations, dict)
        or not isinstance(fixture_modes, dict)
        or not isinstance(expect_members, list)
        or diagnostic_members != ["code", "stage", "pointer"]
        or not isinstance(relation_kinds, list)
        or not isinstance(lock_members, list)
    ):
        raise ValueError("Kernel model-program vector members are incomplete")

    fixture_variants: list[dict[str, object]] = []
    for mode, mode_contract in fixture_modes.items():
        mode_required = (
            mode_contract.get("required_members")
            if isinstance(mode_contract, dict)
            else None
        )
        if (
            not isinstance(mode, str)
            or not isinstance(mode_required, list)
            or "mode" not in mode_required
            or "source" not in mode_required
        ):
            raise ValueError("Kernel model-program fixture contract is incomplete")
        properties: dict[str, object] = {
            "mode": {"const": mode},
            "source": _opaque_object_schema(),
        }
        if mode == "indexed-repeat":
            index_encoding = mode_contract.get("index_encoding")
            if not isinstance(index_encoding, str) or not index_encoding:
                raise ValueError("Kernel indexed-repeat fixture contract is incomplete")
            properties.update(
                {
                    "collection_path": {
                        "type": "array",
                        "items": _non_empty_string_schema(),
                        "minItems": 1,
                    },
                    "count_resource_path": _non_empty_string_schema(),
                    "count_offset": {"enum": [0, 1]},
                    "template": _opaque_object_schema(),
                    "index_member": _non_empty_string_schema(),
                    "index_prefix": _non_empty_string_schema(),
                    "index_width": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 18,
                    },
                    "index_encoding": {"const": index_encoding},
                }
            )
        elif mode != "literal":
            raise ValueError(f"unknown Kernel model-program fixture mode: {mode}")
        if set(properties) != set(mode_required):
            raise ValueError("Kernel model-program fixture members are incomplete")
        fixture_variants.append(
            {
                "type": "object",
                "properties": properties,
                "required": mode_required,
                "unevaluatedProperties": False,
            }
        )

    diagnostic_pairs = {
        (item.get("code"), item.get("stage"))
        for item in cast(list[dict[str, Any]], language_bundle.get("diagnostics", []))
        if isinstance(item, dict)
        and isinstance(item.get("code"), str)
        and isinstance(item.get("stage"), str)
    }
    if not diagnostic_pairs:
        raise ValueError("LDB model-program diagnostic catalog is incomplete")
    diagnostic_schema: dict[str, object] = {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "code": {"const": code},
                    "stage": {"const": stage},
                    "pointer": {
                        **pointer_schema,
                    },
                },
                "required": diagnostic_members,
                "unevaluatedProperties": False,
            }
            for code, stage in sorted(diagnostic_pairs)
        ]
    }
    lock_schema: dict[str, object] = {
        "type": "object",
        "properties": {member: {} for member in lock_members},
        "required": lock_members,
        "unevaluatedProperties": False,
    }
    identity_schema = _non_empty_string_schema()

    def relation_schema(allowed: list[str]) -> dict[str, object]:
        variants: list[dict[str, object]] = []
        for kind in allowed:
            if kind not in relation_kinds:
                raise ValueError(
                    "Kernel model-program category relation is not declared"
                )
            variants.append(
                {
                    "type": "object",
                    "properties": {
                        "kind": {"const": kind},
                        "reference": (
                            {"type": "null"}
                            if kind == "independent"
                            else _non_empty_string_schema()
                        ),
                    },
                    "required": ["kind", "reference"],
                    "unevaluatedProperties": False,
                }
            )
        if not variants:
            raise ValueError("Kernel model-program category has no relation")
        return {"oneOf": variants}

    vector_variants: list[dict[str, object]] = []
    for category in categories:
        outcomes = category_outcomes.get(category)
        relations = category_relations.get(category)
        if (
            not isinstance(category, str)
            or not category
            or not isinstance(outcomes, list)
            or not outcomes
            or not all(outcome in {"admitted", "refused"} for outcome in outcomes)
            or not isinstance(relations, list)
            or not all(isinstance(kind, str) for kind in relations)
        ):
            raise ValueError("Kernel model-program category contract is incomplete")
        for outcome in outcomes:
            admitted = outcome == "admitted"
            expect_properties: dict[str, object] = {
                "outcome": {"const": outcome},
                "diagnostics": {
                    "type": "array",
                    "items": diagnostic_schema,
                    **({"maxItems": 0} if admitted else {"minItems": 1}),
                },
                "semantic_artifacts": {"const": admitted},
                "declaration_count": (
                    {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 2**63 - 1,
                    }
                    if admitted
                    else {"const": 0}
                ),
                "rir_identity": identity_schema if admitted else {"type": "null"},
                "debug_map_identity": (
                    identity_schema if admitted else {"type": "null"}
                ),
                "lock_oracle": lock_schema if admitted else {"type": "null"},
                "relation": relation_schema(relations),
            }
            if set(expect_properties) != set(expect_members):
                raise ValueError(
                    "Kernel model-program expectation members are incomplete"
                )
            vector_variants.append(
                {
                    "type": "object",
                    "properties": {
                        "category": {"const": category},
                        "expect": {
                            "type": "object",
                            "properties": expect_properties,
                            "required": expect_members,
                            "unevaluatedProperties": False,
                        },
                        "id": _non_empty_string_schema(),
                        "source_fixture": {"oneOf": fixture_variants},
                    },
                    "required": required,
                    "unevaluatedProperties": False,
                }
            )
    return vector_variants


def _conformance_vector_schema(
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> dict[str, object]:
    package_vector = meta_format.get("package_vector")
    if not isinstance(package_vector, dict):
        raise ValueError("Kernel package-vector contract is incomplete")
    return {
        "oneOf": [
            _rule_vector_schema(meta_format),
            _diagnostic_vector_schema(meta_format),
            *_package_vector_schemas(meta_format),
            *_model_program_vector_schemas(meta_format, language_bundle),
        ]
    }


def package_release_success_schema() -> dict[str, object]:
    (
        _identity,
        _descriptor,
        release,
        _vector_set,
        _meta_format,
        _language_bundle,
    ) = _package_contracts()
    return _closed_contract_schema(release)


def package_vector_set_success_schema() -> dict[str, object]:
    (
        _identity,
        _descriptor,
        _release,
        vector_set,
        meta_format,
        language_bundle,
    ) = _package_contracts()
    schema = _closed_contract_schema(vector_set)
    properties = cast(dict[str, object], schema["properties"])
    properties["vector_definitions"] = {
        "type": "array",
        "items": _conformance_vector_schema(meta_format, language_bundle),
    }
    return schema


def package_get_success_schema() -> dict[str, object]:
    (
        _identity_contract,
        _descriptor_contract,
        _release_contract,
        _vector_set_contract,
        _meta_format,
        _language_bundle,
    ) = _package_contracts()
    return {
        "oneOf": [
            package_release_success_schema(),
            package_vector_set_success_schema(),
        ]
    }


PACKAGE_GET = CommandDescriptor(
    group="package",
    command="get",
    description="Get one exact member of a Package Release.",
    input_model=PackageGetInput,
    output_model=PackageArtifact,
    handler=package_get_handler(packaged_authority_context),
    fixtures=ConformanceFixtures(
        valid_args=("--id", "core.quantity", "--version", "2.1.0"),
        refusing_args=("--id", "missing.package", "--version", "1.0.0"),
    ),
    schema_major=2,
    structured_params=True,
    refusal_catalog=BOOTSTRAP_REFUSAL_CATALOG,
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
    success_schema=package_get_success_schema,
)
