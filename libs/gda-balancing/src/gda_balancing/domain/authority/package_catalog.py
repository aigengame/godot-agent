"""Package inventory projected from one admitted Language Definition Bundle."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast

from gda_balancing.schema2.authority import AdmittedAuthorityContext
from gda_balancing.schema2.diagnostics import Schema2RefusalReport, ingress_refusal


class PackageInventory(TypedDict):
    """The Package Releases declared by one admitted language bundle."""

    language_bundle_identity: str
    packages: list[dict[str, Any]]


@dataclass(frozen=True)
class PackageArtifactContent:
    """One exact Package Release member selected from an admitted bundle."""

    root: dict[str, Any]


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


def get_package_release(
    context: AdmittedAuthorityContext,
    package_id: str,
    version: str,
    member: Literal["release", "conformance-vectors"],
) -> PackageArtifactContent | Schema2RefusalReport:
    """Select one exact member from the admitted Package Release graph."""
    _kernel, language_bundle = context.mutable_pair()
    releases = getattr(language_bundle, "package_releases", None)
    vector_sets = getattr(language_bundle, "package_conformance_vector_sets", None)
    if not isinstance(releases, list) or not isinstance(vector_sets, list):
        return ingress_refusal(
            "kernel.member_set_mismatch",
            "language-bundle",
            "the admitted LDB has no sealed package graph",
        )
    for release, vector_set in zip(releases, vector_sets, strict=True):
        if release.get("id") == package_id and release.get("version") == version:
            selected = release if member == "release" else vector_set
            return PackageArtifactContent(root=deepcopy(cast(dict[str, Any], selected)))
    return ingress_refusal(
        "kernel.binding_mismatch",
        f"{package_id}@{version}",
        "the exact package coordinate is absent from the admitted LDB",
    )
