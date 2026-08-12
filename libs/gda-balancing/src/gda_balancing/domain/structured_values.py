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
class StructuredValueIndex:
    """Admitted language index for Kernel/LDB structured-value contracts."""

    constructors: dict[str, dict[str, Any]]
    operations: dict[str, dict[str, Any]]
    types: dict[_TypeKey, dict[str, Any]]
    typed_envelope_profile: dict[str, Any] | None
    fixed_value_contracts: dict[str, dict[str, Any]]
    value_nodes: dict[str, dict[str, Any]]


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


def _kernel_structured_value_contracts(
    kernel: dict[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    meta = kernel.get("meta_format")
    literal_typing = meta.get("literal_typing") if isinstance(meta, dict) else None
    runtime = meta.get("runtime_program") if isinstance(meta, dict) else None
    typed_profile = (
        literal_typing.get("typed_envelope_profile")
        if isinstance(literal_typing, dict)
        else None
    )
    fixed_contracts = (
        runtime.get("fixed_value_contracts") if isinstance(runtime, dict) else None
    )
    nodes = runtime.get("nodes") if isinstance(runtime, dict) else None
    if (
        not isinstance(typed_profile, dict)
        or not isinstance(fixed_contracts, dict)
        or not isinstance(nodes, list)
    ):
        raise ValueError("Kernel structured-value contracts are unavailable")
    value_nodes: dict[str, dict[str, Any]] = {}
    for node in nodes:
        semantics = node.get("semantics") if isinstance(node, dict) else None
        operator = semantics.get("operator") if isinstance(semantics, dict) else None
        if operator in {
            "bounded-lookup",
            "canonical-equal",
            "collection-is-empty",
        }:
            if operator in value_nodes:
                raise ValueError("Kernel structured-value operator is duplicated")
            value_nodes[cast(str, operator)] = node
    if set(value_nodes) != {
        "bounded-lookup",
        "canonical-equal",
        "collection-is-empty",
    }:
        raise ValueError("Kernel structured-value operator is unavailable")
    return (
        typed_profile,
        cast(dict[str, dict[str, Any]], fixed_contracts),
        value_nodes,
    )


def _typed_envelope_profile(
    profiles: Iterable[dict[str, Any]],
    kernel_profile: dict[str, Any],
) -> dict[str, Any]:
    matches = [
        profile
        for profile in profiles
        if profile.get("source_kind") == "typed-envelope"
        and profile.get("value_kind") == kernel_profile.get("value_kind")
    ]
    if len(matches) != 1:
        raise ValueError("admitted language has no unique typed-envelope profile")
    if matches[0] != {
        "admission": kernel_profile.get("admission"),
        "id": kernel_profile.get("id"),
        "source_kind": "typed-envelope",
        "value_kind": kernel_profile.get("value_kind"),
    }:
        raise ValueError("typed-envelope admission law is unsupported")
    return kernel_profile


def _selected_typed_envelope_profile(
    profiles: Iterable[dict[str, Any]],
    kernel_profile: dict[str, Any],
) -> dict[str, Any] | None:
    selected = list(profiles)
    if not any(
        profile.get("source_kind") == "typed-envelope"
        and profile.get("value_kind") == kernel_profile.get("value_kind")
        for profile in selected
    ):
        return None
    return _typed_envelope_profile(selected, kernel_profile)


def typed_envelope_members(authority: StructuredValueIndex) -> tuple[str, str]:
    """Return the Kernel-declared type and value member names."""
    profile = authority.typed_envelope_profile
    admission = profile.get("admission") if isinstance(profile, dict) else None
    envelope_members = (
        admission.get("envelope_members") if isinstance(admission, dict) else None
    )
    type_member = profile.get("type_member") if isinstance(profile, dict) else None
    value_member = profile.get("value_member") if isinstance(profile, dict) else None
    if (
        not isinstance(type_member, str)
        or not isinstance(value_member, str)
        or not isinstance(envelope_members, list)
        or set(envelope_members) != {type_member, value_member}
    ):
        raise ValueError("Kernel typed-envelope members are unavailable")
    return type_member, value_member


def package_structured_value_index(
    package_releases: Iterable[dict[str, Any]],
    *,
    kernel: dict[str, Any],
) -> StructuredValueIndex:
    """Project structured-value rules from admitted Package Releases."""
    typed_profile, fixed_contracts, value_nodes = _kernel_structured_value_contracts(
        kernel
    )
    packages = list(package_releases)
    constructors: dict[str, dict[str, Any]] = {}
    operations: dict[str, dict[str, Any]] = {}
    definitions: dict[_TypeKey, dict[str, Any]] = {}
    profiles: list[dict[str, Any]] = []
    for package in packages:
        for constructor in _semantic_definitions(package, "language.constructors"):
            constructor_id = cast(str, constructor["id"])
            if constructor_id in constructors:
                raise ValueError("admitted constructor identity is duplicated")
            constructors[constructor_id] = constructor
        for operation in _semantic_definitions(
            package, "language.structured_operations"
        ):
            operation_id = cast(str, operation["id"])
            if operation_id in operations:
                raise ValueError("admitted structured operation identity is duplicated")
            operations[operation_id] = operation
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
    return StructuredValueIndex(
        constructors=constructors,
        operations=operations,
        types=definitions,
        typed_envelope_profile=_typed_envelope_profile(profiles, typed_profile),
        fixed_value_contracts=fixed_contracts,
        value_nodes=value_nodes,
    )


def language_structured_value_index(
    language_bundle: dict[str, Any],
    *,
    kernel: dict[str, Any],
) -> StructuredValueIndex:
    """Index structured-value rules from an admitted Language Definition Bundle."""
    typed_profile, fixed_contracts, value_nodes = _kernel_structured_value_contracts(
        kernel
    )
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
    operations = {
        cast(str, operation["id"]): operation
        for operation in cast(
            list[dict[str, Any]], language.get("structured_operations")
        )
    }
    return StructuredValueIndex(
        constructors=constructors,
        operations=operations,
        types=definitions,
        typed_envelope_profile=_typed_envelope_profile(
            cast(list[dict[str, Any]], language.get("literal_typing_profiles")),
            typed_profile,
        ),
        fixed_value_contracts=fixed_contracts,
        value_nodes=value_nodes,
    )


def selected_structured_value_index(
    selected_semantics: dict[str, Any],
    *,
    kernel: dict[str, Any],
) -> StructuredValueIndex:
    """Index only the structured-value rules carried by admitted RIR semantics."""
    typed_profile, fixed_contracts, value_nodes = _kernel_structured_value_contracts(
        kernel
    )
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
    operations = {
        cast(str, row["definition"]["id"]): cast(dict[str, Any], row["definition"])
        for row in cast(
            list[dict[str, Any]], selected_semantics["structured_operations"]
        )
    }
    profiles = [
        cast(dict[str, Any], row["definition"])
        for row in cast(
            list[dict[str, Any]], selected_semantics["literal_typing_profiles"]
        )
    ]
    return StructuredValueIndex(
        constructors=constructors,
        operations=operations,
        types=definitions,
        typed_envelope_profile=_selected_typed_envelope_profile(
            profiles, typed_profile
        ),
        fixed_value_contracts=fixed_contracts,
        value_nodes=value_nodes,
    )


def nominal_type_key(
    type_expression: Any, admission_law: dict[str, Any]
) -> tuple[str, str, str] | None:
    """Read one nominal coordinate through the selected typed-envelope law."""
    if not isinstance(type_expression, dict):
        return None
    contract = admission_law.get("nominal_type_reference")
    if not isinstance(contract, dict):
        return None
    coordinate_members = contract.get("coordinate_members")
    optional_kind_member = contract.get("optional_kind_member")
    optional_kind_value = contract.get("optional_kind_value")
    if (
        not isinstance(coordinate_members, list)
        or coordinate_members != ["package", "version", "id"]
        or not isinstance(optional_kind_member, str)
        or not optional_kind_member
        or not isinstance(optional_kind_value, str)
        or not optional_kind_value
    ):
        return None
    expected_members = set(coordinate_members)
    if optional_kind_member in type_expression:
        expected_members.add(optional_kind_member)
        if type_expression.get(optional_kind_member) != optional_kind_value:
            return None
    if set(type_expression) != expected_members:
        return None
    values = tuple(type_expression.get(name) for name in coordinate_members)
    if all(isinstance(value, str) and value for value in values):
        return cast(tuple[str, str, str], values)
    return None


def _nominal_key(
    type_expression: Any, authority: StructuredValueIndex
) -> tuple[str, str, str] | None:
    profile = authority.typed_envelope_profile
    admission = profile.get("admission") if isinstance(profile, dict) else None
    return (
        nominal_type_key(type_expression, admission)
        if isinstance(admission, dict)
        else None
    )


def _member_pointer(pointer: str, member: str | int) -> str:
    escaped = str(member).replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{escaped}"


def _canonical_type_expression(
    type_expression: Any, authority: StructuredValueIndex
) -> JsonValue:
    """Normalize equivalent nominal spellings at public value boundaries."""
    nominal = _nominal_key(type_expression, authority)
    if nominal is not None:
        package, version, type_id = nominal
        return {"id": type_id, "package": package, "version": version}
    if not isinstance(type_expression, dict):
        if isinstance(type_expression, list):
            return cast(
                JsonValue,
                [
                    _canonical_type_expression(item, authority)
                    for item in type_expression
                ],
            )
        return cast(JsonValue, type_expression)
    return cast(
        JsonValue,
        {
            member: _canonical_type_expression(value, authority)
            for member, value in type_expression.items()
        },
    )


def _structural_type_contract(
    type_expression: Any,
    authority: StructuredValueIndex,
    *,
    pointer: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    nominal_key = _nominal_key(type_expression, authority)
    constructor: dict[str, Any] | None = None
    if nominal_key is not None:
        type_definition = authority.types.get(nominal_key)
        constructor_id = (
            type_definition.get("constructor")
            if isinstance(type_definition, dict)
            else None
        )
        constructor = (
            authority.constructors.get(constructor_id)
            if isinstance(constructor_id, str)
            else None
        )
        if (
            not isinstance(type_definition, dict)
            or constructor is None
            or "definition" not in type_definition
        ):
            raise StructuredValueFault(
                "language.structured_value_type_mismatch", pointer
            )
        type_expression = type_definition["definition"]
    if not isinstance(type_expression, dict):
        raise StructuredValueFault("language.structured_value_type_mismatch", pointer)
    if constructor is None:
        kind = type_expression.get("kind")
        matches = [
            candidate
            for candidate in authority.constructors.values()
            if cast(dict[str, Any], candidate.get("value_rule", {})).get(
                "definition_kind"
            )
            == kind
        ]
        if len(matches) != 1:
            raise StructuredValueFault(
                "language.structured_value_type_mismatch", pointer
            )
        constructor = matches[0]
    rule = constructor.get("value_rule")
    if not isinstance(rule, dict):
        raise StructuredValueFault("language.structured_value_type_mismatch", pointer)
    return type_expression, constructor, rule


def _structured_operation_law(
    authority: StructuredValueIndex,
    constructor: dict[str, Any],
    operator: str,
    *,
    pointer: str,
) -> dict[str, Any]:
    constructor_id = constructor.get("id")
    matches = [
        operation
        for operation in authority.operations.values()
        if operation.get("owner_constructor") == constructor_id
        and isinstance(operation.get("law"), dict)
        and operation["law"].get("operator") == operator
    ]
    if len(matches) != 1:
        raise StructuredValueFault("language.structured_value_type_mismatch", pointer)
    operation = matches[0]
    node = authority.value_nodes.get(operator)
    resource_charge = node.get("resource_charge") if isinstance(node, dict) else None
    resource_bounds = operation.get("resource_bounds")
    if (
        not isinstance(resource_charge, dict)
        or not isinstance(resource_charge.get("amount"), int)
        or isinstance(resource_charge["amount"], bool)
        or not isinstance(resource_bounds, dict)
        or not isinstance(resource_bounds.get("max_steps"), int)
        or isinstance(resource_bounds["max_steps"], bool)
        or resource_charge["amount"] > resource_bounds["max_steps"]
    ):
        raise StructuredValueFault("language.structured_value_type_mismatch", pointer)
    return cast(dict[str, Any], operation["law"])


def lookup_type_contract(
    type_expression: Any,
    key: Any,
    *,
    authority: StructuredValueIndex,
) -> tuple[str, JsonValue, str]:
    """Project one declared lookup selector and result type from authority."""
    definition, constructor, rule = _structural_type_contract(
        type_expression, authority, pointer="/type"
    )
    law = _structured_operation_law(
        authority, constructor, "bounded-lookup", pointer="/type"
    )
    selector = law.get("selector")
    projection = law.get("result_projection")
    refusal_signal = law.get("refusal_signal")
    if not isinstance(refusal_signal, str) or not refusal_signal:
        raise StructuredValueFault("language.structured_value_type_mismatch", "/type")
    if (
        selector == "static-field"
        and projection == "record-field-type"
        and rule.get("operator") == "closed-record"
        and isinstance(key, str)
    ):
        fields = definition.get(cast(str, rule["fields_member"]))
        name_member = cast(str, rule["field_name_member"])
        type_member = cast(str, rule["field_type_member"])
        matches = (
            [
                field
                for field in fields
                if isinstance(field, dict) and field.get(name_member) == key
            ]
            if isinstance(fields, list)
            else []
        )
        if len(matches) == 1:
            return (
                selector,
                _canonical_type_expression(matches[0][type_member], authority),
                refusal_signal,
            )
    if (
        selector == "local-index"
        and projection == "list-element-type"
        and rule.get("operator") == "bounded-list"
    ):
        return (
            selector,
            _canonical_type_expression(
                definition[cast(str, rule["element_member"])], authority
            ),
            refusal_signal,
        )
    raise StructuredValueFault("language.structured_value_type_mismatch", "/key")


def equal_result_contract(
    type_expression: Any, *, authority: StructuredValueIndex
) -> str:
    """Return the fixed Kernel result contract for declared structured equality."""
    _definition, constructor, _rule = _structural_type_contract(
        type_expression, authority, pointer="/type"
    )
    law = _structured_operation_law(
        authority, constructor, "canonical-equal", pointer="/type"
    )
    result_contract = law.get("result_contract")
    if not isinstance(result_contract, str) or not result_contract:
        raise StructuredValueFault("language.structured_value_type_mismatch", "/type")
    return result_contract


def is_empty_result_contract(
    type_expression: Any, *, authority: StructuredValueIndex
) -> str:
    """Return the fixed Kernel result contract for admitted List emptiness."""
    _definition, constructor, rule = _structural_type_contract(
        type_expression, authority, pointer="/type"
    )
    law = _structured_operation_law(
        authority, constructor, "collection-is-empty", pointer="/type"
    )
    result_contract = law.get("result_contract")
    if (
        rule.get("operator") != "bounded-list"
        or not isinstance(result_contract, str)
        or not result_contract
    ):
        raise StructuredValueFault("language.structured_value_type_mismatch", "/type")
    return result_contract


def _validate(
    type_expression: Any,
    value: Any,
    authority: StructuredValueIndex,
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
    nominal_key = _nominal_key(type_expression, authority)
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
            _nominal_key(
                type_expression.get(cast(str, rule["target_member"])), authority
            )
            is None
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
    authority: StructuredValueIndex,
    resource_limit: int,
) -> dict[str, JsonValue]:
    """Admit and normalize one authority-declared typed envelope."""
    type_member, value_member = typed_envelope_members(authority)
    profile = cast(dict[str, Any], authority.typed_envelope_profile)
    envelope_members = cast(list[str], profile["admission"]["envelope_members"])
    if (
        not isinstance(envelope, dict)
        or set(envelope) != set(envelope_members)
        or not isinstance(resource_limit, int)
        or isinstance(resource_limit, bool)
        or resource_limit < 1
    ):
        raise StructuredValueFault("language.structured_value_type_mismatch", "")
    return {
        type_member: _canonical_type_expression(envelope[type_member], authority),
        value_member: _validate(
            envelope[type_member],
            envelope[value_member],
            authority,
            _Budget(resource_limit),
            _member_pointer("", value_member),
        ),
    }


def lookup_selector_kind(envelope: Any, *, authority: StructuredValueIndex) -> str:
    """Return the authority-owned selector mode without consulting local names."""
    type_member, _value_member = typed_envelope_members(authority)
    profile = cast(dict[str, Any], authority.typed_envelope_profile)
    envelope_members = cast(list[str], profile["admission"]["envelope_members"])
    if not isinstance(envelope, dict) or set(envelope) != set(envelope_members):
        raise StructuredValueFault("language.structured_value_type_mismatch", "/type")
    type_expression = envelope[type_member]
    _definition, constructor, _rule = _structural_type_contract(
        type_expression, authority, pointer="/type"
    )
    law = _structured_operation_law(
        authority, constructor, "bounded-lookup", pointer="/type"
    )
    selector = law.get("selector")
    if selector not in {"static-field", "local-index"}:
        raise StructuredValueFault("language.structured_value_type_mismatch", "/type")
    return cast(str, selector)


def lookup_typed_value(
    envelope: Any,
    key: Any,
    *,
    authority: StructuredValueIndex,
    resource_limit: int,
) -> dict[str, JsonValue]:
    """Apply the Kernel bounded lookup law to a typed Record or List."""
    admitted = admit_typed_value(
        envelope, authority=authority, resource_limit=resource_limit
    )
    type_member, value_member = typed_envelope_members(authority)
    type_expression: Any = admitted[type_member]
    type_expression, _constructor, rule = _structural_type_contract(
        type_expression, authority, pointer="/type"
    )
    selector, result_type, refusal_signal = lookup_type_contract(
        admitted[type_member], key, authority=authority
    )
    if refusal_signal != "structured-lookup-out-of-range":
        raise StructuredValueFault("language.structured_value_type_mismatch", "/type")
    if selector == "static-field" and isinstance(key, str):
        fields = type_expression[cast(str, rule["fields_member"])]
        name_member = cast(str, rule["field_name_member"])
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
            type_member: result_type,
            value_member: cast(dict[str, Any], admitted[value_member])[key],
        }
    if selector == "local-index" and isinstance(key, int) and not isinstance(key, bool):
        value = cast(list[JsonValue], admitted[value_member])
        if not 0 <= key < len(value):
            raise StructuredValueFault("runtime.structured_lookup_out_of_range", "/key")
        return {
            type_member: result_type,
            value_member: value[key],
        }
    raise StructuredValueFault("language.structured_value_type_mismatch", "/key")


def equal_typed_values(
    left: Any,
    right: Any,
    *,
    authority: StructuredValueIndex,
    resource_limit: int,
) -> dict[str, JsonValue]:
    """Apply exact-type canonical equality to two admitted typed values."""
    admitted_left = admit_typed_value(
        left, authority=authority, resource_limit=resource_limit
    )
    admitted_right = admit_typed_value(
        right, authority=authority, resource_limit=resource_limit
    )
    type_member, value_member = typed_envelope_members(authority)
    if canonical_bytes(admitted_left[type_member]) != canonical_bytes(
        admitted_right[type_member]
    ):
        raise StructuredValueFault(
            "language.structured_value_type_mismatch", "/right/type"
        )
    equality_node = authority.value_nodes["canonical-equal"]
    result = cast(dict[str, Any], equality_node["result"])
    typing = result.get("typing")
    kernel_result_contract = (
        typing.get("contract") if isinstance(typing, dict) else None
    )
    if (
        not isinstance(kernel_result_contract, str)
        or equal_result_contract(admitted_left[type_member], authority=authority)
        != kernel_result_contract
        or kernel_result_contract not in authority.fixed_value_contracts
    ):
        raise StructuredValueFault(
            "language.structured_value_type_mismatch", "/left/type"
        )
    result_type = authority.fixed_value_contracts[kernel_result_contract].get("type")
    if not isinstance(result_type, dict):
        raise StructuredValueFault(
            "language.structured_value_type_mismatch", "/left/type"
        )
    return {
        type_member: cast(JsonValue, result_type),
        value_member: canonical_bytes(admitted_left[value_member])
        == canonical_bytes(admitted_right[value_member]),
    }


def is_empty_typed_value(
    envelope: Any,
    *,
    authority: StructuredValueIndex,
    resource_limit: int,
) -> dict[str, JsonValue]:
    """Apply the selected LDB List-emptiness law to one admitted typed value."""
    admitted = admit_typed_value(
        envelope, authority=authority, resource_limit=resource_limit
    )
    type_member, value_member = typed_envelope_members(authority)
    node = authority.value_nodes["collection-is-empty"]
    typing = cast(dict[str, Any], node["result"]).get("typing")
    kernel_result_contract = (
        typing.get("contract") if isinstance(typing, dict) else None
    )
    if (
        not isinstance(kernel_result_contract, str)
        or is_empty_result_contract(admitted[type_member], authority=authority)
        != kernel_result_contract
        or kernel_result_contract not in authority.fixed_value_contracts
        or not isinstance(admitted[value_member], list)
    ):
        raise StructuredValueFault("language.structured_value_type_mismatch", "/type")
    result_type = authority.fixed_value_contracts[kernel_result_contract].get("type")
    if not isinstance(result_type, dict):
        raise StructuredValueFault("language.structured_value_type_mismatch", "/type")
    return {
        type_member: cast(JsonValue, result_type),
        value_member: not admitted[value_member],
    }


def evaluate_structured_value_vector(
    vector: dict[str, Any],
    *,
    nominal_types: Iterable[dict[str, Any]],
    kernel: dict[str, Any],
    resource_limit: int,
) -> dict[str, JsonValue]:
    """Execute one authority-owned structured-value conformance vector."""
    inp = cast(dict[str, Any], vector["input"])
    authority = package_structured_value_index(nominal_types, kernel=kernel)
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
        "type": result[typed_envelope_members(authority)[0]],
        "value": result[typed_envelope_members(authority)[1]],
    }
