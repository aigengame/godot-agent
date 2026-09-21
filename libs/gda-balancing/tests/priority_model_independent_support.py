"""Independent Model companions for the finite #878 priority witness."""

from copy import deepcopy
import hashlib
from pathlib import Path

import jsonschema

from test_schema2_model_lowerer_conformance import (
    _reference_artifact,
    _reference_content_identity,
    _reference_lowering,
    _reference_rir_semantic_projection,
    _reference_semantic_artifacts,
)


_PRIORITY_SOURCE_IDENTITIES = frozenset(
    {
        "sha256:264febcb46fd722429f9afe8c3fdd2707f1959a4f25c2d774b6e93b211e116b7",
        "sha256:f08d31f15f8c8a488216276f4b38d48de21b5dc3153a12e3870a28106c84d9a6",
    }
)
_MODEL_ROLES = {
    "build-receipt",
    "capability-manifest",
    "debug-map",
    "model-explanation",
    "package-lock",
    "resolution-receipt",
    "resolved-model",
    "rir-semantic-payload",
}


def reference_model_producer():
    """Identify the bounded Build B used by the original/renamed A/B matrix."""
    sources = [
        {
            "path": name,
            "sha256": hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest(),
        }
        for name in (
            "test_schema2_model_lowerer_conformance.py",
            "priority_model_independent_support.py",
        )
    ]
    identity = _reference_content_identity("reference-model-producer-v1", sources)
    return {"compiler": identity, "resolver": identity}


def _identify(checked, role, payload):
    return _reference_artifact(checked, role, payload)


def _model_explanation(checked, lock, rir, debug):
    if rir["formulas"] or rir["formula_bindings"] or rir["initialization_programs"]:
        raise ValueError("the fixed priority Source has no Formula lifecycle")
    language = checked.language_bundle["language"]
    lowering = _reference_lowering(language)
    profile = next(
        row
        for row in language["resolution_profiles"]
        if row["id"] == lowering["resolution_profile"]
    )
    operations = []
    for row in sorted(
        rir["selected_semantics"]["operations"],
        key=lambda item: (item["package"], item["definition"]["id"]),
    ):
        definition = row["definition"]
        if any(node["node"] == "draw" for node in definition["body"]):
            raise ValueError("the fixed priority Operations do not draw RNG")
        identity = _reference_content_identity(
            profile["extensions"]["standard.formula"]["identity_domains"]["operation"],
            {"package": row["package"], "id": definition["id"]},
        )
        value = {
            name: deepcopy(definition[name])
            for name in (
                "id",
                "operation_kind",
                "purity",
                "effects",
                "refusals",
                "resource_bounds",
            )
        }
        value.update(
            {
                "package": row["package"],
                "identity": identity,
                "control_nodes": sorted({node["node"] for node in definition["body"]}),
                "rng_streams": [],
                "outcomes": [
                    {name: outcome[name] for name in ("id", "kind", "state_policy")}
                    for outcome in definition.get("outcomes", [])
                ],
                "default_outcome": definition.get("default_outcome"),
                "formula_evaluation_sites": [],
            }
        )
        operations.append(value)
    return _identify(
        checked,
        "model-explanation",
        {
            "rir_identity": rir["content_identity"],
            "debug_map_identity": debug["content_identity"],
            "declaration_explanations": [
                {
                    name: deepcopy(row[name])
                    for name in ("resolved_symbol", "type_identity", "value_kind")
                }
                for row in rir["declarations"]
                if row.get("value_kind") == "nominal-structured"
            ],
            "formula_explanations": [],
            "operation_explanations": operations,
        },
    )


def _capability_manifest(checked, lock, rir, resolved):
    return _identify(
        checked,
        "capability-manifest",
        {
            "resolved_model_identity": resolved["content_identity"],
            "package_lock_identity": lock["content_identity"],
            "rir_identity": rir["content_identity"],
            "packages": [
                {name: row[name] for name in ("id", "content_identity")}
                for row in lock["packages"]
            ],
            **{
                name: deepcopy(lock[name])
                for name in (
                    "capability_bindings",
                    "types",
                    "components",
                    "conversions",
                    "operations",
                    "numeric_profiles",
                    "runtime_profiles",
                    "language_rules",
                )
            },
        },
    )


def reference_model_artifacts(checked, *, producer):
    """Derive complete companions; producer provenance is explicit input to receipts."""
    if (
        checked.source.get("manifest", {}).get("id") != "example.priority-window"
        or checked.source_identity not in _PRIORITY_SOURCE_IDENTITIES
    ):
        raise ValueError("only the two fixed priority Model Sources are supported")
    result = _reference_semantic_artifacts(checked)
    lock, rir, resolved, debug = (
        result[role]
        for role in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
            "debug-map",
        )
    )
    language = checked.language_bundle["language"]
    lowering = _reference_lowering(language)
    profile = next(
        row
        for row in language["resolution_profiles"]
        if row["id"] == lowering["resolution_profile"]
    )

    result["model-explanation"] = _model_explanation(checked, lock, rir, debug)
    result["capability-manifest"] = _capability_manifest(checked, lock, rir, resolved)
    source = {
        "source_identity": checked.source_identity,
        "kernel_identity": checked.kernel["content_identity"],
        "language_bundle_identity": checked.language_bundle["content_identity"],
    }
    result["resolution-receipt"] = _identify(
        checked,
        "resolution-receipt",
        {
            **source,
            "resolver": producer["resolver"],
            "resolution_profile": profile["id"],
            "package_lock_identity": lock["content_identity"],
            "diagnostics": [],
        },
    )
    result["build-receipt"] = _identify(
        checked,
        "build-receipt",
        {
            **source,
            "compiler": producer["compiler"],
            **{
                field: result[role]["content_identity"]
                for field, role in (
                    ("package_lock_identity", "package-lock"),
                    ("rir_identity", "rir-semantic-payload"),
                    ("resolved_model_identity", "resolved-model"),
                    ("capability_manifest_identity", "capability-manifest"),
                    ("debug_map_identity", "debug-map"),
                    ("model_explanation_identity", "model-explanation"),
                    ("resolution_receipt_identity", "resolution-receipt"),
                )
            },
        },
    )
    return result


def reference_admits_model_artifacts(
    candidate, checked, *, producer, expected_semantic_artifacts
):
    """Admit supplied members from fixed facts without rebuilding the Source."""
    try:
        if (
            checked.source_identity not in _PRIORITY_SOURCE_IDENTITIES
            or set(candidate) != _MODEL_ROLES
        ):
            return False
        for role, artifact in candidate.items():
            payload = {
                key: value
                for key, value in artifact.items()
                if key
                not in {
                    "artifact_kind",
                    "artifact_version",
                    "wire_schema_identity",
                    "content_identity",
                }
            }
            if _identify(checked, role, payload) != artifact:
                return False
        semantic_roles = (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
            "debug-map",
        )
        if any(
            candidate[role] != expected_semantic_artifacts[role]
            for role in semantic_roles
        ):
            return False
        lock = candidate["package-lock"]
        rir = candidate["rir-semantic-payload"]
        resolved = candidate["resolved-model"]
        debug = candidate["debug-map"]
        if lock["semantic_identity"] != _reference_content_identity(
            "package-lock-selected-semantics-v2", lock["selected_semantics"]
        ):
            return False
        semantic_domain, semantic_projection = _reference_rir_semantic_projection(
            checked.language_bundle, rir
        )
        if rir["semantic_identity"] != _reference_content_identity(
            semantic_domain, semantic_projection
        ):
            return False
        if candidate["model-explanation"] != _model_explanation(
            checked, lock, rir, debug
        ) or candidate["capability-manifest"] != _capability_manifest(
            checked, lock, rir, resolved
        ):
            return False
        source = {
            "source_identity": checked.source_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
        }
        language = checked.language_bundle["language"]
        lowering = _reference_lowering(language)
        profile = next(
            row
            for row in language["resolution_profiles"]
            if row["id"] == lowering["resolution_profile"]
        )
        resolution_receipt = _identify(
            checked,
            "resolution-receipt",
            {
                **source,
                "resolver": producer["resolver"],
                "resolution_profile": profile["id"],
                "package_lock_identity": lock["content_identity"],
                "diagnostics": [],
            },
        )
        if candidate["resolution-receipt"] != resolution_receipt:
            return False
        return candidate["build-receipt"] == _identify(
            checked,
            "build-receipt",
            {
                **source,
                "compiler": producer["compiler"],
                **{
                    field: candidate[role]["content_identity"]
                    for field, role in (
                        ("package_lock_identity", "package-lock"),
                        ("rir_identity", "rir-semantic-payload"),
                        ("resolved_model_identity", "resolved-model"),
                        ("capability_manifest_identity", "capability-manifest"),
                        ("debug_map_identity", "debug-map"),
                        ("model_explanation_identity", "model-explanation"),
                        ("resolution_receipt_identity", "resolution-receipt"),
                    )
                },
            },
        )
    except (KeyError, ValueError, TypeError, StopIteration, jsonschema.ValidationError):
        return False
