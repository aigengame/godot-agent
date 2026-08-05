"""Package inventory projected from one admitted Language Definition Bundle."""

from typing import Any, TypedDict

from gda_balancing.schema2.authority import AdmittedAuthorityContext
from gda_balancing.schema2.diagnostics import Schema2RefusalReport, ingress_refusal


class PackageInventory(TypedDict):
    """The Package Releases declared by one admitted language bundle."""

    language_bundle_identity: str
    packages: list[dict[str, Any]]


def list_package_releases(
    context: AdmittedAuthorityContext,
) -> PackageInventory | Schema2RefusalReport:
    """Return the root-declared package inventory from an admitted context."""
    _kernel, language_bundle = context.mutable_pair()
    root = getattr(language_bundle, "root", None)
    if not isinstance(root, dict):
        return ingress_refusal(
            "kernel.member_set_mismatch",
            "language-bundle",
            "the admitted LDB has no sealed package graph",
        )
    return PackageInventory(
        language_bundle_identity=root["content_identity"],
        packages=root["package_descriptors"],
    )
