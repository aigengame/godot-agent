"""Standard Schema 2.0 package inventory commands (bADR-0021/0023)."""

from collections.abc import Callable
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, RootModel

from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.schema2.authority import AuthorityLoadError, load_authorities
from gda_balancing.schema2.bootstrap import BOOTSTRAP_REFUSAL_CATALOG, admit_authorities
from gda_balancing.schema2.diagnostics import (
    Schema2RefusalReport,
    bootstrap_refusal,
    ingress_refusal,
)


class PackageListInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PackageGetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class PackageArtifact(RootModel[dict[str, Any]]):
    """One admitted package inventory or exact Package Release."""


AuthorityProvider = Callable[[], tuple[dict[str, Any], dict[str, Any]]]

PACKAGE_DESCRIPTOR_MEMBERS = (
    "artifact_kind",
    "byte_size",
    "content_identity",
    "id",
    "version",
)
PACKAGE_RELEASE_MEMBERS = (
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
PACKAGE_RELEASE_NESTED_MEMBERS = {
    "capabilities": ("provided", "required"),
    "dependencies": ("optional", "required"),
    "exports": (
        "artifact_contracts",
        "artifact_wire_schemas",
        "components",
        "conversions",
        "diagnostics",
        "domains",
        "kinds",
        "language_rules",
        "model_checks",
        "model_lowerings",
        "model_source_schema_versions",
        "operations",
        "reasons",
        "representations",
        "symbol_roles",
        "template_admission_profiles",
        "types",
        "units",
        "wire_schemas",
    ),
    "profiles": ("numeric", "resolution", "runtime"),
}


def _admitted_package_graph(
    provider: AuthorityProvider,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | Schema2RefusalReport:
    try:
        kernel, ldb = provider()
    except AuthorityLoadError as err:
        return ingress_refusal(err.code, err.subject, err.message)
    admission = admit_authorities(kernel, ldb)
    if not admission.admitted:
        return bootstrap_refusal(admission)
    root = getattr(ldb, "root", None)
    releases = getattr(ldb, "package_releases", None)
    if not isinstance(root, dict) or not isinstance(releases, list):
        return ingress_refusal(
            "kernel.member_set_mismatch",
            "language-bundle",
            "the admitted LDB has no sealed package graph",
        )
    return root, releases


def package_list_handler(
    provider: AuthorityProvider,
) -> Callable[[PackageListInput], PackageArtifact | Schema2RefusalReport]:
    def _run(_inp: PackageListInput) -> PackageArtifact | Schema2RefusalReport:
        graph = _admitted_package_graph(provider)
        if isinstance(graph, Schema2RefusalReport):
            return graph
        root, _releases = graph
        return PackageArtifact(
            root={
                "language_bundle_identity": root["content_identity"],
                "packages": root["package_descriptors"],
            }
        )

    return _run


def package_get_handler(
    provider: AuthorityProvider,
) -> Callable[[PackageGetInput], PackageArtifact | Schema2RefusalReport]:
    def _run(inp: PackageGetInput) -> PackageArtifact | Schema2RefusalReport:
        graph = _admitted_package_graph(provider)
        if isinstance(graph, Schema2RefusalReport):
            return graph
        _root, releases = graph
        for release in releases:
            if release.get("id") == inp.id and release.get("version") == inp.version:
                return PackageArtifact(root=cast(dict[str, Any], release))
        return ingress_refusal(
            "kernel.binding_mismatch",
            f"{inp.id}@{inp.version}",
            "the exact package coordinate is absent from the admitted LDB",
        )

    return _run


def package_list_success_schema() -> dict[str, object]:
    identity = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    descriptor_properties = {
        name: (
            {"const": "domain-package-release"}
            if name == "artifact_kind"
            else (
                {"type": "integer", "minimum": 1}
                if name == "byte_size"
                else (
                    identity
                    if name == "content_identity"
                    else {"type": "string", "minLength": 1}
                )
            )
        )
        for name in PACKAGE_DESCRIPTOR_MEMBERS
    }
    return {
        "type": "object",
        "properties": {
            "language_bundle_identity": identity,
            "packages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": descriptor_properties,
                    "required": list(PACKAGE_DESCRIPTOR_MEMBERS),
                    "unevaluatedProperties": False,
                },
            },
        },
        "required": ["language_bundle_identity", "packages"],
        "unevaluatedProperties": False,
    }


def package_get_success_schema() -> dict[str, object]:
    properties: dict[str, object] = {name: {} for name in PACKAGE_RELEASE_MEMBERS}
    for field, members in PACKAGE_RELEASE_NESTED_MEMBERS.items():
        properties[field] = {
            "type": "object",
            "properties": {name: {} for name in members},
            "required": list(members),
            "unevaluatedProperties": False,
        }
    return {
        "type": "object",
        "properties": properties,
        "required": list(PACKAGE_RELEASE_MEMBERS),
        "unevaluatedProperties": False,
    }


PACKAGE_LIST = CommandDescriptor(
    group="package",
    command="list",
    description="List Package Releases in the admitted Language Definition Bundle.",
    input_model=PackageListInput,
    output_model=PackageArtifact,
    handler=package_list_handler(load_authorities),
    fixtures=ConformanceFixtures(),
    schema_major=2,
    structured_params=True,
    refusal_catalog=BOOTSTRAP_REFUSAL_CATALOG,
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
    success_schema=package_list_success_schema,
)


PACKAGE_GET = CommandDescriptor(
    group="package",
    command="get",
    description="Get one exact Package Release from the admitted language bundle.",
    input_model=PackageGetInput,
    output_model=PackageArtifact,
    handler=package_get_handler(load_authorities),
    fixtures=ConformanceFixtures(
        valid_args=("--id", "core.quantity", "--version", "2.0.0"),
        refusing_args=("--id", "missing.package", "--version", "1.0.0"),
    ),
    schema_major=2,
    structured_params=True,
    refusal_catalog=BOOTSTRAP_REFUSAL_CATALOG,
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
    success_schema=package_get_success_schema,
)
