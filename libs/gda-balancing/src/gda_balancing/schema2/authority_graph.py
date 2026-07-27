"""Closed in-memory projection of one sealed Schema 2.0 LDB graph."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _canonical_graph_members(
    root: dict[str, Any],
    package_releases: list[dict[str, Any]],
    member_byte_sizes: list[int],
    descriptor_order: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[int]]:
    """Normalize descriptor transport order without changing graph semantics."""
    normalized_root = deepcopy(root)
    descriptors = normalized_root.get("package_descriptors")
    if (
        not isinstance(descriptors, list)
        or len(descriptors) != len(package_releases)
        or len(descriptors) != len(member_byte_sizes)
        or not descriptor_order
        or not all(isinstance(name, str) for name in descriptor_order)
        or not all(
            isinstance(descriptor, dict)
            and all(isinstance(descriptor.get(name), str) for name in descriptor_order)
            for descriptor in descriptors
        )
    ):
        return normalized_root, deepcopy(package_releases), list(member_byte_sizes)
    members = sorted(
        zip(descriptors, package_releases, member_byte_sizes, strict=True),
        key=lambda member: tuple(member[0][name] for name in descriptor_order),
    )
    normalized_root["package_descriptors"] = [
        deepcopy(descriptor) for descriptor, _release, _size in members
    ]
    return (
        normalized_root,
        [deepcopy(release) for _descriptor, release, _size in members],
        [size for _descriptor, _release, size in members],
    )


class LanguageBundleIndex(dict[str, Any]):
    """A derived lookup view carrying its exact non-authoritative graph source."""

    def __init__(
        self,
        projection: dict[str, Any],
        *,
        root: dict[str, Any],
        package_releases: list[dict[str, Any]],
        root_byte_size: int,
        member_byte_sizes: list[int],
    ) -> None:
        super().__init__(projection)
        self.root = deepcopy(root)
        self.package_releases = deepcopy(package_releases)
        self.root_byte_size = root_byte_size
        self.member_byte_sizes = tuple(member_byte_sizes)

    def __deepcopy__(self, memo: dict[int, Any]) -> "LanguageBundleIndex":
        duplicate = LanguageBundleIndex(
            deepcopy(dict(self), memo),
            root=deepcopy(self.root, memo),
            package_releases=deepcopy(self.package_releases, memo),
            root_byte_size=self.root_byte_size,
            member_byte_sizes=list(self.member_byte_sizes),
        )
        memo[id(self)] = duplicate
        return duplicate


def derive_language_index(
    root: dict[str, Any],
    package_releases: list[dict[str, Any]],
    required_language_members: list[str],
    *,
    root_byte_size: int,
    member_byte_sizes: list[int],
    descriptor_order: list[str],
) -> LanguageBundleIndex:
    """Derive the legacy-shaped consumer index from package-owned definitions."""
    root, package_releases, member_byte_sizes = _canonical_graph_members(
        root, package_releases, member_byte_sizes, descriptor_order
    )
    language: dict[str, Any] = {}
    for member in required_language_members:
        language[member] = {} if member == "quantity" else []

    diagnostics: list[Any] = []
    vectors: list[Any] = []
    for release in package_releases:
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
                diagnostics.extend(deepcopy(definitions))
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
            existing.extend(deepcopy(definitions))
        vector_definitions = release.get("vector_definitions")
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
        root_byte_size=root_byte_size,
        member_byte_sizes=member_byte_sizes,
    )
