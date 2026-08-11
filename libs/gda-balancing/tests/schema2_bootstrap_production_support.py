"""Consumer A adapters and mutable-fixture helpers for bootstrap conformance.

This module owns every import of the production admission/lifecycle code. The
independent Consumer B implementation lives in
``schema2_bootstrap_conformance_support`` and imports neither production
bootstrap nor the production authority cache.
"""

from copy import deepcopy
from typing import Any

import gda_balancing.domain.authority.admission as production_bootstrap

from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.graph import (
    LanguageBundleIndex,
    derive_language_index,
)
from gda_balancing.domain.authority.admission import admit_authorities
from schema2_bootstrap_conformance_support import (
    _bind_package_vector_set,
    _encoded,
    _identity,
    _package_vector_set,
)


def _authority_candidate() -> dict[str, Any]:
    """Copy the process-scoped admitted baseline once per isolation boundary."""
    context = packaged_authority_context()
    kernel, language_bundle = context.mutable_pair()
    admission = context.admission
    return {
        "kernel": kernel,
        "language_bundle": language_bundle,
        "admission": {
            "admitted": admission.admitted,
            "kernel_identity": admission.kernel_identity,
            "language_bundle_identity": admission.language_bundle_identity,
        },
    }


def _consumer_a(kernel: dict[str, Any], ldb: dict[str, Any]) -> dict[str, Any]:
    result = admit_authorities(kernel, ldb)
    return {
        "admitted": result.admitted,
        "kernel_identity": result.kernel_identity,
        "language_bundle_identity": result.language_bundle_identity,
        "law_ids": list(result.law_ids),
        "law_projections": list(result.law_projections),
        "rule_ids": list(result.rule_ids),
        "rule_projections": list(result.rule_projections),
        "diagnostic_projections": list(result.diagnostic_projections),
        "diagnostics": [
            (item.stage, item.code, item.subject) for item in result.diagnostics
        ],
        "truncated": result.truncated,
    }


def _refresh_package_closure_and_reidentify(ldb: LanguageBundleIndex) -> None:
    kernel = packaged_authority_context().kernel
    projections = kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]

    def path_values(root: Any, dotted: str) -> list[Any]:
        values = [root]
        for segment in dotted.split("."):
            selected: list[Any] = []
            for value in values:
                if not isinstance(value, dict) or segment not in value:
                    continue
                child = value[segment]
                selected.extend(child if isinstance(child, list) else [child])
            values = selected
        return values

    for package in ldb["language"]["packages"]:
        for entry, projection in zip(
            package["semantic_closure"], projections, strict=True
        ):
            definitions = path_values(ldb, entry["authority_path"])
            owners = path_values(package, projection["owners_path"])
            key_member = projection["key_member"]
            entry["definitions"] = deepcopy(
                [
                    definition
                    for definition in definitions
                    if (
                        definition.get(key_member)
                        if key_member is not None and isinstance(definition, dict)
                        else definition
                    )
                    in owners
                ]
            )
        _bind_package_vector_set(package, _package_vector_set(ldb, package))
    _reidentify_graph_root(ldb)


def _reidentify_graph_root(ldb: LanguageBundleIndex) -> None:
    graph_root = getattr(ldb, "root", None)
    if isinstance(graph_root, dict):
        packages = deepcopy(ldb["language"]["packages"])
        vector_sets_by_coordinate = {
            (vector_set["package_id"], vector_set["package_version"]): deepcopy(
                vector_set
            )
            for vector_set in ldb.package_conformance_vector_sets
        }
        vector_sets = []
        for package in packages:
            coordinate = (package["id"], package["version"])
            vector_set = vector_sets_by_coordinate.get(coordinate)
            if vector_set is None:
                vector_set = {
                    "artifact_kind": "package-conformance-vector-set",
                    "content_identity": "",
                    "package_id": package["id"],
                    "package_version": package["version"],
                    "vector_definitions": [],
                    "vectors": [],
                }
                _bind_package_vector_set(package, vector_set)
            vector_sets.append(vector_set)
        members = sorted(
            zip(packages, vector_sets, strict=True),
            key=lambda member: _encoded([member[0]["id"], member[0]["version"]]),
        )
        packages = [package for package, _vector_set in members]
        vector_sets = [vector_set for _package, vector_set in members]
        package_sizes = [len(_encoded(package)) for package in packages]
        vector_set_sizes = [len(_encoded(vector_set)) for vector_set in vector_sets]
        graph_root["resources"] = deepcopy(ldb["resources"])
        graph_root["package_descriptors"] = [
            {
                "artifact_kind": package["artifact_kind"],
                "byte_size": size,
                "content_identity": package["content_identity"],
                "id": package["id"],
                "version": package["version"],
            }
            for package, size in zip(packages, package_sizes, strict=True)
        ]
        graph_root["content_identity"] = _identity(
            "language-definition-bundle-v2", graph_root
        )
        ldb.root = deepcopy(graph_root)
        ldb.package_releases = packages
        ldb.package_conformance_vector_sets = vector_sets
        ldb.root_byte_size = len(_encoded(graph_root))
        ldb.package_byte_sizes = tuple(package_sizes)
        ldb.vector_set_byte_sizes = tuple(vector_set_sizes)
        kernel = packaged_authority_context().kernel
        rebuilt = derive_language_index(
            graph_root,
            packages,
            vector_sets,
            kernel["admission"]["required_language_members"],
            root_byte_size=ldb.root_byte_size,
            package_byte_sizes=package_sizes,
            vector_set_byte_sizes=vector_set_sizes,
            descriptor_order=kernel["meta_format"]["language_bundle"][
                "package_descriptor"
            ]["canonical_order"],
        )
        ldb.root = deepcopy(rebuilt.root)
        ldb.package_releases = deepcopy(rebuilt.package_releases)
        ldb.package_conformance_vector_sets = deepcopy(
            rebuilt.package_conformance_vector_sets
        )
        ldb.root_byte_size = rebuilt.root_byte_size
        ldb.package_byte_sizes = rebuilt.package_byte_sizes
        ldb.vector_set_byte_sizes = rebuilt.vector_set_byte_sizes
        ldb.clear()
        ldb.update(dict(rebuilt))
        return
    ldb["content_identity"] = _identity("language-definition-bundle-v2", ldb)


__all__ = [
    "_authority_candidate",
    "_consumer_a",
    "_refresh_package_closure_and_reidentify",
    "_reidentify_graph_root",
    "admit_authorities",
    "packaged_authority_context",
    "production_bootstrap",
]
