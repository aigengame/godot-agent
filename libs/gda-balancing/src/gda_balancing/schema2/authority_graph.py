"""Closed in-memory projection of one sealed Schema 2.0 LDB graph."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class LanguageBundleIndex(dict[str, Any]):
    """A derived lookup view carrying its exact non-authoritative graph source."""

    def __init__(
        self,
        projection: dict[str, Any],
        *,
        root: dict[str, Any],
        package_releases: list[dict[str, Any]],
        member_byte_sizes: list[int],
    ) -> None:
        super().__init__(projection)
        self.root = deepcopy(root)
        self.package_releases = deepcopy(package_releases)
        self.member_byte_sizes = tuple(member_byte_sizes)

    def __deepcopy__(self, memo: dict[int, Any]) -> "LanguageBundleIndex":
        duplicate = LanguageBundleIndex(
            deepcopy(dict(self), memo),
            root=deepcopy(self.root, memo),
            package_releases=deepcopy(self.package_releases, memo),
            member_byte_sizes=list(self.member_byte_sizes),
        )
        memo[id(self)] = duplicate
        return duplicate


def derive_language_index(
    root: dict[str, Any],
    package_releases: list[dict[str, Any]],
    required_language_members: list[str],
    *,
    member_byte_sizes: list[int],
) -> LanguageBundleIndex:
    """Derive the legacy-shaped consumer index from package-owned definitions."""
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
        member_byte_sizes=member_byte_sizes,
    )
