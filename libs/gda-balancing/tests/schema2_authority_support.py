"""Shared authority inputs for tests that do not exercise loading."""

from typing import Any

from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.graph import LanguageBundleIndex


_PACKAGE_VERSIONED_AUTHORITY_PATHS = frozenset(
    {
        "language.components",
        "language.conversions",
        "language.nominal_types",
        "language.operations",
    }
)


def mutable_authorities() -> tuple[dict[str, Any], LanguageBundleIndex]:
    """Return an owned mutable copy of the admitted packaged authorities."""
    return packaged_authority_context().mutable_pair()


def definition_matches_package_coordinate(
    definition: Any,
    *,
    authority_path: str,
    package_id: str,
    package_version: str,
) -> bool:
    """Select the owning release when an authority id has several versions."""
    if not isinstance(definition, dict):
        return True
    version = definition.get("version")
    if authority_path in _PACKAGE_VERSIONED_AUTHORITY_PATHS:
        return version == package_version
    return definition.get("package") != package_id or version == package_version
