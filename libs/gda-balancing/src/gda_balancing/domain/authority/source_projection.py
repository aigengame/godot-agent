"""Derive Source meaning from the admitted Source Schema annotations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

import jsonschema

from gda_balancing.domain.authority.contract_projection import owned_contract_schema
from gda_balancing.domain.canonical import JsonValue, canonical_bytes

_ROLE = "semantic_role"
_MEMBER = "semantic_member"
_NATIVE = "semantic_native_contract"


def _pointer(parts: tuple[Any, ...]) -> str:
    return "".join("/" + str(x).replace("~", "~0").replace("/", "~1") for x in parts)


def _object_alternatives(schema: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result = [schema]
    branches = schema.get("oneOf", [])
    if isinstance(branches, Sequence) and not isinstance(branches, (str, bytes)):
        for child in branches:
            if isinstance(child, Mapping):
                result.extend(_object_alternatives(child))
    return result


def _semantic_annotation_contract(kernel: Mapping[str, Any]) -> Mapping[str, Any]:
    return cast(
        Mapping[str, Any],
        kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
            "source_notation"
        ]["semantic_annotations"],
    )


def _annotation_contract_is_supported(contract: Mapping[str, Any]) -> bool:
    """Recognize the one generic annotation meta-contract implemented here."""
    return contract == {
        "identifier": "non-empty-string",
        "keys": {
            "member": _MEMBER,
            "native_contract": _NATIVE,
            "role": _ROLE,
        },
        "native_contract": {
            "allowed_members": [
                "kernel_contract_paths",
                "kernel_reference",
                "language_reference",
                "value_location",
            ],
            "closed": True,
            "kernel_reference": {
                "contract_path": "absolute-authority-path",
                "kinds": {
                    "canonical-value": ["value"],
                    "closed-const-object": ["value"],
                    "owned-contract": ["value"],
                    "typed-literal": [
                        "boolean_contract",
                        "source_kinds",
                        "typed_envelope_profile",
                    ],
                },
            },
            "language_reference": {
                "authority_path": "absolute-authority-path",
            },
            "reference_pairs": [
                ["kernel_reference", "kernel_contract_paths"],
                ["language_reference", "value_location"],
            ],
            "value_location": {
                "closed": True,
                "keyword": ["const", "enum"],
                "optional_members": ["semantic_member"],
                "required_members": ["keyword"],
                "semantic_member": "non-empty-string",
            },
        },
        "native_payload_annotations": "forbidden",
        "one_of": {
            "member_coherence": "same-authored-property",
            "role_inheritance": "unannotated-branch",
        },
        "placement": {
            "member": "object-property-schema",
            "native_contract": "semantic-member-schema",
            "role": "object-schema",
        },
        "role_members": {
            "completeness": "same-role-exact-member-set",
            "uniqueness": "per-object",
        },
        "root_role": "required",
    }


def _source_schema(
    kernel: Mapping[str, Any], language_bundle: Mapping[str, Any]
) -> Mapping[str, Any]:
    notation = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["source_notation"]
    role = notation["role"]
    rows = [
        row
        for row in language_bundle["language"]["wire_schemas"]
        if isinstance(row, Mapping) and row.get("protocol_role") == role
    ]
    if len(rows) != 1 or not isinstance(rows[0].get("schema"), Mapping):
        raise ValueError("Source protocol has no unique Schema definition")
    return cast(Mapping[str, Any], rows[0]["schema"])


def _authority_path(
    kernel: Mapping[str, Any], language_bundle: Mapping[str, Any], path: str
) -> Any:
    if (
        not isinstance(path, str)
        or not path
        or path.startswith(".")
        or path.endswith(".")
    ):
        raise ValueError("semantic native contract path is malformed")
    parts = path.split(".")
    if any(not part for part in parts):
        raise ValueError("semantic native contract path is malformed")
    if parts[0] == "kernel":
        values: list[Any] = [kernel]
    elif parts[0] == "language":
        values = [language_bundle["language"]]
    else:
        raise ValueError("semantic native contract path has an unknown authority root")
    for part in parts[1:]:
        selected: list[Any] = []
        for value in values:
            if isinstance(value, Mapping) and part in value:
                selected.append(value[part])
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                for row in value:
                    if not isinstance(row, Mapping) or part not in row:
                        raise ValueError("semantic native contract path is dangling")
                    selected.append(row[part])
            else:
                raise ValueError("semantic native contract path is dangling")
        values = selected
    if not values:
        raise ValueError("semantic native contract path is dangling")
    return values[0] if len(values) == 1 else values


def _without_annotations(schema: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in schema.items()
        if key not in {_MEMBER, _NATIVE, _ROLE}
    }


def _canonical_set(values: Sequence[Any]) -> set[bytes]:
    encoded = [canonical_bytes(cast(JsonValue, value)) for value in values]
    if len(encoded) != len(set(encoded)):
        raise ValueError("semantic native contract value set has duplicates")
    return set(encoded)


def _has_contract_shape(schema: Any, expected: Any) -> bool:
    """Compare structural contract shape while permitting tighter Schema facets."""
    if not isinstance(schema, Mapping) or not isinstance(expected, Mapping):
        return False
    if "type" in expected and schema.get("type") != expected["type"]:
        return False
    if "const" in expected and schema.get("const") != expected["const"]:
        return False
    if "enum" in expected and schema.get("enum") != expected["enum"]:
        return False
    expected_properties = expected.get("properties")
    if isinstance(expected_properties, Mapping):
        properties = schema.get("properties")
        if not isinstance(properties, Mapping) or set(properties) != set(
            expected_properties
        ):
            return False
        if set(schema.get("required", [])) != set(expected.get("required", [])):
            return False
        if schema.get("unevaluatedProperties") is not False:
            return False
        return all(
            _has_contract_shape(properties[name], child)
            for name, child in expected_properties.items()
        )
    expected_items = expected.get("items")
    return expected_items is None or _has_contract_shape(
        schema.get("items"), expected_items
    )


def _typed_literal_is_closed(
    schema: Mapping[str, Any], contracts: Mapping[str, Any]
) -> bool:
    source_kinds = contracts["source_kinds"]
    typed = contracts["typed_envelope_profile"]
    boolean_contract = contracts["boolean_contract"]
    if (
        not isinstance(source_kinds, Sequence)
        or isinstance(source_kinds, (str, bytes))
        or not isinstance(typed, Mapping)
        or not isinstance(boolean_contract, Mapping)
        or not isinstance(boolean_contract.get("kind"), str)
    ):
        return False
    required_kinds = {*source_kinds, boolean_contract["kind"]}
    if len(source_kinds) != len(set(source_kinds)):
        return False
    alternatives = schema.get("oneOf")
    union = alternatives is not None
    if alternatives is None:
        branches: Sequence[Any] = [schema]
    elif (
        not isinstance(alternatives, Sequence)
        or isinstance(alternatives, (str, bytes))
        or not alternatives
        or "type" in schema
        or not all(isinstance(branch, Mapping) for branch in alternatives)
    ):
        return False
    else:
        branches = alternatives
    nominal = typed["admission"]["nominal_type_reference"]
    envelope = set(typed["admission"]["envelope_members"])
    coordinate = set(nominal["coordinate_members"])
    marker = nominal["optional_kind_member"]
    kinds: list[str] = []
    for untyped_branch in branches:
        branch = cast(Mapping[str, Any], untyped_branch)
        kind = branch.get("type")
        if "oneOf" in branch:
            return False
        if kind in required_kinds - {"typed-envelope"}:
            kinds.append(cast(str, kind))
            continue
        if kind != "object" or branch.get("unevaluatedProperties") is not False:
            return False
        properties = branch.get("properties")
        required = branch.get("required")
        if (
            not isinstance(properties, Mapping)
            or set(properties) != envelope
            or not isinstance(required, Sequence)
            or isinstance(required, (str, bytes))
            or len(required) != len(envelope)
            or set(required) != envelope
        ):
            return False
        reference = properties.get(typed["type_member"])
        if (
            not isinstance(reference, Mapping)
            or reference.get("type") != "object"
            or reference.get("unevaluatedProperties") is not False
        ):
            return False
        fields = reference.get("properties")
        reference_required = reference.get("required")
        if (
            not isinstance(fields, Mapping)
            or not coordinate <= set(fields) <= coordinate | {marker}
            or not isinstance(reference_required, Sequence)
            or isinstance(reference_required, (str, bytes))
            or len(reference_required) != len(coordinate)
            or set(reference_required) != coordinate
            or any(
                not isinstance(fields[name], Mapping)
                or fields[name].get("type") != "string"
                for name in coordinate
            )
            or (
                marker in fields
                and (
                    not isinstance(fields[marker], Mapping)
                    or fields[marker].get("const") != nominal["optional_kind_value"]
                )
            )
        ):
            return False
        kinds.append("typed-envelope")
    observed = set(kinds)
    return len(kinds) == len(observed) and (
        observed == required_kinds if union else observed <= required_kinds
    )


def _kernel_reference_is_closed(
    kernel: Mapping[str, Any],
    language_bundle: Mapping[str, Any],
    schema: Mapping[str, Any],
    kind: Any,
    paths: Any,
    contract: Mapping[str, Any],
) -> bool:
    kinds = contract["kinds"]
    if (
        not isinstance(kind, str)
        or kind not in kinds
        or not isinstance(paths, Mapping)
        or set(paths) != set(kinds[kind])
        or not all(isinstance(path, str) and path for path in paths.values())
        or len(set(paths.values())) != len(paths)
    ):
        return False
    resolved = {
        name: _authority_path(kernel, language_bundle, path)
        for name, path in paths.items()
    }
    payload = _without_annotations(schema)
    if kind == "canonical-value":
        return resolved["value"] == {"type": "canonical-value"}
    if kind == "owned-contract":
        value = resolved["value"]
        return isinstance(value, Mapping) and _has_contract_shape(
            payload, owned_contract_schema(dict(value))
        )
    if kind == "closed-const-object":
        value = resolved["value"]
        return isinstance(value, Mapping) and payload == {
            "properties": {name: {"const": item} for name, item in value.items()},
            "required": list(value),
            "type": "object",
            "unevaluatedProperties": False,
        }
    return kind == "typed-literal" and _typed_literal_is_closed(schema, resolved)


def _language_reference_is_closed(
    kernel: Mapping[str, Any],
    language_bundle: Mapping[str, Any],
    schema: Mapping[str, Any],
    siblings: Mapping[str, Mapping[str, Any]],
    authority_path: Any,
    location: Any,
) -> bool:
    del kernel
    if (
        not isinstance(location, Mapping)
        or not set(location)
        <= {
            "keyword",
            "semantic_member",
        }
        or set(location) not in ({"keyword"}, {"keyword", "semantic_member"})
    ):
        return False
    keyword = location.get("keyword")
    if keyword not in {"const", "enum"}:
        return False
    selected = schema
    sibling = location.get("semantic_member")
    if sibling is not None:
        if not isinstance(sibling, str) or not sibling or sibling not in siblings:
            return False
        selected = siblings[sibling]
    if _ROLE in selected:
        return False
    if keyword not in selected:
        return False
    observed = selected[keyword]
    observed_values = observed if keyword == "enum" else [observed]
    if (
        not isinstance(observed_values, Sequence)
        or isinstance(observed_values, (str, bytes))
        or not observed_values
    ):
        return False
    target = _authority_path(
        {"unused": True}, language_bundle, cast(str, authority_path)
    )
    target_values = (
        target
        if isinstance(target, Sequence) and not isinstance(target, (str, bytes))
        else [target]
    )
    return _canonical_set(observed_values) == _canonical_set(target_values)


def _native_contract_is_closed(
    kernel: Mapping[str, Any],
    language_bundle: Mapping[str, Any],
    schema: Mapping[str, Any],
    siblings: Mapping[str, Mapping[str, Any]],
    native_contract: Any,
    contract: Mapping[str, Any],
) -> bool:
    allowed = {
        "kernel_contract_paths",
        "kernel_reference",
        "language_reference",
        "value_location",
    }
    if (
        not isinstance(native_contract, Mapping)
        or not native_contract
        or not set(native_contract) <= allowed
    ):
        return False
    has_kernel_reference = "kernel_reference" in native_contract
    has_kernel_paths = "kernel_contract_paths" in native_contract
    has_language_reference = "language_reference" in native_contract
    has_value_location = "value_location" in native_contract
    if has_kernel_reference != has_kernel_paths:
        return False
    if has_language_reference != has_value_location:
        return False
    if not has_kernel_reference and not has_language_reference:
        return False
    return (
        not has_kernel_reference
        or _kernel_reference_is_closed(
            kernel,
            language_bundle,
            schema,
            native_contract["kernel_reference"],
            native_contract["kernel_contract_paths"],
            contract["kernel_reference"],
        )
    ) and (
        not has_language_reference
        or _language_reference_is_closed(
            kernel,
            language_bundle,
            schema,
            siblings,
            native_contract["language_reference"],
            native_contract["value_location"],
        )
    )


def _entry_roles(node: Mapping[str, Any]) -> frozenset[str]:
    role = node.get(_ROLE)
    if isinstance(role, str):
        return frozenset({role})
    branches = node.get("oneOf")
    if not isinstance(branches, Sequence) or isinstance(branches, (str, bytes)):
        return frozenset()
    return frozenset(
        role
        for branch in branches
        if isinstance(branch, Mapping)
        for role in _entry_roles(branch)
    )


@dataclass(frozen=True)
class SourceSemanticIndex:
    """Frozen, derived Source meaning; it is neither serialized nor identity-bearing."""

    schema: Mapping[str, Any]
    root_role: str
    role_anchors: Mapping[str, tuple[Mapping[str, Any], ...]]
    role_members: Mapping[str, frozenset[str]]
    child_roles: Mapping[tuple[str, str], frozenset[str]]


@dataclass(frozen=True)
class SourceNativeBindingIndex:
    """Frozen LDB tokens selected by the compiler's stable Source ABI slots."""

    roles: Mapping[str, str]
    members: Mapping[str, str]
    discriminators: Mapping[str, JsonValue]


@dataclass(frozen=True)
class SourceAssignmentBinding:
    """One role-scoped assignment mode selected by its admitted behavior."""

    role: str
    mode: str


def source_assignment_binding(
    assignment_policy: Mapping[str, Any],
    *,
    initialization_source: str,
    binding_kind: str | None = None,
    entrypoint_result: bool | None = None,
    entrypoint_operand_access: Sequence[str] | None = None,
    value_member: str | None = None,
    experiment_cardinality: str | None = None,
    event_payload_cardinality: str | None = None,
    external_fact_cardinality: str | None = None,
    override: bool | None = None,
) -> SourceAssignmentBinding:
    """Select one LDB role/mode pair without depending on either native name."""
    role_fields: dict[str, Any] = {
        "binding_kind": binding_kind,
        "entrypoint_result": entrypoint_result,
        "entrypoint_operand_access": (
            list(entrypoint_operand_access)
            if entrypoint_operand_access is not None
            else None
        ),
    }
    mode_fields: dict[str, Any] = {
        "initialization_source": initialization_source,
        "value_member": value_member,
        "experiment_cardinality": experiment_cardinality,
        "event_payload_cardinality": event_payload_cardinality,
        "external_fact_cardinality": external_fact_cardinality,
        "override": override,
    }
    matches = [
        SourceAssignmentBinding(cast(str, row["role"]), cast(str, mode["id"]))
        for row in assignment_policy.get("roles", ())
        if isinstance(row, Mapping)
        and isinstance(row.get("role"), str)
        and all(
            expected is None or row.get(field) == expected
            for field, expected in role_fields.items()
        )
        for mode in row.get("modes", ())
        if isinstance(mode, Mapping)
        and isinstance(mode.get("id"), str)
        and all(
            expected is None or mode.get(field) == expected
            for field, expected in mode_fields.items()
        )
    ]
    if len(matches) != 1:
        raise ValueError("Source assignment behavior has no unique role and mode")
    return matches[0]


def source_assignment_policy(
    language_bundle: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return the default profile's uniquely selected Symbol assignment policy."""
    language = language_bundle["language"]
    profiles = [
        profile
        for profile in language["resolution_profiles"]
        if isinstance(profile, Mapping) and profile.get("default") is True
    ]
    if len(profiles) != 1:
        raise ValueError("Source assignment policy requires one default profile")
    profile = profiles[0]
    lowerings = [
        lowering
        for lowering in language["model_lowerings"]
        if isinstance(lowering, Mapping)
        and lowering.get("id") == profile.get("model_lowering")
        and lowering.get("resolution_profile") == profile.get("id")
    ]
    if len(lowerings) != 1 or not isinstance(
        lowerings[0].get("assignment_policy"), Mapping
    ):
        raise ValueError("Source assignment policy has no unique selected lowering")
    return cast(Mapping[str, Any], lowerings[0]["assignment_policy"])


def project_source_native_token(
    bindings: SourceNativeBindingIndex, slot: str, value: Any
) -> Any:
    """Translate one LDB token through a fixed Source-native ABI slot."""
    binding = bindings.discriminators.get(slot)
    abi = _SOURCE_NATIVE_DISCRIMINATOR_ABI.get(slot)
    if abi is None or binding is None:
        raise ValueError("Source native token slot is unavailable")
    return deepcopy(abi[2]) if value == binding else value


def author_source_native_token(
    bindings: SourceNativeBindingIndex, slot: str, value: Any
) -> Any:
    """Translate one fixed Source-native token back to its LDB-owned spelling."""
    binding = bindings.discriminators.get(slot)
    abi = _SOURCE_NATIVE_DISCRIMINATOR_ABI.get(slot)
    if abi is None or binding is None:
        raise ValueError("Source native token slot is unavailable")
    return deepcopy(binding) if value == abi[2] else value


_SOURCE_NATIVE_ROLE_SLOTS = frozenset(
    f"source.{name}"
    for name in (
        "binding",
        "binding_argument",
        "boolean_value_contract",
        "conditional",
        "derived_site",
        "discard_result",
        "entrypoint",
        "entrypoint_argument",
        "event_operand",
        "formula",
        "formula_argument",
        "formula_call",
        "formula_coordinate",
        "formula_parameter",
        "import",
        "inline_parameter",
        "literal",
        "local_operand",
        "manifest",
        "module",
        "operation_argument",
        "operation_call",
        "operation_coordinate",
        "operation_site",
        "parameter_operand",
        "program",
        "root",
        "slot_parameter",
        "symbol",
        "symbol_operand",
        "template_provenance",
        "value_contract",
        "value_policy",
    )
)


def _member_abi(
    owner: str,
    members: Sequence[str],
    *,
    arrays: Mapping[str, Sequence[str]] | None = None,
    natives: Sequence[str] = (),
    objects: Mapping[str, Sequence[str]] | None = None,
    unions: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, tuple[str, str, tuple[str, ...]]]:
    arrays = arrays or {}
    objects = objects or {}
    unions = unions or {}
    result: dict[str, tuple[str, str, tuple[str, ...]]] = {}
    for member in members:
        shape = "scalar"
        targets: Sequence[str] = ()
        if member in natives:
            shape = "native"
        elif member in arrays:
            shape, targets = "array", arrays[member]
        elif member in objects:
            shape, targets = "object", objects[member]
        elif member in unions:
            shape, targets = "union", unions[member]
        result[f"{owner}.{member}"] = (owner, shape, tuple(targets))
    return result


_SOURCE_NATIVE_MEMBER_ABI: Mapping[str, tuple[str, str, tuple[str, ...]]] = (
    MappingProxyType(
        {
            **_member_abi(
                "source.root",
                (
                    "schema_version",
                    "manifest",
                    "package_requirements",
                    "modules",
                    "formula_bindings",
                    "entrypoints",
                ),
                arrays={
                    "package_requirements": (),
                    "modules": ("source.module",),
                    "formula_bindings": ("source.binding",),
                    "entrypoints": ("source.entrypoint",),
                },
                natives=("schema_version",),
                objects={"manifest": ("source.manifest",)},
            ),
            **_member_abi(
                "source.manifest",
                ("id", "entry_module", "template_provenance"),
                objects={"template_provenance": ("source.template_provenance",)},
            ),
            **_member_abi(
                "source.template_provenance",
                ("template_id", "template_identity", "starter_identity"),
            ),
            **_member_abi(
                "source.module",
                ("id", "imports", "symbols", "formulas"),
                arrays={
                    "imports": ("source.import",),
                    "symbols": ("source.symbol",),
                    "formulas": ("source.formula",),
                },
            ),
            **_member_abi("source.import", ("alias", "package", "symbol")),
            **_member_abi(
                "source.symbol",
                (
                    "symbol",
                    "type",
                    "role",
                    "representation",
                    "kind",
                    "unit",
                    "domain_kind",
                    "domain",
                    "numeric_policy",
                    "value_policy",
                ),
                natives=(
                    "role",
                    "representation",
                    "kind",
                    "unit",
                    "domain",
                    "numeric_policy",
                ),
                objects={"value_policy": ("source.value_policy",)},
            ),
            **_member_abi("source.value_policy", ("mode", "value"), natives=("value",)),
            **_member_abi(
                "source.entrypoint",
                ("id", "operation", "arguments", "result"),
                arrays={"arguments": ("source.entrypoint_argument",)},
                objects={"operation": ("source.operation_coordinate",)},
                unions={"result": ("source.symbol_operand", "source.discard_result")},
            ),
            **_member_abi(
                "source.entrypoint_argument",
                ("port", "operand"),
                unions={
                    "operand": (
                        "source.symbol_operand",
                        "source.literal",
                        "source.event_operand",
                    )
                },
            ),
            **_member_abi("source.operation_coordinate", ("package", "id")),
            **_member_abi("source.formula_coordinate", ("module", "id")),
            **_member_abi(
                "source.formula",
                ("id", "parameters", "result", "body", "expression"),
                arrays={"parameters": ("source.formula_parameter",)},
                objects={"result": ("source.value_contract",)},
                unions={"body": ("source.program", "source.inline_parameter")},
            ),
            **_member_abi(
                "source.formula_parameter",
                (
                    "id",
                    "kind",
                    "type",
                    "domain_kind",
                    "domain",
                    "numeric_policy",
                    "representation",
                    "unit",
                ),
                natives=("domain",),
            ),
            **_member_abi(
                "source.program",
                ("nodes", "result"),
                arrays={
                    "nodes": (
                        "source.formula_call",
                        "source.operation_call",
                        "source.conditional",
                    )
                },
                unions={
                    "result": (
                        "source.parameter_operand",
                        "source.local_operand",
                        "source.symbol_operand",
                        "source.literal",
                    )
                },
            ),
            **_member_abi("source.inline_parameter", ("node", "parameter")),
            **_member_abi(
                "source.formula_call",
                ("id", "node", "formula", "arguments"),
                arrays={"arguments": ("source.formula_argument",)},
                objects={"formula": ("source.formula_coordinate",)},
            ),
            **_member_abi(
                "source.formula_argument",
                ("parameter", "operand"),
                unions={
                    "operand": (
                        "source.parameter_operand",
                        "source.local_operand",
                        "source.symbol_operand",
                        "source.literal",
                    )
                },
            ),
            **_member_abi(
                "source.operation_call",
                ("id", "node", "operation", "arguments", "result"),
                arrays={"arguments": ("source.operation_argument",)},
                objects={"operation": ("source.operation_coordinate",)},
                unions={
                    "result": (
                        "source.value_contract",
                        "source.boolean_value_contract",
                    )
                },
            ),
            **_member_abi(
                "source.operation_argument",
                ("port", "operand"),
                unions={
                    "operand": (
                        "source.parameter_operand",
                        "source.local_operand",
                        "source.symbol_operand",
                        "source.literal",
                    )
                },
            ),
            **_member_abi(
                "source.conditional",
                ("id", "node", "condition", "when_true", "when_false"),
                unions={
                    name: (
                        "source.parameter_operand",
                        "source.local_operand",
                        "source.symbol_operand",
                        "source.literal",
                    )
                    for name in ("condition", "when_true", "when_false")
                },
            ),
            **_member_abi("source.parameter_operand", ("kind", "parameter")),
            **_member_abi("source.local_operand", ("kind", "local")),
            **_member_abi("source.symbol_operand", ("kind", "module", "symbol")),
            **_member_abi("source.literal", ("kind", "value"), natives=("value",)),
            **_member_abi("source.event_operand", ("kind", "name")),
            **_member_abi("source.discard_result", ("kind",)),
            **_member_abi(
                "source.binding",
                ("site", "formula", "arguments"),
                arrays={"arguments": ("source.binding_argument",)},
                objects={"formula": ("source.formula_coordinate",)},
                unions={"site": ("source.derived_site", "source.operation_site")},
            ),
            **_member_abi(
                "source.binding_argument",
                ("parameter", "operand"),
                unions={"operand": ("source.slot_parameter", "source.symbol_operand")},
            ),
            **_member_abi("source.derived_site", ("kind", "module", "symbol")),
            **_member_abi(
                "source.operation_site",
                ("kind", "operation", "slot"),
                objects={"operation": ("source.operation_coordinate",)},
            ),
            **_member_abi("source.slot_parameter", ("kind", "parameter")),
            **_member_abi(
                "source.value_contract",
                (
                    "type",
                    "representation",
                    "kind",
                    "unit",
                    "domain_kind",
                    "domain",
                    "numeric_policy",
                ),
                natives=("domain",),
            ),
            **_member_abi(
                "source.boolean_value_contract",
                ("type", "representation", "kind", "unit", "domain", "numeric_policy"),
                natives=("domain",),
            ),
        }
    )
)

_SOURCE_NATIVE_DISCRIMINATOR_ABI: Mapping[str, tuple[str, str, JsonValue]] = (
    MappingProxyType(
        {
            "source.formula_call.discriminator": (
                "source.formula_call",
                "source.formula_call.node",
                "formula-call",
            ),
            "source.operation_call.discriminator": (
                "source.operation_call",
                "source.operation_call.node",
                "operation-call",
            ),
            "source.conditional.discriminator": (
                "source.conditional",
                "source.conditional.node",
                "conditional",
            ),
            "source.parameter_operand.discriminator": (
                "source.parameter_operand",
                "source.parameter_operand.kind",
                "parameter",
            ),
            "source.local_operand.discriminator": (
                "source.local_operand",
                "source.local_operand.kind",
                "local",
            ),
            "source.symbol_operand.discriminator": (
                "source.symbol_operand",
                "source.symbol_operand.kind",
                "symbol",
            ),
            "source.literal.discriminator": (
                "source.literal",
                "source.literal.kind",
                "literal",
            ),
            "source.event_operand.discriminator": (
                "source.event_operand",
                "source.event_operand.kind",
                "event-reference",
            ),
            "source.discard_result.discriminator": (
                "source.discard_result",
                "source.discard_result.kind",
                "discard",
            ),
            "source.derived_site.discriminator": (
                "source.derived_site",
                "source.derived_site.kind",
                "derived-symbol",
            ),
            "source.operation_site.discriminator": (
                "source.operation_site",
                "source.operation_site.kind",
                "operation-slot",
            ),
            "source.slot_parameter.discriminator": (
                "source.slot_parameter",
                "source.slot_parameter.kind",
                "slot-parameter",
            ),
            "source.inline_parameter.discriminator": (
                "source.inline_parameter",
                "source.inline_parameter.node",
                "parameter",
            ),
            "source.formula_parameter.domain_kind.discriminator": (
                "source.formula_parameter",
                "source.formula_parameter.domain_kind",
                "closed-interval",
            ),
            "source.symbol.domain_kind.discriminator": (
                "source.symbol",
                "source.symbol.domain_kind",
                "closed-interval",
            ),
            "source.value_contract.domain_kind.discriminator": (
                "source.value_contract",
                "source.value_contract.domain_kind",
                "closed-interval",
            ),
        }
    )
)


def _source_member_schemas(
    index: SourceSemanticIndex, role: str, member: str
) -> list[Mapping[str, Any]]:
    return [
        child
        for anchor in index.role_anchors[role]
        for child in cast(
            Mapping[str, Mapping[str, Any]], anchor.get("properties", {})
        ).values()
        if child.get(_MEMBER) == member
    ]


def _source_member_shape_is_closed(field: Mapping[str, Any], shape: str) -> bool:
    # ``native`` requires every occurrence to be authority-owned as one opaque
    # value. Structural members may still contain branch-local native consts.
    if shape == "native":
        return _NATIVE in field
    if shape == "array":
        return field.get("type") == "array"
    if shape == "object":
        return field.get("type") == "object" and "oneOf" not in field
    if shape == "union":
        return isinstance(field.get("oneOf"), Sequence) and bool(field["oneOf"])
    return shape == "scalar" and field.get("type") != "array" and "oneOf" not in field


def derive_source_native_bindings(
    index: SourceSemanticIndex, bindings: Any
) -> SourceNativeBindingIndex:
    """Validate and freeze the LDB tokens assigned to fixed compiler ABI slots."""
    if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
        raise ValueError("Source native bindings are not a list")
    rows: dict[str, Mapping[str, Any]] = {}
    for row in bindings:
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("slot"), str)
            or not row["slot"]
            or row["slot"] in rows
        ):
            raise ValueError("Source native binding slot is malformed or duplicate")
        rows[cast(str, row["slot"])] = row
    expected_slots = (
        _SOURCE_NATIVE_ROLE_SLOTS
        | set(_SOURCE_NATIVE_MEMBER_ABI)
        | set(_SOURCE_NATIVE_DISCRIMINATOR_ABI)
    )
    if set(rows) != expected_slots:
        raise ValueError("Source native binding slots are incomplete")

    role_tokens: dict[str, str] = {}
    for slot in _SOURCE_NATIVE_ROLE_SLOTS:
        row = rows[slot]
        role = row.get("role")
        if (
            set(row) != {"kind", "slot", "role"}
            or row.get("kind") != "role"
            or not isinstance(role, str)
            or not role
            or role not in index.role_members
            or role in role_tokens.values()
        ):
            raise ValueError("Source native role binding is invalid")
        role_tokens[slot] = role
    if role_tokens["source.root"] != index.root_role:
        raise ValueError("Source root native binding is invalid")

    member_tokens: dict[str, str] = {}
    for slot, (owner_slot, shape, target_slots) in _SOURCE_NATIVE_MEMBER_ABI.items():
        row = rows[slot]
        member = row.get("member")
        targets = row.get("target_slots")
        owner = role_tokens[owner_slot]
        if (
            set(row)
            != {"kind", "slot", "owner_slot", "member", "shape", "target_slots"}
            or row.get("kind") != "member"
            or row.get("owner_slot") != owner_slot
            or row.get("shape") != shape
            or not isinstance(targets, Sequence)
            or isinstance(targets, (str, bytes))
            or tuple(targets) != target_slots
            or not isinstance(member, str)
            or not member
            or member not in index.role_members[owner]
        ):
            raise ValueError("Source native member binding is invalid")
        fields = _source_member_schemas(index, owner, member)
        expected_targets = frozenset(role_tokens[target] for target in target_slots)
        if (
            not fields
            or not all(_source_member_shape_is_closed(field, shape) for field in fields)
            or index.child_roles.get((owner, member), frozenset()) != expected_targets
        ):
            raise ValueError("Source native member shape is invalid")
        member_tokens[slot] = member

    for owner_slot, owner in role_tokens.items():
        bound_members = {
            member_tokens[slot]
            for slot, (candidate_owner, _shape, _targets) in (
                _SOURCE_NATIVE_MEMBER_ABI.items()
            )
            if candidate_owner == owner_slot
        }
        if bound_members != set(index.role_members[owner]):
            raise ValueError("Source native member bindings do not close their role")

    discriminator_values: dict[str, JsonValue] = {}
    for slot, (
        owner_slot,
        member_slot,
        _internal_value,
    ) in _SOURCE_NATIVE_DISCRIMINATOR_ABI.items():
        row = rows[slot]
        owner = role_tokens[owner_slot]
        member = member_tokens[member_slot]
        if (
            set(row) != {"kind", "slot", "owner_slot", "member", "value"}
            or row.get("kind") != "discriminator"
            or row.get("owner_slot") != owner_slot
            or row.get("member") != member
        ):
            raise ValueError("Source native discriminator binding is invalid")
        fields = _source_member_schemas(index, owner, member)
        if not fields or any(field.get("const") != row["value"] for field in fields):
            raise ValueError("Source native discriminator value is invalid")
        discriminator_values[slot] = cast(JsonValue, row["value"])

    return SourceNativeBindingIndex(
        roles=MappingProxyType(role_tokens),
        members=MappingProxyType(member_tokens),
        discriminators=MappingProxyType(discriminator_values),
    )


def derive_default_source_native_bindings(
    kernel: Mapping[str, Any], language_bundle: Mapping[str, Any]
) -> SourceNativeBindingIndex:
    """Derive the one default Resolution profile's Source-native ABI bindings."""
    profiles = [
        profile
        for profile in language_bundle["language"]["resolution_profiles"]
        if isinstance(profile, Mapping) and profile.get("default") is True
    ]
    if len(profiles) != 1:
        raise ValueError("Source native bindings require one default profile")
    return derive_source_native_bindings(
        derive_source_semantic_index(kernel, language_bundle),
        profiles[0].get("source_native_bindings"),
    )


def derive_source_semantic_index(
    kernel: Mapping[str, Any], language_bundle: Mapping[str, Any]
) -> SourceSemanticIndex:
    """Validate generic annotations and derive the Source Schema's semantic index."""
    annotation_contract = _semantic_annotation_contract(kernel)
    if not _annotation_contract_is_supported(annotation_contract):
        raise ValueError("Kernel Source semantic annotation contract is unsupported")
    source = _source_schema(kernel, language_bundle)
    if not isinstance(source.get(_ROLE), str) or not source[_ROLE]:
        raise ValueError("Source Schema root has no semantic role")
    role_members: dict[str, frozenset[str]] = {}
    anchors: dict[str, list[Mapping[str, Any]]] = {}
    children: dict[tuple[str, str], set[str]] = {}

    def reject_native_payload_annotations(node: Any) -> None:
        if not isinstance(node, Mapping):
            return
        if set(node) & {_ROLE, _MEMBER, _NATIVE}:
            raise ValueError("native Source payload contains semantic annotations")
        properties = node.get("properties", {})
        if isinstance(properties, Mapping):
            for child in properties.values():
                reject_native_payload_annotations(child)
        items = node.get("items")
        if items is not None:
            reject_native_payload_annotations(items)
        branches = node.get("oneOf", [])
        if isinstance(branches, Sequence) and not isinstance(branches, (str, bytes)):
            for branch in branches:
                reject_native_payload_annotations(branch)

    def walk(
        node: Any,
        *,
        property_schema: bool = False,
        inherited_role: str | None = None,
        inherited_members: Mapping[str, str] | None = None,
        inherited_properties: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        if not isinstance(node, Mapping):
            raise ValueError("Source Schema semantic node is not an object")
        if _MEMBER in node and not property_schema:
            raise ValueError("semantic_member is outside an object property")
        explicit = node.get(_ROLE)
        if explicit is not None and (
            not isinstance(explicit, str) or not explicit or inherited_role is not None
        ):
            raise ValueError("Source role placement is invalid")
        effective_role = cast(str | None, explicit) or inherited_role
        properties = node.get("properties")
        member_map: dict[str, str] = {}
        sibling_schemas: dict[str, Mapping[str, Any]] = {}
        if properties is not None:
            if not isinstance(properties, Mapping):
                raise ValueError("Source object properties are malformed")
            if effective_role is None:
                raise ValueError("Source object has no semantic role")
            for authored, child in properties.items():
                if not isinstance(authored, str) or not isinstance(child, Mapping):
                    raise ValueError("Source semantic property is malformed")
                member = child.get(_MEMBER)
                if not isinstance(member, str) or not member:
                    raise ValueError("Source role member is missing or empty")
                if member in sibling_schemas:
                    raise ValueError("Source role has a duplicate semantic member")
                member_map[authored] = member
                sibling_schemas[member] = (
                    {**inherited_properties[authored], **child}
                    if inherited_properties is not None
                    and authored in inherited_properties
                    else child
                )
            if inherited_members is not None and any(
                inherited_members.get(authored) != member
                for authored, member in member_map.items()
            ):
                raise ValueError(
                    "Source oneOf branch changes inherited member ownership"
                )
        if explicit is not None:
            if properties is None or not member_map:
                raise ValueError("Source role has no semantic members")
            members = frozenset(member_map.values())
            previous = role_members.setdefault(cast(str, explicit), members)
            if previous != members:
                raise ValueError(
                    "Source role occurrences disagree on member completeness"
                )
            anchors.setdefault(cast(str, explicit), []).append(node)
        for authored, child in (
            cast(Mapping[str, Mapping[str, Any]], properties).items()
            if isinstance(properties, Mapping)
            else ()
        ):
            member = member_map[authored]
            selected_child: Mapping[str, Any] = child
            if inherited_properties is not None and authored in inherited_properties:
                selected_child = {**inherited_properties[authored], **child}
            native_contract = selected_child.get(_NATIVE)
            if native_contract is not None:
                if not _native_contract_is_closed(
                    kernel,
                    language_bundle,
                    selected_child,
                    sibling_schemas,
                    native_contract,
                    annotation_contract["native_contract"],
                ):
                    raise ValueError(
                        "Source semantic native contract is not closed: "
                        f"{effective_role}.{member}"
                    )
                reject_native_payload_annotations(_without_annotations(selected_child))
            else:
                child_node = selected_child.get("items", selected_child)
                if isinstance(child_node, Mapping):
                    nested_roles = _entry_roles(child_node)
                    if nested_roles:
                        children.setdefault(
                            (cast(str, effective_role), member), set()
                        ).update(nested_roles)
                walk(selected_child, property_schema=True)
        items = node.get("items")
        if items is not None and properties is None:
            walk(items)
        branches = node.get("oneOf")
        if branches is not None:
            if (
                not isinstance(branches, Sequence)
                or isinstance(branches, (str, bytes))
                or not branches
            ):
                raise ValueError("Source oneOf is empty or malformed")
            for branch in branches:
                walk(
                    branch,
                    inherited_role=effective_role if properties is not None else None,
                    inherited_members=member_map or inherited_members,
                    inherited_properties={
                        **(inherited_properties or {}),
                        **(
                            cast(Mapping[str, Mapping[str, Any]], properties)
                            if isinstance(properties, Mapping)
                            else {}
                        ),
                    },
                )

    walk(source)
    return SourceSemanticIndex(
        schema=source,
        root_role=cast(str, source[_ROLE]),
        role_anchors=MappingProxyType(
            {role: tuple(values) for role, values in anchors.items()}
        ),
        role_members=MappingProxyType(dict(role_members)),
        child_roles=MappingProxyType(
            {key: frozenset(values) for key, values in children.items()}
        ),
    )


def source_schema_member(
    schema: Mapping[str, Any], member: str
) -> tuple[str, Mapping[str, Any]]:
    matches = [
        (name, child)
        for name, child in cast(
            Mapping[str, Mapping[str, Any]], schema["properties"]
        ).items()
        if child.get(_MEMBER) == member
    ]
    if len(matches) != 1:
        raise ValueError("Source semantic member has no unique authored address")
    return matches[0]


def source_native_contract_values(
    language_bundle: Mapping[str, Any],
    schema: Mapping[str, Any],
    member: str,
) -> tuple[JsonValue, ...]:
    """Read one admitted Source native contract from its LDB-owned projection."""
    _, field = source_schema_member(schema, member)
    contract = field.get(_NATIVE)
    if not isinstance(contract, Mapping):
        raise ValueError("Source semantic member has no native contract")
    location = contract.get("value_location")
    authority_path = contract.get("language_reference")
    if not isinstance(location, Mapping) or not isinstance(authority_path, str):
        raise ValueError("Source native contract has no language value projection")
    selected = field
    sibling = location.get("semantic_member")
    if sibling is not None:
        if not isinstance(sibling, str):
            raise ValueError("Source native contract sibling is malformed")
        _, selected = source_schema_member(schema, sibling)
    keyword = location.get("keyword")
    if keyword == "const":
        values: tuple[JsonValue, ...] = (cast(JsonValue, selected["const"]),)
    elif keyword == "enum":
        values = tuple(cast(Sequence[JsonValue], selected["enum"]))
    else:
        raise ValueError("Source native contract value location is unsupported")
    owner = _authority_path({"unused": True}, language_bundle, authority_path)
    owner_values = (
        tuple(cast(Sequence[JsonValue], owner))
        if isinstance(owner, Sequence) and not isinstance(owner, (str, bytes))
        else (cast(JsonValue, owner),)
    )
    if _canonical_set(values) != _canonical_set(owner_values):
        raise ValueError("Source native contract disagrees with its LDB owner")
    return deepcopy(values)


def source_semantic_selector(
    schema: Mapping[str, Any], selector: Sequence[str]
) -> list[str | None]:
    candidates = [schema]
    authored: list[str | None] = []
    for member in selector:
        alternatives = [
            node for candidate in candidates for node in _object_alternatives(candidate)
        ]
        if member == "*":
            candidates = [
                cast(Mapping[str, Any], node["items"])
                for node in alternatives
                if isinstance(node.get("items"), Mapping)
            ]
            if not candidates:
                raise ValueError("Source semantic wildcard has no array owner")
            authored.append(None)
            continue
        children = [
            (name, child)
            for node in alternatives
            for name, child in cast(
                Mapping[str, Mapping[str, Any]], node.get("properties", {})
            ).items()
            if child.get(_MEMBER) == member
        ]
        names = {name for name, _ in children}
        if len(names) != 1:
            raise ValueError("Source semantic selector has no unique authored member")
        authored.append(next(iter(names)))
        candidates = [child for _, child in children]
    return authored


@dataclass(frozen=True)
class SourceProjection:
    value: dict[str, Any]
    authored_paths: dict[str, str]
    authored_source: dict[str, Any]

    def authored_parts(self, parts: tuple[Any, ...]) -> tuple[Any, ...]:
        pointer = self.authored_pointer(_pointer(parts))
        value: Any = self.authored_source
        result: list[Any] = []
        for encoded in pointer.split("/")[1:]:
            member = encoded.replace("~1", "/").replace("~0", "~")
            key: Any = int(member) if isinstance(value, list) else member
            value = value[key]
            result.append(key)
        return tuple(result)

    def authored_pointer(self, pointer: str) -> str:
        parts = pointer.split("/")
        for count in range(len(parts), 0, -1):
            prefix = "/".join(parts[:count])
            if prefix in self.authored_paths:
                return (
                    self.authored_paths[prefix] + "/".join(["", *parts[count:]])
                    if count < len(parts)
                    else self.authored_paths[prefix]
                )
        raise ValueError("Semantic Source pointer has no authored owner")


def semantic_source_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Project semantic names using only the admitted Source Schema annotations."""

    def walk(node: Mapping[str, Any]) -> dict[str, Any]:
        result = deepcopy(dict(node))
        properties = node.get("properties")
        if isinstance(properties, Mapping):
            projected: dict[str, Any] = {}
            names: dict[str, str] = {}
            for authored, child in properties.items():
                if not isinstance(child, Mapping):
                    raise ValueError("Source semantic property is malformed")
                member = child[_MEMBER]
                names[authored] = member
                projected[member] = (
                    deepcopy(dict(child)) if _NATIVE in child else walk(child)
                )
            result["properties"] = projected
            required = node.get("required")
            if isinstance(required, Sequence) and not isinstance(
                required, (str, bytes)
            ):
                result["required"] = [names[name] for name in required]
        items = node.get("items")
        if isinstance(items, Mapping):
            result["items"] = walk(items)
        branches = node.get("oneOf")
        if isinstance(branches, Sequence) and not isinstance(branches, (str, bytes)):
            result["oneOf"] = [walk(branch) for branch in branches]
        return result

    return walk(schema)


def _native_abi_source_schema(
    schema: Mapping[str, Any], bindings: SourceNativeBindingIndex
) -> dict[str, Any]:
    """Project an authored Schema to the fixed host ABI used by reverse authoring."""
    role_slots = {role: slot for slot, role in bindings.roles.items()}
    member_slots = {
        (owner_slot, member): slot
        for slot, member in bindings.members.items()
        for owner_slot, _shape, _targets in [_SOURCE_NATIVE_MEMBER_ABI[slot]]
    }
    discriminator_slots = {
        (owner_slot, member_slot): internal_value
        for owner_slot, member_slot, internal_value in (
            value for value in _SOURCE_NATIVE_DISCRIMINATOR_ABI.values()
        )
    }

    def walk(
        node: Mapping[str, Any], inherited_role: str | None = None
    ) -> dict[str, Any]:
        result = deepcopy(dict(node))
        role = node.get(_ROLE)
        effective_role = role if isinstance(role, str) else inherited_role
        properties = node.get("properties")
        names: dict[str, str] = {}
        if isinstance(properties, Mapping):
            if effective_role is None or effective_role not in role_slots:
                raise ValueError("Source Schema object has no bound native role")
            owner_slot = role_slots[effective_role]
            projected: dict[str, Any] = {}
            for authored, child in properties.items():
                if not isinstance(child, Mapping):
                    raise ValueError("Source Schema property is malformed")
                member = child[_MEMBER]
                member_slot = member_slots.get((owner_slot, member))
                if member_slot is None:
                    raise ValueError("Source Schema member has no bound native slot")
                internal_member = member_slot.rsplit(".", 1)[1]
                names[authored] = internal_member
                projected_child = (
                    deepcopy(dict(child)) if _NATIVE in child else walk(child)
                )
                discriminator = discriminator_slots.get((owner_slot, member_slot))
                if discriminator is not None:
                    projected_child["const"] = deepcopy(discriminator)
                projected[internal_member] = projected_child
            result["properties"] = projected
            required = node.get("required")
            if isinstance(required, Sequence) and not isinstance(
                required, (str, bytes)
            ):
                result["required"] = [names[name] for name in required]
        items = node.get("items")
        if isinstance(items, Mapping):
            result["items"] = walk(items)
        branches = node.get("oneOf")
        if isinstance(branches, Sequence) and not isinstance(branches, (str, bytes)):
            result["oneOf"] = [
                walk(
                    branch,
                    effective_role if isinstance(properties, Mapping) else None,
                )
                for branch in branches
            ]
        return result

    return walk(schema)


def _map_source_value(
    value: dict[str, Any],
    schema: Mapping[str, Any],
    bindings: SourceNativeBindingIndex,
    *,
    write_authored: bool,
) -> tuple[dict[str, Any], dict[str, str]]:
    addresses: dict[str, str] = {}
    role_slots = {role: slot for slot, role in bindings.roles.items()}
    member_slots = {
        (owner_slot, member): slot
        for slot, member in bindings.members.items()
        for owner_slot, _shape, _targets in [_SOURCE_NATIVE_MEMBER_ABI[slot]]
    }
    discriminator_slots = {
        (owner_slot, member_slot): (slot, internal_value)
        for slot, (owner_slot, member_slot, internal_value) in (
            _SOURCE_NATIVE_DISCRIMINATOR_ABI.items()
        )
    }

    def selection_schema(candidate: Mapping[str, Any]) -> dict[str, Any]:
        """Admit only the unresolved Operation result hole during branch selection."""
        result = deepcopy(dict(candidate))
        operation_role = bindings.roles["source.operation_call"]
        result_member = bindings.members["source.operation_call.result"]

        def relax(node: dict[str, Any], inherited_role: str | None = None) -> None:
            role = node.get(_ROLE, inherited_role)
            properties = node.get("properties")
            if isinstance(properties, dict):
                for name, child in list(properties.items()):
                    if not isinstance(child, dict):
                        continue
                    if role == operation_role and child.get(_MEMBER) == result_member:
                        properties[name] = {
                            "anyOf": [
                                child,
                                {"type": "object", "maxProperties": 0},
                            ],
                        }
                    else:
                        relax(child)
            items = node.get("items")
            if isinstance(items, dict):
                relax(items)
            branches = node.get("oneOf")
            if isinstance(branches, list):
                for branch in branches:
                    if isinstance(branch, dict):
                        relax(
                            branch,
                            role if isinstance(properties, dict) else inherited_role,
                        )

        relax(result)
        return result

    def walk(
        current: Any,
        node: Mapping[str, Any],
        wire: tuple[Any, ...],
        semantic: tuple[Any, ...],
        *,
        defer_unresolved_contract: bool = False,
    ) -> Any:
        addresses[_pointer(semantic)] = _pointer(wire)
        if "oneOf" in node and "properties" not in node:
            matching = selection_schema(
                _native_abi_source_schema(node, bindings) if write_authored else node
            )
            branches = [
                branch
                for branch, test in zip(node["oneOf"], matching["oneOf"], strict=True)
                if jsonschema.Draft202012Validator(test).is_valid(current)
            ]
            if (
                not branches
                and isinstance(current, Mapping)
                and not current
                and defer_unresolved_contract
            ):
                # An empty unresolved Operation contract carries no Source-owned
                # token to translate. Leave it for the operation lookup so it can
                # report the stable unresolved-name diagnostic.
                return {}
            if len(branches) != 1:
                raise ValueError("Source value has no unique semantic branch")
            return walk(
                current,
                branches[0],
                wire,
                semantic,
                defer_unresolved_contract=defer_unresolved_contract,
            )
        properties = node.get("properties")
        if isinstance(properties, Mapping):
            if not isinstance(current, Mapping):
                raise ValueError("Source object is malformed")
            role = node.get(_ROLE)
            if not isinstance(role, str) or role not in role_slots:
                raise ValueError("Source object has no bound native role")
            owner_slot = role_slots[role]
            expected_members = {
                (
                    member_slots[(owner_slot, child[_MEMBER])].rsplit(".", 1)[-1]
                    if write_authored
                    else authored
                )
                for authored, child in properties.items()
            }
            if node.get("unevaluatedProperties") is False and not set(current) <= (
                expected_members
            ):
                raise ValueError("Source object has an unknown member")
            result: dict[str, Any] = {}
            for authored, child in properties.items():
                member = child[_MEMBER]
                member_slot = member_slots.get((owner_slot, member))
                if member_slot is None:
                    raise ValueError("Source member has no bound native slot")
                internal_member = member_slot.rsplit(".", 1)[1]
                addresses[_pointer(semantic + (internal_member,))] = _pointer(
                    wire + (authored,)
                )
                intake = internal_member if write_authored else authored
                if intake not in current:
                    continue
                mapped = (
                    deepcopy(current[intake])
                    if _NATIVE in child
                    else walk(
                        current[intake],
                        child,
                        wire + (authored,),
                        semantic + (internal_member,),
                        defer_unresolved_contract=(
                            member_slot == "source.operation_call.result"
                        ),
                    )
                )
                discriminator = discriminator_slots.get((owner_slot, member_slot))
                if discriminator is not None:
                    discriminator_slot, internal_value = discriminator
                    language_value = bindings.discriminators[discriminator_slot]
                    if write_authored:
                        if mapped != internal_value:
                            raise ValueError("Source discriminator has no native value")
                        mapped = deepcopy(language_value)
                    else:
                        if mapped != language_value:
                            raise ValueError(
                                "Source discriminator binding is incoherent"
                            )
                        mapped = deepcopy(internal_value)
                result[authored if write_authored else internal_member] = mapped
            return result
        items = node.get("items")
        if isinstance(items, Mapping):
            return [
                walk(item, items, wire + (i,), semantic + (i,))
                for i, item in enumerate(current)
            ]
        return deepcopy(current)

    return walk(value, schema, (), ()), addresses


def project_source_value(
    source: dict[str, Any],
    schema: Mapping[str, Any],
    bindings: SourceNativeBindingIndex,
) -> SourceProjection:
    value, addresses = _map_source_value(source, schema, bindings, write_authored=False)
    return SourceProjection(value, addresses, source)


def author_source_value(
    value: dict[str, Any],
    schema: Mapping[str, Any],
    bindings: SourceNativeBindingIndex,
) -> dict[str, Any]:
    source, _ = _map_source_value(value, schema, bindings, write_authored=True)
    return source
