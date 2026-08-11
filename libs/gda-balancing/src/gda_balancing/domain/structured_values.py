"""Authority-driven Standard Schema structured values.

This module executes the closed Enum, Record, List, and Ref contracts from an
admitted Language Definition Bundle. It does not own nominal type definitions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, cast

from gda_balancing.domain.canonical import JsonValue, canonical_bytes


_TypeKey = tuple[str, str, str]


@dataclass(frozen=True)
class StructuredValueAuthority:
    """The selected machine rules needed to admit structured values."""

    constructors: dict[str, dict[str, Any]]
    types: dict[_TypeKey, dict[str, Any]]
    typed_envelope_profile: dict[str, Any] | None


@dataclass(frozen=True)
class StructuredValueFault(Exception):
    """A deterministic refusal while admitting or operating on a typed value."""

    code: str
    pointer: str


@dataclass
class _Budget:
    remaining: int

    def consume(self, pointer: str) -> None:
        if self.remaining < 1:
            raise StructuredValueFault(
                "language.structured_value_resource_exhausted", pointer
            )
        self.remaining -= 1


def _semantic_definitions(
    package: dict[str, Any], authority_path: str
) -> list[dict[str, Any]]:
    matches = [
        entry.get("definitions")
        for entry in cast(list[dict[str, Any]], package.get("semantic_closure", []))
        if entry.get("authority_path") == authority_path
    ]
    if len(matches) != 1 or not isinstance(matches[0], list):
        raise ValueError(f"admitted package is missing {authority_path}")
    return cast(list[dict[str, Any]], matches[0])


def _typed_envelope_profile(profiles: Iterable[dict[str, Any]]) -> dict[str, Any]:
    matches = [
        profile
        for profile in profiles
        if profile.get("source_kind") == "typed-envelope"
        and profile.get("value_kind") == "nominal-structured"
    ]
    if len(matches) != 1:
        raise ValueError("admitted language has no unique typed-envelope profile")
    admission = matches[0].get("admission")
    if admission != {
        "envelope_members": ["type", "value"],
        "operator": "recursive-typed-envelope",
        "resource_charge_per_node": 1,
        "type_relation": "exact-selected-type",
    }:
        raise ValueError("typed-envelope admission law is unsupported")
    return matches[0]


def _selected_typed_envelope_profile(
    profiles: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    selected = list(profiles)
    if not any(
        profile.get("source_kind") == "typed-envelope"
        and profile.get("value_kind") == "nominal-structured"
        for profile in selected
    ):
        return None
    return _typed_envelope_profile(selected)


def package_structured_value_authority(
    package_releases: Iterable[dict[str, Any]],
) -> StructuredValueAuthority:
    """Project structured-value rules from admitted Package Releases."""
    packages = list(package_releases)
    constructors: dict[str, dict[str, Any]] = {}
    definitions: dict[_TypeKey, dict[str, Any]] = {}
    profiles: list[dict[str, Any]] = []
    for package in packages:
        for constructor in _semantic_definitions(package, "language.constructors"):
            constructor_id = cast(str, constructor["id"])
            if constructor_id in constructors:
                raise ValueError("admitted constructor identity is duplicated")
            constructors[constructor_id] = constructor
        profiles.extend(
            _semantic_definitions(package, "language.literal_typing_profiles")
        )
        exports = cast(dict[str, Any], package.get("exports", {}))
        for exported_type in cast(list[dict[str, Any]], exports.get("types", [])):
            key = (
                cast(str, package["id"]),
                cast(str, package["version"]),
                cast(str, exported_type["id"]),
            )
            if key in definitions:
                raise ValueError("admitted type identity is duplicated")
            definitions[key] = {
                **exported_type,
                "package": package["id"],
                "version": package["version"],
            }
    for package in packages:
        for definition in _semantic_definitions(package, "language.nominal_types"):
            key = (
                cast(str, definition["package"]),
                cast(str, definition["version"]),
                cast(str, definition["id"]),
            )
            if key not in definitions:
                raise ValueError("nominal definition has no exported type")
            definitions[key] = definition
    return StructuredValueAuthority(
        constructors=constructors,
        types=definitions,
        typed_envelope_profile=_typed_envelope_profile(profiles),
    )


def language_structured_value_authority(
    language_bundle: dict[str, Any],
) -> StructuredValueAuthority:
    """Index structured-value rules from an admitted Language Definition Bundle."""
    language = language_bundle.get("language")
    if not isinstance(language, dict):
        raise ValueError("admitted language content is unavailable")
    packages = cast(list[dict[str, Any]], language.get("packages"))
    package_versions = {
        cast(str, package["id"]): cast(str, package["version"]) for package in packages
    }
    definitions: dict[_TypeKey, dict[str, Any]] = {}
    for package in packages:
        exports = cast(dict[str, Any], package["exports"])
        for exported_type in cast(list[dict[str, Any]], exports.get("types", [])):
            key = (
                cast(str, package["id"]),
                cast(str, package["version"]),
                cast(str, exported_type["id"]),
            )
            definitions[key] = {
                **exported_type,
                "package": package["id"],
                "version": package["version"],
            }
    rows = language.get("nominal_types")
    if not isinstance(rows, (list, tuple)):
        raise ValueError("admitted language has no nominal type collection")
    for definition in cast(Iterable[dict[str, Any]], rows):
        key = (
            cast(str, definition["package"]),
            cast(str, definition["version"]),
            cast(str, definition["id"]),
        )
        if key not in definitions or package_versions.get(key[0]) != key[1]:
            raise ValueError("nominal definition has no selected exported type")
        definitions[key] = definition
    constructors = {
        cast(str, constructor["id"]): constructor
        for constructor in cast(list[dict[str, Any]], language.get("constructors"))
    }
    return StructuredValueAuthority(
        constructors=constructors,
        types=definitions,
        typed_envelope_profile=_typed_envelope_profile(
            cast(list[dict[str, Any]], language.get("literal_typing_profiles"))
        ),
    )


def selected_structured_value_authority(
    selected_semantics: dict[str, Any],
) -> StructuredValueAuthority:
    """Index only the structured-value rules carried by admitted RIR semantics."""
    package_versions = {
        cast(str, package["id"]): cast(str, package["version"])
        for package in cast(list[dict[str, Any]], selected_semantics["packages"])
    }
    definitions: dict[_TypeKey, dict[str, Any]] = {}
    for exported_type in cast(list[dict[str, Any]], selected_semantics["types"]):
        package = cast(str, exported_type["package"])
        definitions[(package, package_versions[package], exported_type["id"])] = {
            **exported_type,
            "version": package_versions[package],
        }
    for row in cast(list[dict[str, Any]], selected_semantics["nominal_types"]):
        definition = cast(dict[str, Any], row["definition"])
        key = (
            cast(str, definition["package"]),
            cast(str, definition["version"]),
            cast(str, definition["id"]),
        )
        if key not in definitions:
            raise ValueError("RIR nominal definition has no selected exported type")
        definitions[key] = definition
    constructors = {
        cast(str, constructor["id"]): constructor
        for constructor in cast(
            list[dict[str, Any]], selected_semantics["constructors"]
        )
    }
    profiles = [
        cast(dict[str, Any], row["definition"])
        for row in cast(
            list[dict[str, Any]], selected_semantics["literal_typing_profiles"]
        )
    ]
    return StructuredValueAuthority(
        constructors=constructors,
        types=definitions,
        typed_envelope_profile=_selected_typed_envelope_profile(profiles),
    )


def _nominal_key(type_expression: Any) -> tuple[str, str, str] | None:
    if not isinstance(type_expression, dict):
        return None
    if set(type_expression) == {"package", "version", "id"} or (
        set(type_expression) == {"kind", "package", "version", "id"}
        and type_expression.get("kind") == "nominal"
    ):
        values = tuple(
            type_expression.get(name) for name in ("package", "version", "id")
        )
        if all(isinstance(value, str) and value for value in values):
            return cast(tuple[str, str, str], values)
    return None


def _member_pointer(pointer: str, member: str | int) -> str:
    escaped = str(member).replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{escaped}"


def _canonical_type_expression(type_expression: Any) -> JsonValue:
    """Normalize equivalent nominal spellings at public value boundaries."""
    nominal = _nominal_key(type_expression)
    if nominal is not None:
        package, version, type_id = nominal
        return {"id": type_id, "package": package, "version": version}
    if not isinstance(type_expression, dict):
        if isinstance(type_expression, list):
            return cast(
                JsonValue,
                [_canonical_type_expression(item) for item in type_expression],
            )
        return cast(JsonValue, type_expression)
    return cast(
        JsonValue,
        {
            member: _canonical_type_expression(value)
            for member, value in type_expression.items()
        },
    )


def _validate(
    type_expression: Any,
    value: Any,
    authority: StructuredValueAuthority,
    budget: _Budget,
    pointer: str,
) -> JsonValue:
    if authority.typed_envelope_profile is None:
        raise ValueError("RIR selected semantics omit the typed-envelope profile")
    charge = cast(
        int, authority.typed_envelope_profile["admission"]["resource_charge_per_node"]
    )
    for _ in range(charge):
        budget.consume(pointer)
    nominal_key = _nominal_key(type_expression)
    if nominal_key is not None:
        type_definition = authority.types.get(nominal_key)
        if type_definition is None:
            raise StructuredValueFault(
                "language.structured_value_type_mismatch", pointer
            )
        constructor_id = type_definition.get("constructor")
        constructor = (
            authority.constructors.get(constructor_id)
            if isinstance(constructor_id, str)
            else None
        )
        if constructor is None:
            raise StructuredValueFault(
                "language.structured_value_type_mismatch", pointer
            )
        if "definition" in type_definition:
            return _validate(
                type_definition["definition"], value, authority, budget, pointer
            )
        value_rule = cast(dict[str, Any], constructor.get("value_rule"))
        if value_rule.get("operator") != "exact-integer" or (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not cast(int, value_rule["minimum"])
            <= value
            <= cast(int, value_rule["maximum"])
        ):
            raise StructuredValueFault(
                "language.structured_value_type_mismatch", pointer
            )
        return value
    if not isinstance(type_expression, dict):
        raise StructuredValueFault("language.structured_value_type_mismatch", pointer)
    kind = type_expression.get("kind")
    matches = [
        constructor
        for constructor in authority.constructors.values()
        if cast(dict[str, Any], constructor.get("value_rule", {})).get(
            "definition_kind"
        )
        == kind
    ]
    if len(matches) != 1:
        raise StructuredValueFault("language.structured_value_type_mismatch", pointer)
    rule = cast(dict[str, Any], matches[0]["value_rule"])
    operator = rule.get("operator")
    if operator == "enum-member":
        members = type_expression.get(cast(str, rule["members_member"]))
        if not isinstance(value, str) or value not in cast(list[Any], members):
            raise StructuredValueFault(
                "language.structured_value_unknown_enum", pointer
            )
        return value
    if operator == "closed-record":
        fields = type_expression.get(cast(str, rule["fields_member"]))
        if not isinstance(fields, list) or not isinstance(value, dict):
            raise StructuredValueFault(
                "language.structured_value_type_mismatch", pointer
            )
        name_member = cast(str, rule["field_name_member"])
        type_member = cast(str, rule["field_type_member"])
        expected = [row.get(name_member) for row in fields if isinstance(row, dict)]
        if len(expected) != len(fields) or any(
            not isinstance(name, str) or not name for name in expected
        ):
            raise ValueError("admitted Record definition is malformed")
        missing = [name for name in expected if name not in value]
        extra = sorted(
            (name for name in value if name not in expected),
            key=lambda name: str(name).encode("utf-8"),
        )
        if missing:
            raise StructuredValueFault(
                "language.structured_value_record_member_mismatch",
                _member_pointer(pointer, cast(str, missing[0])),
            )
        if extra:
            raise StructuredValueFault(
                "language.structured_value_record_member_mismatch",
                _member_pointer(pointer, extra[0]),
            )
        return cast(
            JsonValue,
            {
                cast(str, field[name_member]): _validate(
                    field[type_member],
                    value[field[name_member]],
                    authority,
                    budget,
                    _member_pointer(pointer, cast(str, field[name_member])),
                )
                for field in fields
            },
        )
    if operator == "bounded-list":
        maximum = type_expression.get(cast(str, rule["maximum_length_member"]))
        element = type_expression.get(cast(str, rule["element_member"]))
        if (
            not isinstance(value, list)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or maximum < 0
            or len(value) > maximum
        ):
            raise StructuredValueFault(
                "language.structured_value_type_mismatch", pointer
            )
        return cast(
            JsonValue,
            [
                _validate(
                    element,
                    item,
                    authority,
                    budget,
                    _member_pointer(pointer, index),
                )
                for index, item in enumerate(value)
            ],
        )
    if operator == "canonical-ref-key":
        key_pattern = type_expression.get(cast(str, rule["key_pattern_member"]))
        value_members = cast(list[str], rule["value_members"])
        if (
            _nominal_key(type_expression.get(cast(str, rule["target_member"]))) is None
            or not isinstance(key_pattern, str)
            or not key_pattern
            or not isinstance(value, dict)
            or set(value) != set(value_members)
            or len(value_members) != 1
            or not isinstance(value.get(value_members[0]), str)
        ):
            raise StructuredValueFault(
                "language.structured_value_type_mismatch", pointer
            )
        try:
            key_matches = re.fullmatch(key_pattern, value[value_members[0]]) is not None
        except re.error as error:
            raise ValueError("admitted Ref key pattern is invalid") from error
        if not key_matches:
            raise StructuredValueFault(
                "language.structured_value_type_mismatch", pointer
            )
        return cast(JsonValue, {value_members[0]: value[value_members[0]]})
    raise StructuredValueFault("language.structured_value_type_mismatch", pointer)


def admit_typed_value(
    envelope: Any,
    *,
    authority: StructuredValueAuthority,
    resource_limit: int,
) -> dict[str, JsonValue]:
    """Admit and normalize one ``{type, value}`` envelope."""
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"type", "value"}
        or not isinstance(resource_limit, int)
        or isinstance(resource_limit, bool)
        or resource_limit < 1
    ):
        raise StructuredValueFault("language.structured_value_type_mismatch", "")
    return {
        "type": _canonical_type_expression(envelope["type"]),
        "value": _validate(
            envelope["type"],
            envelope["value"],
            authority,
            _Budget(resource_limit),
            "/value",
        ),
    }


def lookup_selector_kind(envelope: Any, *, authority: StructuredValueAuthority) -> str:
    """Return the authority-owned selector mode without consulting local names."""
    if not isinstance(envelope, dict) or set(envelope) != {"type", "value"}:
        raise StructuredValueFault("language.structured_value_type_mismatch", "/type")
    type_expression = envelope["type"]
    nominal_key = _nominal_key(type_expression)
    if nominal_key is not None:
        definition = authority.types.get(nominal_key)
        if definition is None or "definition" not in definition:
            raise StructuredValueFault(
                "language.structured_value_type_mismatch", "/type"
            )
        type_expression = definition["definition"]
    if not isinstance(type_expression, dict):
        raise StructuredValueFault("language.structured_value_type_mismatch", "/type")
    kind = type_expression.get("kind")
    matches = [
        cast(dict[str, Any], constructor["value_rule"])
        for constructor in authority.constructors.values()
        if cast(dict[str, Any], constructor.get("value_rule", {})).get(
            "definition_kind"
        )
        == kind
    ]
    if len(matches) != 1:
        raise StructuredValueFault("language.structured_value_type_mismatch", "/type")
    operator = matches[0].get("operator")
    if operator == "closed-record":
        return "static-field"
    if operator == "bounded-list":
        return "local-index"
    raise StructuredValueFault("language.structured_value_type_mismatch", "/type")


def lookup_typed_value(
    envelope: Any,
    key: Any,
    *,
    authority: StructuredValueAuthority,
    resource_limit: int,
) -> dict[str, JsonValue]:
    """Apply the Kernel bounded lookup law to a typed Record or List."""
    admitted = admit_typed_value(
        envelope, authority=authority, resource_limit=resource_limit
    )
    type_expression: Any = admitted["type"]
    nominal_key = _nominal_key(type_expression)
    if nominal_key is not None:
        nominal = authority.types.get(nominal_key)
        if nominal is None:
            raise StructuredValueFault(
                "language.structured_value_type_mismatch", "/type"
            )
        type_expression = nominal["definition"]
    kind = type_expression.get("kind") if isinstance(type_expression, dict) else None
    rules = [
        cast(dict[str, Any], constructor["value_rule"])
        for constructor in authority.constructors.values()
        if cast(dict[str, Any], constructor.get("value_rule", {})).get(
            "definition_kind"
        )
        == kind
    ]
    if len(rules) != 1:
        raise StructuredValueFault("language.structured_value_type_mismatch", "/key")
    rule = rules[0]
    if rule["operator"] == "closed-record" and isinstance(key, str):
        fields = type_expression[cast(str, rule["fields_member"])]
        name_member = cast(str, rule["field_name_member"])
        type_member = cast(str, rule["field_type_member"])
        field = next(
            (
                field
                for field in cast(list[dict[str, Any]], fields)
                if field[name_member] == key
            ),
            None,
        )
        if field is None:
            raise StructuredValueFault("runtime.structured_lookup_out_of_range", "/key")
        return {
            "type": _canonical_type_expression(field[type_member]),
            "value": cast(dict[str, Any], admitted["value"])[key],
        }
    if (
        rule["operator"] == "bounded-list"
        and isinstance(key, int)
        and not isinstance(key, bool)
    ):
        value = cast(list[JsonValue], admitted["value"])
        if not 0 <= key < len(value):
            raise StructuredValueFault("runtime.structured_lookup_out_of_range", "/key")
        return {
            "type": _canonical_type_expression(
                type_expression[cast(str, rule["element_member"])]
            ),
            "value": value[key],
        }
    raise StructuredValueFault("language.structured_value_type_mismatch", "/key")


def equal_typed_values(
    left: Any,
    right: Any,
    *,
    authority: StructuredValueAuthority,
    resource_limit: int,
) -> dict[str, JsonValue]:
    """Apply exact-type canonical equality to two admitted typed values."""
    admitted_left = admit_typed_value(
        left, authority=authority, resource_limit=resource_limit
    )
    admitted_right = admit_typed_value(
        right, authority=authority, resource_limit=resource_limit
    )
    if canonical_bytes(admitted_left["type"]) != canonical_bytes(
        admitted_right["type"]
    ):
        raise StructuredValueFault(
            "language.structured_value_type_mismatch", "/right/type"
        )
    return {
        "type": {"id": "Boolean", "package": "kernel", "version": "2.0.0"},
        "value": canonical_bytes(admitted_left["value"])
        == canonical_bytes(admitted_right["value"]),
    }


def evaluate_structured_value_vector(
    vector: dict[str, Any],
    *,
    nominal_types: Iterable[dict[str, Any]],
    resource_limit: int,
) -> dict[str, JsonValue]:
    """Execute one authority-owned structured-value conformance vector."""
    inp = cast(dict[str, Any], vector["input"])
    authority = package_structured_value_authority(nominal_types)
    requested_limit = inp.get("limit")
    limit = (
        min(resource_limit, requested_limit)
        if isinstance(requested_limit, int)
        and not isinstance(requested_limit, bool)
        and requested_limit > 0
        else resource_limit
    )
    try:
        if inp["action"] == "admit":
            result = admit_typed_value(
                inp["left"], authority=authority, resource_limit=limit
            )
        elif inp["action"] == "lookup":
            result = lookup_typed_value(
                inp["left"], inp["key"], authority=authority, resource_limit=limit
            )
        elif inp["action"] == "equal":
            result = equal_typed_values(
                inp["left"],
                inp["right"],
                authority=authority,
                resource_limit=limit,
            )
        else:
            raise ValueError("admitted structured-value vector has an unknown action")
    except StructuredValueFault as fault:
        return {
            "code": fault.code,
            "outcome": "refused",
            "pointer": fault.pointer,
            "type": None,
            "value": None,
        }
    return {
        "code": None,
        "outcome": "admitted",
        "pointer": "",
        "type": result["type"],
        "value": result["value"],
    }
