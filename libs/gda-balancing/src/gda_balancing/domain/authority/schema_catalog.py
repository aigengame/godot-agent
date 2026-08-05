"""Admitted Standard Schema authority and public projections."""

from dataclasses import dataclass
from typing import Any, Literal, cast

from gda_balancing.schema2.authority import AdmittedAuthorityContext
from gda_balancing.schema2.canonical import JsonValue
from gda_balancing.schema2.projections import (
    diagnostic_catalog_projection,
    wire_schema_projection,
)


@dataclass(frozen=True)
class SchemaArtifactContent:
    """One public authority artifact or derived projection."""

    root: dict[str, Any]


def get_schema_artifact(
    context: AdmittedAuthorityContext,
    artifact: Literal["language-bundle", "wire-schema", "diagnostic-catalog"],
) -> SchemaArtifactContent:
    """Project one public artifact from an admitted authority context."""
    kernel, language_bundle = context.mutable_pair()
    admission = context.admission
    authorities: dict[str, JsonValue] = {
        "kernel": cast(JsonValue, kernel),
        "language_bundle": cast(JsonValue, language_bundle),
        "admission": {
            "admitted": True,
            "kernel_identity": admission.kernel_identity,
            "language_bundle_identity": admission.language_bundle_identity,
        },
    }
    if artifact == "language-bundle":
        root = getattr(language_bundle, "root", None)
        package_releases = getattr(language_bundle, "package_releases", None)
        vector_sets = getattr(
            language_bundle,
            "package_conformance_vector_sets",
            None,
        )
        if (
            isinstance(root, dict)
            and isinstance(package_releases, list)
            and isinstance(vector_sets, list)
        ):
            authorities = {
                "kernel": cast(JsonValue, kernel),
                "language_bundle": cast(JsonValue, root),
                "package_releases": cast(JsonValue, package_releases),
                "package_conformance_vector_sets": cast(JsonValue, vector_sets),
                "admission": authorities["admission"],
            }
        return SchemaArtifactContent(root=cast(dict[str, Any], authorities))
    if artifact == "wire-schema":
        return SchemaArtifactContent(root=wire_schema_projection(authorities))
    return SchemaArtifactContent(root=diagnostic_catalog_projection(authorities))
