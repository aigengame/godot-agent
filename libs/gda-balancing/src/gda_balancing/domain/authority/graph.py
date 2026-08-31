"""Closed in-memory projection of one sealed Schema 2.0 LDB graph."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def canonical_graph_members(
    root: dict[str, Any],
    package_releases: list[dict[str, Any]],
    package_conformance_vector_sets: list[dict[str, Any]],
    package_byte_sizes: list[int],
    vector_set_byte_sizes: list[int],
    descriptor_order: list[str],
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[int],
    list[int],
]:
    """Normalize descriptor transport order without changing graph semantics."""
    normalized_root = deepcopy(root)
    descriptors = normalized_root.get("package_descriptors")
    if (
        not isinstance(descriptors, list)
        or len(descriptors) != len(package_releases)
        or len(descriptors) != len(package_conformance_vector_sets)
        or len(descriptors) != len(package_byte_sizes)
        or len(descriptors) != len(vector_set_byte_sizes)
        or not descriptor_order
        or not all(isinstance(name, str) for name in descriptor_order)
        or not all(
            isinstance(descriptor, dict)
            and all(isinstance(descriptor.get(name), str) for name in descriptor_order)
            for descriptor in descriptors
        )
    ):
        return (
            normalized_root,
            deepcopy(package_releases),
            deepcopy(package_conformance_vector_sets),
            list(package_byte_sizes),
            list(vector_set_byte_sizes),
        )
    members = sorted(
        zip(
            descriptors,
            package_releases,
            package_conformance_vector_sets,
            package_byte_sizes,
            vector_set_byte_sizes,
            strict=True,
        ),
        key=lambda member: tuple(member[0][name] for name in descriptor_order),
    )
    normalized_root["package_descriptors"] = [
        deepcopy(descriptor)
        for descriptor, _release, _vectors, _package_size, _vector_size in members
    ]
    return (
        normalized_root,
        [
            deepcopy(release)
            for _descriptor, release, _vectors, _package_size, _vector_size in members
        ],
        [
            deepcopy(vectors)
            for _descriptor, _release, vectors, _package_size, _vector_size in members
        ],
        [size for _descriptor, _release, _vectors, size, _vector_size in members],
        [size for _descriptor, _release, _vectors, _package_size, size in members],
    )


class LanguageBundleGraph(dict[str, Any]):
    """One decoded sealed graph candidate with no derived language projection."""

    def __init__(
        self,
        *,
        root: dict[str, Any],
        package_releases: list[dict[str, Any]],
        package_conformance_vector_sets: list[dict[str, Any]],
        root_byte_size: int,
        package_byte_sizes: list[int],
        vector_set_byte_sizes: list[int],
    ) -> None:
        super().__init__(deepcopy(root))
        self.root = deepcopy(root)
        self.package_releases = deepcopy(package_releases)
        self.package_conformance_vector_sets = deepcopy(package_conformance_vector_sets)
        self.root_byte_size = root_byte_size
        self.package_byte_sizes = tuple(package_byte_sizes)
        self.vector_set_byte_sizes = tuple(vector_set_byte_sizes)

    def __deepcopy__(self, memo: dict[int, Any]) -> "LanguageBundleGraph":
        duplicate = LanguageBundleGraph(
            root=deepcopy(self.root, memo),
            package_releases=deepcopy(self.package_releases, memo),
            package_conformance_vector_sets=deepcopy(
                self.package_conformance_vector_sets, memo
            ),
            root_byte_size=self.root_byte_size,
            package_byte_sizes=list(self.package_byte_sizes),
            vector_set_byte_sizes=list(self.vector_set_byte_sizes),
        )
        memo[id(self)] = duplicate
        return duplicate


class LanguageBundleIndex(LanguageBundleGraph):
    """A derived lookup view carrying its exact admitted graph source."""

    def __init__(
        self,
        projection: dict[str, Any],
        *,
        root: dict[str, Any],
        package_releases: list[dict[str, Any]],
        package_conformance_vector_sets: list[dict[str, Any]],
        root_byte_size: int,
        package_byte_sizes: list[int],
        vector_set_byte_sizes: list[int],
    ) -> None:
        super().__init__(
            root=root,
            package_releases=package_releases,
            package_conformance_vector_sets=package_conformance_vector_sets,
            root_byte_size=root_byte_size,
            package_byte_sizes=package_byte_sizes,
            vector_set_byte_sizes=vector_set_byte_sizes,
        )
        self.clear()
        self.update(projection)

    def __deepcopy__(self, memo: dict[int, Any]) -> "LanguageBundleIndex":
        duplicate = LanguageBundleIndex(
            deepcopy(dict(self), memo),
            root=deepcopy(self.root, memo),
            package_releases=deepcopy(self.package_releases, memo),
            package_conformance_vector_sets=deepcopy(
                self.package_conformance_vector_sets, memo
            ),
            root_byte_size=self.root_byte_size,
            package_byte_sizes=list(self.package_byte_sizes),
            vector_set_byte_sizes=list(self.vector_set_byte_sizes),
        )
        memo[id(self)] = duplicate
        return duplicate


def derive_language_index(
    root: dict[str, Any],
    package_releases: list[dict[str, Any]],
    package_conformance_vector_sets: list[dict[str, Any]],
    required_language_members: list[str],
    *,
    root_byte_size: int,
    package_byte_sizes: list[int],
    vector_set_byte_sizes: list[int],
    descriptor_order: list[str],
) -> LanguageBundleIndex:
    """Derive the legacy-shaped consumer index from package-owned definitions."""
    (
        root,
        package_releases,
        package_conformance_vector_sets,
        package_byte_sizes,
        vector_set_byte_sizes,
    ) = canonical_graph_members(
        root,
        package_releases,
        package_conformance_vector_sets,
        package_byte_sizes,
        vector_set_byte_sizes,
        descriptor_order,
    )
    language: dict[str, Any] = {}
    for member in required_language_members:
        language[member] = {} if member == "quantity" else []

    diagnostics: list[Any] = []
    vectors: list[Any] = []

    def extend_unique(target: list[Any], definitions: list[Any]) -> None:
        """Coalesce equal definitions contributed by compatible releases."""
        for definition in definitions:
            if definition not in target:
                target.append(deepcopy(definition))

    for release, vector_set in zip(
        package_releases, package_conformance_vector_sets, strict=True
    ):
        closure = release.get("semantic_closure")
        if not isinstance(closure, list):
            continue
        for entry in closure:
            if not isinstance(entry, dict):
                continue
            authority_path = entry.get("authority_path")
            definitions = entry.get("definitions")
            if not isinstance(authority_path, str) or not isinstance(definitions, list):
                continue
            if authority_path == "diagnostics":
                extend_unique(diagnostics, definitions)
                continue
            if not authority_path.startswith("language."):
                continue
            segments = authority_path.split(".")[1:]
            target: dict[str, Any] = language
            for segment in segments[:-1]:
                child = target.setdefault(segment, {})
                if not isinstance(child, dict):
                    raise ValueError(f"authority path collision at {authority_path}")
                target = child
            leaf = segments[-1]
            existing = target.setdefault(leaf, [])
            if not isinstance(existing, list):
                raise ValueError(f"authority path collision at {authority_path}")
            extend_unique(existing, definitions)
        vector_definitions = vector_set.get("vector_definitions")
        if isinstance(vector_definitions, list):
            vectors.extend(deepcopy(vector_definitions))

    language["packages"] = deepcopy(package_releases)
    projection = {
        "artifact_kind": root.get("artifact_kind"),
        "artifact_version": root.get("artifact_version"),
        "content_identity": root.get("content_identity"),
        "diagnostics": diagnostics,
        "kernel_identity": root.get("kernel_identity"),
        "language": language,
        "resources": deepcopy(root.get("resources")),
        "schema_major": root.get("schema_major"),
        "vectors": vectors,
    }
    return LanguageBundleIndex(
        projection,
        root=root,
        package_releases=package_releases,
        package_conformance_vector_sets=package_conformance_vector_sets,
        root_byte_size=root_byte_size,
        package_byte_sizes=package_byte_sizes,
        vector_set_byte_sizes=vector_set_byte_sizes,
    )
