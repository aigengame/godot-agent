"""Author a renamed witness only after complete semantic inventory validation.

This transforms inputs, not execution evidence. Fixed consumers must build new
artifacts and results; relabelled producer outputs are never returned as proof.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, cast

from gda_balancing.domain.authority.package_semantics import (
    package_runtime_semantic_closure,
)
from gda_balancing.domain.canonical import JsonValue, content_identity
from schema2_bootstrap_conformance_support import (
    _declared_identity_domain,
    _encoded,
    _identity_from_kernel,
)
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    _attached_language,
    _child,
    _formula_projections,
    _json_pointer_segments,
    _pointer_value,
    read_extension_inventory,
    source_formula_requests,
    validate_extension_inventory,
    validate_token_bijection,
)
from schema2_formula_conformance_support import render_body


def _rewrite_positions(
    value: Any,
    values: Mapping[str, str],
    keys: Mapping[str, str],
    pointer: str = "",
) -> Any:
    """Apply simultaneous edits at original positions, including key swaps."""
    if pointer in values:
        if not isinstance(value, str):
            raise InventoryRefusal("rename value does not identify a string")
        return values[pointer]
    if isinstance(value, list):
        return [
            _rewrite_positions(item, values, keys, _child(pointer, index))
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            path = _child(pointer, key)
            renamed = keys.get(path, key)
            if renamed in result:
                raise InventoryRefusal("renamed object key collides with a member")
            result[renamed] = _rewrite_positions(item, values, keys, path)
        return result
    return deepcopy(value)


def _member_path_values(
    graph: Mapping[str, Any], paths: Mapping[str, Mapping[int, str]]
) -> dict[str, str]:
    """Rewrite declared dot-path segments together at their original positions."""
    result = {}
    for pointer, edits in paths.items():
        segments = _pointer_value(graph, pointer).split(".")
        for index, target in edits.items():
            segments[index] = target
        result[pointer] = ".".join(segments)
    return result


def _renamed_pointer(pointer: str, keys: Mapping[str, str]) -> str:
    original = renamed = ""
    for member in _json_pointer_segments(pointer):
        original = _child(original, member)
        renamed = _child(renamed, keys.get(original, member))
    return renamed


def _json_pointer_values(
    graph: Mapping[str, Any], paths: Mapping[str, Mapping[int, str]]
) -> dict[str, str]:
    """Rewrite all declared pointer segments before encoding the result."""
    result = {}
    for pointer, edits in paths.items():
        segments = _json_pointer_segments(_pointer_value(graph, pointer))
        for index, target in edits.items():
            segments[index] = target
        result[pointer] = "".join(_child("", segment) for segment in segments)
    return result


def _render_formulas(
    kernel: dict[str, Any],
    candidate: dict[str, Any],
    bodies: Mapping[str, Any],
) -> None:
    language = _attached_language(kernel, candidate)
    requests = source_formula_requests(kernel, candidate)
    if set(bodies) != set(requests):
        raise InventoryRefusal("renamed Formula paths do not close")
    for pointer, body in bodies.items():
        request = requests[pointer]
        request["formula"]["expression"] = render_body(
            body, request, language, kernel=kernel
        )
    # Independently compare the rewritten expression with the actual authored
    # body. Copying the body into the expression would hide missed occurrences.
    _formula_projections(kernel, candidate)


def _reseal_authored_graph(kernel: dict[str, Any], graph: dict[str, Any]) -> None:
    """Update authored envelopes using the supplied Kernel's identity contracts."""
    packages, vectors, root = (
        graph["packages"],
        graph["vector_sets"],
        graph["ldb_root"],
    )
    package_ids = [package["id"] for package in packages]
    vector_ids = [vector["package_id"] for vector in vectors]
    descriptor_ids = [row["id"] for row in root["package_descriptors"]]
    if (
        len(package_ids) != len(set(package_ids))
        or sorted(package_ids) != sorted(vector_ids)
        or sorted(package_ids) != sorted(descriptor_ids)
    ):
        raise InventoryRefusal("package, vector, and root membership do not close")

    def seal(value: dict[str, Any], **selector: str) -> None:
        domain = _declared_identity_domain(kernel, **selector)
        identity = _identity_from_kernel(kernel, domain, value) if domain else None
        if identity is None:
            raise InventoryRefusal("unsupported authored identity contract")
        value["content_identity"] = identity

    by_package = {vector["package_id"]: vector for vector in vectors}
    meta = kernel["meta_format"]["package_release"]
    for package in packages:
        vector = by_package[package["id"]]
        seal(vector, collection="language_bundle.package_conformance_vector_sets")
        package["conformance_vectors"] = {
            "artifact_kind": vector["artifact_kind"],
            "byte_size": len(_encoded(vector)),
            "content_identity": vector["content_identity"],
        }
        # Sealing is authoring, not an independent semantic-consumer claim.
        closure = package_runtime_semantic_closure(package, kernel)
        package["semantic_identity"] = content_identity(
            meta["semantic_closure"]["domain"], cast(JsonValue, closure)
        )
        seal(package, collection="language_bundle.language.packages")
    order = kernel["meta_format"]["language_bundle"]["package_descriptor"][
        "canonical_order"
    ]
    packages.sort(key=lambda package: tuple(package[field] for field in order))
    graph["vector_sets"] = [by_package[package["id"]] for package in packages]
    root["kernel_identity"] = kernel["content_identity"]
    root["package_descriptors"] = [
        {
            "artifact_kind": package["artifact_kind"],
            "byte_size": len(_encoded(package)),
            "content_identity": package["content_identity"],
            "id": package["id"],
        }
        for package in packages
    ]
    seal(root, artifact="language-bundle")


def apply_extension_renaming(
    kernel: dict[str, Any],
    graph: Mapping[str, Any],
    pairs: Sequence[tuple[AuthorityToken, AuthorityToken]],
) -> dict[str, Any]:
    """Return renamed authored inputs; refuse every incomplete witness graph.

    The caller cannot supply an inventory with its gaps erased. Generated
    artifacts/results take part in coverage validation but are omitted from the
    returned inputs. Numerical vector expectations are never recalculated.
    """
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    validate_token_bijection(inventory, pairs)
    correspondence = dict(pairs)
    values: dict[str, str] = {}
    keys: dict[str, str] = {}
    formula_values: dict[str, dict[str, str]] = {}
    member_paths: dict[str, dict[int, str]] = {}
    json_pointers: dict[str, dict[int, str]] = {}
    for occurrence in inventory.occurrences:
        target = correspondence.get(occurrence.token, occurrence.token).name
        if occurrence.location == "formula":
            formula_values.setdefault(occurrence.pointer, {})[occurrence.projection] = (
                target
            )
        elif occurrence.location == "key":
            keys[occurrence.pointer] = target
        elif occurrence.location == "member-path":
            member_paths.setdefault(occurrence.pointer, {})[
                int(occurrence.projection)
            ] = target
        elif occurrence.location == "json-pointer":
            json_pointers.setdefault(occurrence.pointer, {})[
                int(occurrence.projection)
            ] = target
        else:
            values[occurrence.pointer] = target
    if values.keys() & (member_paths.keys() | json_pointers.keys()):
        raise InventoryRefusal("path also has a whole-value rename")
    if member_paths.keys() & json_pointers.keys():
        raise InventoryRefusal("path has conflicting encodings")
    values.update(_member_path_values(graph, member_paths))
    values.update(_json_pointer_values(graph, json_pointers))
    inputs = {k: v for k, v in graph.items() if k not in {"artifacts", "results"}}
    candidate = _rewrite_positions(inputs, values, keys)
    bodies = {
        _renamed_pointer(pointer, keys): _rewrite_positions(
            body, formula_values.get(pointer, {}), {}
        )
        for pointer, body in _formula_projections(kernel, graph).items()
    }
    _render_formulas(kernel, candidate, bodies)
    _reseal_authored_graph(kernel, candidate)
    return candidate
