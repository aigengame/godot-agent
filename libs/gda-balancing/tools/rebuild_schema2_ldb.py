#!/usr/bin/env python3
"""Rebuild or verify the checked-in sealed Schema 2.0 LDB graph."""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.authority.package_semantics import (
    package_runtime_semantic_closure,
)


def _identity(domain: str, artifact: dict[str, Any]) -> str:
    body = {key: value for key, value in artifact.items() if key != "content_identity"}
    return content_identity(domain, cast(JsonValue, body))


def _semantic_identity(
    package: dict[str, Any], domain: str, projection: dict[str, Any]
) -> str:
    selected = package_runtime_semantic_closure(package, projection)
    return content_identity(domain, cast(JsonValue, selected))


def _identity_domain(
    kernel: dict[str, Any],
    *,
    artifact: str | None = None,
    collection: str | None = None,
) -> str:
    if (artifact is None) == (collection is None):
        raise ValueError("identity target must select one artifact or collection")
    laws = kernel.get("admission", {}).get("laws")
    identity_laws = (
        [
            law
            for law in laws
            if isinstance(law, dict) and law.get("id") == "kernel.identity.verify"
        ]
        if isinstance(laws, list)
        else []
    )
    selector = "artifact" if artifact is not None else "collection"
    expected = artifact if artifact is not None else collection
    targets = (
        identity_laws[0].get("arguments", {}).get("targets")
        if len(identity_laws) == 1
        else None
    )
    matches = (
        [
            target
            for target in targets
            if isinstance(target, dict) and target.get(selector) == expected
        ]
        if isinstance(targets, list)
        else []
    )
    if len(matches) != 1:
        raise ValueError(f"Kernel declares no unique identity target for {expected}")
    target = matches[0]
    domain = target.get("domain")
    if (
        target.get("identity_member") != "content_identity"
        or not isinstance(domain, str)
        or not domain
    ):
        raise ValueError(f"Kernel identity target is incomplete for {expected}")
    return domain


def _namespace_contract(kernel: dict[str, Any]) -> dict[str, Any]:
    field_types = (
        kernel.get("meta_format", {})
        .get("language_bundle", {})
        .get("package_descriptor", {})
        .get("field_types")
    )
    if not isinstance(field_types, dict):
        raise ValueError("the Kernel declares no package namespace contract")
    id_contract = field_types.get("id")
    if not isinstance(id_contract, dict):
        raise ValueError("the Kernel package namespace contract is incomplete")
    return id_contract


def _matches_namespace(value: Any, contract: dict[str, Any]) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or contract.get("type") != "non-empty-string"
        or not isinstance(contract.get("pattern"), str)
        or "/" in value
        or "\\" in value
    ):
        return False
    try:
        return re.fullmatch(cast(str, contract["pattern"]), value) is not None
    except re.error:
        return False


def _validate_namespace(
    package_id: Any,
    contract: dict[str, Any],
    *,
    subject: str,
) -> str:
    if not _matches_namespace(package_id, contract):
        raise ValueError(f"{subject} is not a Kernel-valid package namespace")
    return cast(str, package_id)


def _package_paths(
    package_dir: Path,
    package_id: Any,
    contract: dict[str, Any],
) -> tuple[Path, Path]:
    package_id = _validate_namespace(package_id, contract, subject="package descriptor")
    directory = package_dir / package_id.replace(".", "-")
    return (
        directory / f"{package_id}.json",
        directory / f"{package_id}.conformance-vectors.json",
    )


def _build(
    authority_dir: Path,
) -> tuple[bytes, dict[Path, bytes]]:
    kernel = json.loads((authority_dir / "kernel.json").read_text())
    root_path = authority_dir / "language-bundle.json"
    root = json.loads(root_path.read_text())
    if "language" in root:
        raise ValueError("the retired monolithic LDB format is not supported")
    descriptors = root.get("package_descriptors")
    if not isinstance(descriptors, list) or not descriptors:
        raise ValueError("the LDB root has no package descriptors")

    package_dir = authority_dir / "packages"
    semantic_projection = kernel["meta_format"]["package_release"][
        "semantic_identity_projection"
    ]
    namespace_contract = _namespace_contract(kernel)
    declared_namespaces = [
        _validate_namespace(
            item.get("id") if isinstance(item, dict) else None,
            namespace_contract,
            subject=f"package descriptor {index}",
        )
        for index, item in enumerate(descriptors)
    ]
    if len(declared_namespaces) != len(set(declared_namespaces)):
        raise ValueError("the LDB root declares duplicate package namespaces")
    declared_path_pairs = [
        _package_paths(package_dir, package_id, namespace_contract)
        for package_id in declared_namespaces
    ]
    declared_paths = {path for pair in declared_path_pairs for path in pair}
    shipped_paths = set(package_dir.rglob("*.json"))
    if declared_paths != shipped_paths:
        missing = sorted(
            str(path.relative_to(package_dir))
            for path in declared_paths - shipped_paths
        )
        extra = sorted(
            str(path.relative_to(package_dir))
            for path in shipped_paths - declared_paths
        )
        raise ValueError(f"package membership drift: missing={missing}, extra={extra}")

    semantic_domain = kernel["meta_format"]["package_release"]["semantic_closure"][
        "domain"
    ]
    package_domain = _identity_domain(
        kernel, collection="language_bundle.language.packages"
    )
    vector_set_domain = _identity_domain(
        kernel,
        collection="language_bundle.package_conformance_vector_sets",
    )
    ldb_domain = _identity_domain(kernel, artifact="language-bundle")
    descriptor_order = kernel["meta_format"]["language_bundle"]["package_descriptor"][
        "canonical_order"
    ]
    if not isinstance(descriptor_order, list) or not descriptor_order:
        raise ValueError("the Kernel declares no package descriptor order")
    packages: list[dict[str, Any]] = []
    vector_sets_by_namespace: dict[str, dict[str, Any]] = {}
    for namespace, (package_path, vector_path) in zip(
        declared_namespaces, declared_path_pairs, strict=True
    ):
        package = json.loads(package_path.read_text())
        vector_set = json.loads(vector_path.read_text())
        package_namespace = _validate_namespace(
            package.get("id"),
            namespace_contract,
            subject=package_path.name,
        )
        vector_namespace = _validate_namespace(
            vector_set.get("package_id"),
            namespace_contract,
            subject=vector_path.name,
        )
        if package_namespace != namespace or vector_namespace != namespace:
            raise ValueError(f"package namespace binding drift for {namespace}")
        dependencies = package.get("dependencies")
        if not isinstance(dependencies, dict):
            raise ValueError(f"{package_path.name} has no dependency contract")
        seen_dependencies: set[str] = set()
        for dependency_kind in ("optional", "required"):
            items = dependencies.get(dependency_kind)
            if not isinstance(items, list):
                raise ValueError(
                    f"{package_path.name} has no {dependency_kind} dependency list"
                )
            for dependency_index, dependency in enumerate(items):
                dependency_id = _validate_namespace(
                    dependency,
                    namespace_contract,
                    subject=(
                        f"{package_path.name} {dependency_kind} dependency "
                        f"{dependency_index}"
                    ),
                )
                if dependency_id in seen_dependencies:
                    raise ValueError(
                        f"{package_path.name} repeats dependency {dependency_id}"
                    )
                seen_dependencies.add(dependency_id)
        vector_set["content_identity"] = _identity(vector_set_domain, vector_set)
        vector_data = canonical_bytes(cast(JsonValue, vector_set))
        package["conformance_vectors"] = {
            "artifact_kind": vector_set["artifact_kind"],
            "byte_size": len(vector_data),
            "content_identity": vector_set["content_identity"],
        }
        package["semantic_identity"] = _semantic_identity(
            package, semantic_domain, semantic_projection
        )
        package["content_identity"] = _identity(package_domain, package)
        packages.append(package)
        vector_sets_by_namespace[package["id"]] = vector_set
    packages.sort(key=lambda item: tuple(item[name] for name in descriptor_order))

    package_bytes: dict[Path, bytes] = {}
    rebuilt_descriptors: list[dict[str, Any]] = []
    for package in packages:
        data = canonical_bytes(cast(JsonValue, package))
        package_path, vector_path = _package_paths(
            package_dir,
            package["id"],
            namespace_contract,
        )
        vector_set = vector_sets_by_namespace[package["id"]]
        package_bytes[package_path] = data
        package_bytes[vector_path] = canonical_bytes(cast(JsonValue, vector_set))
        rebuilt_descriptors.append(
            {
                "artifact_kind": package["artifact_kind"],
                "byte_size": len(data),
                "content_identity": package["content_identity"],
                "id": package["id"],
            }
        )

    rebuilt_root = deepcopy(root)
    rebuilt_root["kernel_identity"] = kernel["content_identity"]
    rebuilt_root["package_descriptors"] = rebuilt_descriptors
    rebuilt_root["content_identity"] = _identity(ldb_domain, rebuilt_root)
    return canonical_bytes(cast(JsonValue, rebuilt_root)), package_bytes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("authority_dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    authority_dir: Path = args.authority_dir
    root_bytes, package_bytes = _build(authority_dir)
    expected = {
        authority_dir / "language-bundle.json": root_bytes,
        **package_bytes,
    }
    drift = [path for path, data in expected.items() if path.read_bytes() != data]
    if args.check:
        if drift:
            raise SystemExit(
                "authority graph needs rebuild: "
                + ", ".join(sorted(path.name for path in drift))
            )
        return
    for path, data in expected.items():
        path.write_bytes(data)


if __name__ == "__main__":
    main()
