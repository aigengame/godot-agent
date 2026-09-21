"""Authority-driven Package Release runtime-semantic projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue


def package_runtime_semantic_closure(
    package: dict[str, Any],
    kernel: dict[str, Any],
) -> list[dict[str, JsonValue]]:
    """Project one Package Release to its executable semantic closure."""
    projection = kernel["meta_format"]["package_release"][
        "semantic_identity_projection"
    ]
    notation_source = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["source_notation"]["operation_source"]
    path_inventory_member = projection.get("path_inventory_member")
    source_member = projection.get("source_member")
    path_member = projection.get("path_member")
    if not all(
        isinstance(member, str) and member
        for member in (
            path_inventory_member,
            source_member,
            path_member,
        )
    ):
        raise ValueError("Package semantic projection authority is malformed")

    runtime_paths = package.get(cast(str, path_inventory_member))
    closure = package.get(cast(str, source_member))
    if (
        not isinstance(runtime_paths, list)
        or not runtime_paths
        or not all(isinstance(path, str) and path for path in runtime_paths)
        or len(runtime_paths) != len(set(runtime_paths))
        or not isinstance(closure, list)
    ):
        raise ValueError("Package semantic projection inventory is malformed")

    projected = deepcopy(
        [
            entry
            for entry in closure
            if isinstance(entry, dict)
            and entry.get(cast(str, path_member)) in set(runtime_paths)
        ]
    )
    for entry in projected:
        if entry[cast(str, path_member)] != notation_source["authority_path"]:
            continue
        definitions = entry.get("definitions")
        if not isinstance(definitions, list):
            raise ValueError("Package semantic closure definitions are malformed")
        for definition in definitions:
            if not isinstance(definition, dict):
                continue
            extensions = definition.get("extensions")
            if not isinstance(extensions, dict):
                continue
            retained = {
                key: value
                for key, value in extensions.items()
                if key != notation_source["extension_member"]
            }
            if retained:
                definition["extensions"] = retained
            else:
                definition.pop("extensions")
    return cast(list[dict[str, JsonValue]], projected)
