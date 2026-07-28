"""Standard Schema 2.0 package inventory commands (bADR-0021/0023)."""

from collections.abc import Callable
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, RootModel

from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.schema2.authority import (
    AuthorityLoadError,
    load_authorities,
    load_descriptor_authorities,
)
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
    member: Literal["release", "conformance-vectors"] = "release"


class PackageArtifact(RootModel[dict[str, Any]]):
    """One admitted package inventory or exact Package Release."""


AuthorityProvider = Callable[[], tuple[dict[str, Any], dict[str, Any]]]


def _admitted_package_graph(
    provider: AuthorityProvider,
) -> (
    tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]
    | Schema2RefusalReport
):
    try:
        kernel, ldb = provider()
    except AuthorityLoadError as err:
        return ingress_refusal(err.code, err.subject, err.message)
    admission = admit_authorities(kernel, ldb)
    if not admission.admitted:
        return bootstrap_refusal(admission)
    root = getattr(ldb, "root", None)
    releases = getattr(ldb, "package_releases", None)
    vector_sets = getattr(ldb, "package_conformance_vector_sets", None)
    if (
        not isinstance(root, dict)
        or not isinstance(releases, list)
        or not isinstance(vector_sets, list)
    ):
        return ingress_refusal(
            "kernel.member_set_mismatch",
            "language-bundle",
            "the admitted LDB has no sealed package graph",
        )
    return root, releases, vector_sets


def package_list_handler(
    provider: AuthorityProvider,
) -> Callable[[PackageListInput], PackageArtifact | Schema2RefusalReport]:
    def _run(_inp: PackageListInput) -> PackageArtifact | Schema2RefusalReport:
        graph = _admitted_package_graph(provider)
        if isinstance(graph, Schema2RefusalReport):
            return graph
        root, _releases, _vector_sets = graph
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
        _root, releases, vector_sets = graph
        for release, vector_set in zip(releases, vector_sets, strict=True):
            if release.get("id") == inp.id and release.get("version") == inp.version:
                selected = release if inp.member == "release" else vector_set
                return PackageArtifact(root=cast(dict[str, Any], selected))
        return ingress_refusal(
            "kernel.binding_mismatch",
            f"{inp.id}@{inp.version}",
            "the exact package coordinate is absent from the admitted LDB",
        )

    return _run


def _contract_schema(contract: dict[str, Any]) -> dict[str, object]:
    if "const" in contract:
        return {"const": contract["const"]}
    value_type = contract.get("type")
    if value_type == "non-empty-string":
        return {"type": "string", "minLength": 1}
    if value_type == "positive-signed-int64":
        return {"type": "integer", "minimum": 1, "maximum": 2**63 - 1}
    if value_type == "signed-int64":
        return {"type": "integer", "minimum": -(2**63), "maximum": 2**63 - 1}
    if value_type == "string-list":
        return {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        }
    if value_type == "list":
        return {"type": "array"}
    if value_type == "list-of":
        items = contract.get("items")
        if not isinstance(items, dict):
            raise ValueError("Kernel list-of contract has no item contract")
        return {"type": "array", "items": _contract_schema(items)}
    if value_type == "closed-object":
        return _closed_contract_schema(contract)
    raise ValueError(f"unsupported Kernel package contract type: {value_type!r}")


def _closed_contract_schema(contract: dict[str, Any]) -> dict[str, object]:
    required = contract.get("required_members")
    field_types = contract.get("field_types", {})
    nested_members = contract.get("nested_members", {})
    nested_field_types = contract.get("nested_field_types", {})
    if (
        contract.get("closed") is not True
        or not isinstance(required, list)
        or not all(isinstance(member, str) for member in required)
        or not isinstance(field_types, dict)
        or not isinstance(nested_members, dict)
        or not isinstance(nested_field_types, dict)
        or set(field_types) | set(nested_members) != set(required)
        or set(nested_members) != set(nested_field_types)
    ):
        raise ValueError("Kernel package object contract is incomplete")
    properties = {
        name: _contract_schema(cast(dict[str, Any], member_contract))
        for name, member_contract in field_types.items()
    }
    for name, members in nested_members.items():
        member_types = nested_field_types.get(name)
        if (
            not isinstance(members, list)
            or not all(isinstance(member, str) for member in members)
            or not isinstance(member_types, dict)
            or set(member_types) != set(members)
        ):
            raise ValueError(f"Kernel nested package contract is incomplete: {name}")
        properties[name] = {
            "type": "object",
            "properties": {
                member: _contract_schema(cast(dict[str, Any], member_types[member]))
                for member in members
            },
            "required": members,
            "unevaluatedProperties": False,
        }
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "unevaluatedProperties": False,
    }


def _package_contracts() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    kernel, _language_bundle = load_descriptor_authorities()
    meta_format = cast(dict[str, Any], kernel["meta_format"])
    language_bundle_contract = cast(dict[str, Any], meta_format["language_bundle"])
    return (
        cast(
            dict[str, Any], language_bundle_contract["member_types"]["content_identity"]
        ),
        cast(dict[str, Any], language_bundle_contract["package_descriptor"]),
        cast(dict[str, Any], meta_format["package_release"]),
        cast(dict[str, Any], meta_format["package_conformance_vector_set"]),
    )


def package_list_success_schema() -> dict[str, object]:
    (
        identity_contract,
        descriptor_contract,
        _release_contract,
        _vector_set_contract,
    ) = _package_contracts()
    return {
        "type": "object",
        "properties": {
            "language_bundle_identity": _contract_schema(identity_contract),
            "packages": {
                "type": "array",
                "items": _closed_contract_schema(descriptor_contract),
            },
        },
        "required": ["language_bundle_identity", "packages"],
        "unevaluatedProperties": False,
    }


def package_get_success_schema() -> dict[str, object]:
    (
        _identity_contract,
        _descriptor_contract,
        release_contract,
        vector_set_contract,
    ) = _package_contracts()
    return {
        "oneOf": [
            _closed_contract_schema(release_contract),
            _closed_contract_schema(vector_set_contract),
        ]
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
    description="Get one exact member of a Package Release.",
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
