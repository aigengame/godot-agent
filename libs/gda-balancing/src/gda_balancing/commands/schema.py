"""Standard Schema 2.0 authority retrieval (bADR-0012/0021/0022).

``schema get`` exposes the admitted Kernel/LDB pair and the exact wire-schema
and Diagnostic-catalog projections generated from it. The packaged JSON
resources are language authority; this command admits them before emitting
anything and returns a stage-aware refusal if their identity, binding, closed
shape, executable vectors, or resource contract fails.
"""

from collections.abc import Callable
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, RootModel, model_validator

from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.schema2.authority import AuthorityLoadError, load_authorities
from gda_balancing.schema2.bootstrap import (
    BOOTSTRAP_REFUSAL_CATALOG,
    SCHEMA2_REFUSAL_STAGES,
    admit_authorities,
)
from gda_balancing.schema2.canonical import JsonValue
from gda_balancing.schema2.diagnostics import (
    Schema2RefusalReport,
    bootstrap_refusal,
    ingress_refusal,
)
from gda_balancing.schema2.projections import (
    diagnostic_catalog_projection,
    wire_schema_projection,
)


class SchemaGetInput(BaseModel):
    """Select one delivered Standard Schema 2.0 authority projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact: Literal[
        "language-bundle",
        "package-list",
        "package",
        "wire-schema",
        "diagnostic-catalog",
    ]
    package_id: str | None = None
    package_version: str | None = None

    @model_validator(mode="after")
    def close_package_coordinate(self) -> "SchemaGetInput":
        coordinate_supplied = (
            self.package_id is not None or self.package_version is not None
        )
        if self.artifact == "package":
            if self.package_id is None or self.package_version is None:
                raise ValueError("package requires package_id and package_version")
        elif coordinate_supplied:
            raise ValueError(
                "package_id and package_version are only valid for package"
            )
        return self


class SchemaArtifact(RootModel[dict[str, Any]]):
    """One stdout-only authority/projection result; descriptor schema is exact."""


AuthorityProvider = Callable[[], tuple[dict[str, Any], dict[str, Any]]]


def schema_get_handler(
    provider: AuthorityProvider,
) -> Callable[[SchemaGetInput], SchemaArtifact | Schema2RefusalReport]:
    """Build the retrieval handler around an injectable authority source.

    Production uses packaged resources; the conformance harness injects
    mutations through the same dispatch/descriptor boundary.
    """

    def _run(inp: SchemaGetInput) -> SchemaArtifact | Schema2RefusalReport:
        try:
            kernel, ldb = provider()
        except AuthorityLoadError as err:
            return ingress_refusal(err.code, err.subject, err.message)
        admission = admit_authorities(kernel, ldb)
        if not admission.admitted:
            return bootstrap_refusal(admission)
        authorities: dict[str, JsonValue] = {
            "kernel": cast(JsonValue, kernel),
            "language_bundle": cast(JsonValue, ldb),
            "admission": {
                "admitted": True,
                "kernel_identity": admission.kernel_identity,
                "language_bundle_identity": admission.language_bundle_identity,
            },
        }
        if inp.artifact == "language-bundle":
            root = getattr(ldb, "root", None)
            package_releases = getattr(ldb, "package_releases", None)
            if isinstance(root, dict) and isinstance(package_releases, list):
                public_authorities = {
                    "kernel": cast(JsonValue, kernel),
                    "language_bundle": cast(JsonValue, root),
                    "package_releases": cast(JsonValue, package_releases),
                    "admission": authorities["admission"],
                }
                return SchemaArtifact(root=cast(dict[str, Any], public_authorities))
            return SchemaArtifact(root=cast(dict[str, Any], authorities))
        if inp.artifact in {"package-list", "package"}:
            root = getattr(ldb, "root", None)
            package_releases = getattr(ldb, "package_releases", None)
            if not isinstance(root, dict) or not isinstance(package_releases, list):
                return ingress_refusal(
                    "kernel.member_set_mismatch",
                    "language-bundle",
                    "the admitted LDB has no sealed package graph",
                )
            if inp.artifact == "package-list":
                return SchemaArtifact(
                    root={
                        "language_bundle_identity": root["content_identity"],
                        "packages": root["package_descriptors"],
                    }
                )
            for release in package_releases:
                if (
                    release.get("id") == inp.package_id
                    and release.get("version") == inp.package_version
                ):
                    return SchemaArtifact(root=cast(dict[str, Any], release))
            return ingress_refusal(
                "kernel.binding_mismatch",
                f"{inp.package_id}@{inp.package_version}",
                "the exact package coordinate is absent from the admitted LDB",
            )
        if inp.artifact == "wire-schema":
            return SchemaArtifact(root=wire_schema_projection(authorities))
        return SchemaArtifact(root=diagnostic_catalog_projection(authorities))

    return _run


run_schema_get = schema_get_handler(load_authorities)


def schema_get_refusal_catalog() -> tuple[tuple[str, str], ...]:
    """Return the non-self-hosted Kernel bootstrap refusal vocabulary."""
    return BOOTSTRAP_REFUSAL_CATALOG


def schema_get_success_schema() -> dict[str, object]:
    """Static closed result shapes; introspection never reads authority bytes."""
    identity = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    admission = {
        "type": "object",
        "properties": {
            "admitted": {"const": True},
            "kernel_identity": identity,
            "language_bundle_identity": identity,
        },
        "required": [
            "admitted",
            "kernel_identity",
            "language_bundle_identity",
        ],
        "unevaluatedProperties": False,
    }
    authority_result = {
        "type": "object",
        "properties": {
            "kernel": {},
            "language_bundle": {},
            "package_releases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        name: {}
                        for name in (
                            "artifact_kind",
                            "capabilities",
                            "content_identity",
                            "dependencies",
                            "exports",
                            "id",
                            "profiles",
                            "runtime_semantic_paths",
                            "semantic_closure",
                            "semantic_identity",
                            "vector_definitions",
                            "vectors",
                            "version",
                        )
                    },
                    "required": [
                        "artifact_kind",
                        "capabilities",
                        "content_identity",
                        "dependencies",
                        "exports",
                        "id",
                        "profiles",
                        "runtime_semantic_paths",
                        "semantic_closure",
                        "semantic_identity",
                        "vector_definitions",
                        "vectors",
                        "version",
                    ],
                    "unevaluatedProperties": False,
                },
            },
            "admission": admission,
        },
        "required": [
            "kernel",
            "language_bundle",
            "package_releases",
            "admission",
        ],
        "unevaluatedProperties": False,
    }
    package_properties = {
        name: {}
        for name in (
            "artifact_kind",
            "capabilities",
            "content_identity",
            "dependencies",
            "exports",
            "id",
            "profiles",
            "runtime_semantic_paths",
            "semantic_closure",
            "semantic_identity",
            "vector_definitions",
            "vectors",
            "version",
        )
    }
    package_result = {
        "type": "object",
        "properties": package_properties,
        "required": list(package_properties),
        "unevaluatedProperties": False,
    }
    package_list_result = {
        "type": "object",
        "properties": {
            "language_bundle_identity": identity,
            "packages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "artifact_kind": {"const": "domain-package-release"},
                        "byte_size": {"type": "integer", "minimum": 1},
                        "content_identity": identity,
                        "id": {"type": "string", "minLength": 1},
                        "version": {"type": "string", "minLength": 1},
                    },
                    "required": [
                        "artifact_kind",
                        "byte_size",
                        "content_identity",
                        "id",
                        "version",
                    ],
                    "unevaluatedProperties": False,
                },
            },
        },
        "required": ["language_bundle_identity", "packages"],
        "unevaluatedProperties": False,
    }
    projection_base = {
        "kernel_identity": identity,
        "language_bundle_identity": identity,
        "content_identity": identity,
    }
    wire_projection = {
        "type": "object",
        "properties": {
            "artifact_kind": {"const": "wire-schema-projection"},
            **projection_base,
            "schemas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "artifact_kind": {"type": "string", "minLength": 1},
                        "schema": {},
                    },
                    "required": ["artifact_kind", "schema"],
                    "unevaluatedProperties": False,
                },
            },
        },
        "required": [
            "artifact_kind",
            "kernel_identity",
            "language_bundle_identity",
            "schemas",
            "content_identity",
        ],
        "unevaluatedProperties": False,
    }
    diagnostic_projection = {
        "type": "object",
        "properties": {
            "artifact_kind": {"const": "diagnostic-catalog-projection"},
            **projection_base,
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "authority": {"enum": ["kernel", "language-bundle"]},
                        "code": {"type": "string", "minLength": 1},
                        "stage": {"enum": list(SCHEMA2_REFUSAL_STAGES)},
                    },
                    "required": ["authority", "code", "stage"],
                    "unevaluatedProperties": False,
                },
            },
        },
        "required": [
            "artifact_kind",
            "kernel_identity",
            "language_bundle_identity",
            "entries",
            "content_identity",
        ],
        "unevaluatedProperties": False,
    }
    return {
        "oneOf": [
            authority_result,
            package_list_result,
            package_result,
            wire_projection,
            diagnostic_projection,
        ]
    }


SCHEMA_GET = CommandDescriptor(
    group="schema",
    command="get",
    description="Emit a Standard Schema 2.0 language authority or projection.",
    input_model=SchemaGetInput,
    output_model=SchemaArtifact,
    handler=run_schema_get,
    positional_field="artifact",
    artifact_sink=False,
    fixtures=ConformanceFixtures(valid_args=("language-bundle",)),
    schema_major=2,
    structured_params=True,
    refusal_catalog=schema_get_refusal_catalog(),
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
    success_schema=schema_get_success_schema,
)
