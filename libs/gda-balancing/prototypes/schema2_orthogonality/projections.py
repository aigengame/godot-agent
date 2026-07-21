"""Generated and reverse-conformance-checked package/LDB projections."""

from __future__ import annotations

from typing import Any

from canonical import artifact, clone


class ProjectionMismatch(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def releases(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(clone(bundle["packages"]), key=lambda release: release["id"])


def operations(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    values = [
        {"package_release": release["identity"], **clone(operation)}
        for release in releases(bundle)
        for operation in release["operations"]
    ]
    return sorted(values, key=lambda operation: operation["id"])


def generate(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    package_values = releases(bundle)
    operation_values = operations(bundle)
    package_surface = [
        {
            "id": release["id"],
            "version": release["version"],
            "identity": release["identity"],
            "dependencies": clone(release["dependencies"]),
            "provides": clone(release["provides"]),
            "requires_capabilities": clone(release["requires_capabilities"]),
            "quantity_kinds": clone(release["quantity_kinds"]),
            "units": clone(release["units"]),
            "numeric_profiles": clone(release["numeric_profiles"]),
            "runtime_profiles": clone(release["runtime_profiles"]),
            "diagnostics": clone(release["diagnostics"]),
        }
        for release in package_values
    ]
    schema = artifact(
        "generated-structural-schema",
        {
            "bundle": bundle["identity"],
            "packages": package_surface,
            "operation_refs": [operation["id"] for operation in operation_values],
            "closed": True,
        },
    )
    registry = artifact(
        "generated-operation-registry",
        {
            "bundle": bundle["identity"],
            "operations": [
                {
                    "package_release": operation["package_release"],
                    "id": operation["id"],
                    "version": operation["version"],
                    "parameters": clone(operation["parameters"]),
                    "result": clone(operation["result"]),
                    "state_contract": clone(operation["state_contract"]),
                    "kind_rules": clone(operation["kind_rules"]),
                    "unit_rules": clone(operation["unit_rules"]),
                    "permitted_numeric_profiles": clone(
                        operation["permitted_numeric_profiles"]
                    ),
                    "purity": operation["purity"],
                    "effects": clone(operation["effects"]),
                    "resource_bounds": clone(operation["resource_bounds"]),
                }
                for operation in operation_values
            ],
        },
    )
    runtime = artifact(
        "generated-runtime-programs",
        {
            "bundle": bundle["identity"],
            "programs": [
                {
                    "package_release": operation["package_release"],
                    "operation": operation["id"],
                    "body": clone(operation["body"]),
                }
                for operation in operation_values
            ],
        },
    )
    vectors = artifact(
        "generated-vector-catalog",
        {
            "bundle": bundle["identity"],
            "vectors": [
                {"package_release": release["identity"], "vector": clone(vector)}
                for release in package_values
                for vector in release["vectors"]
            ],
        },
    )
    documentation = artifact(
        "generated-package-documentation",
        {
            "bundle": bundle["identity"],
            "packages": [
                {
                    "id": release["id"],
                    "version": release["version"],
                    "identity": release["identity"],
                    "capabilities": clone(release["provides"]),
                    "types": [item["id"] for item in release["quantity_kinds"]],
                    "operations": [item["id"] for item in release["operations"]],
                }
                for release in package_values
            ],
        },
    )
    diagnostics = artifact(
        "generated-diagnostic-catalog",
        {
            "bundle": bundle["identity"],
            "diagnostics": [
                {"package_release": release["identity"], "code": code}
                for release in package_values
                for code in release["diagnostics"]
            ],
        },
    )
    return {
        "diagnostics": diagnostics,
        "documentation": documentation,
        "registry": registry,
        "runtime": runtime,
        "schema": schema,
        "vectors": vectors,
    }


def reverse_conformance(
    bundle: dict[str, Any], supplied: dict[str, dict[str, Any]]
) -> None:
    expected = generate(bundle)
    if set(supplied) != set(expected):
        missing = sorted(set(expected) - set(supplied))
        extra = sorted(set(supplied) - set(expected))
        raise ProjectionMismatch(
            "projection.inventory-mismatch", f"missing={missing};extra={extra}"
        )
    for name, expected_projection in expected.items():
        if supplied[name] != expected_projection:
            raise ProjectionMismatch("projection.content-mismatch", name)


def operation_map(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {operation["id"]: operation for operation in operations(bundle)}


def release_map(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {release["id"]: release for release in releases(bundle)}
