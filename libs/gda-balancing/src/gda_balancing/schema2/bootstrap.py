"""One production bootstrap consumer for the Schema 2.0 Kernel/LDB pair.

The consumer implements the Kernel's small, closed meta-operation set.  It
does not contain Quantity rule dispatch: LDB rules are checked through their
declared generic inputs/result and normative vectors.
"""

import json
from dataclasses import dataclass
from typing import Any, cast

import jsonschema

from gda_balancing.schema2.canonical import JsonValue, canonical_bytes, content_identity

_KERNEL_DOMAIN = "schema-major-kernel-v2"
_LDB_DOMAIN = "language-definition-bundle-v2"
SCHEMA2_REFUSAL_STAGES = (
    "ingress",
    "parse",
    "static",
    "resolution",
    "runtime",
    "evaluation",
    "migration",
    "approval",
)
BOOTSTRAP_REFUSAL_CATALOG = (
    ("kernel.binding_mismatch", "ingress"),
    ("kernel.diagnostic_closure", "static"),
    ("kernel.duplicate_identifier", "static"),
    ("kernel.identity_mismatch", "ingress"),
    ("kernel.member_set_mismatch", "ingress"),
    ("kernel.resource_exhausted", "ingress"),
    ("kernel.unknown_operation", "static"),
    ("kernel.vector_mismatch", "static"),
)
_SUPPORTED_KERNEL_IDENTITY = (
    "sha256:cdac2365950e7d7f42c5c763055861e61eb6e9628852f7428ca879e569fc270e"
)
_SUPPORTED_CANONICAL_PROFILE: dict[str, Any] = {
    "array_order": "preserve",
    "character_encoding": "UTF-8",
    "control_character_escaping": {
        "backspace": "\\b",
        "carriage-return": "\\r",
        "form-feed": "\\f",
        "line-feed": "\\n",
        "other-u0000-u001f": "lowercase-u00xx",
        "tab": "\\t",
    },
    "delete_character_escaping": "literal-byte-7f",
    "digest_hex_case": "lowercase",
    "document_terminator": "LF",
    "duplicate_object_keys": "refuse-at-decoding",
    "escape_solidus": False,
    "identity_algorithm": "sha256",
    "identity_domain_prefix": "gda-balancing:",
    "identity_domain_suffix": ":",
    "identity_excluded_members": ["content_identity"],
    "identity_output_prefix": "sha256:",
    "integer_domain": "signed-int64",
    "item_separator": ",",
    "key_separator": ":",
    "lone_surrogate": "refuse",
    "non_ascii_strings": "literal-utf8",
    "number_kinds": ["signed-int64"],
    "object_order": "UTF-8-key-byte-order",
    "optional_members": "omit",
    "printable_ascii_escaping": "only-quotation-mark-and-reverse-solidus",
    "profile": "gda-canonical-json-v1",
    "unicode_normalization": "preserve",
    "whitespace": "none",
}
_KERNEL_MEMBERS = frozenset(
    {
        "admission",
        "artifact_kind",
        "artifact_version",
        "canonical_encoding",
        "content_identity",
        "diagnostics",
        "meta_format",
        "resources",
        "schema_major",
        "vectors",
    }
)
_KNOWN_OPERATIONS = frozenset(
    {
        "verify-content-identity",
        "require-equal",
        "require-exact-members",
        "require-unique-identifiers",
        "require-known-operations",
        "require-vector-closure",
        "require-diagnostic-closure",
        "enforce-resource-limits",
    }
)


@dataclass(frozen=True)
class AdmissionDiagnostic:
    code: str
    stage: str
    subject: str


@dataclass(frozen=True)
class BootstrapAdmission:
    admitted: bool
    kernel_identity: str | None
    language_bundle_identity: str | None
    law_ids: tuple[str, ...]
    law_projections: tuple[tuple[str, str], ...]
    rule_ids: tuple[str, ...]
    rule_projections: tuple[tuple[str, str], ...]
    diagnostic_projections: tuple[tuple[str, str, str], ...]
    diagnostics: tuple[AdmissionDiagnostic, ...]
    truncated: bool


def _artifact_identity(domain: str, artifact: dict[str, Any]) -> str:
    body = {key: value for key, value in artifact.items() if key != "content_identity"}
    return content_identity(domain, cast(JsonValue, body))


def _strict_json_value(text: str) -> JsonValue:
    def reject_number(_value: str) -> Any:
        raise ValueError("non-integer number is outside canonical JSON")

    def closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate object key is outside canonical JSON")
            result[key] = value
        return result

    return cast(
        JsonValue,
        json.loads(
            text,
            object_pairs_hook=closed_object,
            parse_float=reject_number,
            parse_constant=reject_number,
        ),
    )


def _canonical_contract_is_supported(canonical_encoding: Any) -> bool:
    if not isinstance(canonical_encoding, dict):
        return False
    vectors = canonical_encoding.get("vectors")
    profile = {
        key: value for key, value in canonical_encoding.items() if key != "vectors"
    }
    if profile != _SUPPORTED_CANONICAL_PROFILE or not isinstance(vectors, list):
        return False
    expected_ids = {
        "canonical.boundary-integers",
        "canonical.control-character-escaping",
        "canonical.order-array-unicode-escaping",
        "canonical.reject-duplicate-key",
        "canonical.reject-float",
        "canonical.reject-lone-surrogate",
    }
    if {item.get("id") for item in vectors if isinstance(item, dict)} != expected_ids:
        return False
    for vector in vectors:
        if not isinstance(vector, dict):
            return False
        if "value" in vector:
            if set(vector) != {
                "canonical_utf8_hex",
                "domain",
                "id",
                "identity",
                "value",
            }:
                return False
            value = cast(JsonValue, vector["value"])
            domain = vector.get("domain")
            if (
                not isinstance(domain, str)
                or canonical_bytes(value).hex() != vector.get("canonical_utf8_hex")
                or content_identity(domain, value) != vector.get("identity")
            ):
                return False
        else:
            if set(vector) != {"id", "input_lexeme", "refusal"} or not isinstance(
                vector.get("input_lexeme"), str
            ):
                return False
            try:
                canonical_bytes(_strict_json_value(vector["input_lexeme"]))
            except (TypeError, ValueError, UnicodeEncodeError):
                continue
            return False
    return True


def _safe_artifact_identity(
    domain: str,
    artifact: dict[str, Any],
    canonical_encoding: Any,
) -> str | None:
    try:
        supported = _canonical_contract_is_supported(canonical_encoding)
    except (TypeError, ValueError, UnicodeEncodeError):
        supported = False
    if not supported:
        return None
    try:
        return _artifact_identity(domain, artifact)
    except (TypeError, ValueError):
        return None


def _resource_shape(value: Any) -> tuple[int, int]:
    """Return maximum nesting depth and largest single collection iteratively."""
    maximum_depth = 0
    maximum_members = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        maximum_depth = max(maximum_depth, depth)
        if isinstance(current, dict):
            maximum_members = max(maximum_members, len(current))
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            maximum_members = max(maximum_members, len(current))
            stack.extend((item, depth + 1) for item in current)
    return maximum_depth, maximum_members


def _package_is_closed(
    package: dict[str, Any], contract: Any, language_bundle: dict[str, Any]
) -> bool:
    if not isinstance(contract, dict) or contract.get("closed") is not True:
        return False
    required = contract.get("required_members")
    field_types = contract.get("field_types")
    nested_members = contract.get("nested_members")
    nested_types = contract.get("nested_field_types")
    type_export = contract.get("type_export")
    if (
        not isinstance(required, list)
        or set(package) != set(required)
        or not isinstance(field_types, dict)
        or not isinstance(nested_members, dict)
        or not isinstance(nested_types, dict)
        or set(nested_members) != set(nested_types)
        or set(field_types) | set(nested_members) != set(required)
        or set(field_types) & set(nested_members)
        or not all(
            _value_matches_contract(package[name], field_types[name], language_bundle)
            for name in field_types
        )
    ):
        return False
    for name, members in nested_members.items():
        value = package.get(name)
        member_types = nested_types.get(name)
        if (
            not isinstance(value, dict)
            or not isinstance(members, list)
            or set(value) != set(members)
            or not isinstance(member_types, dict)
            or set(member_types) != set(members)
            or not all(
                _value_matches_contract(
                    value[member], member_types[member], language_bundle
                )
                for member in members
            )
        ):
            return False
    exports = package.get("exports")
    exported_types = exports.get("types") if isinstance(exports, dict) else None
    if not isinstance(exported_types, list) or not isinstance(type_export, dict):
        return False
    export_members = type_export.get("required_members")
    export_field_types = type_export.get("field_types")
    return (
        isinstance(export_members, list)
        and isinstance(export_field_types, dict)
        and set(export_field_types) == set(export_members)
        and all(
            isinstance(item, dict)
            and set(item) == set(export_members)
            and all(
                _value_matches_contract(
                    item[member], export_field_types[member], language_bundle
                )
                for member in export_members
            )
            for item in exported_types
        )
    )


def _language_bundle_is_closed(
    language_bundle: dict[str, Any], contract: Any, refusal_stages: Any
) -> bool:
    if not isinstance(contract, dict) or contract.get("closed") is not True:
        return False
    required = contract.get("required_members")
    member_types = contract.get("member_types")
    diagnostics_contract = contract.get("diagnostic")
    resources_contract = contract.get("resources")
    if (
        not isinstance(required, list)
        or set(language_bundle) != set(required)
        or not isinstance(member_types, dict)
        or set(member_types) != set(required)
        or not isinstance(refusal_stages, list)
        or tuple(refusal_stages) != SCHEMA2_REFUSAL_STAGES
    ):
        return False
    for name, value_contract in member_types.items():
        if name == "diagnostics":
            if not isinstance(language_bundle[name], list):
                return False
        elif not _value_matches_contract(
            language_bundle[name], value_contract, language_bundle
        ):
            return False
    if not isinstance(diagnostics_contract, dict):
        return False
    diagnostic_members = diagnostics_contract.get("required_members")
    diagnostic_types = diagnostics_contract.get("field_types")
    diagnostics = language_bundle["diagnostics"]
    if (
        not isinstance(diagnostic_members, list)
        or not isinstance(diagnostic_types, dict)
        or set(diagnostic_types) != set(diagnostic_members)
        or not all(
            isinstance(item, dict)
            and set(item) == set(diagnostic_members)
            and isinstance(item.get("code"), str)
            and bool(item["code"])
            and item.get("stage") in refusal_stages
            for item in diagnostics
        )
    ):
        return False
    if not isinstance(resources_contract, dict):
        return False
    resource_members = resources_contract.get("required_members")
    resource_types = resources_contract.get("field_types")
    resources = language_bundle["resources"]
    return (
        isinstance(resources, dict)
        and isinstance(resource_members, list)
        and set(resources) == set(resource_members)
        and isinstance(resource_types, dict)
        and set(resource_types) == set(resource_members)
        and all(
            _value_matches_contract(
                resources[name], resource_types[name], language_bundle
            )
            for name in resource_members
        )
    )


def _path_values(root: Any, dotted: Any) -> list[Any]:
    """Project a closed dotted path, flattening collection members."""
    if not isinstance(dotted, str) or not dotted:
        return []
    values = [root]
    for part in dotted.split("."):
        projected: list[Any] = []
        for value in values:
            if not isinstance(value, dict) or part not in value:
                return []
            child = value[part]
            if isinstance(child, list):
                projected.extend(child)
            else:
                projected.append(child)
        values = projected
    return values


def _path_is_declared(root: Any, dotted: Any) -> bool:
    if not isinstance(dotted, str) or not dotted:
        return False

    def walk(value: Any, parts: list[str]) -> bool:
        if not parts:
            return True
        if not isinstance(value, dict) or parts[0] not in value:
            return False
        child = value[parts[0]]
        if isinstance(child, list):
            return all(walk(item, parts[1:]) for item in child)
        return walk(child, parts[1:])

    return walk(root, dotted.split("."))


def _exact_path_value(root: Any, dotted: Any) -> tuple[bool, Any]:
    """Resolve a path whose intermediate values are mappings, without flattening."""
    if not isinstance(dotted, str) or not dotted:
        return False, None
    value = root
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


def _closed_json_schema(value: Any, contract: dict[str, Any]) -> bool:
    allowed = contract.get("allowed_keywords")
    dialect = contract.get("dialect")
    closure_keyword = contract.get("object_closure_keyword")
    closure_value = contract.get("object_closure_value")
    keyword_type_requirements = contract.get("keyword_type_requirements")
    if (
        not isinstance(value, dict)
        or not isinstance(allowed, list)
        or not all(isinstance(item, str) for item in allowed)
        or not isinstance(dialect, str)
        or not isinstance(keyword_type_requirements, dict)
        or not all(
            isinstance(keyword, str)
            and isinstance(types, list)
            and types
            and all(isinstance(item, str) for item in types)
            for keyword, types in keyword_type_requirements.items()
        )
        or closure_keyword != "unevaluatedProperties"
        or closure_value is not False
        or contract.get("references") != "forbidden"
        or contract.get("type_form") != "single-string"
        or value.get("$schema") != dialect
    ):
        return False
    try:
        jsonschema.Draft202012Validator.check_schema(value)
    except jsonschema.SchemaError:
        return False
    allowed_set = set(allowed)

    def walk(schema: Any) -> bool:
        if not isinstance(schema, dict) or not set(schema) <= allowed_set:
            return False
        schema_type = schema.get("type")
        if schema_type is not None and (
            not isinstance(schema_type, str)
            or schema_type
            not in {
                "array",
                "boolean",
                "integer",
                "null",
                "number",
                "object",
                "string",
            }
        ):
            return False
        if schema_type == "object" and schema.get(closure_keyword) is not False:
            return False
        if any(
            keyword in schema and schema_type not in required_types
            for keyword, required_types in keyword_type_requirements.items()
        ):
            return False
        if "$ref" in schema:
            return False
        required = schema.get("required")
        if required is not None and (
            not isinstance(required, list)
            or not all(isinstance(item, str) and item for item in required)
            or len(required) != len(set(required))
        ):
            return False
        for keyword in ("$defs", "properties"):
            children = schema.get(keyword)
            if children is not None and (
                not isinstance(children, dict)
                or not all(
                    isinstance(name, str) and name and walk(child)
                    for name, child in children.items()
                )
            ):
                return False
        items = schema.get("items")
        if items is not None and not walk(items):
            return False
        for keyword in ("anyOf", "oneOf"):
            children = schema.get(keyword)
            if children is not None and (
                not isinstance(children, list)
                or not children
                or not all(walk(child) for child in children)
            ):
                return False
        for keyword in ("const", "default", "enum"):
            if keyword in schema:
                try:
                    canonical_bytes(cast(JsonValue, schema[keyword]))
                except (TypeError, ValueError):
                    return False
        return True

    return walk(value)


def _reference_contracts_close(
    kernel: dict[str, Any], language_bundle: dict[str, Any]
) -> bool:
    laws = kernel.get("admission", {}).get("laws", [])
    vector_law = next(
        (
            law
            for law in laws
            if isinstance(law, dict) and law.get("id") == "kernel.vectors.closed"
        ),
        None,
    )
    if not isinstance(vector_law, dict):
        return False
    references = vector_law.get("arguments", {}).get("references")
    equalities = vector_law.get("arguments", {}).get("equalities")
    if not isinstance(references, list) or not isinstance(equalities, list):
        return False
    authorities = {"kernel": kernel, "language_bundle": language_bundle}
    for contract in equalities:
        if (
            not isinstance(contract, dict)
            or set(contract) != {"left", "mode", "right"}
            or contract.get("mode") != "set"
            or not _path_is_declared(authorities, contract.get("left"))
            or not _path_is_declared(authorities, contract.get("right"))
        ):
            return False
        try:
            if set(_path_values(authorities, contract["left"])) != set(
                _path_values(authorities, contract["right"])
            ):
                return False
        except TypeError:
            return False
    for contract in references:
        if not isinstance(contract, dict):
            return False
        owners = _path_values(authorities, contract.get("owners"))
        targets = contract.get("targets")
        if (
            not _path_is_declared(authorities, contract.get("owners"))
            or not owners
            or not isinstance(targets, dict)
        ):
            return False
        for owner in owners:
            if not isinstance(owner, dict):
                return False
            for source_path, target_path in targets.items():
                if not _path_is_declared(owner, source_path) or not _path_is_declared(
                    authorities, target_path
                ):
                    return False
                source_values = _path_values(owner, source_path)
                target_values = _path_values(authorities, target_path)
                if any(value not in target_values for value in source_values):
                    return False
    return True


def _duplicate_identifier_subjects(
    kernel: dict[str, Any], language_bundle: dict[str, Any]
) -> set[str]:
    laws = kernel.get("admission", {}).get("laws", [])
    uniqueness_law = next(
        (
            law
            for law in laws
            if isinstance(law, dict) and law.get("id") == "kernel.identifiers.unique"
        ),
        None,
    )
    if not isinstance(uniqueness_law, dict):
        return {"kernel.admission.laws"}
    collections = uniqueness_law.get("arguments", {}).get("collections")
    if not isinstance(collections, list):
        return {"kernel.admission.laws"}
    authorities = {"kernel": kernel, "language_bundle": language_bundle}
    duplicates: set[str] = set()
    for contract in collections:
        if not isinstance(contract, dict):
            duplicates.add("kernel.admission.laws")
            continue
        keys = contract.get("keys")
        path = contract.get("path")
        subject = contract.get("subject")
        items = _path_values(authorities, path)
        if (
            not isinstance(keys, list)
            or not keys
            or not all(isinstance(key, str) and key for key in keys)
            or not isinstance(subject, str)
            or not subject
        ):
            duplicates.add(str(subject or path or "kernel.admission.laws"))
            continue
        identities: list[tuple[Any, ...]] = []
        for item in items:
            if not isinstance(item, dict) or any(key not in item for key in keys):
                duplicates.add(subject)
                break
            identities.append(tuple(item[key] for key in keys))
        try:
            if len(identities) != len(set(identities)):
                duplicates.add(subject)
        except TypeError:
            duplicates.add(subject)
    return duplicates


def _value_matches_contract(
    value: Any,
    contract: Any,
    language_bundle: dict[str, Any],
) -> bool:
    if not isinstance(contract, dict):
        return False
    if "const" in contract:
        return value == contract["const"] and type(value) is type(contract["const"])
    if "enum" in contract:
        return isinstance(contract["enum"], list) and value in contract["enum"]
    value_type = contract.get("type")
    if value_type == "non-empty-string":
        return isinstance(value, str) and bool(value)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "list":
        return isinstance(value, list)
    if value_type == "object":
        return isinstance(value, dict)
    if value_type == "positive-signed-int64":
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 1 <= value <= 2**63 - 1
        )
    if value_type == "signed-int64":
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and -(2**63) <= value <= 2**63 - 1
        )
    if value_type == "canonical-scalar":
        return (
            value is None
            or isinstance(value, (bool, str))
            or (
                isinstance(value, int)
                and not isinstance(value, bool)
                and -(2**63) <= value <= 2**63 - 1
            )
        )
    if value_type == "scalar-list":
        return isinstance(value, list) and all(
            _value_matches_contract(item, {"type": "canonical-scalar"}, language_bundle)
            for item in value
        )
    if value_type == "string-list":
        return (
            isinstance(value, list)
            and all(isinstance(item, str) and item for item in value)
            and len(value) == len(set(value))
        )
    if value_type == "canonical-value":
        try:
            canonical_bytes(cast(JsonValue, value))
        except (TypeError, ValueError):
            return False
        return True
    if value_type == "inventory-member":
        path = contract.get("path")
        return _path_is_declared(language_bundle, path) and value in _path_values(
            language_bundle, path
        )
    if value_type == "inventory-list-path":
        declared, target = _exact_path_value(language_bundle, value)
        return declared and isinstance(target, list) and bool(target)
    if value_type == "signed-int64-path":
        declared, target = _exact_path_value(language_bundle, value)
        return declared and _value_matches_contract(
            target, {"type": "signed-int64"}, language_bundle
        )
    if value_type == "closed-json-schema":
        return _closed_json_schema(value, contract)
    if value_type == "closed-int64-interval":
        if not isinstance(value, dict) or set(value) != {"minimum", "maximum"}:
            return False
        minimum = value["minimum"]
        maximum = value["maximum"]
        return (
            isinstance(minimum, int)
            and not isinstance(minimum, bool)
            and isinstance(maximum, int)
            and not isinstance(maximum, bool)
            and -(2**63) <= minimum <= maximum <= 2**63 - 1
        )
    return False


def _definition_is_closed(
    value: Any,
    contract: Any,
    language_bundle: dict[str, Any],
) -> bool:
    if not isinstance(value, dict) or not isinstance(contract, dict):
        return False
    required = contract.get("required_members")
    field_types = contract.get("field_types")
    return (
        isinstance(required, list)
        and isinstance(field_types, dict)
        and set(value) == set(required)
        and set(field_types) == set(required)
        and all(
            _value_matches_contract(value[name], field_types[name], language_bundle)
            for name in required
        )
    )


def _language_definitions_are_closed(
    language_bundle: dict[str, Any], meta_format: dict[str, Any]
) -> bool:
    language = language_bundle.get("language")
    authority = meta_format.get("language_definitions")
    if not isinstance(language, dict) or not isinstance(authority, dict):
        return False
    collections = authority.get("collections")
    if not isinstance(collections, dict):
        return False
    for name, contract in collections.items():
        values = language.get(name)
        if not isinstance(values, list) or not isinstance(contract, dict):
            return False
        max_items = contract.get("max_items")
        if max_items is not None:
            if not isinstance(max_items, int) or len(values) > max_items:
                return False
            continue
        item_type = contract.get("item_type")
        if item_type is not None:
            item_contract = {"type": item_type}
            if not all(
                _value_matches_contract(value, item_contract, language_bundle)
                for value in values
            ):
                return False
            continue
        if not all(
            _definition_is_closed(value, contract, language_bundle) for value in values
        ):
            return False
    quantity = language.get("quantity")
    quantity_contract = authority.get("quantity")
    if not isinstance(quantity, dict) or not isinstance(quantity_contract, dict):
        return False
    required = quantity_contract.get("required_members")
    quantity_collections = quantity_contract.get("collections")
    if (
        not isinstance(required, list)
        or set(quantity) != set(required)
        or not isinstance(quantity_collections, dict)
        or set(quantity_collections) != set(required)
    ):
        return False
    for name, contract in quantity_collections.items():
        values = quantity.get(name)
        if not isinstance(values, list) or not isinstance(contract, dict):
            return False
        item_type = contract.get("item_type")
        if item_type is not None:
            item_contract = {"type": item_type}
            if not all(
                _value_matches_contract(value, item_contract, language_bundle)
                for value in values
            ):
                return False
        elif not all(
            _definition_is_closed(value, contract, language_bundle) for value in values
        ):
            return False
    return True


def _fact_schemas(
    meta_format: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    fact_contract = meta_format.get("fact")
    if not isinstance(fact_contract, dict):
        return {}
    schemas = fact_contract.get("schemas")
    field_contracts = fact_contract.get("field_contracts")
    if not isinstance(schemas, list) or not isinstance(field_contracts, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for schema in schemas:
        if not isinstance(schema, dict):
            return {}
        kind = schema.get("kind")
        contract_name = schema.get("field_contract")
        fields = field_contracts.get(contract_name)
        if (
            not isinstance(kind, str)
            or not kind
            or not isinstance(contract_name, str)
            or not isinstance(fields, dict)
            or not all(isinstance(field, str) and field for field in fields)
            or kind in result
        ):
            return {}
        result[kind] = fields
    return result


def _fact_is_closed(
    fact: Any,
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> bool:
    fact_contract = meta_format.get("fact")
    schemas = _fact_schemas(meta_format)
    if not isinstance(fact_contract, dict) or not schemas or not isinstance(fact, dict):
        return False
    required = fact_contract.get("required_members")
    kind = fact.get("kind")
    fields = fact.get("fields")
    return (
        fact_contract.get("closed") is True
        and isinstance(required, list)
        and set(fact) == set(required)
        and isinstance(kind, str)
        and kind in schemas
        and isinstance(fields, dict)
        and set(fields) == set(schemas[kind])
        and all(isinstance(name, str) and name for name in fields)
        and all(
            _value_matches_contract(fields[name], schemas[kind][name], language_bundle)
            for name in fields
        )
    )


def _reason_is_closed(
    reason: Any,
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> bool:
    contract = meta_format.get("diagnostic_reason")
    if not isinstance(contract, dict) or not isinstance(reason, dict):
        return False
    required = contract.get("required_members")
    member_types = contract.get("member_types")
    schemas = contract.get("predicate_schemas")
    predicate = reason.get("predicate")
    if (
        contract.get("closed") is not True
        or contract.get("scalar_equality") != "type-and-canonical-value"
        or not isinstance(required, list)
        or set(reason) != set(required)
        or not isinstance(member_types, dict)
        or set(member_types) != set(required) - {"predicate"}
        or not all(
            _value_matches_contract(reason[name], member_types[name], language_bundle)
            for name in member_types
        )
        or not isinstance(predicate, dict)
        or not isinstance(schemas, list)
    ):
        return False
    operation = predicate.get("operation")
    schema = next(
        (
            item
            for item in schemas
            if isinstance(item, dict) and item.get("operation") == operation
        ),
        None,
    )
    if not isinstance(schema, dict):
        return False
    predicate_required = schema.get("required_members")
    optional = schema.get("optional_members")
    predicate_types = schema.get("member_types")
    input_members = schema.get("input_members")
    input_types = schema.get("input_member_types")
    return (
        isinstance(predicate_required, list)
        and isinstance(optional, list)
        and isinstance(predicate_types, dict)
        and isinstance(input_members, list)
        and isinstance(input_types, dict)
        and set(input_types) == set(input_members)
        and set(predicate_required) <= set(predicate)
        and set(predicate) <= set(predicate_required) | set(optional)
        and set(predicate_types) == set(predicate_required) | set(optional)
        and all(
            _value_matches_contract(
                predicate[name], predicate_types[name], language_bundle
            )
            for name in predicate
        )
        and _reason_operands_are_closed(predicate, language_bundle)
    )


def _reason_operands_are_closed(
    predicate: dict[str, Any], language_bundle: dict[str, Any]
) -> bool:
    operation = predicate.get("operation")
    if operation == "not-member":
        declared, inventory = _exact_path_value(
            language_bundle, predicate.get("inventory_path")
        )
        if not declared or not isinstance(inventory, list) or not inventory:
            return False
        member_field = predicate.get("member_field")
        if member_field is None:
            values = inventory
        elif isinstance(member_field, str) and member_field:
            if not all(
                isinstance(item, dict) and member_field in item for item in inventory
            ):
                return False
            values = [item[member_field] for item in inventory]
        else:
            return False
        return all(
            _value_matches_contract(
                value, {"type": "canonical-scalar"}, language_bundle
            )
            for value in values
        )
    if operation == "greater-than":
        declared, limit = _exact_path_value(
            language_bundle, predicate.get("limit_path")
        )
        return declared and _value_matches_contract(
            limit, {"type": "signed-int64"}, language_bundle
        )
    return operation == "has-duplicate"


def _vector_header_is_closed(
    vector: Any,
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> bool:
    if not isinstance(vector, dict):
        return False
    if "rule" in vector:
        invocation = vector.get("input")
        rule_contract = meta_format.get("rule")
        phases = (
            rule_contract.get("phases") if isinstance(rule_contract, dict) else None
        )
        return (
            set(vector) == {"expect", "id", "input", "rule"}
            and isinstance(vector.get("id"), str)
            and bool(vector["id"])
            and isinstance(vector.get("rule"), str)
            and bool(vector["rule"])
            and isinstance(invocation, dict)
            and set(invocation) == {"facts", "judgment", "phase"}
            and isinstance(invocation.get("judgment"), str)
            and bool(invocation["judgment"])
            and isinstance(phases, list)
            and invocation.get("phase") in phases
            and isinstance(invocation.get("facts"), list)
            and all(
                _fact_is_closed(fact, meta_format, language_bundle)
                for fact in invocation["facts"]
            )
            and _fact_is_closed(vector.get("expect"), meta_format, language_bundle)
        )
    if "diagnostic" in vector:
        contract = meta_format.get("diagnostic_reason")
        if not isinstance(contract, dict):
            return False
        required = contract.get("vector_required_members")
        member_types = contract.get("vector_member_types")
        return (
            isinstance(required, list)
            and set(vector) == set(required)
            and isinstance(member_types, dict)
            and set(member_types) == set(required) - {"input"}
            and all(
                _value_matches_contract(
                    vector[name], member_types[name], language_bundle
                )
                for name in member_types
            )
            and isinstance(vector.get("input"), dict)
        )
    return False


def admit_authorities(
    kernel: dict[str, Any], language_bundle: dict[str, Any]
) -> BootstrapAdmission:
    """Admit an authority pair or return all deterministic bootstrap diagnostics."""
    found: set[AdmissionDiagnostic] = set()

    def refuse(code: str, stage: str, subject: str) -> None:
        found.add(AdmissionDiagnostic(code=code, stage=stage, subject=subject))

    kernel_identity = kernel.get("content_identity")
    ldb_identity = language_bundle.get("content_identity")
    canonical_encoding = kernel.get("canonical_encoding")
    computed_kernel_identity = _safe_artifact_identity(
        _KERNEL_DOMAIN, kernel, canonical_encoding
    )
    computed_ldb_identity = _safe_artifact_identity(
        _LDB_DOMAIN, language_bundle, canonical_encoding
    )
    if (
        not isinstance(kernel_identity, str)
        or kernel_identity != computed_kernel_identity
        or kernel_identity != _SUPPORTED_KERNEL_IDENTITY
    ):
        refuse("kernel.identity_mismatch", "ingress", "kernel")
    if not isinstance(ldb_identity, str) or ldb_identity != computed_ldb_identity:
        refuse("kernel.identity_mismatch", "ingress", "language-bundle")
    if language_bundle.get("kernel_identity") != kernel_identity:
        refuse(
            "kernel.binding_mismatch",
            "ingress",
            "language-bundle.kernel_identity",
        )
    if set(kernel) != _KERNEL_MEMBERS:
        refuse("kernel.member_set_mismatch", "ingress", "kernel")
    if any(item.subject == "kernel" for item in found):
        return _result(
            found,
            128,
            kernel_identity if isinstance(kernel_identity, str) else None,
            ldb_identity if isinstance(ldb_identity, str) else None,
            (),
            (),
            (),
            (),
            (),
        )

    admission = cast(dict[str, Any], kernel.get("admission", {}))
    expected_members = set(cast(list[str], admission.get("required_ldb_members", [])))
    if set(language_bundle) != expected_members:
        refuse("kernel.member_set_mismatch", "ingress", "language-bundle")
    raw_language = language_bundle.get("language")
    expected_language_members = set(
        cast(list[str], admission.get("required_language_members", []))
    )
    if (
        not isinstance(raw_language, dict)
        or set(raw_language) != expected_language_members
    ):
        refuse(
            "kernel.member_set_mismatch",
            "ingress",
            "language-bundle.language",
        )
    raw_meta_format = kernel.get("meta_format")
    refusal_stages = admission.get("refusal_stages")
    language_bundle_contract = (
        raw_meta_format.get("language_bundle")
        if isinstance(raw_meta_format, dict)
        else None
    )
    if not _language_bundle_is_closed(
        language_bundle, language_bundle_contract, refusal_stages
    ):
        refuse("kernel.member_set_mismatch", "ingress", "language-bundle")

    resources = cast(dict[str, Any], kernel.get("resources", {}))
    max_bytes = resources.get("max_authority_bytes", 262144)
    if not isinstance(max_bytes, int) or max_bytes < 1:
        max_bytes = 262144
        refuse("kernel.resource_exhausted", "ingress", "kernel.resources")
    max_depth = resources.get("max_nesting_depth", 32)
    max_members = resources.get("max_members", 256)
    if not isinstance(max_depth, int) or max_depth < 1:
        max_depth = 32
        refuse("kernel.resource_exhausted", "ingress", "kernel.resources")
    if not isinstance(max_members, int) or max_members < 1:
        max_members = 256
        refuse("kernel.resource_exhausted", "ingress", "kernel.resources")
    for subject, artifact in (("kernel", kernel), ("language-bundle", language_bundle)):
        depth, largest_collection = _resource_shape(artifact)
        if depth > max_depth or largest_collection > max_members:
            refuse("kernel.resource_exhausted", "ingress", subject)
        try:
            size = len(canonical_bytes(cast(JsonValue, artifact)))
        except (TypeError, ValueError):
            size = max_bytes + 1
        if size > max_bytes:
            refuse("kernel.resource_exhausted", "ingress", subject)

    packages = raw_language.get("packages") if isinstance(raw_language, dict) else None
    package_contract = (
        raw_meta_format.get("package_release")
        if isinstance(raw_meta_format, dict)
        else None
    )
    if not isinstance(packages, list):
        refuse(
            "kernel.member_set_mismatch", "ingress", "language-bundle.language.packages"
        )
    else:
        for index, package in enumerate(packages):
            subject = f"language-bundle.language.packages.{index}"
            if not isinstance(package, dict) or not _package_is_closed(
                package, package_contract, language_bundle
            ):
                refuse("kernel.member_set_mismatch", "ingress", subject)
                continue
            if package.get("content_identity") != _safe_artifact_identity(
                "domain-package-release-v2", package, canonical_encoding
            ):
                refuse("kernel.identity_mismatch", "ingress", subject)

    cap = resources.get("max_diagnostics", 128)
    if not isinstance(cap, int) or cap < 1:
        cap = 128
    if found:
        return _result(
            found,
            cap,
            kernel_identity if isinstance(kernel_identity, str) else None,
            ldb_identity if isinstance(ldb_identity, str) else None,
            (),
            (),
            (),
            (),
            (),
        )

    laws = cast(list[dict[str, Any]], admission.get("laws", []))
    for subject in _duplicate_identifier_subjects(kernel, language_bundle):
        refuse("kernel.duplicate_identifier", "static", subject)
    law_ids = [str(law.get("id", "")) for law in laws]
    if len(law_ids) != len(set(law_ids)):
        refuse("kernel.duplicate_identifier", "static", "kernel.admission.laws")
    operation_law = next(
        (law for law in laws if law.get("id") == "kernel.operations.closed"), None
    )
    operation_arguments = (
        operation_law.get("arguments", {}) if isinstance(operation_law, dict) else {}
    )
    allowed_operations = operation_arguments.get("admission_operations")
    if not isinstance(allowed_operations, list) or set(allowed_operations) != set(
        _KNOWN_OPERATIONS
    ):
        refuse("kernel.unknown_operation", "static", "kernel.operations.closed")
    for law in laws:
        if law.get("operation") not in set(allowed_operations or []):
            refuse("kernel.unknown_operation", "static", str(law.get("id", "")))
    law_projections = tuple(
        sorted(
            (
                str(law.get("id", "")),
                content_identity("kernel-law-projection-v2", cast(JsonValue, law)),
            )
            for law in laws
        )
    )

    kernel_vectors = cast(list[dict[str, Any]], kernel.get("vectors", []))
    kernel_vector_ids = [str(vector.get("id", "")) for vector in kernel_vectors]
    if len(kernel_vector_ids) != len(set(kernel_vector_ids)):
        refuse("kernel.duplicate_identifier", "static", "kernel.vectors")
    referenced_laws = {str(vector.get("law", "")) for vector in kernel_vectors}
    if set(law_ids) != referenced_laws:
        refuse("kernel.vector_mismatch", "static", "kernel.vectors")
    kernel_diagnostics = cast(list[dict[str, Any]], kernel.get("diagnostics", []))
    kernel_codes = [str(item.get("code", "")) for item in kernel_diagnostics]
    if len(kernel_codes) != len(set(kernel_codes)):
        refuse("kernel.duplicate_identifier", "static", "kernel.diagnostics")
    kernel_catalog = {
        (str(item.get("code", "")), str(item.get("stage", "")))
        for item in kernel_diagnostics
    }
    if kernel_catalog != set(BOOTSTRAP_REFUSAL_CATALOG):
        refuse("kernel.diagnostic_closure", "static", "kernel.diagnostics")
    kernel_vector_catalog = {
        (str(item["diagnostic"]), str(item.get("stage", "")))
        for item in kernel_vectors
        if "diagnostic" in item
    }
    if kernel_catalog != kernel_vector_catalog:
        refuse("kernel.diagnostic_closure", "static", "kernel.diagnostics")

    language = cast(dict[str, Any], language_bundle.get("language", {}))
    meta_format = cast(dict[str, Any], kernel.get("meta_format", {}))
    if not _language_definitions_are_closed(language_bundle, meta_format):
        refuse("kernel.vector_mismatch", "static", "language.definitions")
    raw_ldb_vectors = language_bundle.get("vectors")
    ldb_vectors: list[dict[str, Any]] = []
    if not isinstance(raw_ldb_vectors, list):
        refuse("kernel.vector_mismatch", "static", "language-bundle.vectors")
    else:
        for vector in raw_ldb_vectors:
            if _vector_header_is_closed(vector, meta_format, language_bundle):
                ldb_vectors.append(vector)
            else:
                subject = str(vector.get("id", "")) if isinstance(vector, dict) else ""
                refuse("kernel.vector_mismatch", "static", subject)
    raw_rules = language.get("rules")
    rules: list[dict[str, Any]] = []
    if not isinstance(raw_rules, list) or not all(
        _rule_is_closed(rule, meta_format, language_bundle) for rule in raw_rules
    ):
        refuse("kernel.vector_mismatch", "static", "language.rules")
    else:
        rules = cast(list[dict[str, Any]], raw_rules)
    raw_reasons = language.get("reasons")
    reasons: list[dict[str, Any]] = []
    if not isinstance(raw_reasons, list) or not all(
        _reason_is_closed(reason, meta_format, language_bundle)
        for reason in raw_reasons
    ):
        refuse("kernel.vector_mismatch", "static", "language.reasons")
    else:
        reasons = cast(list[dict[str, Any]], raw_reasons)
    if found:
        return _result(
            found,
            cap,
            kernel_identity if isinstance(kernel_identity, str) else None,
            ldb_identity if isinstance(ldb_identity, str) else None,
            tuple(sorted(law_ids)),
            law_projections,
            (),
            (),
            (),
        )
    rule_ids = [str(rule.get("id", "")) for rule in rules]
    if len(rule_ids) != len(set(rule_ids)):
        refuse("kernel.duplicate_identifier", "static", "language.rules")
    ldb_vector_ids = [str(item.get("id", "")) for item in ldb_vectors]
    if len(ldb_vector_ids) != len(set(ldb_vector_ids)):
        refuse(
            "kernel.duplicate_identifier",
            "static",
            "language-bundle.vectors",
        )
    rule_vectors = [item for item in ldb_vectors if "rule" in item]
    if set(rule_ids) != {str(item["rule"]) for item in rule_vectors}:
        refuse("kernel.vector_mismatch", "static", "language-bundle.vectors")
    rule_projections: list[tuple[str, str]] = []
    for vector in rule_vectors:
        output = _execute_rule_vector(rules, vector, meta_format, language_bundle)
        if output is None or output != vector.get("expect"):
            refuse("kernel.vector_mismatch", "static", str(vector.get("id", "")))
            continue
        rule_projections.append(
            (
                str(vector.get("id", "")),
                content_identity("rule-vector-projection-v2", cast(JsonValue, output)),
            )
        )

    ldb_diagnostics = cast(list[dict[str, Any]], language_bundle.get("diagnostics", []))
    ldb_codes = [str(item.get("code", "")) for item in ldb_diagnostics]
    if len(ldb_codes) != len(set(ldb_codes)):
        refuse("kernel.duplicate_identifier", "static", "language-bundle.diagnostics")
    ldb_catalog = {
        (str(item.get("code", "")), str(item.get("stage", "")))
        for item in ldb_diagnostics
    }
    ldb_vector_catalog = {
        (str(item["diagnostic"]), str(item.get("stage", "")))
        for item in ldb_vectors
        if "diagnostic" in item
    }
    if ldb_catalog != ldb_vector_catalog:
        refuse("kernel.diagnostic_closure", "static", "language-bundle.diagnostics")

    reason_ids = [str(item.get("id", "")) for item in reasons]
    if len(reason_ids) != len(set(reason_ids)):
        refuse("kernel.duplicate_identifier", "static", "language.reasons")
    reason_vectors = [item for item in ldb_vectors if "diagnostic" in item]
    if set(reason_ids) != {str(item.get("reason", "")) for item in reason_vectors}:
        refuse("kernel.vector_mismatch", "static", "language-bundle.reasons")
    by_reason = {str(item.get("id", "")): item for item in reasons}
    diagnostic_projections: list[tuple[str, str, str]] = []
    for vector in reason_vectors:
        reason = by_reason.get(str(vector.get("reason", "")))
        output = _execute_reason_vector(language_bundle, reason, vector, meta_format)
        expected = {
            "code": vector.get("diagnostic"),
            "matched": vector.get("matched"),
            "stage": vector.get("stage"),
        }
        if output != expected:
            refuse("kernel.vector_mismatch", "static", str(vector.get("id", "")))
            continue
        diagnostic_projections.append(
            (
                str(vector.get("id", "")),
                str(vector.get("diagnostic", "")),
                content_identity(
                    "diagnostic-vector-projection-v2", cast(JsonValue, output)
                ),
            )
        )
    for reason_id, reason in by_reason.items():
        vectors = [
            vector for vector in reason_vectors if vector.get("reason") == reason_id
        ]
        if not _reason_vectors_cover_operands(
            language_bundle, reason, vectors, meta_format
        ):
            refuse("kernel.vector_mismatch", "static", reason_id)

    if isinstance(packages, list):
        package_coordinates = [
            (str(package.get("id", "")), str(package.get("version", "")))
            for package in packages
            if isinstance(package, dict)
        ]
        if len(package_coordinates) != len(set(package_coordinates)):
            refuse("kernel.duplicate_identifier", "static", "language.packages")
        vector_ids = {str(item.get("id", "")) for item in ldb_vectors}
        constructor_ids = {
            str(item.get("id", ""))
            for item in cast(list[dict[str, Any]], language.get("constructors", []))
        }
        numeric_profiles = {
            str(item.get("id", ""))
            for item in cast(dict[str, Any], language.get("quantity", {})).get(
                "numeric_policies", []
            )
            if isinstance(item, dict)
        }
        for package in packages:
            if not isinstance(package, dict):
                continue
            exports = cast(dict[str, Any], package.get("exports", {}))
            profiles = cast(dict[str, Any], package.get("profiles", {}))
            references_close = (
                set(map(str, package.get("vectors", []))) <= vector_ids
                and set(map(str, exports.get("language_rules", []))) <= set(rule_ids)
                and set(map(str, exports.get("diagnostics", []))) <= set(ldb_codes)
                and set(map(str, profiles.get("numeric", []))) <= numeric_profiles
                and all(
                    str(item.get("constructor", "")) in constructor_ids
                    for item in exports.get("types", [])
                    if isinstance(item, dict)
                )
            )
            if not references_close:
                refuse(
                    "kernel.vector_mismatch",
                    "static",
                    f"language.packages.{package.get('id', '')}",
                )
        if not _reference_contracts_close(kernel, language_bundle):
            refuse("kernel.vector_mismatch", "static", "language.packages")

    return _result(
        found,
        cap,
        kernel_identity if isinstance(kernel_identity, str) else None,
        ldb_identity if isinstance(ldb_identity, str) else None,
        tuple(sorted(law_ids)),
        law_projections,
        tuple(sorted(rule_ids)),
        tuple(sorted(rule_projections)),
        tuple(sorted(diagnostic_projections)),
    )


def _execute_rule_vector(
    rules: list[dict[str, Any]],
    vector: dict[str, Any],
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> dict[str, Any] | None:
    """Execute the Kernel's closed fact/select/bind/substitute meta-format."""
    if set(vector) != {"expect", "id", "input", "rule"}:
        return None
    invocation = vector.get("input")
    if not isinstance(invocation, dict) or set(invocation) != {
        "facts",
        "judgment",
        "phase",
    }:
        return None
    judgment = invocation.get("judgment")
    phase = invocation.get("phase")
    facts = invocation.get("facts")
    if (
        not isinstance(judgment, str)
        or not isinstance(phase, str)
        or not isinstance(facts, list)
        or not all(
            _fact_is_closed(fact, meta_format, language_bundle) for fact in facts
        )
    ):
        return None

    candidates: list[dict[str, Any]] = []
    for rule in sorted(rules, key=lambda item: str(item.get("id", ""))):
        premises = rule.get("premises")
        if (
            rule.get("phase") != phase
            or rule.get("judgment") != judgment
            or not isinstance(premises, list)
        ):
            continue
        if len(premises) != len(facts):
            continue
        if all(
            isinstance(premise, dict)
            and isinstance(fact, dict)
            and premise.get("fact_kind") == fact.get("kind")
            for premise, fact in zip(premises, facts, strict=True)
        ):
            candidates.append(rule)
    if len(candidates) != 1 or candidates[0].get("id") != vector.get("rule"):
        return None

    selected = candidates[0]
    bindings: dict[str, Any] = {}
    for premise, fact in zip(selected["premises"], facts, strict=True):
        fields = fact.get("fields")
        bind = premise.get("bind")
        if not isinstance(fields, dict) or not isinstance(bind, dict):
            return None
        for variable, field_name in bind.items():
            if not isinstance(variable, str) or field_name not in fields:
                return None
            value = fields[field_name]
            if variable in bindings and bindings[variable] != value:
                return None
            bindings[variable] = value

    conclusion = selected.get("conclusion")
    if not isinstance(conclusion, dict) or not isinstance(
        conclusion.get("fields"), dict
    ):
        return None
    output_fields: dict[str, Any] = {}
    for name, term in conclusion["fields"].items():
        if not isinstance(name, str) or not isinstance(term, dict):
            return None
        if term.get("tag") == "literal" and set(term) == {"tag", "value"}:
            output_fields[name] = term["value"]
        elif term.get("tag") == "variable" and set(term) == {"tag", "name"}:
            variable = term["name"]
            if not isinstance(variable, str) or variable not in bindings:
                return None
            output_fields[name] = bindings[variable]
        else:
            return None
    output = {"kind": conclusion.get("fact_kind"), "fields": output_fields}
    return output if _fact_is_closed(output, meta_format, language_bundle) else None


def _rule_is_closed(
    rule: Any,
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> bool:
    contract = meta_format.get("rule")
    term_contract = meta_format.get("term")
    fact_schemas = _fact_schemas(meta_format)
    if (
        not isinstance(contract, dict)
        or not isinstance(rule, dict)
        or contract.get("closed") is not True
        or not isinstance(contract.get("required_members"), list)
        or set(rule) != set(contract["required_members"])
        or rule.get("phase") not in contract.get("phases", [])
        or not isinstance(rule.get("id"), str)
        or not rule.get("id")
        or not isinstance(rule.get("judgment"), str)
        or not rule.get("judgment")
        or not fact_schemas
    ):
        return False
    premises = rule.get("premises")
    conclusion = rule.get("conclusion")
    premise_members = contract.get("premise_required_members")
    conclusion_members = contract.get("conclusion_required_members")
    if not isinstance(premises, list) or not isinstance(premise_members, list):
        return False
    for item in premises:
        if not isinstance(item, dict):
            return False
        fact_kind = item.get("fact_kind")
        bindings = item.get("bind")
        if (
            set(item) != set(premise_members)
            or not isinstance(fact_kind, str)
            or fact_kind not in fact_schemas
            or not isinstance(bindings, dict)
            or not all(
                isinstance(variable, str)
                and variable
                and isinstance(field, str)
                and field in fact_schemas[fact_kind]
                for variable, field in bindings.items()
            )
        ):
            return False
    conclusion_kind = (
        conclusion.get("fact_kind") if isinstance(conclusion, dict) else None
    )
    if (
        not isinstance(conclusion, dict)
        or not isinstance(conclusion_members, list)
        or set(conclusion) != set(conclusion_members)
        or not isinstance(conclusion_kind, str)
        or conclusion_kind not in fact_schemas
    ):
        return False
    fields = conclusion.get("fields")
    if (
        not isinstance(fields, dict)
        or set(fields) != set(fact_schemas[conclusion_kind])
        or not isinstance(term_contract, dict)
        or not isinstance(term_contract.get("constructors"), list)
    ):
        return False
    constructors = {
        str(item.get("tag")): item
        for item in term_contract["constructors"]
        if isinstance(item, dict)
    }
    for term in fields.values():
        if not isinstance(term, dict):
            return False
        tag = term.get("tag")
        constructor = constructors.get(tag) if isinstance(tag, str) else None
        if not isinstance(constructor, dict):
            return False
        required_members = constructor.get("required_members")
        member_types = constructor.get("member_types")
        if (
            not isinstance(required_members, list)
            or set(term) != set(required_members)
            or not isinstance(member_types, dict)
            or set(member_types) != set(required_members)
            or not all(
                _value_matches_contract(term[name], member_types[name], language_bundle)
                for name in term
            )
        ):
            return False
    return True


def _execute_reason_vector(
    language_bundle: dict[str, Any],
    reason: dict[str, Any] | None,
    vector: dict[str, Any],
    meta_format: dict[str, Any],
) -> dict[str, Any] | None:
    """Execute one closed post-admission reason predicate from LDB data."""
    reason_contract = meta_format.get("diagnostic_reason")
    if not isinstance(reason_contract, dict):
        return None
    required = reason_contract.get("vector_required_members")
    member_types = reason_contract.get("vector_member_types")
    if (
        not isinstance(required, list)
        or set(vector) != set(required)
        or not isinstance(member_types, dict)
        or set(member_types) != set(required) - {"input"}
        or not all(
            _value_matches_contract(vector[name], member_types[name], language_bundle)
            for name in member_types
        )
        or not _reason_is_closed(reason, meta_format, language_bundle)
        or not isinstance(vector.get("input"), dict)
    ):
        return None
    assert reason is not None
    if (
        vector["reason"] != reason.get("id")
        or vector["diagnostic"] != reason.get("diagnostic")
        or vector["stage"] != reason.get("stage")
    ):
        return None
    predicate = reason.get("predicate")
    if not isinstance(predicate, dict):
        return None
    operation = predicate.get("operation")
    inp = cast(dict[str, Any], vector["input"])
    predicate_schema = next(
        (
            item
            for item in cast(list[dict[str, Any]], reason_contract["predicate_schemas"])
            if item.get("operation") == operation
        ),
        None,
    )
    input_types = (
        predicate_schema.get("input_member_types")
        if isinstance(predicate_schema, dict)
        else None
    )
    if (
        not isinstance(predicate_schema, dict)
        or set(inp) != set(cast(list[str], predicate_schema.get("input_members", [])))
        or not isinstance(input_types, dict)
        or set(inp) != set(input_types)
        or not all(
            _value_matches_contract(inp[name], input_types[name], language_bundle)
            for name in inp
        )
    ):
        return None
    matched = False
    if operation == "not-member":
        inventory = _resolve_path(language_bundle, predicate.get("inventory_path"))
        if not isinstance(inventory, list):
            return None
        member_field = predicate.get("member_field")
        values = [
            item.get(member_field)
            if isinstance(member_field, str) and isinstance(item, dict)
            else item
            for item in inventory
        ]
        matched = _canonical_scalar_key(inp.get("value")) not in {
            _canonical_scalar_key(item) for item in values
        }
    elif operation == "has-duplicate":
        values = inp.get("values")
        if not isinstance(values, list):
            return None
        keys = [_canonical_scalar_key(item) for item in values]
        matched = len(keys) != len(set(keys))
    elif operation == "greater-than":
        limit = _resolve_path(language_bundle, predicate.get("limit_path"))
        value = inp.get("value")
        if not isinstance(limit, int) or not isinstance(value, int):
            return None
        matched = value > limit
    return {
        "code": reason.get("diagnostic"),
        "matched": matched,
        "stage": reason.get("stage"),
    }


def _canonical_scalar_key(value: Any) -> tuple[str, Any]:
    return (
        "null"
        if value is None
        else "boolean"
        if isinstance(value, bool)
        else "integer"
        if isinstance(value, int)
        else "string",
        value,
    )


def _reason_vectors_cover_operands(
    language_bundle: dict[str, Any],
    reason: dict[str, Any],
    vectors: list[dict[str, Any]],
    meta_format: dict[str, Any],
) -> bool:
    contract = meta_format.get("diagnostic_reason")
    predicate = reason.get("predicate")
    if not isinstance(contract, dict) or not isinstance(predicate, dict):
        return False
    coverage = contract.get("vector_coverage")
    operation = predicate.get("operation")
    if not isinstance(coverage, dict) or not isinstance(operation, str):
        return False
    if not vectors or any(
        not isinstance(vector, dict)
        or not isinstance(vector.get("matched"), bool)
        or not isinstance(vector.get("input"), dict)
        for vector in vectors
    ):
        return False
    outcomes = {vector.get("matched") for vector in vectors}
    if outcomes != {False, True}:
        return False
    if operation == "not-member":
        if coverage.get(operation) != "every-inventory-member-and-one-non-member":
            return False
        inventory = _resolve_path(language_bundle, predicate.get("inventory_path"))
        if not isinstance(inventory, list):
            return False
        member_field = predicate.get("member_field")
        if member_field is None:
            values = inventory
        elif (
            isinstance(member_field, str)
            and member_field
            and all(
                isinstance(item, dict) and member_field in item for item in inventory
            )
        ):
            values = [item[member_field] for item in inventory]
        else:
            return False
        if not all(
            _value_matches_contract(
                value, {"type": "canonical-scalar"}, language_bundle
            )
            for value in values
        ):
            return False
        if not all(
            _value_matches_contract(
                cast(dict[str, Any], vector["input"]).get("value"),
                {"type": "canonical-scalar"},
                language_bundle,
            )
            for vector in vectors
        ):
            return False
        nonmatches = {
            _canonical_scalar_key(vector.get("input", {}).get("value"))
            for vector in vectors
            if vector.get("matched") is False and isinstance(vector.get("input"), dict)
        }
        return {_canonical_scalar_key(value) for value in values} <= nonmatches
    if operation == "has-duplicate":
        return coverage.get(operation) == "both-outcomes" and all(
            _value_matches_contract(
                cast(dict[str, Any], vector["input"]).get("values"),
                {"type": "scalar-list"},
                language_bundle,
            )
            for vector in vectors
        )
    if operation == "greater-than":
        if coverage.get(operation) != "limit-and-successor":
            return False
        limit = _resolve_path(language_bundle, predicate.get("limit_path"))
        if not isinstance(limit, int) or isinstance(limit, bool) or limit >= 2**63 - 1:
            return False
        if not all(
            _value_matches_contract(
                cast(dict[str, Any], vector["input"]).get("value"),
                {"type": "signed-int64"},
                language_bundle,
            )
            for vector in vectors
        ):
            return False
        witnesses = {
            (vector.get("input", {}).get("value"), vector.get("matched"))
            for vector in vectors
            if isinstance(vector.get("input"), dict)
        }
        return {(limit, False), (limit + 1, True)} <= witnesses
    return False


def _resolve_path(root: dict[str, Any], dotted: Any) -> Any:
    if not isinstance(dotted, str):
        return None
    value: Any = root
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _result(
    found: set[AdmissionDiagnostic],
    cap: int,
    kernel_identity: str | None,
    ldb_identity: str | None,
    law_ids: tuple[str, ...],
    law_projections: tuple[tuple[str, str], ...],
    rule_ids: tuple[str, ...],
    rule_projections: tuple[tuple[str, str], ...],
    diagnostic_projections: tuple[tuple[str, str, str], ...],
) -> BootstrapAdmission:
    ordered = sorted(found, key=lambda item: (item.stage, item.subject, item.code))
    truncated = len(ordered) > cap
    emitted = tuple(ordered[:cap])
    return BootstrapAdmission(
        admitted=not found,
        kernel_identity=kernel_identity,
        language_bundle_identity=ldb_identity,
        law_ids=law_ids,
        law_projections=law_projections,
        rule_ids=rule_ids,
        rule_projections=rule_projections,
        diagnostic_projections=diagnostic_projections,
        diagnostics=emitted,
        truncated=truncated,
    )
