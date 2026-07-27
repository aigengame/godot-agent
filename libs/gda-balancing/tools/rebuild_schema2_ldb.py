#!/usr/bin/env python3
"""Rebuild or verify the checked-in sealed Schema 2.0 LDB graph."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from gda_balancing.schema2.canonical import JsonValue, canonical_bytes, content_identity


_PACKAGE_DOMAIN = "domain-package-release-v2"
_LDB_DOMAIN = "language-definition-bundle-v2"


def _identity(domain: str, artifact: dict[str, Any]) -> str:
    body = {key: value for key, value in artifact.items() if key != "content_identity"}
    return content_identity(domain, cast(JsonValue, body))


def _semantic_identity(package: dict[str, Any], domain: str) -> str:
    runtime_paths = package.get("runtime_semantic_paths")
    closure = package.get("semantic_closure")
    if not isinstance(runtime_paths, list) or not isinstance(closure, list):
        raise ValueError(f"{package.get('id', '<unknown>')} has no semantic closure")
    selected = [
        item
        for item in closure
        if isinstance(item, dict) and item.get("authority_path") in set(runtime_paths)
    ]
    return content_identity(domain, cast(JsonValue, selected))


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
    declared_paths = {
        package_dir / f"{item['id']}@{item['version']}.json"
        for item in descriptors
        if isinstance(item, dict)
    }
    shipped_paths = set(package_dir.glob("*.json"))
    if declared_paths != shipped_paths:
        missing = sorted(str(path.name) for path in declared_paths - shipped_paths)
        extra = sorted(str(path.name) for path in shipped_paths - declared_paths)
        raise ValueError(f"package membership drift: missing={missing}, extra={extra}")

    semantic_domain = kernel["meta_format"]["package_release"]["semantic_closure"][
        "domain"
    ]
    packages: list[dict[str, Any]] = []
    for path in declared_paths:
        package = json.loads(path.read_text())
        package["semantic_identity"] = _semantic_identity(package, semantic_domain)
        package["content_identity"] = _identity(_PACKAGE_DOMAIN, package)
        packages.append(package)
    packages.sort(key=lambda item: (item["id"], item["version"]))

    package_bytes: dict[Path, bytes] = {}
    rebuilt_descriptors: list[dict[str, Any]] = []
    for package in packages:
        data = canonical_bytes(cast(JsonValue, package))
        path = package_dir / f"{package['id']}@{package['version']}.json"
        package_bytes[path] = data
        rebuilt_descriptors.append(
            {
                "artifact_kind": package["artifact_kind"],
                "byte_size": len(data),
                "content_identity": package["content_identity"],
                "id": package["id"],
                "version": package["version"],
            }
        )

    rebuilt_root = deepcopy(root)
    rebuilt_root["kernel_identity"] = kernel["content_identity"]
    rebuilt_root["package_descriptors"] = rebuilt_descriptors
    rebuilt_root["content_identity"] = _identity(_LDB_DOMAIN, rebuilt_root)
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
    drift = [
        path for path, data in expected.items() if path.read_bytes() != data
    ]
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
