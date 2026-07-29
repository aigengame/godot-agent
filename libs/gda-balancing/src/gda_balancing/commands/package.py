"""Standard Schema 2.0 package inventory commands (bADR-0021/0023)."""

import re
from collections.abc import Callable
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

from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.schema2.authority import (
    AuthorityLoadError,
    load_authorities,
    load_descriptor_authorities,
)
from gda_balancing.schema2.bootstrap import BOOTSTRAP_REFUSAL_CATALOG, admit_authorities
from gda_balancing.schema2.diagnostics import (
    Schema2RefusalReport,
    bootstrap_refusal,
    ingress_refusal,
)


def _package_coordinate_contracts() -> dict[str, dict[str, Any]]:
    kernel, _language_bundle = load_descriptor_authorities()
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


class PackageListInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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


AuthorityProvider = Callable[[], tuple[dict[str, Any], dict[str, Any]]]


def _admitted_package_graph(
    provider: AuthorityProvider,
) -> (
    tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]
    | Schema2RefusalReport
):
    try:
        kernel, ldb = provider()
    except AuthorityLoadError as err:
        return ingress_refusal(err.code, err.subject, err.message)
    admission = admit_authorities(kernel, ldb)
    if not admission.admitted:
        return bootstrap_refusal(admission)
    root = getattr(ldb, "root", None)
    releases = getattr(ldb, "package_releases", None)
    vector_sets = getattr(ldb, "package_conformance_vector_sets", None)
    if (
        not isinstance(root, dict)
        or not isinstance(releases, list)
        or not isinstance(vector_sets, list)
    ):
        return ingress_refusal(
            "kernel.member_set_mismatch",
            "language-bundle",
            "the admitted LDB has no sealed package graph",
        )
    return root, releases, vector_sets


def package_list_handler(
    provider: AuthorityProvider,
) -> Callable[[PackageListInput], PackageArtifact | Schema2RefusalReport]:
    def _run(_inp: PackageListInput) -> PackageArtifact | Schema2RefusalReport:
        graph = _admitted_package_graph(provider)
        if isinstance(graph, Schema2RefusalReport):
            return graph
        root, _releases, _vector_sets = graph
        return PackageArtifact(
            root={
                "language_bundle_identity": root["content_identity"],
                "packages": root["package_descriptors"],
            }
        )

    return _run


def package_get_handler(
    provider: AuthorityProvider,
) -> Callable[[PackageGetInput], PackageArtifact | Schema2RefusalReport]:
    def _run(inp: PackageGetInput) -> PackageArtifact | Schema2RefusalReport:
        graph = _admitted_package_graph(provider)
        if isinstance(graph, Schema2RefusalReport):
            return graph
        _root, releases, vector_sets = graph
        for release, vector_set in zip(releases, vector_sets, strict=True):
            if release.get("id") == inp.id and release.get("version") == inp.version:
                selected = release if inp.member == "release" else vector_set
                return PackageArtifact(root=cast(dict[str, Any], selected))
        return ingress_refusal(
            "kernel.binding_mismatch",
            f"{inp.id}@{inp.version}",
            "the exact package coordinate is absent from the admitted LDB",
        )

    return _run


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
    kernel, language_bundle = load_descriptor_authorities()
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


def _package_vector_schemas(contract: dict[str, Any]) -> list[dict[str, object]]:
    categories = contract.get("categories")
    kinds = contract.get("kinds")
    if (
        contract.get("closed") is not True
        or not isinstance(categories, list)
        or not categories
        or not all(isinstance(category, str) for category in categories)
        or not isinstance(kinds, list)
        or not kinds
    ):
        raise ValueError("Kernel package-vector contract is incomplete")

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
            if not isinstance(input_members, list) or set(input_members) != {
                "seed",
                "state_names",
                "values",
            }:
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
                                    "pattern": "^[0-9a-f]+$",
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
                    "pointer": {"type": "string", "pattern": "^(?:$|/)"},
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
            *_package_vector_schemas(package_vector),
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


PACKAGE_LIST = CommandDescriptor(
    group="package",
    command="list",
    description="List Package Releases in the admitted Language Definition Bundle.",
    input_model=PackageListInput,
    output_model=PackageArtifact,
    handler=package_list_handler(load_authorities),
    fixtures=ConformanceFixtures(),
    schema_major=2,
    structured_params=True,
    refusal_catalog=BOOTSTRAP_REFUSAL_CATALOG,
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
    success_schema=package_list_success_schema,
)


PACKAGE_GET = CommandDescriptor(
    group="package",
    command="get",
    description="Get one exact member of a Package Release.",
    input_model=PackageGetInput,
    output_model=PackageArtifact,
    handler=package_get_handler(load_authorities),
    fixtures=ConformanceFixtures(
        valid_args=("--id", "core.quantity", "--version", "2.0.0"),
        refusing_args=("--id", "missing.package", "--version", "1.0.0"),
    ),
    schema_major=2,
    structured_params=True,
    refusal_catalog=BOOTSTRAP_REFUSAL_CATALOG,
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
    success_schema=package_get_success_schema,
)
