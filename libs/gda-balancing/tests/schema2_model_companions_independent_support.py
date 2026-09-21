"""Independent Model companions over the existing independent compiler output."""

from copy import deepcopy
import hashlib
from pathlib import Path

import jsonschema

from test_schema2_model_lowerer_conformance import (
    _reference_artifact,
    _reference_content_identity,
    _reference_lowering,
    _reference_semantic_artifacts,
)


def reference_model_producer():
    """Record the reference sources used to extend Model companion production.

    This provenance is not the external full-build freeze required by #878.
    """
    sources = [
        {
            "path": name,
            "sha256": hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest(),
        }
        for name in (
            "test_schema2_model_lowerer_conformance.py",
            "schema2_model_companions_independent_support.py",
        )
    ]
    identity = _reference_content_identity("reference-model-producer-v1", sources)
    return {"compiler": identity, "resolver": identity}


def reference_model_artifacts(checked, *, producer):
    """Derive complete companions; producer provenance is explicit input to receipts."""
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

    def identify(role, payload):
        return _reference_artifact(checked, role, payload)

    formulas = []
    for formula in sorted(rir["formulas"], key=lambda row: (row["module"], row["id"])):
        value = {
            name: deepcopy(formula[name])
            for name in (
                "module",
                "id",
                "identity",
                "parameters",
                "result",
                "body",
                "expression",
                "closure",
            )
        }
        value["evaluation_sites"] = [
            {
                "identity": binding["site"]["identity"],
                "binding_identity": binding["identity"],
                "context": deepcopy(binding["site"]["context"]),
                "operands": deepcopy(binding["arguments"]),
                "result": deepcopy(formula["result"]),
            }
            for binding in rir["formula_bindings"]
            if binding["formula"]["identity"] == formula["identity"]
        ]
        formulas.append(value)
    operations = []
    for row in sorted(
        rir["selected_semantics"]["operations"],
        key=lambda row: (row["package"], row["definition"]["id"]),
    ):
        definition = row["definition"]
        identity = _reference_content_identity(
            profile["formula_resolution"]["identity_domains"]["operation"],
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
                "rng_streams": sorted(
                    {
                        node["stream"]
                        for node in definition["body"]
                        if node["node"] == "draw"
                    }
                ),
                "outcomes": [
                    {name: outcome[name] for name in ("id", "kind", "state_policy")}
                    for outcome in definition.get("outcomes", [])
                ],
                "default_outcome": definition.get("default_outcome"),
                "formula_evaluation_sites": [
                    binding["site"]["identity"]
                    for binding in rir["formula_bindings"]
                    if binding["site"].get("kind") == "operation-slot"
                    and binding["site"].get("operation", {}).get("identity") == identity
                ],
            }
        )
        operations.append(value)
    result["model-explanation"] = identify(
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
            "formula_explanations": formulas,
            "operation_explanations": operations,
        },
    )
    result["capability-manifest"] = identify(
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
    source = {
        "source_identity": checked.source_identity,
        "kernel_identity": checked.kernel["content_identity"],
        "language_bundle_identity": checked.language_bundle["content_identity"],
    }
    result["resolution-receipt"] = identify(
        "resolution-receipt",
        {
            **source,
            "resolver": producer["resolver"],
            "resolution_profile": profile["id"],
            "package_lock_identity": lock["content_identity"],
            "diagnostics": [],
        },
    )
    result["build-receipt"] = identify(
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
    result["model-build-command-input"] = identify("model-build-command-input", source)
    return result


def reference_admits_model_artifacts(candidate, checked, *, producer):
    """Compare every supplied member with independent Source-derived facts."""
    try:
        expected = reference_model_artifacts(checked, producer=producer)
        roles = {value["artifact_kind"]: role for role, value in expected.items()}
        actual = {}
        for value in candidate.values():
            role = roles.get(value.get("artifact_kind"))
            if role is None or role in actual:
                return False
            actual[role] = value
        return actual == expected
    except (KeyError, ValueError, TypeError, StopIteration, jsonschema.ValidationError):
        return False
