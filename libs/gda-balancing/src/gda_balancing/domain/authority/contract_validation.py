"""Shared primitives for closed Authority contract validation."""

import json
import re
from functools import cache
from typing import Any, cast

import jsonschema

from gda_balancing.domain.canonical import JsonValue, canonical_bytes


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


@cache
def _meta_validate_json_schema(
    canonical_schema_bytes: bytes,
    canonical_kernel_schema_profile_bytes: bytes,
) -> bool:
    """Meta-validate one exact production schema/profile cache key."""
    try:
        schema = json.loads(canonical_schema_bytes)
        profile = json.loads(canonical_kernel_schema_profile_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(schema, dict) or not isinstance(profile, dict):
        return False
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError:
        return False
    return True


def reset_schema_meta_validation_cache_for_tests() -> None:
    """Reset only the production cache domain for deterministic regressions."""
    _meta_validate_json_schema.cache_clear()


def schema_meta_validation_cache_info() -> Any:
    """Expose cache counters to performance regression tests."""
    return _meta_validate_json_schema.cache_info()


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
        schema_bytes = canonical_bytes(cast(JsonValue, value))
        profile_bytes = canonical_bytes(cast(JsonValue, contract))
    except (TypeError, ValueError, UnicodeEncodeError):
        return False
    if not _meta_validate_json_schema(schema_bytes, profile_bytes):
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
        if not isinstance(value, str) or not value:
            return False
        pattern = contract.get("pattern")
        if pattern is None:
            return True
        if not isinstance(pattern, str):
            return False
        try:
            return re.fullmatch(pattern, value) is not None
        except re.error:
            return False
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
    if value_type == "closed-discriminated-object":
        discriminator = contract.get("discriminator")
        variants = contract.get("variants")
        if (
            not isinstance(value, dict)
            or not isinstance(discriminator, str)
            or not discriminator
            or not isinstance(variants, dict)
            or not variants
        ):
            return False
        variant = variants.get(value.get(discriminator))
        return isinstance(variant, dict) and _value_matches_contract(
            value, variant, language_bundle
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
