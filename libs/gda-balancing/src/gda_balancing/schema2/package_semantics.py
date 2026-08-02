"""Authority-driven Package Release runtime-semantic projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from gda_balancing.schema2.canonical import JsonValue


def package_runtime_semantic_closure(
    package: dict[str, Any],
    projection: dict[str, Any],
) -> list[dict[str, JsonValue]]:
    """Project one Package Release to its executable semantic closure."""
    path_inventory_member = projection.get("path_inventory_member")
    source_member = projection.get("source_member")
    path_member = projection.get("path_member")
    extension_inventory_member = projection.get("extension_inventory_member")
    if not all(
        isinstance(member, str) and member
        for member in (
            path_inventory_member,
            source_member,
            path_member,
            extension_inventory_member,
        )
    ):
        raise ValueError("Package semantic projection authority is malformed")

    runtime_paths = package.get(cast(str, path_inventory_member))
    closure = package.get(cast(str, source_member))
    excluded_extensions = package.get(cast(str, extension_inventory_member))
    if (
        not isinstance(runtime_paths, list)
        or not runtime_paths
        or not all(isinstance(path, str) and path for path in runtime_paths)
        or len(runtime_paths) != len(set(runtime_paths))
        or not isinstance(closure, list)
        or not isinstance(excluded_extensions, list)
        or not all(
            isinstance(extension, str) and extension
            for extension in excluded_extensions
        )
        or len(excluded_extensions) != len(set(excluded_extensions))
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
    found_extensions: set[str] = set()
    excluded = set(excluded_extensions)
    for entry in projected:
        definitions = entry.get("definitions")
        if not isinstance(definitions, list):
            raise ValueError("Package semantic closure definitions are malformed")
        for definition in definitions:
            if not isinstance(definition, dict):
                continue
            extensions = definition.get("extensions")
            if not isinstance(extensions, dict):
                continue
            found_extensions.update(excluded & set(extensions))
            retained = {
                key: value for key, value in extensions.items() if key not in excluded
            }
            if retained:
                definition["extensions"] = retained
            else:
                definition.pop("extensions")
    if found_extensions != excluded:
        raise ValueError("Package semantic extension exclusion is stale")
    return cast(list[dict[str, JsonValue]], projected)
