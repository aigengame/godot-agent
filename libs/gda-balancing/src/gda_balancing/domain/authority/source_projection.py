"""Bind admitted Source Schema objects to their finite semantic roles."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import jsonschema


def _pointer(parts: tuple[Any, ...]) -> str:
    return "".join("/" + str(x).replace("~", "~0").replace("/", "~1") for x in parts)


def source_role_contract(kernel: dict[str, Any]) -> dict[str, Any]:
    return kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "source_notation"
    ]["semantic_roles"]


def _object_alternatives(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect Schema branches at this same instance, without evaluating a grammar."""
    result = [schema]
    for child in schema.get("oneOf", []):
        result.extend(_object_alternatives(child))
    return result


def _native_source_schema(
    kernel: dict[str, Any], schema: dict[str, Any], native: str
) -> bool:
    """Verify only the existing native transport boundary; values keep their owner."""
    if native == "canonical-value":
        # Assignment payloads keep their existing Kernel canonical-value owner.
        return (
            kernel["meta_format"]["fact"]["field_contracts"]["quantity-symbol"][
                "value_policy"
            ]["type"]
            == "canonical-value"
        )
    if native == "closed-interval":
        from gda_balancing.domain.authority.rir_projection import _owned_contract_schema

        contract = kernel["meta_format"]["fact"]["field_contracts"]["quantity-symbol"][
            "domain"
        ]
        expected = _owned_contract_schema(contract)
        return (
            schema.get("type") == "object"
            and set(schema.get("properties", {})) == set(expected["properties"])
            and set(schema.get("required", [])) == set(expected["required"])
            and all(
                child.get("type") == "integer"
                for child in schema["properties"].values()
            )
        )
    if native == "boolean-domain":
        domain = kernel["meta_format"]["runtime_program"]["fixed_value_contracts"][
            "kernel-boolean"
        ]["domain"]
        return (
            schema.get("type") == "object"
            and set(schema.get("properties", {})) == set(domain)
            and set(schema.get("required", [])) == set(domain)
            and all(
                schema["properties"][name].get("const") == value
                for name, value in domain.items()
            )
        )
    if native != "typed-literal":
        return False
    typed = kernel["meta_format"]["literal_typing"]["typed_envelope_profile"]
    for branch in _object_alternatives(schema):
        if branch.get("type") != "object":
            continue
        if set(branch.get("properties", {})) != set(
            typed["admission"]["envelope_members"]
        ) or set(branch.get("required", [])) != set(
            typed["admission"]["envelope_members"]
        ):
            return False
        reference = branch["properties"][typed["type_member"]]
        nominal = typed["admission"]["nominal_type_reference"]
        fields = reference.get("properties", {})
        coordinate = set(nominal["coordinate_members"])
        if not coordinate <= set(fields) <= coordinate | {
            nominal["optional_kind_member"]
        } or not coordinate <= set(reference.get("required", [])):
            return False
        if any(fields[name].get("type") != "string" for name in coordinate):
            return False
        marker = nominal["optional_kind_member"]
        if (
            marker in fields
            and fields[marker].get("const") != nominal["optional_kind_value"]
        ):
            return False
    return True


def source_schema_member(
    schema: dict[str, Any], member: str
) -> tuple[str, dict[str, Any]]:
    """Locate a semantic member in its one annotated object."""
    matches = [
        (name, child)
        for name, child in schema["properties"].items()
        if child.get("semantic_member") == member
    ]
    if len(matches) != 1:
        raise ValueError("Source semantic member has no unique authored address")
    return matches[0]


def source_semantic_selector(
    schema: dict[str, Any], selector: list[str]
) -> list[str | None]:
    """Resolve semantic member segments to one authored path, without reading values."""
    candidates = [schema]
    authored: list[str | None] = []
    for member in selector:
        alternatives = [
            node for candidate in candidates for node in _object_alternatives(candidate)
        ]
        if member == "*":
            candidates = [node["items"] for node in alternatives if "items" in node]
            if not candidates:
                raise ValueError("Source semantic wildcard has no array owner")
            authored.append(None)
            continue
        children = [
            (name, child)
            for node in alternatives
            for name, child in node.get("properties", {}).items()
            if child.get("semantic_member") == member
        ]
        names = {name for name, _ in children}
        if len(names) != 1:
            raise ValueError("Source semantic selector has no unique authored member")
        authored.append(next(iter(names)))
        candidates = [child for _, child in children]
    return authored


def source_member_paths(
    schema: dict[str, Any], role: str, member: str
) -> set[tuple[str, ...]]:
    """Read authored addresses from annotations for existing Resolution constraints."""
    result: set[tuple[str, ...]] = set()

    def walk(node: dict[str, Any], path: tuple[str, ...]) -> None:
        if node.get("semantic_role") == role:
            name, _ = source_schema_member(node, member)
            result.add(path + (name,))
        for name, child in node.get("properties", {}).items():
            walk(child, path + (name,))
        if "items" in node:
            walk(node["items"], path)
        for child in node.get("oneOf", []):
            walk(child, path)

    walk(schema, ())
    return result


def _source_child_roles(kernel: dict[str, Any], role: str, member: str) -> Any:
    """Read contextual ownership, reusing the existing Formula role families."""
    law = source_role_contract(kernel)
    if (
        role == "conditional"
        and member
        in kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
            "rir_structure"
        ]["containers"]["conditional_operands"]["required_members"]
    ):
        return {"family": "operand_kinds"}
    return law["children"].get(role, {}).get(member)


def _source_expected_roles(kernel: dict[str, Any], contract: Any) -> set[str]:
    law = source_role_contract(kernel)
    formula = kernel["meta_format"]["formula_resolution"]
    if isinstance(contract, list):
        return set(contract)
    if "callee" in contract:
        return {
            item["role"]
            for item in formula["static_callees"]
            if item["node"] == contract["callee"]
        }
    family = contract["family"]
    discriminator = "node" if family == "body_nodes" else "kind"
    result = set()
    for value in formula[family]:
        matches = [
            role
            for role, owner in law["roles"].items()
            if owner.get("discriminator", {}).get(discriminator) == value
            and role != "inline-parameter"
        ]
        if len(matches) != 1:
            raise ValueError("Kernel Formula family has no unique Source semantic role")
        result.add(matches[0])
    return result


def _schema_object_roles(node: dict[str, Any]) -> set[str]:
    if "semantic_role" in node:
        return {node["semantic_role"]}
    if "oneOf" in node:
        return set().union(*(_schema_object_roles(child) for child in node["oneOf"]))
    raise ValueError("Source object has no contextual semantic owner")


def validate_source_roles(kernel: dict[str, Any], schema: dict[str, Any]) -> bool:
    """Close semantic annotations; JSON Schema alone owns structural validation."""
    law = source_role_contract(kernel)
    seen: set[str] = set()

    def walk(
        node: dict[str, Any],
        inherited: dict[str, str] | None = None,
        native: bool = False,
        property_member: bool = False,
    ) -> None:
        if "semantic_member" in node and not property_member:
            raise ValueError("Source member annotation is outside an object property")
        if native:
            if "semantic_role" in node or "semantic_member" in node:
                raise ValueError("Native payload internals have a Source annotation")
            for child in node.get("properties", {}).values():
                walk(child, native=True)
            if "items" in node:
                walk(node["items"], native=True)
            for child in node.get("oneOf", []):
                walk(child, native=True)
            return
        role = node.get("semantic_role")
        if role is not None:
            if inherited is not None or role not in law["roles"]:
                raise ValueError(
                    "Source semantic object has duplicate or unknown ownership"
                )
            seen.add(role)
        owner = law["roles"][role] if role is not None else None
        mapping = {
            name: child.get("semantic_member")
            for name, child in node.get("properties", {}).items()
        }
        if mapping:
            if owner is None and inherited is None:
                raise ValueError("Source object has no semantic owner")
            if any(member is None for member in mapping.values()) or len(
                set(mapping.values())
            ) != len(mapping):
                raise ValueError(
                    "Source member has missing or duplicate semantic ownership"
                )
            if owner is not None and set(mapping.values()) != set(owner["members"]):
                raise ValueError("Source role has missing or extra semantic members")
            if inherited is not None and any(
                inherited.get(name) != member for name, member in mapping.items()
            ):
                raise ValueError(
                    "Source same-instance branch assigns a different member owner"
                )
        for name, child in node.get("properties", {}).items():
            member = mapping[name]
            if role is not None:
                anchor = _source_child_roles(kernel, role, member)
                if anchor is not None:
                    selected = child
                    if isinstance(anchor, dict) and "items" in anchor:
                        if child.get("type") != "array":
                            raise ValueError(
                                "Source collection changes its semantic cardinality"
                            )
                        selected, anchor = child["items"], anchor["items"]
                    if _schema_object_roles(selected) != _source_expected_roles(
                        kernel, anchor
                    ):
                        raise ValueError(
                            "Source member is attached to a different semantic owner"
                        )
            native_kind = owner.get("native_members", {}).get(member) if owner else None
            if native_kind is not None:
                if not _native_source_schema(kernel, child, native_kind):
                    raise ValueError("Source payload changes its native boundary")
                payload = {
                    key: value
                    for key, value in child.items()
                    if key != "semantic_member"
                }
                walk(payload, native=True)
            else:
                if (
                    owner
                    and member in owner.get("discriminator", {})
                    and child.get("const") != owner["discriminator"][member]
                ):
                    raise ValueError(
                        "Source discriminator has a different semantic meaning"
                    )
                walk(child, property_member=True)
        if "items" in node:
            walk(node["items"])
        for child in node.get("oneOf", []):
            walk(child, mapping or inherited)

    try:
        if schema.get("semantic_role") != law["root"]:
            return False
        walk(schema)
        return seen == set(law["roles"])
    except (KeyError, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class SourceProjection:
    """One semantic Source with the exact authored address for each produced value."""

    value: dict[str, Any]
    authored_paths: dict[str, str]
    authored_source: dict[str, Any]

    def authored_parts(self, parts: tuple[Any, ...]) -> tuple[Any, ...]:
        """Locate a produced Source row in the original document."""
        pointer = self.authored_pointer(_pointer(parts))
        value: Any = self.authored_source
        result: list[Any] = []
        for encoded in pointer.split("/")[1:]:
            member = encoded.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                key: Any = int(member)
            else:
                key = member
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


def semantic_source_schema(
    kernel: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any]:
    """Project the one admitted grammar's property names for semantic values."""
    law = source_role_contract(kernel)

    def walk(
        node: dict[str, Any], owner: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        result = deepcopy(node)
        if "semantic_role" in node:
            owner = law["roles"][node["semantic_role"]]
        if "properties" in node:
            properties = {}
            names = {}
            for name, child in node["properties"].items():
                member = child["semantic_member"]
                names[name] = member
                native = owner and member in owner.get("native_members", {})
                properties[member] = deepcopy(child) if native else walk(child)
            result["properties"] = properties
            if "required" in node:
                result["required"] = [names[name] for name in node["required"]]
        if "items" in node:
            result["items"] = walk(node["items"])
        if "oneOf" in node:
            result["oneOf"] = [walk(child, owner) for child in node["oneOf"]]
        return result

    return walk(schema)


def _map_source_value(
    value: dict[str, Any],
    kernel: dict[str, Any],
    schema: dict[str, Any],
    *,
    write_authored: bool,
) -> tuple[dict[str, Any], dict[str, str]]:
    law = source_role_contract(kernel)
    addresses: dict[str, str] = {}

    def walk(
        value: Any,
        node: dict[str, Any],
        wire: tuple[Any, ...],
        semantic: tuple[Any, ...],
    ) -> Any:
        addresses[_pointer(semantic)] = _pointer(wire)
        if "oneOf" in node and "properties" not in node:
            matching = semantic_source_schema(kernel, node) if write_authored else node
            # Validation has already established oneOf uniqueness; use its matched branch.
            branch = next(
                branch
                for branch, test in zip(node["oneOf"], matching["oneOf"], strict=True)
                if jsonschema.Draft202012Validator(test).is_valid(value)
            )
            return walk(value, branch, wire, semantic)
        role = node.get("semantic_role")
        if role is not None:
            owner = law["roles"][role]
            result: dict[str, Any] = {}
            for name, child in node["properties"].items():
                member = child["semantic_member"]
                addresses[_pointer(semantic + (member,))] = _pointer(wire + (name,))
                intake = member if write_authored else name
                if intake not in value:
                    continue
                result[name if write_authored else member] = (
                    deepcopy(value[intake])
                    if member in owner.get("native_members", {})
                    else walk(
                        value[intake], child, wire + (name,), semantic + (member,)
                    )
                )
            return result
        if "items" in node:
            return [
                walk(item, node["items"], wire + (i,), semantic + (i,))
                for i, item in enumerate(value)
            ]
        return deepcopy(value)

    return walk(value, schema, (), ()), addresses


def project_source_value(
    source: dict[str, Any], kernel: dict[str, Any], schema: dict[str, Any]
) -> SourceProjection:
    """Project a validated authored Source without interpreting a second grammar."""
    value, addresses = _map_source_value(source, kernel, schema, write_authored=False)
    return SourceProjection(value, addresses, source)


def author_source_value(
    value: dict[str, Any], kernel: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any]:
    """Write produced semantic values through the same local Schema annotations."""
    source, _ = _map_source_value(value, kernel, schema, write_authored=True)
    return source
