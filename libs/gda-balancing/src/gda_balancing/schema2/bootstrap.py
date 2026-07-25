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
from gda_balancing.schema2.template_contract import (
    TEMPLATE_ARGUMENT_TYPES,
    TEMPLATE_PRIMITIVE_CHARGES,
    TEMPLATE_PRIMITIVE_EVALUATIONS,
    TEMPLATE_PRIMITIVE_RESULT_EFFECTS,
    TEMPLATE_RESOURCE_ACCOUNTING,
    TEMPLATE_SELECTOR_CONTRACT,
)

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
    "sha256:87125b0d62997effb17c8aeb8128be567ebcaee836e4b6e82297d69051d2bbe9"
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


def _package_semantic_closure_is_closed(
    package: dict[str, Any],
    contract: Any,
) -> bool:
    if not isinstance(contract, dict):
        return False
    closure_contract = contract.get("semantic_closure")
    closure = package.get("semantic_closure")
    if not isinstance(closure_contract, dict) or not isinstance(closure, list):
        return False
    domain = closure_contract.get("domain")
    entry_members = closure_contract.get("entry_members")
    projections = closure_contract.get("projections")
    if (
        not isinstance(domain, str)
        or not domain
        or not isinstance(entry_members, list)
        or entry_members != ["authority_path", "definitions"]
        or not isinstance(projections, list)
        or len(closure) != len(projections)
    ):
        return False
    for entry, projection in zip(closure, projections, strict=True):
        key_member = (
            projection.get("key_member") if isinstance(projection, dict) else None
        )
        owners_path = (
            projection.get("owners_path") if isinstance(projection, dict) else None
        )
        if (
            not isinstance(entry, dict)
            or set(entry) != set(entry_members)
            or not isinstance(projection, dict)
            or set(projection) != {"authority_path", "key_member", "owners_path"}
            or entry.get("authority_path") != projection.get("authority_path")
            or not isinstance(entry.get("definitions"), list)
            or not isinstance(projection.get("authority_path"), str)
            or (key_member is not None and not isinstance(key_member, str))
            or not isinstance(owners_path, str)
            or not owners_path
            or not _path_is_declared(package, owners_path)
        ):
            return False
        definitions = entry["definitions"]
        owned_values = _path_values(package, owners_path)

        def definition_key(value: Any) -> bytes | None:
            selected = value
            if key_member is not None:
                if not isinstance(value, dict) or key_member not in value:
                    return None
                selected = value[key_member]
            try:
                return canonical_bytes(cast(JsonValue, selected))
            except (TypeError, ValueError):
                return None

        def owner_key(value: Any) -> bytes | None:
            try:
                return canonical_bytes(cast(JsonValue, value))
            except (TypeError, ValueError):
                return None

        definition_keys = [definition_key(value) for value in definitions]
        owner_keys = [owner_key(value) for value in owned_values]
        if (
            any(key is None for key in definition_keys)
            or any(key is None for key in owner_keys)
            or len(set(definition_keys)) != len(definition_keys)
            or len(set(owner_keys)) != len(owner_keys)
            or set(definition_keys) != set(owner_keys)
        ):
            return False
    semantic_projection = contract.get("semantic_identity_projection")
    if (
        not isinstance(semantic_projection, dict)
        or set(semantic_projection)
        != {"domain", "path_inventory_member", "source_member", "path_member"}
        or semantic_projection.get("source_member") != "semantic_closure"
        or semantic_projection.get("path_member") != "authority_path"
        or not isinstance(semantic_projection.get("domain"), str)
        or not isinstance(semantic_projection.get("path_inventory_member"), str)
    ):
        return False
    runtime_paths = package.get(semantic_projection["path_inventory_member"])
    closure_paths = [entry["authority_path"] for entry in closure]
    if (
        not isinstance(runtime_paths, list)
        or not runtime_paths
        or not all(isinstance(path, str) and path for path in runtime_paths)
        or len(runtime_paths) != len(set(runtime_paths))
        or not set(runtime_paths) <= set(closure_paths)
    ):
        return False
    runtime_closure = [
        entry for entry in closure if entry["authority_path"] in set(runtime_paths)
    ]
    try:
        expected = content_identity(
            semantic_projection["domain"], cast(JsonValue, runtime_closure)
        )
    except (TypeError, ValueError):
        return False
    return package.get("semantic_identity") == expected


def _package_semantic_projections_are_exact(
    packages: list[dict[str, Any]],
    contract: Any,
    language_bundle: dict[str, Any],
) -> bool:
    if not isinstance(contract, dict):
        return False
    closure_contract = contract.get("semantic_closure")
    if not isinstance(closure_contract, dict):
        return False
    projections = closure_contract.get("projections")
    if not isinstance(projections, list):
        return False
    for index, projection in enumerate(projections):
        if not isinstance(projection, dict):
            return False
        authority_path = projection.get("authority_path")
        key_member = projection.get("key_member")
        declared, authority_definitions = _exact_path_value(
            language_bundle, authority_path
        )
        if not declared or not isinstance(authority_definitions, list):
            return False
        embedded: list[Any] = []
        for package in packages:
            closure = package.get("semantic_closure")
            if not isinstance(closure, list) or index >= len(closure):
                return False
            entry = closure[index]
            if (
                not isinstance(entry, dict)
                or entry.get("authority_path") != authority_path
                or not isinstance(entry.get("definitions"), list)
            ):
                return False
            embedded.extend(entry["definitions"])

        def definition_key(value: Any) -> tuple[str, bytes] | None:
            if key_member is None:
                try:
                    return ("value", canonical_bytes(cast(JsonValue, value)))
                except (TypeError, ValueError):
                    return None
            if (
                not isinstance(key_member, str)
                or not isinstance(value, dict)
                or key_member not in value
            ):
                return None
            try:
                return (
                    "member",
                    canonical_bytes(cast(JsonValue, value[key_member])),
                )
            except (TypeError, ValueError):
                return None

        embedded_keys = [definition_key(value) for value in embedded]
        authority_keys = [definition_key(value) for value in authority_definitions]
        if (
            any(key is None for key in embedded_keys)
            or any(key is None for key in authority_keys)
            or len(set(embedded_keys)) != len(embedded_keys)
            or len(set(authority_keys)) != len(authority_keys)
        ):
            return False
        embedded_by_key = dict(zip(embedded_keys, embedded, strict=True))
        authority_by_key = dict(zip(authority_keys, authority_definitions, strict=True))
        if embedded_by_key != authority_by_key:
            return False
    return True


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


def _profiled_equality_values(
    authorities: dict[str, Any], contract: dict[str, Any]
) -> list[Any] | None:
    profile_contract = contract.get("profile")
    template = contract.get("right_template")
    if (
        not isinstance(profile_contract, dict)
        or set(profile_contract)
        != {
            "owner_profile_member",
            "owners",
            "profile_key_member",
            "profiles",
        }
        or not isinstance(template, list)
        or not template
        or not all(
            (isinstance(segment, str) and bool(segment))
            or (
                isinstance(segment, dict)
                and set(segment) == {"profile_member"}
                and isinstance(segment["profile_member"], str)
                and bool(segment["profile_member"])
            )
            for segment in template
        )
    ):
        return None
    owners_path = profile_contract.get("owners")
    profiles_path = profile_contract.get("profiles")
    owner_profile_member = profile_contract.get("owner_profile_member")
    profile_key_member = profile_contract.get("profile_key_member")
    if (
        not isinstance(owners_path, str)
        or not _path_is_declared(authorities, owners_path)
        or not isinstance(profiles_path, str)
        or not _path_is_declared(authorities, profiles_path)
        or not isinstance(owner_profile_member, str)
        or not owner_profile_member
        or not isinstance(profile_key_member, str)
        or not profile_key_member
    ):
        return None
    owners = _path_values(authorities, owners_path)
    profiles = _path_values(authorities, profiles_path)
    if not owners or not profiles:
        return None
    profile_rows = [
        profile
        for profile in profiles
        if isinstance(profile, dict) and profile_key_member in profile
    ]
    profile_keys = [profile[profile_key_member] for profile in profile_rows]
    if len(profile_rows) != len(profiles) or len(profile_keys) != len(
        set(profile_keys)
    ):
        return None
    profiles_by_key = dict(zip(profile_keys, profile_rows, strict=True))
    selected_profiles: list[dict[str, Any]] = []
    for owner in owners:
        if (
            not isinstance(owner, dict)
            or owner_profile_member not in owner
            or owner[owner_profile_member] not in profiles_by_key
        ):
            return None
        profile = profiles_by_key[owner[owner_profile_member]]
        if profile not in selected_profiles:
            selected_profiles.append(profile)

    values: list[Any] = []
    for profile in selected_profiles:
        segments: list[str] = []
        for segment in template:
            if isinstance(segment, str):
                segments.append(segment)
                continue
            profile_value = profile.get(segment["profile_member"])
            if not isinstance(profile_value, str) or not profile_value:
                return None
            segments.append(profile_value)
        selected: list[Any] = [authorities]
        for segment in segments:
            expanded: list[Any] = []
            for value in selected:
                candidates = value if isinstance(value, list) else [value]
                for candidate in candidates:
                    if not isinstance(candidate, dict) or segment not in candidate:
                        continue
                    child = candidate[segment]
                    expanded.extend(child if isinstance(child, list) else [child])
            if not expanded:
                return None
            selected = expanded
        values.extend(selected)
    return values


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
    correlations = vector_law.get("arguments", {}).get("correlations")
    if (
        not isinstance(references, list)
        or not isinstance(equalities, list)
        or not isinstance(correlations, list)
    ):
        return False
    authorities = {"kernel": kernel, "language_bundle": language_bundle}
    for contract in correlations:
        if not isinstance(contract, dict):
            return False
        collection_contract = {
            "owners",
            "owner_value_member",
            "references_member",
            "targets",
            "target_key_member",
            "target_value_member",
        }
        invocation_contract = {
            "equal_members",
            "owner_key_member",
            "owners",
            "target_key_member",
            "targets",
        }
        if set(contract) == invocation_contract:
            owners = _path_values(authorities, contract["owners"])
            targets = _path_values(authorities, contract["targets"])
            equal_members = contract["equal_members"]
            owner_key_member = contract["owner_key_member"]
            target_key_member = contract["target_key_member"]
            if (
                not _path_is_declared(authorities, contract["owners"])
                or not _path_is_declared(authorities, contract["targets"])
                or not isinstance(equal_members, list)
                or not equal_members
                or not all(
                    isinstance(member, str) and member for member in equal_members
                )
                or not isinstance(owner_key_member, str)
                or not isinstance(target_key_member, str)
            ):
                return False
            target_rows = [
                target
                for target in targets
                if isinstance(target, dict) and target_key_member in target
            ]
            target_keys = [target[target_key_member] for target in target_rows]
            if len(target_keys) != len(set(target_keys)):
                return False
            targets_by_key = dict(zip(target_keys, target_rows, strict=True))
            if any(
                not isinstance(owner, dict)
                or owner_key_member not in owner
                or owner[owner_key_member] not in targets_by_key
                or any(
                    owner.get(member)
                    != targets_by_key[owner[owner_key_member]].get(member)
                    for member in equal_members
                )
                for owner in owners
            ):
                return False
            continue
        if set(contract) != collection_contract:
            return False
        owners = _path_values(authorities, contract["owners"])
        targets = _path_values(authorities, contract["targets"])
        owner_value_member = contract["owner_value_member"]
        references_member = contract["references_member"]
        target_key_member = contract["target_key_member"]
        target_value_member = contract["target_value_member"]
        if (
            not _path_is_declared(authorities, contract["owners"])
            or not _path_is_declared(authorities, contract["targets"])
            or not all(
                isinstance(name, str) and name
                for name in (
                    owner_value_member,
                    references_member,
                    target_key_member,
                    target_value_member,
                )
            )
        ):
            return False
        target_values = {
            target[target_key_member]: target.get(target_value_member)
            for target in targets
            if isinstance(target, dict) and target_key_member in target
        }
        for owner in owners:
            if (
                not isinstance(owner, dict)
                or owner_value_member not in owner
                or not isinstance(owner.get(references_member), list)
                or any(
                    reference not in target_values
                    or target_values[reference] != owner[owner_value_member]
                    for reference in owner[references_member]
                )
            ):
                return False
    for contract in equalities:
        if not isinstance(contract, dict) or contract.get("mode") != "set":
            return False
        if set(contract) == {"left", "mode", "right"}:
            if not _path_is_declared(
                authorities, contract.get("left")
            ) or not _path_is_declared(authorities, contract.get("right")):
                return False
            right_values = _path_values(authorities, contract["right"])
        elif set(contract) == {
            "left",
            "mode",
            "profile",
            "right_template",
        }:
            if not _path_is_declared(authorities, contract.get("left")):
                return False
            right_values = _profiled_equality_values(authorities, contract)
            if right_values is None:
                return False
        else:
            return False
        try:
            if set(_path_values(authorities, contract["left"])) != set(right_values):
                return False
        except TypeError:
            return False
    for contract in references:
        if not isinstance(contract, dict):
            return False
        owners = _path_values(authorities, contract.get("owners"))
        targets = contract.get("targets")
        if not _path_is_declared(authorities, contract.get("owners")) or not isinstance(
            targets, dict
        ):
            return False
        # Reference contracts quantify the rows that exist. A declared empty
        # owner collection is closed by construction; optional language
        # collections such as Conversions must not require a fabricated row.
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
    if value_type == "path-segments":
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and item for item in value)
        )
    if value_type == "canonical-value":
        try:
            canonical_bytes(cast(JsonValue, value))
        except (TypeError, ValueError):
            return False
        return True
    if value_type == "closed-object":
        required = contract.get("required_members")
        field_types = contract.get("field_types")
        return (
            isinstance(value, dict)
            and isinstance(required, list)
            and isinstance(field_types, dict)
            and set(value) == set(required)
            and set(field_types) == set(required)
            and all(
                _value_matches_contract(value[name], field_types[name], language_bundle)
                for name in required
            )
        )
    if value_type == "list-of":
        item_contract = contract.get("items")
        return (
            isinstance(value, list)
            and isinstance(item_contract, dict)
            and all(
                _value_matches_contract(item, item_contract, language_bundle)
                for item in value
            )
        )
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
    optional = contract.get("optional_members", [])
    field_types = contract.get("field_types")
    return (
        isinstance(required, list)
        and isinstance(optional, list)
        and isinstance(field_types, dict)
        and not set(required) & set(optional)
        and set(required) <= set(value)
        and set(value) <= set(required) | set(optional)
        and set(field_types) == set(required) | set(optional)
        and all(
            _value_matches_contract(value[name], field_types[name], language_bundle)
            for name in value
        )
    )


def _fact_contract_at_path(fields: dict[str, Any], path: Any) -> dict[str, Any] | None:
    if (
        not isinstance(path, list)
        or not path
        or not all(isinstance(segment, str) and segment for segment in path)
        or path[0] not in fields
    ):
        return None
    contract = fields[path[0]]
    for segment in path[1:]:
        if (
            not isinstance(contract, dict)
            or contract.get("type") != "closed-object"
            or not isinstance(contract.get("field_types"), dict)
            or segment not in contract["field_types"]
        ):
            return None
        contract = contract["field_types"][segment]
    return contract if isinstance(contract, dict) else None


def _fact_contract_path_is_declared(fields: dict[str, Any], path: Any) -> bool:
    return _fact_contract_at_path(fields, path) is not None


def _resolution_judgment_is_closed(contract: Any) -> bool:
    if (
        not isinstance(contract, dict)
        or set(contract)
        != {
            "closed",
            "input",
            "operations",
            "result",
            "stage_order",
            "relation_schemas",
            "relation_recipe_format",
            "routing_equivalences",
            "resource_accounting",
            "law_format",
        }
        or contract.get("closed") is not True
    ):
        return False
    stages = contract.get("stage_order")
    relations = contract.get("relation_schemas")
    operations = contract.get("operations")
    law_format = contract.get("law_format")
    recipe_format = contract.get("relation_recipe_format")
    routing_equivalences = contract.get("routing_equivalences")
    resource_accounting = contract.get("resource_accounting")
    if (
        not isinstance(stages, list)
        or not stages
        or not all(isinstance(stage, str) and stage for stage in stages)
        or len(stages) != len(set(stages))
        or not isinstance(relations, list)
        or not relations
        or not isinstance(operations, list)
        or not operations
        or not isinstance(law_format, dict)
        or set(law_format) != {"closed", "operators"}
        or law_format.get("closed") is not True
        or not isinstance(law_format.get("operators"), list)
        or not isinstance(recipe_format, dict)
        or set(recipe_format)
        != {
            "closed",
            "binding_source_roots",
            "term_roots",
            "predicate_operators",
            "binding",
            "term",
            "predicate",
            "field",
            "root_typing",
        }
        or recipe_format.get("closed") is not True
        or recipe_format.get("binding_source_roots")
        != ["source", "language", "binding"]
        or recipe_format.get("term_roots") != ["source", "language", "binding"]
        or recipe_format.get("predicate_operators") != ["equal"]
        or recipe_format.get("binding")
        != {
            "required_members": ["name", "source"],
            "source_result": "list",
            "expansion_order": "source-list-order",
        }
        or recipe_format.get("term")
        != {
            "required_members": {
                "source": ["root", "path"],
                "language": ["root", "path"],
                "binding": ["root", "binding", "path"],
            },
            "path_semantics": "closed-object-member-path",
            "empty_path": "identity",
        }
        or recipe_format.get("predicate")
        != {
            "required_members": ["operator", "left", "right"],
            "operand_type": "canonical-value",
        }
        or recipe_format.get("field")
        != {
            "required_members": ["name", "term", "pointer"],
            "result_type": "non-empty-string",
            "pointer_true_origin": "source",
        }
        or recipe_format.get("root_typing")
        != {
            "source": "model-source-wire-schema",
            "language": "kernel-declared-language-contracts",
            "binding": "expanded-binding-item",
        }
        or not isinstance(routing_equivalences, list)
        or not routing_equivalences
        or any(
            not isinstance(item, dict)
            or set(item)
            != {
                "profile_member",
                "recipe",
                "subject_kind",
                "subject",
                "projection",
            }
            or not all(
                isinstance(item.get(member), str) and item[member]
                for member in ("profile_member", "recipe", "subject")
            )
            or item.get("subject_kind") not in {"binding-source", "field-term"}
            or item.get("projection") not in {"dot-path", "last-segment"}
            for item in routing_equivalences
        )
        or len(
            {
                item["profile_member"]
                for item in routing_equivalences
                if isinstance(item, dict) and "profile_member" in item
            }
        )
        != len(routing_equivalences)
        or resource_accounting
        != {
            "limit_member": "max_rule_match_steps",
            "counter_scope": "per-resolution-stage",
            "charged_events": [
                "binding-expansion",
                "predicate-comparison",
                "field-projection",
                "law-subject-evaluation",
                "law-target-comparison",
            ],
            "exhaustion_reason": {
                "stage": "static",
                "operation": "greater-than",
                "limit_path": "resources.max_rule_match_steps",
            },
        }
    ):
        return False
    relation_fields: dict[str, set[str]] = {}
    for relation in relations:
        if (
            not isinstance(relation, dict)
            or set(relation) != {"id", "fields", "pointer_fields"}
            or not isinstance(relation.get("id"), str)
            or not isinstance(relation.get("fields"), list)
            or not relation["fields"]
            or not all(isinstance(field, str) and field for field in relation["fields"])
            or len(relation["fields"]) != len(set(relation["fields"]))
            or not isinstance(relation.get("pointer_fields"), list)
            or not all(
                isinstance(field, str) and field for field in relation["pointer_fields"]
            )
            or not set(relation["pointer_fields"]) <= set(relation["fields"])
            or relation["id"] in relation_fields
        ):
            return False
        relation_fields[relation["id"]] = set(relation["fields"])
    law_specs = {
        item["id"]: item
        for item in law_format["operators"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if len(law_specs) != len(law_format["operators"]):
        return False
    for spec in law_specs.values():
        required = spec.get("required_members")
        optional = spec.get("optional_members")
        if (
            set(spec)
            not in (
                {"id", "required_members", "optional_members"},
                {"id", "required_members", "optional_members", "cardinalities"},
            )
            or not isinstance(required, list)
            or not isinstance(optional, list)
            or not all(isinstance(member, str) and member for member in required)
            or not all(isinstance(member, str) and member for member in optional)
            or len(required) != len(set(required))
            or len(optional) != len(set(optional))
            or set(required) & set(optional)
        ):
            return False
    operation_ids: set[str] = set()
    for operation in operations:
        if (
            not isinstance(operation, dict)
            or set(operation)
            != {
                "id",
                "stage",
                "law",
                "input",
                "result",
                "effects",
                "refusals",
                "resources",
            }
            or not isinstance(operation.get("id"), str)
            or operation["id"] in operation_ids
            or operation.get("stage") not in stages
            or not isinstance(operation.get("law"), dict)
            or operation.get("input") != {"fact_kind": "resolution-state"}
            or operation.get("result") != {"fact_kind": "resolution-state"}
            or operation.get("effects") != []
            or operation.get("refusals") != ["reason-bound-diagnostic"]
            or operation.get("resources")
            != [
                "max_diagnostics",
                "max_rule_match_steps",
                "max_symbols",
            ]
        ):
            return False
        operation_ids.add(operation["id"])
        law = operation["law"]
        spec = law_specs.get(law.get("operator"))
        if not isinstance(spec, dict):
            return False
        required_members = set(spec["required_members"])
        optional_members = set(spec["optional_members"])
        if not required_members <= set(law) or not set(law) <= (
            required_members | optional_members
        ):
            return False
        operator = law["operator"]
        if operator == "require-match":
            subject_fields = relation_fields.get(law.get("subject_relation"))
            target_fields = relation_fields.get(law.get("target_relation"))
            matches = law.get("match")
            cardinalities = spec.get("cardinalities")
            if (
                subject_fields is None
                or target_fields is None
                or not isinstance(matches, list)
                or not matches
                or not isinstance(cardinalities, list)
                or law.get("cardinality") not in cardinalities
                or law.get("pointer_field") not in subject_fields
                or any(
                    not isinstance(match, dict)
                    or set(match) != {"subject", "target"}
                    or match.get("subject") not in subject_fields
                    or match.get("target") not in target_fields
                    for match in matches
                )
            ):
                return False
            guard = law.get("guard")
            if guard is not None:
                guard_relation = (
                    guard.get("target_relation") if isinstance(guard, dict) else None
                )
                guard_fields = (
                    relation_fields.get(guard_relation)
                    if isinstance(guard_relation, str)
                    else None
                )
                if (
                    not isinstance(guard, dict)
                    or set(guard) != {"target_relation", "match", "cardinality"}
                    or guard_fields is None
                    or guard.get("cardinality") not in cardinalities
                    or not isinstance(guard.get("match"), list)
                    or not guard["match"]
                    or any(
                        not isinstance(match, dict)
                        or set(match) != {"subject", "target"}
                        or match.get("subject") not in subject_fields
                        or match.get("target") not in guard_fields
                        for match in guard["match"]
                    )
                ):
                    return False
        elif operator in {"require-unique", "require-single-value"}:
            fields = relation_fields.get(law.get("relation"))
            list_members = (
                ("scope", "key")
                if operator == "require-unique"
                else ("scope", "group", "value")
            )
            if (
                fields is None
                or law.get("pointer_field") not in fields
                or any(
                    not isinstance(law.get(member), list)
                    or not all(field in fields for field in law[member])
                    for member in list_members
                )
                or (
                    operator == "require-unique" and not cast(list[Any], law.get("key"))
                )
                or (
                    operator == "require-single-value"
                    and (
                        not cast(list[Any], law.get("group"))
                        or not cast(list[Any], law.get("value"))
                    )
                )
            ):
                return False
        else:
            return False
    flattened = [
        operation["id"]
        for stage in stages
        for operation in operations
        if operation["stage"] == stage
    ]
    return flattened == [operation["id"] for operation in operations]


def _json_schema_path(schema: Any, path: list[str]) -> dict[str, Any] | None:
    current = schema
    for segment in path:
        if (
            not isinstance(current, dict)
            or current.get("type") != "object"
            or not isinstance(current.get("properties"), dict)
            or segment not in current["properties"]
        ):
            return None
        current = current["properties"][segment]
    return current if isinstance(current, dict) else None


def _schema_value_kind(schema: Any) -> str | None:
    if not isinstance(schema, dict):
        return None
    value_type = schema.get("type")
    if isinstance(value_type, str):
        return value_type
    if "const" in schema:
        value = schema["const"]
        if isinstance(value, str):
            return "string"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        kinds = {_canonical_value_kind(value) for value in schema["enum"]}
        if len(kinds) == 1:
            return kinds.pop()
    return None


def _canonical_value_kind(value: Any) -> str | None:
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return None


def _package_release_path_contract(
    contract: dict[str, Any], path: list[str]
) -> dict[str, Any] | None:
    if not path:
        return contract
    if len(path) == 1:
        field_types = contract.get("field_types")
        selected = field_types.get(path[0]) if isinstance(field_types, dict) else None
        return selected if isinstance(selected, dict) else None
    if len(path) != 2:
        return None
    nested = contract.get("nested_field_types")
    group = nested.get(path[0]) if isinstance(nested, dict) else None
    selected = group.get(path[1]) if isinstance(group, dict) else None
    if not isinstance(selected, dict):
        return None
    if path == ["exports", "types"]:
        item = contract.get("type_export")
        if not isinstance(item, dict):
            return None
        return {**selected, "items": item}
    return selected


def _contract_value_kind(contract: Any) -> str | None:
    if not isinstance(contract, dict):
        return None
    value_type = contract.get("type")
    if value_type in {"inventory-member", "non-empty-string", "string"}:
        return "string"
    if value_type in {"list", "list-of", "string-list"}:
        return "array"
    if value_type in {"closed-int64-interval", "closed-object"} or (
        "required_members" in contract and "field_types" in contract
    ):
        return "object"
    if value_type in {"positive-signed-int64", "signed-int64"}:
        return "integer"
    if value_type == "boolean":
        return "boolean"
    if "const" in contract:
        return _canonical_value_kind(contract["const"])
    return None


def _relation_recipe_paths_are_typed(
    profile: dict[str, Any],
    language_bundle: dict[str, Any],
    resolution_contract: dict[str, Any],
    package_release_contract: dict[str, Any],
) -> bool:
    language = language_bundle.get("language")
    wire_schemas = language.get("wire_schemas") if isinstance(language, dict) else None
    if not isinstance(language, dict) or not isinstance(wire_schemas, list):
        return False
    source_schemas = [
        item.get("schema")
        for item in wire_schemas
        if isinstance(item, dict)
        and item.get("artifact_kind") == "model-source-package"
    ]
    if len(source_schemas) != 1 or not isinstance(source_schemas[0], dict):
        return False
    source_schema = source_schemas[0]
    recipes = profile["relation_recipes"]
    recipe_by_id = {recipe["id"]: recipe for recipe in recipes}

    # A shape is (representation, schema-or-values, source-origin).
    def term_shape(
        term: dict[str, Any],
        bindings: dict[str, tuple[str, Any, str]],
    ) -> tuple[str, Any, str] | None:
        root = term["root"]
        if root == "source":
            shape: tuple[str, Any, str] = ("schema", source_schema, "source")
        elif root == "language":
            if term["path"] != ["packages"]:
                return None
            return ("contract-list", package_release_contract, "language")
        elif root == "binding" and term.get("binding") in bindings:
            shape = bindings[term["binding"]]
        else:
            return None
        representation, payload, origin = shape
        path = term["path"]
        if representation == "schema":
            selected = _json_schema_path(payload, path)
            return ("schema", selected, origin) if selected is not None else None
        if representation == "contract":
            selected = _package_release_path_contract(payload, path)
            return ("contract", selected, origin) if selected is not None else None
        values = payload
        for segment in path:
            if not isinstance(values, list):
                return None
            selected_values = []
            for value in values:
                if not isinstance(value, dict) or segment not in value:
                    return None
                selected_values.append(value[segment])
            values = selected_values
        return ("values", values, origin)

    def result_kind(shape: tuple[str, Any, str]) -> str | None:
        representation, payload, _origin = shape
        if representation == "schema":
            return _schema_value_kind(payload)
        if representation in {"contract", "contract-list"}:
            return (
                "array"
                if representation == "contract-list"
                else _contract_value_kind(payload)
            )
        if not isinstance(payload, list) or not payload:
            return None
        kinds = {_canonical_value_kind(value) for value in payload}
        return kinds.pop() if len(kinds) == 1 else None

    for recipe in recipes:
        bindings: dict[str, tuple[str, Any, str]] = {}
        for binding in recipe["bindings"]:
            shape = term_shape(binding["source"], bindings)
            if shape is None:
                return False
            representation, payload, origin = shape
            if representation == "schema":
                if (
                    not isinstance(payload, dict)
                    or payload.get("type") != "array"
                    or not isinstance(payload.get("items"), dict)
                ):
                    return False
                bindings[binding["name"]] = ("schema", payload["items"], origin)
            elif representation in {"contract", "contract-list"}:
                if representation == "contract-list":
                    item_contract = payload
                elif payload.get("type") == "string-list":
                    item_contract = {"type": "non-empty-string"}
                else:
                    item_contract = payload.get("items")
                if not isinstance(item_contract, dict):
                    return False
                bindings[binding["name"]] = ("contract", item_contract, origin)
            else:
                if (
                    not isinstance(payload, list)
                    or not payload
                    or not all(isinstance(value, list) for value in payload)
                ):
                    return False
                bindings[binding["name"]] = (
                    "values",
                    [item for value in payload for item in value],
                    origin,
                )
        for predicate in recipe["predicates"]:
            left = term_shape(predicate["left"], bindings)
            right = term_shape(predicate["right"], bindings)
            if (
                left is None
                or right is None
                or result_kind(left) is None
                or result_kind(left) != result_kind(right)
            ):
                return False
        for field in recipe["fields"]:
            shape = term_shape(field["term"], bindings)
            if (
                shape is None
                or result_kind(shape) != "string"
                or (field["pointer"] and shape[2] != "source")
            ):
                return False

    for equivalence in resolution_contract["routing_equivalences"]:
        recipe = recipe_by_id.get(equivalence["recipe"])
        if recipe is None:
            return False
        if equivalence["subject_kind"] == "binding-source":
            matches = [
                binding["source"]
                for binding in recipe["bindings"]
                if binding["name"] == equivalence["subject"]
            ]
        else:
            matches = [
                field["term"]
                for field in recipe["fields"]
                if field["name"] == equivalence["subject"]
            ]
        if len(matches) != 1 or not matches[0]["path"]:
            return False
        expected = (
            ".".join(matches[0]["path"])
            if equivalence["projection"] == "dot-path"
            else matches[0]["path"][-1]
        )
        if profile.get(equivalence["profile_member"]) != expected:
            return False
    return True


def _relation_recipes_are_closed(
    profile: dict[str, Any],
    resolution_contract: dict[str, Any],
    language_bundle: dict[str, Any],
    package_release_contract: dict[str, Any],
) -> bool:
    recipes = profile.get("relation_recipes")
    schemas = resolution_contract.get("relation_schemas")
    recipe_format = resolution_contract.get("relation_recipe_format")
    if (
        not isinstance(recipes, list)
        or not isinstance(schemas, list)
        or not isinstance(recipe_format, dict)
        or [item.get("id") for item in recipes if isinstance(item, dict)]
        != [item.get("id") for item in schemas if isinstance(item, dict)]
    ):
        return False
    allowed_sources = set(
        cast(list[str], recipe_format.get("binding_source_roots", []))
    )
    allowed_terms = set(cast(list[str], recipe_format.get("term_roots", [])))
    allowed_predicates = set(
        cast(list[str], recipe_format.get("predicate_operators", []))
    )

    def term_is_closed(
        term: Any,
        bindings: set[str],
        *,
        allowed_roots: set[str],
    ) -> bool:
        if not isinstance(term, dict) or not isinstance(term.get("root"), str):
            return False
        root = term["root"]
        expected = (
            {"root", "path", "binding"}
            if root == "binding"
            else {
                "root",
                "path",
            }
        )
        return (
            root in allowed_roots
            and set(term) == expected
            and isinstance(term.get("path"), list)
            and all(isinstance(segment, str) and segment for segment in term["path"])
            and (
                root != "binding"
                or (
                    isinstance(term.get("binding"), str) and term["binding"] in bindings
                )
            )
        )

    for recipe, schema in zip(recipes, schemas, strict=True):
        if (
            not isinstance(recipe, dict)
            or not isinstance(schema, dict)
            or set(recipe) != {"id", "bindings", "predicates", "fields"}
            or recipe.get("id") != schema.get("id")
            or not isinstance(recipe.get("bindings"), list)
            or not isinstance(recipe.get("predicates"), list)
            or not isinstance(recipe.get("fields"), list)
        ):
            return False
        bindings: set[str] = set()
        for binding in recipe["bindings"]:
            if (
                not isinstance(binding, dict)
                or set(binding) != {"name", "source"}
                or not isinstance(binding.get("name"), str)
                or not binding["name"]
                or binding["name"] in bindings
                or not term_is_closed(
                    binding.get("source"),
                    bindings,
                    allowed_roots=allowed_sources,
                )
            ):
                return False
            bindings.add(binding["name"])
        for predicate in recipe["predicates"]:
            if (
                not isinstance(predicate, dict)
                or set(predicate) != {"operator", "left", "right"}
                or predicate.get("operator") not in allowed_predicates
                or not term_is_closed(
                    predicate.get("left"),
                    bindings,
                    allowed_roots=allowed_terms,
                )
                or not term_is_closed(
                    predicate.get("right"),
                    bindings,
                    allowed_roots=allowed_terms,
                )
            ):
                return False
        schema_fields = schema.get("fields")
        pointer_fields = schema.get("pointer_fields")
        if (
            not isinstance(schema_fields, list)
            or not isinstance(pointer_fields, list)
            or [
                field.get("name")
                for field in recipe["fields"]
                if isinstance(field, dict)
            ]
            != schema_fields
            or any(
                not isinstance(field, dict)
                or set(field) != {"name", "term", "pointer"}
                or field.get("pointer") != (field.get("name") in pointer_fields)
                or not term_is_closed(
                    field.get("term"),
                    bindings,
                    allowed_roots=allowed_terms,
                )
                for field in recipe["fields"]
            )
        ):
            return False
    return _relation_recipe_paths_are_typed(
        profile,
        language_bundle,
        resolution_contract,
        package_release_contract,
    )


def _semantic_element_contract(
    authority_path: str, language_definitions: dict[str, Any]
) -> dict[str, Any] | None:
    parts = authority_path.split(".")
    if len(parts) == 2 and parts[0] == "language":
        collections = language_definitions.get("collections")
        contract = collections.get(parts[1]) if isinstance(collections, dict) else None
    elif len(parts) == 3 and parts[:2] == ["language", "quantity"]:
        quantity = language_definitions.get("quantity")
        collections = (
            quantity.get("collections") if isinstance(quantity, dict) else None
        )
        contract = collections.get(parts[2]) if isinstance(collections, dict) else None
    else:
        return None
    if not isinstance(contract, dict):
        return None
    item_type = contract.get("item_type")
    return {"type": item_type} if isinstance(item_type, str) else contract


def _definition_contract_at_path(
    contract: dict[str, Any], path: list[str]
) -> dict[str, Any] | None:
    selected = contract
    for segment in path:
        field_types = selected.get("field_types")
        if not isinstance(field_types, dict):
            return None
        child = field_types.get(segment)
        if not isinstance(child, dict):
            return None
        selected = child
    return selected


def _contract_assignable_to_schema(contract: dict[str, Any], schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    if "const" in contract:
        value = contract["const"]
        if "const" in schema and schema["const"] != value:
            return False
        if isinstance(schema.get("enum"), list) and value not in schema["enum"]:
            return False
        expected = _canonical_value_kind(value)
        actual = schema.get("type")
        return actual is None or actual == expected
    value_type = contract.get("type")
    if value_type in {"inventory-member", "non-empty-string", "string"}:
        return schema.get("type") == "string"
    if value_type in {"positive-signed-int64", "signed-int64"}:
        return schema.get("type") == "integer"
    if value_type == "boolean":
        return schema.get("type") == "boolean"
    if value_type == "string-list":
        return (
            schema.get("type") == "array"
            and isinstance(schema.get("items"), dict)
            and schema["items"].get("type") == "string"
        )
    if value_type == "list-of":
        item = contract.get("items")
        return (
            schema.get("type") == "array"
            and isinstance(item, dict)
            and _contract_assignable_to_schema(item, schema.get("items"))
        )
    is_object = value_type == "closed-object" or (
        value_type is None
        and isinstance(contract.get("required_members"), list)
        and isinstance(contract.get("field_types"), dict)
    )
    if is_object:
        required = contract.get("required_members")
        fields = contract.get("field_types")
        properties = schema.get("properties")
        schema_required = schema.get("required")
        return (
            schema.get("type") == "object"
            and isinstance(required, list)
            and isinstance(fields, dict)
            and isinstance(properties, dict)
            and isinstance(schema_required, list)
            and set(required) == set(fields)
            and set(fields) == set(properties)
            and set(schema_required) == set(required)
            and schema.get("unevaluatedProperties") is False
            and all(
                _contract_assignable_to_schema(fields[name], properties[name])
                for name in fields
            )
        )
    return False


def _schema_items_match(source: Any, target: Any) -> bool:
    return isinstance(source, dict) and isinstance(target, dict) and source == target


def _runtime_projection_is_closed(
    profile: Any,
    contract: Any,
    language_bundle: dict[str, Any],
    declaration_fields: dict[str, Any],
    language_definitions: dict[str, Any],
) -> bool:
    if (
        not isinstance(profile, dict)
        or set(profile) != {"outputs", "collections", "seeds", "edges"}
        or not isinstance(contract, dict)
        or set(contract)
        != {
            "closed",
            "collection_source_kinds",
            "output_shapes",
            "seed_operators",
            "edge_operators",
            "output_kinds",
            "collection",
            "seed",
            "edge",
            "path_typing",
            "output_typing",
            "resource_accounting",
        }
        or contract.get("closed") is not True
    ):
        return False
    source_kinds = set(cast(list[Any], contract.get("collection_source_kinds", [])))
    output_shapes = set(cast(list[Any], contract.get("output_shapes", [])))
    seed_operators = set(cast(list[Any], contract.get("seed_operators", [])))
    edge_operators = set(cast(list[Any], contract.get("edge_operators", [])))
    output_kinds = set(cast(list[Any], contract.get("output_kinds", [])))
    if (
        source_kinds != {"lock-member", "semantic-closure"}
        or output_shapes
        != {"as-is", "package-definition", "definition", "closure-only"}
        or seed_operators != {"declaration-field"}
        or edge_operators != {"equal"}
        or output_kinds
        != {
            "selected-packages",
            "selected-semantic-closures",
        }
        or contract.get("collection")
        != {
            "required_members": ["id", "source", "output_member", "output_shape"],
            "lock_source_members": ["kind", "member", "package_path"],
            "closure_source_members": ["kind", "authority_path"],
        }
        or contract.get("seed")
        != {
            "required_members": [
                "operator",
                "collection",
                "declaration_path",
                "declaration_package_path",
                "target_path",
            ],
            "match": "canonical-equality",
            "cardinality": "at-least-one",
        }
        or contract.get("edge")
        != {
            "required_members": [
                "operator",
                "source_collection",
                "source_path",
                "target_collection",
                "target_path",
                "same_package",
            ],
            "match": "canonical-equality",
            "cardinality": "at-least-one",
        }
        or contract.get("path_typing")
        != {
            "declaration": "terminal-fact-contract",
            "lock": "package-lock-wire-schema",
            "semantic_closure": "kernel-language-definition-contract",
            "empty_path": "identity",
        }
        or contract.get("output_typing")
        != {
            "source": "collection-element-contract",
            "target": "rir-selected-semantics-member-schema",
            "shape_transforms": {
                "as-is": "identity",
                "definition": "identity",
                "package-definition": "package-and-definition-object",
                "closure-only": "no-output",
            },
        }
        or contract.get("resource_accounting")
        != {
            "limit_member": "max_runtime_projection_steps",
            "counter_scope": "per-runtime-projection",
            "charged_events": [
                "catalog-row",
                "seed-candidate",
                "edge-source",
                "edge-target",
                "collection-output-row",
                "explicit-output-row",
            ],
            "exhaustion_reason": {
                "stage": "static",
                "operation": "greater-than",
                "limit_path": "resources.max_runtime_projection_steps",
            },
        }
    ):
        return False

    def path_is_closed(path: Any, *, empty: bool = False) -> bool:
        return (
            isinstance(path, list)
            and (empty or bool(path))
            and all(isinstance(segment, str) and segment for segment in path)
        )

    outputs = profile.get("outputs")
    collections = profile.get("collections")
    seeds = profile.get("seeds")
    edges = profile.get("edges")
    if (
        not isinstance(outputs, list)
        or not isinstance(collections, list)
        or not isinstance(seeds, list)
        or not isinstance(edges, list)
    ):
        return False
    output_members: list[str] = []
    for output in outputs:
        if not isinstance(output, dict) or output.get("kind") not in output_kinds:
            return False
        kind = output["kind"]
        expected = {
            "kind",
            "source_member",
            "output_member",
            "package_member",
        }
        if kind == "selected-packages":
            expected.add("members")
        elif kind == "selected-semantic-closures":
            expected.update(
                {
                    "entries_member",
                    "authority_path_member",
                    "definitions_member",
                }
            )
        if (
            set(output) != expected
            or any(
                not isinstance(output.get(member), str) or not output[member]
                for member in expected - {"kind", "members"}
            )
            or (
                "members" in output
                and (
                    not isinstance(output["members"], list)
                    or not output["members"]
                    or not all(
                        isinstance(member, str) and member
                        for member in output["members"]
                    )
                    or len(output["members"]) != len(set(output["members"]))
                )
            )
        ):
            return False
        output_members.append(output["output_member"])

    collection_ids: list[str] = []
    authority_paths: set[str] = set()
    for collection in collections:
        if (
            not isinstance(collection, dict)
            or set(collection) != {"id", "source", "output_member", "output_shape"}
            or not isinstance(collection.get("id"), str)
            or not collection["id"]
            or not isinstance(collection.get("source"), dict)
            or collection.get("output_shape") not in output_shapes
            or (
                collection["output_shape"] == "closure-only"
                and collection.get("output_member") is not None
            )
            or (
                collection["output_shape"] != "closure-only"
                and (
                    not isinstance(collection.get("output_member"), str)
                    or not collection["output_member"]
                )
            )
        ):
            return False
        source = collection["source"]
        if source.get("kind") == "lock-member":
            if (
                set(source) != {"kind", "member", "package_path"}
                or not isinstance(source.get("member"), str)
                or not source["member"]
                or not path_is_closed(source.get("package_path"))
            ):
                return False
        elif source.get("kind") == "semantic-closure":
            if (
                set(source) != {"kind", "authority_path"}
                or not isinstance(source.get("authority_path"), str)
                or not source["authority_path"]
            ):
                return False
            authority_paths.add(source["authority_path"])
        else:
            return False
        collection_ids.append(collection["id"])
        if collection["output_member"] is not None:
            output_members.append(collection["output_member"])
    if len(collection_ids) != len(set(collection_ids)):
        return False
    collection_names = set(collection_ids)

    for seed in seeds:
        if not isinstance(seed, dict) or seed.get("operator") not in seed_operators:
            return False
        expected = {
            "operator",
            "collection",
            "declaration_path",
            "declaration_package_path",
            "target_path",
        }
        if (
            set(seed) != expected
            or seed.get("collection") not in collection_names
            or not path_is_closed(seed.get("declaration_package_path"))
            or not path_is_closed(seed.get("declaration_path"))
            or not path_is_closed(seed.get("target_path"), empty=True)
        ):
            return False
    for edge in edges:
        if (
            not isinstance(edge, dict)
            or set(edge)
            != {
                "operator",
                "source_collection",
                "source_path",
                "target_collection",
                "target_path",
                "same_package",
            }
            or edge.get("operator") not in edge_operators
            or edge.get("source_collection") not in collection_names
            or edge.get("target_collection") not in collection_names
            or not path_is_closed(edge.get("source_path"), empty=True)
            or not path_is_closed(edge.get("target_path"), empty=True)
            or not isinstance(edge.get("same_package"), bool)
        ):
            return False
    if len(output_members) != len(set(output_members)):
        return False
    language = language_bundle.get("language")
    wire_schemas = (
        language.get("artifact_wire_schemas") if isinstance(language, dict) else None
    )
    if not isinstance(wire_schemas, list):
        return False
    rir_schemas = [
        item.get("schema")
        for item in wire_schemas
        if isinstance(item, dict)
        and item.get("artifact_kind") == "rir-semantic-payload"
    ]
    if len(rir_schemas) != 1 or not isinstance(rir_schemas[0], dict):
        return False
    selected_schema = (
        rir_schemas[0].get("properties", {}).get("selected_semantics")
        if isinstance(rir_schemas[0].get("properties"), dict)
        else None
    )
    required_outputs = (
        selected_schema.get("required") if isinstance(selected_schema, dict) else None
    )
    selected_properties = (
        selected_schema.get("properties") if isinstance(selected_schema, dict) else None
    )
    packages = language.get("packages") if isinstance(language, dict) else None
    lock_schemas = [
        item.get("schema")
        for item in wire_schemas
        if isinstance(item, dict) and item.get("artifact_kind") == "package-lock"
    ]
    if not (
        isinstance(required_outputs, list)
        and set(output_members) == set(required_outputs)
        and isinstance(selected_properties, dict)
        and isinstance(packages, list)
        and all(
            authority_paths
            <= {
                entry.get("authority_path")
                for entry in package.get("semantic_closure", [])
                if isinstance(entry, dict)
            }
            for package in packages
            if isinstance(package, dict)
        )
        and len(lock_schemas) == 1
        and isinstance(lock_schemas[0], dict)
        and isinstance(lock_schemas[0].get("properties"), dict)
    ):
        return False
    lock_properties = lock_schemas[0]["properties"]

    def fact_contract(path: list[str]) -> dict[str, Any] | None:
        if not path or path[0] not in declaration_fields:
            return None
        selected = declaration_fields[path[0]]
        for segment in path[1:]:
            if (
                not isinstance(selected, dict)
                or selected.get("type") != "closed-object"
                or not isinstance(selected.get("field_types"), dict)
                or segment not in selected["field_types"]
            ):
                return None
            selected = selected["field_types"][segment]
        return selected if isinstance(selected, dict) else None

    def contract_kind(value: dict[str, Any] | None) -> str | None:
        if value is None:
            return None
        kind = value.get("type")
        if kind in {"non-empty-string", "inventory-member"}:
            return "string"
        if kind in {"closed-object", "closed-int64-interval"}:
            return "object"
        if kind in {"signed-int64", "positive-signed-int64"}:
            return "integer"
        if kind == "boolean":
            return "boolean"
        return None

    collection_shapes: dict[str, tuple[str, Any]] = {}
    for collection in collections:
        source = collection["source"]
        if source["kind"] == "lock-member":
            member_schema = lock_properties.get(source["member"])
            if (
                not isinstance(member_schema, dict)
                or member_schema.get("type") != "array"
                or not isinstance(member_schema.get("items"), dict)
                or _schema_value_kind(
                    _json_schema_path(
                        member_schema["items"],
                        source["package_path"],
                    )
                )
                != "string"
            ):
                return False
            collection_shapes[collection["id"]] = (
                "schema",
                member_schema["items"],
            )
        else:
            element_contract = _semantic_element_contract(
                source["authority_path"], language_definitions
            )
            if element_contract is None:
                return False
            collection_shapes[collection["id"]] = ("contract", element_contract)

    def projected_kind(shape: tuple[str, Any], path: list[str]) -> str | None:
        representation, payload = shape
        if representation == "schema":
            selected = _json_schema_path(payload, path)
            return _schema_value_kind(selected)
        selected = _definition_contract_at_path(payload, path)
        return _contract_value_kind(selected)

    for seed in seeds:
        declaration_kind = contract_kind(fact_contract(seed["declaration_path"]))
        package_kind = contract_kind(fact_contract(seed["declaration_package_path"]))
        target_kind = projected_kind(
            collection_shapes[seed["collection"]],
            seed["target_path"],
        )
        if (
            declaration_kind is None
            or declaration_kind != target_kind
            or package_kind != "string"
        ):
            return False
    for edge in edges:
        source_kind = projected_kind(
            collection_shapes[edge["source_collection"]],
            edge["source_path"],
        )
        target_kind = projected_kind(
            collection_shapes[edge["target_collection"]],
            edge["target_path"],
        )
        if source_kind is None or source_kind != target_kind:
            return False
    for collection in collections:
        output_member = collection["output_member"]
        if output_member is None:
            continue
        target = selected_properties.get(output_member)
        if (
            not isinstance(target, dict)
            or target.get("type") != "array"
            or not isinstance(target.get("items"), dict)
        ):
            return False
        representation, payload = collection_shapes[collection["id"]]
        shape = collection["output_shape"]
        if representation == "schema":
            if shape != "as-is" or not _schema_items_match(payload, target["items"]):
                return False
        elif shape == "definition":
            if not _contract_assignable_to_schema(payload, target["items"]):
                return False
        elif shape == "package-definition":
            target_item = target["items"]
            properties = target_item.get("properties")
            if not (
                target_item.get("type") == "object"
                and isinstance(properties, dict)
                and set(properties) == {"package", "definition"}
                and set(target_item.get("required", [])) == {"package", "definition"}
                and target_item.get("unevaluatedProperties") is False
                and properties["package"].get("type") == "string"
                and _contract_assignable_to_schema(payload, properties["definition"])
            ):
                return False
        else:
            return False
    for output in outputs:
        source_schema = lock_properties.get(output["source_member"])
        target_schema = selected_properties.get(output["output_member"])
        if (
            not isinstance(source_schema, dict)
            or source_schema.get("type") != "array"
            or not isinstance(source_schema.get("items"), dict)
            or not isinstance(target_schema, dict)
            or target_schema.get("type") != "array"
            or not isinstance(target_schema.get("items"), dict)
            or _schema_value_kind(
                _json_schema_path(
                    source_schema["items"],
                    [output["package_member"]],
                )
            )
            != "string"
        ):
            return False
        if output["kind"] == "selected-packages" and any(
            _json_schema_path(source_schema["items"], [member]) is None
            for member in output["members"]
        ):
            return False
        if output["kind"] == "selected-packages":
            source_properties = source_schema["items"].get("properties")
            target_item = target_schema["items"]
            target_properties = target_item.get("properties")
            members = set(output["members"])
            if not (
                isinstance(source_properties, dict)
                and isinstance(target_properties, dict)
                and set(target_properties) == members
                and set(target_item.get("required", [])) == members
                and target_item.get("unevaluatedProperties") is False
                and all(
                    source_properties[member] == target_properties[member]
                    for member in members
                )
            ):
                return False
        if output["kind"] == "selected-semantic-closures":
            entries = _json_schema_path(
                source_schema["items"],
                [output["entries_member"]],
            )
            if (
                not isinstance(entries, dict)
                or entries.get("type") != "array"
                or not isinstance(entries.get("items"), dict)
                or _schema_value_kind(
                    _json_schema_path(
                        entries["items"],
                        [output["authority_path_member"]],
                    )
                )
                != "string"
                or _json_schema_path(
                    entries["items"],
                    [output["definitions_member"]],
                )
                is None
            ):
                return False
            source_item = source_schema["items"]
            source_properties = source_item.get("properties")
            target_item = target_schema["items"]
            target_properties = target_item.get("properties")
            projected = {output["package_member"], output["entries_member"]}
            if not (
                isinstance(source_properties, dict)
                and isinstance(target_properties, dict)
                and set(target_properties) == projected
                and set(target_item.get("required", [])) == projected
                and target_item.get("unevaluatedProperties") is False
                and all(
                    source_properties[member] == target_properties[member]
                    for member in projected
                )
            ):
                return False
    return True


def _template_selector_is_closed(
    value: Any,
    roots: set[str],
    roles: set[str],
) -> bool:
    if (
        not isinstance(value, dict)
        or set(value) != {"root", "name", "path"}
        or not isinstance(value.get("root"), str)
        or value["root"] not in roots
        or not isinstance(value.get("name"), str)
        or not isinstance(value.get("path"), list)
        or not all(isinstance(part, str) and part for part in value["path"])
    ):
        return False
    return value["root"] != "role" or value["name"] in roles


def _template_primitive_argument_is_closed(
    value: Any,
    contract: dict[str, Any],
    *,
    argument_types: dict[str, dict[str, Any]],
    roots: set[str],
    roles: set[str],
    produced_derived: set[str],
    result_members: set[str],
) -> bool:
    kind = contract["kind"]
    if kind == "selector":
        return _template_selector_is_closed(value, roots, roles)
    if kind == "non-empty-list":
        item = contract.get("item")
        item_contract = argument_types.get(item) if isinstance(item, str) else None
        return (
            isinstance(value, list)
            and bool(value)
            and item_contract is not None
            and all(
                _template_primitive_argument_is_closed(
                    item,
                    item_contract,
                    argument_types=argument_types,
                    roots=roots,
                    roles=roles,
                    produced_derived=produced_derived,
                    result_members=result_members,
                )
                for item in value
            )
        )
    if kind == "role-name":
        return isinstance(value, str) and value in roles
    if kind == "string-list":
        return (
            isinstance(value, list)
            and (contract.get("empty") is True or bool(value))
            and all(isinstance(part, str) and part for part in value)
        )
    if kind == "string":
        return isinstance(value, str) and (contract.get("empty") is True or bool(value))
    if kind == "derived-name":
        return (
            isinstance(value, str)
            and bool(value)
            and (contract.get("fresh") is not True or value not in produced_derived)
        )
    if kind == "model-fact-bindings":
        return (
            isinstance(value, list)
            and (contract.get("cardinality") != "one-or-more" or bool(value))
            and all(
                isinstance(binding, dict)
                and set(binding) == {"result", "source"}
                and isinstance(binding.get("source"), str)
                and binding["source"] in result_members
                and isinstance(binding.get("result"), str)
                and bool(binding["result"])
                and binding["result"] not in produced_derived
                for binding in value
            )
            and len({binding["source"] for binding in value}) == len(value)
            and len({binding["result"] for binding in value}) == len(value)
        )
    if kind == "enum":
        return value in contract.get("values", [])
    if kind == "canonical-json":
        try:
            canonical_bytes(cast(JsonValue, value))
        except (TypeError, ValueError, UnicodeEncodeError):
            return False
        return True
    return False


def _template_primitive_arguments_are_closed(
    arguments: dict[str, Any],
    primitive: dict[str, Any],
    argument_types: dict[str, dict[str, Any]],
    *,
    roots: set[str],
    roles: set[str],
    produced_derived: set[str],
) -> bool:
    declared = primitive.get("argument_types")
    result_members = primitive.get("result_members", [])
    return (
        isinstance(declared, dict)
        and isinstance(result_members, list)
        and set(arguments) == set(primitive.get("argument_members", []))
        and all(
            isinstance(type_id, str)
            and type_id in argument_types
            and _template_primitive_argument_is_closed(
                arguments[name],
                argument_types[type_id],
                argument_types=argument_types,
                roots=roots,
                roles=roles,
                produced_derived=produced_derived,
                result_members=set(result_members),
            )
            for name, type_id in declared.items()
        )
    )


def _template_primitive_evaluation_is_closed(
    primitive: dict[str, Any],
) -> bool:
    """Close the Schema-major host primitive vocabulary without owning profiles."""
    primitive_id = primitive.get("id")
    return isinstance(primitive_id, str) and primitive.get(
        "evaluation"
    ) == TEMPLATE_PRIMITIVE_EVALUATIONS.get(primitive_id)


def _template_admission_profiles_are_closed(
    language_bundle: dict[str, Any],
    meta_format: dict[str, Any],
) -> bool:
    language = language_bundle.get("language")
    contract = meta_format.get("template_admission")
    if not isinstance(language, dict) or not isinstance(contract, dict):
        return False
    if (
        set(contract)
        != {
            "closed",
            "operations",
            "primitive_spec",
            "resource_accounting",
            "role_contract",
            "selector",
        }
        or contract.get("closed") is not True
    ):
        return False
    selector_contract = contract.get("selector")
    accounting = contract.get("resource_accounting")
    operations = contract.get("operations")
    role_contract = contract.get("role_contract")
    primitive_spec = contract.get("primitive_spec")
    if (
        not isinstance(selector_contract, dict)
        or selector_contract != TEMPLATE_SELECTOR_CONTRACT
        or not isinstance(accounting, dict)
        or accounting != TEMPLATE_RESOURCE_ACCOUNTING
        or not isinstance(operations, list)
        or not operations
        or not isinstance(primitive_spec, dict)
        or role_contract
        != {
            "cardinalities": ["exactly-one", "one-or-more"],
            "identifier": "non-empty-string",
        }
    ):
        return False
    role_cardinalities = cast(dict[str, Any], role_contract)["cardinalities"]
    roots = set(cast(list[str], selector_contract["roots"]))
    if (
        set(primitive_spec)
        != {
            "argument_types",
            "canonical_equality",
            "closed",
            "evaluation_order",
            "primitives",
            "version",
        }
        or primitive_spec.get("closed") is not True
        or primitive_spec.get("version") != "template-graph-primitives-v1"
        or primitive_spec.get("evaluation_order") != "profile-order-first-failure"
        or primitive_spec.get("canonical_equality") != "kernel-canonical-bytes"
        or not isinstance(primitive_spec.get("argument_types"), list)
        or not isinstance(primitive_spec.get("primitives"), list)
    ):
        return False
    argument_type_rows = cast(list[Any], primitive_spec["argument_types"])
    if argument_type_rows != TEMPLATE_ARGUMENT_TYPES:
        return False
    argument_types: dict[str, dict[str, Any]] = {}
    allowed_type_members = {
        "cardinality",
        "empty",
        "fresh",
        "id",
        "item",
        "kind",
        "values",
    }
    for row in argument_type_rows:
        if (
            not isinstance(row, dict)
            or not set(row) <= allowed_type_members
            or set(row) < {"id", "kind"}
            or not isinstance(row.get("id"), str)
            or not row["id"]
            or row["id"] in argument_types
            or row.get("kind")
            not in {
                "canonical-json",
                "derived-name",
                "enum",
                "model-fact-bindings",
                "non-empty-list",
                "role-name",
                "selector",
                "string",
                "string-list",
            }
        ):
            return False
        argument_types[row["id"]] = row
    charge_events = {
        row["event"] for row in cast(list[dict[str, str]], accounting["charge_rules"])
    }
    primitive_rows = cast(list[Any], primitive_spec["primitives"])
    primitives_by_id: dict[str, dict[str, Any]] = {}
    evaluation_kinds: set[str] = set()
    for primitive in primitive_rows:
        if (
            not isinstance(primitive, dict)
            or set(primitive)
            not in (
                {
                    "argument_members",
                    "argument_types",
                    "charges",
                    "evaluation",
                    "failure",
                    "id",
                    "result_effect",
                },
                {
                    "argument_members",
                    "argument_types",
                    "charges",
                    "evaluation",
                    "failure",
                    "id",
                    "result_effect",
                    "result_members",
                },
            )
            or not isinstance(primitive.get("id"), str)
            or not primitive["id"]
            or primitive["id"] in primitives_by_id
            or not isinstance(primitive.get("argument_members"), list)
            or not primitive["argument_members"]
            or len(primitive["argument_members"])
            != len(set(primitive["argument_members"]))
            or not isinstance(primitive.get("argument_types"), dict)
            or set(primitive["argument_types"]) != set(primitive["argument_members"])
            or any(
                type_id not in argument_types
                for type_id in primitive["argument_types"].values()
            )
            or primitive.get("result_effect")
            not in {"bind-derived", "bind-model-facts", "preserve-graph"}
            or primitive.get("failure")
            != {"mode": "judgment-diagnostic", "short_circuit": True}
            or not isinstance(primitive.get("charges"), list)
            or "judgment" not in primitive["charges"]
            or len(primitive["charges"]) != len(set(primitive["charges"]))
            or not set(primitive["charges"]) <= charge_events
            or not isinstance(primitive.get("evaluation"), dict)
            or not isinstance(primitive["evaluation"].get("kind"), str)
            or primitive["evaluation"]["kind"] in evaluation_kinds
            or not _template_primitive_evaluation_is_closed(primitive)
        ):
            return False
        result_members = primitive.get("result_members")
        evaluation_kind = primitive["evaluation"]["kind"]
        if (
            (primitive["result_effect"] == "bind-model-facts")
            != (result_members is not None)
            or (
                result_members is not None
                and (
                    not isinstance(result_members, list)
                    or not result_members
                    or len(result_members) != len(set(result_members))
                    or not all(
                        isinstance(member, str) and member for member in result_members
                    )
                )
            )
            or primitive["result_effect"]
            != TEMPLATE_PRIMITIVE_RESULT_EFFECTS.get(evaluation_kind)
            or primitive["charges"] != TEMPLATE_PRIMITIVE_CHARGES.get(evaluation_kind)
            or (
                evaluation_kind == "model-source-admission"
                and result_members
                != ["root_requirements", "resolved_packages", "source_symbols"]
            )
        ):
            return False
        primitives_by_id[primitive["id"]] = primitive
        evaluation_kinds.add(primitive["evaluation"]["kind"])
    if not primitives_by_id:
        return False
    operations_by_id: dict[str, dict[str, Any]] = {}
    for operation in operations:
        if (
            not isinstance(operation, dict)
            or set(operation)
            != {
                "effects",
                "id",
                "input",
                "law",
                "refusals",
                "resources",
                "result",
            }
            or not isinstance(operation.get("id"), str)
            or operation["id"] in operations_by_id
            or operation.get("input") != {"fact_kind": "template-graph"}
            or operation.get("result") != {"fact_kind": "template-graph"}
            or operation.get("effects") != []
            or operation.get("refusals") != ["reason-bound-diagnostic"]
            or not isinstance(operation.get("resources"), list)
            or "max_template_admission_steps" not in operation["resources"]
        ):
            return False
        law = operation.get("law")
        if (
            not isinstance(law, dict)
            or set(law) != {"operator", "primitive"}
            or law.get("operator") != operation["id"]
            or law.get("primitive") not in primitives_by_id
        ):
            return False
        operations_by_id[operation["id"]] = operation
    profiles = language.get("template_admission_profiles")
    diagnostics = {
        item.get("code")
        for item in cast(list[dict[str, Any]], language_bundle.get("diagnostics", []))
        if isinstance(item, dict)
    }
    if not isinstance(profiles, list) or len(profiles) != 1:
        return False
    profile = profiles[0]
    if not isinstance(profile, dict) or set(profile) != {
        "id",
        "judgments",
        "max_steps_path",
        "member_roles",
        "resource_diagnostic",
        "structural_diagnostic",
    }:
        return False
    role_rows = profile.get("member_roles")
    judgments = profile.get("judgments")
    schema_kinds = {
        row.get("artifact_kind")
        for collection in ("wire_schemas", "artifact_wire_schemas")
        for row in cast(list[dict[str, Any]], language.get(collection, []))
        if isinstance(row, dict)
    }
    if (
        not isinstance(role_rows, list)
        or not role_rows
        or len({row.get("role") for row in role_rows if isinstance(row, dict)})
        != len(role_rows)
        or len({row.get("member_kind") for row in role_rows if isinstance(row, dict)})
        != len(role_rows)
        or any(
            not isinstance(row, dict)
            or set(row) != {"cardinality", "member_kind", "required_operations", "role"}
            or row.get("cardinality") not in role_cardinalities
            or not isinstance(row.get("role"), str)
            or not row["role"]
            or not isinstance(row.get("member_kind"), str)
            or not row["member_kind"]
            or row["member_kind"] not in schema_kinds
            or not isinstance(row.get("required_operations"), list)
            or any(
                operation not in operations_by_id
                for operation in row.get("required_operations", [])
            )
            or len(row.get("required_operations", []))
            != len(set(row.get("required_operations", [])))
            for row in role_rows
        )
        or not isinstance(judgments, list)
        or not judgments
        or profile.get("max_steps_path") != accounting.get("limit_path")
        or profile.get("resource_diagnostic") != accounting.get("exhaustion_diagnostic")
        or profile.get("resource_diagnostic") not in diagnostics
        or profile.get("structural_diagnostic") not in diagnostics
    ):
        return False
    roles = {
        row["role"]
        for row in role_rows
        if isinstance(row, dict) and isinstance(row.get("role"), str)
    }
    try:
        limit = _exact_path_value(language_bundle, profile["max_steps_path"])
    except (KeyError, TypeError):
        return False
    if (
        not limit[0]
        or not isinstance(limit[1], int)
        or isinstance(limit[1], bool)
        or limit[1] < 1
    ):
        return False
    judgment_ids: set[str] = set()
    consulted_operations: set[str] = set()
    consulted_primitives: set[str] = set()
    role_operations: set[tuple[str, str]] = set()
    produced_derived: set[str] = set()
    selector_members = {"inventory", "left", "right", "selector", "source", "target"}
    for judgment in judgments:
        if (
            not isinstance(judgment, dict)
            or set(judgment) != {"arguments", "diagnostic", "id", "operation"}
            or not isinstance(judgment.get("id"), str)
            or not judgment["id"]
            or judgment["id"] in judgment_ids
            or judgment.get("diagnostic") not in diagnostics
            or judgment.get("operation") not in operations_by_id
            or not isinstance(judgment.get("arguments"), dict)
        ):
            return False
        operation = operations_by_id[judgment["operation"]]
        law = cast(dict[str, Any], operation["law"])
        primitive = primitives_by_id[law["primitive"]]
        arguments = cast(dict[str, Any], judgment["arguments"])
        if not _template_primitive_arguments_are_closed(
            arguments,
            primitive,
            argument_types,
            roots=roots,
            roles=roles,
            produced_derived=produced_derived,
        ):
            return False
        selectors: list[dict[str, Any]] = []
        for name, value in arguments.items():
            if name in selector_members:
                if not _template_selector_is_closed(value, roots, roles):
                    return False
                selectors.append(value)
            if name == "selectors":
                if (
                    not isinstance(value, list)
                    or not value
                    or not all(
                        _template_selector_is_closed(item, roots, roles)
                        for item in value
                    )
                ):
                    return False
                selectors.extend(value)
            if name.endswith("_path") and (
                not isinstance(value, list)
                or not all(isinstance(part, str) and part for part in value)
            ):
                return False
        for selector in selectors:
            if selector["root"] == "role":
                role_operations.add((selector["name"], judgment["operation"]))
            if (
                selector["root"] == "derived"
                and selector["name"] not in produced_derived
            ):
                return False
        if arguments.get("relation") not in {None, "equal", "subset"}:
            return False
        if arguments.get("outcome") not in {None, "admitted", "refused"}:
            return False
        role = arguments.get("role")
        if role is not None:
            if not isinstance(role, str) or role not in roles:
                return False
            role_operations.add((role, judgment["operation"]))
        evaluation = cast(dict[str, Any], primitive["evaluation"])
        if evaluation["kind"] == "model-source-admission":
            bindings = arguments.get("fact_bindings")
            result_members = primitive.get("result_members")
            if (
                not isinstance(bindings, list)
                or not bindings
                or not isinstance(result_members, list)
                or any(
                    not isinstance(binding, dict)
                    or set(binding) != {"result", "source"}
                    or binding.get("source") not in result_members
                    or not isinstance(binding.get("result"), str)
                    or not binding["result"]
                    for binding in bindings
                )
                or len({binding["source"] for binding in bindings}) != len(bindings)
                or len({binding["result"] for binding in bindings}) != len(bindings)
                or any(binding["result"] in produced_derived for binding in bindings)
            ):
                return False
            produced_derived.update(binding["result"] for binding in bindings)
        if evaluation["kind"] in {
            "concatenate-selections",
            "content-identity",
        }:
            result = arguments.get("result")
            if (
                not isinstance(result, str)
                or not result
                or result in produced_derived
                or (
                    evaluation["kind"] == "content-identity"
                    and (
                        not isinstance(arguments.get("identity_domain"), str)
                        or not arguments["identity_domain"]
                    )
                )
            ):
                return False
            produced_derived.add(result)
        judgment_ids.add(judgment["id"])
        consulted_operations.add(judgment["operation"])
        consulted_primitives.add(law["primitive"])
    required_role_operations = {
        (row["role"], operation)
        for row in role_rows
        if isinstance(row, dict)
        for operation in row["required_operations"]
    }
    return (
        consulted_operations == set(operations_by_id)
        and consulted_primitives == set(primitives_by_id)
        and required_role_operations <= role_operations
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
    if not _template_admission_profiles_are_closed(language_bundle, meta_format):
        return False
    fact_schemas = _fact_schemas(meta_format)
    rules = language.get("rules")
    lowerings = language.get("model_lowerings")
    profiles = language.get("resolution_profiles")
    if (
        not fact_schemas
        or not isinstance(rules, list)
        or not isinstance(lowerings, list)
        or not isinstance(profiles, list)
    ):
        return False
    rules_by_id = {
        rule["id"]: rule
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("id"), str)
    }
    profiles_by_id = {
        profile["id"]: profile
        for profile in profiles
        if isinstance(profile, dict) and isinstance(profile.get("id"), str)
    }
    resolution_contract = meta_format.get("resolution_judgment")
    operation_specs = (
        resolution_contract.get("operations")
        if isinstance(resolution_contract, dict)
        else None
    )
    operation_order = [
        item["id"] for item in operation_specs or [] if isinstance(item, dict)
    ]
    operations_by_id = {
        item["id"]: item
        for item in operation_specs or []
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    reason_stages = {
        item["id"]: item["stage"]
        for item in cast(list[dict[str, Any]], language.get("reasons", []))
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("stage"), str)
    }
    accounting = (
        resolution_contract.get("resource_accounting")
        if isinstance(resolution_contract, dict)
        else None
    )
    exhaustion_reason = (
        accounting.get("exhaustion_reason") if isinstance(accounting, dict) else None
    )
    resource_reasons = [
        item
        for item in cast(list[dict[str, Any]], language.get("reasons", []))
        if isinstance(exhaustion_reason, dict)
        and item.get("stage") == exhaustion_reason.get("stage")
        and isinstance(item.get("predicate"), dict)
        and item["predicate"].get("operation") == exhaustion_reason.get("operation")
        and item["predicate"].get("limit_path") == exhaustion_reason.get("limit_path")
    ]
    runtime_projection_contract = meta_format.get("runtime_projection")
    runtime_accounting = (
        runtime_projection_contract.get("resource_accounting")
        if isinstance(runtime_projection_contract, dict)
        else None
    )
    runtime_exhaustion_reason = (
        runtime_accounting.get("exhaustion_reason")
        if isinstance(runtime_accounting, dict)
        else None
    )
    runtime_resource_reasons = [
        item
        for item in cast(list[dict[str, Any]], language.get("reasons", []))
        if isinstance(runtime_exhaustion_reason, dict)
        and item.get("stage") == runtime_exhaustion_reason.get("stage")
        and isinstance(item.get("predicate"), dict)
        and item["predicate"].get("operation")
        == runtime_exhaustion_reason.get("operation")
        and item["predicate"].get("limit_path")
        == runtime_exhaustion_reason.get("limit_path")
    ]
    if (
        len(profiles_by_id) != len(profiles)
        or not isinstance(resolution_contract, dict)
        or not _resolution_judgment_is_closed(resolution_contract)
        or not isinstance(operation_specs, list)
        or not operation_specs
        or len(operations_by_id) != len(operation_specs)
        or len(resource_reasons) != 1
        or len(runtime_resource_reasons) != 1
        or len([profile for profile in profiles if profile.get("default") is True]) != 1
    ):
        return False
    for profile in profiles:
        chain = profile.get("judgment_chain")
        if (
            not isinstance(chain, list)
            or not _relation_recipes_are_closed(
                profile,
                resolution_contract,
                language_bundle,
                cast(dict[str, Any], meta_format["package_release"]),
            )
            or [item.get("operation") for item in chain if isinstance(item, dict)]
            != operation_order
            or any(
                not isinstance(item, dict)
                or item.get("operation") not in operations_by_id
                or reason_stages.get(item.get("reason"))
                != operations_by_id[item["operation"]].get("stage")
                for item in chain
            )
        ):
            return False
    for lowering in lowerings:
        if not isinstance(lowering, dict):
            return False
        chain = lowering.get("rule_chain")
        equalities = lowering.get("output_equalities")
        profile_id = lowering.get("resolution_profile")
        initial_kind = lowering.get("initial_fact_kind")
        if not isinstance(profile_id, str) or not isinstance(initial_kind, str):
            return False
        profile = profiles_by_id.get(profile_id)
        initial_fields = fact_schemas.get(initial_kind)
        if (
            not isinstance(chain, list)
            or not chain
            or not isinstance(equalities, list)
            or not all(isinstance(item, dict) for item in equalities)
            or not isinstance(profile, dict)
            or not isinstance(initial_fields, dict)
            or profile.get("symbol_fact_member") not in initial_fields
        ):
            return False
        terminal = chain[-1]
        rule = (
            rules_by_id.get(terminal.get("rule"))
            if isinstance(terminal, dict)
            else None
        )
        conclusion = rule.get("conclusion") if isinstance(rule, dict) else None
        kind = conclusion.get("fact_kind") if isinstance(conclusion, dict) else None
        fields = fact_schemas.get(kind) if isinstance(kind, str) else None
        pairs: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        if not isinstance(fields, dict) or not _runtime_projection_is_closed(
            lowering.get("runtime_projection"),
            runtime_projection_contract,
            language_bundle,
            fields,
            cast(dict[str, Any], meta_format["language_definitions"]),
        ):
            return False
        for equality in equalities:
            left = equality.get("left")
            right = equality.get("right")
            if (
                not _fact_contract_path_is_declared(fields, left)
                or not _fact_contract_path_is_declared(fields, right)
                or left == right
            ):
                return False
            left_contract = _fact_contract_at_path(fields, left)
            right_contract = _fact_contract_at_path(fields, right)
            left_kind = _contract_value_kind(left_contract)
            right_kind = _contract_value_kind(right_contract)
            if (
                left_kind is None
                or left_kind != right_kind
                or (
                    left_kind in {"array", "object"} and left_contract != right_contract
                )
            ):
                return False
            pairs.append((tuple(left), tuple(right)))
        if len(pairs) != len(set(pairs)):
            return False
        if not any(left == (profile["symbol_fact_member"],) for left, _ in pairs):
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
    return operation in {"has-duplicate", "invalid-interval", "not-equal"}


def _model_program_vector_is_closed(
    vector: dict[str, Any],
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> bool:
    contract = meta_format.get("model_program_vector")
    if not isinstance(contract, dict):
        return False
    required = contract.get("required_members")
    categories = contract.get("categories")
    category_outcomes = contract.get("category_outcomes")
    category_relations = contract.get("category_relations")
    fixture_modes = contract.get("fixture_modes")
    expect_members = contract.get("expect_members")
    lock_members = contract.get("lock_oracle_members")
    relation_kinds = contract.get("relation_kinds")
    category = vector.get("category")
    fixture = vector.get("source_fixture")
    expect = vector.get("expect")
    if (
        not isinstance(required, list)
        or set(vector) != set(required)
        or not isinstance(vector.get("id"), str)
        or not vector["id"]
        or not isinstance(categories, list)
        or category not in categories
        or not isinstance(category_outcomes, dict)
        or not isinstance(category_relations, dict)
        or not isinstance(fixture_modes, dict)
        or not isinstance(expect_members, list)
        or not isinstance(lock_members, list)
        or not isinstance(relation_kinds, list)
        or not isinstance(fixture, dict)
        or not isinstance(expect, dict)
        or set(expect) != set(expect_members)
    ):
        return False
    mode = fixture.get("mode")
    mode_contract = fixture_modes.get(mode) if isinstance(mode, str) else None
    if (
        not isinstance(mode_contract, dict)
        or not isinstance(mode_contract.get("required_members"), list)
        or set(fixture) != set(mode_contract["required_members"])
        or not isinstance(fixture.get("source"), dict)
    ):
        return False
    if mode == "indexed-repeat":
        collection_path = fixture.get("collection_path")
        count_path = fixture.get("count_resource_path")
        count_offset = fixture.get("count_offset")
        template = fixture.get("template")
        index_member = fixture.get("index_member")
        index_prefix = fixture.get("index_prefix")
        index_width = fixture.get("index_width")
        if (
            not isinstance(collection_path, list)
            or not collection_path
            or not all(isinstance(item, str) and item for item in collection_path)
            or not isinstance(count_path, str)
            or not count_path
            or count_offset not in (0, 1)
            or not isinstance(template, dict)
            or not isinstance(index_member, str)
            or not index_member
            or index_member not in template
            or not isinstance(index_prefix, str)
            or not index_prefix
            or not isinstance(index_width, int)
            or isinstance(index_width, bool)
            or not 1 <= index_width <= 18
            or fixture.get("index_encoding") != mode_contract.get("index_encoding")
        ):
            return False
        current: Any = fixture["source"]
        for segment in collection_path:
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            elif (
                isinstance(current, list)
                and segment.isdecimal()
                and int(segment) < len(current)
            ):
                current = current[int(segment)]
            else:
                return False
        declared, count = _exact_path_value(language_bundle, count_path)
        if (
            not isinstance(current, list)
            or current
            or not declared
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 1
        ):
            return False
    elif mode != "literal":
        return False
    outcome = expect.get("outcome")
    allowed_outcomes = category_outcomes.get(category)
    diagnostics = expect.get("diagnostics")
    semantic_artifacts = expect.get("semantic_artifacts")
    declaration_count = expect.get("declaration_count")
    relation = expect.get("relation")
    if (
        not isinstance(allowed_outcomes, list)
        or outcome not in allowed_outcomes
        or not isinstance(diagnostics, list)
        or not all(
            isinstance(item, dict)
            and set(item) == {"code", "stage"}
            and isinstance(item["code"], str)
            and item["code"]
            and isinstance(item["stage"], str)
            and item["stage"]
            for item in diagnostics
        )
        or not isinstance(semantic_artifacts, bool)
        or not isinstance(declaration_count, int)
        or isinstance(declaration_count, bool)
        or declaration_count < 0
        or not isinstance(relation, dict)
        or set(relation) != {"kind", "reference"}
        or relation.get("kind") not in relation_kinds
        or relation.get("kind") not in category_relations.get(category, [])
    ):
        return False
    catalog = {
        (item.get("code"), item.get("stage"))
        for item in cast(list[dict[str, Any]], language_bundle.get("diagnostics", []))
        if isinstance(item, dict)
    }
    if any((item["code"], item["stage"]) not in catalog for item in diagnostics):
        return False
    reference = relation.get("reference")
    if relation["kind"] == "independent":
        if reference is not None:
            return False
    elif not isinstance(reference, str) or not reference:
        return False
    lock_oracle = expect.get("lock_oracle")
    rir_identity = expect.get("rir_identity")
    debug_map_identity = expect.get("debug_map_identity")
    if outcome == "admitted":
        return (
            semantic_artifacts is True
            and not diagnostics
            and declaration_count > 0
            and isinstance(rir_identity, str)
            and bool(rir_identity)
            and isinstance(debug_map_identity, str)
            and bool(debug_map_identity)
            and isinstance(lock_oracle, dict)
            and set(lock_oracle) == set(lock_members)
        )
    return (
        semantic_artifacts is False
        and bool(diagnostics)
        and declaration_count == 0
        and rir_identity is None
        and debug_map_identity is None
        and lock_oracle is None
    )


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
    if "category" in vector:
        return _model_program_vector_is_closed(vector, meta_format, language_bundle)
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
    admitted_packages: list[dict[str, Any]] = []
    semantic_projection_mismatch = False
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
            admitted_packages.append(package)
            if package.get("content_identity") != _safe_artifact_identity(
                "domain-package-release-v2", package, canonical_encoding
            ):
                refuse("kernel.identity_mismatch", "ingress", subject)
            if not _package_semantic_closure_is_closed(package, package_contract):
                refuse(
                    "kernel.identity_mismatch",
                    "ingress",
                    f"{subject}.semantic_identity",
                )
        semantic_projection_mismatch = len(admitted_packages) == len(
            packages
        ) and not _package_semantic_projections_are_exact(
            admitted_packages, package_contract, language_bundle
        )

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
    program_vectors = [item for item in ldb_vectors if "category" in item]
    program_contract = meta_format.get("model_program_vector")
    expected_categories = (
        program_contract.get("categories")
        if isinstance(program_contract, dict)
        else None
    )
    category_outcomes = (
        program_contract.get("category_outcomes")
        if isinstance(program_contract, dict)
        else None
    )
    program_by_id = {str(item.get("id", "")): item for item in program_vectors}
    program_vectors_close = (
        isinstance(expected_categories, list)
        and isinstance(category_outcomes, dict)
        and set(expected_categories)
        == {str(item.get("category", "")) for item in program_vectors}
        and all(
            {
                str(item.get("expect", {}).get("outcome", ""))
                for item in program_vectors
                if item.get("category") == category
            }
            == set(category_outcomes.get(category, []))
            for category in expected_categories
        )
    )
    if program_vectors_close:
        for vector in program_vectors:
            relation = cast(dict[str, Any], vector["expect"]["relation"])
            if relation["kind"] == "independent":
                continue
            reference = program_by_id.get(str(relation["reference"]))
            if reference is None:
                program_vectors_close = False
                break
            expected = cast(dict[str, Any], vector["expect"])
            reference_expected = cast(dict[str, Any], reference["expect"])
            if (
                expected["lock_oracle"] != reference_expected["lock_oracle"]
                or (
                    relation["kind"] == "semantic-equivalent"
                    and (
                        expected["rir_identity"] != reference_expected["rir_identity"]
                        or expected["debug_map_identity"]
                        == reference_expected["debug_map_identity"]
                    )
                )
                or (
                    relation["kind"] == "semantic-change"
                    and expected["rir_identity"] == reference_expected["rir_identity"]
                )
            ):
                program_vectors_close = False
                break
    if not program_vectors_close:
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language-bundle.model-program-vectors",
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
        vectors_by_id = {str(item.get("id", "")): item for item in ldb_vectors}
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
                and package.get("vector_definitions")
                == [
                    vectors_by_id[vector_id]
                    for vector_id in package.get("vectors", [])
                    if vector_id in vectors_by_id
                ]
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

    if semantic_projection_mismatch and not found:
        for index in range(len(admitted_packages)):
            refuse(
                "kernel.identity_mismatch",
                "ingress",
                f"language-bundle.language.packages.{index}.semantic_identity",
            )

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
    elif operation == "invalid-interval":
        minimum = inp.get("minimum")
        maximum = inp.get("maximum")
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
        ):
            return None
        matched = minimum > maximum
    elif operation == "not-equal":
        try:
            matched = canonical_bytes(
                cast(JsonValue, inp.get("actual"))
            ) != canonical_bytes(cast(JsonValue, inp.get("expected")))
        except (TypeError, ValueError):
            return None
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
    if operation == "invalid-interval":
        if coverage.get(operation) != "both-outcomes":
            return False
        return outcomes == {False, True} and all(
            _value_matches_contract(
                cast(dict[str, Any], vector["input"]).get(name),
                {"type": "signed-int64"},
                language_bundle,
            )
            for vector in vectors
            for name in ("minimum", "maximum")
        )
    if operation == "not-equal":
        if coverage.get(operation) != "both-outcomes":
            return False
        return outcomes == {False, True} and all(
            _value_matches_contract(
                cast(dict[str, Any], vector["input"]).get(name),
                {"type": "canonical-value"},
                language_bundle,
            )
            for vector in vectors
            for name in ("actual", "expected")
        )
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
